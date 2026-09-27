"""Unit contract for S3's tenant-bound identity proof service."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from app.db.models import AgentIdentityChallenge, AgentIdentityProof
from app.services.agent_identity import (
    AgentIdentityConfirmationDenied,
    ProofIntegrityInput,
    build_credential_fingerprint,
    build_proof_integrity_hmac,
    build_roles_fingerprint,
    confirm_identity_challenge,
    issue_identity_challenge,
    parse_challenge_code,
    resolve_confirmed_identity,
    verify_proof_integrity_hmac,
)
from app.db.models import (
    AgentConfig,
    AppUser,
    Celula,
    ConsentRecord,
    Conversation,
    Igreja,
    Message,
    Pessoa,
    UserRole,
)


_SECRET = "s3-test-session-secret"
_NOW = dt.datetime(2026, 9, 26, 15, 0, tzinfo=dt.timezone.utc)
_IGREJA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_CONVERSA = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
_APP_USER = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
_CHALLENGE = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_ROLE = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


def _proof_input(**changes: object) -> ProofIntegrityInput:
    values: dict[str, object] = {
        "challenge_id": _CHALLENGE,
        "igreja_id": _IGREJA,
        "app_user_id": _APP_USER,
        "pessoa_id": _PESSOA,
        "conversation_id": _CONVERSA,
        "confirmed_at": _NOW,
        "confirmed_until": _NOW + dt.timedelta(minutes=15),
        "credential_fingerprint": build_credential_fingerprint(
            _SECRET,
            clerk_user_id="clerk_synthetic_a",
            password_changed_at=None,
        ),
        "roles_fingerprint": build_roles_fingerprint(
            _SECRET,
            roles=((_ROLE, "pastor"),),
        ),
    }
    values.update(changes)
    return ProofIntegrityInput(**values)


def test_challenge_code_requires_exact_lowercase_canonical_uuid() -> None:
    assert parse_challenge_code(str(_CHALLENGE)) == _CHALLENGE
    for invalid in (
        str(_CHALLENGE).upper(),
        "{" + str(_CHALLENGE) + "}",
        "perfil:" + str(_CHALLENGE),
        str(_CHALLENGE) + " ",
        "not-a-challenge",
    ):
        assert parse_challenge_code(invalid) is None


def test_proof_hmac_binds_every_identity_and_snapshot_component() -> None:
    source = _proof_input()
    mac = build_proof_integrity_hmac(_SECRET, source)
    assert verify_proof_integrity_hmac(_SECRET, source, mac)

    variants = (
        _proof_input(challenge_id=uuid.uuid4()),
        _proof_input(igreja_id=uuid.uuid4()),
        _proof_input(app_user_id=uuid.uuid4()),
        _proof_input(pessoa_id=uuid.uuid4()),
        _proof_input(conversation_id=uuid.uuid4()),
        _proof_input(confirmed_at=_NOW + dt.timedelta(seconds=1)),
        _proof_input(confirmed_until=_NOW + dt.timedelta(minutes=14)),
        _proof_input(credential_fingerprint="0" * 64),
        _proof_input(roles_fingerprint="1" * 64),
    )
    assert all(not verify_proof_integrity_hmac(_SECRET, value, mac) for value in variants)


def test_proof_hmac_canonicalizes_equivalent_timezone_offsets_with_microseconds() -> None:
    reference = _proof_input()
    offset = dt.timezone(dt.timedelta(hours=-3))
    shifted = _proof_input(
        confirmed_at=reference.confirmed_at.astimezone(offset),
        confirmed_until=reference.confirmed_until.astimezone(offset),
    )
    assert build_proof_integrity_hmac(_SECRET, reference) == build_proof_integrity_hmac(
        _SECRET, shifted
    )


def test_role_fingerprint_detects_remove_and_reinsert_with_same_label() -> None:
    first = build_roles_fingerprint(_SECRET, roles=((_ROLE, "lider_celula"),))
    reinserted = build_roles_fingerprint(
        _SECRET,
        roles=((uuid.UUID("00000000-0000-0000-0000-0000000000e2"), "lider_celula"),),
    )
    assert first != reinserted


def test_models_keep_tenant_composite_links_and_immutable_proof_shape() -> None:
    challenge_constraints = {constraint.name for constraint in AgentIdentityChallenge.__table__.constraints}
    proof_constraints = {constraint.name for constraint in AgentIdentityProof.__table__.constraints}

    assert "agent_identity_challenges_tenant_conversation_fkey" in challenge_constraints
    assert "agent_identity_challenges_tenant_pessoa_fkey" in challenge_constraints
    assert "agent_identity_challenges_inbound_once_key" in challenge_constraints
    assert "agent_identity_proofs_challenge_once_key" in proof_constraints
    assert "agent_identity_proofs_tenant_challenge_fkey" in proof_constraints


@pytest.mark.parametrize("value", [None, "", 3, True])
def test_challenge_code_rejects_noncanonical_types(value: object) -> None:
    assert parse_challenge_code(value) is None


class _Result:
    def __init__(self, *, scalar=None, scalars=()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _ScriptedSession:
    def __init__(self, results) -> None:
        self._results = list(results)
        self.added: list[object] = []

    def execute(self, _statement):
        if not self._results:
            raise AssertionError("consulta inesperada")
        return self._results.pop(0)

    def add(self, value) -> None:
        self.added.append(value)

    def flush(self) -> None:
        for value in self.added:
            if getattr(value, "id", None) is None:
                value.id = uuid.UUID("00000000-0000-0000-0000-0000000000d2")


def _identity_rows():
    igreja = Igreja(id=_IGREJA, nome="Igreja sintética", status="ativa")
    pessoa = Pessoa(
        id=_PESSOA,
        igreja_id=_IGREJA,
        nome="Pessoa sintética",
        telefone="5500000000000",
        optout=False,
        sem_interesse=False,
        arquivada_em=None,
    )
    conversation = Conversation(
        id=_CONVERSA,
        igreja_id=_IGREJA,
        pessoa_id=_PESSOA,
        telefone="5500000000000",
        estado="ia",
    )
    config = AgentConfig(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000a2"),
        igreja_id=_IGREJA,
        comportamento="perfil sintético",
        ativo=True,
    )
    consent = ConsentRecord(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000a3"),
        igreja_id=_IGREJA,
        pessoa_id=_PESSOA,
        termo_versao="s3-synthetic",
        aceite_em=_NOW,
    )
    challenge = AgentIdentityChallenge(
        id=_CHALLENGE,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        pessoa_id=_PESSOA,
        issued_from_message_id=uuid.UUID("00000000-0000-0000-0000-0000000000a4"),
        issued_at=_NOW,
        challenge_expires_at=_NOW + dt.timedelta(minutes=5),
        sequence=1,
    )
    app_user = AppUser(
        id=_APP_USER,
        igreja_id=_IGREJA,
        pessoa_id=_PESSOA,
        clerk_user_id="clerk_synthetic_a",
        nome="Operador sintético",
        email="synthetic@example.invalid",
        status="ativo",
        password_changed_at=None,
    )
    role = UserRole(
        id=_ROLE,
        igreja_id=_IGREJA,
        user_id=_APP_USER,
        papel="pastor",
    )
    credential = build_credential_fingerprint(
        _SECRET,
        clerk_user_id=app_user.clerk_user_id,
        password_changed_at=None,
    )
    roles = build_roles_fingerprint(_SECRET, roles=((role.id, role.papel),))
    proof_input = _proof_input(
        credential_fingerprint=credential,
        roles_fingerprint=roles,
    )
    proof = AgentIdentityProof(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000a5"),
        igreja_id=_IGREJA,
        challenge_id=_CHALLENGE,
        conversation_id=_CONVERSA,
        pessoa_id=_PESSOA,
        confirmed_by_app_user_id=_APP_USER,
        confirmed_at=_NOW,
        confirmed_until=_NOW + dt.timedelta(minutes=15),
        credential_fingerprint=credential,
        roles_fingerprint=roles,
        integrity_hmac=build_proof_integrity_hmac(_SECRET, proof_input),
    )
    return igreja, pessoa, conversation, config, consent, challenge, app_user, role, proof


def test_resolve_revalidates_mutable_gates_and_hmac(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    igreja, pessoa, conversation, config, consent, challenge, app_user, role, proof = _identity_rows()
    cell_id = uuid.UUID("00000000-0000-0000-0000-0000000000c2")
    session = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=igreja),
            _Result(scalar=pessoa),
            _Result(scalar=config),
            _Result(scalar=consent),
            _Result(scalar=challenge),
            _Result(scalar=proof),
            _Result(scalar=app_user, scalars=[app_user]),
            _Result(scalars=[role]),
            _Result(scalars=[cell_id]),
        ]
    )

    context = resolve_confirmed_identity(
        session,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        session_secret=_SECRET,
        now=_NOW + dt.timedelta(seconds=1),
        term_version="s3-synthetic",
    )

    assert context is not None
    assert context.roles == frozenset({"pastor"})
    assert context.owned_cell_ids == (cell_id,)

    pessoa.optout = True
    blocked_session = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=igreja),
            _Result(scalar=pessoa),
        ]
    )
    assert (
        resolve_confirmed_identity(
            blocked_session,
            igreja_id=_IGREJA,
            conversation_id=_CONVERSA,
            session_secret=_SECRET,
            now=_NOW + dt.timedelta(seconds=1),
            term_version="s3-synthetic",
        )
        is None
    )


def test_issue_replays_same_inbound_under_conversation_lock(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, _, _, _ = _identity_rows()
    inbound_id = challenge.issued_from_message_id
    inbound = Message(
        id=inbound_id,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        direcao="in",
        autor="contato",
        texto="#perfil",
    )
    session = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=pessoa),
            _Result(scalar=inbound),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )
    issued = issue_identity_challenge(
        session,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=inbound_id,
        now=_NOW,
    )
    assert issued.sequence == 1
    assert issued.expires_at == _NOW + dt.timedelta(minutes=5)
    assert sum(isinstance(row, AgentIdentityChallenge) for row in session.added) == 1

    replay = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=pessoa),
            _Result(scalar=inbound),
            _Result(scalar=challenge),
        ]
    )
    replayed = issue_identity_challenge(
        replay,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=inbound_id,
        now=_NOW + dt.timedelta(seconds=1),
    )
    assert replayed.challenge == str(challenge.id)
    assert replayed.sequence == 1
    assert replay.added == []


def test_issue_captures_ttl_after_its_short_locks(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, _, _, _ = _identity_rows()
    inbound = Message(
        id=challenge.issued_from_message_id,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        direcao="in",
        autor="contato",
        texto="#perfil",
    )
    clock = {"now": _NOW}
    original_locked = identity._locked_one_or_none

    def _delayed_lock(*args, **kwargs):
        result = original_locked(*args, **kwargs)
        clock["now"] = _NOW + dt.timedelta(minutes=2)
        return result

    monkeypatch.setattr(identity, "_locked_one_or_none", _delayed_lock)
    monkeypatch.setattr(identity, "_now", lambda _value: clock["now"])
    session = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=pessoa),
            _Result(scalar=inbound),
            _Result(scalar=None),
            _Result(scalar=None),
        ]
    )

    issued = issue_identity_challenge(
        session,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=inbound.id,
        now=None,
    )

    assert issued.expires_at == _NOW + dt.timedelta(minutes=7)
    assert session.added[0].issued_at == _NOW + dt.timedelta(minutes=2)


def test_confirm_requires_current_single_active_panel_link(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )
    confirmation = confirm_identity_challenge(
        session,
        igreja_id=_IGREJA,
        app_user_id=_APP_USER,
        clerk_user_id="clerk_synthetic_a",
        session_claims={"iat": _NOW.timestamp(), "exp": (_NOW + dt.timedelta(hours=1)).timestamp()},
        challenge=str(_CHALLENGE),
        session_secret=_SECRET,
        now=_NOW,
    )
    assert confirmation.confirmed_until == _NOW + dt.timedelta(minutes=15)
    proofs = [row for row in session.added if isinstance(row, AgentIdentityProof)]
    assert len(proofs) == 1
    assert proofs[0].integrity_hmac

    duplicate_user = AppUser(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000b2"),
        igreja_id=_IGREJA,
        pessoa_id=_PESSOA,
        clerk_user_id="clerk_synthetic_b",
        nome="Outro sintético",
        email="other@example.invalid",
        status="ativo",
    )
    denied = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user, duplicate_user]),
        ]
    )
    with pytest.raises(AgentIdentityConfirmationDenied):
        confirm_identity_challenge(
            denied,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={"iat": _NOW.timestamp(), "exp": (_NOW + dt.timedelta(hours=1)).timestamp()},
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=_NOW,
        )


def test_confirm_rechecks_password_change_against_server_verified_iat(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    app_user.password_changed_at = _NOW
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )
    with pytest.raises(AgentIdentityConfirmationDenied):
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={
                "iat": (_NOW - dt.timedelta(seconds=6)).timestamp(),
                "exp": (_NOW + dt.timedelta(hours=1)).timestamp(),
            },
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=_NOW,
        )


def test_confirm_rechecks_session_expiry_after_waiting_for_locks(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    clock = {"now": _NOW}
    original_locked = identity._locked_one_or_none
    lock_count = 0

    def _delayed_lock(*args, **kwargs):
        nonlocal lock_count
        result = original_locked(*args, **kwargs)
        lock_count += 1
        if lock_count == 1:
            clock["now"] = _NOW + dt.timedelta(minutes=2)
        return result

    monkeypatch.setattr(identity, "_locked_one_or_none", _delayed_lock)
    monkeypatch.setattr(identity, "_now", lambda _value: clock["now"])
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )

    with pytest.raises(AgentIdentityConfirmationDenied):
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={
                "iat": _NOW.timestamp(),
                "exp": (_NOW + dt.timedelta(minutes=1)).timestamp(),
            },
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=None,
        )
    assert not any(isinstance(row, AgentIdentityProof) for row in session.added)


def test_confirm_rechecks_challenge_expiry_after_waiting_for_locks(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    clock = {"now": _NOW}
    original_locked = identity._locked_one_or_none
    lock_count = 0

    def _delayed_lock(*args, **kwargs):
        nonlocal lock_count
        result = original_locked(*args, **kwargs)
        lock_count += 1
        if lock_count == 1:
            clock["now"] = _NOW + dt.timedelta(minutes=6)
        return result

    monkeypatch.setattr(identity, "_locked_one_or_none", _delayed_lock)
    monkeypatch.setattr(identity, "_now", lambda _value: clock["now"])
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )

    with pytest.raises(AgentIdentityConfirmationDenied):
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={
                "iat": _NOW.timestamp(),
                "exp": (_NOW + dt.timedelta(hours=1)).timestamp(),
            },
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=None,
        )
    assert not any(isinstance(row, AgentIdentityProof) for row in session.added)


def test_confirm_rechecks_password_change_after_its_last_lock(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    original_role_snapshot = identity._role_snapshot

    def _role_snapshot_after_wait(*args, **kwargs):
        app_user.password_changed_at = _NOW
        return original_role_snapshot(*args, **kwargs)

    monkeypatch.setattr(identity, "_role_snapshot", _role_snapshot_after_wait)
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )

    with pytest.raises(AgentIdentityConfirmationDenied):
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={
                "iat": (_NOW - dt.timedelta(seconds=6)).timestamp(),
                "exp": (_NOW + dt.timedelta(hours=1)).timestamp(),
            },
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=_NOW,
        )
    assert not any(isinstance(row, AgentIdentityProof) for row in session.added)


@pytest.mark.parametrize("invalid_exp", [None, True, "1790010000", float("nan"), 10**400])
def test_confirm_rejects_nonfinite_or_untyped_exp_after_locks(monkeypatch, invalid_exp) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )

    with pytest.raises(AgentIdentityConfirmationDenied):
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={"iat": _NOW.timestamp(), "exp": invalid_exp},
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=_NOW,
        )
    assert not any(isinstance(row, AgentIdentityProof) for row in session.added)


def test_resolve_fails_closed_when_a_second_active_panel_link_appears(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    igreja, pessoa, conversation, config, consent, challenge, app_user, role, proof = _identity_rows()
    duplicate = AppUser(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000b2"),
        igreja_id=_IGREJA,
        pessoa_id=_PESSOA,
        clerk_user_id="clerk_synthetic_second",
        nome="Operador sintético dois",
        email="synthetic-two@example.invalid",
        status="ativo",
    )
    session = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=igreja),
            _Result(scalar=pessoa),
            _Result(scalar=config),
            _Result(scalar=consent),
            _Result(scalar=challenge),
            _Result(scalar=proof),
            _Result(scalar=app_user, scalars=[app_user, duplicate]),
            _Result(scalars=[role]),
            _Result(scalars=[]),
        ]
    )

    assert (
        resolve_confirmed_identity(
            session,
            igreja_id=_IGREJA,
            conversation_id=_CONVERSA,
            session_secret=_SECRET,
            now=_NOW + dt.timedelta(seconds=1),
            term_version="s3-synthetic",
        )
        is None
    )


def test_identity_audit_uses_only_enumerated_sanitized_metadata(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        identity,
        "log_agent_event",
        lambda _session, **kwargs: events.append(kwargs),
        raising=False,
    )
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    inbound = Message(
        id=challenge.issued_from_message_id,
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        direcao="in",
        autor="contato",
        texto="#perfil",
    )
    issue_identity_challenge(
        _ScriptedSession(
            [
                _Result(scalar=conversation),
                _Result(scalar=pessoa),
                _Result(scalar=inbound),
                _Result(scalar=None),
                _Result(scalar=None),
            ]
        ),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=inbound.id,
        now=_NOW,
    )
    confirm_identity_challenge(
        _ScriptedSession(
            [
                _Result(scalar=challenge),
                _Result(scalar=conversation),
                _Result(scalar=challenge),
                _Result(scalar=challenge),
                _Result(scalar=None),
                _Result(scalar=pessoa),
                _Result(scalars=[app_user]),
                _Result(scalars=[role]),
            ]
        ),
        igreja_id=_IGREJA,
        app_user_id=_APP_USER,
        clerk_user_id="clerk_synthetic_a",
        session_claims={"iat": _NOW.timestamp(), "exp": (_NOW + dt.timedelta(hours=1)).timestamp()},
        challenge=str(_CHALLENGE),
        session_secret=_SECRET,
        now=_NOW,
    )

    assert [event["evento"] for event in events] == [
        "agent_identity_challenge",
        "agent_identity_confirmation",
    ]
    for event in events:
        payload = event["payload"]
        assert isinstance(payload, dict)
        assert payload["flow_version"] == "s3_identity_v1"
        assert payload["result"] in {"issued", "confirmed"}
        assert type(payload["latency_ms"]) is int
        serialized = repr(payload)
        for forbidden in (
            str(_CHALLENGE),
            "clerk_synthetic_a",
            "5500000000000",
            _SECRET,
        ):
            assert forbidden not in serialized


def test_confirmation_denial_audits_only_fixed_expiry_metadata(monkeypatch) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    events: list[dict[str, object]] = []
    monkeypatch.setattr(
        identity,
        "log_agent_event",
        lambda _session, **kwargs: events.append(kwargs),
        raising=False,
    )
    _, pessoa, conversation, _, _, challenge, app_user, role, _ = _identity_rows()
    session = _ScriptedSession(
        [
            _Result(scalar=challenge),
            _Result(scalar=conversation),
            _Result(scalar=challenge),
            _Result(scalar=challenge),
            _Result(scalar=None),
            _Result(scalar=pessoa),
            _Result(scalars=[app_user]),
            _Result(scalars=[role]),
        ]
    )
    with pytest.raises(AgentIdentityConfirmationDenied) as denied:
        confirm_identity_challenge(
            session,
            igreja_id=_IGREJA,
            app_user_id=_APP_USER,
            clerk_user_id="clerk_synthetic_a",
            session_claims={
                "iat": _NOW.timestamp(),
                "exp": (_NOW - dt.timedelta(seconds=1)).timestamp(),
            },
            challenge=str(_CHALLENGE),
            session_secret=_SECRET,
            now=_NOW,
    )

    assert denied.value.audit_logged is True
    assert len(events) == 1
    event = events[0]
    assert event["igreja_id"] == _IGREJA
    assert event["conversation_id"] == _CONVERSA
    assert event["evento"] == "agent_identity_confirmation"
    payload = event["payload"]
    assert set(payload) == {"flow_version", "result", "latency_ms"}
    assert payload["flow_version"] == "s3_identity_v1"
    assert payload["result"] == "expired"
    assert type(payload["latency_ms"]) is int
    assert str(_CHALLENGE) not in repr(payload)
    assert "clerk_synthetic_a" not in repr(payload)
    assert _SECRET not in repr(payload)


def test_confirmation_scope_reapplies_only_server_verified_sub_after_begin(monkeypatch) -> None:
    import app.services.agent_identity as identity

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        identity,
        "set_tenant_context",
        lambda session, sub: calls.append(("claim", sub)),
    )
    monkeypatch.setattr(
        identity,
        "require_tenant_scope",
        lambda session, **kwargs: calls.append(("scope", kwargs["expected_igreja_id"])),
    )
    identity._require_scope(object(), _IGREJA, clerk_user_id="clerk_synthetic_a")
    assert calls == [("claim", "clerk_synthetic_a"), ("scope", _IGREJA)]


@pytest.mark.parametrize(
    ("change", "result_count"),
    (
        ("igreja_bloqueada", 2),
        ("config_inativa", 4),
        ("termo_invalido", 5),
    ),
)
def test_resolve_fails_closed_for_current_billing_config_or_term_gate(
    monkeypatch, change: str, result_count: int
) -> None:
    import app.services.agent_identity as identity

    monkeypatch.setattr(identity, "_require_scope", lambda *args, **kwargs: None)
    igreja, pessoa, conversation, config, consent, *_ = _identity_rows()
    if change == "igreja_bloqueada":
        igreja.status = "suspensa"
    elif change == "config_inativa":
        config.ativo = False
    else:
        consent.termo_versao = "versao-anterior"
    session = _ScriptedSession(
        [
            _Result(scalar=conversation),
            _Result(scalar=igreja),
            _Result(scalar=pessoa),
            _Result(scalar=config),
            _Result(scalar=consent),
        ][:result_count]
    )
    assert (
        resolve_confirmed_identity(
            session,
            igreja_id=_IGREJA,
            conversation_id=_CONVERSA,
            session_secret=_SECRET,
            now=_NOW,
            term_version="s3-synthetic",
        )
        is None
    )
