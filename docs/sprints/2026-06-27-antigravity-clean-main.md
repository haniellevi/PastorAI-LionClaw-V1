# Antigravity clean-main handoff - 2026-06-27

**Branch:** `codex/antigravity-clean-main` - **Commits:** nenhum - **Deploy:** nao

## O que foi feito

- Criada worktree limpa em `PastorAi-1.0-antigravity`, baseada em `origin/main`.
- Adicionado `AGENTS.md` com regras adaptadas para Antigravity e contexto
  multi-agente.
- Adicionado `docs/antigravity-onboarding-prompt.md`.
- Adicionado `docs/ANTIGRAVITY_HANDOFF.md`.
- Atualizado `.gitignore` para bloquear estado local de agentes/IDEs:
  `.agents/`, `.claude/`, `.codex/`, `.lionclaw/`, `.mcp.json` e `*.bak`.
- Atualizado `next` e `eslint-config-next` de `14.2.15` para `14.2.35`, sem
  salto major.

## Decisoes

- Nao trazer a alteracao antiga de `frontend/src/app/globals.css` da pasta
  desatualizada; a worktree limpa usa o visual atual de `origin/main`.
- Nao executar `npm audit fix --force`; upgrades major de Clerk/Next devem ser
  missao separada.
- Antigravity deve receber primeiro um prompt de entendimento, nao uma tarefa de
  implementacao.

## Pendente / proximo passo

- Rodar validacoes completas nesta worktree limpa.
- Se tudo passar, usar esta pasta como base para a frente Antigravity.
- Depois, planejar separadamente upgrade major de Clerk/Next e gate RLS em
  staging.

## Verificacao

- `backend: pytest -q` passou.
- `frontend: npm run typecheck` passou.
- `frontend: npm run build` passou com Next.js `14.2.35`.
- `frontend: npm audit --audit-level=moderate` ainda falha com 10
  vulnerabilidades residuais: 9 high, 1 moderate. A correcao automatica exige
  `npm audit fix --force` e upgrades major, portanto ficou como missao separada.
- `code-review-graph build` passou nesta worktree: 248 arquivos, 2334 nos,
  18456 arestas.
