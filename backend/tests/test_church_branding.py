"""Missão 4 PR1 — branding da igreja (logo + fallback nome), backend-only.

Harness offline (FakeSession-style, como test_agenda_recipients_evt7_pr2):
roteia a auth (AppUser/UserRole) e o select de Igreja por entidade, sem DB real,
com um FakeStorage no lugar do Supabase Storage. Cobre o contrato HTTP novo:

  - GET    /igreja/branding   nome + logoUrl (admin); 403 p/ não-admin;
  - PUT    /igreja/logo       upload válido PNG/JPG/WebP; 400 SVG / >1MB /
                              base64 inválido / mime falsificado (magic bytes);
                              path SEMPRE derivado do igreja_id do token;
                              502 quando o Storage falha; 403 não-admin;
  - DELETE /igreja/logo       remove (idempotente); 403 não-admin;
  - GET    /auth/me           expõe igrejaNome + igrejaLogoUrl (aditivo).

Também verifica que a migration espelha policy/grant (RLS de igrejas era
SELECT-only — sem a policy nova o UPDATE seria no-op silencioso).
"""

from __future__ import annotations

import base64
import pathlib
import uuid
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.db.models import AppUser, Igreja
from app.db.session import get_db
from app.services.clerk import get_clerk_client
from app.services.storage import MAX_LOGO_BYTES, StorageError, get_storage
from tests.conftest import FakeClerk, make_app_user

_AUTH = {"Authorization": "Bearer good"}
_IGREJA = "00000000-0000-0000-0000-000000000001"

# Menores payloads que passam nos sniffers de magic bytes.
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 16
_WEBP = b"RIFF" + b"\x10\x00\x00\x00" + b"WEBP" + b"\x00" * 8


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


class _R:
    def __init__(self, *, scalar=None, scalars=None) -> None:
        self._scalar = scalar
        self._scalars = scalars or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._scalars))


class BrandingSession:
    """Roteia auth (AppUser/UserRole) + o select da própria Igreja.

    Captura os params compilados do select de Igreja para provar que o WHERE
    usa o igreja_id do TOKEN (isolamento entre tenants é a query, não o body).
    """

    def __init__(self, *, app_user, roles, igreja=None, fail_commit=False) -> None:
        self.app_user = app_user
        self.roles = roles
        self.igreja = igreja
        self.committed = False
        self.igreja_where_params: dict | None = None
        self._fail_commit = fail_commit

    def execute(self, statement, params=None) -> _R:
        descs = list(getattr(statement, "column_descriptions", []) or [])
        ent = descs[0].get("entity") if descs else None
        if ent is AppUser:
            return _R(scalar=self.app_user)
        if ent is Igreja:
            self.igreja_where_params = dict(statement.compile().params)
            return _R(scalar=self.igreja)
        return _R(scalars=self.roles)

    def commit(self) -> None:
        if self._fail_commit:
            # Simula o que a RLS faz se a migration NÃO tiver sido aplicada:
            # o UPDATE casa 0 linhas → StaleDataError no flush.
            from sqlalchemy.orm.exc import StaleDataError

            raise StaleDataError("expected to update 1 row(s); 0 were matched")
        self.committed = True

    def close(self) -> None:  # pragma: no cover
        pass


class FakeStorage:
    """Grava chamadas de upload/remove; opcionalmente falha o upload."""

    def __init__(self, *, fail_upload: bool = False) -> None:
        self._fail_upload = fail_upload
        self.uploads: list[tuple[str, bytes, str]] = []
        self.removed: list[list[str]] = []

    def upload_logo(self, path: str, data: bytes, content_type: str) -> None:
        if self._fail_upload:
            raise StorageError("boom")
        self.uploads.append((path, data, content_type))

    def remove_logo(self, paths: list[str]) -> None:
        self.removed.append(list(paths))


def _igreja(*, nome="Igreja Piloto", logo_path=None):
    return SimpleNamespace(id=_IGREJA, nome=nome, logo_path=logo_path)


def _wire(app, *, session, storage=None) -> TestClient:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_clerk_client] = lambda: FakeClerk()
    app.dependency_overrides[get_storage] = lambda: storage or FakeStorage()
    return TestClient(app)


def _session(*, roles, igreja=None, app_user=None, fail_commit=False) -> BrandingSession:
    return BrandingSession(
        app_user=app_user or make_app_user(),
        roles=roles,
        igreja=igreja,
        fail_commit=fail_commit,
    )


def _set_supabase_url(monkeypatch, url="https://supa.example.co") -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "supabase_url", url, raising=False)


# ---- GET /igreja/branding ---------------------------------------------------
def test_get_branding_without_logo_returns_nome_and_null_url(app) -> None:
    session = _session(roles=["admin"], igreja=_igreja())
    resp = _wire(app, session=session).get("/igreja/branding", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json() == {"nome": "Igreja Piloto", "logoUrl": None}


def test_get_branding_with_logo_builds_public_url(app, monkeypatch) -> None:
    _set_supabase_url(monkeypatch)
    session = _session(
        roles=["admin"], igreja=_igreja(logo_path=f"{_IGREJA}/logo-abc123.png")
    )
    resp = _wire(app, session=session).get("/igreja/branding", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["logoUrl"] == (
        f"https://supa.example.co/storage/v1/object/public/church-logos/{_IGREJA}/logo-abc123.png"
    )


def test_get_branding_blocks_non_admin(app) -> None:
    session = _session(roles=["pastor"], igreja=_igreja())
    resp = _wire(app, session=session).get("/igreja/branding", headers=_AUTH)
    assert resp.status_code == 403


# ---- PUT /igreja/logo — uploads válidos -------------------------------------
def test_upload_png_persists_and_path_is_tenant_scoped(app, monkeypatch) -> None:
    _set_supabase_url(monkeypatch)
    igreja = _igreja()
    session = _session(roles=["admin"], igreja=igreja)
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_PNG)},
    )
    assert resp.status_code == 200
    # Path derivado do igreja_id do TOKEN (nunca do payload).
    path, data, mime = storage.uploads[0]
    assert path.startswith(f"{_IGREJA}/logo-")
    assert path.endswith(".png")
    assert data == _PNG
    assert mime == "image/png"
    # Persistiu o ponteiro e commitou.
    assert igreja.logo_path == path
    assert session.committed is True
    # O WHERE do select da igreja usa o igreja_id do token.
    assert uuid.UUID(_IGREJA) in session.igreja_where_params.values()
    assert resp.json()["logoUrl"].endswith(path)


def test_upload_webp_and_jpeg_accepted(app) -> None:
    for mime, blob, ext in (
        ("image/webp", _WEBP, ".webp"),
        ("image/jpeg", _JPG, ".jpg"),
        ("image/jpg", _JPG, ".jpg"),  # alias comum de navegador
    ):
        igreja = _igreja()
        session = _session(roles=["admin"], igreja=igreja)
        storage = FakeStorage()
        resp = _wire(app, session=session, storage=storage).put(
            "/igreja/logo", headers=_AUTH, json={"mime": mime, "base64": _b64(blob)}
        )
        assert resp.status_code == 200, mime
        assert igreja.logo_path.endswith(ext)


def test_upload_replaces_old_logo_and_removes_old_object(app) -> None:
    old_path = f"{_IGREJA}/logo-old00000.png"
    igreja = _igreja(logo_path=old_path)
    session = _session(roles=["admin"], igreja=igreja)
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_PNG)},
    )
    assert resp.status_code == 200
    assert igreja.logo_path != old_path  # sufixo rotativo = cache-busting
    assert [old_path] in storage.removed  # objeto antigo limpo (best-effort)


# ---- PUT /igreja/logo — rejeições -------------------------------------------
def test_upload_rejects_svg(app) -> None:
    session = _session(roles=["admin"], igreja=_igreja())
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/svg+xml", "base64": _b64(b"<svg></svg>")},
    )
    assert resp.status_code == 400
    assert storage.uploads == []  # nada tocou o Storage


def test_upload_rejects_oversize(app) -> None:
    big = _PNG + b"\x00" * MAX_LOGO_BYTES  # > 1 MB com header PNG válido
    session = _session(roles=["admin"], igreja=_igreja())
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(big)},
    )
    assert resp.status_code == 400
    assert "1 MB" in resp.json()["detail"]
    assert storage.uploads == []


def test_upload_rejects_invalid_base64(app) -> None:
    session = _session(roles=["admin"], igreja=_igreja())
    resp = _wire(app, session=session).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": "not-base64!!!"},
    )
    assert resp.status_code == 400


def test_upload_rejects_mime_that_does_not_match_magic_bytes(app) -> None:
    # Declara PNG mas o conteúdo é JPEG → magic bytes mandam.
    session = _session(roles=["admin"], igreja=_igreja())
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_JPG)},
    )
    assert resp.status_code == 400
    assert storage.uploads == []


def test_upload_rejects_non_image_bytes(app) -> None:
    session = _session(roles=["admin"], igreja=_igreja())
    resp = _wire(app, session=session).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(b"GIF89a not allowed")},
    )
    assert resp.status_code == 400


def test_upload_storage_failure_returns_502_and_nothing_persists(app) -> None:
    igreja = _igreja()
    session = _session(roles=["admin"], igreja=igreja)
    resp = _wire(app, session=session, storage=FakeStorage(fail_upload=True)).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_PNG)},
    )
    assert resp.status_code == 502
    assert igreja.logo_path is None
    assert session.committed is False


def test_upload_commit_failure_returns_500_and_cleans_orphan_object(app) -> None:
    """Se o commit falha (ex.: migration não aplicada → StaleDataError), o
    objeto recém-enviado é removido (sem órfão) e a resposta é 500 amigável."""
    igreja = _igreja()
    session = _session(roles=["admin"], igreja=igreja, fail_commit=True)
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_PNG)},
    )
    assert resp.status_code == 500
    assert "Tente novamente" in resp.json()["detail"]
    # O objeto enviado foi limpo (compensação), não fica órfão no bucket.
    uploaded_path = storage.uploads[0][0]
    assert [uploaded_path] in storage.removed


def test_upload_blocks_non_admin(app) -> None:
    session = _session(roles=["pastor", "lider_celula"], igreja=_igreja())
    resp = _wire(app, session=session).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_PNG)},
    )
    assert resp.status_code == 403


def test_upload_path_follows_token_church_not_payload(app) -> None:
    """Admin da igreja B: tudo (WHERE + path no bucket) sai do TOKEN dele.

    Não existe igreja_id no body — o contrato nem permite mirar outra igreja; o
    teste prova que o path e a query seguem o tenant autenticado.
    """
    other_igreja_id = "00000000-0000-0000-0000-000000000002"
    app_user_b = make_app_user()
    app_user_b.igreja_id = other_igreja_id
    app_user_b.igreja.id = other_igreja_id
    igreja_b = SimpleNamespace(id=other_igreja_id, nome="Igreja B", logo_path=None)
    session = _session(roles=["admin"], igreja=igreja_b, app_user=app_user_b)
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).put(
        "/igreja/logo",
        headers=_AUTH,
        json={"mime": "image/png", "base64": _b64(_PNG)},
    )
    assert resp.status_code == 200
    path, _, _ = storage.uploads[0]
    assert path.startswith(f"{other_igreja_id}/")
    assert not path.startswith(f"{_IGREJA}/")
    assert uuid.UUID(other_igreja_id) in session.igreja_where_params.values()


# ---- DELETE /igreja/logo -----------------------------------------------------
def test_delete_logo_clears_pointer_and_removes_object(app) -> None:
    old_path = f"{_IGREJA}/logo-old00000.png"
    igreja = _igreja(logo_path=old_path)
    session = _session(roles=["admin"], igreja=igreja)
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).delete(
        "/igreja/logo", headers=_AUTH
    )
    assert resp.status_code == 200
    assert resp.json() == {"nome": "Igreja Piloto", "logoUrl": None}
    assert igreja.logo_path is None
    assert session.committed is True
    assert [old_path] in storage.removed


def test_delete_logo_is_idempotent_without_logo(app) -> None:
    igreja = _igreja(logo_path=None)
    session = _session(roles=["admin"], igreja=igreja)
    storage = FakeStorage()
    resp = _wire(app, session=session, storage=storage).delete(
        "/igreja/logo", headers=_AUTH
    )
    assert resp.status_code == 200
    assert storage.removed == []
    assert session.committed is False  # nada a persistir


def test_delete_blocks_non_admin(app) -> None:
    session = _session(roles=["membro"], igreja=_igreja())
    resp = _wire(app, session=session).delete("/igreja/logo", headers=_AUTH)
    assert resp.status_code == 403


# ---- GET /auth/me — branding aditivo -----------------------------------------
def test_me_exposes_igreja_nome_and_null_logo(app) -> None:
    session = _session(roles=["admin"], igreja=_igreja())
    resp = _wire(app, session=session).get("/auth/me", headers=_AUTH)
    assert resp.status_code == 200
    body = resp.json()
    assert body["igrejaNome"] == "Igreja Piloto"
    assert body["igrejaLogoUrl"] is None


def test_me_exposes_logo_url_when_set(app, monkeypatch) -> None:
    _set_supabase_url(monkeypatch)
    user = make_app_user()
    user.igreja.logo_path = f"{_IGREJA}/logo-abc123.png"
    session = _session(roles=["membro"], igreja=None, app_user=user)
    resp = _wire(app, session=session).get("/auth/me", headers=_AUTH)
    assert resp.status_code == 200
    assert resp.json()["igrejaLogoUrl"].endswith(
        f"/storage/v1/object/public/church-logos/{_IGREJA}/logo-abc123.png"
    )


def test_patch_me_also_returns_branding(app) -> None:
    """PATCH /auth/me também devolve igrejaNome (o shell pode re-hidratar dele)."""
    session = _session(roles=["admin"], igreja=None)
    resp = _wire(app, session=session).patch(
        "/auth/me", headers=_AUTH, json={"chatNome": "Pr. Piloto"}
    )
    assert resp.status_code == 200
    assert resp.json()["igrejaNome"] == "Igreja Piloto"


# ---- Migration espelha o contrato ---------------------------------------------
def test_migration_has_column_policy_and_column_grant() -> None:
    """Sem policy+grant o UPDATE do tenant é no-op silencioso (RLS SELECT-only)."""
    path = (
        pathlib.Path(__file__).resolve().parents[1]
        / "migrations"
        / "20260707_011455_igreja_logo_branding.sql"
    )
    sql = path.read_text(encoding="utf-8").lower()
    assert "add column if not exists logo_path" in sql
    assert "create policy igrejas_self_update on igrejas" in sql
    assert "using (id = current_igreja_id())" in sql
    assert "with check (id = current_igreja_id())" in sql
    assert "revoke update on igrejas from authenticated" in sql
    assert "grant update (logo_path) on igrejas to authenticated" in sql
    # O revoke table-wide senão quebraria o trigger de auto-upgrade de plano
    # (roda como authenticated); por isso é elevado a SECURITY DEFINER.
    assert "alter function public.fn_subscription_autoupgrade() security definer" in sql
