#!/usr/bin/env bash
# Atualiza e serve o painel de acompanhamento do plano (docs/ops/acompanhamento/).
#   ./acompanhar.sh            lê o GitHub (somente leitura) e regenera o painel
#   ./acompanhar.sh offline    regenera sem consultar o GitHub
#   ./acompanhar.sh verificar  só valida tarefas.json
#   ./acompanhar.sh servir     regenera e serve em http://127.0.0.1:8791/painel.html
#   ./acompanhar.sh mod        abre o Claude Code com o mod do painel (comando /plano)
#   ./acompanhar.sh executar   abre o Claude Code com o mod e já manda continuar o plano
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
  executar)
    command -v claude >/dev/null || { echo "claude não encontrado"; exit 1; }
    python3 "$dir/atualizar.py" || true
    prompt='Continue a execução do plano de refatoração do Igreja12. Leia AGENTS.md, docs/ops/refatoracao-modular-plano.md e docs/ops/acompanhamento/README.md. Rode ./acompanhar.sh verificar e veja o estado no painel (/plano). Execute uma tarefa por vez, na ordem do plano, começando pela próxima executável do painel (hoje T04: test-local.sh rejeitar alvo desconhecido, em PR pequeno a partir de origin/main, numa worktree nova). O registro de acompanhamento fica na branch do #461 (esta worktree): ao iniciar, concluir ou bloquear cada tarefa, atualize estado, indicadores, evidências e próxima ação em docs/ops/acompanhamento/tarefas.json, rode ./acompanhar.sh e commite o registro na branch do #461, para o pipeline refletir o progresso. Não invente evidência, percentual nem prazo. Limites: não faça merge, deploy, provisionamento, limpeza de worktrees, envios reais nem ative Auto-fix; a integração do #463 e qualquer merge dependem de mim. Não altere configurações do Claude Code. Preserve mudanças alheias. Se travar, marque a tarefa como bloqueada com o motivo e me pergunte.'
    exec claude --plugin-dir "$dir/mod" "$prompt"
    ;;
  *)
    echo "Uso: $0 [atualizar|offline|verificar|servir|mod|executar]" >&2
    exit 2
    ;;
esac
