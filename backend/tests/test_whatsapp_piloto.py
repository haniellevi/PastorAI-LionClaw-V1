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


def test_padroes_seguros_de_producao() -> None:
    fields = Settings.model_fields
    assert fields["whatsapp_piloto_igreja_ids"].default == ""
    assert fields["whatsapp_sla_enabled"].default is False


@pytest.mark.parametrize(
    "ids,sla,esperado",
    [
        ("", True, False),  # igreja fora do piloto
        (str(_PILOTO), False, False),  # piloto, mas SLA por WhatsApp desligado
        (str(_PILOTO), True, True),
    ],
)
def test_sla_whatsapp_so_em_piloto_com_flag(monkeypatch, ids, sla, esperado) -> None:
    settings = _settings(ids)
    settings.whatsapp_sla_enabled = sla
    monkeypatch.setattr(sla_engine, "get_settings", lambda: settings)
    assert sla_engine._sla_whatsapp_allowed(_PILOTO) is esperado


class _NadaSession:
    """Sessão mínima: nenhum marcador existente, nenhum registro encontrado."""

    def execute(self, _stmt):
        return type("R", (), {"first": lambda self: None})()

    def get(self, *_a):
        return None


def test_sla_fechado_adia_sem_reservar_marcador(monkeypatch) -> None:
    from app.agent import masking

    monkeypatch.setattr(sla_engine, "get_settings", lambda: _settings(""))

    def _nao_reserva(*_a, **_k):  # pragma: no cover
        raise AssertionError("gate fechado: nada é reservado (a cobrança fica pendente)")

    monkeypatch.setattr(masking, "reserve_agent_event", _nao_reserva)
    breach = sla_engine.SlaBreach(
        igreja_id=_PILOTO,
        source="work_queue",
        item_id=uuid.uuid4(),
        kind="fonovisita",
        status=sla_engine.SlaStatus.COBRANCA,
        titulo="Ligar para visitante",
    )
    engine = sla_engine.SlaEngine(evolution=object())
    assert engine._dispatch(_NadaSession(), breach, "inst-1") is False


def test_aviso_de_billing_fora_do_piloto_fica_pendente(monkeypatch) -> None:
    monkeypatch.setattr(billing_worker, "get_settings", lambda: _settings(""))

    def _nao_notifica(*_a, **_k):  # pragma: no cover
        raise AssertionError("fora do piloto nada é enviado")

    monkeypatch.setattr(billing_worker, "notify_autoupgrade", _nao_notifica)
    op = type("Op", (), {"notify_status": "pending", "to_plano": "101_200", "id": uuid.uuid4()})()
    assert billing_worker._deliver_upgrade_notification(None, op, _PILOTO, object()) is False
    assert op.notify_status == "pending"
