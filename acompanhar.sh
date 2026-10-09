#!/usr/bin/env bash
# Atualiza e serve o painel de acompanhamento do plano (docs/ops/acompanhamento/).
#   ./acompanhar.sh            lê o GitHub (somente leitura) e regenera o painel
#   ./acompanhar.sh offline    regenera sem consultar o GitHub
#   ./acompanhar.sh verificar  só valida tarefas.json
#   ./acompanhar.sh servir     regenera e serve em http://127.0.0.1:8791/painel.html
#   ./acompanhar.sh mod        abre o Claude Code com o mod do painel (comando /plano)
#   ./acompanhar.sh executar   abre o Claude Code com o mod e já manda continuar o plano
# O painel também abre direto do arquivo docs/ops/acompanhamento/painel.html depois de gerado.
# dados.js e github.json são gerados e locais (não versionados): em checkout novo rode ./acompanhar.sh offline.
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
    prompt='Continue o plano incremental em docs/ops/refatoracao-modular-plano.md. Confirme repositório, worktree, branch, SHA e alterações antes de agir; leia AGENTS.md, o MVP e tarefas.json. Escolha a próxima fatia executável conforme evidências atuais, distinguindo desenvolvimento local, CI, integração e publicação. #461, #463 e #464 já foram integrados: não use essas branches como destino de novos registros. Preserve alterações alheias e use branch/worktree própria para a fatia. Atualize tarefas.json e a sprint com provas do SHA exato; rode ./acompanhar.sh offline para atualizar o painel sem inventar CI. Não repita testes já aprovados sem mudança, falha ou dúvida relevante. Iteração local com dados sintéticos pode avançar; push, merge, provisionamento, banco remoto, deploy, limpeza e efeitos reais exigem autorização nominal já presente na sessão. Não altere configurações do Claude Code, não desligue checks e não abra gates para um teste passar. T08 continua exigindo a decisão de recursos/custo antes da publicação online.'
    exec claude --plugin-dir "$dir/mod" "$prompt"
    ;;
  *)
    echo "Uso: $0 [atualizar|offline|verificar|servir|mod|executar]" >&2
    exit 2
    ;;
esac
