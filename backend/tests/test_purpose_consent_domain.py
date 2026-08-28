from __future__ import annotations

import datetime as dt
import inspect
from dataclasses import FrozenInstanceError

import pytest

from app.domain.purpose_consent import (
    MAX_PURPOSE_CONSENT_TERM_VERSION_LENGTH,
    PURPOSE_CONSENT_PURPOSES,
    PurposeConsentEvent,
    PurposeConsentEventState,
    PurposeConsentProjectionState,
    PurposeConsentPurpose,
    PurposeConsentSource,
    PurposeConsentValidationError,
    TrustedTermVersion,
    build_purpose_consent_snapshot,
    project_purpose_consent,
)


CURRENT_VERSION = TrustedTermVersion("2026-08-v1")


def _event(
    purpose: PurposeConsentPurpose,
    state: PurposeConsentEventState,
    *,
    sequence: int = 1,
    version: str = "2026-08-v1",
) -> PurposeConsentEvent:
    return PurposeConsentEvent(
        purpose=purpose,
        state=state,
        source=PurposeConsentSource.WHATSAPP_INBOUND,
        versao_termo=version,
        sequence=sequence,
        registered_at=dt.datetime(2026, 8, 28, tzinfo=dt.timezone.utc),
    )


def _current_versions() -> dict[PurposeConsentPurpose, TrustedTermVersion]:
    return {purpose: CURRENT_VERSION for purpose in PURPOSE_CONSENT_PURPOSES}


def test_canonical_values_are_closed_to_the_four_approved_purposes() -> None:
    assert tuple(item.value for item in PurposeConsentPurpose) == (
        "atendimento_solicitado",
        "cuidado_pastoral",
        "tarefas_operacionais",
        "comunicados",
    )
    assert tuple(item.value for item in PurposeConsentEventState) == (
        "concedido",
        "retirado",
    )
    assert tuple(item.value for item in PurposeConsentSource) == (
        "whatsapp_inbound",
        "painel_autenticado",
    )
    assert tuple(item.value for item in PurposeConsentProjectionState) == (
        "ausente",
        "concedido",
        "retirado",
        "reaceite_necessario",
        "bloqueado_optout_global",
    )


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ((), PurposeConsentProjectionState.AUSENTE),
        (
            (
                _event(
                    PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
                    PurposeConsentEventState.CONCEDIDO,
                ),
            ),
            PurposeConsentProjectionState.CONCEDIDO,
        ),
        (
            (
                _event(
                    PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
                    PurposeConsentEventState.RETIRADO,
                ),
            ),
            PurposeConsentProjectionState.RETIRADO,
        ),
        (
            (
                _event(
                    PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
                    PurposeConsentEventState.CONCEDIDO,
                    version="2026-07-v1",
                ),
            ),
            PurposeConsentProjectionState.REACEITE_NECESSARIO,
        ),
    ],
)
def test_projection_covers_absent_granted_withdrawn_and_reacceptance(
    events: tuple[PurposeConsentEvent, ...],
    expected: PurposeConsentProjectionState,
) -> None:
    projection = project_purpose_consent(
        purpose=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        events=events,
        current_term_version=CURRENT_VERSION,
        global_optout=False,
    )

    assert projection.state is expected


def test_highest_sequence_wins_independently_of_input_order() -> None:
    projection = project_purpose_consent(
        purpose=PurposeConsentPurpose.CUIDADO_PASTORAL,
        events=(
            _event(
                PurposeConsentPurpose.CUIDADO_PASTORAL,
                PurposeConsentEventState.CONCEDIDO,
                sequence=3,
            ),
            _event(
                PurposeConsentPurpose.CUIDADO_PASTORAL,
                PurposeConsentEventState.RETIRADO,
                sequence=2,
            ),
            _event(
                PurposeConsentPurpose.CUIDADO_PASTORAL,
                PurposeConsentEventState.CONCEDIDO,
                sequence=1,
                version="2026-07-v1",
            ),
        ),
        current_term_version=CURRENT_VERSION,
        global_optout=False,
    )

    assert projection.state is PurposeConsentProjectionState.CONCEDIDO
    assert projection.sequence == 3


def test_global_optout_overrides_effective_state_without_erasing_evidence() -> None:
    projection = project_purpose_consent(
        purpose=PurposeConsentPurpose.COMUNICADOS,
        events=(
            _event(
                PurposeConsentPurpose.COMUNICADOS,
                PurposeConsentEventState.CONCEDIDO,
                sequence=4,
            ),
        ),
        current_term_version=CURRENT_VERSION,
        global_optout=True,
    )

    assert (
        projection.state
        is PurposeConsentProjectionState.BLOQUEADO_OPTOUT_GLOBAL
    )
    assert projection.recorded_state is PurposeConsentEventState.CONCEDIDO
    assert projection.versao_termo_registrada == CURRENT_VERSION.value
    assert projection.sequence == 4


def test_projection_rejects_cross_purpose_contamination_and_duplicate_sequence() -> None:
    wrong_purpose = _event(
        PurposeConsentPurpose.COMUNICADOS,
        PurposeConsentEventState.CONCEDIDO,
    )
    with pytest.raises(PurposeConsentValidationError, match="contaminou"):
        project_purpose_consent(
            purpose=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            events=(wrong_purpose,),
            current_term_version=CURRENT_VERSION,
            global_optout=False,
        )

    duplicate = _event(
        PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
        PurposeConsentEventState.RETIRADO,
    )
    with pytest.raises(PurposeConsentValidationError, match="duplicada"):
        project_purpose_consent(
            purpose=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            events=(
                _event(
                    PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
                    PurposeConsentEventState.CONCEDIDO,
                ),
                duplicate,
            ),
            current_term_version=CURRENT_VERSION,
            global_optout=False,
        )


def test_snapshot_is_frozen_complete_and_independent_from_mutable_input() -> None:
    mutable_events: list[PurposeConsentEvent] = []
    snapshot = build_purpose_consent_snapshot(
        events=mutable_events,
        current_term_versions=_current_versions(),
        global_optout=False,
    )
    mutable_events.append(
        _event(
            PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            PurposeConsentEventState.CONCEDIDO,
        )
    )

    assert len(snapshot.projections) == 4
    assert all(
        item.state is PurposeConsentProjectionState.AUSENTE
        for item in snapshot.projections
    )
    with pytest.raises(FrozenInstanceError):
        snapshot.global_optout = True  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.projections[0].state = (  # type: ignore[misc]
            PurposeConsentProjectionState.CONCEDIDO
        )


def test_legacy_consent_cannot_enter_or_grant_the_projection() -> None:
    parameters = inspect.signature(build_purpose_consent_snapshot).parameters
    assert set(parameters) == {
        "events",
        "current_term_versions",
        "global_optout",
    }

    legacy_pessoa_consentimento = True
    assert legacy_pessoa_consentimento is True
    snapshot = build_purpose_consent_snapshot(
        events=(),
        current_term_versions=_current_versions(),
        global_optout=False,
    )
    assert all(
        item.state is PurposeConsentProjectionState.AUSENTE
        for item in snapshot.projections
    )


@pytest.mark.parametrize(
    "value",
    [
        "",
        " 2026-08-v1",
        "2026-08-v1 ",
        "2026-\x00-v1",
        "x" * (MAX_PURPOSE_CONSENT_TERM_VERSION_LENGTH + 1),
    ],
)
def test_trusted_term_version_rejects_invalid_text(value: str) -> None:
    with pytest.raises(PurposeConsentValidationError):
        TrustedTermVersion(value)


def test_projection_requires_trusted_current_version_and_exact_term_map() -> None:
    with pytest.raises(PurposeConsentValidationError, match="confiável"):
        project_purpose_consent(
            purpose=PurposeConsentPurpose.ATENDIMENTO_SOLICITADO,
            events=(),
            current_term_version="2026-08-v1",  # type: ignore[arg-type]
            global_optout=False,
        )

    raw_key_map = {
        purpose.value: CURRENT_VERSION for purpose in PURPOSE_CONSENT_PURPOSES
    }
    with pytest.raises(PurposeConsentValidationError, match="quatro finalidades"):
        build_purpose_consent_snapshot(
            events=(),
            current_term_versions=raw_key_map,  # type: ignore[arg-type]
            global_optout=False,
        )
