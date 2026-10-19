"""Prayer routing is local, closed and never invents authority from text."""

import uuid
import pytest
from app.prayer import policy
from app.prayer.catalog import classify, own_summary, presentation


def test_disabled_without_both_release_and_tenant(monkeypatch):
    tenant = uuid.uuid4()
    monkeypatch.delenv("PRAYER_REQUEST_ENABLED_IGREJA_IDS", raising=False)
    assert not policy.enabled(tenant)
    monkeypatch.setenv("PRAYER_REQUEST_ENABLED_IGREJA_IDS", str(tenant))
    assert not policy.enabled(tenant)
    monkeypatch.setattr(
        policy, "PRAYER_REQUEST_APPROVED_RELEASE_ID", "synthetic-test-only"
    )
    assert policy.enabled(tenant)
    assert not policy.enabled(uuid.uuid4())


@pytest.mark.parametrize(
    "text", ["talvez", "sim, mas não sei", "qualquer pessoa", "", "SIM!"]
)
def test_unclear_audience_never_becomes_consent(text):
    assert classify(text, pending=True) == "clarify"


def test_catalog_uses_closed_audience_and_explicit_confirmation():
    assert classify("Só pastores", pending=True) == "pastoral"
    assert classify("Pastores e meu líder", pending=True) == "pastoral_lider"
    assert classify("SIM", pending=True) == "confirm"
    assert classify("NÃO", pending=True) == "cancel"
    assert classify("SIM", pending=False) == "none"
    assert classify("Peço oração por mim: preciso de força.", pending=False) == "start"


def test_own_request_and_honest_disclosure():
    assert (
        own_summary("Peço oração por mim:  preciso de força. ") == "preciso de força."
    )
    assert own_summary("Peço oração pela pessoa P-00000") is None
    text = presentation("preciso de força.", "pastoral", None)
    assert "preciso de força." in text
    assert "equipe pastoral" in text
    assert "pastores ativos" in text
    assert "Admin e atendimento não têm acesso por cargo" in text
    assert "não protege retroativamente" in text
    assert "SIM" in text
    assert "10 minutos" in text
