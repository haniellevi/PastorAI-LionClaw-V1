"""Pure domain model for purpose-specific consent.

Only events from ``consentimento_finalidade_evento`` participate in this
projection.  The legacy ``pessoas.consentimento`` flag and ``consent_records``
table are deliberately absent: neither can grant a purpose-specific consent.
"""

from __future__ import annotations

import datetime as dt
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final


class PurposeConsentValidationError(ValueError):
    """Raised when an untrusted value cannot enter the consent domain."""


class PurposeConsentPurpose(str, Enum):
    """Canonical purposes supported by the first inactive domain slice."""

    ATENDIMENTO_SOLICITADO = "atendimento_solicitado"
    CUIDADO_PASTORAL = "cuidado_pastoral"
    TAREFAS_OPERACIONAIS = "tarefas_operacionais"
    COMUNICADOS = "comunicados"


class PurposeConsentEventState(str, Enum):
    """Facts that may be appended to a purpose stream."""

    CONCEDIDO = "concedido"
    RETIRADO = "retirado"


class PurposeConsentSource(str, Enum):
    """Server-recognized event sources."""

    WHATSAPP_INBOUND = "whatsapp_inbound"
    PAINEL_AUTENTICADO = "painel_autenticado"


class PurposeConsentProjectionState(str, Enum):
    """Effective state consumed by future policy gates."""

    AUSENTE = "ausente"
    CONCEDIDO = "concedido"
    RETIRADO = "retirado"
    REACEITE_NECESSARIO = "reaceite_necessario"
    BLOQUEADO_OPTOUT_GLOBAL = "bloqueado_optout_global"


PURPOSE_CONSENT_PURPOSES: Final[tuple[PurposeConsentPurpose, ...]] = tuple(
    PurposeConsentPurpose
)
MAX_PURPOSE_CONSENT_TERM_VERSION_LENGTH: Final = 128
MAX_PURPOSE_CONSENT_IDEMPOTENCY_KEY_LENGTH: Final = 128


def _require_exact_enum(value: object, enum_type: type[Enum], field: str) -> None:
    if type(value) is not enum_type:
        raise PurposeConsentValidationError(f"{field} inválido")


def _require_normalized_text(value: object, *, field: str, max_length: int) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise PurposeConsentValidationError(f"{field} deve ser texto normalizado")
    if len(value) > max_length:
        raise PurposeConsentValidationError(f"{field} excede o limite permitido")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise PurposeConsentValidationError(f"{field} contém caractere de controle")


@dataclass(frozen=True, slots=True)
class TrustedTermVersion:
    """Current term version supplied by a trusted server-side component.

    Callers must pass this value object to the service.  A raw string is never
    accepted as the authoritative version used to decide whether reacceptance
    is necessary.
    """

    value: str

    def __post_init__(self) -> None:
        _require_normalized_text(
            self.value,
            field="versao_termo",
            max_length=MAX_PURPOSE_CONSENT_TERM_VERSION_LENGTH,
        )


@dataclass(frozen=True, slots=True)
class PurposeConsentEvent:
    """Immutable event value used by the pure projection."""

    purpose: PurposeConsentPurpose
    state: PurposeConsentEventState
    source: PurposeConsentSource
    versao_termo: str
    sequence: int
    registered_at: dt.datetime

    def __post_init__(self) -> None:
        _require_exact_enum(self.purpose, PurposeConsentPurpose, "finalidade")
        _require_exact_enum(self.state, PurposeConsentEventState, "estado")
        _require_exact_enum(self.source, PurposeConsentSource, "fonte")
        _require_normalized_text(
            self.versao_termo,
            field="versao_termo",
            max_length=MAX_PURPOSE_CONSENT_TERM_VERSION_LENGTH,
        )
        if type(self.sequence) is not int or self.sequence <= 0:
            raise PurposeConsentValidationError("sequencia deve ser positiva")
        if not isinstance(self.registered_at, dt.datetime):
            raise PurposeConsentValidationError("registrado_em inválido")
        if (
            self.registered_at.tzinfo is None
            or self.registered_at.utcoffset() is None
        ):
            raise PurposeConsentValidationError(
                "registrado_em deve conter fuso horário"
            )


@dataclass(frozen=True, slots=True)
class PurposeConsentProjection:
    """Effective result plus the last recorded fact behind that result."""

    purpose: PurposeConsentPurpose
    state: PurposeConsentProjectionState
    recorded_state: PurposeConsentEventState | None
    versao_termo_registrada: str | None
    sequence: int | None

    def __post_init__(self) -> None:
        _require_exact_enum(self.purpose, PurposeConsentPurpose, "finalidade")
        _require_exact_enum(self.state, PurposeConsentProjectionState, "projecao")
        if self.sequence is None:
            if self.recorded_state is not None or self.versao_termo_registrada is not None:
                raise PurposeConsentValidationError(
                    "projeção sem sequência não pode conter evento registrado"
                )
            if self.state not in (
                PurposeConsentProjectionState.AUSENTE,
                PurposeConsentProjectionState.BLOQUEADO_OPTOUT_GLOBAL,
            ):
                raise PurposeConsentValidationError(
                    "projeção efetiva exige evento registrado"
                )
            return

        if type(self.sequence) is not int or self.sequence <= 0:
            raise PurposeConsentValidationError("sequencia projetada inválida")
        _require_exact_enum(
            self.recorded_state,
            PurposeConsentEventState,
            "estado registrado",
        )
        _require_normalized_text(
            self.versao_termo_registrada,
            field="versao_termo registrada",
            max_length=MAX_PURPOSE_CONSENT_TERM_VERSION_LENGTH,
        )
        if self.state is PurposeConsentProjectionState.AUSENTE:
            raise PurposeConsentValidationError(
                "projeção ausente não pode conter evento registrado"
            )
        if (
            self.state is PurposeConsentProjectionState.CONCEDIDO
            and self.recorded_state is not PurposeConsentEventState.CONCEDIDO
        ):
            raise PurposeConsentValidationError("concessão projetada inconsistente")
        if (
            self.state is PurposeConsentProjectionState.RETIRADO
            and self.recorded_state is not PurposeConsentEventState.RETIRADO
        ):
            raise PurposeConsentValidationError("retirada projetada inconsistente")
        if (
            self.state is PurposeConsentProjectionState.REACEITE_NECESSARIO
            and self.recorded_state is not PurposeConsentEventState.CONCEDIDO
        ):
            raise PurposeConsentValidationError("reaceite projetado inconsistente")


@dataclass(frozen=True, slots=True)
class PurposeConsentSnapshot:
    """Independent immutable snapshot of all four purpose projections."""

    projections: tuple[PurposeConsentProjection, ...]
    global_optout: bool

    def __post_init__(self) -> None:
        if type(self.global_optout) is not bool:
            raise PurposeConsentValidationError("optout global inválido")
        if not isinstance(self.projections, tuple):
            raise PurposeConsentValidationError("projeções devem ser imutáveis")
        if any(type(item) is not PurposeConsentProjection for item in self.projections):
            raise PurposeConsentValidationError("projeção inválida no snapshot")
        purposes = tuple(item.purpose for item in self.projections)
        if purposes != PURPOSE_CONSENT_PURPOSES:
            raise PurposeConsentValidationError(
                "snapshot deve conter as quatro finalidades na ordem canônica"
            )

    def for_purpose(
        self, purpose: PurposeConsentPurpose
    ) -> PurposeConsentProjection:
        """Return one canonical purpose, rejecting arbitrary strings."""

        _require_exact_enum(purpose, PurposeConsentPurpose, "finalidade")
        return self.projections[PURPOSE_CONSENT_PURPOSES.index(purpose)]


def project_purpose_consent(
    *,
    purpose: PurposeConsentPurpose,
    events: Iterable[PurposeConsentEvent],
    current_term_version: TrustedTermVersion,
    global_optout: bool,
) -> PurposeConsentProjection:
    """Project one purpose stream deterministically and fail closed.

    The highest sequence is authoritative.  Duplicate sequences or events from
    another purpose indicate a contaminated stream and are rejected instead of
    being silently ignored.
    """

    _require_exact_enum(purpose, PurposeConsentPurpose, "finalidade")
    if type(current_term_version) is not TrustedTermVersion:
        raise PurposeConsentValidationError(
            "versao_termo atual deve vir de componente confiável"
        )
    if type(global_optout) is not bool:
        raise PurposeConsentValidationError("optout global inválido")

    stream = tuple(events)
    seen_sequences: set[int] = set()
    for event in stream:
        if type(event) is not PurposeConsentEvent:
            raise PurposeConsentValidationError("evento de consentimento inválido")
        if event.purpose is not purpose:
            raise PurposeConsentValidationError(
                "evento de outra finalidade contaminou a projeção"
            )
        if event.sequence in seen_sequences:
            raise PurposeConsentValidationError("sequencia duplicada na projeção")
        seen_sequences.add(event.sequence)

    latest = max(stream, key=lambda item: item.sequence, default=None)
    if latest is None:
        base_state = PurposeConsentProjectionState.AUSENTE
        recorded_state = None
        versao_termo_registrada = None
        sequence = None
    else:
        recorded_state = latest.state
        versao_termo_registrada = latest.versao_termo
        sequence = latest.sequence
        if latest.state is PurposeConsentEventState.RETIRADO:
            base_state = PurposeConsentProjectionState.RETIRADO
        elif latest.versao_termo == current_term_version.value:
            base_state = PurposeConsentProjectionState.CONCEDIDO
        else:
            base_state = PurposeConsentProjectionState.REACEITE_NECESSARIO

    effective_state = (
        PurposeConsentProjectionState.BLOQUEADO_OPTOUT_GLOBAL
        if global_optout
        else base_state
    )
    return PurposeConsentProjection(
        purpose=purpose,
        state=effective_state,
        recorded_state=recorded_state,
        versao_termo_registrada=versao_termo_registrada,
        sequence=sequence,
    )


def build_purpose_consent_snapshot(
    *,
    events: Iterable[PurposeConsentEvent],
    current_term_versions: Mapping[PurposeConsentPurpose, TrustedTermVersion],
    global_optout: bool,
) -> PurposeConsentSnapshot:
    """Build all projections without consulting or accepting legacy consent."""

    if type(global_optout) is not bool:
        raise PurposeConsentValidationError("optout global inválido")
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

    immutable_events = tuple(events)
    by_purpose: dict[PurposeConsentPurpose, list[PurposeConsentEvent]] = {
        purpose: [] for purpose in PURPOSE_CONSENT_PURPOSES
    }
    for event in immutable_events:
        if type(event) is not PurposeConsentEvent:
            raise PurposeConsentValidationError("evento de consentimento inválido")
        by_purpose[event.purpose].append(event)

    projections = tuple(
        project_purpose_consent(
            purpose=purpose,
            events=by_purpose[purpose],
            current_term_version=trusted_term_versions[purpose],
            global_optout=global_optout,
        )
        for purpose in PURPOSE_CONSENT_PURPOSES
    )
    return PurposeConsentSnapshot(
        projections=projections,
        global_optout=global_optout,
    )
