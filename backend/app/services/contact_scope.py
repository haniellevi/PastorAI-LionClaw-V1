"""Canonical row visibility predicates for contacts and dependent services."""

from __future__ import annotations

import uuid

from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaMembro, Conversation, Pessoa
from app.deps import CurrentUser, resolve_actor_pessoa_id


# Papéis com visão tenant-wide de Pessoas. ``has_any_role`` preserva a união dos
# papéis e concede acesso implícito ao admin, mesmo sem listá-lo aqui.
CONTACTS_TENANT_WIDE_ROLES = [
    "pastor",
    "lider_g12",
    "lider_consol",
]

# Somente papéis que realmente operam uma caixa de entrada restrita recebem a
# exceção de Pessoa por conversa atribuída. ``membro`` e ``lider_mult`` não a
# herdam apenas porque uma Conversation foi associada artificialmente a eles.
CONTACTS_RESTRICTED_INBOX_ROLES = {"lider_celula", "operador"}


def _contact_scope_conditions(
    db: Session,
    current_user: CurrentUser,
    *,
    include_assigned_conversation: bool = False,
):
    """Return SQL predicates for the caller's row-level Pessoas visibility.

    Tenant-wide roles retain the complete tenant view. A cell leader sees their
    own Pessoa plus Pessoas with an active canonical membership in an active
    cell they lead. Restricted inbox roles may additionally see Pessoas of
    tenant Conversations currently assigned to the caller. Other restricted
    roles see only their own Pessoa.

    Every branch carries explicit tenant predicates in addition to RLS. When a
    restricted caller has no linked Pessoa (and no detail exception applies),
    ``false()`` makes count and row queries return an empty result fail-closed.
    """

    igreja_id = uuid.UUID(current_user.igreja_id)
    tenant_condition = Pessoa.igreja_id == igreja_id

    if current_user.has_any_role(CONTACTS_TENANT_WIDE_ROLES):
        return (tenant_condition,)

    actor_pessoa_id = resolve_actor_pessoa_id(db, current_user)
    actor_uuid = uuid.UUID(actor_pessoa_id) if actor_pessoa_id else None
    visible = []

    if actor_uuid is not None:
        visible.append(Pessoa.id == actor_uuid)

        if "lider_celula" in current_user.roles:
            active_member_of_led_cell = (
                select(CelulaMembro.id)
                .join(Celula, Celula.id == CelulaMembro.celula_id)
                .where(
                    CelulaMembro.igreja_id == igreja_id,
                    CelulaMembro.pessoa_id == Pessoa.id,
                    CelulaMembro.ativo.is_(True),
                    Celula.igreja_id == igreja_id,
                    Celula.lider_id == actor_uuid,
                    Celula.ativo.is_(True),
                )
                .correlate(Pessoa)
                .exists()
            )
            visible.append(active_member_of_led_cell)

    if (
        include_assigned_conversation
        and current_user.roles & CONTACTS_RESTRICTED_INBOX_ROLES
    ):
        assigned_conversation = (
            select(Conversation.id)
            .where(
                Conversation.igreja_id == igreja_id,
                Conversation.pessoa_id == Pessoa.id,
                Conversation.assumido_por == uuid.UUID(current_user.app_user_id),
            )
            .correlate(Pessoa)
            .exists()
        )
        visible.append(assigned_conversation)

    return (tenant_condition, or_(*visible) if visible else false())
