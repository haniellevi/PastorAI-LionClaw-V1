# PR4+ — Migrar routers restantes + destino de ensure_tenant_context — 2026-07-07

**Branch:** main (working tree; commit a cargo do dono)  ·  **Commits:** —  ·  **Deploy:** não (backend só vale após reiniciar uvicorn; sem mudança de comportamento)

## Contexto
Continuação do seam profundo de tenant (PR2/PR3-A/PR3-B). Desde o PR3-A,
`get_current_user` (deps.py) marca a sessão com `mark_tenant_scoped` e o listener
`after_begin` (app/db/tenant_session.py) reaplica o escopo em TODA transação —
inclusive leituras pós-commit. Logo, as chamadas `ensure_tenant_context(db, current_user)`
no topo dos routers viraram **redundantes**. Este PR removeu-as e decidiu o destino
final da função (OQ#3).

## O que foi feito
- **Removidas TODAS as chamadas `ensure_tenant_context(db, current_user)` dos 26 routers**
  + os respectivos imports, em lotes pequenos (≤3 routers por lote, gate por lote):
  - Alta densidade: `cell_meetings.py` (18 chamadas), `calendar.py` (10),
    `conversations.py` (9), `cell_requests.py` (8), `cells.py` (7), `cell_discipulo.py` (7).
  - Restantes: `agent.py`, `contacts.py`, `events.py`, `team.py`, `pipeline.py`,
    `church.py`, `cell_central.py`, `cell_materials.py`, `cell_notices.py`,
    `work_queue.py`, `broadcasts.py`, `whatsapp.py`, `dashboard.py`, `roles.py`,
    `subscription.py`, `reports.py`, `assistant.py`, `auth.py`, `consolidacao.py`,
    `multiplicacoes.py`.
  - Grep confirma **0 chamadas** de escopo manual redundante nos routers.
- **feat-018 — destino em `_common.py`:** `ensure_tenant_context` foi **convertido em
  SHIM DE ASSERT fail-closed** (não removido). Agora ele NÃO re-seta o GUC às cegas:
  lê `db.info[TENANT_IGREJA_KEY]` e **levanta `TenantScopeError`** se a sessão não
  estiver marcada como tenant-scoped no mesmo igreja do usuário autenticado. Nunca
  degrada para "seguir sem escopo" (`_common.py:70-100`).
- **Auditoria de `clear_tenant_context` (rls.py:68):** grep em `backend/` → **zero
  chamadores**. Documentado no docstring que ela é inócua no modelo novo (só limpa
  `request.jwt.claims`, não reverte o GUC/role) e que saídas cross-tenant deliberadas
  devem usar `mark_cross_tenant` (D4), nunca esta função.
- Docstrings de módulo de `dashboard.py` e `church.py` atualizadas (referências stale
  a `ensure_tenant_context` → seam via `get_current_user`).
- Novo teste `tests/test_common_shim.py` (3 casos) provando o contrato fail-closed do
  shim (marcado+igual → passa; não-marcado → falha; marcado em outro tenant → falha).

## Decisões
- **OQ#3 = shim de assert (não remoção).** Preferido pela SPEC para observabilidade
  contínua fail-closed: manter o símbolo dá rede de segurança a chamadores futuros
  (falha barulhenta em vez de BYPASSRLS silencioso) e documenta a arquitetura num
  lugar canônico. A garantia contínua de escopo já vive no listener do seam.
- Remoção em **lotes pequenos** (blast radius, SPEC §10): cada lote validado antes de
  avançar; coexistência idempotente garante que remover gradualmente é seguro.

## Verificação
- `py_compile` OK em todos os routers + `_common.py`/`rls.py`/`tenant_session.py`/`deps.py`.
- **Suíte offline pytest verde (EXIT=0)**, sem falhas/erros (rls_integration = skip sem
  `RLS_TEST_DATABASE_URL`); `test_common_shim.py` + `test_tenant_session_unit.py` = 21 passed.
- Grep: **0** ocorrências de `ensure_tenant_context(db, current_user)` nos routers;
  função remanescente só em `_common.py` (shim).
- ⚠️ **T1-T6 (integração RLS)** exigem Postgres descartável (`RLS_TEST_DATABASE_URL`),
  não disponível neste ambiente — rodar no job de CI dedicado (feat-CI do PR1) para
  fechar o gate de não-regressão de isolamento.

## Pendente / próximo passo
- Rodar T1-T6 no CI com Postgres descartável para confirmar isolamento pós-migração.
- Bug pré-existente não relacionado: warnings `HTTP_422_UNPROCESSABLE_ENTITY` deprecado
  (Starlette) em vários routers — limpeza futura.
