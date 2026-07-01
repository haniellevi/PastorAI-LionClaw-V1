"""Aviso síncrono de confirmação de evento à equipe interna (EVT-7 PR1).

Quando um evento é confirmado (POST /events/{id}/confirm) e a flag
``AGENDA_NOTIFY_ENABLED`` está ligada, a Agenda avisa a coordenação da igreja
(papéis ``pastor`` / ``lider_g12``) pelo número oficial via Evolution.

Fonte do telefone (mesma do motor de SLA, `sla_engine.py`): usuários com papel de
coordenação → ``AppUser.pessoa_id`` → ``Pessoa.telefone``. É só a EQUIPE (por
papel); nunca membros/visitantes. Sem papéis/telefone ou sem número oficial
conectado, ninguém é notificado (não se inventa destinatário).

O envio passa por ``EvolutionClient.send_text``, que já respeita o ``outbound_guard``
(B2): fora de produção o envio é SIMULADO (retorna True sem tocar a rede). Aqui
NÃO se contorna o guard.

Idempotência por evento via ``events.notificado_em``: uma segunda chamada não
reenvia. Qualquer falha de envio é engolida (logada) — o aviso é best-effort e
NUNCA desfaz a confirmação; ``notificado_em`` só é marcado quando ≥1 envio ocorre.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import AppUser, Event, Pessoa, UserRole, WhatsappConnection
from app.services.evolution import EvolutionClient, EvolutionError

logger = logging.getLogger("pastorai.event_notify")

# Papéis que recebem o aviso interno — mesma coordenação do motor de SLA.
NOTIFY_ROLES: frozenset[str] = frozenset({"pastor", "lider_g12"})

STATUS_CONFIRMADO = "confirmado"


def _team_phones(db: Session, igreja_id: uuid.UUID) -> list[str]:
    """Telefones da equipe interna (coordenação) da igreja.

    Usuários com papel em ``NOTIFY_ROLES`` → ``AppUser.pessoa_id`` →
    ``Pessoa.telefone``. Só equipe, nunca membros/visitantes. Sem papéis ou sem
    telefone conhecido → lista vazia (não inventa destinatário).
    """
    user_ids = db.execute(
        select(UserRole.user_id).where(
            UserRole.igreja_id == igreja_id,
            UserRole.papel.in_(NOTIFY_ROLES),
        )
    ).scalars().all()
    phones: list[str] = []
    for uid in set(user_ids):
        app_user = db.get(AppUser, uid)
        if app_user is None or app_user.pessoa_id is None:
            continue
        pessoa = db.get(Pessoa, app_user.pessoa_id)
        if pessoa and pessoa.telefone:
            phones.append(pessoa.telefone)
    return phones


def _instance(db: Session, igreja_id: uuid.UUID) -> str | None:
    """Instância do número oficial da igreja (remetente), ou None se não conectado."""
    conn = db.execute(
        select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
    ).scalar_one_or_none()
    return conn.instance if conn else None


def _message(event: Event) -> str:
    """Mensagem simples, sem dado sensível: título + quando + CTA para a Agenda."""
    quando = event.data.isoformat() if event.data else "sem data"
    if event.hora:
        quando = f"{quando} {event.hora}"
    return (
        f"Evento confirmado: {event.titulo} em {quando}. "
        "Abra a Agenda para revisar."
    )


def notify_event_confirmed(
    db: Session,
    event: Event,
    *,
    settings: Settings | None = None,
    evolution: EvolutionClient | None = None,
) -> bool:
    """Avisa a equipe interna que um evento foi confirmado (best-effort, idempotente).

    Só age com ``AGENDA_NOTIFY_ENABLED`` ligada, evento já ``confirmado`` e ainda
    não notificado (``notificado_em is None``). Um evento ``a_confirmar`` (ainda não
    confirmado) NÃO dispara envio. Envia pelo número oficial via
    ``EvolutionClient.send_text`` (respeita o outbound_guard). Marca
    ``notificado_em`` quando ≥1 envio ocorre. Retorna True se notificou.

    Falhas são engolidas (logadas) para não desfazer a confirmação — o caller
    ainda deve blindar contra erros inesperados de DB.
    """
    settings = settings or get_settings()
    if not settings.agenda_notify_enabled:
        return False
    if event.status != STATUS_CONFIRMADO or event.notificado_em is not None:
        return False

    igreja_id = event.igreja_id
    if not isinstance(igreja_id, uuid.UUID):
        igreja_id = uuid.UUID(str(igreja_id))

    instance = _instance(db, igreja_id)
    phones = _team_phones(db, igreja_id)
    if not instance or not phones:
        logger.info("Agenda notify: sem instância/destinatário; nada enviado")
        return False

    client = evolution or EvolutionClient(settings)
    texto = _message(event)
    sent = 0
    for phone in phones:
        try:
            client.send_text(instance, phone, texto)
            sent += 1
        except EvolutionError:
            logger.warning("Agenda notify: falha ao enviar aviso de evento")

    if not sent:
        return False

    event.notificado_em = dt.datetime.now(dt.timezone.utc)
    db.flush()
    db.commit()
    return True
