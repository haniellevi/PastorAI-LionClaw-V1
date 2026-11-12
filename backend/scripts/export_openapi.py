"""Exporta o contrato OpenAPI do backend para o painel gerar seus tipos.

Gera o schema direto do app FastAPI, sem subir servidor, sem banco e sem
variáveis de ambiente. A saída é JSON com chaves ordenadas, para o diff ser
estável e legível.

Depois de mudar rotas ou modelos de resposta:

    cd backend && python scripts/export_openapi.py
    cd ../frontend && npm run api:types

`--check` só compara e falha se o arquivo do painel estiver desatualizado.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TARGET = BACKEND_ROOT.parent / "frontend" / "openapi.json"
UPDATE_HINT = (
    "cd backend && python scripts/export_openapi.py && "
    "cd ../frontend && npm run api:types"
)


def render() -> str:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    from app.main import create_app

    schema = create_app().openapi()
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="não escreve; falha se o arquivo estiver desatualizado")
    parser.add_argument("--output", type=Path, default=TARGET)
    args = parser.parse_args(argv)

    current = render()
    if args.check:
        existing = args.output.read_text(encoding="utf-8") if args.output.exists() else None
        if existing != current:
            print(f"OPENAPI_DESATUALIZADO: {args.output} difere do backend. Rode: {UPDATE_HINT}",
                  file=sys.stderr)
            return 1
        print(f"OPENAPI_OK: {args.output}")
        return 0

    args.output.write_text(current, encoding="utf-8")
    print(f"OpenAPI exportado para {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
