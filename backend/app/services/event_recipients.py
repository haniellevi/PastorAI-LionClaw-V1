"""Resolve a configuração de notificação de um evento em destinatários reais
(EVT-8 PR2) — camada de acesso ao banco; a lógica pura fica em
``app/domain/event_notifications.py``.

Combina a **seleção individual** (``event_notify_targets``, validada no PR1) com
os **públicos coletivos** de ``Event.publico_alvo`` (``toda_igreja``/``pastores``/
``g12_pastoral``/``lideres_celula``, D1), aplica opt-out (LGPD) e deduplica.

Tudo tenant-scoped por ``igreja_id`` explícito no WHERE (defesa em profundidade
além da RLS). **NÃO envia nada** e **não** toca ``notificacao_enviada_em``: o
disparo real (WhatsApp/Evolution) e o cron são EVT-9. Espelha a delimitação do
PR1: ``agenda_alert_recipients`` (EVT-7, aviso interno da equipe) NÃO é fonte
aqui.

Fonte de verdade dos papéis/derivações:
  - ``pastores`` = ``user_roles.papel = 'pastor'`` (via ``app_users.pessoa_id``).
  - ``g12_pastoral`` = ``user_roles.papel = 'lider_g12'`` (D2).
  - ``lideres_celula`` = ``celulas.lider_id`` de célula ``ativo=true`` (D5) —
    NUNCA ``celula_membro.papel='lider'``.
  - ``toda_igreja`` = pessoas da igreja, excluindo CSIM (``sem_interesse=true``,
    fora da visão ministerial).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, Event, EventNotifyTarget, Pessoa, UserRole
from app.domain.event_notifications import (
    Candidate,
    ResolvedAudience,
    resolve_recipients,
)


def _as_uuid(value: object) -> uuid.UUID:
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _individual_candidates(
    db: Session, event_id: uuid.UUID, igreja_id: uuid.UUID
) -> list[Candidate]:
    """Candidatos da seleção individual (``event_notify_targets`` do PR1).

    Prefere ``pessoa_id``: resolve a ``Pessoa`` do tenant para pegar telefone +
    opt-out. Sem pessoa vinculada, usa o telefone canônico já persistido (que o
    PR1 validou contra ``conversations`` — nunca digitação livre).
    """
    targets = db.execute(
        select(EventNotifyTarget).where(
            EventNotifyTarget.event_id == event_id,
            EventNotifyTarget.igreja_id == igreja_id,
        )
    ).scalars().all()

    pessoa_ids = [t.pessoa_id for t in targets if t.pessoa_id is not None]
    pessoa_map: dict[uuid.UUID, Pessoa] = {}
    if pessoa_ids:
        rows = db.execute(
            select(Pessoa).where(
                Pessoa.id.in_(pessoa_ids),
                Pessoa.igreja_id == igreja_id,
            )
        ).scalars().all()
        pessoa_map = {p.id: p for p in rows}

    candidates: list[Candidate] = []
    for t in targets:
        if t.pessoa_id is not None:
            pessoa = pessoa_map.get(t.pessoa_id)
            if pessoa is None:
                # Pessoa removida/de outro tenant — não inventa destinatário.
                continue
            candidates.append(
                Candidate(
                    pessoa_id=str(pessoa.id),
                    telefone=pessoa.telefone,
                    optout=pessoa.optout,
                )
            )
        else:
            candidates.append(
                Candidate(pessoa_id=None, telefone=t.telefone, optout=False)
            )
    return candidates


def _candidates_por_papel(
    db: Session, igreja_id: uuid.UUID, papel: str
) -> list[Candidate]:
    """Pessoas com um papel ministerial no painel (``user_roles.papel``).

    ``app_users.pessoa_id`` é nullable: um usuário do papel sem pessoa vinculada
    não tem telefone e simplesmente não vira candidato (limitação conhecida).
    """
    rows = db.execute(
        select(Pessoa)
        .join(AppUser, AppUser.pessoa_id == Pessoa.id)
        .join(UserRole, UserRole.user_id == AppUser.id)
        .where(
            UserRole.papel == papel,
            UserRole.igreja_id == igreja_id,
            Pessoa.igreja_id == igreja_id,
        )
    ).scalars().all()
    return [Candidate(str(p.id), p.telefone, p.optout) for p in rows]


def _candidates_lideres_celula(
    db: Session, igreja_id: uuid.UUID
) -> list[Candidate]:
    """Líderes de célula = ``celulas.lider_id`` de célula ATIVA (D5).

    Fonte canônica é ``Celula.lider_id`` — NÃO ``celula_membro.papel='lider'``.
    """
    rows = db.execute(
        select(Pessoa)
        .join(Celula, Celula.lider_id == Pessoa.id)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.ativo.is_(True),
            Pessoa.igreja_id == igreja_id,
        )
    ).scalars().all()
    return [Candidate(str(p.id), p.telefone, p.optout) for p in rows]


def _candidates_toda_igreja(
    db: Session, igreja_id: uuid.UUID
) -> list[Candidate]:
    """Toda a igreja, exceto CSIM (``sem_interesse=true``, fora da visão).

    CSIM foi tirado da Jornada G12 (contato sem interesse ministerial); notificá-lo
    de eventos não faz sentido no domínio atual. Opt-out é aplicado depois, no
    domínio puro.
    """
    rows = db.execute(
        select(Pessoa).where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.sem_interesse.is_(False),
        )
    ).scalars().all()
    return [Candidate(str(p.id), p.telefone, p.optout) for p in rows]


def _coletivo_candidates(
    db: Session, igreja_id: uuid.UUID, publico_alvo: list[str] | None
) -> list[Candidate]:
    """Materializa os candidatos coletivos só dos públicos pedidos no evento."""
    publico = set(publico_alvo or [])
    candidates: list[Candidate] = []
    if "toda_igreja" in publico:
        candidates += _candidates_toda_igreja(db, igreja_id)
    if "pastores" in publico:
        candidates += _candidates_por_papel(db, igreja_id, "pastor")
    if "g12_pastoral" in publico:
        candidates += _candidates_por_papel(db, igreja_id, "lider_g12")
    if "lideres_celula" in publico:
        candidates += _candidates_lideres_celula(db, igreja_id)
    return candidates


def resolve_event_notification_recipients(
    db: Session, event_id: uuid.UUID | str, igreja_id: uuid.UUID | str
) -> ResolvedAudience:
    """Resolve os destinatários da notificação de um evento (EVT-8 PR2).

    Tenant-scoped. Retorna a audiência resolvida (entregáveis + telemetria de
    opt-out/sem-telefone). Evento inexistente/de outro tenant → audiência vazia.
    **Não envia nada.**
    """
    event_uuid = _as_uuid(event_id)
    igreja_uuid = _as_uuid(igreja_id)

    event = db.execute(
        select(Event).where(
            Event.id == event_uuid,
            Event.igreja_id == igreja_uuid,
        )
    ).scalar_one_or_none()
    if event is None:
        return ResolvedAudience(recipients=[], ignored_optout=0, skipped_sem_telefone=0)

    individual = _individual_candidates(db, event_uuid, igreja_uuid)
    coletivo = _coletivo_candidates(db, igreja_uuid, event.publico_alvo)
    return resolve_recipients(individual, coletivo)
