"""Aviso síncrono de confirmação de evento à equipe interna (EVT-7).

Quando um evento é confirmado (POST /events/{id}/confirm) e a flag
``AGENDA_NOTIFY_ENABLED`` está ligada, a Agenda avisa os destinatários configurados
da igreja pelo número oficial via Evolution.

Fonte do telefone (EVT-7 PR2): a config explícita ``agenda_alert_recipients``
(opt-in, por igreja, independente de papel e de ``AppUser.pessoa_id``). Só os
destinatários ``ativo=true`` recebem. Sem destinatário configurado ou sem número
oficial conectado, ninguém é notificado (não se inventa destinatário). Ver
docs/design/AGENDA-EVENTOS-EVT7-destinatarios-alerta.md.

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
from app.db.models import AgendaAlertRecipient, Event, WhatsappConnection
from app.services.evolution import EvolutionClient, EvolutionError

logger = logging.getLogger("pastorai.event_notify")

STATUS_CONFIRMADO = "confirmado"


def _alert_phones(db: Session, igreja_id: uuid.UUID) -> list[str]:
    """Telefones dos destinatários de alerta ATIVOS da igreja (EVT-7 PR2).

    Lê ``agenda_alert_recipients`` (config explícita, opt-in) filtrando
    ``ativo=true``. Sem destinatário ativo → lista vazia (não inventa
    destinatário). Deduplica preservando a ordem; ignora vazios.
    """
    rows = db.execute(
        select(AgendaAlertRecipient.telefone).where(
            AgendaAlertRecipient.igreja_id == igreja_id,
            AgendaAlertRecipient.ativo.is_(True),
        )
    ).scalars().all()
    phones: list[str] = []
    for telefone in rows:
        if telefone and telefone not in phones:
            phones.append(telefone)
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
    phones = _alert_phones(db, igreja_id)
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
