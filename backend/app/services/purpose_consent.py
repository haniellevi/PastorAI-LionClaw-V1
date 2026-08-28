"""Inactive internal service for the purpose-consent ledger (D2B2a/D2B2b1).

The service has no router, worker, graph, tool, broadcast or webhook caller in
this slice.  It never commits or rolls back the external transaction; an
internal SAVEPOINT exists only to classify an idempotency UNIQUE collision.
Transaction ownership remains with a future, explicitly authorized caller.
The D2B2b1 boundary rejects every grant before I/O. A later writer may only
enable grants through a separately reviewed authorization and evidence gate.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    ConsentimentoFinalidadeEvento,
    Pessoa,
)
from app.db.rls_observability import require_tenant_scope
from app.domain.purpose_consent import (
    OpaquePurposeConsentIdempotencyKey,
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentEvent,
    PurposeConsentEventState,
    PurposeConsentPurpose,
    PurposeConsentSnapshot,
    PurposeConsentSource,
    PurposeConsentValidationError,
    TrustedTermVersion,
    build_purpose_consent_snapshot,
)

_PG_UNIQUE_VIOLATION = "23505"
_IDEMPOTENCY_CONSTRAINT = "consentimento_finalidade_evento_idempotencia_key"


class PurposeConsentServiceError(RuntimeError):
    """Base error for failures that depend on persisted state."""


class PurposeConsentPersonNotFoundError(PurposeConsentServiceError):
    """The Pessoa does not exist in the explicit tenant."""


class PurposeConsentActorNotFoundError(PurposeConsentServiceError):
    """The authenticated panel actor does not exist in the explicit tenant."""


class PurposeConsentIdempotencyConflictError(PurposeConsentServiceError):
    """A tenant idempotency key was reused with a different intent."""


class PurposeConsentDataIntegrityError(PurposeConsentServiceError):
    """Persisted data violates the domain contract and cannot be projected."""


def _is_idempotency_unique_violation(exc: IntegrityError) -> bool:
    orig = exc.orig
    sqlstates = (
        getattr(orig, "pgcode", None),
        getattr(orig, "sqlstate", None),
    )
    constraint_name = getattr(getattr(orig, "diag", None), "constraint_name", None)
    return (
        _PG_UNIQUE_VIOLATION in sqlstates
        and constraint_name == _IDEMPOTENCY_CONSTRAINT
    )


def _require_uuid(value: object, *, field: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        raise PurposeConsentValidationError(f"{field} deve ser UUID não nulo")
    return value


def _require_idempotency_key(
    value: object,
) -> OpaquePurposeConsentIdempotencyKey:
    if type(value) is not OpaquePurposeConsentIdempotencyKey:
        raise PurposeConsentValidationError(
            "chave_idempotencia deve ser opaca e gerada no servidor"
        )
    if not value._was_server_minted_in_this_process():
        raise PurposeConsentValidationError(
            "chave_idempotencia opaca não tem proveniência válida neste processo"
        )
    return value


def _validate_append_contract(
    *,
    igreja_id: object,
    pessoa_id: object,
    finalidade: object,
    estado: object,
    versao_termo: object,
    fonte: object,
    chave_idempotencia: object,
    registrado_por_app_user_id: object,
) -> tuple[
    uuid.UUID,
    uuid.UUID,
    OpaquePurposeConsentIdempotencyKey,
    uuid.UUID | None,
]:
    tenant_id = _require_uuid(igreja_id, field="igreja_id")
    person_id = _require_uuid(pessoa_id, field="pessoa_id")
    if type(finalidade) is not PurposeConsentPurpose:
        raise PurposeConsentValidationError("finalidade inválida")
    if type(estado) is not PurposeConsentEventState:
        raise PurposeConsentValidationError("estado inválido")
    if type(versao_termo) is not TrustedTermVersion:
        raise PurposeConsentValidationError(
            "versao_termo deve vir de componente confiável"
        )
    if type(fonte) is not PurposeConsentSource:
        raise PurposeConsentValidationError("fonte inválida")
    idempotency_key = _require_idempotency_key(chave_idempotencia)

    actor_id: uuid.UUID | None
    if fonte is PurposeConsentSource.PAINEL_AUTENTICADO:
        actor_id = _require_uuid(
            registrado_por_app_user_id,
            field="registrado_por_app_user_id",
        )
    else:
        if registrado_por_app_user_id is not None:
            raise PurposeConsentValidationError(
                "whatsapp_inbound exige registrado_por_app_user_id nulo"
            )
        actor_id = None
    if estado is PurposeConsentEventState.CONCEDIDO:
        raise PurposeConsentValidationError(
            "estado concedido permanece bloqueado até existir writer autorizado"
        )
    return tenant_id, person_id, idempotency_key, actor_id


def _event_matches_intent(
    event: ConsentimentoFinalidadeEvento,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    finalidade: PurposeConsentPurpose,
    estado: PurposeConsentEventState,
    versao_termo: TrustedTermVersion,
    fonte: PurposeConsentSource,
    chave_idempotencia: OpaquePurposeConsentIdempotencyKey,
    registrado_por_app_user_id: uuid.UUID | None,
) -> bool:
    return (
        event.igreja_id == igreja_id
        and event.pessoa_id == pessoa_id
        and event.finalidade == finalidade.value
        and event.estado == estado.value
        and event.versao_termo == versao_termo.value
        and event.fonte == fonte.value
        and event.chave_idempotencia == chave_idempotencia.value
        and event.registrado_por_app_user_id == registrado_por_app_user_id
    )


def _lock_tenant_idempotency_key(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    chave_idempotencia: OpaquePurposeConsentIdempotencyKey,
) -> None:
    """Serialize one tenant key before locking any domain row.

    The database UNIQUE constraint remains the final barrier.  This
    transaction-scoped lock makes a concurrent request for the same key wait
    before choosing a Pessoa row, so replay and divergent conflict keep their
    structured service semantics even when the two intents name different
    Pessoas.
    """

    lock_key = (
        f"purpose-consent-idempotency:{igreja_id}:"
        f"{chave_idempotencia.value}"
    )
    db.execute(
        text(
            "select pg_catalog.pg_advisory_xact_lock("
            "pg_catalog.hashtextextended(:tenant_idempotency_key, 0))"
        ),
        {"tenant_idempotency_key": lock_key},
    ).scalar_one()


def append_purpose_consent_event(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    finalidade: PurposeConsentPurpose,
    estado: PurposeConsentEventState,
    versao_termo: TrustedTermVersion,
    fonte: PurposeConsentSource,
    chave_idempotencia: OpaquePurposeConsentIdempotencyKey,
    registrado_por_app_user_id: uuid.UUID | None = None,
) -> ConsentimentoFinalidadeEvento:
    """Append one permitted withdrawal or replay its tenant-scoped intent.

    The tenant role and GUC are proved first.  A transaction-scoped advisory
    lock serializes the tenant idempotency key before the Pessoa row becomes
    the stream serialization point.  The database trigger assigns sequence
    under its own lock, and unique constraints remain the final race barrier.
    This function flushes to surface those guarantees and never commits.
    Purpose-specific grants remain blocked by the pre-I/O contract validator.
    """

    tenant_id, person_id, idempotency_key, actor_id = _validate_append_contract(
        igreja_id=igreja_id,
        pessoa_id=pessoa_id,
        finalidade=finalidade,
        estado=estado,
        versao_termo=versao_termo,
        fonte=fonte,
        chave_idempotencia=chave_idempotencia,
        registrado_por_app_user_id=registrado_por_app_user_id,
    )
    require_tenant_scope(
        db,
        expected_igreja_id=tenant_id,
        source="purpose_consent_append",
    )
    _lock_tenant_idempotency_key(
        db,
        igreja_id=tenant_id,
        chave_idempotencia=idempotency_key,
    )

    locked_person_id = db.execute(
        select(Pessoa.id)
        .where(Pessoa.igreja_id == tenant_id, Pessoa.id == person_id)
        .with_for_update()
    ).scalar_one_or_none()
    if locked_person_id is None:
        raise PurposeConsentPersonNotFoundError(
            "pessoa não encontrada no tenant explícito"
        )

    if actor_id is not None:
        actor_exists = db.execute(
            select(AppUser.id).where(
                AppUser.igreja_id == tenant_id,
                AppUser.id == actor_id,
            )
        ).scalar_one_or_none()
        if actor_exists is None:
            raise PurposeConsentActorNotFoundError(
                "operador autenticado não encontrado no tenant explícito"
            )

    existing = db.execute(
        select(ConsentimentoFinalidadeEvento).where(
            ConsentimentoFinalidadeEvento.igreja_id == tenant_id,
            ConsentimentoFinalidadeEvento.chave_idempotencia
            == idempotency_key.value,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if _event_matches_intent(
            existing,
            igreja_id=tenant_id,
            pessoa_id=person_id,
            finalidade=finalidade,
            estado=estado,
            versao_termo=versao_termo,
            fonte=fonte,
            chave_idempotencia=idempotency_key,
            registrado_por_app_user_id=actor_id,
        ):
            return existing
        raise PurposeConsentIdempotencyConflictError(
            "chave_idempotencia já usada neste tenant com intenção divergente"
        )

    event = ConsentimentoFinalidadeEvento(
        igreja_id=tenant_id,
        pessoa_id=person_id,
        finalidade=finalidade.value,
        estado=estado.value,
        versao_termo=versao_termo.value,
        fonte=fonte.value,
        registrado_por_app_user_id=actor_id,
        chave_idempotencia=idempotency_key.value,
    )
    # ``begin_nested`` flushes any state already pending in the caller before
    # opening the SAVEPOINT.  The new event remains transient until afterward,
    # so this handler can only classify a collision caused by this insert.
    savepoint = db.begin_nested()
    try:
        with savepoint:
            db.add(event)
            db.flush()
    except IntegrityError as exc:
        if not _is_idempotency_unique_violation(exc):
            raise
        race_winner = db.execute(
            select(ConsentimentoFinalidadeEvento).where(
                ConsentimentoFinalidadeEvento.igreja_id == tenant_id,
                ConsentimentoFinalidadeEvento.chave_idempotencia
                == idempotency_key.value,
            )
        ).scalar_one_or_none()
        if race_winner is None:
            raise PurposeConsentIdempotencyConflictError(
                "colisão idempotente concorrente exige nova transação"
            ) from exc
        if _event_matches_intent(
            race_winner,
            igreja_id=tenant_id,
            pessoa_id=person_id,
            finalidade=finalidade,
            estado=estado,
            versao_termo=versao_termo,
            fonte=fonte,
            chave_idempotencia=idempotency_key,
            registrado_por_app_user_id=actor_id,
        ):
            return race_winner
        raise PurposeConsentIdempotencyConflictError(
            "chave_idempotencia concorrente tem intenção divergente"
        ) from exc
    if type(event.sequencia) is not int or event.sequencia <= 0:
        raise PurposeConsentDataIntegrityError(
            "banco não atribuiu uma sequencia positiva ao evento"
        )
    return event


def load_purpose_consent_snapshot(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    current_term_versions: Mapping[PurposeConsentPurpose, TrustedTermVersion],
) -> PurposeConsentSnapshot:
    """Read an immutable snapshot using only the new tenant-scoped ledger."""

    tenant_id = _require_uuid(igreja_id, field="igreja_id")
    person_id = _require_uuid(pessoa_id, field="pessoa_id")
    if not isinstance(current_term_versions, Mapping):
        raise PurposeConsentValidationError("versões atuais devem ser um mapeamento")
    term_purposes = tuple(current_term_versions)
    if (
        any(type(item) is not PurposeConsentPurpose for item in term_purposes)
        or set(term_purposes) != set(PURPOSE_CONSENT_PURPOSES)
    ):
        raise PurposeConsentValidationError(
            "versões atuais devem cobrir exatamente as quatro finalidades"
        )
    trusted_term_versions: dict[PurposeConsentPurpose, TrustedTermVersion] = {}
    for purpose in PURPOSE_CONSENT_PURPOSES:
        term_version = current_term_versions[purpose]
        if type(term_version) is not TrustedTermVersion:
            raise PurposeConsentValidationError(
                "versao_termo atual deve vir de componente confiável"
            )
        trusted_term_versions[purpose] = term_version

    require_tenant_scope(
        db,
        expected_igreja_id=tenant_id,
        source="purpose_consent_snapshot",
    )

    global_optout = db.execute(
        select(Pessoa.optout).where(
            Pessoa.igreja_id == tenant_id,
            Pessoa.id == person_id,
        )
    ).scalar_one_or_none()
    if global_optout is None:
        raise PurposeConsentPersonNotFoundError(
            "pessoa não encontrada no tenant explícito"
        )
    if type(global_optout) is not bool:
        raise PurposeConsentDataIntegrityError("optout global persistido é inválido")

    persisted_events = list(
        db.execute(
            select(ConsentimentoFinalidadeEvento)
            .where(
                ConsentimentoFinalidadeEvento.igreja_id == tenant_id,
                ConsentimentoFinalidadeEvento.pessoa_id == person_id,
            )
            .distinct(ConsentimentoFinalidadeEvento.finalidade)
            .order_by(
                ConsentimentoFinalidadeEvento.finalidade.asc(),
                ConsentimentoFinalidadeEvento.sequencia.desc(),
            )
        )
        .scalars()
        .all()
    )

    try:
        events = tuple(
            PurposeConsentEvent(
                purpose=PurposeConsentPurpose(row.finalidade),
                state=PurposeConsentEventState(row.estado),
                source=PurposeConsentSource(row.fonte),
                versao_termo=row.versao_termo,
                sequence=row.sequencia,
                registered_at=row.registrado_em,
            )
            for row in persisted_events
        )
        return build_purpose_consent_snapshot(
            events=events,
            current_term_versions=trusted_term_versions,
            global_optout=global_optout,
        )
    except (PurposeConsentValidationError, ValueError, TypeError) as exc:
        raise PurposeConsentDataIntegrityError(
            "ledger persistido não pode ser projetado com segurança"
        ) from exc
