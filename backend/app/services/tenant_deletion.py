"""Atomic tenant deletion with durable, retryable external cleanup."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, inspect, select, text, update
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    ConsentRecord,
    Conversation,
    E4bConsentHold,
    E4bConsentHoldEvent,
    E4bConsentOperation,
    E4bConsentReceipt,
    E4bConsentRetention,
    E4bConsentStream,
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
_LOCAL_DELETED = "tenant_deletion.local_deleted"
_LEGACY_DELETED = "excluir"
_TASK_KINDS = {
    "clerk_user",
    "evolution_instance",
    "asaas_subscription",
    "storage_media",
    "storage_logo",
}
_E4B_MODELS = (
    E4bConsentHoldEvent,
    E4bConsentHold,
    E4bConsentRetention,
    E4bConsentReceipt,
    E4bConsentStream,
    E4bConsentOperation,
)
_E4B_SCHEMA = "public"
_MEDIA_BATCH_SIZE = 100


class TenantDeletionError(RuntimeError):
    """Base error for a local tenant-deletion transition."""


class TenantDeletionNotFound(TenantDeletionError):
    """No tenant and no durable deletion record exists for the requested id."""


class TenantDeletionBlocked(TenantDeletionError):
    """An immutable tenant relation makes a complete deletion unsafe."""


class E4bPopulatedError(TenantDeletionBlocked):
    """A reset found rows in one or more protected E4B tables."""

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


@dataclass(frozen=True)
class TenantDeletionActor:
    app_user_id: uuid.UUID | None
    email: str | None


@dataclass(frozen=True)
class CleanupTask:
    task_id: uuid.UUID
    igreja_id: uuid.UUID
    kind: str
    payload: dict[str, object]


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


def _reset_e4b_counts(session: Session, *, lock_tables: bool) -> dict[str, int]:
    tables = _reset_e4b_table_names(session)
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
    session.add(
        PlatformAuditLog(
            actor_id=actor.app_user_id,
            actor_email=actor.email,
            acao=action,
            alvo_tipo="igreja",
            alvo_id=igreja_id,
            alvo_nome=igreja_name,
            detalhe=detail,
        )
    )


def _task_detail(task: CleanupTask) -> dict[str, object]:
    return {
        "version": 1,
        "task_id": str(task.task_id),
        "kind": task.kind,
        "payload": task.payload,
    }


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


def _pending_tasks(events: list[PlatformAuditLog]) -> tuple[CleanupTask, ...]:
    tasks: dict[uuid.UUID, CleanupTask] = {}
    terminal: set[uuid.UUID] = set()
    for event in events:
        task = _task_from_event(event)
        if task is None:
            continue
        if event.acao == _PENDING:
            tasks[task.task_id] = task
        elif event.acao in {_DONE, _REJECTED}:
            terminal.add(task.task_id)
    return tuple(task for task_id, task in tasks.items() if task_id not in terminal)


def _has_delete_record(events: list[PlatformAuditLog]) -> bool:
    return any(event.acao in {_LOCAL_DELETED, _LEGACY_DELETED} for event in events)


def _e4b_models_present(session: Session) -> tuple[type[object], ...]:
    inspector = inspect(session.connection())
    return tuple(model for model in _E4B_MODELS if inspector.has_table(model.__tablename__))


def _assert_e4b_empty(session: Session, igreja_id: uuid.UUID) -> None:
    """Fail before DML when an immutable E4B table still has tenant rows."""
    for model in _e4b_models_present(session):
        marker = session.execute(
            select(model.igreja_id).where(model.igreja_id == igreja_id).limit(1)
        ).scalar_one_or_none()
        if marker is not None:
            raise TenantDeletionBlocked(
                "A igreja contém dados E4B imutáveis e não pode ser excluída"
            )


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
    for index in range(0, len(valid_media), _MEDIA_BATCH_SIZE):
        tasks.append(
            _new_task(
                session,
                actor,
                igreja,
                "storage_media",
                {"paths": valid_media[index : index + _MEDIA_BATCH_SIZE]},
            )
        )

    if igreja.logo_path:
        valid_logo, invalid_logo = _split_tenant_paths(igreja.id, [igreja.logo_path])
        if invalid_logo:
            _rejected_target(session, actor, igreja, "storage_logo", "outside_tenant_prefix")
        elif valid_logo:
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
    session.execute(delete(ConsentRecord).where(ConsentRecord.igreja_id == igreja.id))
    session.execute(delete(Message).where(Message.igreja_id == igreja.id))
    session.execute(delete(Conversation).where(Conversation.igreja_id == igreja.id))
    session.execute(delete(UserRole).where(UserRole.igreja_id == igreja.id))

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


def _require_paths(payload: dict[str, object]) -> list[object]:
    paths = payload.get("paths")
    if not isinstance(paths, list) or not paths:
        raise CleanupRejected("Manifesto de limpeza inválido")
    return paths


def _lock_cleanup_table(session: Session, table: str) -> None:
    # Static table names only. This lock serializes a target check with a new
    # tenant binding until the provider effect and its audit outcome commit.
    session.execute(text(f"LOCK TABLE public.{table} IN SHARE ROW EXCLUSIVE MODE"))


def _execute_cleanup_task(
    session: Session,
    task: CleanupTask,
    *,
    clerk: ClerkClient,
    evolution: EvolutionClient,
    asaas: AsaasClient,
    storage: SupabaseStorage,
) -> None:
    if task.kind == "clerk_user":
        clerk_user_id = _require_str(task.payload, "clerk_user_id")
        if not is_valid_clerk_user_id(clerk_user_id):
            raise CleanupRejected("Identidade Clerk inválida")
        _lock_cleanup_table(session, "app_users")
        existing_user = session.execute(
            select(AppUser.id).where(AppUser.clerk_user_id == clerk_user_id).limit(1)
        ).scalar_one_or_none()
        if existing_user is not None:
            raise CleanupRejected("Identidade Clerk já pertence a uma conta sobrevivente")
        clerk.delete_user(clerk_user_id)
        return
    if task.kind == "evolution_instance":
        instance = _require_str(task.payload, "instance")
        _lock_cleanup_table(session, "whatsapp_connections")
        existing_connection = session.execute(
            select(WhatsappConnection.igreja_id)
            .where(WhatsappConnection.instance == instance)
            .limit(1)
        ).scalar_one_or_none()
        if existing_connection is not None:
            raise CleanupRejected("Instância Evolution já pertence a uma igreja sobrevivente")
        if not evolution.delete_instance(instance):
            raise CleanupDeferred("gate_closed")
        return
    if task.kind == "asaas_subscription":
        subscription_id = _require_str(task.payload, "subscription_id")
        if not is_valid_subscription_id(subscription_id):
            raise CleanupRejected("Assinatura Asaas inválida")
        _lock_cleanup_table(session, "subscriptions")
        existing_subscription = session.execute(
            select(Subscription.igreja_id)
            .where(Subscription.asaas_subscription_id == subscription_id)
            .limit(1)
        ).scalar_one_or_none()
        if existing_subscription is not None:
            raise CleanupRejected("Assinatura Asaas já pertence a uma igreja sobrevivente")
        if not asaas.cancel_subscription(
            subscription_id,
            expected_external_reference=_require_str(task.payload, "external_reference"),
        ):
            raise CleanupDeferred("gate_closed")
        return
    if task.kind == "storage_media":
        paths = tenant_owned_paths(task.igreja_id, _require_paths(task.payload))
        _lock_cleanup_table(session, "messages")
        reused_path = session.execute(
            select(Message.igreja_id)
            .where(Message.media_path.in_(paths))
            .limit(1)
        ).scalar_one_or_none()
        # The old tenant no longer exists once this task is eligible.  A row
        # with this path therefore always belongs to a surviving binding,
        # including a restored tenant with the same UUID.
        if reused_path is not None:
            raise CleanupRejected("Mídia já pertence a uma igreja sobrevivente")
        storage.remove_tenant_media(task.igreja_id, paths)
        return
    if task.kind == "storage_logo":
        paths = tenant_owned_paths(task.igreja_id, _require_paths(task.payload))
        _lock_cleanup_table(session, "igrejas")
        reused_path = session.execute(
            select(Igreja.id).where(Igreja.logo_path.in_(paths)).limit(1)
        ).scalar_one_or_none()
        if reused_path is not None:
            raise CleanupRejected("Logo já pertence a uma igreja sobrevivente")
        storage.remove_tenant_logos(task.igreja_id, paths)
        return
    raise CleanupRejected("Tipo de limpeza desconhecido")


def _persist_cleanup_event(
    session: Session,
    actor: TenantDeletionActor,
    task: CleanupTask,
    action: str,
    reason: str | None = None,
) -> bool:
    detail: dict[str, object] = _task_detail(task)
    if reason:
        detail["reason"] = reason
    _audit(session, actor, action, task.igreja_id, None, detail)
    try:
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Could not persist tenant cleanup outcome")
        return False
    return True


def run_pending_cleanup(
    session: Session,
    actor: TenantDeletionActor,
    tasks: tuple[CleanupTask, ...],
    *,
    clerk: ClerkClient,
    evolution: EvolutionClient,
    asaas: AsaasClient,
    storage: SupabaseStorage,
) -> tuple[CleanupOutcome, ...]:
    """Execute only durable pending tasks after the local transaction committed."""
    outcomes: list[CleanupOutcome] = []
    for task in tasks:
        try:
            _execute_cleanup_task(
                session,
                task,
                clerk=clerk,
                evolution=evolution,
                asaas=asaas,
                storage=storage,
            )
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
        if _persist_cleanup_event(session, actor, task, action, reason):
            outcomes.append(CleanupOutcome(task.task_id, status_name))
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
    pending_tasks = 0
    for igreja_id in igreja_ids:
        result = delete_tenant_locally(session, igreja_id, actor)
        pending_tasks += len(result.pending_tasks)
    session.flush()
    return TenantResetResult(
        igrejas_deleted=len(igreja_ids), pending_tasks=pending_tasks
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
