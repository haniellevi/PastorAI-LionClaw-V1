# PR1 — Superfície de teste RLS + observabilidade (aditivo) — 2026-07-07

**Branch:** (a criar pelo dono; trabalho feito sobre `main`)  ·  **Commits:** (pendente — dono commita)  ·  **Deploy:** não (só teste/CI, zero runtime)

## O que foi feito
PR **estritamente aditivo**: cria a superfície única da invariante de isolamento por tenant (D5) e o sinal de observabilidade, **sem tocar nenhum runtime de produção** (deps.py/session.py/routers/workers/factory de sessão intactos).

- **Config opt-in**:
  - `backend/.env.example` — bloco novo `RLS_TEST_DATABASE_URL=` (vazio) com comentário: DEVE apontar para Postgres DESCARTÁVEL, nunca DEV/PROD; ausência ⇒ skip limpo.
  - `backend/pytest.ini` — seção `markers` com `rls_integration: testes que exigem Postgres real (RLS_TEST_DATABASE_URL)`.
- **`backend/tests/conftest_rls.py`** (nome NÃO-`conftest.py` de propósito → não auto-carrega; importado explicitamente):
  - `assert_disposable_database(url)` + `RlsProductionGuardError` — guard OBRIGATÓRIO (D5.1) que **levanta (fail, não skip)** com denylist `pffafnchtxbimpwyaczq` (PROD) / `cxmjojnocigekgcxhubi` (DEV) / `supabase.co` / `prod`.
  - Fixtures `rls_database_url` (skip limpo se env ausente), `rls_engine`, `rls_seeded` — provisiona no banco descartável: role `authenticated` NOBYPASSRLS, `current_igreja_id()` (réplica fiel da migration 20260624_090102), tabelas tenant-scoped (igrejas/app_users/pessoas), policies RLS padrão 0003, grants ao tenant e seed de 2 igrejas A/B com 1 pessoa cada.
- **`backend/app/db/rls_observability.py`** — helper read-only `probe_tenant_scope(session)` → `TenantScopeSignal(role, igreja_id, is_scoped)`. Emite UM `SELECT current_setting('role'), current_igreja_id()`; **não** faz nenhum SET/set_config, não muta a sessão, **não é plugado em produção**. Extra `log_if_not_scoped` (opcional, também read-only).
- **`backend/tests/test_rls_invariant.py`** (`@pytest.mark.rls_integration`) — T1 (sem contexto ⇒ 0 linhas; igreja inexistente ⇒ 0), T2 (isolamento A↔B simétrico), T3 skip "aguarda PR2 seam", T4 skip "aguarda PR3-B worker", T5 (probe reporta não-escopada no role de conexão), T6 (probe reporta escopada com authenticated+GUC).
- **`backend/tests/test_rls_guard.py`** — unit puro (roda sempre, offline): prova que URL DEV/PROD faz a suite FALHAR (raise), e que URL descartável passa.
- **`.github/workflows/rls-integration.yml`** — job com serviço Postgres 16 descartável, `RLS_TEST_DATABASE_URL` setada só nesse job (localhost efêmero), passo de guard reusando `assert_disposable_database`, roda `pytest -m rls_integration` com `--junitxml`, e passo final que **falha se T1-T6 não executarem** (0 coletados ou todos skip, via parse do XML).

## Decisões
- **Skip vs fail**: env ausente ⇒ skip limpo (dev/CI offline verdes); URL DEV/PROD ⇒ raise (aborta). O guard vive num só lugar (`assert_disposable_database`), reusado por fixture e CI.
- **`conftest_rls.py` (não `conftest.py`)**: evita auto-carregar a suíte de integração para todo mundo; os testes importam via `from tests.conftest_rls import ...`.
- **T5/T6 = observabilidade** completam o mapa T1-T6 do SPEC §8, então o gate do CI ("não todos skip") tem T1/T2/T5/T6 executando de fato e T3/T4 propositalmente skip.
- **`current_setting('role')`**: após `SET LOCAL ROLE authenticated` retorna `'authenticated'`; no role de conexão retorna `'none'` → base do `is_scoped`.

## Pendente / próximo passo
- **PR2**: cria o seam (factory de sessão escopada) → ativa T3.
- **PR3-B**: migra o worker para o seam → ativa T4; e depois plugar `probe_tenant_scope`/`log_if_not_scoped` num caminho de amostra real.
- Dono: criar branch + revisar `git diff` + commitar (não commitado aqui por política).

## Verificação
- `pytest tests/test_rls_invariant.py tests/test_rls_guard.py tests/test_rls_context.py` → 9 passed, 7 skipped (skips = integração sem env + T3/T4).
- **Suíte completa**: `1011 passed, 7 skipped` (só os RLS integration), zero falhas, sem warning de marker.
- YAML do workflow valida (`yaml.safe_load` OK).
- `git status`: apenas aditivo — modificados só `.env.example` e `pytest.ini`; novos arquivos de teste/CI/helper. Nenhum runtime de produção tocado.
