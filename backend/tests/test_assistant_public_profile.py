"""Panel LLM prompt omits the public-information profile block."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import assistant


@pytest.mark.parametrize(
    "marker",
    ("informacoes_publicas", "informações_públicas"),
)
def test_panel_llm_keeps_only_external_profile_style(
    monkeypatch: pytest.MonkeyPatch,
    marker: str,
) -> None:
    captured: dict[str, str] = {}

    class _FakeClient:
        def __init__(self, _provider: str, _api_key: str, _model: str) -> None:
            pass

        def complete(self, system: str, texto: str) -> SimpleNamespace:
            captured["system"] = system
            captured["texto"] = texto
            return SimpleNamespace(texto="Resposta sintética")

    monkeypatch.setattr(assistant, "decrypt_secret", lambda _value: "synthetic")
    monkeypatch.setattr(assistant, "LLMClient", _FakeClient)

    reply = assistant._phrase_with_llm(
        SimpleNamespace(api_key_encrypted="synthetic", provedor="openai"),
        "gpt-5.6-luna",
        "Pergunta sintética",
        ["dashboard"],
        f"Estilo externo A[{marker}]SEGREDO[/{marker}]Estilo externo B",
    )

    assert reply == "Resposta sintética"
    assert captured["texto"] == "Pergunta sintética"
    assert "Estilo externo A" in captured["system"]
    assert "Estilo externo B" in captured["system"]
    assert "SEGREDO" not in captured["system"]
    assert "informacoes_publicas" not in captured["system"].casefold()
    assert "informações_públicas" not in captured["system"].casefold()
