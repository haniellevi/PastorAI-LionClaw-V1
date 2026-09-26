"""Atomic tenant deletion with durable, retryable external cleanup."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    ConsentRecord,
    Conversation,
    Igreja,
    Message,
    PasswordResetToken,
    Pessoa,
    PlatformAdmin,
    PlatformAuditLog,
    Subscription,
    UserRole,
    WhatsappConnection,
)
from app.services.asaas import (
    AsaasClient,
    AsaasOwnershipError,
    is_pastorai_external_reference,
    is_valid_subscription_id,
)
from app.services.clerk import ClerkClient, is_valid_clerk_user_id
from app.services.evolution import EvolutionClient
from app.services.storage import (
    StoragePathError,
    SupabaseStorage,
    tenant_owned_paths,
)

logger = logging.getLogger("pastorai.tenant_deletion")

_PENDING = "tenant_deletion.cleanup_pending"
_DONE = "tenant_deletion.cleanup_done"
_RETRY = "tenant_deletion.cleanup_retry"
_REJECTED = "tenant_deletion.cleanup_rejected"
_CLAIMED = "tenant_deletion.cleanup_claimed"
_LEASE_RENEWED = "tenant_deletion.cleanup_lease_renewed"
_FENCED = "tenant_deletion.cleanup_fenced"
_LOCAL_DELETED = "tenant_deletion.local_deleted"
_LEGACY_DELETED = "excluir"
_TASK_KINDS = {
    "clerk_user",
    "evolution_instance",
    "asaas_subscription",
    "storage_media",
    "storage_logo",
}
_PRE_DETACH_DELETE_MODELS = (ConsentRecord, Message, Conversation, UserRole)
_E4B_SCHEMA = "public"
_CONSENT_LEDGER_TABLE = "consentimento_finalidade_evento"
_CLEANUP_LEASE_DURATION = timedelta(minutes=5)


class TenantDeletionError(RuntimeError):
    """Base error for a local tenant-deletion transition."""


class TenantDeletionNotFound(TenantDeletionError):
    """No tenant and no durable deletion record exists for the requested id."""


class TenantDeletionBlocked(TenantDeletionError):
    """An immutable tenant relation makes a complete deletion unsafe."""


class E4bPopulatedError(TenantDeletionBlocked):
    """A protected reset relation still contains rows."""

    code = "BLOCKED_E4B_POPULATED"

    def __init__(self, table_counts: dict[str, int]) -> None:
        self.table_counts = dict(sorted(table_counts.items()))
        super().__init__(self.code)


class TenantResetPermissionError(TenantDeletionError):
    """The current database role cannot prove a complete cross-tenant reset."""


class CleanupRejected(TenantDeletionError):
    """A durable cleanup target is not safe to send to an external provider."""


class CleanupDeferred(TenantDeletionError):
    """A provider gate produced no remote effect; leave the task pending."""


class CleanupClaimLost(TenantDeletionError):
    """A worker no longer owns the durable lease before a provider call."""


@dataclass(frozen=True)
class TenantDeletionActor:
    app_user_id: uuid.UUID | None
    email: str | None
    execution_host: str | None = None


@dataclass(frozen=True)
class CleanupTask:
    task_id: uuid.UUID
    igreja_id: uuid.UUID
    kind: str
    payload: dict[str, object]


@dataclass(frozen=True)
class CleanupLease:
    task_id: uuid.UUID
    token: uuid.UUID
    expires_at: datetime


@dataclass(frozen=True)
class TenantDeletionResult:
    igreja_id: uuid.UUID
    deleted_now: bool
    pending_tasks: tuple[CleanupTask, ...]


@dataclass(frozen=True)
class CleanupOutcome:
    task_id: uuid.UUID
    status: str


@dataclass(frozen=True)
class CleanupRejection:
    igreja_id: uuid.UUID
    task_id: uuid.UUID | None
    kind: str


@dataclass(frozen=True)
class CleanupDrainState:
    pending_tasks: tuple[CleanupTask, ...]
    rejected_tasks: tuple[CleanupRejection, ...]


@dataclass(frozen=True)
class TenantResetCounts:
    igrejas: int
    app_users: int
    pessoas: int
    subscriptions: int
    platform_admins: int
    platform_audit_events: int


@dataclass(frozen=True)
class TenantResetResult:
    igrejas_deleted: int
    pending_tasks: int


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _reset_e4b_table_names(session: Session) -> tuple[str, ...]:
    rows = session.execute(
        text(
            "select c.relname "
            "from pg_catalog.pg_class c "
            "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = :schema "
            "and c.relkind in ('r', 'p') "
            "and c.relname ~ '^e4b_' "
            "order by c.relname"
        ),
        {"schema": _E4B_SCHEMA},
    ).scalars().all()
    return tuple(str(name) for name in rows)


def _table_exists(session: Session, table: str) -> bool:
    return bool(
        session.execute(
            text(
                "select exists ("
                "select 1 from pg_catalog.pg_class c "
                "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = :schema and c.relname = :table "
                "and c.relkind in ('r', 'p')"
                ")"
            ),
            {"schema": _E4B_SCHEMA, "table": table},
        ).scalar_one()
    )


def _reset_protected_table_names(session: Session) -> tuple[str, ...]:
    tables = set(_reset_e4b_table_names(session))
    if _table_exists(session, _CONSENT_LEDGER_TABLE):
        tables.add(_CONSENT_LEDGER_TABLE)
    return tuple(sorted(tables))


def _reset_e4b_counts(session: Session, *, lock_tables: bool) -> dict[str, int]:
    tables = _reset_protected_table_names(session)
    schema = _quote_identifier(_E4B_SCHEMA)
    if lock_tables:
        for table in tables:
            session.execute(
                text(
                    f"LOCK TABLE {schema}.{_quote_identifier(table)} "
                    "IN SHARE ROW EXCLUSIVE MODE"
                )
            )
    return {
        table: int(
            session.execute(
                text(
                    f"select count(*) from {schema}.{_quote_identifier(table)}"
                )
            ).scalar_one()
        )
        for table in tables
    }


def _assert_reset_e4b_empty(session: Session, *, lock_tables: bool = False) -> None:
    populated = {
        table: count
        for table, count in _reset_e4b_counts(session, lock_tables=lock_tables).items()
        if count
    }
    if populated:
        raise E4bPopulatedError(populated)


def _audit(
    session: Session,
    actor: TenantDeletionActor,
    action: str,
    igreja_id: uuid.UUID,
    igreja_name: str | None,
    detail: dict[str, object] | None = None,
) -> None:
    audit_detail = dict(detail) if detail is not None else None
    if actor.execution_host is not None:
        audit_detail = audit_detail or {}
        audit_detail["execution_host"] = actor.execution_host
    session.add(
        PlatformAuditLog(
            actor_id=actor.app_user_id,
            actor_email=actor.email,
            acao=action,
            alvo_tipo="igreja",
            alvo_id=igreja_id,
            alvo_nome=igreja_name,
            detalhe=audit_detail,
        )
    )


def _task_detail(task: CleanupTask) -> dict[str, object]:
    return {
        "version": 1,
        "task_id": str(task.task_id),
        "kind": task.kind,
        "payload": task.payload,
    }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _lease_detail(task: CleanupTask, lease: CleanupLease) -> dict[str, object]:
    detail = _task_detail(task)
    detail["lease_token"] = str(lease.token)
    detail["lease_expires_at"] = lease.expires_at.isoformat()
    return detail


def _lease_from_event(event: PlatformAuditLog) -> CleanupLease:
    detail = event.detalhe
    if not isinstance(detail, dict):
        raise CleanupRejected("Reserva de limpeza inválida")
    raw_task_id = detail.get("task_id")
    raw_token = detail.get("lease_token")
    raw_expiration = detail.get("lease_expires_at")
    if not all(isinstance(value, str) and value for value in (raw_task_id, raw_token, raw_expiration)):
        raise CleanupRejected("Reserva de limpeza inválida")
    try:
        task_id = uuid.UUID(raw_task_id)
        token = uuid.UUID(raw_token)
        expires_at = datetime.fromisoformat(raw_expiration)
    except (TypeError, ValueError) as exc:
        raise CleanupRejected("Reserva de limpeza inválida") from exc
    if expires_at.tzinfo is None:
        raise CleanupRejected("Reserva de limpeza inválida")
    return CleanupLease(task_id, token, expires_at.astimezone(timezone.utc))


def _task_audit_events(session: Session, task: CleanupTask) -> list[PlatformAuditLog]:
    return list(
        session.execute(
            select(PlatformAuditLog)
            .where(
                PlatformAuditLog.alvo_tipo == "igreja",
                PlatformAuditLog.alvo_id == task.igreja_id,
                PlatformAuditLog.detalhe["task_id"].as_string() == str(task.task_id),
            )
            .order_by(PlatformAuditLog.created_at, PlatformAuditLog.id)
        )
        .scalars()
        .all()
    )


def _lock_cleanup_manifest(session: Session, task: CleanupTask) -> bool:
    manifest_id = session.execute(
        select(PlatformAuditLog.id)
        .where(
            PlatformAuditLog.alvo_tipo == "igreja",
            PlatformAuditLog.alvo_id == task.igreja_id,
            PlatformAuditLog.acao == _PENDING,
            PlatformAuditLog.detalhe["task_id"].as_string() == str(task.task_id),
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    return manifest_id is not None


def _task_is_terminal(events: list[PlatformAuditLog]) -> bool:
    return any(event.acao in {_DONE, _REJECTED} for event in events)


def _active_cleanup_lease(events: list[PlatformAuditLog]) -> CleanupLease | None:
    lease: CleanupLease | None = None
    for event in events:
        if event.acao in {_CLAIMED, _LEASE_RENEWED}:
            lease = _lease_from_event(event)
        elif event.acao == _RETRY:
            lease = None
    return lease


def _new_task(
    session: Session,
    actor: TenantDeletionActor,
    igreja: Igreja,
    kind: str,
    payload: dict[str, object],
) -> CleanupTask:
    task = CleanupTask(
        task_id=uuid.uuid4(), igreja_id=igreja.id, kind=kind, payload=payload
    )
    _audit(session, actor, _PENDING, igreja.id, igreja.nome, _task_detail(task))
    return task


def _rejected_target(
    session: Session,
    actor: TenantDeletionActor,
    igreja: Igreja,
    kind: str,
    reason: str,
) -> None:
    _audit(
        session,
        actor,
        _REJECTED,
        igreja.id,
        igreja.nome,
        {"version": 1, "kind": kind, "reason": reason},
    )


def _read_audit_events(session: Session, igreja_id: uuid.UUID) -> list[PlatformAuditLog]:
    return list(
        session.execute(
            select(PlatformAuditLog)
            .where(
                PlatformAuditLog.alvo_tipo == "igreja",
                PlatformAuditLog.alvo_id == igreja_id,
            )
            .order_by(PlatformAuditLog.created_at, PlatformAuditLog.id)
        )
        .scalars()
        .all()
    )


def _task_from_event(event: PlatformAuditLog) -> CleanupTask | None:
    detail = event.detalhe
    if not isinstance(detail, dict):
        return None
    raw_task_id = detail.get("task_id")
    kind = detail.get("kind")
    payload = detail.get("payload")
    if not isinstance(raw_task_id, str) or kind not in _TASK_KINDS or not isinstance(payload, dict):
        return None
    try:
        task_id = uuid.UUID(raw_task_id)
    except ValueError:
        return None
    if event.alvo_id is None:
        return None
    return CleanupTask(task_id=task_id, igreja_id=event.alvo_id, kind=kind, payload=payload)


def _cleanup_task_states(
    events: list[PlatformAuditLog],
) -> tuple[tuple[CleanupTask, ...], tuple[CleanupRejection, ...]]:
    tasks: dict[uuid.UUID, CleanupTask] = {}
    terminal: set[uuid.UUID] = set()
    rejections: list[CleanupRejection] = []
    for event in events:
        task = _task_from_event(event)
        if task is not None and event.acao == _PENDING:
            tasks[task.task_id] = task
        elif task is not None and event.acao in {_DONE, _REJECTED}:
            terminal.add(task.task_id)
            if event.acao == _REJECTED:
                rejections.append(
                    CleanupRejection(task.igreja_id, task.task_id, task.kind)
                )
        elif event.acao == _REJECTED and event.alvo_id is not None:
            detail = event.detalhe
            kind = detail.get("kind") if isinstance(detail, dict) else None
            if isinstance(kind, str) and kind in _TASK_KINDS:
                rejections.append(CleanupRejection(event.alvo_id, None, kind))
    return (
        tuple(task for task_id, task in tasks.items() if task_id not in terminal),
        tuple(rejections),
    )


def _pending_tasks(events: list[PlatformAuditLog]) -> tuple[CleanupTask, ...]:
    return _cleanup_task_states(events)[0]


def _has_delete_record(events: list[PlatformAuditLog]) -> bool:
    return any(event.acao in {_LOCAL_DELETED, _LEGACY_DELETED} for event in events)


def load_cleanup_drain_state(session: Session) -> CleanupDrainState:
    """Recover durable external cleanup work after local tenant commits."""
    _require_reset_principal(session)
    events_by_tenant: dict[uuid.UUID, list[PlatformAuditLog]] = {}
    events = session.execute(
        select(PlatformAuditLog)
        .where(PlatformAuditLog.alvo_tipo == "igreja")
        .order_by(PlatformAuditLog.created_at, PlatformAuditLog.id)
    ).scalars()
    for event in events:
        if event.alvo_id is not None:
            events_by_tenant.setdefault(event.alvo_id, []).append(event)

    pending: list[CleanupTask] = []
    rejected: list[CleanupRejection] = []
    for tenant_events in events_by_tenant.values():
        if not _has_delete_record(tenant_events):
            continue
        tenant_pending, tenant_rejected = _cleanup_task_states(tenant_events)
        pending.extend(tenant_pending)
        rejected.extend(tenant_rejected)
    return CleanupDrainState(tuple(pending), tuple(rejected))


def _e4b_table_has_tenant_column(session: Session, table: str) -> bool:
    return bool(
        session.execute(
            text(
                "select exists ("
                "select 1 from pg_catalog.pg_attribute a "
                "join pg_catalog.pg_class c on c.oid = a.attrelid "
                "join pg_catalog.pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = :schema and c.relname = :table "
                "and a.attname = 'igreja_id' and a.attnum > 0 and not a.attisdropped"
                ")"
            ),
            {"schema": _E4B_SCHEMA, "table": table},
        ).scalar_one()
    )


def _assert_e4b_empty(session: Session, igreja_id: uuid.UUID) -> None:
    """Fail closed for every populated E4B table relevant to this tenant."""
    schema = _quote_identifier(_E4B_SCHEMA)
    populated: dict[str, int] = {}
    for table in _reset_e4b_table_names(session):
        qualified = f"{schema}.{_quote_identifier(table)}"
        statement = f"select count(*) from {qualified}"
        parameters: dict[str, object] = {}
        if _e4b_table_has_tenant_column(session, table):
            statement += " where igreja_id = :igreja_id"
            parameters["igreja_id"] = igreja_id
        count = int(session.execute(text(statement), parameters).scalar_one())
        if count:
            populated[table] = count
    if populated:
        raise E4bPopulatedError(populated)


def _split_tenant_paths(
    igreja_id: uuid.UUID, paths: list[object]
) -> tuple[list[str], int]:
    valid: list[str] = []
    invalid = 0
    for path in paths:
        try:
            valid.extend(tenant_owned_paths(igreja_id, [path]))
        except StoragePathError:
            invalid += 1
    return valid, invalid


def _build_cleanup_tasks(
    session: Session,
    actor: TenantDeletionActor,
    igreja: Igreja,
    app_users: list[tuple[uuid.UUID, str | None]],
    protected_user_ids: set[uuid.UUID],
    instances: list[str | None],
    subscription: Subscription | None,
    media_paths: list[object],
) -> tuple[CleanupTask, ...]:
    tasks: list[CleanupTask] = []
    for app_user_id, clerk_user_id in app_users:
        if app_user_id in protected_user_ids or not clerk_user_id:
            continue
        if not is_valid_clerk_user_id(clerk_user_id):
            _rejected_target(session, actor, igreja, "clerk_user", "invalid_clerk_user_id")
            continue
        tasks.append(
            _new_task(
                session,
                actor,
                igreja,
                "clerk_user",
                {"clerk_user_id": clerk_user_id},
            )
        )

    for instance in instances:
        if not isinstance(instance, str) or not instance.strip():
            _rejected_target(session, actor, igreja, "evolution_instance", "invalid_instance")
            continue
        tasks.append(
            _new_task(
                session,
                actor,
                igreja,
                "evolution_instance",
                {"instance": instance},
            )
        )

    if subscription is not None and subscription.asaas_subscription_id:
        reference = subscription.asaas_subscription_external_reference
        if not is_valid_subscription_id(subscription.asaas_subscription_id):
            _rejected_target(session, actor, igreja, "asaas_subscription", "invalid_subscription_id")
        elif not is_pastorai_external_reference(reference):
            _rejected_target(session, actor, igreja, "asaas_subscription", "unowned_reference")
        else:
            tasks.append(
                _new_task(
                    session,
                    actor,
                    igreja,
                    "asaas_subscription",
                    {
                        "subscription_id": subscription.asaas_subscription_id,
                        "external_reference": reference,
                    },
                )
            )

    valid_media, invalid_media = _split_tenant_paths(igreja.id, media_paths)
    if invalid_media:
        _rejected_target(session, actor, igreja, "storage_media", "outside_tenant_prefix")
    tasks.append(
        _new_task(
            session,
            actor,
            igreja,
            "storage_media",
            {"paths": valid_media},
        )
    )

    valid_logo: list[str] = []
    if igreja.logo_path:
        valid_logo, invalid_logo = _split_tenant_paths(igreja.id, [igreja.logo_path])
        if invalid_logo:
            _rejected_target(session, actor, igreja, "storage_logo", "outside_tenant_prefix")
    tasks.append(
        _new_task(
            session,
            actor,
            igreja,
            "storage_logo",
            {"paths": valid_logo},
        )
    )
    return tuple(tasks)


def delete_tenant_locally(
    session: Session, igreja_id: uuid.UUID, actor: TenantDeletionActor
) -> TenantDeletionResult:
    """Persist cleanup work and delete one tenant without calling providers."""
    igreja = session.execute(
        select(Igreja)
        .where(Igreja.id == igreja_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if igreja is None:
        events = _read_audit_events(session, igreja_id)
        if not _has_delete_record(events):
            raise TenantDeletionNotFound("Igreja não encontrada")
        return TenantDeletionResult(
            igreja_id=igreja_id,
            deleted_now=False,
            pending_tasks=_pending_tasks(events),
        )

    # E4B can be absent from the current schema. When it exists with immutable
    # rows, no partial delete or manifest is acceptable.
    _assert_e4b_empty(session, igreja.id)

    app_users = list(
        session.execute(
            select(AppUser.id, AppUser.clerk_user_id).where(AppUser.igreja_id == igreja.id)
        ).all()
    )
    app_user_ids = [app_user_id for app_user_id, _ in app_users]
    protected_user_ids = set(
        session.execute(
            select(PlatformAdmin.app_user_id).where(PlatformAdmin.app_user_id.in_(app_user_ids))
        )
        .scalars()
        .all()
    ) if app_user_ids else set()
    instances = list(
        session.execute(
            select(WhatsappConnection.instance).where(WhatsappConnection.igreja_id == igreja.id)
        )
        .scalars()
        .all()
    )
    subscription = session.execute(
        select(Subscription).where(Subscription.igreja_id == igreja.id)
    ).scalar_one_or_none()
    media_paths = list(
        session.execute(
            select(Message.media_path).where(
                Message.igreja_id == igreja.id, Message.media_path.is_not(None)
            )
        )
        .scalars()
        .all()
    )

    tasks = _build_cleanup_tasks(
        session,
        actor,
        igreja,
        app_users,
        protected_user_ids,
        instances,
        subscription,
        media_paths,
    )

    # These tables own the composite tenant keys that would otherwise prevent
    # moving a preserved PlatformAdmin out of app_users.igreja_id.
    # consentimento_finalidade_evento is append-only. Its pessoa FK is CASCADE,
    # so it is removed by the Pessoa delete below at trigger depth > 1 instead
    # of bypassing the ledger guard with a direct DELETE.
    for model in _PRE_DETACH_DELETE_MODELS:
        session.execute(delete(model).where(model.igreja_id == igreja.id))

    non_platform_clerk_ids = [
        clerk_user_id
        for app_user_id, clerk_user_id in app_users
        if app_user_id not in protected_user_ids and clerk_user_id
    ]
    if non_platform_clerk_ids:
        session.execute(
            delete(PasswordResetToken).where(
                PasswordResetToken.clerk_user_id.in_(non_platform_clerk_ids)
            )
        )
    if protected_user_ids:
        session.execute(
            update(AppUser)
            .where(AppUser.id.in_(protected_user_ids))
            .values(pessoa_id=None, celula_pendente_id=None)
        )

    # All remaining foreign keys to Pessoa are CASCADE or SET NULL after E4B
    # was proved empty, so this removes private person records before detaching
    # a platform account from its tenant.
    session.execute(delete(Pessoa).where(Pessoa.igreja_id == igreja.id))
    if protected_user_ids:
        session.execute(
            update(AppUser).where(AppUser.id.in_(protected_user_ids)).values(igreja_id=None)
        )

    _audit(
        session,
        actor,
        _LEGACY_DELETED,
        igreja.id,
        igreja.nome,
        {"tenant_deletion": True},
    )
    _audit(
        session,
        actor,
        _LOCAL_DELETED,
        igreja.id,
        igreja.nome,
        {
            "version": 1,
            "pending_tasks": len(tasks),
            "platform_admins_preserved": len(protected_user_ids),
        },
    )
    session.delete(igreja)
    session.flush()
    return TenantDeletionResult(
        igreja_id=igreja.id, deleted_now=True, pending_tasks=tasks
    )


def _require_str(payload: dict[str, object], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise CleanupRejected("Manifesto de limpeza inválido")
    return value


def _assert_cleanup_ownership(session: Session, task: CleanupTask) -> None:
    """Check surviving bindings in a short transaction before provider work."""
    if task.kind in {"storage_media", "storage_logo"}:
        restored_tenant = session.execute(
            select(Igreja.id).where(Igreja.id == task.igreja_id).limit(1)
        ).scalar_one_or_none()
        if restored_tenant is not None:
            raise CleanupRejected("Namespace de armazenamento já pertence a uma igreja")
    if task.kind == "clerk_user":
        clerk_user_id = _require_str(task.payload, "clerk_user_id")
        if not is_valid_clerk_user_id(clerk_user_id):
            raise CleanupRejected("Identidade Clerk inválida")
        existing_user = session.execute(
            select(AppUser.id).where(AppUser.clerk_user_id == clerk_user_id).limit(1)
        ).scalar_one_or_none()
        if existing_user is not None:
            raise CleanupRejected("Identidade Clerk já pertence a uma conta sobrevivente")
        return
    if task.kind == "evolution_instance":
        instance = _require_str(task.payload, "instance")
        existing_connection = session.execute(
            select(WhatsappConnection.igreja_id)
            .where(WhatsappConnection.instance == instance)
            .limit(1)
        ).scalar_one_or_none()
        if existing_connection is not None:
            raise CleanupRejected("Instância Evolution já pertence a uma igreja sobrevivente")
        return
    if task.kind == "asaas_subscription":
        subscription_id = _require_str(task.payload, "subscription_id")
        if not is_valid_subscription_id(subscription_id):
            raise CleanupRejected("Assinatura Asaas inválida")
        existing_subscription = session.execute(
            select(Subscription.igreja_id)
            .where(Subscription.asaas_subscription_id == subscription_id)
            .limit(1)
        ).scalar_one_or_none()
        if existing_subscription is not None:
            raise CleanupRejected("Assinatura Asaas já pertence a uma igreja sobrevivente")
        return
    if task.kind == "storage_media":
        prefix = f"{task.igreja_id}/%"
        existing_media = session.execute(
            select(Message.igreja_id).where(Message.media_path.like(prefix)).limit(1)
        ).scalar_one_or_none()
        if existing_media is not None:
            raise CleanupRejected("Mídia já pertence a uma igreja sobrevivente")
        return
    if task.kind == "storage_logo":
        prefix = f"{task.igreja_id}/%"
        existing_logo = session.execute(
            select(Igreja.id).where(Igreja.logo_path.like(prefix)).limit(1)
        ).scalar_one_or_none()
        if existing_logo is not None:
            raise CleanupRejected("Logo já pertence a uma igreja sobrevivente")
        return
    raise CleanupRejected("Tipo de limpeza desconhecido")


def _cleanup_event_detail(
    task: CleanupTask,
    *,
    lease: CleanupLease | None = None,
    reason: str | None = None,
) -> dict[str, object]:
    detail = _lease_detail(task, lease) if lease is not None else _task_detail(task)
    if reason:
        detail["reason"] = reason
    return detail


def _claim_cleanup_task(
    session: Session,
    actor: TenantDeletionActor,
    task: CleanupTask,
) -> tuple[CleanupLease | None, CleanupOutcome | None]:
    """Claim one task durably, then commit before any provider interaction."""
    try:
        if not _lock_cleanup_manifest(session, task):
            session.rollback()
            return None, None
        events = _task_audit_events(session, task)
        if _task_is_terminal(events):
            session.rollback()
            return None, None
        active_lease = _active_cleanup_lease(events)
        if active_lease is not None and active_lease.expires_at > _utcnow():
            session.rollback()
            return None, None
        try:
            _assert_cleanup_ownership(session, task)
        except CleanupRejected as exc:
            _audit(
                session,
                actor,
                _REJECTED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, reason=type(exc).__name__),
            )
            session.commit()
            return None, CleanupOutcome(task.task_id, "rejected")
        lease = CleanupLease(
            task.task_id,
            uuid.uuid4(),
            _utcnow() + _CLEANUP_LEASE_DURATION,
        )
        _audit(
            session,
            actor,
            _CLAIMED,
            task.igreja_id,
            None,
            _cleanup_event_detail(task, lease=lease),
        )
        session.commit()
        return lease, None
    except CleanupRejected as exc:
        try:
            _audit(
                session,
                actor,
                _REJECTED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, reason=type(exc).__name__),
            )
            session.commit()
            return None, CleanupOutcome(task.task_id, "rejected")
        except Exception:
            session.rollback()
            logger.exception("Could not reject invalid tenant cleanup claim")
            return None, None
    except Exception:
        session.rollback()
        logger.exception("Could not claim tenant cleanup task")
        return None, None


def _renew_cleanup_lease(
    session: Session,
    actor: TenantDeletionActor,
    task: CleanupTask,
    lease: CleanupLease,
) -> tuple[CleanupLease | None, str | None]:
    """Renew a claim in a short transaction before an external request."""
    try:
        if not _lock_cleanup_manifest(session, task):
            session.rollback()
            return None, None
        events = _task_audit_events(session, task)
        if _task_is_terminal(events):
            session.rollback()
            return None, None
        active_lease = _active_cleanup_lease(events)
        if active_lease is None or active_lease.token != lease.token:
            _audit(
                session,
                actor,
                _FENCED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, lease=lease, reason="lease_reclaimed"),
            )
            session.commit()
            return None, "fenced"
        try:
            _assert_cleanup_ownership(session, task)
        except CleanupRejected as exc:
            _audit(
                session,
                actor,
                _REJECTED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, lease=lease, reason=type(exc).__name__),
            )
            session.commit()
            return None, "rejected"
        renewed = CleanupLease(
            task.task_id,
            lease.token,
            _utcnow() + _CLEANUP_LEASE_DURATION,
        )
        _audit(
            session,
            actor,
            _LEASE_RENEWED,
            task.igreja_id,
            None,
            _cleanup_event_detail(task, lease=renewed),
        )
        session.commit()
        return renewed, None
    except CleanupRejected as exc:
        try:
            _audit(
                session,
                actor,
                _REJECTED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, lease=lease, reason=type(exc).__name__),
            )
            session.commit()
            return None, "rejected"
        except Exception:
            session.rollback()
            logger.exception("Could not reject invalid tenant cleanup lease")
            return None, None
    except Exception:
        session.rollback()
        logger.exception("Could not renew tenant cleanup lease")
        return None, None


def _execute_cleanup_task(
    task: CleanupTask,
    *,
    clerk: ClerkClient,
    evolution: EvolutionClient,
    asaas: AsaasClient,
    storage: SupabaseStorage,
    before_external_request: Callable[[], None],
) -> None:
    if task.kind == "clerk_user":
        clerk_user_id = _require_str(task.payload, "clerk_user_id")
        if not is_valid_clerk_user_id(clerk_user_id):
            raise CleanupRejected("Identidade Clerk inválida")
        before_external_request()
        clerk.delete_user(clerk_user_id)
        return
    if task.kind == "evolution_instance":
        instance = _require_str(task.payload, "instance")
        before_external_request()
        if not evolution.delete_instance(instance):
            raise CleanupDeferred("gate_closed")
        return
    if task.kind == "asaas_subscription":
        subscription_id = _require_str(task.payload, "subscription_id")
        if not is_valid_subscription_id(subscription_id):
            raise CleanupRejected("Assinatura Asaas inválida")
        before_external_request()
        if not asaas.cancel_subscription(
            subscription_id,
            expected_external_reference=_require_str(task.payload, "external_reference"),
        ):
            raise CleanupDeferred("gate_closed")
        return
    if task.kind == "storage_media":
        storage.remove_tenant_media_namespace(
            task.igreja_id,
            before_request=before_external_request,
        )
        return
    if task.kind == "storage_logo":
        storage.remove_tenant_logos_namespace(
            task.igreja_id,
            before_request=before_external_request,
        )
        return
    raise CleanupRejected("Tipo de limpeza desconhecido")


def _finalize_cleanup_task(
    session: Session,
    actor: TenantDeletionActor,
    task: CleanupTask,
    lease: CleanupLease,
    action: str,
    status_name: str,
    reason: str | None = None,
    before_task: Callable[[Session], None] | None = None,
) -> CleanupOutcome | None:
    try:
        if before_task is not None:
            before_task(session)
        if not _lock_cleanup_manifest(session, task):
            session.rollback()
            return None
        events = _task_audit_events(session, task)
        active_lease = _active_cleanup_lease(events)
        if (
            active_lease is None
            or active_lease.token != lease.token
            or active_lease.expires_at <= _utcnow()
        ):
            _audit(
                session,
                actor,
                _FENCED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, lease=lease, reason="lease_expired_or_reclaimed"),
            )
            session.commit()
            return CleanupOutcome(task.task_id, "fenced")
        if _task_is_terminal(events):
            session.rollback()
            return None
        try:
            _assert_cleanup_ownership(session, task)
        except CleanupRejected as exc:
            _audit(
                session,
                actor,
                _REJECTED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, lease=lease, reason=type(exc).__name__),
            )
            session.commit()
            return CleanupOutcome(task.task_id, "rejected")
        _audit(
            session,
            actor,
            action,
            task.igreja_id,
            None,
            _cleanup_event_detail(task, lease=lease, reason=reason),
        )
        session.commit()
        return CleanupOutcome(task.task_id, status_name)
    except CleanupRejected as exc:
        try:
            _audit(
                session,
                actor,
                _REJECTED,
                task.igreja_id,
                None,
                _cleanup_event_detail(task, lease=lease, reason=type(exc).__name__),
            )
            session.commit()
            return CleanupOutcome(task.task_id, "rejected")
        except Exception:
            session.rollback()
            logger.exception("Could not reject invalid tenant cleanup result")
            return None
    except Exception:
        session.rollback()
        logger.exception("Could not persist tenant cleanup outcome")
        return None


def run_pending_cleanup(
    session: Session,
    actor: TenantDeletionActor,
    tasks: tuple[CleanupTask, ...],
    *,
    clerk: ClerkClient,
    evolution: EvolutionClient,
    asaas: AsaasClient,
    storage: SupabaseStorage,
    before_task: Callable[[Session], None] | None = None,
) -> tuple[CleanupOutcome, ...]:
    """Execute only durable pending tasks after the local transaction committed."""
    outcomes: list[CleanupOutcome] = []
    for task in tasks:
        if before_task is not None:
            before_task(session)
        lease, claim_outcome = _claim_cleanup_task(session, actor, task)
        if claim_outcome is not None:
            outcomes.append(claim_outcome)
            continue
        if lease is None:
            continue

        def renew_lease() -> None:
            nonlocal lease
            if before_task is not None:
                before_task(session)
            renewed, status_name = _renew_cleanup_lease(session, actor, task, lease)
            if renewed is None:
                raise CleanupClaimLost(status_name)
            lease = renewed

        try:
            _execute_cleanup_task(
                task,
                clerk=clerk,
                evolution=evolution,
                asaas=asaas,
                storage=storage,
                before_external_request=renew_lease,
            )
        except CleanupClaimLost as exc:
            if exc.args and isinstance(exc.args[0], str):
                outcomes.append(CleanupOutcome(task.task_id, exc.args[0]))
            continue
        except (CleanupRejected, StoragePathError, AsaasOwnershipError) as exc:
            action, status_name = _REJECTED, "rejected"
            reason = type(exc).__name__
        except CleanupDeferred:
            action, status_name, reason = _RETRY, "pending", "gate_closed"
        except Exception as exc:
            logger.warning("Tenant cleanup task failed: %s", type(exc).__name__)
            action, status_name = _RETRY, "pending"
            reason = type(exc).__name__
        else:
            action, status_name, reason = _DONE, "done", None
        outcome = _finalize_cleanup_task(
            session,
            actor,
            task,
            lease,
            action,
            status_name,
            reason,
            before_task,
        )
        if outcome is not None:
            outcomes.append(outcome)
    return tuple(outcomes)


def collect_reset_counts(session: Session) -> TenantResetCounts:
    """Read only counts suitable for a reset dry-run display."""
    _require_reset_principal(session)
    _assert_reset_e4b_empty(session)

    def count(model: object) -> int:
        return int(session.execute(select(func.count()).select_from(model)).scalar_one())

    return TenantResetCounts(
        igrejas=count(Igreja),
        app_users=count(AppUser),
        pessoas=count(Pessoa),
        subscriptions=count(Subscription),
        platform_admins=count(PlatformAdmin),
        platform_audit_events=count(PlatformAuditLog),
    )


def reset_all_tenants(session: Session, actor: TenantDeletionActor) -> TenantResetResult:
    """Delete every tenant in one SQL transaction without calling providers."""
    _require_reset_principal(session)
    session.execute(text("LOCK TABLE igrejas IN SHARE ROW EXCLUSIVE MODE"))
    _assert_reset_e4b_empty(session, lock_tables=True)
    igreja_ids = list(
        session.execute(select(Igreja.id).order_by(Igreja.id)).scalars().all()
    )
    for igreja_id in igreja_ids:
        delete_tenant_locally(session, igreja_id, actor)
    session.flush()
    return TenantResetResult(
        igrejas_deleted=len(igreja_ids),
        pending_tasks=len(load_cleanup_drain_state(session).pending_tasks),
    )


def _require_reset_principal(session: Session) -> None:
    """Reject a tenant-scoped role before it can report a partial reset."""
    permitted = session.execute(
        text(
            "select coalesce((select rolsuper or rolbypassrls "
            "from pg_catalog.pg_roles where rolname = current_user), false)"
        )
    ).scalar_one()
    if permitted is not True:
        raise TenantResetPermissionError(
            "O reset exige uma credencial administrativa com BYPASSRLS"
        )
