# Promoção da Agenda MVP (EVT-1..5) para produção — 2026-06-30

**Branch:** `docs/agenda-mvp-prod-promotion` (este registro, docs-only)
· **Commits/SHA promovido:** `27f7e7d` (merge da EVT-5, PR #71)
· **Deploy:** **sim** — migration prod + backend VPS + frontend Vercel (smoke funcional pendente)

## O que foi feito
Promoção da **Agenda MVP** (EVT-1..5: schema, CRUD+confirm, visões Semana/Mês/Ano,
detalhe/editar/excluir, fila "A confirmar") de `main` `27f7e7d` para **produção**,
em ordem segura: migration → backend → frontend, cada passo com diagnóstico
read-only antes e verificação depois.

- **Migration EVT-1 no PROD** `pffafnchtxbimpwyaczq` (projeto **Pastor-Ai-LionClaw-v1**,
  us-west-2): aplicada **manual via SQL Editor** pelo responsável (só o DDL do
  arquivo `20260629_222635_evt1_…sql`; prod **não tem** `schema_migrations`).
- **Backend prod** rebuildado no `27f7e7d` na VPS `2.25.167.107`
  (`/opt/pastorai-lionclaw`): deploy por **tarball** do backend versionado
  (VPS sem `.git`), preservando `Dockerfile`/`.dockerignore` remotos, com **backup**
  prévio (`/root/pastorai-backups/backend-before-27f7e7d-20260630-122910.tar.gz`),
  via `docker compose up -d --build --no-deps backend`. Workers **não** reiniciados.
- **Frontend prod** publicado por `vercel --prod` (projeto `pastorai-frontend`),
  de um worktree limpo em `27f7e7d`, build remoto, alias `app.igreja12.com.br`.
- **Runbook operacional** criado: `docs/ops/PROD-ENV-RUNBOOK.md` (refs, infra,
  processos de deploy, comandos seguros/proibidos, riscos do smoke).

## Decisões
- **Ordem migration → backend → frontend.** Migration EVT-1 é **aditiva** e
  backward-compatible (colunas com default, `data` vira nullable), então o backend
  antigo continua funcionando entre a migration e o deploy de código — ordem segura.
- **Deploy backend só do serviço `backend`** (`--no-deps backend`) para honrar
  "não reiniciar workers" — `queue_worker`/`cron_worker` mantiveram container
  ID/StartedAt.
- **Migration aplicada pelo humano via SQL Editor** (não por IA/MCP): produção é
  escrita irreversível em dados reais; método espelha o usado no DEV.
- **Backend por tarball, não git** — a VPS não tem `.git`; preservar
  `Dockerfile`/`.dockerignore` remotos evita regressão de build.
- **Smoke funcional em prod adiado** (só read-only nesta fase): falta usuário Clerk
  de produção e há risco de **evento órfão no Google** (`POST /events` cria evento
  real se o Google estiver configurado; `DELETE` do app não remove — escopo EVT-6+).

## Verificação
- **Migration prod (read-only via MCP só-SELECT):** `events` com 18 colunas, `data`
  nullable, 4 enums (`event_status/tipo/origem/recorrencia`), 4 constraints
  (`events_hora_formato_chk` NOT VALID), FK `events_confirmado_por_fkey`→`app_users`,
  RLS enabled + policy `tenant_isolation` presentes; **dados reais inalterados**
  (`events=1`, `igrejas=2`, `app_users=3`, `pessoas=10`; backfill da linha existente
  para `status=confirmado`, `data` preservada).
- **Backend prod:** `https://api.igreja12.com.br/health` → `{"status":"ok"}`;
  `openapi.json` contém `/events/{event_id}`, `/events/{event_id}/confirm`,
  `recorrencia`, `a_confirmar`, `confirmado_por` (prova EVT-2..5).
- **Frontend prod:** deployment `dpl_66e4fhmGyg9cp8zBAFaP9KP33Rj6` READY;
  `https://app.igreja12.com.br` HTTP 200; bundle (`app/page-*.js`) contém
  `"A confirmar"` e aponta `https://api.igreja12.com.br`; **sem** ref de dev.
- **DEV smoke (pré-promoção):** smoke autenticado completo no `27f7e7d` contra o
  Supabase dev (login→criar→semear `a_confirmar`→confirmar→sai da fila→cleanup,
  `events=0`), sem envio real.

## Pendente / próximo passo
- **Smoke funcional em produção** com usuário Clerk de **produção**, ciente do risco
  de órfão no Google (ver `docs/ops/PROD-ENV-RUNBOOK.md` §8). Qualquer dado de teste
  removido, voltando ao baseline.
- **Pós-MVP:** EVT-6 (import Google → fila "a confirmar", exige corrigir o token
  por-igreja desconectado do push) e EVT-7 (lembrete/planejamento — worker + envio).
