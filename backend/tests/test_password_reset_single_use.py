"""SEC-3B: uso único do token de reset de senha (MEDIO-003).

Cobre o par mint/verify_reset_token do ClerkClient (jti real, ida e volta via
JWT) e os endpoints reais via TestClient: um token válido funciona uma vez,
reuso falha, token expirado falha, token inexistente falha, os três motivos
de rejeição devolvem a MESMA resposta genérica, forgot-password persiste só
(jti, expires_at) — nunca o token em claro — e continua sem revelar se o
e-mail existe.

A corrida de duplo-uso é fechada em produção por `SELECT ... FOR UPDATE` na
claim da linha (ver app/routers/auth.py::reset_password); a suíte offline não
tem um Postgres real pra provar o lock de concorrência entre duas conexões,
então o teste de reuso abaixo prova a mesma invariante por reuso sequencial
(a linha só transiciona de não-usada pra usada uma vez).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.db.models import PasswordResetToken
from app.db.session import get_db
from app.services.brevo import get_brevo_client
from app.services.clerk import ClerkAuthError, ClerkClient, get_clerk_client
from tests.conftest import FakeSession, make_app_user

_SETTINGS = Settings(session_jwt_secret="s" * 40, password_reset_ttl_minutes=30)


def _wire(app, *, session, clerk) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: clerk
    return TestClient(app)


# ---- Unit: ClerkClient.mint_reset_token / verify_reset_token -----------------


def test_mint_and_verify_reset_token_roundtrip() -> None:
    clerk = ClerkClient(settings=_SETTINGS)
    token, jti, expires_at = clerk.mint_reset_token("clerk_user_1")
    uuid.UUID(jti)  # é um UUID válido
    assert expires_at > datetime.now(timezone.utc)
    clerk_user_id, verified_jti = clerk.verify_reset_token(token)
    assert clerk_user_id == "clerk_user_1"
    assert verified_jti == jti


def test_verify_reset_token_rejects_tampered_signature() -> None:
    clerk = ClerkClient(settings=_SETTINGS)
    token, _jti, _exp = clerk.mint_reset_token("clerk_user_1")
    other = ClerkClient(settings=Settings(session_jwt_secret="o" * 40))
    try:
        other.verify_reset_token(token)
        raise AssertionError("deveria ter levantado ClerkAuthError")
    except ClerkAuthError:
        pass


# ---- Endpoint: /auth/reset-password -------------------------------------------


class _ResetClerk:
    """Stub: token de reset sempre válido pro (clerk_user_id, jti) dados."""

    def __init__(
        self,
        clerk_user_id: str = "clerk_user_1",
        jti: str = "11111111-1111-1111-1111-111111111111",
    ) -> None:
        self._clerk_user_id = clerk_user_id
        self._jti = jti
        self.set_password_calls = 0

    def verify_reset_token(self, token: str) -> tuple[str, str]:
        return self._clerk_user_id, self._jti

    def set_user_password(self, clerk_user_id: str, password: str) -> None:
        self.set_password_calls += 1


def _row(*, used_at=None, expires_in_minutes: float = 10):
    return SimpleNamespace(
        used_at=used_at,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    )


def test_valid_token_resets_password_once(app) -> None:
    user = make_app_user()
    row = _row()
    clerk = _ResetClerk()
    client = _wire(app, session=FakeSession(app_user=user, reset_token=row), clerk=clerk)

    resp = client.post(
        "/auth/reset-password", json={"token": "tok", "password": "novaSenha123"}
    )

    assert resp.status_code == 200
    assert row.used_at is not None
    assert clerk.set_password_calls == 1
    assert user.password_changed_at is not None  # integração SEC-3A mantida


def test_second_use_of_same_token_is_rejected(app) -> None:
    """Reuso falha — mesma checagem que o `SELECT ... FOR UPDATE` protege
    contra corrida real de duas requisições simultâneas no Postgres."""
    user = make_app_user()
    row = _row(used_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    clerk = _ResetClerk()
    client = _wire(app, session=FakeSession(app_user=user, reset_token=row), clerk=clerk)

    resp = client.post(
        "/auth/reset-password", json={"token": "tok", "password": "novaSenha123"}
    )

    assert resp.status_code == 400
    assert clerk.set_password_calls == 0


def test_expired_token_is_rejected(app) -> None:
    user = make_app_user()
    row = _row(expires_in_minutes=-1)
    clerk = _ResetClerk()
    client = _wire(app, session=FakeSession(app_user=user, reset_token=row), clerk=clerk)

    resp = client.post(
        "/auth/reset-password", json={"token": "tok", "password": "novaSenha123"}
    )

    assert resp.status_code == 400
    assert clerk.set_password_calls == 0


def test_nonexistent_token_row_is_rejected(app) -> None:
    user = make_app_user()
    clerk = _ResetClerk()
    client = _wire(app, session=FakeSession(app_user=user, reset_token=None), clerk=clerk)

    resp = client.post(
        "/auth/reset-password", json={"token": "tok", "password": "novaSenha123"}
    )

    assert resp.status_code == 400
    assert clerk.set_password_calls == 0


def test_all_rejection_reasons_return_identical_generic_response(app) -> None:
    """Reuso, expirado e inexistente devolvem o MESMO corpo/status — não dá
    pra distinguir o motivo de fora (defesa em profundidade, estilo US-01)."""
    user = make_app_user()
    scenarios = [
        _row(used_at=datetime.now(timezone.utc)),
        _row(expires_in_minutes=-1),
        None,
    ]
    bodies = []
    for reset_token in scenarios:
        client = _wire(
            app,
            session=FakeSession(app_user=user, reset_token=reset_token),
            clerk=_ResetClerk(),
        )
        resp = client.post(
            "/auth/reset-password", json={"token": "tok", "password": "novaSenha123"}
        )
        assert resp.status_code == 400
        bodies.append(resp.json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_invalid_jwt_signature_is_also_generic_400(app) -> None:
    """Assinatura inválida (verify_reset_token levanta) cai no mesmo 400."""

    class _RaisingClerk:
        def verify_reset_token(self, token: str) -> tuple[str, str]:
            raise ClerkAuthError("bad signature")

    user = make_app_user()
    client = _wire(app, session=FakeSession(app_user=user), clerk=_RaisingClerk())

    resp = client.post(
        "/auth/reset-password", json={"token": "tok", "password": "novaSenha123"}
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "Link inválido ou expirado. Peça um novo."


# ---- Endpoint: /auth/forgot-password persiste (jti, expires_at) --------------


class _RecordingSession:
    """Local double: só grava o que foi adicionado (persist do token)."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        pass

    def close(self) -> None:  # pragma: no cover
        pass


class _RecordingMailer:
    def __init__(self) -> None:
        self.links: list[str] = []

    def send_password_reset(self, *, to_email: str, reset_link: str) -> None:
        self.links.append(reset_link)


class _KnownEmailClerk:
    def __init__(self, clerk_user_id: str = "clerk_user_1") -> None:
        self._clerk_user_id = clerk_user_id

    def find_user_id_by_email(self, email: str) -> str | None:
        return self._clerk_user_id

    def mint_reset_token(self, clerk_user_id: str) -> tuple[str, str, datetime]:
        jti = "22222222-2222-2222-2222-222222222222"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        return f"token-for-{clerk_user_id}", jti, expires_at


class _UnknownEmailClerk:
    def find_user_id_by_email(self, email: str) -> str | None:
        return None


def test_forgot_password_persists_jti_and_expiry_not_the_raw_token(app) -> None:
    session = _RecordingSession()
    mailer = _RecordingMailer()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: _KnownEmailClerk()
    app.dependency_overrides[get_brevo_client] = lambda: mailer
    client = TestClient(app)

    resp = client.post("/auth/forgot-password", json={"email": "pastor@igreja.com"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, PasswordResetToken)
    assert str(row.jti) == "22222222-2222-2222-2222-222222222222"
    assert row.clerk_user_id == "clerk_user_1"
    assert row.expires_at > datetime.now(timezone.utc)
    assert not hasattr(row, "token")  # nunca o token em claro persistido
    assert mailer.links and "token-for-clerk_user_1" in mailer.links[0]


def test_forgot_password_same_response_regardless_of_email_existing(app) -> None:
    known_session = _RecordingSession()
    app.dependency_overrides[get_db] = lambda: known_session
    app.dependency_overrides[get_clerk_client] = lambda: _KnownEmailClerk()
    app.dependency_overrides[get_brevo_client] = lambda: _RecordingMailer()
    client = TestClient(app)
    known_resp = client.post(
        "/auth/forgot-password", json={"email": "existe@igreja.com"}
    )

    unknown_session = _RecordingSession()
    app.dependency_overrides[get_db] = lambda: unknown_session
    app.dependency_overrides[get_clerk_client] = lambda: _UnknownEmailClerk()
    unknown_resp = client.post(
        "/auth/forgot-password", json={"email": "nao-existe@igreja.com"}
    )

    assert known_resp.status_code == unknown_resp.status_code == 200
    assert known_resp.json() == unknown_resp.json() == {"status": "ok"}
    assert len(known_session.added) == 1
    assert len(unknown_session.added) == 0
