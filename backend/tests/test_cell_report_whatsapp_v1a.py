from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
import uuid
from types import SimpleNamespace

import pytest

from app.domain.cell_report_v1a import (
    CellReportV1aError,
    parse_v1a_cell_report_text,
)
from app.services.whatsapp_privilege import PrivilegeContext, PrivilegeResolutionKind
from app.services import cell_report_v1a_service as transaction_service
from app.services import cell_report_whatsapp as service


TENANT = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
PERSON = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
NOW = dt.datetime(2026, 9, 27, 15, tzinfo=dt.timezone.utc)


def _privilege_context(*, inbound_message_id: uuid.UUID) -> PrivilegeContext:
    return PrivilegeContext(
        igreja_id=TENANT,
        conversation_id=uuid.UUID("00000000-0000-0000-0000-0000000000c1"),
        inbound_message_id=inbound_message_id,
        pessoa_id=PERSON,
        app_user_id=uuid.UUID("00000000-0000-0000-0000-0000000000d1"),
        roles=frozenset({"lider_celula"}),
        role_snapshot=((uuid.UUID("00000000-0000-0000-0000-0000000000e1"), "lider_celula"),),
        owned_cell_ids=(uuid.UUID("00000000-0000-0000-0000-0000000000f1"),),
        credential_fingerprint="a" * 64,
        phone_fingerprint="b" * 64,
        authorization_fingerprint="c" * 64,
        proof_id=None,
        proof_until=None,
        sensitive=False,
        scope_fingerprint="d" * 64,
        context_fingerprint="e" * 64,
        kind=PrivilegeResolutionKind.PRIVILEGED,
    )


def test_cell_report_gate_is_inert_without_its_reviewed_release(monkeypatch) -> None:
    monkeypatch.setenv("CELL_REPORT_ENABLED_IGREJA_IDS", str(TENANT))
    monkeypatch.setattr(service, "CELL_REPORT_APPROVED_RELEASE_ID", None)
    monkeypatch.setattr(service, "privilege_enabled_from_environment", lambda _tenant: True)

    assert service.cell_report_enabled_from_environment(TENANT) is False


def test_cell_report_gate_requires_s3_gate_and_exact_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("CELL_REPORT_ENABLED_IGREJA_IDS", str(TENANT))
    monkeypatch.setattr(service, "CELL_REPORT_APPROVED_RELEASE_ID", "v1a-reviewed")
    monkeypatch.setattr(service, "privilege_enabled_from_environment", lambda tenant: tenant == TENANT)

    assert service.cell_report_enabled_from_environment(TENANT) is True
    assert service.cell_report_enabled_from_environment(uuid.uuid4()) is False


def test_active_partial_draft_does_not_capture_an_unrelated_public_question(monkeypatch) -> None:
    inbound_id = uuid.UUID("00000000-0000-0000-0000-0000000000a2")
    active = transaction_service._DraftReference(
        id=uuid.UUID("00000000-0000-0000-0000-0000000000a3"),
        meeting_id=uuid.UUID("00000000-0000-0000-0000-0000000000a4"),
    )
    context = _privilege_context(inbound_message_id=inbound_id)
    monkeypatch.setattr(transaction_service, "_now", lambda *_args: NOW)
    monkeypatch.setattr(transaction_service, "require_tenant_scope", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(transaction_service, "_lock_conversation_and_inbound", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(transaction_service, "_current_lgpd_acceptance", lambda *_args, **_kwargs: "termo-v1")
    monkeypatch.setattr(transaction_service, "_active_draft_hint", lambda *_args, **_kwargs: active)
    monkeypatch.setattr(
        transaction_service,
        "_eligible_meeting",
        lambda *_args, **_kwargs: pytest.fail("pergunta pública não deve tocar o rascunho"),
    )

    result = transaction_service.stage_v1a_cell_report_turn(
        object(),
        context=context,
        inbound_message_id=inbound_id,
        text="Qual é o endereço da igreja?",
        summary_message=SimpleNamespace(),
        now=NOW,
    )

    assert result.kind is transaction_service.CellReportStageKind.NOT_APPLICABLE


def test_v1a_receipt_text_uses_only_server_cell_and_meeting_date() -> None:
    meeting = transaction_service._Meeting(
        uuid.UUID("00000000-0000-0000-0000-0000000000a5"),
        "Célula Sintética",
        dt.date(2026, 9, 26),
    )

    assert transaction_service._render_v1a_cell_report_receipt(meeting) == (
        "Relatório confirmado. Célula Célula Sintética, reunião de 26/09/2026."
    )


def test_v1a_receipt_loads_only_the_executed_server_proposal_and_meeting(monkeypatch) -> None:
    inbound_id = uuid.UUID("00000000-0000-0000-0000-0000000000a7")
    proposal_id = uuid.UUID("00000000-0000-0000-0000-0000000000a8")
    meeting_id = uuid.UUID("00000000-0000-0000-0000-0000000000a9")
    proposal = SimpleNamespace(
        arguments_json={
            "rascunho_id": str(uuid.UUID("00000000-0000-0000-0000-0000000000aa")),
            "reuniao_id": str(meeting_id),
            "revisao": 1,
        },
        target_id=meeting_id,
    )

    class _Result:
        def __init__(self, *, scalar=None, row=None) -> None:
            self._scalar = scalar
            self._row = row

        def scalar_one_or_none(self):
            return self._scalar

        def one_or_none(self):
            return self._row

    class _Session:
        def __init__(self) -> None:
            self._results = iter(
                (
                    _Result(scalar=proposal),
                    _Result(row=(dt.date(2026, 9, 26), "Célula Sintética")),
                )
            )

        def execute(self, _statement):
            return next(self._results)

    monkeypatch.setattr(transaction_service, "require_tenant_scope", lambda *_args, **_kwargs: None)

    assert transaction_service.v1a_receipt_text_after_execution(
        _Session(),
        context=_privilege_context(inbound_message_id=inbound_id),
        proposal_id=proposal_id,
    ) == "Relatório confirmado. Célula Célula Sintética, reunião de 26/09/2026."


def test_committed_v1a_receipt_is_reused_without_rebuilding_current_cell_data() -> None:
    import app.agent.privileged_turn as privileged_turn

    proposal_id = uuid.UUID("00000000-0000-0000-0000-0000000000a6")
    committed = "Relatório confirmado. Célula Célula Sintética, reunião de 26/09/2026. Comprovante: opaque."
    message = SimpleNamespace(
        texto=committed,
        agent_privilege_context={"kind": "receipt", "proposal_id": str(proposal_id)},
    )

    assert privileged_turn._stored_receipt_response(message, proposal_id) == committed
    assert privileged_turn._stored_receipt_response(message, uuid.uuid4()) is None


def test_lgpd_consent_requires_latest_unambiguous_current_acceptance() -> None:
    accepted = service.LgpdConsentRecord("termo-v2", NOW - dt.timedelta(minutes=1), uuid.uuid4())
    assert service.current_v1a_lgpd_acceptance((accepted,), current_term="termo-v2", now=NOW) == "termo-v2"

    old = service.LgpdConsentRecord("termo-v1", NOW - dt.timedelta(minutes=2), uuid.uuid4())
    revoked = service.LgpdConsentRecord("optout:termo-v2", NOW - dt.timedelta(minutes=1), uuid.uuid4())
    assert service.current_v1a_lgpd_acceptance((old, revoked), current_term="termo-v2", now=NOW) is None

    conflict = service.LgpdConsentRecord("optout:termo-v2", accepted.aceite_em, uuid.uuid4())
    assert service.current_v1a_lgpd_acceptance((accepted, conflict), current_term="termo-v2", now=NOW) is None

    duplicate = service.LgpdConsentRecord("termo-v2", accepted.aceite_em, uuid.uuid4())
    assert service.current_v1a_lgpd_acceptance((accepted, duplicate), current_term="termo-v2", now=NOW) is None


@pytest.mark.parametrize(
    "record",
    [
        service.LgpdConsentRecord("termo-v2", None, uuid.uuid4()),
        service.LgpdConsentRecord("termo-v2", NOW + dt.timedelta(seconds=1), uuid.uuid4()),
    ],
)
def test_lgpd_consent_rejects_missing_or_future_timestamp(record) -> None:
    assert service.current_v1a_lgpd_acceptance((record,), current_term="termo-v2", now=NOW) is None


def test_llm_projection_never_receives_raw_text_or_private_observations() -> None:
    candidate = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )

    projection = service.v1a_extraction_projection(candidate)

    assert projection == {
        "presentes": 10,
        "visitantes": 2,
        "decisoes": 1,
        "oferta_centavos": 3000,
    }
    assert "Fulano" not in repr(projection)
    assert "Rua" not in repr(projection)


def test_llm_projection_preserves_missing_values_as_null() -> None:
    candidate = parse_v1a_cell_report_text("10 presentes")

    assert service.v1a_extraction_projection(candidate) == {
        "presentes": 10,
        "visitantes": None,
        "decisoes": None,
        "oferta_centavos": None,
    }


def _assert_educational_clarify(result) -> None:
    assert result.kind is transaction_service.CellReportStageKind.CLARIFY
    assert result.proposal is None
    assert result.response is not None
    assert (
        "Exemplo válido: presentes: 8, visitantes: 2, decisões: 1, oferta: R$ 42,50."
        in result.response
    )
    assert "vírgula ou quebra de linha" in result.response


def _patch_stage_access(monkeypatch) -> None:
    monkeypatch.setattr(transaction_service, "_now", lambda *_args: NOW)
    monkeypatch.setattr(
        transaction_service, "require_tenant_scope", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        transaction_service,
        "_lock_conversation_and_inbound",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        transaction_service,
        "_current_lgpd_acceptance",
        lambda *_args, **_kwargs: "termo-v1",
    )


def _raise_v1a_error(*_args, **_kwargs):
    raise CellReportV1aError("inválido")


def test_v1a_parse_clarify_teaches_closed_multiline_format(monkeypatch) -> None:
    inbound_id = uuid.uuid4()
    _patch_stage_access(monkeypatch)
    monkeypatch.setattr(
        transaction_service, "_active_draft_hint", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        transaction_service,
        "v1a_whitelisted_extraction_projection",
        lambda *_args, **_kwargs: pytest.fail("parser inválido não chama provedor"),
    )

    result = transaction_service.stage_v1a_cell_report_turn(
        object(),
        context=_privilege_context(inbound_message_id=inbound_id),
        inbound_message_id=inbound_id,
        text="presentes: 8, obs: dado sintético",
        summary_message=SimpleNamespace(),
        now=NOW,
    )

    _assert_educational_clarify(result)
    assert "dado sintético" not in result.response


def test_v1a_missing_fields_clarify_teaches_closed_multiline_format(monkeypatch) -> None:
    inbound_id = uuid.uuid4()
    meeting = transaction_service._Meeting(uuid.uuid4(), "Célula Sintética", NOW.date())

    class _Session:
        def add(self, draft) -> None:
            draft.id = uuid.uuid4()

        def flush(self) -> None:
            pass

    _patch_stage_access(monkeypatch)
    monkeypatch.setattr(
        transaction_service, "_active_draft_hint", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        transaction_service, "_eligible_meeting", lambda *_args, **_kwargs: meeting
    )
    monkeypatch.setattr(
        transaction_service,
        "_lock_active_draft_after_meeting",
        lambda *_args, **_kwargs: None,
    )

    result = transaction_service.stage_v1a_cell_report_turn(
        _Session(),
        context=_privilege_context(inbound_message_id=inbound_id),
        inbound_message_id=inbound_id,
        text="presentes: 8",
        summary_message=SimpleNamespace(),
        now=NOW,
    )

    _assert_educational_clarify(result)


def test_v1a_extraction_correction_clarify_teaches_closed_multiline_format(monkeypatch) -> None:
    inbound_id = uuid.uuid4()
    meeting = transaction_service._Meeting(uuid.uuid4(), "Célula Sintética", NOW.date())
    _patch_stage_access(monkeypatch)
    monkeypatch.setattr(
        transaction_service, "_active_draft_hint", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        transaction_service, "_eligible_meeting", lambda *_args, **_kwargs: meeting
    )
    monkeypatch.setattr(
        transaction_service,
        "_lock_active_draft_after_meeting",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        transaction_service,
        "v1a_whitelisted_extraction_projection",
        lambda *_args, **_kwargs: {"presentes": "oito"},
    )
    monkeypatch.setattr(
        transaction_service,
        "canonical_v1a_draft_payload",
        _raise_v1a_error,
    )

    result = transaction_service.stage_v1a_cell_report_turn(
        object(),
        context=_privilege_context(inbound_message_id=inbound_id),
        inbound_message_id=inbound_id,
        text="visitantes: 2",
        summary_message=SimpleNamespace(),
        now=NOW,
    )

    _assert_educational_clarify(result)


def test_v1a_revision_correction_clarify_teaches_closed_multiline_format(monkeypatch) -> None:
    inbound_id = uuid.uuid4()
    meeting = transaction_service._Meeting(uuid.uuid4(), "Célula Sintética", NOW.date())
    active = SimpleNamespace(expires_at=NOW + dt.timedelta(hours=1))
    _patch_stage_access(monkeypatch)
    monkeypatch.setattr(
        transaction_service,
        "_active_draft_hint",
        lambda *_args, **_kwargs: SimpleNamespace(meeting_id=meeting.id),
    )
    monkeypatch.setattr(
        transaction_service, "_eligible_meeting", lambda *_args, **_kwargs: meeting
    )
    monkeypatch.setattr(
        transaction_service,
        "_lock_active_draft_after_meeting",
        lambda *_args, **_kwargs: active,
    )
    monkeypatch.setattr(
        transaction_service,
        "v1a_whitelisted_extraction_projection",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        transaction_service,
        "_rehydrate_verified_draft_candidate",
        lambda *_args, **_kwargs: parse_v1a_cell_report_text("presentes: 8"),
    )
    monkeypatch.setattr(
        transaction_service,
        "merge_v1a_cell_report_text",
        _raise_v1a_error,
    )

    result = transaction_service.stage_v1a_cell_report_turn(
        object(),
        context=_privilege_context(inbound_message_id=inbound_id),
        inbound_message_id=inbound_id,
        text="presentes: 9",
        summary_message=SimpleNamespace(),
        now=NOW,
    )

    _assert_educational_clarify(result)


def test_draft_payload_is_closed_and_round_trips_only_aggregate_values() -> None:
    candidate = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )

    payload = service.canonical_v1a_draft_payload(candidate)
    restored = service.rehydrate_v1a_draft_candidate(payload)

    assert payload == {
        "presentes": 10,
        "visitantes": 2,
        "decisoes": 1,
        "oferta_centavos": 3000,
    }
    assert restored == candidate


def test_execution_rejects_a_draft_payload_that_no_longer_matches_its_digest() -> None:
    original = service.canonical_v1a_draft_payload(
        parse_v1a_cell_report_text(
            "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
        )
    )
    tampered = dict(original)
    tampered["oferta_centavos"] = 9_999
    draft = SimpleNamespace(
        candidate_json=tampered,
        candidate_sha256=transaction_service._canonical_payload_sha256(original),
    )

    with pytest.raises(service.CellReportWhatsappError):
        transaction_service._rehydrate_verified_draft_candidate(draft)


def test_execution_rejects_a_payload_with_a_rewritten_digest_when_summary_differs() -> None:
    delivered = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )
    changed = parse_v1a_cell_report_text(
        "99 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )
    meeting = transaction_service._Meeting(
        uuid.UUID("00000000-0000-0000-0000-0000000000c1"),
        "Célula Sintética",
        dt.date(2026, 9, 26),
    )
    proposal = SimpleNamespace(
        summary_sha256=transaction_service._expected_summary_sha256(delivered, meeting)
    )

    assert transaction_service._proposal_summary_matches_candidate(
        proposal, delivered, meeting
    )
    assert not transaction_service._proposal_summary_matches_candidate(
        proposal, changed, meeting
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"presentes": 1},
        {
            "presentes": 1,
            "visitantes": 0,
            "decisoes": 0,
            "oferta_centavos": 100,
            "observacoes": "privado",
        },
        {
            "presentes": 1,
            "visitantes": 0,
            "decisoes": 0,
            "oferta_centavos": -1,
        },
    ],
)
def test_draft_payload_rejects_incomplete_or_private_or_invalid_values(payload: object) -> None:
    with pytest.raises(service.CellReportWhatsappError):
        service.rehydrate_v1a_draft_candidate(payload)


def test_upper_bound_cost_estimate_is_conservative_and_bounded() -> None:
    observed: list[tuple[str, int, int]] = []

    def estimate(model: str, tokens_in: int, tokens_out: int) -> float:
        observed.append((model, tokens_in, tokens_out))
        return 0.0000001

    assert service.estimate_v1a_extraction_microusd("synthetic-model", estimate) == 1
    assert observed == [
        (
            "synthetic-model",
            service.CELL_REPORT_MAX_INPUT_TOKENS,
            service.CELL_REPORT_MAX_OUTPUT_TOKENS,
        )
    ]


@pytest.mark.parametrize("cost", [0.0, -0.1, float("nan"), float("inf")])
def test_unknown_or_nonpositive_cost_fails_closed(cost: float) -> None:
    with pytest.raises(service.CellReportWhatsappError):
        service.estimate_v1a_extraction_microusd("synthetic-model", lambda *_args: cost)


def test_actual_extraction_cost_uses_bounded_usage_and_never_assumes_zero() -> None:
    usage = SimpleNamespace(
        modelo="synthetic-model",
        tokens_in=12,
        tokens_out=8,
        custo=0.000123,
    )

    assert service.actual_v1a_extraction_microusd(
        usage,
        lambda *_args: 0.0000191,
    ) == 20

    for malformed in (
        SimpleNamespace(modelo="synthetic-model", tokens_in=12, tokens_out=8, custo=None),
        SimpleNamespace(modelo="synthetic-model", tokens_in=True, tokens_out=8, custo=0.1),
        SimpleNamespace(modelo="synthetic-model", tokens_in=12, tokens_out=401, custo=0.1),
        SimpleNamespace(modelo="synthetic-model", tokens_in=12, tokens_out=8, custo=float("nan")),
    ):
        with pytest.raises(service.CellReportWhatsappError):
            service.actual_v1a_extraction_microusd(malformed, lambda *_args: 0.1)


def test_whitelisted_fallback_never_passes_raw_names_or_addresses_to_extractor() -> None:
    raw = (
        "presentes: dez; visitantes: dois; decisões: uma; oferta: trinta reais; "
        "visitante Fulano, Rua Sintética 100"
    )
    captured: list[dict[str, str]] = []

    result = service.complete_v1a_candidate_from_whitelisted_projection(
        raw,
        parse_v1a_cell_report_text(""),
        extract=lambda projection: captured.append(projection) or {
            "presentes": 10,
            "visitantes": 2,
            "decisoes": 1,
            "oferta_centavos": 3000,
        },
    )

    assert captured == [
        {
            "presentes": "dez",
            "visitantes": "dois",
            "decisoes": "uma",
            "oferta": "trinta reais",
        }
    ]
    assert result.presentes == 10
    assert result.visitantes == 2
    assert result.decisoes == 1
    assert result.oferta == "30.00"
    assert "Fulano" not in repr(captured)
    assert "Rua" not in repr(captured)


def test_whitelisted_projection_keeps_closed_compound_number_words_intact() -> None:
    assert service.v1a_whitelisted_extraction_projection(
        "presentes: vinte e cinco; oferta: trinta e cinco reais"
    ) == {
        "presentes": "vinte e cinco",
        "oferta": "trinta e cinco reais",
    }


def test_conventional_complete_parser_never_invokes_fallback_extractor() -> None:
    direct = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )

    result = service.complete_v1a_candidate_from_whitelisted_projection(
        "texto não deve ir ao extrator",
        direct,
        extract=lambda _projection: pytest.fail("extrator não deveria ser chamado"),
    )

    assert result == direct


def test_complete_candidate_needs_explicit_correction_mode_before_calling_extractor() -> None:
    direct = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )

    result = service.complete_v1a_candidate_from_whitelisted_projection(
        "presentes: doze",
        direct,
        extract=lambda _projection: pytest.fail("extrator não deveria ser chamado"),
    )

    assert result == direct


def test_explicit_whitelisted_word_correction_can_replace_only_its_label() -> None:
    direct = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )
    captured: list[dict[str, str]] = []

    result = service.complete_v1a_candidate_from_whitelisted_projection(
        "presentes: doze",
        direct,
        allow_explicit_corrections=True,
        extract=lambda projection: captured.append(projection) or {
            "presentes": 12,
            "visitantes": None,
            "decisoes": None,
            "oferta_centavos": None,
        },
    )

    assert captured == [{"presentes": "doze"}]
    assert result.presentes == 12
    assert result.visitantes == 2
    assert result.decisoes == 1
    assert result.oferta == "30.00"


def test_post_http_projection_applies_only_the_explicit_label() -> None:
    direct = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )

    result = service.complete_v1a_candidate_from_projection(
        direct,
        projection={"presentes": "doze"},
        extracted={
            "presentes": 12,
            "visitantes": None,
            "decisoes": None,
            "oferta_centavos": None,
        },
        allow_explicit_corrections=True,
    )

    assert (result.presentes, result.visitantes, result.decisoes, result.oferta) == (
        12,
        2,
        1,
        "30.00",
    )


def test_explicit_correction_rejects_model_value_for_any_unlabelled_field() -> None:
    direct = parse_v1a_cell_report_text(
        "10 presentes; 2 visitantes; 1 decisão; oferta: 30,00"
    )

    with pytest.raises(service.CellReportWhatsappError):
        service.complete_v1a_candidate_from_whitelisted_projection(
            "presentes: doze",
            direct,
            allow_explicit_corrections=True,
            extract=lambda _projection: {
                "presentes": 12,
                "visitantes": 99,
                "decisoes": None,
                "oferta_centavos": None,
            },
        )


def test_fallback_result_can_fill_only_fields_absent_from_parser() -> None:
    direct = parse_v1a_cell_report_text("10 presentes")

    with pytest.raises(service.CellReportWhatsappError):
        service.complete_v1a_candidate_from_whitelisted_projection(
            "visitantes: dois",
            direct,
            extract=lambda _projection: {
                "presentes": 11,
                "visitantes": 2,
                "decisoes": None,
                "oferta_centavos": None,
            },
        )


def test_fallback_cannot_invent_a_field_absent_from_the_whitelisted_projection() -> None:
    with pytest.raises(service.CellReportWhatsappError):
        service.complete_v1a_candidate_from_whitelisted_projection(
            "presentes: dez",
            parse_v1a_cell_report_text(""),
            extract=lambda _projection: {
                "presentes": 10,
                "visitantes": 0,
                "decisoes": None,
                "oferta_centavos": None,
            },
        )


def test_whitelisted_projection_rejects_fractional_or_truncated_number_prefixes() -> None:
    projection = service.v1a_whitelisted_extraction_projection(
        "presentes: dez; visitantes: 2; decisões: 1; oferta: 30,50"
    )

    assert projection == {
        "presentes": "dez",
        "visitantes": "2",
        "decisoes": "1",
    }
    for text in (
        "presentes: 2.5",
        "presentes: 2,5",
        "presentes: doze mil",
        "oferta: 30.50",
        "oferta: 30mil",
        "oferta: 30 centavos",
        "visitantes: 12345678",
    ):
        assert service.v1a_whitelisted_extraction_projection(text) == {}


def test_whitelisted_fallback_leaves_an_unprojected_fractional_offer_unknown() -> None:
    result = service.complete_v1a_candidate_from_whitelisted_projection(
        "presentes: dez; visitantes: 2; decisões: 1; oferta: 30,50",
        parse_v1a_cell_report_text(""),
        extract=lambda projection: {
            "presentes": 10 if "presentes" in projection else None,
            "visitantes": 2 if "visitantes" in projection else None,
            "decisoes": 1 if "decisoes" in projection else None,
            "oferta_centavos": None,
        },
    )

    assert (result.presentes, result.visitantes, result.decisoes, result.oferta) == (
        10,
        2,
        1,
        None,
    )
