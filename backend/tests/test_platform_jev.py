"""Console Master: status da triagem Jev e teste com mensagem sintética."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy.sql.elements import TextClause

from app.db.models import PlatformAuditLog, PlatformJevSettings
from app.config import get_settings
from app.routers import platform_jev
from app.services import crypto
from app.services import semantic_triage as jev_triage
from app.services.semantic_triage import ShadowTriage, TriageSettings
from app.services.rate_limit import RateLimiter, get_rate_limiter
from tests.conftest import FakeClerk, make_app_user
from tests.test_platform_admin import _AUTH, PlatformDB, _Result
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


class JevDB(PlatformDB):
    """PlatformDB com a linha única de configuração do Jev salva pelo console."""

    def __init__(
        self,
        *,
        jev_settings: PlatformJevSettings | None = None,
        tabela_existe: bool = True,
        **kw,
    ) -> None:
        super().__init__(**kw)
        self.jev_settings = jev_settings
        # False simula o banco antes da migration 20260926_120446.
        self.tabela_existe = tabela_existe

    def execute(self, statement, params=None) -> _Result:
        if isinstance(statement, TextClause) and "to_regclass" in statement.text:
            return SimpleNamespace(scalar=lambda: self.tabela_existe)
        descs = list(getattr(statement, "column_descriptions", []) or [])
        if descs and descs[0].get("entity") is PlatformJevSettings:
            if not self.tabela_existe:
                raise AssertionError("platform_jev_settings não existe")
            self.statements.append(statement)
            return _Result(scalar=self.jev_settings)
        return super().execute(statement, params)

    def add(self, obj) -> None:
        super().add(obj)
        if isinstance(obj, PlatformJevSettings):
            self.jev_settings = obj


def _admin_db(**kw) -> JevDB:
    return JevDB(gate_app_user=make_app_user(), admin_marker="pa1", **kw)


@pytest.fixture
def cifra(monkeypatch):
    """Chave de cifra de teste para `services/crypto`, sem vazar entre testes."""
    monkeypatch.setattr(crypto.get_settings(), "secrets_encryption_key", "k" * 32)
    crypto._get_fernet.cache_clear()  # noqa: SLF001 - rebuild Fernet with test key
    yield
    crypto._get_fernet.cache_clear()  # noqa: SLF001 - don't leak the test key


def _console_row(**values: object) -> PlatformJevSettings:
    row = PlatformJevSettings(id=1, igreja_ids=[])
    for key, value in values.items():
        setattr(row, key, value)
    return row


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


# ---------------------------------------------------------------------------
# Configuração pelo console (PUT /admin/jev/config)
# ---------------------------------------------------------------------------
_CHAVE_CONSOLE = "tsk-chave-do-console-123"


def test_config_exige_platform_admin(app, monkeypatch) -> None:
    _use_settings(monkeypatch)
    db = JevDB(gate_app_user=make_app_user(), admin_marker=None)
    client = _wire(app, db=db, clerk=FakeClerk())
    resp = client.put("/admin/jev/config", headers=_AUTH, json={"apiKey": _CHAVE_CONSOLE})
    assert resp.status_code == 403
    assert db.jev_settings is None


def test_config_salva_chave_cifrada_e_nunca_devolve(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch)
    db = _admin_db()
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.put(
        "/admin/jev/config",
        headers=_AUTH,
        json={"apiKey": f"  {_CHAVE_CONSOLE}  ", "modelo": "JEV-1.13", "timeoutSegundos": 1.5},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert _CHAVE_CONSOLE not in json.dumps(body)
    assert body["configurado"] is True
    assert body["chaveOrigem"] == "console"
    assert body["chaveAtualizadaEm"] is not None
    assert body["modelo"] == "jev-1.13"
    assert body["timeoutSegundos"] == 1.5
    row = db.jev_settings
    assert row.api_key_encrypted != _CHAVE_CONSOLE
    assert crypto.decrypt_secret(row.api_key_encrypted) == _CHAVE_CONSOLE
    audit = [o for o in db.added if isinstance(o, PlatformAuditLog)]
    assert [a.acao for a in audit] == ["jev_configurar"]
    assert audit[0].detalhe["chave"] == "alterada"
    assert _CHAVE_CONSOLE not in json.dumps(audit[0].detalhe)
    assert db.committed


def test_console_vale_sobre_o_ambiente_e_campo_vazio_cai_nele(
    app, monkeypatch, cifra
) -> None:
    _use_settings(
        monkeypatch,
        typesafe_api_key=_SECRET,
        typesafe_model="jev-latest",
        typesafe_timeout_seconds=2.0,
        jev_shadow_triage_igreja_ids=str(_IGREJA),
    )
    row = _console_row(
        api_key_encrypted=crypto.encrypt_secret(_CHAVE_CONSOLE), modelo="jev-1.13"
    )
    client = _wire(app, db=_admin_db(jev_settings=row), clerk=FakeClerk())

    body = client.get("/admin/jev", headers=_AUTH).json()

    assert body["chaveOrigem"] == "console"
    assert body["modelo"] == "jev-1.13"
    # Timeout não salvo no console: vale o do ambiente.
    assert body["timeoutSegundos"] == 2.0
    # Lista salva pelo console (vazia) substitui a do ambiente.
    assert body["igrejas"] == []


def test_chave_ilegivel_nao_cai_na_do_ambiente(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    row = _console_row(api_key_encrypted="nao-e-um-token-fernet")
    client = _wire(app, db=_admin_db(jev_settings=row), clerk=FakeClerk())

    body = client.get("/admin/jev", headers=_AUTH).json()

    assert body["configurado"] is False
    assert body["chaveIlegivel"] is True
    assert body["chaveOrigem"] is None


def test_remover_chave_volta_para_o_ambiente(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    row = _console_row(api_key_encrypted=crypto.encrypt_secret(_CHAVE_CONSOLE))
    db = _admin_db(jev_settings=row)
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.put("/admin/jev/config", headers=_AUTH, json={"removerChave": True})

    assert resp.status_code == 200
    assert db.jev_settings.api_key_encrypted is None
    assert resp.json()["chaveOrigem"] == "ambiente"
    audit = [o for o in db.added if isinstance(o, PlatformAuditLog)]
    assert audit[0].detalhe["chave"] == "removida"


def test_salvar_sem_chave_nova_mantem_a_salva(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch)
    token = crypto.encrypt_secret(_CHAVE_CONSOLE)
    db = _admin_db(jev_settings=_console_row(api_key_encrypted=token))
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.put("/admin/jev/config", headers=_AUTH, json={"modelo": "jev-latest"})

    assert resp.status_code == 200
    assert db.jev_settings.api_key_encrypted == token
    assert resp.json()["chaveOrigem"] == "console"


@pytest.mark.parametrize(
    ("payload", "trecho"),
    [
        ({"igrejaIds": [str(_IGREJA)]}, "DPA"),
        ({"igrejaIds": [str(_IGREJA)], "dpaAssinadoEm": "2999-01-01"}, "futuro"),
        (
            {"igrejaIds": [str(_IGREJA), str(_FANTASMA)], "dpaAssinadoEm": "2026-09-01"},
            "não encontrada",
        ),
        ({"modelo": "gpt-5.6-luna"}, "Modelo inválido"),
        ({"timeoutSegundos": 11}, "timeout"),
        ({"timeoutSegundos": 0}, "timeout"),
        ({"timeoutSegundos": 0.04}, "timeout"),
        ({"apiKey": "curta"}, "Chave inválida"),
        ({"apiKey": "tem espaco no meio"}, "Chave inválida"),
        ({"apiKey": "x" * 513}, "Chave inválida"),
        ({"apiKey": _CHAVE_CONSOLE, "removerChave": True}, "Escolha"),
    ],
)
def test_config_recusa_valores_invalidos(
    app, monkeypatch, cifra, payload: dict, trecho: str
) -> None:
    _use_settings(monkeypatch)
    db = _admin_db(igrejas=[SimpleNamespace(id=_IGREJA, nome="Igreja Piloto")])
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.put("/admin/jev/config", headers=_AUTH, json=payload)

    assert resp.status_code == 422
    assert trecho in resp.json()["detail"]
    # A resposta de erro nunca ecoa a chave colada.
    if payload.get("apiKey"):
        assert payload["apiKey"] not in resp.text
    assert db.jev_settings is None
    assert not db.committed


def test_config_lista_igrejas_com_dpa(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch)
    db = _admin_db(igrejas=[SimpleNamespace(id=_IGREJA, nome="Igreja Piloto")])
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.put(
        "/admin/jev/config",
        headers=_AUTH,
        json={"igrejaIds": [str(_IGREJA), str(_IGREJA)], "dpaAssinadoEm": "2026-09-20"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["igrejas"] == [{"id": str(_IGREJA), "nome": "Igreja Piloto"}]
    assert body["dpaAssinadoEm"] == "2026-09-20"
    assert db.jev_settings.igreja_ids == [_IGREJA]
    assert db.jev_settings.dpa_assinado_em == dt.date(2026, 9, 20)


def test_config_sem_chave_de_cifra_responde_409(app, monkeypatch) -> None:
    _use_settings(monkeypatch)
    monkeypatch.setattr(crypto.get_settings(), "secrets_encryption_key", "")
    crypto._get_fernet.cache_clear()  # noqa: SLF001
    try:
        db = _admin_db()
        client = _wire(app, db=db, clerk=FakeClerk())
        resp = client.put("/admin/jev/config", headers=_AUTH, json={"apiKey": _CHAVE_CONSOLE})
    finally:
        crypto._get_fernet.cache_clear()  # noqa: SLF001
    assert resp.status_code == 409
    assert "SECRETS_ENCRYPTION_KEY" in resp.json()["detail"]
    assert not db.committed


def test_status_sem_a_tabela_do_console_usa_o_ambiente(app, monkeypatch) -> None:
    # Deploy do código antes da migration 20260926_120446.
    _use_settings(monkeypatch, typesafe_api_key=_SECRET)
    client = _wire(app, db=_admin_db(tabela_existe=False), clerk=FakeClerk())

    resp = client.get("/admin/jev", headers=_AUTH)

    assert resp.status_code == 200
    assert resp.json()["configurado"] is True
    assert resp.json()["chaveOrigem"] == "ambiente"


def test_salvar_sem_a_tabela_do_console_responde_409(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch)
    db = _admin_db(tabela_existe=False)
    client = _wire(app, db=db, clerk=FakeClerk())

    resp = client.put("/admin/jev/config", headers=_AUTH, json={"apiKey": _CHAVE_CONSOLE})

    assert resp.status_code == 409
    assert "20260926_120446" in resp.json()["detail"]
    assert db.jev_settings is None
    assert not db.committed


def test_teste_usa_a_chave_salva_no_console(app, monkeypatch, cifra) -> None:
    _use_settings(monkeypatch)
    row = _console_row(api_key_encrypted=crypto.encrypt_secret(_CHAVE_CONSOLE))
    seen: dict = {}

    def _fake(settings, texto, *, termo_pendente, remetente_ministerial):
        seen["chave"] = settings.typesafe_api_key
        return None

    monkeypatch.setattr(jev_triage, "run_shadow_triage", _fake)
    client = _wire(app, db=_admin_db(jev_settings=row), clerk=FakeClerk())

    assert client.post("/admin/jev/teste", headers=_AUTH).status_code == 502
    assert seen["chave"] == _CHAVE_CONSOLE
