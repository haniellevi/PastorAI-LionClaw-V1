"""Console Master: status da triagem Jev e teste com mensagem sintética."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from app.db.models import PlatformAuditLog
from app.config import get_settings
from app.routers import platform_jev
from app.services import semantic_triage as jev_triage
from app.services.semantic_triage import ShadowTriage, TriageSettings
from app.services.rate_limit import RateLimiter, get_rate_limiter
from tests.conftest import FakeClerk, make_app_user
from tests.test_platform_admin import _AUTH, PlatformDB
from tests.test_platform_admin import _wire as _wire_admin
from tests.test_rate_limit import FakeRedis

_IGREJA = uuid.UUID("11111111-1111-1111-1111-111111111111")
_FANTASMA = uuid.UUID("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
_SECRET = "tsk-segredo-que-nunca-sai"


@pytest.fixture(autouse=True)
def _sem_env_typesafe(monkeypatch) -> None:
    for var in ("TYPESAFE_API_KEY", "JEV_SHADOW_TRIAGE_IGREJA_IDS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(platform_jev, "external_sends_allowed", lambda: True)


def _wire(app, *, db, clerk):
    limiter = RateLimiter(redis_client=FakeRedis())
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    return _wire_admin(app, db=db, clerk=clerk)


def _use_settings(monkeypatch, **values: object) -> None:
    settings = TriageSettings(_env_file=None, **values)  # type: ignore[call-arg]
    monkeypatch.setattr(jev_triage, "get_triage_settings", lambda: settings)


def _admin_db(**kw) -> PlatformDB:
    return PlatformDB(gate_app_user=make_app_user(), admin_marker="pa1", **kw)


def test_status_exige_platform_admin(app, monkeypatch) -> None:
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    db = PlatformDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    assert client.get("/admin/jev", headers=_AUTH).status_code == 403
    assert client.post("/admin/jev/teste", headers=_AUTH).status_code == 403


def test_status_nao_devolve_a_chave_e_resolve_nomes(app, monkeypatch) -> None:
    _use_settings(
        monkeypatch,
        typesafe_api_key=_SECRET,
        jev_shadow_triage_igreja_ids=f"{_IGREJA},{_FANTASMA},lixo",
    )
    db = _admin_db(igrejas=[SimpleNamespace(id=_IGREJA, nome="Igreja Piloto")])
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.get("/admin/jev", headers=_AUTH)

    assert resp.status_code == 200
    body = resp.json()
    assert _SECRET not in json.dumps(body)
    assert body["configurado"] is True
    assert body["integradoAoAgente"] is False
    assert body["enviosExternosPermitidos"] is True
    assert body["modelo"] == "jev-latest"
    assert body["idsInvalidos"] == 1
    assert body["igrejas"] == [
        {"id": str(_IGREJA), "nome": "Igreja Piloto"},
        {"id": str(_FANTASMA), "nome": None},
    ]


def test_status_desligado_por_padrao(app, monkeypatch) -> None:
    _use_settings(monkeypatch)
    client = _wire(app, db=_admin_db(), clerk=FakeClerk())
    body = client.get("/admin/jev", headers=_AUTH).json()
    assert body["configurado"] is False
    assert body["igrejas"] == []


def test_teste_sem_chave_responde_409_sem_chamar_api(app, monkeypatch) -> None:
    _use_settings(monkeypatch)

    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("não deveria chamar o Jev")

    monkeypatch.setattr(jev_triage, "run_shadow_triage", _boom)
    client = _wire(app, db=_admin_db(), clerk=FakeClerk())
    assert client.post("/admin/jev/teste", headers=_AUTH).status_code == 409


def test_teste_com_envios_desligados_responde_409(app, monkeypatch) -> None:
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    monkeypatch.setattr(platform_jev, "external_sends_allowed", lambda: False)

    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("não deveria chamar o Jev")

    monkeypatch.setattr(jev_triage, "run_shadow_triage", _boom)
    client = _wire(app, db=_admin_db(), clerk=FakeClerk())
    resp = client.post("/admin/jev/teste", headers=_AUTH)
    assert resp.status_code == 409
    assert "ALLOW_REAL_SENDS" in resp.json()["detail"]
    status_body = client.get("/admin/jev", headers=_AUTH).json()
    assert status_body["enviosExternosPermitidos"] is False


def test_teste_tem_limite_de_taxa_por_operador(app, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "rate_limit_auth_enabled", True, raising=False)
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    monkeypatch.setattr(jev_triage, "run_shadow_triage", lambda *a, **k: None)
    client = _wire(app, db=_admin_db(), clerk=FakeClerk())
    codes = [
        client.post("/admin/jev/teste", headers=_AUTH).status_code
        for _ in range(platform_jev.TESTE_LIMITE_POR_JANELA + 1)
    ]
    assert codes[:-1] == [502] * platform_jev.TESTE_LIMITE_POR_JANELA
    assert codes[-1] == 429


@pytest.mark.parametrize("disponivel", [True, False])
def test_teste_usa_mensagem_sintetica_e_audita(
    app, monkeypatch, disponivel: bool
) -> None:
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    seen: dict = {}

    def _fake(settings, texto, *, termo_pendente, remetente_ministerial):
        seen["texto"] = texto
        if not disponivel:
            return None
        return ShadowTriage(
            modelo="jev-1.13.0",
            risco_pastoral=0.061,
            pede_optout=0.01,
            aceita_termo=None,
            intencao="pedido_oracao",
            intencao_confianca=1.0,
            latencia_ms=850,
            tokens_in=400,
            tokens_out=30,
        )

    monkeypatch.setattr(jev_triage, "run_shadow_triage", _fake)
    db = _admin_db()
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.post("/admin/jev/teste", headers=_AUTH)

    assert seen["texto"] == platform_jev.MENSAGEM_TESTE
    audit = [o for o in db.added if isinstance(o, PlatformAuditLog)]
    assert [a.acao for a in audit] == ["jev_testar"]
    assert audit[0].detalhe == {"ok": disponivel}
    assert audit[0].actor_email is None
    if disponivel:
        assert resp.status_code == 200
        assert resp.json()["intencao"] == "pedido_oracao"
        assert resp.json()["latenciaMs"] == 850
    else:
        assert resp.status_code == 502
