# C1 — Seam profundo de RLS/tenant-context (fechamento) — 2026-07-08

**Branch:** `feat/c1-rls-pr-a` → `-b` → `-c` → `-d` (split de 4 PRs)  ·  **Commits:** PR-A `4862211`, PR-B `5ac1869`, PR-C `5c6e2a7`, PR-D `f23162f`  ·  **Merges:** #123 `7b7e197`, #124 `5e977c8`, #125 `bccdec4`, #126 `a41cfec`  ·  **Deploy:** sim — produção (VPS Hostinger, backend + queue-worker + cron-worker)

Origem: pipeline `architecture-review` do LionClaw (run `20260707_112731-2c3953`), candidato **C1**, decisões D1–D5. O refactor chegou como diff não-commitado; foi congelado e integrado à `main` em 4 PRs atômicos, cada um com gates completos antes do merge, e deployado incrementalmente em produção.

## O que foi feito

O isolamento por tenant (RLS por `igreja_id`) deixou de ser re-asserção manual espalhada em ~116 call sites e virou um **seam profundo** de sessão:

- **PR-A (#123)** — `backend/app/db/tenant_session.py` (novo): `mark_tenant_scoped` / `mark_cross_tenant` / `promote_to_tenant` sobre `session.info`, exceções fail-closed (`TenantScopeError` / `TenantPinConflictError` / `TenantPromotionError`) e **listener SQLAlchemy `after_begin`** que reaplica GUC `app.tenant_igreja_id` + `SET LOCAL ROLE authenticated` em **toda** transação de sessão marcada — inclusive leituras pós-commit, onde o modelo antigo perdia o escopo e voltava a BYPASSRLS. Registro do listener em `session.py`. Observabilidade read-only em `rls_observability.py`. Superfície de teste RLS opt-in (`RLS_TEST_DATABASE_URL` + guard fail-loud anti DEV/PROD) e CI `.github/workflows/rls-integration.yml` (Postgres 16 efêmero, anti-cobertura-falsa).
- **PR-B (#124)** — `deps.py`: `get_current_user` marca a sessão (`mark_tenant_scoped`, D1) após resolver o `app_user`; `get_platform_admin` marca saída cross-tenant nomeada (`mark_cross_tenant`, D4). `subscription.py` (caso âncora): remove a re-asserção manual pós-commit — o listener D2 cobre.
- **PR-C (#125)** — `queue_worker.py`: ingestão em duas fases nomeadas (`mark_cross_tenant` no lookup por instância → `promote_to_tenant`, ordem virou invariante executável, D4). `sla_engine.py`: sweep processa **cada igreja numa sessão nova** `mark_tenant_scoped` (D3, pinning), fechada por iteração — RLS passa a valer no SLA, que antes rodava 100% BYPASSRLS.
- **PR-D (#126)** — `_common.py`: `ensure_tenant_context` deixa de re-setar o GUC e vira **shim de assert fail-closed** (decisão OQ#3) — levanta `TenantScopeError` se a sessão não estiver marcada no igreja do usuário. Removidos os **116 call sites** de `ensure_tenant_context` dos **25 routers** + imports órfãos. O escopo por tenant passa a vir 100% de `get_current_user` + listener.

`SET LOCAL ROLE authenticated` (invariante crítico do projeto) foi **preservado** em `rls.py` e **duplicado** no listener — o isolamento ficou mais forte, não mais fraco.

## Decisões

- **Split em 4 PRs, não 5** (o plano do pipeline previa 5): `test_rls_invariant.py` já importava o seam em nível de módulo, então PR1+PR2 colapsaram em PR-A. Ordem seg­ura: PR-A (base neutra) → PR-B ∥ PR-C (após PR-A) → PR-D (atômico, após PR-B em produção).
- **PR-D atômico** (shim + remoção dos 116 call sites no mesmo PR): são as duas metades de uma única troca de invariante. Separar reabriria BYPASSRLS silencioso (remoção sem shim) ou derrubaria endpoints (shim sem remoção).
- **Deploy por tarball** (`git archive` do merge commit + `docker compose up -d --build --no-deps` dos 3 serviços de app), nunca `git pull` — a VPS não tem `.git`. Redis/Evolution/Caddy nunca tocados.
- **`ensure_tenant_context` mantido como shim** (não removido): observabilidade fail-closed contínua para chamadores futuros/esquecidos.

## Verificação (gates executados em cada PR)

- `compileall` + import `app.main`/`create_app` — OK em todos.
- **Suíte offline** pytest: 1029/13 (PR-A/B), 1031/13 (PR-C), **1034/13** (PR-D) — 0 failed.
- **Prova RLS real** contra Postgres efêmero Docker: **13 passed / 0 skipped / 0 failed** em todos os PRs (guard anti DEV/PROD + anti-skip do CI).
- **CI GitHub `rls-integration`**: verde em #123/#124/#125/#126.
- Secret scan + `git diff --check`: limpos.
- **Policies RLS das 7 tabelas do sweep SLA** (`work_queue_items`, `consolidacoes`, `agent_conversation_logs`, `app_users`, `pessoas`, `user_roles`, `whatsapp_connections`) validadas em **DEV e PROD**: RLS on, policy `tenant_isolation` (USING+WITH CHECK em `current_igreja_id()`), role `authenticated` NOBYPASSRLS com SELECT/INSERT, `current_igreja_id()` prioriza o GUC.
- **Deploys em produção** confirmados por `StartedAt` (só os 3 serviços de app recriados; redis/caddy/evolution inalterados), health `HTTP/2 200 {"status":"ok"}` via Caddy, logs sem `TenantScopeError`/500/traceback, shim presente no container.
- **Smoke autenticado** confirmado pelo dono: telas logadas (dashboard, contatos, células/reuniões, agenda, conversas, pipeline) + um write carregam sem 500 — os routers migrados seguem escopados por `get_current_user` na prática.

## Pendente / próximo passo (dívidas remanescentes)

- **`run_due_crons` (cron legado)** segue na sessão compartilhada **BYPASSRLS** — fora do escopo do C1; se escrever dados por tenant, roda sem RLS. Candidato a um C1-follow-up.
- **Limpeza opcional na VPS**: arquivos de backup de deploys manuais antigos em `backend/app/routers/*.py.p0b2new` / `*.bak-prePR1` / `*.evt8anew` contêm código pré-shim. Não são `.py` (Python não importa), inócuos em runtime, mas poluem grep/árvore. Decisão do dono.
- **Docstring do shim** menciona "26 routers" (25 no PR-D + `subscription.py` no PR-B) — defensável no total C1; ajuste doc-only se quiser refletir o escopo estrito do PR-D.
