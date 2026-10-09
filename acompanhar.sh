#!/usr/bin/env bash
# Atualiza e serve o painel de acompanhamento do plano (docs/ops/acompanhamento/).
#   ./acompanhar.sh            lê o GitHub (somente leitura) e regenera o painel
#   ./acompanhar.sh offline    regenera sem consultar o GitHub
#   ./acompanhar.sh verificar  só valida tarefas.json
#   ./acompanhar.sh servir     regenera e serve em http://127.0.0.1:8791/painel.html
#   ./acompanhar.sh mod        abre o Claude Code com o mod do painel (comando /plano)
# O painel também abre direto do arquivo docs/ops/acompanhamento/painel.html.
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
dir="$root/docs/ops/acompanhamento"
porta="${ACOMPANHAMENTO_PORTA:-8791}"

command -v python3 >/dev/null || { echo "python3 não encontrado"; exit 1; }

case "${1:-atualizar}" in
  atualizar) python3 "$dir/atualizar.py" ;;
  offline)   python3 "$dir/atualizar.py" --sem-github ;;
  verificar) python3 "$dir/atualizar.py" --verificar ;;
  servir)
    python3 "$dir/atualizar.py"
    echo "Painel em http://127.0.0.1:${porta}/painel.html (Ctrl+C encerra)"
    exec python3 -m http.server "$porta" --bind 127.0.0.1 --directory "$dir"
    ;;
  mod)
    command -v claude >/dev/null || { echo "claude não encontrado"; exit 1; }
    python3 "$dir/atualizar.py" || true
    exec claude --plugin-dir "$dir/mod"
    ;;
  *)
    echo "Uso: $0 [atualizar|offline|verificar|servir|mod]" >&2
    exit 2
    ;;
esac
