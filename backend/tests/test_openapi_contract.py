"""O contrato OpenAPI que o painel usa para gerar tipos acompanha o backend.

`frontend/openapi.json` é gerado por `scripts/export_openapi.py` e vira tipos
TypeScript com `npm run api:types`. Se uma rota ou modelo de resposta mudar
sem regenerar, o painel passaria a compilar contra um contrato antigo.
"""

from __future__ import annotations

from scripts import export_openapi


def test_contrato_openapi_do_painel_esta_atualizado() -> None:
    target = export_openapi.TARGET
    assert target.exists(), f"{target} não existe. Rode: {export_openapi.UPDATE_HINT}"

    atualizado = target.read_text(encoding="utf-8") == export_openapi.render()

    assert atualizado, (
        "frontend/openapi.json está desatualizado em relação ao backend. "
        f"Rode: {export_openapi.UPDATE_HINT}"
    )


def test_exportacao_e_estavel_entre_chamadas() -> None:
    assert export_openapi.render() == export_openapi.render()
