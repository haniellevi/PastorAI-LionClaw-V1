"""Domínio puro da operação de consentimento E4b (C0).

Este módulo contém apenas valores imutáveis, validações e projeções. Ele não
conhece o consentimento legado, não abre I/O e não escolhe um adapter de
persistência. Um futuro boundary deve resolver identidade, tenant, vínculos e
capabilities no servidor e entregar somente os fatos abaixo ao classificador.
"""

from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Final, NewType


class E4bValidationError(ValueError):
    """Valor não atende ao contrato fechado do domínio E4b."""


class E4bAction(str, Enum):
    """Ações próprias da cadeia E4b."""

    ACCEPT = "ACCEPT"
    WITHDRAW = "WITHDRAW"


class E4bOrigin(str, Enum):
    """Origem única aceita por este domínio."""

    E4B = "E4B"


class E4bConcessionState(str, Enum):
    """Estado derivado da concessão por stream."""

    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class E4bManifestantRole(str, Enum):
    """Vínculo explícito de quem manifesta a ação."""

    TITULAR = "TITULAR"
    RESPONSAVEL = "RESPONSAVEL"


class E4bOperatorKind(str, Enum):
    """Forma fechada da identidade que executa o fluxo."""

    HUMAN = "HUMAN"
    TECHNICAL = "TECHNICAL"


class E4bRole(str, Enum):
    """Papéis que podem aparecer em um vínculo de autoria explícito."""

    TITULAR = "TITULAR"
    MANIFESTANTE = "MANIFESTANTE"
    RESPONSAVEL = "RESPONSAVEL"


class E4bClassification(str, Enum):
    """Resultado puro da classificação de uma intenção."""

    ELIGIBLE = "ELIGIBLE"
    REPLAY = "REPLAY"
    CONFLICT = "CONFLICT"
    DENIED = "DENIED"


class E4bDenialReason(str, Enum):
    """Motivos observáveis, sem transportar conteúdo pastoral ou PII."""

    INVALID_INPUT = "INVALID_INPUT"
    LEGACY_ARTIFACT = "LEGACY_ARTIFACT"
    AUTHORITY_UNRESOLVED = "AUTHORITY_UNRESOLVED"
    MANIFESTANT_RELATION_INVALID = "MANIFESTANT_RELATION_INVALID"
    OPERATOR_ROLE_UNRESOLVED = "OPERATOR_ROLE_UNRESOLVED"
    TENANT_MISMATCH = "TENANT_MISMATCH"
    FINGERPRINT_INVALID = "FINGERPRINT_INVALID"
    ACTION_ORIGIN_INVALID = "ACTION_ORIGIN_INVALID"
    ACTIVE_CONCESSION = "ACTIVE_CONCESSION"
    WITHDRAWN_CONCESSION = "WITHDRAWN_CONCESSION"
    MISSING_ORIGIN = "MISSING_ORIGIN"
    ORIGIN_NOT_ACCEPT = "ORIGIN_NOT_ACCEPT"
    ORIGIN_NOT_ACTIVE = "ORIGIN_NOT_ACTIVE"
    ORIGIN_NOT_CONFIRMED = "ORIGIN_NOT_CONFIRMED"
    ORIGIN_TENANT_MISMATCH = "ORIGIN_TENANT_MISMATCH"
    ORIGIN_SUBJECT_MISMATCH = "ORIGIN_SUBJECT_MISMATCH"
    ORIGIN_PURPOSE_MISMATCH = "ORIGIN_PURPOSE_MISMATCH"
    CONCESSION_MISMATCH = "CONCESSION_MISMATCH"


class E4bAccessDecision(str, Enum):
    """Resultado da autorização de leitura administrativa."""

    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class E4bAdminScope(str, Enum):
    """Escopos administrativos permitidos pelo contrato."""

    READ = "READ"
    REIDENTIFY = "REIDENTIFY"


class E4bRetentionState(str, Enum):
    """Projeção da retenção identificável."""

    RETENTION_RUNNING = "RETENTION_RUNNING"
    RETENTION_HELD = "RETENTION_HELD"
    RETENTION_ELIGIBLE = "RETENTION_ELIGIBLE"


class E4bHoldEventType(str, Enum):
    """Eventos imutáveis que abrem ou resolvem um legal hold."""

    HOLD_APPLIED = "HOLD_APPLIED"
    HOLD_RESOLVED = "HOLD_RESOLVED"


class E4bDeleteDecision(str, Enum):
    """A disposição de Pessoa continua fora do domínio C0."""

    DENIED = "DENIED"
    DEFERRED = "DEFERRED"


# Estes aliases documentam a separação sem criar wrappers que permitam misturar
# identificadores de cadeias diferentes por acidente no código chamador.
E4bOperationId = NewType("E4bOperationId", uuid.UUID)
E4bCorrelationId = NewType("E4bCorrelationId", uuid.UUID)
E4bReceiptId = NewType("E4bReceiptId", uuid.UUID)
E4bHoldId = NewType("E4bHoldId", uuid.UUID)

E4B_IDEMPOTENCY_KEY_PREFIX: Final = "e4b:consent-operation:v1:"
E4B_FINGERPRINT_VERSION: Final = "e4b-fingerprint:v1"
E4B_RETENTION_MONTHS: Final = 24
E4B_RECEIPT_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "operation_id",
        "correlation_id",
        "receipt_id",
        "igreja_id",
        "action",
        "concession_state",
        "origin",
        "manifestant_role",
        "confirmed_at",
        "contract_version",
        "policy_version",
        "term_version",
        "content_digest",
        "fingerprint",
    }
)

_KEY_SUFFIX_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}")
_DIGEST_RE: Final = re.compile(r"[0-9a-f]{64}")
_SAFE_VERSION_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_UTC: Final = dt.timezone.utc


def _fail(field_name: str, message: str) -> None:
    raise E4bValidationError(f"{field_name}: {message}")


def _require_uuid(value: object, *, field_name: str) -> uuid.UUID:
    if type(value) is not uuid.UUID or value.int == 0:
        _fail(field_name, "UUID não nulo obrigatório")
    return value


def _require_exact_enum(
    value: object, enum_type: type[Enum], *, field_name: str
) -> None:
    if type(value) is not enum_type:
        _fail(field_name, "enum fechado obrigatório")


def _require_text(value: object, *, field_name: str, max_length: int = 128) -> str:
    if type(value) is not str or not value or value != value.strip():
        _fail(field_name, "texto normalizado obrigatório")
    if len(value) > max_length:
        _fail(field_name, "texto excede o limite")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        _fail(field_name, "texto contém caractere de controle")
    return value


def _require_version(value: object, *, field_name: str) -> str:
    _require_text(value, field_name=field_name)
    if _SAFE_VERSION_RE.fullmatch(value) is None:
        _fail(field_name, "versão inválida")
    return value


def _require_digest(value: object, *, field_name: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        _fail(field_name, "digest SHA-256 hexadecimal obrigatório")
    return value


def _as_utc(value: object, *, field_name: str) -> dt.datetime:
    if not isinstance(value, dt.datetime):
        _fail(field_name, "instante UTC obrigatório")
    if value.tzinfo is None or value.utcoffset() is None:
        _fail(field_name, "instante sem fuso não é aceito")
    return value.astimezone(_UTC)


def _require_bool(value: object, *, field_name: str) -> bool:
    if type(value) is not bool:
        _fail(field_name, "booleano obrigatório")
    return value


def _uuid_tuple(value: Iterable[object], *, field_name: str) -> tuple[uuid.UUID, ...]:
    if isinstance(value, (str, bytes)):
        _fail(field_name, "sequência de UUIDs obrigatória")
    try:
        result = tuple(_require_uuid(item, field_name=field_name) for item in value)
    except TypeError as exc:
        raise E4bValidationError(f"{field_name}: sequência obrigatória") from exc
    if len(set(result)) != len(result):
        _fail(field_name, "UUID repetido")
    return result


@dataclass(frozen=True, slots=True)
class E4bIdempotencyKey:
    """Chave opaca reidratável somente dentro de um tenant E4b."""

    igreja_id: uuid.UUID
    value: str

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        if type(self.value) is not str or not self.value.startswith(
            E4B_IDEMPOTENCY_KEY_PREFIX
        ):
            _fail("value", "namespace E4b obrigatório")
        suffix = self.value[len(E4B_IDEMPOTENCY_KEY_PREFIX) :]
        if _KEY_SUFFIX_RE.fullmatch(suffix) is None:
            _fail("value", "chave idempotente opaca inválida")

    @classmethod
    def from_persisted(
        cls, *, igreja_id: uuid.UUID, value: str
    ) -> "E4bIdempotencyKey":
        """Reidrata um valor já lido por um boundary E4b autorizado."""

        return cls(igreja_id=igreja_id, value=value)


@dataclass(frozen=True, slots=True)
class E4bFingerprint:
    """Digest hexadecimal da intenção fechada pelo servidor."""

    value: str

    def __post_init__(self) -> None:
        _require_digest(self.value, field_name="fingerprint")


@dataclass(frozen=True, slots=True)
class E4bAuthorityResolution:
    """Fatos de identidade resolvidos antes de entrar no domínio.

    Os booleanos são atestações de um boundary confiável. O domínio não os
    deduz a partir de IDs, e a igualdade de IDs só é válida quando um vínculo
    de sobreposição foi explicitamente resolvido em ``operator_role_links``.
    """

    igreja_id: uuid.UUID
    titular_pessoa_id: uuid.UUID
    manifestante_pessoa_id: uuid.UUID
    manifestant_role: E4bManifestantRole
    responsavel_pessoa_id: uuid.UUID | None
    operador_id: uuid.UUID
    operator_kind: E4bOperatorKind
    finalidade_id: str
    origin: E4bOrigin
    correlation_id: uuid.UUID
    contract_version: str
    policy_version: str
    term_version: str
    content_digest: str
    server_resolved: bool = True
    manifestant_relation_valid: bool = True
    operator_role_links: frozenset[E4bRole] = frozenset()
    legacy_artifact: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.titular_pessoa_id, field_name="titular_pessoa_id")
        _require_uuid(
            self.manifestante_pessoa_id, field_name="manifestante_pessoa_id"
        )
        _require_exact_enum(
            self.manifestant_role,
            E4bManifestantRole,
            field_name="manifestant_role",
        )
        if self.responsavel_pessoa_id is not None:
            _require_uuid(self.responsavel_pessoa_id, field_name="responsavel_pessoa_id")
        _require_uuid(self.operador_id, field_name="operador_id")
        _require_exact_enum(self.operator_kind, E4bOperatorKind, field_name="operator_kind")
        _require_text(self.finalidade_id, field_name="finalidade_id")
        _require_exact_enum(self.origin, E4bOrigin, field_name="origin")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        _require_version(self.contract_version, field_name="contract_version")
        _require_version(self.policy_version, field_name="policy_version")
        _require_version(self.term_version, field_name="term_version")
        _require_digest(self.content_digest, field_name="content_digest")
        _require_bool(self.server_resolved, field_name="server_resolved")
        _require_bool(
            self.manifestant_relation_valid,
            field_name="manifestant_relation_valid",
        )
        if type(self.operator_role_links) is not frozenset:
            _fail("operator_role_links", "frozenset obrigatório")
        if any(type(role) is not E4bRole for role in self.operator_role_links):
            _fail("operator_role_links", "papel fechado obrigatório")
        if self.manifestant_role is E4bManifestantRole.TITULAR:
            if self.manifestante_pessoa_id != self.titular_pessoa_id:
                _fail("manifestante_pessoa_id", "titular deve manifestar em seu próprio nome")
            if self.responsavel_pessoa_id is not None:
                _fail("responsavel_pessoa_id", "titular não possui responsável no vínculo")
        else:
            if self.responsavel_pessoa_id is None:
                _fail("responsavel_pessoa_id", "responsável obrigatório")
            if self.manifestante_pessoa_id != self.responsavel_pessoa_id:
                _fail("manifestante_pessoa_id", "manifestante deve ser o responsável resolvido")
            if self.responsavel_pessoa_id == self.titular_pessoa_id:
                _fail("responsavel_pessoa_id", "responsável deve ser distinto do titular")

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.igreja_id

    @property
    def manifestant_id(self) -> uuid.UUID:
        return self.manifestante_pessoa_id

    @property
    def operator_id(self) -> uuid.UUID:
        return self.operador_id


@dataclass(frozen=True, slots=True)
class E4bConsentIntent:
    """Intenção E4b ainda não confirmada nem persistida."""

    action: E4bAction
    idempotency_key: E4bIdempotencyKey
    fingerprint: E4bFingerprint
    authority: E4bAuthorityResolution
    origin_accept_operation_id: uuid.UUID | None = None
    legacy_artifact: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_exact_enum(self.action, E4bAction, field_name="action")
        if type(self.idempotency_key) is not E4bIdempotencyKey:
            _fail("idempotency_key", "chave E4b obrigatória")
        if type(self.fingerprint) is not E4bFingerprint:
            _fail("fingerprint", "fingerprint E4b obrigatório")
        if type(self.authority) is not E4bAuthorityResolution:
            _fail("authority", "resolução de autoridade obrigatória")
        if self.origin_accept_operation_id is not None:
            _require_uuid(
                self.origin_accept_operation_id,
                field_name="origin_accept_operation_id",
            )

    @classmethod
    def create(
        cls,
        *,
        action: E4bAction,
        idempotency_key: E4bIdempotencyKey,
        authority: E4bAuthorityResolution,
        origin_accept_operation_id: uuid.UUID | None = None,
        legacy_artifact: object | None = None,
    ) -> "E4bConsentIntent":
        """Monta a intenção usando o digest canônico do próprio domínio."""

        provisional = cls(
            action=action,
            idempotency_key=idempotency_key,
            fingerprint=E4bFingerprint("0" * 64),
            authority=authority,
            origin_accept_operation_id=origin_accept_operation_id,
            legacy_artifact=legacy_artifact,
        )
        return replace(provisional, fingerprint=compute_e4b_fingerprint(provisional))


@dataclass(frozen=True, slots=True)
class E4bConcession:
    """Projeção da concessão para um stream de igreja, titular e finalidade."""

    igreja_id: uuid.UUID
    titular_pessoa_id: uuid.UUID
    finalidade_id: str
    state: E4bConcessionState
    accept_operation_id: uuid.UUID
    withdraw_operation_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.titular_pessoa_id, field_name="titular_pessoa_id")
        _require_text(self.finalidade_id, field_name="finalidade_id")
        _require_exact_enum(self.state, E4bConcessionState, field_name="state")
        _require_uuid(self.accept_operation_id, field_name="accept_operation_id")
        if self.state is E4bConcessionState.ACTIVE:
            if self.withdraw_operation_id is not None:
                _fail("withdraw_operation_id", "concessão ativa não pode ter retirada")
        elif self.withdraw_operation_id is None:
            _fail("withdraw_operation_id", "concessão retirada exige operação de retirada")
        else:
            _require_uuid(self.withdraw_operation_id, field_name="withdraw_operation_id")
            if self.withdraw_operation_id == self.accept_operation_id:
                _fail("withdraw_operation_id", "retirada deve ser uma operação nova")

    @property
    def concession_state(self) -> E4bConcessionState:
        return self.state


@dataclass(frozen=True, slots=True)
class E4bConfirmedOperation:
    """Cadeia confirmada, usada apenas como snapshot para replay/projeção."""

    operation_id: uuid.UUID
    igreja_id: uuid.UUID
    idempotency_key: E4bIdempotencyKey
    correlation_id: uuid.UUID
    fingerprint: E4bFingerprint
    action: E4bAction
    origin: E4bOrigin
    titular_pessoa_id: uuid.UUID
    manifestante_pessoa_id: uuid.UUID
    manifestant_role: E4bManifestantRole
    responsavel_pessoa_id: uuid.UUID | None
    operador_id: uuid.UUID
    finalidade_id: str
    origin_accept_operation_id: uuid.UUID | None
    concession_state: E4bConcessionState
    receipt_id: uuid.UUID
    confirmed_at: dt.datetime
    contract_version: str
    policy_version: str
    term_version: str
    content_digest: str

    def __post_init__(self) -> None:
        _require_uuid(self.operation_id, field_name="operation_id")
        _require_uuid(self.igreja_id, field_name="igreja_id")
        if type(self.idempotency_key) is not E4bIdempotencyKey:
            _fail("idempotency_key", "chave E4b obrigatória")
        if self.idempotency_key.igreja_id != self.igreja_id:
            _fail("igreja_id", "chave e operação pertencem a igrejas diferentes")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        if type(self.fingerprint) is not E4bFingerprint:
            _fail("fingerprint", "fingerprint E4b obrigatório")
        _require_exact_enum(self.action, E4bAction, field_name="action")
        _require_exact_enum(self.origin, E4bOrigin, field_name="origin")
        _require_uuid(self.titular_pessoa_id, field_name="titular_pessoa_id")
        _require_uuid(
            self.manifestante_pessoa_id, field_name="manifestante_pessoa_id"
        )
        _require_exact_enum(
            self.manifestant_role,
            E4bManifestantRole,
            field_name="manifestant_role",
        )
        if self.responsavel_pessoa_id is not None:
            _require_uuid(self.responsavel_pessoa_id, field_name="responsavel_pessoa_id")
        _require_uuid(self.operador_id, field_name="operador_id")
        _require_text(self.finalidade_id, field_name="finalidade_id")
        if self.origin_accept_operation_id is not None:
            _require_uuid(
                self.origin_accept_operation_id,
                field_name="origin_accept_operation_id",
            )
        _require_exact_enum(
            self.concession_state,
            E4bConcessionState,
            field_name="concession_state",
        )
        _require_uuid(self.receipt_id, field_name="receipt_id")
        canonical_confirmed_at = _as_utc(self.confirmed_at, field_name="confirmed_at")
        object.__setattr__(self, "confirmed_at", canonical_confirmed_at)
        _require_version(self.contract_version, field_name="contract_version")
        _require_version(self.policy_version, field_name="policy_version")
        _require_version(self.term_version, field_name="term_version")
        _require_digest(self.content_digest, field_name="content_digest")
        if self.action is E4bAction.ACCEPT:
            if self.origin_accept_operation_id is not None:
                _fail("origin_accept_operation_id", "ACCEPT não referencia origem")
            if self.concession_state is not E4bConcessionState.ACTIVE:
                _fail("concession_state", "ACCEPT confirmado deve ativar concessão")
        else:
            if self.origin_accept_operation_id is None:
                _fail("origin_accept_operation_id", "WITHDRAW exige origem ACCEPT")
            elif self.origin_accept_operation_id == self.operation_id:
                _fail("origin_accept_operation_id", "WITHDRAW não pode ser sua própria origem")
            if self.concession_state is not E4bConcessionState.WITHDRAWN:
                _fail("concession_state", "WITHDRAW confirmado deve retirar concessão")
        if self.manifestant_role is E4bManifestantRole.TITULAR:
            if self.manifestante_pessoa_id != self.titular_pessoa_id:
                _fail("manifestante_pessoa_id", "vínculo titular inconsistente")
            if self.responsavel_pessoa_id is not None:
                _fail("responsavel_pessoa_id", "titular não possui responsável")
        else:
            if self.responsavel_pessoa_id is None:
                _fail("responsavel_pessoa_id", "responsável obrigatório")
            if self.manifestante_pessoa_id != self.responsavel_pessoa_id:
                _fail("manifestante_pessoa_id", "vínculo responsável inconsistente")

    @property
    def receipt(self) -> "E4bReceipt":
        return project_receipt(self)


@dataclass(frozen=True, slots=True)
class E4bClassificationResult:
    """Resultado detalhado sem qualquer efeito colateral."""

    classification: E4bClassification
    reason: E4bDenialReason | None = None
    existing_operation: E4bConfirmedOperation | None = None
    origin_accept_operation_id: uuid.UUID | None = None
    receipt: "E4bReceipt" | None = None
    intent_fingerprint: E4bFingerprint | None = None

    def __post_init__(self) -> None:
        _require_exact_enum(
            self.classification,
            E4bClassification,
            field_name="classification",
        )
        if self.reason is not None:
            _require_exact_enum(self.reason, E4bDenialReason, field_name="reason")
        if self.existing_operation is not None and type(
            self.existing_operation
        ) is not E4bConfirmedOperation:
            _fail("existing_operation", "snapshot E4b obrigatório")
        if self.origin_accept_operation_id is not None:
            _require_uuid(
                self.origin_accept_operation_id,
                field_name="origin_accept_operation_id",
            )
        if self.receipt is not None and type(self.receipt) is not E4bReceipt:
            _fail("receipt", "receipt E4b obrigatório")
        if self.intent_fingerprint is not None and type(
            self.intent_fingerprint
        ) is not E4bFingerprint:
            _fail("intent_fingerprint", "fingerprint E4b obrigatório")
        if self.classification is E4bClassification.REPLAY:
            if self.existing_operation is None or self.receipt is None:
                _fail("receipt", "replay exige operação e receipt confirmados")
        elif self.classification is E4bClassification.ELIGIBLE:
            if self.existing_operation is not None or self.receipt is not None:
                _fail("existing_operation", "elegibilidade não pode confirmar ou reidratar")
            if self.intent_fingerprint is None:
                _fail("intent_fingerprint", "elegibilidade deve estar ligada à intenção")
        elif self.classification is E4bClassification.CONFLICT:
            if self.existing_operation is not None or self.receipt is not None:
                _fail("existing_operation", "conflito não devolve receipt")
        else:
            if self.existing_operation is not None or self.receipt is not None:
                _fail("existing_operation", "negação não devolve receipt")

    @property
    def decision(self) -> E4bClassification:
        return self.classification

    @property
    def eligible_for_staging(self) -> bool:
        return self.classification is E4bClassification.ELIGIBLE

    @property
    def requires_confirmation(self) -> bool:
        return self.eligible_for_staging


def _canonical_intent_payload(intent: E4bConsentIntent) -> dict[str, object]:
    authority = intent.authority
    return {
        "version": E4B_FINGERPRINT_VERSION,
        "igreja_id": str(authority.igreja_id),
        "titular_pessoa_id": str(authority.titular_pessoa_id),
        "finalidade_id": authority.finalidade_id,
        "action": intent.action.value,
        "origin": authority.origin.value,
        "origin_accept_operation_id": (
            str(intent.origin_accept_operation_id)
            if intent.origin_accept_operation_id is not None
            else None
        ),
        "manifestante_pessoa_id": str(authority.manifestante_pessoa_id),
        "manifestant_role": authority.manifestant_role.value,
        "responsavel_pessoa_id": (
            str(authority.responsavel_pessoa_id)
            if authority.responsavel_pessoa_id is not None
            else None
        ),
        "operador_id": str(authority.operador_id),
        "operator_kind": authority.operator_kind.value,
        "correlation_id": str(authority.correlation_id),
        "contract_version": authority.contract_version,
        "policy_version": authority.policy_version,
        "term_version": authority.term_version,
        "content_digest": authority.content_digest,
        "operator_role_links": sorted(role.value for role in authority.operator_role_links),
    }


def compute_e4b_fingerprint(intent: E4bConsentIntent) -> E4bFingerprint:
    """Calcula o digest canônico da intenção, sem incluir a chave idempotente."""

    if type(intent) is not E4bConsentIntent:
        _fail("intent", "intenção E4b obrigatória")
    encoded = json.dumps(
        _canonical_intent_payload(intent),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return E4bFingerprint(hashlib.sha256(encoded).hexdigest())


def fingerprint_matches_intent(intent: E4bConsentIntent) -> bool:
    """Confere se F foi produzido pelos campos fechados da própria intenção."""

    if type(intent) is not E4bConsentIntent:
        return False
    return compute_e4b_fingerprint(intent) == intent.fingerprint


def _denied(reason: E4bDenialReason) -> E4bClassificationResult:
    return E4bClassificationResult(
        classification=E4bClassification.DENIED,
        reason=reason,
    )


def _authority_denial_reason(
    intent: E4bConsentIntent,
) -> E4bDenialReason | None:
    authority = intent.authority
    if intent.legacy_artifact is not None or authority.legacy_artifact is not None:
        # A legacy object is opaque by design: the domain never imports or
        # interprets it, and its presence cannot be used as E4b evidence.
        return E4bDenialReason.LEGACY_ARTIFACT
    if not authority.server_resolved:
        return E4bDenialReason.AUTHORITY_UNRESOLVED
    if not authority.manifestant_relation_valid:
        return E4bDenialReason.MANIFESTANT_RELATION_INVALID
    if intent.idempotency_key.igreja_id != authority.igreja_id:
        return E4bDenialReason.TENANT_MISMATCH
    if authority.origin is not E4bOrigin.E4B:
        return E4bDenialReason.ACTION_ORIGIN_INVALID
    role_ids = {
        E4bRole.TITULAR: authority.titular_pessoa_id,
        E4bRole.MANIFESTANTE: authority.manifestante_pessoa_id,
        E4bRole.RESPONSAVEL: authority.responsavel_pessoa_id,
    }
    for role, role_id in role_ids.items():
        if role_id is not None and role_id == authority.operador_id:
            if role not in authority.operator_role_links:
                return E4bDenialReason.OPERATOR_ROLE_UNRESOLVED
    if not fingerprint_matches_intent(intent):
        return E4bDenialReason.FINGERPRINT_INVALID
    if intent.action is E4bAction.ACCEPT and intent.origin_accept_operation_id is not None:
        return E4bDenialReason.ACTION_ORIGIN_INVALID
    if intent.action is E4bAction.WITHDRAW and intent.origin_accept_operation_id is None:
        return E4bDenialReason.MISSING_ORIGIN
    return None


def _same_stream(
    authority: E4bAuthorityResolution, concession: E4bConcession
) -> bool:
    return (
        authority.igreja_id == concession.igreja_id
        and authority.titular_pessoa_id == concession.titular_pessoa_id
        and authority.finalidade_id == concession.finalidade_id
    )


def _replay_or_conflict(
    intent: E4bConsentIntent,
    existing_operation: E4bConfirmedOperation | None,
) -> E4bClassificationResult | None:
    if existing_operation is None:
        return None
    if type(existing_operation) is not E4bConfirmedOperation:
        return _denied(E4bDenialReason.INVALID_INPUT)
    if existing_operation.igreja_id != intent.authority.igreja_id:
        return _denied(E4bDenialReason.TENANT_MISMATCH)
    if existing_operation.idempotency_key.igreja_id != intent.idempotency_key.igreja_id:
        return _denied(E4bDenialReason.TENANT_MISMATCH)
    if existing_operation.idempotency_key != intent.idempotency_key:
        # The adapter should pass the row for this K only. A snapshot for a
        # different key is not proof of a conflict and cannot affect this K.
        return None
    if existing_operation.fingerprint == intent.fingerprint:
        return E4bClassificationResult(
            classification=E4bClassification.REPLAY,
            existing_operation=existing_operation,
            origin_accept_operation_id=existing_operation.origin_accept_operation_id,
            receipt=project_receipt(existing_operation),
        )
    return E4bClassificationResult(classification=E4bClassification.CONFLICT)


def classify_e4b_intent(
    intent: E4bConsentIntent,
    *,
    existing_operation: E4bConfirmedOperation | None = None,
    concession: E4bConcession | None = None,
    origin_accept_operation: E4bConfirmedOperation | None = None,
) -> E4bClassificationResult:
    """Classifica uma intenção usando somente snapshots E4b já resolvidos.

    A ordem é deliberada: artefato legado e autoridade inválida falham antes
    de qualquer replay/origem/concessão. Um replay exato devolve a operação e
    o receipt históricos mesmo se a concessão atual já estiver WITHDRAWN; ele
    jamais ativa uma concessão novamente.
    """

    if type(intent) is not E4bConsentIntent:
        return _denied(E4bDenialReason.INVALID_INPUT)
    authority = intent.authority
    authority_reason = _authority_denial_reason(intent)
    if authority_reason is not None:
        return _denied(authority_reason)

    replay = _replay_or_conflict(intent, existing_operation)
    if replay is not None:
        return replay

    if concession is not None and type(concession) is not E4bConcession:
        return _denied(E4bDenialReason.INVALID_INPUT)
    if origin_accept_operation is not None and type(
        origin_accept_operation
    ) is not E4bConfirmedOperation:
        return _denied(E4bDenialReason.INVALID_INPUT)

    if intent.action is E4bAction.ACCEPT:
        if concession is not None and _same_stream(authority, concession):
            if concession.state is E4bConcessionState.ACTIVE:
                return _denied(E4bDenialReason.ACTIVE_CONCESSION)
            return _denied(E4bDenialReason.WITHDRAWN_CONCESSION)
        return E4bClassificationResult(
            classification=E4bClassification.ELIGIBLE,
            intent_fingerprint=intent.fingerprint,
        )

    if origin_accept_operation is None:
        return _denied(E4bDenialReason.MISSING_ORIGIN)
    origin = origin_accept_operation
    if origin.action is not E4bAction.ACCEPT:
        return _denied(E4bDenialReason.ORIGIN_NOT_ACCEPT)
    if origin.origin is not E4bOrigin.E4B:
        return _denied(E4bDenialReason.ORIGIN_NOT_ACCEPT)
    if origin.concession_state is not E4bConcessionState.ACTIVE:
        return _denied(E4bDenialReason.ORIGIN_NOT_ACTIVE)
    if origin.receipt_id.int == 0 or origin.confirmed_at is None:
        return _denied(E4bDenialReason.ORIGIN_NOT_CONFIRMED)
    if origin.operation_id != intent.origin_accept_operation_id:
        return _denied(E4bDenialReason.ORIGIN_NOT_ACCEPT)
    if origin.igreja_id != authority.igreja_id:
        return _denied(E4bDenialReason.ORIGIN_TENANT_MISMATCH)
    if origin.titular_pessoa_id != authority.titular_pessoa_id:
        return _denied(E4bDenialReason.ORIGIN_SUBJECT_MISMATCH)
    if origin.finalidade_id != authority.finalidade_id:
        return _denied(E4bDenialReason.ORIGIN_PURPOSE_MISMATCH)
    if concession is None or not _same_stream(authority, concession):
        return _denied(E4bDenialReason.CONCESSION_MISMATCH)
    if concession.state is not E4bConcessionState.ACTIVE:
        return _denied(E4bDenialReason.ORIGIN_NOT_ACTIVE)
    if concession.accept_operation_id != origin.operation_id:
        return _denied(E4bDenialReason.CONCESSION_MISMATCH)
    return E4bClassificationResult(
        classification=E4bClassification.ELIGIBLE,
        origin_accept_operation_id=origin.operation_id,
        intent_fingerprint=intent.fingerprint,
    )


def build_confirmed_operation(
    intent: E4bConsentIntent,
    *,
    classification: E4bClassificationResult,
    operation_id: uuid.UUID,
    receipt_id: uuid.UUID,
    confirmed_at: dt.datetime,
) -> E4bConfirmedOperation:
    """Cria um snapshot confirmado após um resultado ``ELIGIBLE``.

    A função é uma construção pura para testes e para um futuro writer. Ela
    não confirma transação, não persiste e não emite receipt externamente.
    """

    if type(intent) is not E4bConsentIntent:
        _fail("intent", "intenção E4b obrigatória")
    if type(classification) is not E4bClassificationResult:
        _fail("classification", "resultado E4b obrigatório")
    if classification.classification is not E4bClassification.ELIGIBLE:
        _fail("classification", "somente intenção elegível pode ser confirmada")
    if classification.intent_fingerprint != intent.fingerprint:
        _fail("classification", "resultado não pertence à intenção")
    _require_uuid(operation_id, field_name="operation_id")
    _require_uuid(receipt_id, field_name="receipt_id")
    confirmed_at_utc = _as_utc(confirmed_at, field_name="confirmed_at")
    authority = intent.authority
    action = intent.action
    origin_id = (
        classification.origin_accept_operation_id
        if action is E4bAction.WITHDRAW
        else None
    )
    if origin_id != intent.origin_accept_operation_id:
        _fail("origin_accept_operation_id", "resultado e intenção divergem")
    return E4bConfirmedOperation(
        operation_id=operation_id,
        igreja_id=authority.igreja_id,
        idempotency_key=intent.idempotency_key,
        correlation_id=authority.correlation_id,
        fingerprint=intent.fingerprint,
        action=action,
        origin=authority.origin,
        titular_pessoa_id=authority.titular_pessoa_id,
        manifestante_pessoa_id=authority.manifestante_pessoa_id,
        manifestant_role=authority.manifestant_role,
        responsavel_pessoa_id=authority.responsavel_pessoa_id,
        operador_id=authority.operador_id,
        finalidade_id=authority.finalidade_id,
        origin_accept_operation_id=origin_id,
        concession_state=(
            E4bConcessionState.ACTIVE
            if action is E4bAction.ACCEPT
            else E4bConcessionState.WITHDRAWN
        ),
        receipt_id=receipt_id,
        confirmed_at=confirmed_at_utc,
        contract_version=authority.contract_version,
        policy_version=authority.policy_version,
        term_version=authority.term_version,
        content_digest=authority.content_digest,
    )


@dataclass(frozen=True, slots=True)
class E4bReceipt:
    """Receipt minimizado, sem IDs diretos de pessoas ou finalidade."""

    operation_id: uuid.UUID
    correlation_id: uuid.UUID
    receipt_id: uuid.UUID
    igreja_id: uuid.UUID
    action: E4bAction
    concession_state: E4bConcessionState
    origin: E4bOrigin
    manifestant_role: E4bManifestantRole
    confirmed_at: dt.datetime
    contract_version: str
    policy_version: str
    term_version: str
    content_digest: str
    fingerprint: E4bFingerprint

    def __post_init__(self) -> None:
        _require_uuid(self.operation_id, field_name="operation_id")
        _require_uuid(self.correlation_id, field_name="correlation_id")
        _require_uuid(self.receipt_id, field_name="receipt_id")
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_exact_enum(self.action, E4bAction, field_name="action")
        _require_exact_enum(
            self.concession_state,
            E4bConcessionState,
            field_name="concession_state",
        )
        _require_exact_enum(self.origin, E4bOrigin, field_name="origin")
        _require_exact_enum(
            self.manifestant_role,
            E4bManifestantRole,
            field_name="manifestant_role",
        )
        object.__setattr__(
            self,
            "confirmed_at",
            _as_utc(self.confirmed_at, field_name="confirmed_at"),
        )
        _require_version(self.contract_version, field_name="contract_version")
        _require_version(self.policy_version, field_name="policy_version")
        _require_version(self.term_version, field_name="term_version")
        _require_digest(self.content_digest, field_name="content_digest")
        if type(self.fingerprint) is not E4bFingerprint:
            _fail("fingerprint", "fingerprint E4b obrigatório")

    def to_mapping(self) -> dict[str, str]:
        """Serializa apenas a allowlist pública do receipt."""

        return {
            "operation_id": str(self.operation_id),
            "correlation_id": str(self.correlation_id),
            "receipt_id": str(self.receipt_id),
            "igreja_id": str(self.igreja_id),
            "action": self.action.value,
            "concession_state": self.concession_state.value,
            "origin": self.origin.value,
            "manifestant_role": self.manifestant_role.value,
            "confirmed_at": self.confirmed_at.isoformat(),
            "contract_version": self.contract_version,
            "policy_version": self.policy_version,
            "term_version": self.term_version,
            "content_digest": self.content_digest,
            "fingerprint": self.fingerprint.value,
        }

    @property
    def allowlisted_keys(self) -> frozenset[str]:
        return frozenset(self.to_mapping())


def project_receipt(operation: E4bConfirmedOperation) -> E4bReceipt:
    """Projeta exatamente um receipt a partir de uma cadeia confirmada."""

    if type(operation) is not E4bConfirmedOperation:
        _fail("operation", "operação confirmada E4b obrigatória")
    return E4bReceipt(
        operation_id=operation.operation_id,
        correlation_id=operation.correlation_id,
        receipt_id=operation.receipt_id,
        igreja_id=operation.igreja_id,
        action=operation.action,
        concession_state=operation.concession_state,
        origin=operation.origin,
        manifestant_role=operation.manifestant_role,
        confirmed_at=operation.confirmed_at,
        contract_version=operation.contract_version,
        policy_version=operation.policy_version,
        term_version=operation.term_version,
        content_digest=operation.content_digest,
        fingerprint=operation.fingerprint,
    )


@dataclass(frozen=True, slots=True)
class E4bAdminReadRequest:
    """Pedido administrativo com autoridade já resolvida no mesmo tenant."""

    actor_id: uuid.UUID
    requester_igreja_id: uuid.UUID
    record_igreja_id: uuid.UUID
    resolved_admin_igreja_id: uuid.UUID | None
    scope: E4bAdminScope
    resolved_admin_actor_id: uuid.UUID | None = None
    server_resolved: bool = True
    read_scope_granted: bool = True
    presented_credential: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_uuid(self.actor_id, field_name="actor_id")
        _require_uuid(self.requester_igreja_id, field_name="requester_igreja_id")
        _require_uuid(self.record_igreja_id, field_name="record_igreja_id")
        if self.resolved_admin_igreja_id is not None:
            _require_uuid(
                self.resolved_admin_igreja_id,
                field_name="resolved_admin_igreja_id",
            )
        if self.resolved_admin_actor_id is not None:
            _require_uuid(
                self.resolved_admin_actor_id,
                field_name="resolved_admin_actor_id",
            )
        _require_exact_enum(self.scope, E4bAdminScope, field_name="scope")
        _require_bool(self.server_resolved, field_name="server_resolved")
        _require_bool(self.read_scope_granted, field_name="read_scope_granted")


def classify_admin_read(request: E4bAdminReadRequest) -> E4bAccessDecision:
    """Permite leitura/reidentificação somente ao admin server-owned local."""

    if type(request) is not E4bAdminReadRequest:
        return E4bAccessDecision.DENIED
    if request.presented_credential is not None:
        # Receipt, K, C, F e qualquer artefato recebido não são credenciais.
        return E4bAccessDecision.DENIED
    if not request.server_resolved or not request.read_scope_granted:
        return E4bAccessDecision.DENIED
    if request.requester_igreja_id != request.record_igreja_id:
        return E4bAccessDecision.DENIED
    if request.resolved_admin_igreja_id != request.record_igreja_id:
        return E4bAccessDecision.DENIED
    if request.resolved_admin_actor_id != request.actor_id:
        return E4bAccessDecision.DENIED
    return E4bAccessDecision.ALLOWED


def admin_read_allowed(request: E4bAdminReadRequest) -> bool:
    """Atalho booleano explícito para boundaries administrativos."""

    return classify_admin_read(request) is E4bAccessDecision.ALLOWED


def add_calendar_months(value: dt.datetime, months: int) -> dt.datetime:
    """Adiciona meses de calendário, usando o último dia quando necessário."""

    if type(months) is not int:
        _fail("months", "inteiro obrigatório")
    value_utc = _as_utc(value, field_name="value")
    month_index = (value_utc.month - 1) + months
    target_year = value_utc.year + month_index // 12
    target_month = month_index % 12 + 1
    target_day = min(
        value_utc.day,
        calendar.monthrange(target_year, target_month)[1],
    )
    return value_utc.replace(year=target_year, month=target_month, day=target_day)


def calculate_retention_due_at(confirmed_at: dt.datetime) -> dt.datetime:
    """Vencimento inicial em 24 meses de calendário UTC."""

    return add_calendar_months(confirmed_at, E4B_RETENTION_MONTHS)


@dataclass(frozen=True, slots=True)
class E4bRetention:
    """Relógio de retenção efetiva, com holds sobrepostos sem dupla contagem."""

    igreja_id: uuid.UUID
    operation_id: uuid.UUID
    confirmed_at: dt.datetime
    retention_due_at: dt.datetime
    state: E4bRetentionState
    active_hold_ids: tuple[uuid.UUID, ...] = ()
    suspension_started_at: dt.datetime | None = None
    last_event_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.operation_id, field_name="operation_id")
        confirmed = _as_utc(self.confirmed_at, field_name="confirmed_at")
        due = _as_utc(self.retention_due_at, field_name="retention_due_at")
        object.__setattr__(self, "confirmed_at", confirmed)
        object.__setattr__(self, "retention_due_at", due)
        if due < confirmed:
            _fail("retention_due_at", "vencimento anterior à confirmação")
        _require_exact_enum(self.state, E4bRetentionState, field_name="state")
        holds = _uuid_tuple(self.active_hold_ids, field_name="active_hold_ids")
        object.__setattr__(self, "active_hold_ids", holds)
        if self.suspension_started_at is not None:
            suspension = _as_utc(
                self.suspension_started_at,
                field_name="suspension_started_at",
            )
            object.__setattr__(self, "suspension_started_at", suspension)
            if suspension < confirmed:
                _fail("suspension_started_at", "suspensão anterior à confirmação")
        if self.last_event_at is not None:
            last_event = _as_utc(self.last_event_at, field_name="last_event_at")
            object.__setattr__(self, "last_event_at", last_event)
            if last_event < confirmed:
                _fail("last_event_at", "evento anterior à confirmação")
        if holds and self.suspension_started_at is None:
            _fail("suspension_started_at", "hold ativo exige início de suspensão")
        if not holds and self.suspension_started_at is not None:
            _fail("suspension_started_at", "sem hold ativo não há suspensão")
        if self.state is E4bRetentionState.RETENTION_HELD and not holds:
            _fail("state", "estado HELD exige hold ativo")
        if self.state is not E4bRetentionState.RETENTION_HELD and holds:
            _fail("state", "hold ativo exige estado HELD")


def start_retention(
    *, igreja_id: uuid.UUID, operation_id: uuid.UUID, confirmed_at: dt.datetime
) -> E4bRetention:
    """Inicia a retenção no commit lógico de uma operação confirmada."""

    confirmed_utc = _as_utc(confirmed_at, field_name="confirmed_at")
    return E4bRetention(
        igreja_id=igreja_id,
        operation_id=operation_id,
        confirmed_at=confirmed_utc,
        retention_due_at=calculate_retention_due_at(confirmed_utc),
        state=E4bRetentionState.RETENTION_RUNNING,
    )


def retention_state_at(
    retention: E4bRetention, at: dt.datetime
) -> E4bRetentionState:
    """Calcula o estado em um instante fornecido, sem relógio de sistema."""

    if type(retention) is not E4bRetention:
        _fail("retention", "projeção E4b obrigatória")
    at_utc = _as_utc(at, field_name="at")
    if at_utc < retention.confirmed_at:
        _fail("at", "instante anterior à confirmação")
    if retention.active_hold_ids:
        return E4bRetentionState.RETENTION_HELD
    if at_utc >= retention.retention_due_at:
        return E4bRetentionState.RETENTION_ELIGIBLE
    return E4bRetentionState.RETENTION_RUNNING


@dataclass(frozen=True, slots=True)
class E4bHoldEvent:
    """Evento mínimo de hold, sem motivo livre ou conteúdo pastoral."""

    hold_id: uuid.UUID
    igreja_id: uuid.UUID
    operation_id: uuid.UUID
    authority_id: uuid.UUID
    event_type: E4bHoldEventType
    occurred_at: dt.datetime
    policy_version: str
    server_resolved_authority: bool = True
    human_capability_resolved: bool = True

    def __post_init__(self) -> None:
        _require_uuid(self.hold_id, field_name="hold_id")
        _require_uuid(self.igreja_id, field_name="igreja_id")
        _require_uuid(self.operation_id, field_name="operation_id")
        _require_uuid(self.authority_id, field_name="authority_id")
        _require_exact_enum(self.event_type, E4bHoldEventType, field_name="event_type")
        object.__setattr__(
            self,
            "occurred_at",
            _as_utc(self.occurred_at, field_name="occurred_at"),
        )
        _require_version(self.policy_version, field_name="policy_version")
        _require_bool(
            self.server_resolved_authority,
            field_name="server_resolved_authority",
        )
        _require_bool(
            self.human_capability_resolved,
            field_name="human_capability_resolved",
        )


def _validate_hold_event(retention: E4bRetention, event: E4bHoldEvent) -> None:
    if type(retention) is not E4bRetention:
        _fail("retention", "projeção E4b obrigatória")
    if type(event) is not E4bHoldEvent:
        _fail("event", "evento de hold E4b obrigatório")
    if not event.server_resolved_authority or not event.human_capability_resolved:
        _fail("event", "capability humana server-owned não resolvida")
    if event.igreja_id != retention.igreja_id:
        _fail("igreja_id", "hold e retenção pertencem a igrejas diferentes")
    if event.operation_id != retention.operation_id:
        _fail("operation_id", "hold e retenção pertencem a operações diferentes")
    if event.occurred_at < retention.confirmed_at:
        _fail("occurred_at", "hold anterior à confirmação")
    if retention.last_event_at is not None and event.occurred_at < retention.last_event_at:
        _fail("occurred_at", "eventos de hold devem ser monotônicos")


def apply_hold(retention: E4bRetention, event: E4bHoldEvent) -> E4bRetention:
    """Aplica um hold; o primeiro congela o relógio, os seguintes sobrepõem."""

    _validate_hold_event(retention, event)
    if event.event_type is not E4bHoldEventType.HOLD_APPLIED:
        _fail("event_type", "apply_hold exige HOLD_APPLIED")
    if event.hold_id in retention.active_hold_ids:
        _fail("hold_id", "hold já ativo")
    active = retention.active_hold_ids + (event.hold_id,)
    suspension_started_at = (
        retention.suspension_started_at
        if retention.active_hold_ids
        else event.occurred_at
    )
    return replace(
        retention,
        state=E4bRetentionState.RETENTION_HELD,
        active_hold_ids=active,
        suspension_started_at=suspension_started_at,
        last_event_at=event.occurred_at,
    )


def resolve_hold(retention: E4bRetention, event: E4bHoldEvent) -> E4bRetention:
    """Resolve um hold e prolonga o prazo somente ao fechar a sobreposição."""

    _validate_hold_event(retention, event)
    if event.event_type is not E4bHoldEventType.HOLD_RESOLVED:
        _fail("event_type", "resolve_hold exige HOLD_RESOLVED")
    if event.hold_id not in retention.active_hold_ids:
        _fail("hold_id", "hold não está ativo")
    remaining = tuple(
        hold_id for hold_id in retention.active_hold_ids if hold_id != event.hold_id
    )
    if remaining:
        return replace(
            retention,
            state=E4bRetentionState.RETENTION_HELD,
            active_hold_ids=remaining,
            last_event_at=event.occurred_at,
        )
    if retention.suspension_started_at is None:
        _fail("suspension_started_at", "hold ativo sem início de suspensão")
    suspended_for = event.occurred_at - retention.suspension_started_at
    if suspended_for.total_seconds() < 0:
        _fail("occurred_at", "resolução anterior ao início da suspensão")
    due = retention.retention_due_at + suspended_for
    state = (
        E4bRetentionState.RETENTION_ELIGIBLE
        if event.occurred_at >= due
        else E4bRetentionState.RETENTION_RUNNING
    )
    return replace(
        retention,
        state=state,
        retention_due_at=due,
        active_hold_ids=(),
        suspension_started_at=None,
        last_event_at=event.occurred_at,
    )


def classify_person_delete(
    retention: E4bRetention, *, at: dt.datetime
) -> E4bDeleteDecision:
    """Bloqueia delete sob retenção; elegibilidade ainda exige política própria."""

    state = retention_state_at(retention, at)
    if state in (
        E4bRetentionState.RETENTION_RUNNING,
        E4bRetentionState.RETENTION_HELD,
    ):
        return E4bDeleteDecision.DENIED
    return E4bDeleteDecision.DEFERRED


# Nomes de leitura equivalentes deixam a API explícita para boundaries em
# inglês sem introduzir módulos auxiliares ou dependências de runtime.
E4bOperation = E4bConfirmedOperation
E4bResult = E4bClassification
E4bManifestantCategory = E4bManifestantRole
E4bRetentionProjection = E4bRetention


__all__ = (
    "E4B_FINGERPRINT_VERSION",
    "E4B_IDEMPOTENCY_KEY_PREFIX",
    "E4B_RECEIPT_ALLOWLIST",
    "E4B_RETENTION_MONTHS",
    "E4bAccessDecision",
    "E4bAction",
    "E4bAdminReadRequest",
    "E4bAdminScope",
    "E4bAuthorityResolution",
    "E4bClassification",
    "E4bClassificationResult",
    "E4bConfirmedOperation",
    "E4bConcession",
    "E4bConcessionState",
    "E4bConsentIntent",
    "E4bCorrelationId",
    "E4bDeleteDecision",
    "E4bDenialReason",
    "E4bFingerprint",
    "E4bHoldEvent",
    "E4bHoldEventType",
    "E4bHoldId",
    "E4bIdempotencyKey",
    "E4bManifestantCategory",
    "E4bManifestantRole",
    "E4bOperation",
    "E4bOperationId",
    "E4bOperatorKind",
    "E4bOrigin",
    "E4bReceipt",
    "E4bReceiptId",
    "E4bResult",
    "E4bRetention",
    "E4bRetentionProjection",
    "E4bRetentionState",
    "E4bRole",
    "E4bValidationError",
    "add_calendar_months",
    "admin_read_allowed",
    "apply_hold",
    "build_confirmed_operation",
    "calculate_retention_due_at",
    "classify_admin_read",
    "classify_e4b_intent",
    "classify_person_delete",
    "compute_e4b_fingerprint",
    "fingerprint_matches_intent",
    "project_receipt",
    "resolve_hold",
    "retention_state_at",
    "start_retention",
)
