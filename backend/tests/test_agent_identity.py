"""Focused RED/GREEN contracts for S3 local identity confirmation."""

from __future__ import annotations

import datetime as dt
import uuid

from app.db.models import AgentIdentityChallenge, AgentIdentityProof
from app.services.agent_identity import (
    ConfirmedIdentityContext,
    ProofIntegrityInput,
    build_credential_fingerprint,
    build_proof_integrity_hmac,
    build_roles_fingerprint,
    verify_proof_integrity_hmac,
)


def test_identity_proof_hmac_binds_tenant_actor_conversation_and_role_snapshot() -> None:
    now = dt.datetime(2026, 9, 27, 12, tzinfo=dt.timezone.utc)
    secret = "s3-synthetic-secret"
    role_id = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
    value = ProofIntegrityInput(
        challenge_id=uuid.UUID("00000000-0000-0000-0000-0000000000d1"),
        igreja_id=uuid.UUID("00000000-0000-0000-0000-0000000000a1"),
        app_user_id=uuid.UUID("00000000-0000-0000-0000-0000000000b1"),
        pessoa_id=uuid.UUID("00000000-0000-0000-0000-0000000000f1"),
        conversation_id=uuid.UUID("00000000-0000-0000-0000-0000000000c1"),
        confirmed_at=now,
        confirmed_until=now + dt.timedelta(minutes=15),
        credential_fingerprint=build_credential_fingerprint(
            secret, clerk_user_id="clerk_synthetic", password_changed_at=None
        ),
        roles_fingerprint=build_roles_fingerprint(secret, roles=((role_id, "pastor"),)),
    )
    integrity = build_proof_integrity_hmac(secret, value)

    assert verify_proof_integrity_hmac(secret, value, integrity)
    assert not verify_proof_integrity_hmac(
        secret,
        ProofIntegrityInput(
            **{**value.__dict__, "conversation_id": uuid.uuid4()}
        ),
        integrity,
    )


def test_identity_models_keep_tenant_scoped_challenge_and_immutable_proof_links() -> None:
    challenge_constraints = {
        constraint.name for constraint in AgentIdentityChallenge.__table__.constraints
    }
    proof_constraints = {
        constraint.name for constraint in AgentIdentityProof.__table__.constraints
    }

    assert "agent_identity_challenges_tenant_conversation_fkey" in challenge_constraints
    assert "agent_identity_challenges_inbound_once_key" in challenge_constraints
    assert "agent_identity_proofs_tenant_challenge_fkey" in proof_constraints
    assert "agent_identity_proofs_challenge_once_key" in proof_constraints
    assert "proof_id" in ConfirmedIdentityContext.__dataclass_fields__
