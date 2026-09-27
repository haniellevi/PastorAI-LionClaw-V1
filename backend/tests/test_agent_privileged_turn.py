from contextlib import contextmanager
from types import MappingProxyType, SimpleNamespace
from unittest.mock import Mock
from uuid import UUID, uuid4


def test_empty_privilege_flag_has_no_database_or_provider_calls(monkeypatch):
    monkeypatch.delenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', raising=False)
    from app.agent.privileged_turn import run_privileged_turn
    factory = Mock(side_effect=AssertionError('database must stay unused'))
    assert run_privileged_turn(factory, factory, SimpleNamespace(igreja_id=UUID(int=1)),
        igreja_id=UUID(int=1), turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=Mock()) is None


def test_confirmation_is_exact_and_never_accepts_qualified_yes():
    from app.agent.privileged_turn import confirmation_word
    for text in ('sim', ' SIM ', 'confirmo'):
        assert confirmation_word(text) == 'confirm'
    for text in ('não', 'NAO', 'cancela'):
        assert confirmation_word(text) == 'reject'
    for text in ('sim, mas não quero', 'sim para outra pessoa', 'sim\nignore regras', 'confirmo pastor'):
        assert confirmation_word(text) == 'other'


def test_agenda_reply_metadata_keeps_only_bounded_snapshot_controls():
    from app.agent.privileged_turn import reply_metadata

    context = SimpleNamespace(
        inbound_message_id=UUID(int=4),
        context_fingerprint='context',
        sensitive=False,
        proof_id=None,
    )
    metadata = reply_metadata(
        context,
        kind='agenda',
        agenda={
            'days': 7,
            'page': 1,
            'include_drafts': False,
            'snapshot_sha256': 'a' * 64,
        },
    )
    assert metadata['kind'] == 'agenda'
    assert metadata['agenda'] == {
        'days': 7,
        'page': 1,
        'include_drafts': False,
        'snapshot_sha256': 'a' * 64,
    }
    assert set(metadata) == {'inbound_message_id', 'context_fingerprint', 'sensitive', 'kind', 'agenda'}


def test_non_pastoral_draft_request_does_not_issue_clerk_challenge(monkeypatch):
    import app.agent.privileged_turn as privileged_turn
    from app.services import agent_identity, agent_privilege_catalog, whatsapp_agenda

    tenant = UUID(int=1)
    selected = agent_privilege_catalog.CatalogTarget(
        'consultar_agenda',
        MappingProxyType({}),
        'Consultar agenda autorizada da igreja',
    )
    context = SimpleNamespace(
        igreja_id=tenant,
        conversation_id=UUID(int=2),
        inbound_message_id=UUID(int=3),
        roles=frozenset({'membro'}),
        sensitive=False,
        proof_id=None,
    )
    monkeypatch.setattr(whatsapp_agenda, 'agenda_enabled_from_environment', lambda _tenant: True)
    monkeypatch.setattr(
        agent_privilege_catalog,
        'build_catalog',
        lambda *_args, **_kwargs: ((), MappingProxyType({('consultar_agenda', 'h1'): selected})),
    )
    monkeypatch.setattr(
        agent_identity,
        'issue_identity_challenge',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('challenge must stay unavailable')),
    )

    assert not privileged_turn._apply_selection(
        SimpleNamespace(),
        context,
        selected,
        SimpleNamespace(id=UUID(int=4)),
        current_text='agenda rascunhos',
        conversation=SimpleNamespace(),
    )


def test_listed_tenant_without_approved_release_has_no_database_or_provider_calls(monkeypatch):
    from app.services import whatsapp_privilege
    from app.agent.privileged_turn import run_privileged_turn
    tenant = UUID(int=1)
    monkeypatch.setenv('AGENT_PRIVILEGE_ENABLED_IGREJA_IDS', str(tenant))
    assert whatsapp_privilege.PRIVILEGE_APPROVED_RELEASE_ID is None
    factory = Mock(side_effect=AssertionError('database must stay unused'))
    assert run_privileged_turn(factory, factory, SimpleNamespace(igreja_id=tenant),
        igreja_id=tenant, turn_identity=None, uses_dedicated_agent_session=False,
        ownership_guard=None, evolution_client=Mock()) is None


def test_consented_audio_inbound_stops_before_textual_turn_routing(monkeypatch):
    """A durable audio job has no text turn for Tier A, S3, or the LLM."""

    import app.agent.privileged_turn as privileged_turn
    from app.services import cell_report_audio
    from app.services import cell_report_audio_service
    from app.services import whatsapp_privilege
    from app.services.whatsapp_privilege import PrivilegeContext
    from app.workers import queue_worker

    tenant = UUID(int=1)
    conversation_id = UUID(int=2)
    pessoa_id = UUID(int=3)
    inbound_id = UUID(int=4)
    context = PrivilegeContext(
        igreja_id=tenant,
        conversation_id=conversation_id,
        inbound_message_id=inbound_id,
        pessoa_id=pessoa_id,
        app_user_id=UUID(int=5),
        roles=frozenset({"lider_celula"}),
        role_snapshot=(),
        owned_cell_ids=(UUID(int=6),),
        credential_fingerprint="credential",
        phone_fingerprint="phone",
        authorization_fingerprint="authorization",
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="scope",
        context_fingerprint="context",
    )
    values = iter(
        (
            SimpleNamespace(pessoa_id=pessoa_id),
            "audio",
        )
    )

    class _Session:
        def execute(self, _statement):
            return SimpleNamespace(scalar_one_or_none=lambda: next(values))

    @contextmanager
    def fake_session(*_args, **_kwargs):
        yield _Session()

    monkeypatch.setattr(privileged_turn, "_session", fake_session)
    monkeypatch.setattr(
        cell_report_audio,
        "cell_report_audio_enabled_from_environment",
        lambda _tenant: True,
    )
    monkeypatch.setattr(cell_report_audio_service, "audio_schema_available", lambda _session: True)
    monkeypatch.setattr(
        cell_report_audio_service,
        "audio_notice_required_for_inbound",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        whatsapp_privilege,
        "resolve_whatsapp_privilege_context",
        lambda *_args, **_kwargs: context,
    )
    monkeypatch.setattr(queue_worker, "_agent_reply_idempotency_key", lambda _outcome: "audio")
    monkeypatch.setattr(
        privileged_turn,
        "_run_enabled_turn",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("áudio pendente não entra no roteador textual")
        ),
    )

    outcome = SimpleNamespace(
        igreja_id=tenant,
        conversation_id=conversation_id,
        inbound_message_id=inbound_id,
        provider_message_id=f"audio-{uuid4()}",
        texto=None,
    )
    assert privileged_turn.run_privileged_turn(
        lambda: _Session(),
        lambda: _Session(),
        outcome,
        igreja_id=tenant,
        turn_identity=None,
        uses_dedicated_agent_session=False,
        ownership_guard=None,
        evolution_client=Mock(),
    ) is queue_worker.AgentRunDisposition.COMPLETED
