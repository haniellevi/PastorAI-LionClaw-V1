# Antigravity handoff tecnico - PastorAI

Data: 2026-06-27
Worktree: `C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0-antigravity`
Branch: `codex/antigravity-clean-main`
Base: `origin/main` em `baeb26c`

Este e o ponto de entrada operacional para continuar o PastorAI com
Antigravity. Esta worktree foi criada porque a pasta anterior usada por esta
conversa estava 68 commits atrasada em relacao ao trabalho recente do Claude
Code.

## Status executivo

Esta worktree parte do `origin/main` mais recente e ja contem os sprints
recentes de redesign e ambiente registrados em `docs/sprints/`.

O objetivo desta branch nao e implementar feature. O objetivo e preparar uma
base limpa, segura e explicita para o Antigravity entender o projeto antes de
codar.

Validacao local executada nesta worktree:

- Backend: `pytest -q` passou.
- Frontend: `npm run typecheck` passou.
- Frontend: `npm run build` passou com Next.js `14.2.35`.
- Auditoria: `npm audit --audit-level=moderate` ainda falha com 10
  vulnerabilidades residuais (9 high, 1 moderate), sem aplicar force fix.
- Grafo: `code-review-graph build` passou nesta worktree com 248 arquivos,
  2334 nos e 18456 arestas.

## Estado Git esperado

Comando:

```powershell
git status --short --branch
```

Estado esperado apos este handoff:

```text
## codex/antigravity-clean-main...origin/main
 M .gitignore
 M frontend/package-lock.json
 M frontend/package.json
?? AGENTS.md
?? docs/ANTIGRAVITY_HANDOFF.md
?? docs/antigravity-onboarding-prompt.md
?? docs/sprints/2026-06-27-antigravity-clean-main.md
```

Nao deve haver mudanca em `frontend/src/app/globals.css` nesta worktree. A
versao visual atual vem do `origin/main`, isto e, do fluxo recente do Claude
Code.

## Mudancas preparatorias aplicadas

1. Criada worktree limpa a partir de `origin/main`.
2. Adicionado `AGENTS.md` para regras multi-agente e Antigravity.
3. Adicionado prompt de onboarding do Antigravity.
4. Adicionado este handoff tecnico.
5. Atualizado `.gitignore` para bloquear estado local de agentes/IDEs:
   `.agents/`, `.claude/`, `.codex/`, `.lionclaw/`, `.mcp.json` e `*.bak`.
6. Atualizado Next.js dentro da mesma major: `next` e `eslint-config-next`
   `14.2.15` -> `14.2.35`.

## Contrato de seguranca e arquitetura

### Multi-tenant e RLS

Fonte principal:

- `backend/app/db/rls.py`
- `backend/app/deps.py`

Regra critica: a conexao Supabase pode usar role com `BYPASSRLS`. Portanto o
backend precisa aplicar contexto de tenant e cair em role sujeita a RLS:

- Requests autenticados: `set_tenant_context(session, clerk_user_id)`.
- Workers sem Clerk: `set_tenant_context_for_igreja(session, igreja_id)`.

Ambos precisam preservar `SET LOCAL ROLE authenticated`.

Excecao intencional: console de plataforma usa `get_platform_admin`, sem
`set_tenant_context`, para operacao cross-tenant via allowlist. Nao reutilizar
esse padrao em endpoints normais de igreja.

### Migrations

Fonte: `backend/migrations/README.md`.

- Historico `0001` a `0017` congelado.
- Novas migrations usam timestamp UTC: `AAAAMMDD_HHMMSS_slug.sql`.
- Aplicacao no Supabase e manual, em ordem alfabetica.

### Segredos

Arquivos reais de ambiente devem continuar ignorados:

- `backend/.env`
- `frontend/.env.local`
- qualquer `.env` que nao seja template.

Templates versionaveis:

- `backend/.env.example`
- `frontend/.env.example`
- `deploy/.env.example`
- `deploy/.env.staging.example`, se existir.

Nao imprimir valores de `.env`. Em auditoria, relatar apenas nome da chave e se
esta `set`, `empty` ou `placeholder`.

## Riscos conhecidos

1. `npm audit` pode continuar acusando vulnerabilidades em Clerk/Next que so
   somem com upgrade major. Nao rodar `npm audit fix --force` sem missao propria.
2. Upgrade de Clerk exige teste humano de login real.
3. RLS local cobre comportamento por testes, mas prova final precisa staging com
   dois tenants.
4. Mudancas visuais devem respeitar os docs de design e sprints recentes.
5. Antigravity nao deve assumir contexto da conversa do Claude Code; deve ler os
   documentos.

## Comandos de validacao

Backend:

```powershell
cd backend
if (Test-Path .\.venv\Scripts\python.exe) {
  .\.venv\Scripts\python.exe -m pytest -q
} else {
  python -m pytest -q
}
```

Frontend:

```powershell
cd frontend
npm install
npm run typecheck
npm run build
npm audit --audit-level=moderate
```

## Proximo passo recomendado

Antes de pedir feature ao Antigravity:

1. Confirmar que `git status` so contem os arquivos preparatorios.
2. Enviar ao Antigravity o conteudo de
   `docs/antigravity-onboarding-prompt.md`.
3. Exigir relatorio de entendimento antes de codigo.
