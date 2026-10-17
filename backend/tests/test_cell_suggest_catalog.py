import uuid
import pytest
from app.cell_suggest import policy
from app.agent.nodes import route_cell_suggest_intent


@pytest.mark.parametrize(
    "answer",
    [
        "SIM",
        "sim!",
        "Não",
        "ok",
        "cancelar",
        "Registre decisão de Maria",
        "Só pastores",
        "oração por mim",
        "19:00",
        "marcar fonovisita feita",
        "atribua consolidação",
        "qual o horário do culto",
        "endereço da igreja",
    ],
)
def test_other_protocol_answers_are_never_neighborhoods(answer):
    assert route_cell_suggest_intent(answer, pending=True)[0] == "none"


def test_neighborhood_answer_requires_own_live_state():
    assert route_cell_suggest_intent("São José", pending=False)[0] == "none"
    assert route_cell_suggest_intent("SAO JOSE", pending=True) == ("lookup", "sao jose")


def test_release_fence_and_empty_allowlist(monkeypatch):
    tenant = uuid.uuid4()
    monkeypatch.setenv("CELL_SUGGEST_ENABLED_IGREJA_IDS", str(tenant))
    assert not policy.enabled(tenant)
    monkeypatch.setattr(policy, "CELL_SUGGEST_APPROVED_RELEASE_ID", "synthetic-only")
    monkeypatch.delenv("CELL_SUGGEST_ENABLED_IGREJA_IDS")
    assert not policy.enabled(tenant)
    monkeypatch.setenv("CELL_SUGGEST_ENABLED_IGREJA_IDS", str(tenant))
    assert policy.enabled(tenant)
    assert not policy.enabled(uuid.uuid4())
    monkeypatch.setenv("CELL_SUGGEST_ENABLED_IGREJA_IDS", str(tenant) + ",invalid")
    assert not policy.enabled(tenant)
