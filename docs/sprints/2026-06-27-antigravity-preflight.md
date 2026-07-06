# Antigravity preflight tecnico - 2026-06-27

**Branch:** `codex/antigravity-preflight` - **Commits:** nenhum - **Deploy:** nao

## O que foi feito

- Criada branch de preflight para sair da `main`.
- Criado `docs/antigravity-onboarding-prompt.md` com o prompt de onboarding do
  Antigravity.
- Criado `docs/ANTIGRAVITY_HANDOFF.md` com estado real do repo, gates,
  riscos e proximas missoes.
- Atualizado `.gitignore` para bloquear estado local de agentes/IDEs:
  `.agents/`, `.claude/`, `.codex/`, `.lionclaw/`, `.mcp.json` e `*.bak`.
- Restauradas dependencias do frontend com `npm install`.
- Atualizado `next` e `eslint-config-next` de `14.2.15` para `14.2.35`, sem
  salto major.
- Atualizado `code-review-graph` incrementalmente.

## Decisoes

- Nao executar `npm audit fix --force`, porque ele exige upgrades major
  (`@clerk/nextjs@7.5.9`, Next 16) e deve virar missao propria.
- Nao reverter a mudanca visual existente em `frontend/src/app/globals.css`;
  ela precisa ser comparada com o redesign/PR correspondente antes de qualquer
  rollback.
- Nao versionar configs locais de agentes. Foi observado que `.claude` contem
  historico operacional e pode conter credenciais em texto.
- Antes de feature nova, decidir se a frente Antigravity parte desta branch ou
  de uma worktree limpa baseada em `origin/main`, pois a base local esta 68
  commits atrasada.

## Pendente / proximo passo

- Sincronizar com `origin/main` ou criar worktree limpa antes de feature nova.
- Planejar upgrade major de Clerk/Next para limpar o audit residual.
- Fazer gate RLS real contra Supabase/staging com dois tenants.
- Decidir destino de arquivos ainda nao rastreados versionaveis:
  `AGENTS.md`, Docker/deploy, `discovery-notes.md` e `skills-lock.json`.

## Verificacao

- `backend/.venv/Scripts/python.exe -m pytest -q` passou.
- `frontend: npm run typecheck` passou.
- `frontend: npm run build` passou com Next.js `14.2.35`.
- `frontend: npm audit --audit-level=moderate` ainda falha com 10
  vulnerabilidades residuais: 9 high, 1 moderate; nenhuma critical apos patch
  de Next.
- `code-review-graph update --skip-flows` concluiu e deixou o grafo atualizado.
