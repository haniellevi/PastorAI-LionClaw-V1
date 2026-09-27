"""Offline contract for S3 WhatsApp privilege facts."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.services.whatsapp_privilege import (
    PrivilegeContext,
    PrivilegeResolutionKind,
    build_privilege_scope_fingerprint,
    build_privilege_context_fingerprint,
    parse_privilege_role,
    resolve_whatsapp_privilege_context,
)


def test_privilege_roles_are_closed_and_do_not_infer_authority_from_unknown_input() -> None:
    assert PrivilegeResolutionKind.PUBLIC.value == "public"
    assert PrivilegeResolutionKind.HUMAN_REQUIRED.value == "human_required"
    assert parse_privilege_role("pastor") == "pastor"

    for value in ("", "lider_por_telefone", "financeiro", True, None):
        with pytest.raises(ValueError):
            parse_privilege_role(value)


def test_context_fingerprint_binds_credential_scope_and_optional_proof() -> None:
    secret = "s3-synthetic-secret"
    context = PrivilegeContext(
        igreja_id=uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
        conversation_id=uuid.UUID("00000000-0000-0000-0000-0000000000c1"),
        inbound_message_id=uuid.UUID("00000000-0000-0000-0000-0000000000d1"),
        pessoa_id=uuid.UUID("00000000-0000-0000-0000-0000000000f1"),
        app_user_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
        roles=frozenset({"pastor"}),
        role_snapshot=((uuid.UUID("00000000-0000-0000-0000-0000000000e1"), "pastor"),),
        owned_cell_ids=(uuid.UUID("00000000-0000-0000-0000-0000000000c2"),),
        credential_fingerprint="1" * 64,
        phone_fingerprint="2" * 64,
        authorization_fingerprint="4" * 64,
        proof_id=uuid.UUID("00000000-0000-0000-0000-0000000000a2"),
        proof_until=dt.datetime(2026, 9, 27, 12, 15, tzinfo=dt.timezone.utc),
        sensitive=True,
        scope_fingerprint="",
        context_fingerprint="",
    )
    fingerprint = build_privilege_context_fingerprint(secret, context)
    changed = replace(context, credential_fingerprint="3" * 64)

    assert len(fingerprint) == 64
    assert fingerprint != build_privilege_context_fingerprint(secret, changed)
    assert build_privilege_scope_fingerprint(secret, context) == build_privilege_scope_fingerprint(
        secret,
        replace(context, inbound_message_id=uuid.uuid4()),
    )


class _Result:
    def __init__(self, *, scalar=None, scalars=()) -> None:
        self._scalar = scalar
        self._scalars = list(scalars)

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class _Session:
    def __init__(self, results) -> None:
        self._results = list(results)

    def execute(self, _statement):
        if not self._results:
            raise AssertionError("consulta inesperada")
        return self._results.pop(0)


_IGREJA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_CONVERSA = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_INBOUND = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
_PESSOA = uuid.UUID("00000000-0000-0000-0000-0000000000f1")
_USER = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


def test_resolver_keeps_absence_public_and_duplicate_phone_human(monkeypatch) -> None:
    import app.services.whatsapp_privilege as privilege

    monkeypatch.setattr(privilege, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        privilege,
        "get_settings",
        lambda: SimpleNamespace(effective_session_secret="s3-synthetic-secret"),
    )
    inbound = SimpleNamespace(
        id=_INBOUND, igreja_id=_IGREJA, conversation_id=_CONVERSA, direcao="in"
    )
    conversation = SimpleNamespace(
        id=_CONVERSA,
        igreja_id=_IGREJA,
        pessoa_id=None,
        telefone="5500000000000",
        estado="ia",
        assumido_por=None,
    )
    igreja = SimpleNamespace(id=_IGREJA, status="ativa")
    config = SimpleNamespace(id=uuid.uuid4(), igreja_id=_IGREJA, ativo=True)

    public = resolve_whatsapp_privilege_context(
        _Session(
            [
                _Result(scalar=inbound),
                _Result(scalar=conversation),
                _Result(scalar=igreja),
                _Result(scalar=config),
                _Result(scalars=[]),
            ]
        ),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=_INBOUND,
    )
    assert public.kind is PrivilegeResolutionKind.PUBLIC

    duplicate = SimpleNamespace(
        id=_PESSOA,
        igreja_id=_IGREJA,
        telefone="5500000000000",
        arquivada_em=None,
        optout=False,
        sem_interesse=False,
    )
    human = resolve_whatsapp_privilege_context(
        _Session(
            [
                _Result(scalar=inbound),
                _Result(scalar=conversation),
                _Result(scalar=igreja),
                _Result(scalar=config),
                _Result(
                    scalars=[
                        duplicate,
                        SimpleNamespace(
                            id=uuid.uuid4(),
                            igreja_id=_IGREJA,
                            telefone="5500000000000",
                            arquivada_em=None,
                            optout=False,
                            sem_interesse=False,
                        ),
                    ]
                ),
            ]
        ),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=_INBOUND,
    )
    assert human.kind is PrivilegeResolutionKind.HUMAN_REQUIRED


def test_suffix_candidate_limit_fails_closed_before_selecting_one_phone_match(monkeypatch) -> None:
    import app.services.whatsapp_privilege as privilege

    monkeypatch.setattr(privilege, "require_tenant_scope", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        privilege,
        "get_settings",
        lambda: SimpleNamespace(effective_session_secret="s3-synthetic-secret"),
    )
    inbound = SimpleNamespace(
        id=_INBOUND, igreja_id=_IGREJA, conversation_id=_CONVERSA, direcao="in"
    )
    conversation = SimpleNamespace(
        id=_CONVERSA,
        igreja_id=_IGREJA,
        pessoa_id=None,
        telefone="5500000000000",
        estado="ia",
        assumido_por=None,
    )
    igreja = SimpleNamespace(id=_IGREJA, status="ativa")
    config = SimpleNamespace(id=uuid.uuid4(), igreja_id=_IGREJA, ativo=True)
    one_exact = SimpleNamespace(
        id=_PESSOA,
        igreja_id=_IGREJA,
        telefone="5500000000000",
        arquivada_em=None,
        optout=False,
        sem_interesse=False,
    )
    suffix_only = [
        SimpleNamespace(
            id=uuid.uuid4(),
            igreja_id=_IGREJA,
            telefone=f"55000000{i:04d}",
            arquivada_em=None,
            optout=False,
            sem_interesse=False,
        )
        for i in range(2)
    ]
    result = resolve_whatsapp_privilege_context(
        _Session(
            [
                _Result(scalar=inbound),
                _Result(scalar=conversation),
                _Result(scalar=igreja),
                _Result(scalar=config),
                _Result(scalars=[one_exact, *suffix_only]),
            ]
        ),
        igreja_id=_IGREJA,
        conversation_id=_CONVERSA,
        inbound_message_id=_INBOUND,
    )
    assert result.kind is PrivilegeResolutionKind.HUMAN_REQUIRED


def test_privilege_flag_is_inert_until_the_exact_tenant_is_listed(monkeypatch) -> None:
    import app.services.whatsapp_privilege as privilege

    monkeypatch.delenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", raising=False)
    assert not privilege.privilege_enabled_from_environment(_IGREJA)

    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", str(_IGREJA))
    assert privilege.privilege_enabled_from_environment(_IGREJA)
    assert not privilege.privilege_enabled_from_environment(uuid.uuid4())

    monkeypatch.setenv("AGENT_PRIVILEGE_ENABLED_IGREJA_IDS", f"{_IGREJA},not-a-uuid")
    assert not privilege.privilege_enabled_from_environment(_IGREJA)
