"""MVP: WhatsApp automático só para igrejas piloto (WHATSAPP_PILOTO_IGREJA_IDS).

Cobre o agente (worker), as cobranças de SLA e o aviso de billing. O conftest
libera tudo por padrão; aqui os métodos originais são restaurados.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import Settings
from app.services import billing_worker, sla_engine
from app.workers import queue_worker

_PILOTO = uuid.UUID("11111111-1111-1111-1111-111111111111")
_OUTRA = uuid.UUID("22222222-2222-2222-2222-222222222222")

# Capturados na importação, antes do fixture autouse do conftest trocá-los.
_REAL_HELPER = queue_worker._whatsapp_reply_enabled
_REAL_PILOTO = Settings.whatsapp_piloto


@pytest.fixture(autouse=True)
def _lista_real(monkeypatch) -> None:
    monkeypatch.setattr(Settings, "whatsapp_piloto", _REAL_PILOTO)


def _settings(ids: str) -> Settings:
    return Settings(_env_file=None, whatsapp_piloto_igreja_ids=ids)  # type: ignore[call-arg]


def test_lista_vazia_desliga_para_todas() -> None:
    assert _settings("").whatsapp_piloto(_PILOTO) is False


def test_so_igreja_listada_e_liberada() -> None:
    settings = _settings(f" {str(_PILOTO).upper()} , ")
    assert settings.whatsapp_piloto(_PILOTO) is True
    assert settings.whatsapp_piloto(str(_PILOTO)) is True
    assert settings.whatsapp_piloto(_OUTRA) is False
    assert settings.whatsapp_piloto("") is False


def test_worker_fora_da_lista_nao_roda_o_agente(monkeypatch) -> None:
    monkeypatch.setattr(queue_worker, "_whatsapp_reply_enabled", _REAL_HELPER)
    monkeypatch.setattr(queue_worker, "get_settings", lambda: _settings(""))

    def _nunca(*_a, **_k):  # pragma: no cover
        raise AssertionError("nenhuma sessão, reserva ou LLM fora da lista")

    outcome = queue_worker.IngestionOutcome(
        result=queue_worker.IngestionResult.REGISTERED,
        conversation_id=uuid.uuid4(),
        inbound=True,
        igreja_id=_OUTRA,
        provider_message_id="prov-1",
        texto="oi",
    )
    result = queue_worker.run_agent_for_message(_nunca, outcome)
    assert result is queue_worker.AgentRunDisposition.COMPLETED


@pytest.mark.parametrize("ids,esperado", [("", False), (str(_PILOTO), True)])
def test_helper_do_worker_le_a_lista(monkeypatch, ids: str, esperado: bool) -> None:
    monkeypatch.setattr(queue_worker, "get_settings", lambda: _settings(ids))
    assert _REAL_HELPER(_PILOTO) is esperado


class _ConnSession:
    """Sessão mínima: devolve uma conexão WhatsApp para qualquer select."""

    def execute(self, _stmt):
        conn = type("Conn", (), {"instance": "inst-1"})()
        return type("R", (), {"scalar_one_or_none": lambda self: conn})()


@pytest.mark.parametrize(
    "ids,sla,esperado",
    [
        ("", True, None),  # igreja fora do piloto
        (str(_PILOTO), False, None),  # piloto, mas SLA por WhatsApp desligado
        (str(_PILOTO), True, "inst-1"),
    ],
)
def test_sla_so_envia_em_piloto_com_flag(monkeypatch, ids, sla, esperado) -> None:
    settings = _settings(ids)
    settings.whatsapp_sla_enabled = sla
    monkeypatch.setattr(sla_engine, "get_settings", lambda: settings)
    assert sla_engine._instance(_ConnSession(), _PILOTO) == esperado


@pytest.mark.parametrize("ids,esperado", [("", None), (str(_PILOTO), "inst-1")])
def test_aviso_de_billing_so_em_piloto(monkeypatch, ids, esperado) -> None:
    monkeypatch.setattr(billing_worker, "get_settings", lambda: _settings(ids))
    assert billing_worker._notify_instance(_ConnSession(), _PILOTO) == esperado
