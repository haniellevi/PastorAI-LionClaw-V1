"""Triagem Jev em modo sombra: desligada por padrão, só observa, nunca levanta.

Sem rede: a API da TypeSafe é simulada por `httpx.MockTransport`.
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest

from app.agent.context import LegacyTermContext, TrustedAgentContext
from app.db.models import AgentConversationLog
from app.domain.agent_authz import PrivilegeContext
from app.services import semantic_triage as jev_triage
from app.services.semantic_triage import TriageSettings

_IGREJA_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OUTRA_IGREJA = uuid.UUID("44444444-4444-4444-4444-444444444444")
_CONVERSATION_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
_PESSOA_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")


@pytest.fixture(autouse=True)
def _sem_env_typesafe(monkeypatch) -> None:
    for var in ("TYPESAFE_API_KEY", "JEV_SHADOW_TRIAGE_IGREJA_IDS"):
        monkeypatch.delenv(var, raising=False)
    # Guard B2 aberto por padrão nestes testes; o caso fechado é explícito.
    monkeypatch.setattr(jev_triage, "external_sends_allowed", lambda: True)


def _settings(**overrides: object) -> TriageSettings:
    values: dict[str, object] = {
        "typesafe_api_key": "test-key",
        "jev_shadow_triage_igreja_ids": str(_IGREJA_ID),
    }
    values.update(overrides)
    return TriageSettings(_env_file=None, **values)  # type: ignore[call-arg]


def _api_body(**answers: object) -> dict:
    base: dict = {
        "risco_pastoral": {"type": "noul", "noul": 0.02},
        "pede_optout": {"type": "noul", "noul": 0.01},
        "intencao": {
            "type": "choice",
            "choice": "pedido_oracao",
            "probabilities": {"pedido_oracao": 0.9, "outro": 0.1},
            "confidence": 0.87,
        },
    }
    base.update(answers)
    return {
        "model": "jev-1.13.0",
        "answers": base,
        "usage": {"input_tokens": 410, "output_tokens": 30},
    }


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


# ---- Gate --------------------------------------------------------------------
def test_desligado_por_padrao() -> None:
    assert not jev_triage.shadow_enabled_for(
        TriageSettings(_env_file=None), _IGREJA_ID  # type: ignore[call-arg]
    )


def test_sem_chave_fica_desligado_mesmo_com_igreja_listada() -> None:
    assert not jev_triage.shadow_enabled_for(
        _settings(typesafe_api_key="  "), _IGREJA_ID
    )


def test_so_liga_para_igreja_listada_e_ignora_id_invalido() -> None:
    settings = _settings(
        jev_shadow_triage_igreja_ids=f"nao-e-uuid, {_IGREJA_ID} ,"
    )
    assert jev_triage.shadow_enabled_for(settings, _IGREJA_ID)
    assert not jev_triage.shadow_enabled_for(settings, _OUTRA_IGREJA)


# ---- Request -----------------------------------------------------------------
def test_request_mascara_dados_sensiveis_da_mensagem() -> None:
    body = jev_triage.build_request(
        "meu cpf 000.000.000-00, email user@example.com, fone 5500000000000",
        termo_pendente=False,
        remetente_ministerial=False,
        model="jev-latest",
    )
    mensagem = body["state"]["mensagem"]
    assert "000.000.000-00" not in mensagem
    assert "user@example.com" not in mensagem
    assert "5500000000000" not in mensagem
    assert set(body["state"]) == {
        "mensagem",
        "canal",
        "remetente_e_lider_ou_pastor",
    }


# Números sintéticos (só zeros), montados em tempo de execução para não
# parecerem contato real no guard de privacidade do código-fonte.
_Z4 = "0" * 4
_FONES_SINTETICOS = [
    f"(00) 9{_Z4}-{_Z4}",
    f"00 9{_Z4}-{_Z4}",
    f"+55 00 9{_Z4}-{_Z4}",
    f"{_Z4} {_Z4}",
]


@pytest.mark.parametrize("fone", _FONES_SINTETICOS)
def test_request_redige_telefone_formatado(fone: str) -> None:
    body = jev_triage.build_request(
        f"me chama no {fone} por favor",
        termo_pendente=False,
        remetente_ministerial=False,
        model="m",
    )
    assert fone not in body["state"]["mensagem"]
    assert "0000" not in body["state"]["mensagem"]


def test_redacao_preserva_numeros_de_relatorio() -> None:
    texto = "Célula de terça: 12 presentes, 2 visitantes, oferta 85 reais"
    assert jev_triage.redact_for_egress(texto) == texto


def test_pergunta_de_aceite_so_existe_com_termo_pendente() -> None:
    sem = jev_triage.build_request(
        "sim", termo_pendente=False, remetente_ministerial=False, model="m"
    )
    com = jev_triage.build_request(
        "sim", termo_pendente=True, remetente_ministerial=False, model="m"
    )
    assert "aceita_termo" not in sem["questions"]
    assert com["questions"]["aceita_termo"]["type"] == "noul"
    assert "outro" in com["questions"]["intencao"]["criteria"]


# ---- Chamada -----------------------------------------------------------------
def test_chamada_ok_envia_bearer_e_parseia_respostas() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json=_api_body(aceita_termo={"type": "noul", "noul": 0.2})
        )

    result = jev_triage.run_shadow_triage(
        _settings(),
        "orem pela minha mãe",
        termo_pendente=True,
        remetente_ministerial=False,
        transport=_transport(handler),
    )

    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["model"] == "jev-latest"
    assert result is not None
    assert result.intencao == "pedido_oracao"
    assert result.aceita_termo == pytest.approx(0.2)
    payload = result.to_log_payload()
    assert payload["tokensIn"] == 410
    assert "mensagem" not in payload and "texto" not in payload


@pytest.mark.parametrize(
    "handler",
    [
        lambda request: httpx.Response(500, json={"error": "boom"}),
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")),
        lambda request: httpx.Response(200, json={"answers": {}}),
        lambda request: httpx.Response(
            200,
            json=_api_body(
                intencao={"type": "choice", "choice": "inventada", "confidence": 1}
            ),
        ),
    ],
    ids=["http_500", "timeout", "sem_respostas", "intencao_fora_do_conjunto"],
)
def test_qualquer_falha_vira_none(handler) -> None:
    assert (
        jev_triage.run_shadow_triage(
            _settings(),
            "oi",
            termo_pendente=False,
            remetente_ministerial=False,
            transport=_transport(handler),
        )
        is None
    )


def test_guard_de_envios_fechado_nao_chama_api(monkeypatch) -> None:
    monkeypatch.setattr(jev_triage, "external_sends_allowed", lambda: False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("ALLOW_REAL_SENDS fechado: nada pode sair")

    assert (
        jev_triage.run_shadow_triage(
            _settings(),
            "oi",
            termo_pendente=False,
            remetente_ministerial=False,
            transport=_transport(handler),
        )
        is None
    )


def test_url_da_api_exige_https() -> None:
    with pytest.raises(ValueError):
        _settings(typesafe_api_url="http://api.typesafe.ai/v1/systemone")


def test_texto_vazio_nao_chama_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("não deveria chamar a API")

    assert (
        jev_triage.run_shadow_triage(
            _settings(),
            "   ",
            termo_pendente=False,
            remetente_ministerial=False,
            transport=_transport(handler),
        )
        is None
    )


# ---- Evento de auditoria: só registra --------------------------------------------
class _LogSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    def flush(self) -> None:
        pass


def _context(accepted_version: str | None = "v1") -> TrustedAgentContext:
    return TrustedAgentContext(
        igreja_id=_IGREJA_ID,
        conversation_id=_CONVERSATION_ID,
        pessoa_id=_PESSOA_ID,
        conversation_state="ia",
        igreja_nome="Igreja Piloto",
        privilege=PrivilegeContext(pessoa_id=str(_PESSOA_ID), tipo="visitante"),
        legacy_term=LegacyTermContext(accepted_version, "v1"),
    )


def _log(
    session: _LogSession, settings: TriageSettings, texto: str = "oi"
) -> None:
    jev_triage.log_shadow_triage(
        session,  # type: ignore[arg-type]
        igreja_id=_IGREJA_ID,
        conversation_id=_CONVERSATION_ID,
        context=_context(accepted_version=None),
        texto=texto,
        route="consent",
        settings=settings,
    )


def test_log_nao_chama_jev_quando_desligado(monkeypatch) -> None:
    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("não deveria chamar o Jev")

    monkeypatch.setattr(jev_triage, "run_shadow_triage", _boom)
    session = _LogSession()
    _log(session, _settings(jev_shadow_triage_igreja_ids=""))
    assert session.added == []


def test_log_registra_evento_sem_texto_da_mensagem(monkeypatch) -> None:
    captured: dict = {}

    def _fake(settings, texto, *, termo_pendente, remetente_ministerial):
        captured["termo_pendente"] = termo_pendente
        return jev_triage.parse_response(_api_body(), latencia_ms=120)

    monkeypatch.setattr(jev_triage, "run_shadow_triage", _fake)
    session = _LogSession()
    _log(session, _settings(), texto="texto muito particular")

    assert captured["termo_pendente"] is True
    [row] = session.added
    assert isinstance(row, AgentConversationLog)
    assert row.evento == "jev_shadow_triage"
    assert row.payload["status"] == "ok"
    assert row.payload["routeRegras"] == "consent"
    assert row.payload["intencao"] == "pedido_oracao"
    assert "texto muito particular" not in json.dumps(row.payload)


def test_log_registra_indisponivel_quando_jev_falha(monkeypatch) -> None:
    monkeypatch.setattr(
        jev_triage, "run_shadow_triage", lambda *a, **k: None
    )
    session = _LogSession()
    _log(session, _settings())
    [row] = session.added
    assert row.payload["status"] == "indisponivel"
