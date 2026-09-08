"""Closed, offline domain objects for the consent evidence store.

This module deliberately contains no ORM, provider, network, vault or runtime
adapter.  It describes the small value objects consumed by the internal unit
of work in :mod:`app.services.consent_evidence_store`.  A caller must obtain a
``TrustedConsentEvidenceAuthority`` from an independently implemented,
server-owned source before a value can be persisted.

The first slice is intentionally narrow: an authenticated adult acting for
themself may record an initial refusal.  Presentation evidence is also
supported.  ACCEPT and WITHDRAW are represented as parser values so a caller
can identify them, but they are not persistible in this slice.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
import secrets
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol, TypeAlias, runtime_checkable

from app.domain.purpose_consent import PurposeConsentPurpose


class ConsentEvidenceValidationError(ValueError):
    """A value cannot enter the closed evidence-store domain."""


class ConsentEvidenceSourceError(RuntimeError):
    """The independent source could not provide trusted authority."""


class ConsentEvidenceActionBlockedError(ConsentEvidenceValidationError):
    """An action is known but outside the E1--E3 writer boundary."""


# The existing purpose enum is the canonical cross-module enum.  Keeping the
# alias preserves identity when the evidence store is later joined to the
# purpose-consent ledger.
ConsentEvidencePurpose = PurposeConsentPurpose  # type: ignore[assignment,misc]


class ConsentEvidenceChannel(str, Enum):
    WHATSAPP = "WHATSAPP"
    PANEL = "PANEL"


class ConsentEvidenceLanguage(str, Enum):
    PT_BR = "pt-BR"


class ConsentChallengeState(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ConsentEvidenceType(str, Enum):
    PRESENTATION = "PRESENTATION"
    MANIFESTATION = "MANIFESTATION"


class ConsentEvidenceAction(str, Enum):
    ACCEPT = "ACCEPT"
    REFUSE_INITIAL = "REFUSE_INITIAL"
    WITHDRAW = "WITHDRAW"


class ConsentEvidenceLedgerState(str, Enum):
    ABSENT = "ABSENT"
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class ConsentEvidenceSubjectKind(str, Enum):
    ADULT_SELF = "ADULT_SELF"


class ConsentEvidenceAgeStatus(str, Enum):
    ADULT = "ADULT"
    UNKNOWN = "UNKNOWN"
    MINOR = "MINOR"


class ConsentEvidenceAuthenticationState(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"


class ConsentEvidenceSessionState(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ConsentEvidenceInteractionIntegrity(str, Enum):
    ORIGINAL_DIRECT = "ORIGINAL_DIRECT"
    EDITED = "EDITED"
    FORWARDED = "FORWARDED"
    UNKNOWN = "UNKNOWN"


class ConsentEvidenceChoiceMode(str, Enum):
    PRESENTATION_ONLY = "PRESENTATION_ONLY"
    EXPLICIT_CONTROL = "EXPLICIT_CONTROL"
    INFERRED = "INFERRED"


class ConsentEvidenceSchemaVersion(str, Enum):
    RECEIPT_LAB_V1 = "consent-receipt/lab-v1"


MAX_PACKAGE_VERSION_LENGTH: Final = 128
MAX_HASH_LENGTH: Final = 64
MAX_CHALLENGE_LIFETIME: Final = dt.timedelta(minutes=30)
REFUSAL_RETENTION_YEARS: Final = 5
PRESENTATION_RETENTION_DAYS: Final = 90
IDEMPOTENCY_KEY_PREFIX: Final = "ce:v1:"
_PACKAGE_VERSION_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_IDEMPOTENCY_KEY_RE: Final = re.compile(
    rf"{re.escape(IDEMPOTENCY_KEY_PREFIX)}[0-9a-f]{{64}}"
)
_IDEMPOTENCY_KEY_MINT_SECRET: Final = secrets.token_bytes(32)


def _reject(field: str, message: str | None = None) -> None:
    raise ConsentEvidenceValidationError(message or f"{field} inválido")


def require_uuid(value: object, *, field: str) -> uuid.UUID:
    """Require a non-zero UUID object; strings are not silently coerced."""

    if type(value) is not uuid.UUID or value.int == 0:
        _reject(field, f"{field} deve ser UUID não nulo")
    return value


def require_utc(value: object, *, field: str) -> dt.datetime:
    """Require an aware UTC datetime with no date/string coercion."""

    if type(value) is not dt.datetime:
        _reject(field, f"{field} deve ser datetime UTC")
    if value.tzinfo is None or value.utcoffset() != dt.timedelta(0):
        _reject(field, f"{field} deve estar em UTC")
    return value


def require_sha256(value: object, *, field: str) -> str:
    if type(value) is not str or not _SHA256_RE.fullmatch(value):
        _reject(field, f"{field} deve ser SHA-256 hexadecimal minúsculo")
    return value


def require_package_version(value: object) -> str:
    if (
        type(value) is not str
        or not value.isascii()
        or len(value) > MAX_PACKAGE_VERSION_LENGTH
        or _PACKAGE_VERSION_RE.fullmatch(value) is None
    ):
        _reject("package_version", "package_version inválido")
    return value


def _require_enum(value: object, enum_type: type[Enum], *, field: str) -> Enum:
    if type(value) is not enum_type:
        _reject(field)
    return value


def _require_optional_uuid(value: object, *, field: str) -> uuid.UUID | None:
    if value is None:
        return None
    return require_uuid(value, field=field)


def _format_instant(value: dt.datetime) -> str:
    """Canonical RFC3339 UTC representation with fixed microsecond precision."""

    value = require_utc(value, field="timestamp")
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_value(value: object) -> object:
    if isinstance(value, Enum):
        enum_value = value.value
        if type(enum_value) is not str or not enum_value.isascii():
            _reject("canonical_value", "enum canônico deve ter valor ASCII")
        return enum_value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        return _format_instant(value)
    if isinstance(value, OpaqueConsentEvidenceIdempotencyKey):
        return value.value
    if value is None or type(value) is bool:
        return value
    if type(value) is str:
        if not value.isascii():
            _reject("canonical_value", "strings canônicos devem ser ASCII")
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str or not key.isascii() for key in value):
            _reject("canonical_json", "chaves canônicas devem ser ASCII")
        return {
            key: _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda item: item[0])
        }
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    _reject("canonical_value", "valor não permitido na canonicalização")


def canonical_json(value: Mapping[str, object]) -> str:
    """Serialize the explicit closed JSON subset used by evidence digests."""

    normalized = _canonical_value(value)
    if not isinstance(normalized, dict):
        _reject("canonical_json", "envelope canônico inválido")
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


@dataclass(frozen=True, slots=True, init=False)
class OpaqueConsentEvidenceIdempotencyKey:
    """Server-minted opaque key with no string rehydration constructor."""

    value: str
    _mint_proof: bytes = field(repr=False, compare=False)

    @classmethod
    def generate(cls) -> OpaqueConsentEvidenceIdempotencyKey:
        entropy = secrets.token_hex(32)
        if type(entropy) is not str:
            raise ConsentEvidenceValidationError("aleatoriedade produziu chave inválida")
        value = f"{IDEMPOTENCY_KEY_PREFIX}{entropy}"
        if _IDEMPOTENCY_KEY_RE.fullmatch(value) is None:
            raise ConsentEvidenceValidationError("chave opaca inválida")
        instance = object.__new__(cls)
        object.__setattr__(instance, "value", value)
        object.__setattr__(
            instance,
            "_mint_proof",
            hmac.digest(_IDEMPOTENCY_KEY_MINT_SECRET, value.encode("ascii"), "sha256"),
        )
        return instance

    def _was_server_minted_in_this_process(self) -> bool:
        try:
            value = self.value
            proof = self._mint_proof
        except AttributeError:
            return False
        if (
            type(value) is not str
            or type(proof) is not bytes
            or _IDEMPOTENCY_KEY_RE.fullmatch(value) is None
        ):
            return False
        expected = hmac.digest(
            _IDEMPOTENCY_KEY_MINT_SECRET,
            value.encode("ascii"),
            "sha256",
        )
        return (
            secrets.compare_digest(proof, expected)
        )


def require_persisted_idempotency_key(value: object) -> str:
    """Validate a stored key without pretending it was minted in this process."""

    if type(value) is not str or _IDEMPOTENCY_KEY_RE.fullmatch(value) is None:
        _reject("chave_idempotencia", "chave persistida inválida")
    return value


# Short compatibility alias used by callers that do not need the long name.
ConsentEvidenceIdempotencyKey: TypeAlias = OpaqueConsentEvidenceIdempotencyKey


@dataclass(frozen=True, slots=True)
class ConsentChallenge:
    """Closed row-shaped challenge DTO."""

    id: uuid.UUID
    igreja_id: uuid.UUID
    pessoa_id: uuid.UUID
    finalidade: ConsentEvidencePurpose
    package_id: uuid.UUID
    package_version: str
    content_digest: str
    catalog_entry_digest: str
    notice_text_digest: str
    binding_id: uuid.UUID
    interaction_id: uuid.UUID
    canal: ConsentEvidenceChannel
    idioma: ConsentEvidenceLanguage
    criado_em: dt.datetime
    expira_em: dt.datetime
    estado: ConsentChallengeState = ConsentChallengeState.OPEN
    encerrado_em: dt.datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "id",
            "igreja_id",
            "pessoa_id",
            "package_id",
            "binding_id",
            "interaction_id",
        ):
            require_uuid(getattr(self, field_name), field=field_name)
        _require_enum(self.finalidade, PurposeConsentPurpose, field="finalidade")
        require_package_version(self.package_version)
        require_sha256(self.content_digest, field="content_digest")
        require_sha256(self.catalog_entry_digest, field="catalog_entry_digest")
        require_sha256(self.notice_text_digest, field="notice_text_digest")
        _require_enum(self.canal, ConsentEvidenceChannel, field="canal")
        _require_enum(self.idioma, ConsentEvidenceLanguage, field="idioma")
        _require_enum(self.estado, ConsentChallengeState, field="estado")
        created = require_utc(self.criado_em, field="criado_em")
        expires = require_utc(self.expira_em, field="expira_em")
        if expires <= created or expires - created > MAX_CHALLENGE_LIFETIME:
            _reject("expira_em", "desafio excede validade técnica de 30 minutos")
        ended = _require_optional_utc(self.encerrado_em, field="encerrado_em")
        if self.estado is ConsentChallengeState.OPEN:
            if ended is not None:
                _reject("encerrado_em", "desafio OPEN não pode estar encerrado")
        elif ended is None:
            _reject("encerrado_em", "desafio terminal exige encerrado_em")
        elif ended < created:
            _reject("encerrado_em", "encerrado_em anterior ao desafio")
        elif self.estado is ConsentChallengeState.EXPIRED and ended < expires:
            _reject("encerrado_em", "desafio EXPIRED exige instante após expiração")

    @property
    def challenge_id(self) -> uuid.UUID:
        return self.id

    def with_state(
        self, state: ConsentChallengeState, ended_at: dt.datetime
    ) -> ConsentChallenge:
        _require_enum(state, ConsentChallengeState, field="estado")
        if self.estado is not ConsentChallengeState.OPEN:
            _reject("estado", "desafio terminal não pode sofrer nova transição")
        if state is ConsentChallengeState.OPEN:
            _reject("estado", "transição terminal não pode reabrir desafio")
        ended_at = require_utc(ended_at, field="encerrado_em")
        if state is ConsentChallengeState.EXPIRED and ended_at < self.expira_em:
            _reject("encerrado_em", "desafio EXPIRED exige instante após expiração")
        return ConsentChallenge(
            id=self.id,
            igreja_id=self.igreja_id,
            pessoa_id=self.pessoa_id,
            finalidade=self.finalidade,
            package_id=self.package_id,
            package_version=self.package_version,
            content_digest=self.content_digest,
            catalog_entry_digest=self.catalog_entry_digest,
            notice_text_digest=self.notice_text_digest,
            binding_id=self.binding_id,
            interaction_id=self.interaction_id,
            canal=self.canal,
            idioma=self.idioma,
            criado_em=self.criado_em,
            expira_em=self.expira_em,
            estado=state,
            encerrado_em=ended_at,
        )


def _require_optional_utc(
    value: object, *, field: str
) -> dt.datetime | None:
    if value is None:
        return None
    return require_utc(value, field=field)


@dataclass(frozen=True, slots=True)
class ConsentEvidenceRecord:
    """Closed append-only evidence row."""

    id: uuid.UUID
    igreja_id: uuid.UUID
    desafio_id: uuid.UUID
    tipo: ConsentEvidenceType
    # Persisted rows intentionally use a validated string.  A persisted value
    # may be read after process restart; it is not rehydrated as a live
    # server-minted authority token.
    chave_idempotencia: str
    registrado_em: dt.datetime
    evidence_digest: str
    apresentacao_id: uuid.UUID | None = None
    acao: ConsentEvidenceAction | None = None

    def __post_init__(self) -> None:
        for field_name in ("id", "igreja_id", "desafio_id"):
            require_uuid(getattr(self, field_name), field=field_name)
        _require_enum(self.tipo, ConsentEvidenceType, field="tipo")
        require_persisted_idempotency_key(self.chave_idempotencia)
        require_utc(self.registrado_em, field="registrado_em")
        require_sha256(self.evidence_digest, field="evidence_digest")
        presentation_id = _require_optional_uuid(
            self.apresentacao_id, field="apresentacao_id"
        )
        if self.tipo is ConsentEvidenceType.PRESENTATION:
            if presentation_id is not None or self.acao is not None:
                _reject(
                    "apresentacao_id",
                    "PRESENTATION não pode conter manifestação",
                )
        else:
            if presentation_id is None:
                _reject("apresentacao_id", "MANIFESTATION exige apresentação")
            if self.acao is not ConsentEvidenceAction.REFUSE_INITIAL:
                _reject(
                    "acao",
                    "somente REFUSE_INITIAL é persistível neste estágio",
                )

    @property
    def evidence_id(self) -> uuid.UUID:
        return self.id


@dataclass(frozen=True, slots=True)
class ConsentReceipt:
    """Minimal refusal receipt; no delivery state is stored or claimed."""

    id: uuid.UUID
    igreja_id: uuid.UUID
    evidencia_id: uuid.UUID
    chave_idempotencia: str
    registrado_em: dt.datetime
    acao: ConsentEvidenceAction
    schema_version: ConsentEvidenceSchemaVersion = (
        ConsentEvidenceSchemaVersion.RECEIPT_LAB_V1
    )

    def __post_init__(self) -> None:
        for field_name in ("id", "igreja_id", "evidencia_id"):
            require_uuid(getattr(self, field_name), field=field_name)
        require_persisted_idempotency_key(self.chave_idempotencia)
        require_utc(self.registrado_em, field="registrado_em")
        if self.acao is not ConsentEvidenceAction.REFUSE_INITIAL:
            _reject("acao", "recibo E2 só admite REFUSE_INITIAL")
        _require_enum(
            self.schema_version,
            ConsentEvidenceSchemaVersion,
            field="schema_version",
        )


@dataclass(frozen=True, slots=True)
class ConsentEvidenceRequest:
    """Input envelope for presentation or initial-refusal recording.

    The timestamps are checked against observations returned by the trusted
    source.  They are not an authority by themselves.
    """

    desafio: ConsentChallenge
    chave_idempotencia: OpaqueConsentEvidenceIdempotencyKey
    apresentada_em: dt.datetime
    manifestada_em: dt.datetime | None = None
    acao: ConsentEvidenceAction | None = None

    def __post_init__(self) -> None:
        if type(self.desafio) is not ConsentChallenge:
            _reject("desafio", "desafio fechado obrigatório")
        if type(self.chave_idempotencia) is not OpaqueConsentEvidenceIdempotencyKey:
            _reject("chave_idempotencia", "chave opaca inválida")
        if not self.chave_idempotencia._was_server_minted_in_this_process():
            _reject("chave_idempotencia", "chave sem proveniência server-owned")
        presented = require_utc(self.apresentada_em, field="apresentada_em")
        manifested = _require_optional_utc(
            self.manifestada_em, field="manifestada_em"
        )
        if self.acao is None:
            if manifested is not None:
                _reject("manifestada_em", "PRESENTATION não tem manifestação")
        elif self.acao is ConsentEvidenceAction.REFUSE_INITIAL:
            if manifested is None:
                _reject("manifestada_em", "recusa exige manifestação")
        elif self.acao in (
            ConsentEvidenceAction.ACCEPT,
            ConsentEvidenceAction.WITHDRAW,
        ):
            # Keep parser values visible, but make the service's pre-I/O gate
            # deterministic and impossible to bypass through a DTO.
            if manifested is None:
                _reject("manifestada_em", "ação explícita exige manifestação")
        else:
            _reject("acao", "ação inválida")
        if presented < self.desafio.criado_em or presented >= self.desafio.expira_em:
            _reject("apresentada_em", "apresentação fora da validade do desafio")
        if manifested is not None and (
            manifested < presented or manifested >= self.desafio.expira_em
        ):
            _reject("manifestada_em", "manifestação fora da validade do desafio")


@dataclass(frozen=True, slots=True)
class TrustedAdultSelfSubject:
    """Server observation proving the narrow adult/self boundary."""

    kind: ConsentEvidenceSubjectKind
    age_status: ConsentEvidenceAgeStatus
    authentication_state: ConsentEvidenceAuthenticationState
    session_state: ConsentEvidenceSessionState
    interaction_integrity: ConsentEvidenceInteractionIntegrity
    choice_mode: ConsentEvidenceChoiceMode

    def __post_init__(self) -> None:
        _require_enum(self.kind, ConsentEvidenceSubjectKind, field="subject_kind")
        _require_enum(
            self.age_status, ConsentEvidenceAgeStatus, field="age_status"
        )
        _require_enum(
            self.authentication_state,
            ConsentEvidenceAuthenticationState,
            field="authentication_state",
        )
        _require_enum(
            self.session_state,
            ConsentEvidenceSessionState,
            field="session_state",
        )
        _require_enum(
            self.interaction_integrity,
            ConsentEvidenceInteractionIntegrity,
            field="interaction_integrity",
        )
        _require_enum(
            self.choice_mode, ConsentEvidenceChoiceMode, field="choice_mode"
        )


@dataclass(frozen=True, slots=True)
class TrustedConsentEvidenceAuthority:
    """Closed result from an independently server-owned source.

    There is intentionally no ``authorized: bool`` field.  The service only
    accepts the complete typed observation and validates every member against
    the requested challenge before and after acquiring database locks.
    """

    igreja_id: uuid.UUID
    pessoa_id: uuid.UUID
    actor_id: uuid.UUID
    finalidade: ConsentEvidencePurpose
    package_id: uuid.UUID
    package_version: str
    content_digest: str
    catalog_entry_digest: str
    notice_text_digest: str
    binding_id: uuid.UUID
    interaction_id: uuid.UUID
    canal: ConsentEvidenceChannel
    idioma: ConsentEvidenceLanguage
    subject: TrustedAdultSelfSubject
    prior_ledger_state: ConsentEvidenceLedgerState
    prior_event_id: uuid.UUID | None = None
    action: ConsentEvidenceAction | None = None
    presented_at: dt.datetime | None = None
    manifested_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "igreja_id",
            "pessoa_id",
            "actor_id",
            "package_id",
            "binding_id",
            "interaction_id",
        ):
            require_uuid(getattr(self, field_name), field=field_name)
        if self.actor_id != self.pessoa_id:
            _reject("actor_id", "ator não é a própria Pessoa")
        _require_enum(self.finalidade, PurposeConsentPurpose, field="finalidade")
        require_package_version(self.package_version)
        require_sha256(self.content_digest, field="content_digest")
        require_sha256(self.catalog_entry_digest, field="catalog_entry_digest")
        require_sha256(self.notice_text_digest, field="notice_text_digest")
        _require_enum(self.canal, ConsentEvidenceChannel, field="canal")
        _require_enum(self.idioma, ConsentEvidenceLanguage, field="idioma")
        if type(self.subject) is not TrustedAdultSelfSubject:
            _reject("subject", "observação de sujeito inválida")
        _require_enum(
            self.prior_ledger_state,
            ConsentEvidenceLedgerState,
            field="prior_ledger_state",
        )
        _require_optional_uuid(self.prior_event_id, field="prior_event_id")
        if self.prior_ledger_state is ConsentEvidenceLedgerState.ABSENT:
            if self.prior_event_id is not None:
                _reject("prior_event_id", "ledger ausente não tem evento anterior")
        elif self.prior_event_id is None:
            _reject("prior_event_id", "ledger presente exige evento anterior")
        if self.action is not None:
            _require_enum(self.action, ConsentEvidenceAction, field="action")
        _require_optional_utc(self.presented_at, field="presented_at")
        _require_optional_utc(self.manifested_at, field="manifested_at")


@runtime_checkable
class ConsentEvidenceSource(Protocol):
    """Interface for a future server-owned authority adapter.

    Implementations are deliberately external to this module.  Both methods
    return a complete typed observation; neither returns a permission boolean.
    ``revalidate`` must perform a fresh observation after the UoW locks.
    """

    def resolve(
        self,
        request: ConsentEvidenceRequest,
        *,
        now: dt.datetime,
    ) -> TrustedConsentEvidenceAuthority:
        ...

    def revalidate(
        self,
        request: ConsentEvidenceRequest,
        previous: TrustedConsentEvidenceAuthority,
        *,
        now: dt.datetime,
    ) -> TrustedConsentEvidenceAuthority:
        ...


class DenyByDefaultConsentEvidenceSource:
    """Default source: no evidence-store operation is authorized."""

    def resolve(
        self,
        request: ConsentEvidenceRequest,
        *,
        now: dt.datetime,
    ) -> TrustedConsentEvidenceAuthority:
        raise ConsentEvidenceSourceError("fonte server-owned indisponível")

    def revalidate(
        self,
        request: ConsentEvidenceRequest,
        previous: TrustedConsentEvidenceAuthority,
        *,
        now: dt.datetime,
    ) -> TrustedConsentEvidenceAuthority:
        raise ConsentEvidenceSourceError("fonte server-owned indisponível")


DEFAULT_CONSENT_EVIDENCE_SOURCE: Final = DenyByDefaultConsentEvidenceSource()


def evidence_digest_payload(evidence: ConsentEvidenceRecord) -> dict[str, object]:
    """Return the closed envelope used to calculate ``evidence_digest``."""

    if type(evidence) is not ConsentEvidenceRecord:
        _reject("evidence", "evidência fechada obrigatória")

    return {
        "id": evidence.id,
        "igreja_id": evidence.igreja_id,
        "desafio_id": evidence.desafio_id,
        "tipo": evidence.tipo,
        "chave_idempotencia": evidence.chave_idempotencia,
        "registrado_em": evidence.registrado_em,
        "apresentacao_id": evidence.apresentacao_id,
        "acao": evidence.acao,
    }


def compute_evidence_digest(
    evidence: ConsentEvidenceRecord,
    challenge: ConsentChallenge,
) -> str:
    """Hash evidence plus the complete immutable challenge binding.

    A digest without the immutable challenge tuple is not evidence for this
    store.  Requiring the challenge at the signature boundary prevents a
    caller from accidentally producing an unverifiable row hash.
    """

    if type(evidence) is not ConsentEvidenceRecord:
        _reject("evidence", "evidência fechada obrigatória")
    payload = evidence_digest_payload(evidence)
    if type(challenge) is not ConsentChallenge:
        _reject("challenge", "desafio fechado obrigatório")
    if (
        challenge.id != evidence.desafio_id
        or challenge.igreja_id != evidence.igreja_id
    ):
        _reject("challenge", "desafio não corresponde à evidência")
    payload["challenge"] = {
        "id": challenge.id,
        "igreja_id": challenge.igreja_id,
        "pessoa_id": challenge.pessoa_id,
        "finalidade": challenge.finalidade,
        "package_id": challenge.package_id,
        "package_version": challenge.package_version,
        "content_digest": challenge.content_digest,
        "catalog_entry_digest": challenge.catalog_entry_digest,
        "notice_text_digest": challenge.notice_text_digest,
        "binding_id": challenge.binding_id,
        "interaction_id": challenge.interaction_id,
        "canal": challenge.canal,
        "idioma": challenge.idioma,
        "criado_em": challenge.criado_em,
        "expira_em": challenge.expira_em,
    }
    return hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()


def evidence_matches_digest(
    evidence: ConsentEvidenceRecord,
    challenge: ConsentChallenge,
) -> bool:
    if (
        type(evidence) is not ConsentEvidenceRecord
        or type(challenge) is not ConsentChallenge
    ):
        return False
    return secrets.compare_digest(
        evidence.evidence_digest, compute_evidence_digest(evidence, challenge)
    )


def build_evidence(
    *,
    evidence_id: uuid.UUID,
    igreja_id: uuid.UUID,
    desafio_id: uuid.UUID,
    tipo: ConsentEvidenceType,
    chave_idempotencia: OpaqueConsentEvidenceIdempotencyKey,
    challenge: ConsentChallenge,
    registrado_em: dt.datetime,
    apresentacao_id: uuid.UUID | None = None,
    acao: ConsentEvidenceAction | None = None,
) -> ConsentEvidenceRecord:
    """Build a record and calculate its digest inside the trusted service."""

    if type(challenge) is not ConsentChallenge:
        _reject("challenge", "desafio fechado obrigatório")
    if (
        type(chave_idempotencia) is not OpaqueConsentEvidenceIdempotencyKey
        or not chave_idempotencia._was_server_minted_in_this_process()
    ):
        _reject("chave_idempotencia", "chave sem proveniência server-owned")
    if (
        challenge.id != desafio_id
        or challenge.igreja_id != igreja_id
    ):
        _reject("challenge", "desafio não corresponde à evidência")
    provisional = ConsentEvidenceRecord(
        id=evidence_id,
        igreja_id=igreja_id,
        desafio_id=desafio_id,
        tipo=tipo,
        chave_idempotencia=chave_idempotencia.value,
        registrado_em=registrado_em,
        evidence_digest="0" * 64,
        apresentacao_id=apresentacao_id,
        acao=acao,
    )
    return ConsentEvidenceRecord(
        id=provisional.id,
        igreja_id=provisional.igreja_id,
        desafio_id=provisional.desafio_id,
        tipo=provisional.tipo,
        chave_idempotencia=provisional.chave_idempotencia,
        registrado_em=provisional.registrado_em,
        evidence_digest=compute_evidence_digest(provisional, challenge),
        apresentacao_id=provisional.apresentacao_id,
        acao=provisional.acao,
    )


def add_calendar_years(value: dt.datetime, years: int) -> dt.datetime:
    """Add calendar years and clamp February 29 to February 28."""

    value = require_utc(value, field="retention_start")
    if type(years) is not int or years < 0:
        _reject("years", "anos de retenção inválidos")
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        # The only invalid date generated by preserving month/day across years
        # in this contract is February 29 in a non-leap target year.
        if value.month == 2 and value.day == 29:
            return value.replace(year=value.year + years, day=28)
        raise


def refusal_retention_deadline(recorded_at: dt.datetime) -> dt.datetime:
    return add_calendar_years(recorded_at, REFUSAL_RETENTION_YEARS)


def presentation_retention_deadline(
    *,
    challenge_expires_at: dt.datetime,
    abandoned_at: dt.datetime | None = None,
    challenge_created_at: dt.datetime | None = None,
) -> dt.datetime:
    """Return 90 days after abandonment, or after challenge expiry.

    An observation after expiry cannot extend retention: its anchor is clamped
    to ``challenge_expires_at``.  When the creation instant is supplied, an
    abandonment before creation is rejected as malformed.
    """

    expires = require_utc(challenge_expires_at, field="challenge_expires_at")
    abandoned = _require_optional_utc(abandoned_at, field="abandoned_at")
    created = _require_optional_utc(
        challenge_created_at, field="challenge_created_at"
    )
    if created is not None and created >= expires:
        _reject("challenge_created_at", "criação não precede expiração")
    if abandoned is not None and created is not None and abandoned < created:
        _reject("abandoned_at", "abandono anterior ao desafio")
    # Abandonment after the technical expiry is not a new retention anchor.
    start = expires if abandoned is None or abandoned >= expires else abandoned
    return start + dt.timedelta(days=PRESENTATION_RETENTION_DAYS)


def receipt_retention_deadline(
    *,
    action: ConsentEvidenceAction,
    recorded_at: dt.datetime,
    challenge_expires_at: dt.datetime | None = None,
    abandoned_at: dt.datetime | None = None,
    challenge_created_at: dt.datetime | None = None,
) -> dt.datetime:
    """Return the receipt deadline matching its evidence, without delivery."""

    _require_enum(action, ConsentEvidenceAction, field="action")
    recorded_at = require_utc(recorded_at, field="recorded_at")
    if action is ConsentEvidenceAction.REFUSE_INITIAL:
        return refusal_retention_deadline(recorded_at)
    if challenge_expires_at is None:
        _reject("challenge_expires_at", "apresentação exige expiração do desafio")
    return presentation_retention_deadline(
        challenge_expires_at=challenge_expires_at,
        abandoned_at=abandoned_at,
        challenge_created_at=challenge_created_at,
    )


def validate_source_binding(
    request: ConsentEvidenceRequest,
    authority: TrustedConsentEvidenceAuthority,
) -> None:
    """Check every authority member against the closed challenge/request."""

    if type(request) is not ConsentEvidenceRequest:
        _reject("request", "solicitação fechada obrigatória")
    if type(authority) is not TrustedConsentEvidenceAuthority:
        _reject("authority", "observação server-owned inválida")

    challenge = request.desafio
    expected = {
        "igreja_id": challenge.igreja_id,
        "pessoa_id": challenge.pessoa_id,
        "finalidade": challenge.finalidade,
        "package_id": challenge.package_id,
        "package_version": challenge.package_version,
        "content_digest": challenge.content_digest,
        "catalog_entry_digest": challenge.catalog_entry_digest,
        "notice_text_digest": challenge.notice_text_digest,
        "binding_id": challenge.binding_id,
        "interaction_id": challenge.interaction_id,
        "canal": challenge.canal,
        "idioma": challenge.idioma,
    }
    for field_name, expected_value in expected.items():
        if getattr(authority, field_name) != expected_value:
            _reject(field_name, "fonte server-owned diverge do desafio")
    if authority.actor_id != challenge.pessoa_id:
        _reject("actor_id", "ator não é a própria Pessoa")
    subject = authority.subject
    if (
        subject.kind is not ConsentEvidenceSubjectKind.ADULT_SELF
        or subject.age_status is not ConsentEvidenceAgeStatus.ADULT
        or subject.authentication_state
        is not ConsentEvidenceAuthenticationState.VALID
        or subject.session_state is not ConsentEvidenceSessionState.ACTIVE
        or subject.interaction_integrity
        is not ConsentEvidenceInteractionIntegrity.ORIGINAL_DIRECT
    ):
        _reject("subject", "sujeito adulto autenticado não comprovado")
    if request.acao is None:
        if (
            authority.action is not None
            or subject.choice_mode is not ConsentEvidenceChoiceMode.PRESENTATION_ONLY
        ):
            _reject("choice_mode", "apresentação não pode conter escolha")
    else:
        if subject.choice_mode is not ConsentEvidenceChoiceMode.EXPLICIT_CONTROL:
            _reject("choice_mode", "manifestação exige controle explícito")
        if authority.action is not request.acao:
            _reject("action", "ação observada diverge da solicitação")
        if (
            request.acao is ConsentEvidenceAction.REFUSE_INITIAL
            and authority.prior_ledger_state is not ConsentEvidenceLedgerState.ABSENT
        ):
            _reject("prior_ledger_state", "recusa inicial não pode reclassificar ledger")
    if authority.presented_at != request.apresentada_em:
        _reject("presented_at", "horário de apresentação não comprovado")
    if authority.manifested_at != request.manifestada_em:
        _reject("manifested_at", "horário de manifestação não comprovado")
    if authority.presented_at is not None:
        if (
            authority.presented_at < challenge.criado_em
            or authority.presented_at >= challenge.expira_em
        ):
            _reject("presented_at", "apresentação fora da validade")
    if authority.manifested_at is not None:
        if authority.presented_at is None or authority.manifested_at < authority.presented_at:
            _reject("manifested_at", "cronologia da manifestação inválida")
        if authority.manifested_at >= challenge.expira_em:
            _reject("manifested_at", "manifestação após expiração")


def compare_challenges(left: ConsentChallenge, right: ConsentChallenge) -> bool:
    """Compare only immutable challenge intent (not consume state/timestamps)."""

    if type(left) is not ConsentChallenge or type(right) is not ConsentChallenge:
        return False
    return _challenge_immutable_tuple(left) == _challenge_immutable_tuple(right)


def _challenge_immutable_tuple(
    challenge: ConsentChallenge,
) -> tuple[object, ...]:
    return (
        challenge.id,
        challenge.igreja_id,
        challenge.pessoa_id,
        challenge.finalidade,
        challenge.package_id,
        challenge.package_version,
        challenge.content_digest,
        challenge.catalog_entry_digest,
        challenge.notice_text_digest,
        challenge.binding_id,
        challenge.interaction_id,
        challenge.canal,
        challenge.idioma,
        challenge.criado_em,
        challenge.expira_em,
    )


def compare_evidence_intent(
    existing: ConsentEvidenceRecord,
    *,
    request: ConsentEvidenceRequest,
    presentation_id: uuid.UUID | None = None,
) -> bool:
    """Compare all immutable fields relevant to an idempotent replay."""

    if (
        type(existing) is not ConsentEvidenceRecord
        or type(request) is not ConsentEvidenceRequest
    ):
        return False
    if not evidence_matches_digest(existing, request.desafio):
        return False
    if request.acao is None:
        return (
            existing.tipo is ConsentEvidenceType.PRESENTATION
            and existing.desafio_id == request.desafio.id
            and existing.chave_idempotencia == request.chave_idempotencia.value
            and existing.registrado_em == request.apresentada_em
            and existing.apresentacao_id is None
            and existing.acao is None
        )
    return (
        existing.tipo is ConsentEvidenceType.MANIFESTATION
        and existing.desafio_id == request.desafio.id
        and existing.chave_idempotencia == request.chave_idempotencia.value
        and existing.registrado_em == request.manifestada_em
        and existing.apresentacao_id == presentation_id
        and existing.acao is request.acao
    )


__all__ = [
    "ConsentChallenge",
    "ConsentChallengeState",
    "ConsentEvidenceAction",
    "ConsentEvidenceAgeStatus",
    "ConsentEvidenceAuthenticationState",
    "ConsentEvidenceChannel",
    "ConsentEvidenceChoiceMode",
    "ConsentEvidenceIdempotencyKey",
    "ConsentEvidenceInteractionIntegrity",
    "ConsentEvidenceLanguage",
    "ConsentEvidenceLedgerState",
    "ConsentEvidencePurpose",
    "ConsentEvidenceRecord",
    "ConsentEvidenceRequest",
    "ConsentEvidenceSchemaVersion",
    "ConsentEvidenceSessionState",
    "ConsentEvidenceSource",
    "ConsentEvidenceSourceError",
    "ConsentEvidenceSubjectKind",
    "ConsentEvidenceType",
    "ConsentEvidenceValidationError",
    "ConsentReceipt",
    "DEFAULT_CONSENT_EVIDENCE_SOURCE",
    "DenyByDefaultConsentEvidenceSource",
    "MAX_CHALLENGE_LIFETIME",
    "OpaqueConsentEvidenceIdempotencyKey",
    "PRESENTATION_RETENTION_DAYS",
    "REFUSAL_RETENTION_YEARS",
    "TrustedAdultSelfSubject",
    "TrustedConsentEvidenceAuthority",
    "add_calendar_years",
    "build_evidence",
    "canonical_json",
    "compare_challenges",
    "compare_evidence_intent",
    "compute_evidence_digest",
    "evidence_digest_payload",
    "evidence_matches_digest",
    "presentation_retention_deadline",
    "receipt_retention_deadline",
    "refusal_retention_deadline",
    "require_package_version",
    "require_persisted_idempotency_key",
    "require_sha256",
    "require_uuid",
    "require_utc",
    "validate_source_binding",
]
