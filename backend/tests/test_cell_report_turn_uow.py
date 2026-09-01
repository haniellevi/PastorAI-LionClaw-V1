from __future__ import annotations

import ast
import datetime as dt
import inspect
import uuid

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import StatementError

from app.agent.turn_execution import (
    AgentCompatibilityKeyVersion,
    build_agent_effect_compatibility_key,
    build_agent_turn_execution_plan,
)
from app.agent.turn_identity import (
    AgentEffectIntent,
    AgentEffectKind,
    AgentTurnIdentity,
    build_agent_effect_intent,
    build_agent_turn_identity,
)
from app.db.models import AgentConversationLog, Message
from app.services import cell_report_turn_uow as uow
from app.services.cell_report_application import (
    CellReportApplicationError,
    CellReportApplicationErrorCode,
    CellReportConfirmationResult,
    build_cell_report_confirmation_effect_payload,
)


TENANT = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER_TENANT = uuid.UUID("11111111-1111-1111-1111-111111111112")
MEETING = uuid.UUID("22222222-2222-2222-2222-222222222222")
CONVERSATION = uuid.UUID("33333333-3333-3333-3333-333333333333")
OTHER_CONVERSATION = uuid.UUID("33333333-3333-3333-3333-333333333334")
ACTOR = uuid.UUID("44444444-4444-4444-4444-444444444444")
INBOUND = uuid.UUID("55555555-5555-5555-5555-555555555555")
OTHER_INBOUND = uuid.UUID("55555555-5555-5555-5555-555555555556")
REPLY_MESSAGE = uuid.UUID("66666666-6666-6666-6666-666666666666")
NOW = dt.datetime(2026, 8, 31, 21, 0, tzinfo=dt.timezone.utc)
COMMAND = "CONFIRMAR RELATORIO AAAAAAAAAAAA"
REPLY_TEXT = "Relatório confirmado com sucesso."


class _ScalarRows:
    def __init__(
        self,
        values: list[object],
        *,
        error: Exception | None = None,
    ) -> None:
        self._values = values
        self._error = error

    def all(self) -> list[object]:
        if self._error is not None:
            raise self._error
        return list(self._values)


class _Result:
    def __init__(
        self,
        values: list[object] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self._values = values or []
        self._error = error

    def scalars(self) -> _ScalarRows:
        return _ScalarRows(self._values, error=self._error)


class _FakeSession:
    def __init__(
        self,
        responses: list[_Result],
        *,
        transaction_active: bool = True,
        transaction_error: Exception | None = None,
        execute_error: Exception | None = None,
        flush_error: Exception | None = None,
        add_error: Exception | None = None,
    ) -> None:
        self.responses = list(responses)
        self.transaction_active = transaction_active
        self.transaction_error = transaction_error
        self.execute_error = execute_error
        self.flush_error = flush_error
        self.add_error = add_error
        self.statements: list[object] = []
        self.added: list[object] = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0

    def in_transaction(self) -> bool:
        if self.transaction_error is not None:
            raise self.transaction_error
        return self.transaction_active

    def execute(self, statement: object) -> _Result:
        self.statements.append(statement)
        if self.execute_error is not None:
            raise self.execute_error
        if not self.responses:
            raise AssertionError("unexpected database query")
        return self.responses.pop(0)

    def add(self, value: object) -> None:
        if self.add_error is not None:
            raise self.add_error
        self.added.append(value)

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_error is not None:
            raise self.flush_error

    def commit(self) -> None:
        self.commit_calls += 1
        raise AssertionError("unit of work must not commit")

    def rollback(self) -> None:
        self.rollback_calls += 1
        raise AssertionError("unit of work must not roll back")


@pytest.fixture(autouse=True)
def _tenant_scope(monkeypatch: pytest.MonkeyPatch):
    calls: list[tuple[object, str | None]] = []

    def require_scope(_db, *, expected_igreja_id, source=None):
        calls.append((expected_igreja_id, source))

    monkeypatch.setattr(uow, "require_tenant_scope", require_scope)
    return calls


def _identity(
    *,
    tenant: uuid.UUID = TENANT,
    conversation: uuid.UUID = CONVERSATION,
    inbound: uuid.UUID = INBOUND,
) -> AgentTurnIdentity:
    return build_agent_turn_identity(
        igreja_id=tenant,
        conversation_id=conversation,
        inbound_message_id=inbound,
        provider_message_id=f"provider-{inbound.hex}",
    )


def _intents(
    identity: AgentTurnIdentity,
    *,
    reply_text: str = REPLY_TEXT,
    submission_ordinal: int = 0,
    reply_ordinal: int = 0,
    audit_ordinal: int = 0,
) -> tuple[AgentEffectIntent, AgentEffectIntent, AgentEffectIntent]:
    submission = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.TOOL_CALL,
        ordinal=submission_ordinal,
        payload=build_cell_report_confirmation_effect_payload(
            igreja_id=identity.igreja_id,
            reuniao_id=MEETING,
            conversa_id=identity.conversation_id,
            ator_pessoa_id=ACTOR,
            command=COMMAND,
        ),
    )
    reply = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.OUTBOUND_REPLY,
        ordinal=reply_ordinal,
        payload=uow.build_cell_report_turn_reply_effect_payload(
            turn_identity=identity,
            submission_intent=submission,
            reply_text=reply_text,
        ),
    )
    audit = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.AUDIT_EVENT,
        ordinal=audit_ordinal,
        payload=uow.build_cell_report_turn_audit_effect_payload(
            turn_identity=identity,
            submission_intent=submission,
            reply_intent=reply,
        ),
    )
    return submission, audit, reply


def _plan_and_v2_key(
    identity: AgentTurnIdentity,
    intents: tuple[AgentEffectIntent, AgentEffectIntent, AgentEffectIntent],
) -> tuple[object, str]:
    plan = build_agent_turn_execution_plan(identity, intents)
    key = build_agent_effect_compatibility_key(
        identity,
        plan,
        intents[2],
        version=AgentCompatibilityKeyVersion.V2,
    )
    return plan, key.key


def _message(
    provider_key: str,
    *,
    state: str = "ia_executando",
    text: str | None = None,
    **overrides: object,
) -> Message:
    values: dict[str, object] = {
        "id": REPLY_MESSAGE,
        "igreja_id": TENANT,
        "conversation_id": CONVERSATION,
        "direcao": "out",
        "autor": "ia",
        "agent_reply_state": state,
        "texto": text,
        "provider_message_id": provider_key,
        "tipo": "texto",
        "media_path": None,
        "media_mime": None,
        "media_nome": None,
        "media_tamanho": None,
        "autor_nome": None,
        "enviado_por": None,
    }
    values.update(overrides)
    return Message(**values)


def _confirmation(*, replayed: bool) -> CellReportConfirmationResult:
    return CellReportConfirmationResult(
        snapshot={"schema": "cell-report/v2"},
        accepted_workflow=None,
        replayed=replayed,
        requires_caller_commit=not replayed,
    )


def _audit_row(
    identity: AgentTurnIdentity,
    intents: tuple[AgentEffectIntent, AgentEffectIntent, AgentEffectIntent],
) -> AgentConversationLog:
    plan, _key = _plan_and_v2_key(identity, intents)
    payload = uow.build_cell_report_turn_audit_effect_payload(
        turn_identity=identity,
        submission_intent=intents[0],
        reply_intent=intents[2],
    )
    payload["plan_digest"] = plan.plan_digest
    return AgentConversationLog(
        igreja_id=TENANT,
        conversation_id=CONVERSATION,
        evento=uow.CELL_REPORT_TURN_AUDIT_EVENT,
        payload=payload,
    )


def _stage(
    db: _FakeSession,
    *,
    identity: AgentTurnIdentity | None = None,
    intents: tuple[AgentEffectIntent, AgentEffectIntent, AgentEffectIntent]
    | None = None,
    provider_key: str | None = None,
    key_version: AgentCompatibilityKeyVersion = AgentCompatibilityKeyVersion.V2,
    reply_text: str = REPLY_TEXT,
    tenant: uuid.UUID = TENANT,
    conversation: uuid.UUID = CONVERSATION,
):
    current_identity = identity or _identity()
    current_intents = intents or _intents(current_identity, reply_text=reply_text)
    if provider_key is None:
        _plan, provider_key = _plan_and_v2_key(current_identity, current_intents)
    return uow.stage_confirmed_cell_report_turn(
        db,  # type: ignore[arg-type]
        igreja_id=tenant,
        reuniao_id=MEETING,
        conversa_id=conversation,
        ator_pessoa_id=ACTOR,
        command=COMMAND,
        turn_identity=current_identity,
        submission_intent=current_intents[0],
        audit_intent=current_intents[1],
        reply_intent=current_intents[2],
        reply_message_id=REPLY_MESSAGE,
        expected_reply_provider_key=provider_key,
        reply_key_version=key_version,
        reply_text=reply_text,
        now=NOW,
    )


def test_stage_materializes_audit_and_pending_reply_in_caller_transaction(
    monkeypatch: pytest.MonkeyPatch,
    _tenant_scope,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    plan, provider_key = _plan_and_v2_key(identity, intents)
    message = _message(provider_key)
    db = _FakeSession([_Result([message]), _Result([])])
    calls: list[dict[str, object]] = []

    def confirm(session, **kwargs):
        assert session is db
        assert message.agent_reply_state == "ia_executando"
        assert message.texto is None
        assert db.added == []
        calls.append(kwargs)
        return _confirmation(replayed=False)

    monkeypatch.setattr(uow, "confirm_cell_report", confirm)
    result = _stage(
        db,
        identity=identity,
        intents=intents,
        provider_key=provider_key,
    )

    assert result.replayed is False
    assert result.requires_caller_commit is True
    assert result.plan.plan_digest == plan.plan_digest
    assert [item.kind for item in result.plan.effect_intents] == [
        AgentEffectKind.TOOL_CALL,
        AgentEffectKind.AUDIT_EVENT,
        AgentEffectKind.OUTBOUND_REPLY,
    ]
    assert calls == [
        {
            "igreja_id": TENANT,
            "reuniao_id": MEETING,
            "conversa_id": CONVERSATION,
            "ator_pessoa_id": ACTOR,
            "command": COMMAND,
            "turn_identity": identity,
            "submission_intent": intents[0],
            "now": NOW,
            "expected_replayed": False,
        }
    ]
    assert message.agent_reply_state == "ia_pendente"
    assert message.texto == REPLY_TEXT
    assert len(db.added) == 1
    audit = db.added[0]
    assert type(audit) is AgentConversationLog
    assert audit.igreja_id == TENANT
    assert audit.conversation_id == CONVERSATION
    assert audit.evento == uow.CELL_REPORT_TURN_AUDIT_EVENT
    assert audit.payload == {
        **uow.build_cell_report_turn_audit_effect_payload(
            turn_identity=identity,
            submission_intent=intents[0],
            reply_intent=intents[2],
        ),
        "plan_digest": plan.plan_digest,
    }
    assert REPLY_TEXT not in repr(audit.payload)
    assert COMMAND not in repr(audit.payload)
    assert str(TENANT) not in repr(audit.payload)
    assert db.flush_calls == 1
    assert db.commit_calls == db.rollback_calls == 0
    assert _tenant_scope == [(TENANT, "cell_report_turn_uow")]
    assert "Relatório" not in repr(result)


def test_exact_pending_replay_requires_matching_audit_and_does_not_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, provider_key = _plan_and_v2_key(identity, intents)
    message = _message(provider_key, state="ia_pendente", text=REPLY_TEXT)
    audit = _audit_row(identity, intents)
    db = _FakeSession([_Result([message]), _Result([audit])])
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: _confirmation(replayed=True),
    )

    result = _stage(
        db,
        identity=identity,
        intents=intents,
        provider_key=provider_key,
    )

    assert result.replayed is True
    assert result.requires_caller_commit is True
    assert db.added == []
    assert db.flush_calls == 0
    assert db.commit_calls == db.rollback_calls == 0
    assert message.agent_reply_state == "ia_pendente"
    assert message.texto == REPLY_TEXT


def test_second_exact_call_in_same_transaction_still_requires_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, provider_key = _plan_and_v2_key(identity, intents)
    message = _message(provider_key)
    db = _FakeSession([_Result([message]), _Result([])])
    confirmations = iter(
        [_confirmation(replayed=False), _confirmation(replayed=True)]
    )
    expected_replays: list[bool] = []

    def confirm(_session, **kwargs):
        expected_replays.append(kwargs["expected_replayed"])
        return next(confirmations)

    monkeypatch.setattr(uow, "confirm_cell_report", confirm)
    first = _stage(
        db,
        identity=identity,
        intents=intents,
        provider_key=provider_key,
    )
    audit = db.added[0]
    db.responses.extend([_Result([message]), _Result([audit])])
    second = _stage(
        db,
        identity=identity,
        intents=intents,
        provider_key=provider_key,
    )

    assert first.replayed is False
    assert second.replayed is True
    assert first.requires_caller_commit is True
    assert second.requires_caller_commit is True
    assert expected_replays == [False, True]
    assert len(db.added) == 1
    assert db.flush_calls == 1
    assert db.commit_calls == db.rollback_calls == 0
    assert db.in_transaction() is True


@pytest.mark.parametrize(
    ("version", "provider_key"),
    [
        (AgentCompatibilityKeyVersion.V1, "agent-reply:" + "a" * 64),
        (
            AgentCompatibilityKeyVersion.V0,
            "agent-reply:" + "a" * 64 + ":" + "b" * 64,
        ),
    ],
)
def test_locked_legacy_reply_key_is_bound_as_exact_evidence_only(
    monkeypatch: pytest.MonkeyPatch,
    version: AgentCompatibilityKeyVersion,
    provider_key: str,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    message = _message(provider_key)
    db = _FakeSession([_Result([message]), _Result([])])
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: _confirmation(replayed=False),
    )

    result = _stage(
        db,
        identity=identity,
        intents=intents,
        provider_key=provider_key,
        key_version=version,
    )

    assert result.replayed is False
    assert message.agent_reply_state == "ia_pendente"
    assert message.provider_message_id == provider_key


@pytest.mark.parametrize(
    "version",
    [AgentCompatibilityKeyVersion.V1, AgentCompatibilityKeyVersion.V0],
)
def test_malformed_legacy_key_fails_after_locked_row_without_domain_call(
    monkeypatch: pytest.MonkeyPatch,
    version: AgentCompatibilityKeyVersion,
) -> None:
    key = "agent-reply:" + "x" * 64
    message = _message(key)
    db = _FakeSession([_Result([message])])
    called = False

    def confirm(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(uow, "confirm_cell_report", confirm)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, provider_key=key, key_version=version)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID
    assert called is False
    assert len(db.statements) == 1


def test_v2_key_mismatch_fails_before_transaction_or_database() -> None:
    db = _FakeSession([], transaction_active=False)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, provider_key="agent_effect_key_v2_" + "0" * 64)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.REPLY_KEY_INVALID
    assert db.statements == []


@pytest.mark.parametrize(
    ("overrides", "state", "text"),
    [
        ({"igreja_id": OTHER_TENANT}, "ia_executando", None),
        (
            {"id": uuid.UUID("66666666-6666-6666-6666-666666666667")},
            "ia_executando",
            None,
        ),
        ({"conversation_id": OTHER_CONVERSATION}, "ia_executando", None),
        (
            {"provider_message_id": "agent_effect_key_v2_" + "f" * 64},
            "ia_executando",
            None,
        ),
        ({"direcao": "in"}, "ia_executando", None),
        ({"autor": "humano"}, "ia_executando", None),
        ({"tipo": "audio"}, "ia_executando", None),
        ({"media_path": "private/path"}, "ia_executando", None),
        ({"media_mime": "audio/ogg"}, "ia_executando", None),
        ({"media_nome": "private.ogg"}, "ia_executando", None),
        ({"media_tamanho": 1}, "ia_executando", None),
        ({"autor_nome": "Pessoa Privada"}, "ia_executando", None),
        ({"enviado_por": ACTOR}, "ia_executando", None),
        ({}, "ia_executando", "resposta antecipada"),
        ({}, "ia_reservada", None),
        ({}, "ia_em_transporte", REPLY_TEXT),
        ({}, "ia_pendente", "resposta divergente"),
    ],
)
def test_locked_reply_row_shape_and_state_divergence_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, object],
    state: str,
    text: str | None,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key, state=state, text=text, **overrides)
    db = _FakeSession([_Result([message])])
    called = False

    def confirm(*_args, **_kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(uow, "confirm_cell_report", confirm)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_CONFLICT
    )
    assert called is False
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([], uow.CellReportTurnUnitOfWorkErrorCode.REPLY_MESSAGE_NOT_FOUND),
        (
            [object(), object()],
            uow.CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY,
        ),
    ],
)
def test_reply_row_cardinality_fails_closed(
    rows: list[object],
    code: uow.CellReportTurnUnitOfWorkErrorCode,
) -> None:
    db = _FakeSession([_Result(rows)])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db)
    assert raised.value.code is code
    assert db.flush_calls == 0


def test_executing_row_with_existing_audit_is_replay_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    db = _FakeSession(
        [_Result([_message(key)]), _Result([_audit_row(identity, intents)])]
    )
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: pytest.fail("domain call must not run"),
    )
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT
    )


def test_pending_row_without_audit_is_replay_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    db = _FakeSession(
        [_Result([_message(key, state="ia_pendente", text=REPLY_TEXT)]), _Result([])]
    )
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: pytest.fail("domain call must not run"),
    )
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT
    )


def test_malformed_fixed_event_audit_fails_closed() -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key, state="ia_pendente", text=REPLY_TEXT)
    db = _FakeSession([_Result([message]), _Result([object()])])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.AUDIT_CONFLICT


def test_duplicate_fixed_event_audits_conflict() -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key, state="ia_pendente", text=REPLY_TEXT)
    audits = [_audit_row(identity, intents), _audit_row(identity, intents)]
    db = _FakeSession([_Result([message]), _Result(audits)])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.AUDIT_CONFLICT


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("igreja_id", OTHER_TENANT),
        ("conversation_id", OTHER_CONVERSATION),
        ("payload", {"private": "private.person@example.invalid"}),
    ],
)
def test_fixed_event_audit_scope_and_payload_must_match_exactly(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    audit = _audit_row(identity, intents)
    setattr(audit, field, value)
    message = _message(key, state="ia_pendente", text=REPLY_TEXT)
    db = _FakeSession([_Result([message]), _Result([audit])])
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: pytest.fail("domain call must not run"),
    )

    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.AUDIT_CONFLICT
    assert "private.person" not in str(raised.value)
    assert "private.person" not in repr(raised.value)


def test_other_event_does_not_count_as_this_uow_audit_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    other_event = _audit_row(identity, intents)
    other_event.evento = "other_event"
    message = _message(key, state="ia_pendente", text=REPLY_TEXT)
    # The fixed-event query excludes the colliding row represented above.
    db = _FakeSession([_Result([message]), _Result([])])
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: pytest.fail("domain call must not run"),
    )

    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)

    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT
    )
    audit_sql = str(
        db.statements[1].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "agent_conversation_logs.evento = 'cell_report_turn_staged'" in audit_sql
    assert other_event.evento == "other_event"
    assert db.added == []
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("message_state", "message_text", "confirmation_replayed"),
    [
        ("ia_executando", None, True),
        ("ia_pendente", REPLY_TEXT, False),
    ],
)
def test_domain_replay_result_must_match_locked_ledger_state(
    monkeypatch: pytest.MonkeyPatch,
    message_state: str,
    message_text: str | None,
    confirmation_replayed: bool,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    audit_rows = (
        [_audit_row(identity, intents)] if message_state == "ia_pendente" else []
    )
    db = _FakeSession(
        [
            _Result([_message(key, state=message_state, text=message_text)]),
            _Result(audit_rows),
        ]
    )
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: _confirmation(replayed=confirmation_replayed),
    )
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT
    assert db.added == []
    assert db.flush_calls == 0


@pytest.mark.parametrize(
    ("report_state", "message_state", "message_text", "audit_exists"),
    [
        ("pendente", "ia_pendente", REPLY_TEXT, True),
        ("enviado", "ia_executando", None, False),
    ],
)
def test_locked_replay_expectation_rejects_before_any_uow_mutation(
    monkeypatch: pytest.MonkeyPatch,
    report_state: str,
    message_state: str,
    message_text: str | None,
    audit_exists: bool,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key, state=message_state, text=message_text)
    audit = _audit_row(identity, intents) if audit_exists else None
    responses = [
        _Result([message]),
        _Result([audit] if audit is not None else []),
    ]
    db = _FakeSession(responses)
    message_before = (
        message.agent_reply_state,
        message.texto,
        message.provider_message_id,
    )
    audit_before = dict(audit.payload) if audit is not None else None

    def reject_replay_mismatch(_session, **kwargs):
        assert kwargs["expected_replayed"] is audit_exists
        assert report_state in {"pendente", "enviado"}
        raise CellReportApplicationError(
            CellReportApplicationErrorCode.REPLAY_EXPECTATION_MISMATCH
        )

    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        reject_replay_mismatch,
    )
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)

    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.REPLAY_CONFLICT
    )
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert (
        message.agent_reply_state,
        message.texto,
        message.provider_message_id,
    ) == message_before
    if audit is not None:
        assert audit.payload == audit_before
    assert db.added == []
    assert db.flush_calls == 0
    assert db.commit_calls == db.rollback_calls == 0
    assert db.in_transaction() is True


def test_domain_rejection_does_not_stage_reply_or_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key)
    db = _FakeSession([_Result([message]), _Result([])])

    def reject(*_args, **_kwargs):
        raise CellReportApplicationError(
            CellReportApplicationErrorCode.CONFIRMATION_REJECTED
        )

    monkeypatch.setattr(uow, "confirm_cell_report", reject)
    with pytest.raises(CellReportApplicationError):
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert message.agent_reply_state == "ia_executando"
    assert message.texto is None
    assert db.added == []
    assert db.flush_calls == 0


def test_cross_tenant_identity_and_cross_turn_intents_fail_before_database() -> None:
    db = _FakeSession([])
    wrong_identity = _identity(tenant=OTHER_TENANT)
    wrong_intents = _intents(wrong_identity)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(
            db,
            identity=wrong_identity,
            intents=wrong_intents,
            tenant=TENANT,
        )
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )
    assert db.statements == []

    identity = _identity()
    intents = list(_intents(identity))
    other_identity = _identity(inbound=OTHER_INBOUND)
    intents[1] = _intents(other_identity)[1]
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(
            db,
            identity=identity,
            intents=tuple(intents),  # type: ignore[arg-type]
            provider_key="agent_effect_key_v2_" + "0" * 64,
        )
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )
    assert db.statements == []


def test_missing_required_intent_fails_closed_before_database() -> None:
    identity = _identity()
    submission, _audit, reply = _intents(identity)
    db = _FakeSession([])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(
            db,
            identity=identity,
            intents=(submission, None, reply),  # type: ignore[arg-type]
            provider_key="agent_effect_key_v2_" + "0" * 64,
        )
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )
    assert raised.value.__context__ is None
    assert db.statements == []


def test_audit_builder_missing_reply_fails_with_sanitized_contract_error() -> None:
    identity = _identity()
    submission, _audit, _reply = _intents(identity)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        uow.build_cell_report_turn_audit_effect_payload(
            turn_identity=identity,
            submission_intent=submission,
            reply_intent=None,  # type: ignore[arg-type]
        )
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )


@pytest.mark.parametrize(
    ("submission_ordinal", "audit_ordinal", "reply_ordinal"),
    [(1, 0, 0), (0, 1, 0), (0, 0, 1)],
)
def test_nonzero_effect_ordinals_are_rejected_before_database(
    submission_ordinal: int,
    audit_ordinal: int,
    reply_ordinal: int,
) -> None:
    identity = _identity()
    if submission_ordinal or reply_ordinal:
        with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
            _intents(
                identity,
                submission_ordinal=submission_ordinal,
                audit_ordinal=audit_ordinal,
                reply_ordinal=reply_ordinal,
            )
        assert raised.value.code is (
            uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
        )
        return
    intents = _intents(
        identity,
        submission_ordinal=submission_ordinal,
        audit_ordinal=audit_ordinal,
        reply_ordinal=reply_ordinal,
    )
    db = _FakeSession([])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents)
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )
    assert db.statements == []


def test_changed_reply_or_audit_payload_digest_is_rejected_before_database() -> None:
    identity = _identity()
    submission, audit, reply = _intents(identity)
    changed_reply = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.OUTBOUND_REPLY,
        ordinal=0,
        payload=uow.build_cell_report_turn_reply_effect_payload(
            turn_identity=identity,
            submission_intent=submission,
            reply_text="Outra resposta",
        ),
    )
    db = _FakeSession([])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=(submission, audit, changed_reply))
    assert (
        raised.value.code
        is uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )

    changed_audit = build_agent_effect_intent(
        identity,
        kind=AgentEffectKind.AUDIT_EVENT,
        ordinal=0,
        payload={"private": "payload"},
    )
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=(submission, changed_audit, reply))
    assert (
        raised.value.code
        is uow.CellReportTurnUnitOfWorkErrorCode.EFFECT_PLAN_INVALID
    )
    assert db.statements == []


@pytest.mark.parametrize(
    "reply_text",
    [
        "",
        " leading",
        "trailing ",
        "line\nbreak",
        "x" * 32_769,
        "á" * 20_000,
    ],
)
def test_reply_text_bounds_fail_before_database(reply_text: str) -> None:
    db = _FakeSession([])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, reply_text=reply_text)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.INVALID_ARGUMENT
    assert db.statements == []


def test_unicode_reply_within_byte_bound_is_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = "Relatório confirmado com bênção."
    identity = _identity()
    intents = _intents(identity, reply_text=response)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key)
    db = _FakeSession([_Result([message]), _Result([])])
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: _confirmation(replayed=False),
    )
    result = _stage(
        db,
        identity=identity,
        intents=intents,
        provider_key=key,
        reply_text=response,
    )
    assert result.replayed is False
    assert message.texto == response


def _private_statement_error(stage: str) -> StatementError:
    private = "private.person@example.invalid"
    return StatementError(
        f"{stage} failed",
        "SELECT private",
        {"secret": private},
        RuntimeError(private),
    )


@pytest.mark.parametrize("failure", ["execute", "scalars", "add", "flush"])
def test_sqlalchemy_failures_are_sanitized_without_private_exception_chain(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    identity = _identity()
    intents = _intents(identity)
    _plan, key = _plan_and_v2_key(identity, intents)
    message = _message(key)
    error = _private_statement_error(failure)
    kwargs: dict[str, object] = {}
    if failure == "execute":
        kwargs["execute_error"] = error
        responses: list[_Result] = []
    elif failure == "scalars":
        responses = [_Result([message], error=error)]
    else:
        responses = [_Result([message]), _Result([])]
        kwargs[f"{failure}_error"] = error
    db = _FakeSession(responses, **kwargs)  # type: ignore[arg-type]
    monkeypatch.setattr(
        uow,
        "confirm_cell_report",
        lambda *_args, **_kwargs: _confirmation(replayed=False),
    )

    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db, identity=identity, intents=intents, provider_key=key)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY
    assert "private.person" not in str(raised.value)
    assert "private.person" not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_tenant_scope_sqlalchemy_failure_is_sanitized_before_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = _private_statement_error("scope")

    def fail_scope(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(uow, "require_tenant_scope", fail_scope)
    db = _FakeSession([])
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db)
    assert raised.value.code is uow.CellReportTurnUnitOfWorkErrorCode.DATA_INTEGRITY
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert db.statements == []


def test_missing_external_transaction_fails_before_scope_and_queries(
    _tenant_scope,
) -> None:
    db = _FakeSession([], transaction_active=False)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db)
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.TRANSACTION_REQUIRED
    )
    assert _tenant_scope == []
    assert db.statements == []


def test_transaction_sqlalchemy_failure_is_sanitized_before_scope_and_queries(
    _tenant_scope,
) -> None:
    error = _private_statement_error("transaction")
    db = _FakeSession([], transaction_error=error)
    with pytest.raises(uow.CellReportTurnUnitOfWorkError) as raised:
        _stage(db)
    assert raised.value.code is (
        uow.CellReportTurnUnitOfWorkErrorCode.TRANSACTION_REQUIRED
    )
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert "private.person" not in repr(raised.value)
    assert _tenant_scope == []
    assert db.statements == []


def test_sql_statements_lock_explicit_tenant_rows() -> None:
    identity = _identity()
    intents = _intents(identity)
    message_statement = uow._locked_reply_message_statement(
        igreja_id=TENANT,
        conversa_id=CONVERSATION,
        reply_message_id=REPLY_MESSAGE,
    )
    audit_statement = uow._matching_audit_statement(
        igreja_id=TENANT,
        conversa_id=CONVERSATION,
        submission_effect_id=intents[0].effect_id,
    )
    sql = [
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        )
        for statement in (message_statement, audit_statement)
    ]
    assert "messages.igreja_id" in sql[0]
    assert "messages.conversation_id" in sql[0]
    assert "messages.id" in sql[0]
    assert "LIMIT" in sql[0] and "FOR UPDATE" in sql[0]
    assert "agent_conversation_logs.igreja_id" in sql[1]
    assert "agent_conversation_logs.conversation_id" in sql[1]
    assert "agent_conversation_logs.evento" in sql[1]
    assert "payload ->>" in sql[1]
    assert "LIMIT" in sql[1] and "FOR UPDATE" in sql[1]


def test_module_is_offline_flush_only_and_has_no_runtime_wiring() -> None:
    source = inspect.getsource(uow)
    tree = ast.parse(source)
    method_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert method_calls.isdisjoint({"begin", "commit", "rollback", "send"})
    assert all(
        forbidden not in imported
        for imported in imports
        for forbidden in (
            "app.agent.runtime",
            "queue_worker",
            "evolution",
            "requests",
            "httpx",
            "socket",
        )
    )
    assert "confirm_cell_report" in source
    assert "require_tenant_scope" in source


def test_public_payload_builders_have_closed_non_arbitrary_signatures() -> None:
    reply_parameters = set(
        inspect.signature(
            uow.build_cell_report_turn_reply_effect_payload
        ).parameters
    )
    audit_parameters = set(
        inspect.signature(
            uow.build_cell_report_turn_audit_effect_payload
        ).parameters
    )
    assert reply_parameters == {
        "turn_identity",
        "submission_intent",
        "reply_text",
    }
    assert audit_parameters == {
        "turn_identity",
        "submission_intent",
        "reply_intent",
    }
    assert "requires_caller_commit" not in inspect.signature(
        uow.CellReportTurnStageResult
    ).parameters
