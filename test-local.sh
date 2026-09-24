#!/usr/bin/env bash
# Roda os testes locais com as mesmas versões do CI (Python 3.13, Node 24, umask 022).
#   ./test-local.sh            backend + frontend
#   ./test-local.sh backend    só backend
#   ./test-local.sh frontend   só frontend
set -euo pipefail
umask 022

root=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
alvo="${1:-todos}"

python="${PASTORAI_PYTHON:-$root/backend/.venv-runtime/bin/python}"
node_bin="${PASTORAI_NODE_BIN:-$HOME/.nvm/versions/node/v$(cat "$root/.nvmrc")/bin}"

if [[ "$alvo" == "todos" || "$alvo" == "backend" ]]; then
  "$python" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version' \
    || { echo "Python 3.13 esperado em $python (crie com: uv venv backend/.venv-runtime --python 3.13.14 && uv pip install -p backend/.venv-runtime -r backend/requirements.lock)"; exit 1; }
  (cd "$root/backend" && "$python" -m pytest -q -p no:cacheprovider -m "not rls_integration")
fi

if [[ "$alvo" == "todos" || "$alvo" == "frontend" ]]; then
  [[ -x "$node_bin/node" ]] || { echo "Node $(cat "$root/.nvmrc") esperado (instale com: nvm install)"; exit 1; }
  export PATH="$node_bin:$PATH"
  (cd "$root/frontend" && npx tsc --noEmit && npx vitest run)
fi
