# Plano — produção limpa — 2026-07-09

Baseado em: `docs/ops/PROD-ENV-RUNBOOK.md`, `backend/migrations/README.md`, `SPEC_PROGRESS.md`,
`docs/sprints/README.md` (main-clean, `a7a04c8`) + `SNAPSHOT-RAIZ-SUJA-2026-07-09.md`.
Somente leitura/planejamento — nenhuma ação executada aqui.

## 1. Já em main (`a7a04c8`)

- **C1 RLS/tenant-context**: seam completo (`mark_tenant_scoped`/`mark_cross_tenant`/`promote_to_tenant`,
  listener `after_begin`, T1-T6 `rls_integration`) via PR-A/B/C/D — mecanismo 100% em produção.
- **Célula**: schema base (PR1), reuniões/presença (PR2), Central/Solicitações/Multiplicação (PR3-PR9),
  líder-derivado L1-L3, PR-A1 (guard líder-candidato), PR-A1.1 (Central seleciona célula existente),
  **PR-A2** `celula_membro` canônico (#134 — migration DEV e PROD já confirmadas pelo dono).
- **Segurança**: SEC-1 (config seguro session/CORS), SEC-2 (rate limit auth), SEC-3A (invalidação de
  sessão), SEC-3B (reset token uso único) — todos mergeados.
- **Outros**: billing/planos (#140), pausa IA CSIM (#139), branding por tenant (#121), onboarding de
  igreja (#110/#112/#116), Agenda EVT-1..8 (EVT-9 com flag off), Pessoas/Comunicação admin (#137),
  fechamento do ciclo 7B (#142/#143).

## 2. Só na raiz suja — ✅ **RAIZ LIMPA 2026-07-09** (conteúdo preservado em branch de backup)

Depois do deploy validado (seção 4), a raiz foi limpa: `git worktree list` final só mostra a raiz em
`main`; `git status --short --branch` = `## main...origin/main` sem modificação; HEAD = `a7a04c8` =
`origin/main`. Todo o conteúdo abaixo (itens a-e) foi **preservado antes de limpar**, na branch local
**`backup/raiz-suja-2026-07-09`**, commit **`d0b5053`** — inclusive estes 2 arquivos de plano/handoff
(que eram untracked na raiz e ficaram só nesse commit de backup). **Não deletar essa branch ainda.**
Descrição original do que havia (histórico, pra referência):

a) **Refactor de routers em pacote** — `backend/app/db/models/`, `backend/app/routers/{calendar,cell_requests,cells,platform_admin}/`,
   `backend/app/workers/queue_worker/` substituem os 5 arquivos flat marcados `D` no snapshot.
   Conteúdo migrado, não perdido — mas nunca virou commit em nenhum branch.

b) **Possível trabalho de segurança adicional** — `backend/app/services/rate_limit.py`, 3 migrations
   datadas `2026-07-07` (`app_user_password_changed_at`, `agent_event_idempotency_marker_uidx`,
   `force_rls_tenant_tables`), 4 testes (`test_auth_rate_limit.py`, `test_auth_session_invalidation.py`,
   `test_config_production.py`, `test_subscription_autoupgrade.py`) + 8 docs de sprint `2026-07-07/08`.
   **Não determinado ainda** se é rascunho anterior do que já foi formalizado e mergeado (SEC-1/2/3A/3B)
   ou trabalho novo (candidato a SEC-4/5) — precisa comparar diff contra os SHAs já mergeados antes de
   decidir descartar ou promover a PR.

c) **Refactor frontend dashboard/admin** — `ChurchAdminsTab.tsx`, `ChurchAgenteTab.tsx`,
   `ChurchDashboardTab.tsx`, `church-page-utils.ts`, `ActionModal.tsx`, `DashTileCard.tsx`,
   `JourneyCard.tsx`, `MemberWelcome.tsx`, `dashboard-types.ts`, `useDashboardData.ts`, `session-token.ts`
   — sem branch/PR conhecida.

d) **Ferramental local** — `.agents/`/`.claude/skills` (Clerk, Supabase), `.codex/`, `.mcp.json`,
   `skills-lock.json`, `discovery-notes.md` — ambiente, não é código de produto.

e) **Tarballs soltos** — `.deploy-artifacts/pastorai-backend-ac14850.tar`, `pastorai-backend-5e977c8.tar`
   — resíduo de deploys manuais passados, já aplicados.

## 3. Depende de migration manual em PROD

- Nenhuma pendente confirmada agora (PR-A2 DEV+PROD já confirmadas pelo dono).
- **Se** as 3 migrations soltas (item 2b) forem trabalho novo (não duplicata), precisam virar PR formal
  com review, então migration DEV → verificação → PROD, seguindo `backend/migrations/README.md`
  (nome por timestamp, aplicação manual em ordem alfabética, sem ledger em PROD).

## 4. Depende de deploy backend — ✅ **RESOLVIDO 2026-07-09** (`DEPLOY_PROD_BACKEND_AND_QUEUE_WORKER_PASS`)

- **SEC-1/SEC-2/SEC-3A/SEC-3B** — mergeados; deploy de backend feito nesta rodada, código em produção.
- **PR-A2 (#134)** — migration PROD confirmada; `backend` (3 write-sites) e `queue-worker`
  (`vincular_celula`, 4º write-site) deployados de forma controlada. Ver
  `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md` pra evidências completas (hash conferido na VPS, backup,
  health público antes/depois, fila Redis vazia checada antes do restart do worker).
- `pastorai_cron_worker` **deliberadamente não reiniciado** (não importa `agent/tools.py`) — fica pra um
  gate futuro se necessário.

## 5. Depende de ação humana

- **SEC-0** — rotação de senha/credencial Clerk. Fora do alcance de automação, pendência antiga. **Único
  item humano ainda em aberto.**
- Decisão sobre o conteúdo preservado em `backup/raiz-suja-2026-07-09` (`d0b5053`, item 2): descartar,
  ou formalizar partes dele em branch/PR.
- Decisão futura (não urgente): recriar `cron-worker` ou manter como está.

## 7. Smoke funcional autenticado em produção — ✅ **PASS 2026-07-09** (`SMOKE_PROD_READ_ONLY_PASS`)

Executado Bloco A (admin) + Bloco C (líder), só read-only, sessão PROD ativa no browser conectado
(nunca digitei credencial). Ver `docs/sprints/SMOKE-PROD-PLAN-2026-07-09.md` e
`docs/sprints/DEPLOY-HANDOFF-2026-07-09.md` pra evidência completa. Resumo: prova cruzada confirma
PR-A2 funcionando ponta-a-ponta em produção (admin vê 4 pessoas com `célula = Celula 1`; líder vê as
mesmas 4 como discípulos ativos via `celula_membro`). Zero escrita, zero efeito externo disparado, Bloco
B (criar dado de teste) não precisou ser executado. **Ciclo PR-A2/SEC-1..3B encerrado
ponta-a-ponta** — único item pendente é SEC-0 (ação humana, seção 5).

## 6a. Validação local — tentativa 1, 2026-07-09 (main-clean sem ambiente) — BLOCKED

`PastorAi-1.0-main-clean` não tinha ambiente provisionado (worktree só pra snapshot git) — os 4 comandos
falharam antes de validar qualquer coisa:

| Comando | Resultado | Erro exato |
|---|---|---|
| `backend\.venv\Scripts\python.exe -m pytest -q` | FAIL | `.venv` não existe nesse worktree — `The term '.\.venv\Scripts\python.exe' is not recognized...` |
| `npm run typecheck` (frontend) | FAIL | `node_modules` não instalado — `'tsc' não é reconhecido como um comando interno ou externo...` |
| `npm run lint` (frontend) | FAIL | idem — `'next' não é reconhecido...` |
| `npm run build` (frontend) | FAIL | idem — `'next' não é reconhecido...` |

## 6b. Validação local — tentativa 2, 2026-07-09 (após provisionar) — **PASS**

Autorizado provisionar `main-clean` (venv Python local + `npm ci`), sem tocar raiz suja, sem commit,
sem migration, sem deploy. Base reconfirmada antes de rodar: detached HEAD `a7a04c8` = `origin/main`,
working tree limpo.

**Backend** (`PastorAi-1.0-main-clean\backend`):

| Comando | Exit code | Resultado |
|---|---|---|
| `py -3 -m venv .venv` | 0 | venv criado, Python 3.13.5 |
| `.\.venv\Scripts\python.exe -m pip install --upgrade pip` | 0 | pip 25.1.1 → 26.1.2 |
| `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` | 0 | fastapi 0.139.0, SQLAlchemy 2.0.51, pytest 9.1.1 + deps — sem conflitos |
| `.\.venv\Scripts\python.exe -m pytest -q` | 0 | só pontos (passou) + 13 `s` (skipped) — **zero `F`/`E`**. Warnings benignos (StarletteDeprecationWarning, JWT InsecureKeyLengthWarning — segredo de teste curto, esperado). Linha-resumo final "N passed" não apareceu no stdout capturado (peculiaridade do writer/pipe PowerShell, reproduzida em 4 tentativas incl. `-u` e `--collect-only`) — exit code 0 é o critério oficial do pytest, considerado **PASS** |

**Frontend** (`PastorAi-1.0-main-clean\frontend`):

| Comando | Exit code | Resultado |
|---|---|---|
| `npm ci` | 0 | 397 pacotes instalados. `ERESOLVE` overriding peer-dep (vite/vitest vs `@types/node`) — não bloqueante. 10 vulnerabilidades reportadas pelo `npm audit` (1 moderada, 8 altas, 1 crítica) — **não investigadas, fora do escopo desta validação** |
| `npm run typecheck` (`tsc --noEmit`) | 0 | sem erros |
| `npm run lint` (`next lint`) | 0 | "No ESLint warnings or errors" |
| `npm run build` (`next build`) | 0 | compilado, 6/6 páginas estáticas geradas (`/`, `/_not-found`, `/admin`, `/gestao`) |

**Status final: PASS.** Nenhum arquivo de código alterado, nada commitado, nenhuma migration/deploy.
`.venv` e `node_modules` agora existem no worktree `main-clean` (efeito esperado do provisionamento).

## 8. Validações antes de qualquer deploy (histórico, pré-execução)

- `pytest` completo no `main-clean` (passo 4 deste plano).
- `typecheck` + `lint` + `build` do frontend (idem).
- CI verde no SHA exato usado no tarball (`a7a04c8` já passou CI nos merges que o compõem).
- sha256 do tarball registrado no handoff.
- Pós-deploy: `docker compose ps` (backend + queue_worker healthy), `curl .../health` 200, grep no
  container confirmando os arquivos-chave (`services/celula_membro.py`, chamadas `ensure_active_membro`
  em `auth.py`/`contacts.py`/`team.py`/`agent/tools.py`).
- Não reaplicar nenhuma migration já confirmada como aplicada.
