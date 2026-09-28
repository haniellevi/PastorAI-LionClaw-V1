"""Deterministic, non-HTTP state transitions for the S2b secretary offer."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.agent import runtime
from app.db.models import AgentConfig, Conversation, Igreja, Message, Pessoa
from app.services.secretaria_offer import (
    OFFER_ACCEPT_WAITING,
    OFFER_CANCELLED,
    OFFER_EXPIRED,
    OFFER_PENDING,
    OFFER_PREPARED,
    promote_secretaria_offer_after_delivery,
    resolve_secretaria_offer_inbound,
)


_TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_CONVERSATION = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
_OUTBOUND = uuid.UUID("00000000-0000-0000-0000-0000000000f1")


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value

    def scalar_one(self):
        return self.value

    def one_or_none(self):
        return self.value


class _OfferSession:
    def __init__(self, *, now: dt.datetime | None = None) -> None:
        self.now = now

    def execute(self, statement):
        if "clock_timestamp" in str(statement):
            return _Result(self.now)
        return _Result(_OUTBOUND)


class _MissingAnchorOfferSession(_OfferSession):
    def execute(self, statement):
        if "clock_timestamp" in str(statement):
            return _Result(self.now)
        return _Result(None)


class _RuntimeOfferSession:
    """Minimal runtime session proving the non-Tier-A handoff path is durable."""

    def __init__(
        self,
        *,
        conversation,
        pessoa,
        igreja,
        config,
        inbound_text: str = "sim",
        offer_anchor_exists: bool = True,
    ) -> None:
        self.conversation = conversation
        self.pessoa = pessoa
        self.igreja = igreja
        self.config = config
        self.inbound_text = inbound_text
        self.offer_anchor_exists = offer_anchor_exists
        self.message_reads = 0
        self.commits = 0

    def execute(self, statement, _params=None):
        descriptions = list(getattr(statement, "column_descriptions", []) or [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is Conversation:
            return _Result(self.conversation)
        if entity is Pessoa:
            return _Result(self.pessoa)
        if entity is Igreja:
            return _Result(self.igreja)
        if entity is AgentConfig:
            return _Result(self.config)
        if entity is Message:
            self.message_reads += 1
            if self.message_reads == 1:
                return _Result((dt.datetime(2029, 1, 1, tzinfo=dt.UTC), self.inbound_text))
            return _Result(_OUTBOUND if self.offer_anchor_exists else None)
        if "clock_timestamp" in str(statement):
            return _Result(dt.datetime(2029, 1, 1, tzinfo=dt.UTC))
        return _Result(None)

    def commit(self):
        self.commits += 1


def _conversation(*, state: str, expiry: dt.datetime | None = None, response=None):
    return SimpleNamespace(
        id=_CONVERSATION,
        igreja_id=_TENANT,
        secretaria_oferta_estado=state,
        secretaria_oferta_message_id=_OUTBOUND,
        secretaria_oferta_expira_em=expiry,
        secretaria_oferta_resposta_message_id=response,
    )


def test_unrelated_message_cancels_offer_and_continues_normal_turn() -> None:
    conversation = _conversation(
        state=OFFER_PENDING,
        expiry=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
    )

    result = resolve_secretaria_offer_inbound(
        _OfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=uuid.uuid4(),
        current_text="Preciso de oração pela minha família",
        now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
    )

    assert result.continue_turn is True
    assert result.terminal is False
    assert conversation.secretaria_oferta_estado == OFFER_CANCELLED
    assert conversation.secretaria_oferta_resposta_message_id is None


def test_expired_offer_continues_the_unrelated_question() -> None:
    conversation = _conversation(
        state=OFFER_PENDING,
        expiry=dt.datetime(2028, 1, 1, tzinfo=dt.UTC),
    )

    result = resolve_secretaria_offer_inbound(
        _OfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=uuid.uuid4(),
        current_text="Que horas é o culto?",
        consent_needs_reaccept=True,
        now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
    )

    assert result.continue_turn is True
    assert result.terminal is False
    assert conversation.secretaria_oferta_estado == OFFER_EXPIRED
    assert conversation.secretaria_oferta_resposta_message_id is None


def test_expired_offer_binds_stale_term_acceptance_and_retries_terminally() -> None:
    conversation = _conversation(
        state=OFFER_PENDING,
        expiry=dt.datetime(2028, 1, 1, tzinfo=dt.UTC),
    )
    inbound = uuid.uuid4()
    now = dt.datetime(2029, 1, 1, tzinfo=dt.UTC)

    first = resolve_secretaria_offer_inbound(
        _OfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=inbound,
        current_text="sim concordo",
        consent_needs_reaccept=True,
        now=now,
    )
    retry = resolve_secretaria_offer_inbound(
        _OfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=inbound,
        current_text="sim concordo",
        consent_needs_reaccept=True,
        now=now,
    )

    assert first.terminal is True
    assert first.continue_turn is False
    assert retry.terminal is True
    assert conversation.secretaria_oferta_estado == OFFER_EXPIRED
    assert conversation.secretaria_oferta_resposta_message_id == inbound


def test_missing_offer_anchor_binds_stale_term_acceptance() -> None:
    conversation = _conversation(
        state=OFFER_PENDING,
        expiry=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
    )
    inbound = uuid.uuid4()

    first = resolve_secretaria_offer_inbound(
        _MissingAnchorOfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=inbound,
        current_text="sim concordo",
        consent_needs_reaccept=True,
        now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
    )
    retry = resolve_secretaria_offer_inbound(
        _MissingAnchorOfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=inbound,
        current_text="sim concordo",
        consent_needs_reaccept=True,
        now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
    )

    assert first.terminal is True
    assert first.continue_turn is False
    assert retry.terminal is True
    assert conversation.secretaria_oferta_estado == OFFER_CANCELLED
    assert conversation.secretaria_oferta_resposta_message_id == inbound


def test_active_offer_binds_stale_term_acceptance_not_equal_to_sim() -> None:
    for state, expiry in (
        (OFFER_PREPARED, None),
        (OFFER_ACCEPT_WAITING, None),
        (OFFER_PENDING, dt.datetime(2030, 1, 1, tzinfo=dt.UTC)),
    ):
        conversation = _conversation(state=state, expiry=expiry)
        inbound = uuid.uuid4()

        first = resolve_secretaria_offer_inbound(
            _OfferSession(),
            conversation,
            igreja_id=_TENANT,
            inbound_message_id=inbound,
            current_text="sim concordo",
            consent_needs_reaccept=True,
            now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
        )
        retry = resolve_secretaria_offer_inbound(
            _OfferSession(),
            conversation,
            igreja_id=_TENANT,
            inbound_message_id=inbound,
            current_text="sim concordo",
            consent_needs_reaccept=True,
            now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
        )

        assert first.terminal is True
        assert first.continue_turn is False
        assert first.handoff is False
        assert retry.terminal is True
        assert conversation.secretaria_oferta_estado == OFFER_CANCELLED
        assert conversation.secretaria_oferta_resposta_message_id == inbound


def test_early_yes_can_be_revoked_before_delivery_without_handoff() -> None:
    first_inbound = uuid.uuid4()
    conversation = _conversation(state=OFFER_PREPARED)
    session = _OfferSession()

    early_yes = resolve_secretaria_offer_inbound(
        session,
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=first_inbound,
        current_text="SIM!",
    )
    revoked = resolve_secretaria_offer_inbound(
        session,
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=uuid.uuid4(),
        current_text="não",
    )

    assert early_yes.terminal is True
    assert conversation.secretaria_oferta_estado == OFFER_CANCELLED
    assert revoked.terminal is True
    assert promote_secretaria_offer_after_delivery(
        session,
        conversation,
        outbound_message_id=_OUTBOUND,
    ) is False


def test_pending_yes_consumes_once_and_requests_handoff() -> None:
    conversation = _conversation(
        state=OFFER_PENDING,
        expiry=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
    )
    inbound = uuid.uuid4()

    result = resolve_secretaria_offer_inbound(
        _OfferSession(),
        conversation,
        igreja_id=_TENANT,
        inbound_message_id=inbound,
        current_text="sim.",
        consent_needs_reaccept=True,
        now=dt.datetime(2029, 1, 1, tzinfo=dt.UTC),
    )

    assert result.handoff is True
    assert result.terminal is True
    assert conversation.secretaria_oferta_resposta_message_id == inbound


def test_runtime_direct_path_uses_pending_offer_before_stale_consent(monkeypatch) -> None:
    pessoa_id = uuid.uuid4()
    inbound_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=_CONVERSATION,
        igreja_id=_TENANT,
        pessoa_id=pessoa_id,
        estado="ia",
        assumido_por=None,
        assumido_em=None,
        espera_desde=None,
        secretaria_oferta_estado=OFFER_PENDING,
        secretaria_oferta_message_id=_OUTBOUND,
        secretaria_oferta_expira_em=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
        secretaria_oferta_resposta_message_id=None,
    )
    pessoa = SimpleNamespace(
        id=pessoa_id,
        igreja_id=_TENANT,
        optout=False,
        sem_interesse=False,
        tipo="contato",
    )
    session = _RuntimeOfferSession(
        conversation=conversation,
        pessoa=pessoa,
        igreja=SimpleNamespace(id=_TENANT, nome="Igreja sintética"),
        config=SimpleNamespace(igreja_id=_TENANT, ativo=True, comportamento="Tom"),
    )

    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_trusted_inbound_identity_enabled=False,
            agent_term_version="s2b-v2",
            agent_default_model="synthetic",
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_active_credential",
        lambda *_a: SimpleNamespace(api_key_encrypted="synthetic", provedor="openai"),
    )
    monkeypatch.setattr(runtime, "_latest_consent_version", lambda *_a: "s2b-v1")
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_a, **_k: None)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a oferta deve resolver antes de consentimento ou grafo")

    monkeypatch.setattr(runtime, "run_turn", forbidden)
    monkeypatch.setattr(runtime, "_apply_consent", forbidden)

    result = runtime.process_inbound_message(
        session,
        igreja_id=_TENANT,
        conversation_id=_CONVERSATION,
        texto="texto forjado pelo chamador",
        inbound_message_id=inbound_id,
        provider_message_id="S2B-OFFER-INBOUND",
    )

    assert result.suppressed is True
    assert result.reason == "secretaria_offer_accepted"
    assert conversation.estado == "humano"
    assert conversation.secretaria_oferta_estado == "consumida"
    assert conversation.secretaria_oferta_resposta_message_id == inbound_id
    assert session.commits == 1


def test_runtime_expired_offer_binds_stale_acceptance_without_consent(monkeypatch) -> None:
    pessoa_id = uuid.uuid4()
    inbound_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=_CONVERSATION,
        igreja_id=_TENANT,
        pessoa_id=pessoa_id,
        estado="ia",
        assumido_por=None,
        assumido_em=None,
        espera_desde=None,
        secretaria_oferta_estado=OFFER_PENDING,
        secretaria_oferta_message_id=_OUTBOUND,
        secretaria_oferta_expira_em=dt.datetime(2028, 1, 1, tzinfo=dt.UTC),
        secretaria_oferta_resposta_message_id=None,
    )
    pessoa = SimpleNamespace(
        id=pessoa_id,
        igreja_id=_TENANT,
        optout=False,
        sem_interesse=False,
        tipo="contato",
    )
    session = _RuntimeOfferSession(
        conversation=conversation,
        pessoa=pessoa,
        igreja=SimpleNamespace(id=_TENANT, nome="Igreja sintética"),
        config=SimpleNamespace(igreja_id=_TENANT, ativo=True, comportamento="Tom"),
        inbound_text="sim concordo",
    )

    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_trusted_inbound_identity_enabled=False,
            agent_term_version="s2b-v2",
            agent_default_model="synthetic",
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_active_credential",
        lambda *_a: SimpleNamespace(api_key_encrypted="synthetic", provedor="openai"),
    )
    monkeypatch.setattr(runtime, "_latest_consent_version", lambda *_a: "s2b-v1")
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_a, **_k: None)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("aceite não pode alcançar consentimento, grafo ou LLM")

    monkeypatch.setattr(runtime, "run_turn", forbidden)
    monkeypatch.setattr(runtime, "_apply_consent", forbidden)

    result = runtime.process_inbound_message(
        session,
        igreja_id=_TENANT,
        conversation_id=_CONVERSATION,
        texto="texto forjado pelo chamador",
        inbound_message_id=inbound_id,
        provider_message_id="S2B-OFFER-EXPIRED",
    )

    assert result.suppressed is True
    assert result.reason == "secretaria_offer_resolved"
    assert conversation.secretaria_oferta_estado == OFFER_EXPIRED
    assert conversation.secretaria_oferta_resposta_message_id == inbound_id
    assert session.commits == 1


def test_runtime_pending_offer_binds_stale_term_acceptance_without_consent(monkeypatch) -> None:
    pessoa_id = uuid.uuid4()
    inbound_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=_CONVERSATION,
        igreja_id=_TENANT,
        pessoa_id=pessoa_id,
        estado="ia",
        assumido_por=None,
        assumido_em=None,
        espera_desde=None,
        secretaria_oferta_estado=OFFER_PENDING,
        secretaria_oferta_message_id=_OUTBOUND,
        secretaria_oferta_expira_em=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
        secretaria_oferta_resposta_message_id=None,
    )
    pessoa = SimpleNamespace(
        id=pessoa_id,
        igreja_id=_TENANT,
        optout=False,
        sem_interesse=False,
        tipo="contato",
    )
    session = _RuntimeOfferSession(
        conversation=conversation,
        pessoa=pessoa,
        igreja=SimpleNamespace(id=_TENANT, nome="Igreja sintética"),
        config=SimpleNamespace(igreja_id=_TENANT, ativo=True, comportamento="Tom"),
        inbound_text="sim concordo",
    )

    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_trusted_inbound_identity_enabled=False,
            agent_term_version="s2b-v2",
            agent_default_model="synthetic",
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_active_credential",
        lambda *_a: SimpleNamespace(api_key_encrypted="synthetic", provedor="openai"),
    )
    monkeypatch.setattr(runtime, "_latest_consent_version", lambda *_a: "s2b-v1")
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_a, **_k: None)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("aceite não pode alcançar consentimento, grafo ou LLM")

    monkeypatch.setattr(runtime, "run_turn", forbidden)
    monkeypatch.setattr(runtime, "_apply_consent", forbidden)

    result = runtime.process_inbound_message(
        session,
        igreja_id=_TENANT,
        conversation_id=_CONVERSATION,
        texto="texto forjado pelo chamador",
        inbound_message_id=inbound_id,
        provider_message_id="S2B-OFFER-PENDING",
    )

    assert result.suppressed is True
    assert result.reason == "secretaria_offer_resolved"
    assert conversation.secretaria_oferta_estado == OFFER_CANCELLED
    assert conversation.secretaria_oferta_resposta_message_id == inbound_id
    assert session.commits == 1


def test_runtime_tier_preflight_uses_offer_before_stale_consent(monkeypatch) -> None:
    pessoa_id = uuid.uuid4()
    inbound_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=_CONVERSATION,
        igreja_id=_TENANT,
        pessoa_id=pessoa_id,
        estado="ia",
        assumido_por=None,
        assumido_em=None,
        espera_desde=None,
        secretaria_oferta_estado=OFFER_PENDING,
        secretaria_oferta_message_id=_OUTBOUND,
        secretaria_oferta_expira_em=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
        secretaria_oferta_resposta_message_id=None,
    )
    pessoa = SimpleNamespace(
        id=pessoa_id,
        igreja_id=_TENANT,
        optout=False,
        sem_interesse=False,
        tipo="contato",
    )
    session = _RuntimeOfferSession(
        conversation=conversation,
        pessoa=pessoa,
        igreja=SimpleNamespace(id=_TENANT, nome="Igreja sintética"),
        config=SimpleNamespace(igreja_id=_TENANT, ativo=True, comportamento="Tom"),
    )
    terminal_calls: list[dict[str, object]] = []

    monkeypatch.setattr(runtime, "require_tenant_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            agent_trusted_inbound_identity_enabled=False,
            agent_term_version="s2b-v2",
            agent_default_model="synthetic",
        ),
    )
    monkeypatch.setattr(
        runtime,
        "_active_credential",
        lambda *_a: SimpleNamespace(api_key_encrypted="synthetic", provedor="openai"),
    )
    monkeypatch.setattr(runtime, "_latest_consent_version", lambda *_a: "s2b-v1")
    monkeypatch.setattr(runtime, "log_agent_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        runtime,
        "_apply_tier_a_terminal_reply",
        lambda _session, **kwargs: terminal_calls.append(kwargs) or conversation,
    )

    result = runtime.process_inbound_message(
        session,
        igreja_id=_TENANT,
        conversation_id=_CONVERSATION,
        texto="texto forjado pelo chamador",
        inbound_message_id=inbound_id,
        provider_message_id="S2B-OFFER-TIER-A",
        tier_a_preflight=True,
        tier_a_reply_provider_message_id="S2B-OFFER-REPLY",
    )

    assert result.suppressed is True
    assert result.reason == "secretaria_offer_accepted"
    assert terminal_calls == [
        {
            "igreja_id": _TENANT,
            "conversation_id": _CONVERSATION,
            "reply_provider_message_id": "S2B-OFFER-REPLY",
            "handoff": True,
            "ownership_guard": None,
        }
    ]
