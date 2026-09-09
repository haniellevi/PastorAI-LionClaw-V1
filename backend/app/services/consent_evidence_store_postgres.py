"""Internal laboratory persistence adapter. No connection factory or caller.

Borrows an existing scoped transaction. Never commits, rolls back, changes
role/GUC, sends, or writes the purpose ledger. DTO rows are storage facts,
not authentication or operational authorization.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import fields, replace
from enum import Enum
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.rls_observability import require_tenant_scope
from app.domain.consent_evidence_store import (
    ConsentChallenge,
    ConsentChallengeState,
    ConsentEvidenceAction,
    ConsentEvidenceChannel,
    ConsentEvidenceLanguage,
    ConsentEvidenceLedgerState,
    ConsentEvidencePurpose,
    ConsentEvidenceRecord,
    ConsentEvidenceSchemaVersion,
    ConsentEvidenceType,
    ConsentReceipt,
    OpaqueConsentEvidenceIdempotencyKey,
)


def _parameters(row):
    # Reconstruct to validate even a tampered frozen DTO before persistence.
    validated = replace(row)
    return {
        item.name: (
            value.value if isinstance(value := getattr(validated, item.name), Enum)
            else value
        )
        for item in fields(validated)
    }


def _challenge(row) -> ConsentChallenge | None:
    if row is None:
        return None
    values = dict(row)
    values['finalidade'] = ConsentEvidencePurpose(values['finalidade'])
    values['canal'] = ConsentEvidenceChannel(values['canal'])
    values['idioma'] = ConsentEvidenceLanguage(values['idioma'])
    values['estado'] = ConsentChallengeState(values['estado'])
    return ConsentChallenge(**values)


def _evidence(row) -> ConsentEvidenceRecord | None:
    if row is None:
        return None
    values = dict(row)
    values['tipo'] = ConsentEvidenceType(values['tipo'])
    values['acao'] = None if values['acao'] is None else ConsentEvidenceAction(values['acao'])
    return ConsentEvidenceRecord(**values)


def _receipt(row) -> ConsentReceipt | None:
    if row is None:
        return None
    values = dict(row)
    values['acao'] = ConsentEvidenceAction(values['acao'])
    values['schema_version'] = ConsentEvidenceSchemaVersion(values['schema_version'])
    return ConsentReceipt(**values)


class PostgresConsentEvidenceStore:
    """SQLAlchemy adapter; source/RBAC authority remains an independent seam."""

    def __init__(self, session: Session):
        self.session = session

    def transaction_active(self) -> bool:
        return bool(self.session.in_transaction())

    def require_tenant_scope(self, igreja_id: uuid.UUID) -> None:
        require_tenant_scope(
            self.session, expected_igreja_id=igreja_id,
            source="consent_evidence_lab",
        )

    def require_readonly_observation(self) -> None:
        if not self.transaction_active():
            raise RuntimeError("observation transaction required")
        value = self.session.execute(text("show transaction_read_only")).scalar_one()
        if value != "on":
            raise RuntimeError("independent readonly observation required")
        # A transaction that staged persistent rows has an assigned xid even
        # if its caller subsequently changes the transaction to READ ONLY.
        # Reject it: observation must not see its own uncommitted evidence.
        assigned = self.session.execute(text(
            "select pg_catalog.pg_current_xact_id_if_assigned() is not null"
        )).scalar_one()
        if assigned:
            raise RuntimeError("observation cannot reuse a writing transaction")

    def lock_idempotency_key(
        self, igreja_id: uuid.UUID, chave_idempotencia: OpaqueConsentEvidenceIdempotencyKey,
    ) -> None:
        if (type(chave_idempotencia) is not OpaqueConsentEvidenceIdempotencyKey
                or not chave_idempotencia._was_server_minted_in_this_process()):
            raise ValueError("server-issued request key required")
        transaction = self.session.get_transaction()
        if transaction is None:
            raise RuntimeError("external transaction required")
        isolation = self.session.execute(text("show transaction_isolation")).scalar_one()
        if isolation != "read committed":
            raise RuntimeError("read committed required for post-lock revalidation")
        key = f"purpose-consent-idempotency:{igreja_id}:{chave_idempotencia.value}"
        prior = self.session.info.get("consent_evidence_lab_lock_scope")
        if prior is not None and prior[0] is transaction:
            if prior[1] != key:
                raise RuntimeError("one idempotency key per transaction required")
        else:
            self.session.info["consent_evidence_lab_lock_scope"] = [transaction, key, None]
        self.session.execute(
            text("select pg_catalog.pg_advisory_xact_lock("
                 "pg_catalog.hashtextextended(:key, 0))"),
            {"key": key},
        )

    def lock_ledger_stream(
        self, igreja_id: uuid.UUID, pessoa_id: uuid.UUID,
        finalidade: ConsentEvidencePurpose,
    ) -> None:
        # Exact identity of the historical ledger's prepare_insert trigger.
        # The caller must first secure the new challenge's FK or lock the
        # existing challenge. No Pessoa row lock may be acquired after this.
        stream = f"{igreja_id}:{pessoa_id}:{finalidade.value}"
        scope = self.session.info.get("consent_evidence_lab_lock_scope")
        if scope is None or scope[0] is not self.session.get_transaction():
            raise RuntimeError("idempotency lock required before stream")
        if scope[2] is not None and scope[2] != stream:
            raise RuntimeError("one consent stream per transaction required")
        scope[2] = stream
        self.session.execute(
            text("select pg_catalog.pg_advisory_xact_lock("
                 "pg_catalog.hashtextextended(:stream, 0))"),
            {"stream": stream},
        )

    def lock_challenge(self, igreja_id: uuid.UUID, desafio_id: uuid.UUID) -> None:
        self.session.execute(
            text("select id from public.consentimento_desafio "
                 "where igreja_id=:tenant and id=:id for update"),
            {"tenant": igreja_id, "id": desafio_id},
        ).scalar_one_or_none()

    def get_challenge(self, igreja_id, desafio_id):
        return _challenge(self.session.execute(
            text("select * from public.consentimento_desafio where igreja_id=:tenant and id=:id"),
            {"tenant": igreja_id, "id": desafio_id},
        ).mappings().one_or_none())

    def get_challenge_by_binding_interaction(self, igreja_id, binding_id, interaction_id):
        return _challenge(self.session.execute(
            text("select * from public.consentimento_desafio where igreja_id=:tenant "
                 "and binding_id=:binding and interaction_id=:interaction"),
            {"tenant": igreja_id, "binding": binding_id, "interaction": interaction_id},
        ).mappings().one_or_none())

    def get_evidence_by_idempotency(self, igreja_id, chave_idempotencia):
        # Reads may use a persisted key from the independently authenticated
        # source after restart. It is not rehydrated as a minted request key.
        from app.domain.consent_evidence_store import require_persisted_idempotency_key
        key = (chave_idempotencia.value
               if type(chave_idempotencia) is OpaqueConsentEvidenceIdempotencyKey
               else chave_idempotencia)
        require_persisted_idempotency_key(key)
        return _evidence(self.session.execute(
            text("select * from public.consentimento_evidencia "
                 "where igreja_id=:tenant and chave_idempotencia=:key"),
            {"tenant": igreja_id, "key": key},
        ).mappings().one_or_none())

    def get_evidence_by_challenge_type(self, igreja_id, desafio_id, tipo):
        return _evidence(self.session.execute(
            text("select * from public.consentimento_evidencia "
                 "where igreja_id=:tenant and desafio_id=:id and tipo=:type"),
            {"tenant": igreja_id, "id": desafio_id, "type": tipo.value},
        ).mappings().one_or_none())

    def get_receipt_by_evidence(self, igreja_id, evidencia_id):
        return _receipt(self.session.execute(
            text("select * from public.consentimento_recibo "
                 "where igreja_id=:tenant and evidencia_id=:id"),
            {"tenant": igreja_id, "id": evidencia_id},
        ).mappings().one_or_none())

    def get_ledger_state(self, igreja_id, pessoa_id, finalidade):
        row = self.session.execute(
            text("select id, estado from public.consentimento_finalidade_evento "
                 "where igreja_id=:tenant and pessoa_id=:person and finalidade=:purpose "
                 "order by sequencia desc limit 1"),
            {"tenant": igreja_id, "person": pessoa_id, "purpose": finalidade.value},
        ).mappings().one_or_none()
        if row is None:
            return ConsentEvidenceLedgerState.ABSENT, None
        states = {"concedido": ConsentEvidenceLedgerState.GRANTED,
                  "retirado": ConsentEvidenceLedgerState.WITHDRAWN}
        return states[row["estado"]], row["id"]

    def insert_challenge(self, challenge: ConsentChallenge) -> bool:
        if type(challenge) is not ConsentChallenge:
            raise ValueError("closed challenge required")
        parameters = _parameters(challenge)
        columns = ", ".join(parameters)
        binds = ", ".join(":" + key for key in parameters)
        created = self.session.execute(text(
            f"insert into public.consentimento_desafio ({columns}) values ({binds}) "
            "on conflict do nothing returning id"
        ), parameters).scalar_one_or_none()
        # A conflicting winner must be read/locked by the service BEFORE
        # taking the stream lock. Do not adopt another challenge identity.
        return created is not None

    def insert_evidence(self, evidence: ConsentEvidenceRecord) -> None:
        if type(evidence) is not ConsentEvidenceRecord:
            raise ValueError("closed evidence required")
        self._insert("consentimento_evidencia", _parameters(evidence))

    def insert_receipt(self, receipt: ConsentReceipt) -> None:
        if type(receipt) is not ConsentReceipt:
            raise ValueError("closed receipt required")
        self._insert("consentimento_recibo", _parameters(receipt))

    def _insert(self, table, parameters):
        # Names originate exclusively in the closed dataclasses above, never
        # in a request dict. Values remain SQL parameters.
        schemas = {
            "consentimento_desafio": ConsentChallenge,
            "consentimento_evidencia": ConsentEvidenceRecord,
            "consentimento_recibo": ConsentReceipt,
        }
        if table not in schemas or set(parameters) != {item.name for item in fields(schemas[table])}:
            raise ValueError("closed insert shape required")
        columns = ", ".join(parameters)
        binds = ", ".join(":" + key for key in parameters)
        self.session.execute(text(f"insert into public.{table} ({columns}) values ({binds})"), parameters)

    def transition_challenge(self, igreja_id, desafio_id, state, ended_at: dt.datetime):
        result = self.session.execute(
            text("update public.consentimento_desafio "
                 "set estado=:state, encerrado_em=:ended "
                 "where igreja_id=:tenant and id=:id and estado='OPEN'"),
            {"tenant": igreja_id, "id": desafio_id, "state": state.value, "ended": ended_at},
        )
        if result.rowcount != 1:
            raise ValueError("challenge transition conflict")

    def flush(self) -> None:
        self.session.flush()
