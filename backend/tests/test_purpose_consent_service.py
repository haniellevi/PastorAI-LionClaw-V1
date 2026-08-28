from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import TextClause

from app.db.models import ConsentimentoFinalidadeEvento, Pessoa
from app.db.rls_observability import TenantScopeVerificationError
from app.domain.purpose_consent import (
    OpaquePurposeConsentIdempotencyKey,
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentEventState,
    PurposeConsentProjectionState,
    PurposeConsentPurpose,
    PurposeConsentSource,
    PurposeConsentValidationError,
    TrustedTermVersion,
)
from app.services.purpose_consent import (
    PurposeConsentActorNotFoundError,
    PurposeConsentDataIntegrityError,
    PurposeConsentIdempotencyConflictError,
    PurposeConsentPersonNotFoundError,
    append_purpose_consent_event,
    load_purpose_consent_snapshot,
)


TENANT_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
OTHER_TENANT_ID = uuid.UUID("20000000-0000-0000-0000-000000000002")
PERSON_ID = uuid.UUID("30000000-0000-0000-0000-000000000003")
OTHER_PERSON_ID = uuid.UUID("40000000-0000-0000-0000-000000000004")
ACTOR_ID = uuid.UUID("50000000-0000-0000-0000-000000000005")
TERM_VERSION = TrustedTermVersion("2026-08-v1")
IDEMPOTENCY_KEY = OpaquePurposeConsentIdempotencyKey.generate()


class _Result:
    def __init__(self, value: object) -> None:
        self.value = value

    def scalar_one_or_none(self) -> object | None:
        if isinstance(self.value, list):
            if len(self.value) > 1:
                raise AssertionError("resultado fake não é escalar")
            return self.value[0] if self.value else None
        return self.value

    def scalar_one(self) -> object:
        return self.value

    def one(self) -> object:
        return self.value

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[object]:
        if isinstance(self.value, list):
            return list(self.value)
        if self.value is None:
            return []
        return [self.value]


class _FakeNestedTransaction:
    def __enter__(self) -> _FakeNestedTransaction:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object,
    ) -> bool:
        return False


class _FakeSession:
    def __init__(
        self,
        results: Iterable[object],
        *,
        server_sequence: int = 1,
        scope_role: str | None = "authenticated",
        scope_tenant: uuid.UUID | None = TENANT_ID,
        scope_guc: uuid.UUID | None = TENANT_ID,
        flush_error: IntegrityError | None = None,
    ) -> None:
        self._results = list(results)
        self.server_sequence = server_sequence
        self.statements: list[Any] = []
        self.statement_parameters: list[dict[str, object] | None] = []
        self.added: list[object] = []
        self.flush_calls = 0
        self.begin_nested_calls = 0
        self.sequence_before_flush: object = "not-observed"
        self.scope_role = scope_role
        self.scope_tenant = scope_tenant
        self.scope_guc = scope_guc
        self.flush_error = flush_error

    def execute(
        self,
        statement: Any,
        parameters: dict[str, object] | None = None,
    ) -> _Result:
        self.statements.append(statement)
        self.statement_parameters.append(parameters)
        statement_text = (
            statement.text
            if isinstance(statement, TextClause)
            else _compiled(statement)
        )
        if "current_setting('role'" in statement_text:
            return _Result(
                SimpleNamespace(
                    role=self.scope_role,
                    igreja_id=self.scope_tenant,
                    tenant_guc=self.scope_guc,
                )
            )
        if "pg_advisory_xact_lock" in statement_text:
            return _Result(None)
        if not self._results:
            raise AssertionError("query inesperada")
        return _Result(self._results.pop(0))

    def add(self, value: object) -> None:
        self.added.append(value)

    def begin_nested(self) -> _FakeNestedTransaction:
        self.begin_nested_calls += 1
        return _FakeNestedTransaction()

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_error is not None:
            error = self.flush_error
            self.flush_error = None
            raise error
        if self.added and isinstance(
            self.added[-1], ConsentimentoFinalidadeEvento
        ):
            event = self.added[-1]
            self.sequence_before_flush = event.sequencia
            if event.sequencia is None:
                event.sequencia = self.server_sequence

    def commit(self) -> None:
        raise AssertionError("o serviço interno não pode fazer commit")

    def rollback(self) -> None:
        raise AssertionError("o serviço interno não pode fazer rollback")


def _person(*, tenant_id: uuid.UUID = TENANT_ID, optout: bool = False) -> Pessoa:
    return Pessoa(
        id=PERSON_ID,
        igreja_id=tenant_id,
        nome="Pessoa teste",
        telefone="5511999999999",
        consentimento=True,
        optout=optout,
    )


def _persisted_event(
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    pessoa_id: uuid.UUID = PERSON_ID,
    finalidade: PurposeConsentPurpose = PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
    estado: PurposeConsentEventState = PurposeConsentEventState.RETIRADO,
    versao_termo: str = TERM_VERSION.value,
    fonte: PurposeConsentSource = PurposeConsentSource.WHATSAPP_INBOUND,
    chave_idempotencia: str = IDEMPOTENCY_KEY.value,
    actor_id: uuid.UUID | None = None,
    sequencia: int = 1,
) -> ConsentimentoFinalidadeEvento:
    return ConsentimentoFinalidadeEvento(
        id=uuid.uuid4(),
        igreja_id=tenant_id,
        pessoa_id=pessoa_id,
        finalidade=finalidade.value,
        estado=estado.value,
        versao_termo=versao_termo,
        fonte=fonte.value,
        registrado_por_app_user_id=actor_id,
        chave_idempotencia=chave_idempotencia,
        sequencia=sequencia,
        registrado_em=dt.datetime(2026, 8, 28, tzinfo=dt.timezone.utc),
    )


def _current_versions() -> dict[PurposeConsentPurpose, TrustedTermVersion]:
    return {purpose: TERM_VERSION for purpose in PURPOSE_CONSENT_PURPOSES}


def _compiled(statement: Any) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _idempotency_integrity_error() -> IntegrityError:
    original = Exception("unique violation")
    original.pgcode = "23505"  # type: ignore[attr-defined]
    original.sqlstate = "23505"  # type: ignore[attr-defined]
    original.diag = SimpleNamespace(  # type: ignore[attr-defined]
        constraint_name="consentimento_finalidade_evento_idempotencia_key"
    )
    return IntegrityError("insert", {}, original)


def test_orm_mirrors_canonical_columns_and_database_invariants() -> None:
    table = ConsentimentoFinalidadeEvento.__table__
    assert tuple(column.name for column in table.columns) == (
        "id",
        "igreja_id",
        "pessoa_id",
        "finalidade",
        "estado",
        "versao_termo",
        "fonte",
        "registrado_por_app_user_id",
        "chave_idempotencia",
        "sequencia",
        "registrado_em",
    )
    assert isinstance(table.c.sequencia.type, BigInteger)
    assert table.c.sequencia.server_default is not None

    unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert ("igreja_id", "chave_idempotencia") in unique_columns
    assert ("igreja_id", "id") in unique_columns
    assert (
        "igreja_id",
        "pessoa_id",
        "finalidade",
        "sequencia",
    ) in unique_columns
    unique_names = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    assert {
        "consentimento_finalidade_evento_tenant_id_key",
        "consentimento_finalidade_evento_idempotencia_key",
        "consentimento_finalidade_evento_stream_seq_key",
    } <= unique_names

    composite_foreign_keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }
    assert ("igreja_id", "pessoa_id") in composite_foreign_keys
    assert ("igreja_id", "registrado_por_app_user_id") in composite_foreign_keys

    actor_index = next(
        index
        for index in table.indexes
        if index.name == "consentimento_finalidade_evento_registrado_por_idx"
    )
    assert tuple(column.name for column in actor_index.columns) == (
        "registrado_por_app_user_id",
        "igreja_id",
    )

    checks = " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert "tarefas_operacionais" in checks
    assert "comunicados" in checks
    assert "versao_termo !~ '[[:cntrl:]]'" in checks
    assert (
        "chave_idempotencia ~ '^[a-z0-9][a-z0-9:._-]{0,127}$'" in checks
    )


def test_append_locks_person_uses_server_sequence_and_never_commits() -> None:
    db = _FakeSession([PERSON_ID, None], server_sequence=41)

    event = append_purpose_consent_event(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        pessoa_id=PERSON_ID,
        finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        estado=PurposeConsentEventState.RETIRADO,
        versao_termo=TERM_VERSION,
        fonte=PurposeConsentSource.WHATSAPP_INBOUND,
        chave_idempotencia=IDEMPOTENCY_KEY,
    )

    assert event.sequencia == 41
    assert event.chave_idempotencia == IDEMPOTENCY_KEY.value
    assert db.sequence_before_flush is None
    assert db.flush_calls == 1
    assert db.begin_nested_calls == 1
    assert len(db.added) == 1
    assert "current_setting('role'" in str(db.statements[0])
    assert "pg_advisory_xact_lock" in str(db.statements[1])
    assert getattr(db.statements[2], "_for_update_arg", None) is not None
    assert all("igreja_id" in _compiled(query) for query in db.statements[2:])
    assert db.statement_parameters[1] == {
        "tenant_idempotency_key": (
            f"purpose-consent-idempotency:{TENANT_ID}:{IDEMPOTENCY_KEY.value}"
        )
    }


def test_identical_tenant_scoped_replay_returns_existing_without_write() -> None:
    existing = _persisted_event()
    db = _FakeSession([PERSON_ID, existing])

    replay = append_purpose_consent_event(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        pessoa_id=PERSON_ID,
        finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        estado=PurposeConsentEventState.RETIRADO,
        versao_termo=TERM_VERSION,
        fonte=PurposeConsentSource.WHATSAPP_INBOUND,
        chave_idempotencia=IDEMPOTENCY_KEY,
    )

    assert replay is existing
    assert db.added == []
    assert db.flush_calls == 0
    idempotency_sql = _compiled(db.statements[3])
    assert "igreja_id" in idempotency_sql
    assert "chave_idempotencia" in idempotency_sql


def test_unique_race_is_replayed_or_mapped_without_raw_integrity_error() -> None:
    identical_winner = _persisted_event()
    replay_db = _FakeSession(
        [PERSON_ID, None, identical_winner],
        flush_error=_idempotency_integrity_error(),
    )

    replay = append_purpose_consent_event(
        replay_db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        pessoa_id=PERSON_ID,
        finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        estado=PurposeConsentEventState.RETIRADO,
        versao_termo=TERM_VERSION,
        fonte=PurposeConsentSource.WHATSAPP_INBOUND,
        chave_idempotencia=IDEMPOTENCY_KEY,
    )

    assert replay is identical_winner
    assert replay_db.begin_nested_calls == 1

    divergent_winner = _persisted_event(pessoa_id=OTHER_PERSON_ID)
    conflict_db = _FakeSession(
        [PERSON_ID, None, divergent_winner],
        flush_error=_idempotency_integrity_error(),
    )
    with pytest.raises(PurposeConsentIdempotencyConflictError):
        append_purpose_consent_event(
            conflict_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )

    invisible_winner_db = _FakeSession(
        [PERSON_ID, None, None],
        flush_error=_idempotency_integrity_error(),
    )
    with pytest.raises(PurposeConsentIdempotencyConflictError, match="nova transação"):
        append_purpose_consent_event(
            invisible_winner_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )


@pytest.mark.parametrize(
    ("pessoa_id", "finalidade"),
    [
        (OTHER_PERSON_ID, PurposeConsentPurpose.ATENDIMENTO_SOLICITADO),
        (PERSON_ID, PurposeConsentPurpose.CUIDADO_PASTORAL),
    ],
)
def test_reused_key_with_divergent_intent_fails_closed(
    pessoa_id: uuid.UUID,
    finalidade: PurposeConsentPurpose,
) -> None:
    existing = _persisted_event()
    db = _FakeSession([pessoa_id, existing])

    with pytest.raises(PurposeConsentIdempotencyConflictError):
        append_purpose_consent_event(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=pessoa_id,
            finalidade=finalidade,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )

    assert db.added == []
    assert db.flush_calls == 0
    assert "pg_advisory_xact_lock" in str(db.statements[1])
    assert getattr(db.statements[2], "_for_update_arg", None) is not None


def test_append_and_snapshot_require_exact_role_and_guc_before_domain_query() -> None:
    unscoped_append_db = _FakeSession(
        [PERSON_ID, None],
        scope_role="none",
        scope_tenant=None,
        scope_guc=None,
    )
    with pytest.raises(TenantScopeVerificationError):
        append_purpose_consent_event(
            unscoped_append_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )
    assert len(unscoped_append_db.statements) == 1
    assert unscoped_append_db.added == []

    missing_guc_append_db = _FakeSession(
        [PERSON_ID, None],
        scope_tenant=TENANT_ID,
        scope_guc=None,
    )
    with pytest.raises(TenantScopeVerificationError):
        append_purpose_consent_event(
            missing_guc_append_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )
    assert len(missing_guc_append_db.statements) == 1

    wrong_tenant_snapshot_db = _FakeSession(
        [False, []],
        scope_tenant=OTHER_TENANT_ID,
        scope_guc=OTHER_TENANT_ID,
    )
    with pytest.raises(TenantScopeVerificationError):
        load_purpose_consent_snapshot(
            wrong_tenant_snapshot_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            current_term_versions=_current_versions(),
        )
    assert len(wrong_tenant_snapshot_db.statements) == 1


def test_panel_requires_actor_and_validates_actor_in_same_tenant() -> None:
    with pytest.raises(PurposeConsentValidationError, match="app_user_id"):
        append_purpose_consent_event(
            _FakeSession([]),  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.CUIDADO_PASTORAL,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.PAINEL_AUTENTICADO,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )

    missing_actor_db = _FakeSession([PERSON_ID, None])
    with pytest.raises(PurposeConsentActorNotFoundError):
        append_purpose_consent_event(
            missing_actor_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.CUIDADO_PASTORAL,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.PAINEL_AUTENTICADO,
            chave_idempotencia=IDEMPOTENCY_KEY,
            registrado_por_app_user_id=ACTOR_ID,
        )

    actor_sql = _compiled(missing_actor_db.statements[3])
    assert "app_users.igreja_id" in actor_sql
    assert str(TENANT_ID) in actor_sql
    assert str(ACTOR_ID) in actor_sql


def test_panel_append_persists_the_validated_same_tenant_actor() -> None:
    db = _FakeSession([PERSON_ID, ACTOR_ID, None], server_sequence=2)

    event = append_purpose_consent_event(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        pessoa_id=PERSON_ID,
        finalidade=PurposeConsentPurpose.CUIDADO_PASTORAL,
        estado=PurposeConsentEventState.RETIRADO,
        versao_termo=TERM_VERSION,
        fonte=PurposeConsentSource.PAINEL_AUTENTICADO,
        chave_idempotencia=IDEMPOTENCY_KEY,
        registrado_por_app_user_id=ACTOR_ID,
    )

    assert event.registrado_por_app_user_id == ACTOR_ID
    assert event.sequencia == 2
    assert all("igreja_id" in _compiled(query) for query in db.statements[2:])


def test_whatsapp_requires_null_actor() -> None:
    with pytest.raises(PurposeConsentValidationError, match="nulo"):
        append_purpose_consent_event(
            _FakeSession([]),  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
            registrado_por_app_user_id=ACTOR_ID,
        )


@pytest.mark.parametrize(
    "raw_key",
    (
        "pc:v1:" + ("a" * 64),
        "wa:message:123",
        ":starts-with-punctuation",
        "Uppercase",
        "contains space",
        "á",
        "x" * 129,
        object(),
    ),
)
def test_append_rejects_raw_idempotency_key_before_any_io(raw_key: object) -> None:
    db = _FakeSession([])

    with pytest.raises(PurposeConsentValidationError, match="opaca"):
        append_purpose_consent_event(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=raw_key,  # type: ignore[arg-type]
        )

    assert db.statements == []
    assert db.added == []
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    "forgery",
    ("mutated-value", "missing-proof", "mutated-proof"),
)
def test_append_revalidates_forged_value_object_before_any_io(forgery: str) -> None:
    if forgery == "mutated-value":
        forged_key = OpaquePurposeConsentIdempotencyKey.generate()
        object.__setattr__(
            forged_key,
            "value",
            "pc:v1:" + ("0" * 64),
        )
    elif forgery == "missing-proof":
        forged_key = object.__new__(OpaquePurposeConsentIdempotencyKey)
        object.__setattr__(forged_key, "value", "pc:v1:" + ("a" * 64))
    else:
        forged_key = OpaquePurposeConsentIdempotencyKey.generate()
        object.__setattr__(forged_key, "_mint_proof", b"\x00" * 32)
    db = _FakeSession([])

    with pytest.raises(PurposeConsentValidationError, match="proveniência"):
        append_purpose_consent_event(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=forged_key,
        )

    assert db.statements == []
    assert db.added == []
    assert db.flush_calls == 0


def test_append_rejects_grant_before_any_io() -> None:
    db = _FakeSession([])

    with pytest.raises(PurposeConsentValidationError, match="concedido"):
        append_purpose_consent_event(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.CONCEDIDO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )

    assert db.statements == []
    assert db.added == []
    assert db.flush_calls == 0


def test_raw_term_version_and_invalid_tenant_fail_before_any_query() -> None:
    raw_term_db = _FakeSession([])
    with pytest.raises(PurposeConsentValidationError, match="confiável"):
        append_purpose_consent_event(
            raw_term_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo="2026-08-v1",  # type: ignore[arg-type]
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )
    assert raw_term_db.statements == []

    invalid_tenant_db = _FakeSession([])
    with pytest.raises(PurposeConsentValidationError, match="igreja_id"):
        append_purpose_consent_event(
            invalid_tenant_db,  # type: ignore[arg-type]
            igreja_id=str(TENANT_ID),  # type: ignore[arg-type]
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )
    assert invalid_tenant_db.statements == []


def test_person_must_exist_in_explicit_tenant() -> None:
    db = _FakeSession(
        [None],
        scope_tenant=OTHER_TENANT_ID,
        scope_guc=OTHER_TENANT_ID,
    )
    with pytest.raises(PurposeConsentPersonNotFoundError):
        append_purpose_consent_event(
            db,  # type: ignore[arg-type]
            igreja_id=OTHER_TENANT_ID,
            pessoa_id=PERSON_ID,
            finalidade=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            estado=PurposeConsentEventState.RETIRADO,
            versao_termo=TERM_VERSION,
            fonte=PurposeConsentSource.WHATSAPP_INBOUND,
            chave_idempotencia=IDEMPOTENCY_KEY,
        )
    sql = _compiled(db.statements[2])
    assert str(OTHER_TENANT_ID) in sql
    assert str(PERSON_ID) in sql


def test_snapshot_ignores_legacy_grant_and_filters_every_query_by_tenant() -> None:
    legacy_pessoa = _person()
    assert legacy_pessoa.consentimento is True
    db = _FakeSession([False, []])

    snapshot = load_purpose_consent_snapshot(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        pessoa_id=PERSON_ID,
        current_term_versions=_current_versions(),
    )

    assert all(
        projection.state is PurposeConsentProjectionState.AUSENTE
        for projection in snapshot.projections
    )
    assert all("igreja_id" in _compiled(query) for query in db.statements[1:])
    assert all(
        str(TENANT_ID) in _compiled(query) for query in db.statements[1:]
    )
    assert "pessoas.consentimento" not in _compiled(db.statements[1])
    assert "DISTINCT ON" in _compiled(db.statements[2])


def test_snapshot_projects_new_events_and_global_optout_independently() -> None:
    event = _persisted_event(
        finalidade=PurposeConsentPurpose.COMUNICADOS,
        estado=PurposeConsentEventState.CONCEDIDO,
    )
    db = _FakeSession([True, [event]])

    snapshot = load_purpose_consent_snapshot(
        db,  # type: ignore[arg-type]
        igreja_id=TENANT_ID,
        pessoa_id=PERSON_ID,
        current_term_versions=_current_versions(),
    )

    assert snapshot.global_optout is True
    assert all(
        projection.state
        is PurposeConsentProjectionState.BLOQUEADO_OPTOUT_GLOBAL
        for projection in snapshot.projections
    )
    comunicados = snapshot.for_purpose(PurposeConsentPurpose.COMUNICADOS)
    assert comunicados.recorded_state is PurposeConsentEventState.CONCEDIDO


def test_snapshot_fails_closed_for_invalid_persisted_event_or_term_map() -> None:
    invalid_event = _persisted_event(estado=PurposeConsentEventState.CONCEDIDO)
    invalid_event.finalidade = "finalidade_inventada"
    db = _FakeSession([False, [invalid_event]])
    with pytest.raises(PurposeConsentDataIntegrityError):
        load_purpose_consent_snapshot(
            db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            current_term_versions=_current_versions(),
        )

    invalid_terms_db = _FakeSession([])
    with pytest.raises(PurposeConsentValidationError, match="quatro finalidades"):
        load_purpose_consent_snapshot(
            invalid_terms_db,  # type: ignore[arg-type]
            igreja_id=TENANT_ID,
            pessoa_id=PERSON_ID,
            current_term_versions={
                PurposeConsentPurpose.ATENDIMENTO_SOLICITADO: TERM_VERSION
            },
        )
    assert invalid_terms_db.statements == []
