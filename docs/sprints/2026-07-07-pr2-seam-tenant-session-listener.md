# PR2 — Seam profundo `tenant_session.py` + listener `after_begin` (aditivo) — 2026-07-07

**Branch:** (a criar pelo dono; trabalho feito sobre `main`)  ·  **Commits:** (pendente — dono commita)  ·  **Deploy:** não (seam disponibilizado, ainda não plugado em routers/worker de produção)

## O que foi feito
PR **aditivo e coexistente**: cria o seam único que concentra `GUC + SET LOCAL ROLE + reasserção pós-commit + pinning + saída cross-tenant nomeada` (D1/D2/D3/D4) e o registra via listener `after_begin`. **Nenhum código legado removido** — `ensure_tenant_context`/`set_tenant_context*` seguem intactos e o seam coexiste com eles.

- **`backend/app/db/tenant_session.py`** (novo — o seam):
  - Chaves de `session.info`: `TENANT_IGREJA_KEY='tenant_igreja_id'`, `TENANT_META_KEY='tenant_meta'`, `CROSS_TENANT_KEY='cross_tenant'`.
  - Hierarquia de exceções nomeada, fail-closed: `TenantScopeError(RuntimeError)` base → `TenantPinConflictError`, `TenantPromotionError`.
  - `mark_tenant_scoped(session, igreja_id, *, actor_sub, actor_role, source)` — valida (rejeita vazio/None), **pina** o tenant em `session.info` (D1/D3); conflita se já cross-tenant ou pinado em outra igreja; idempotente no mesmo tenant (preserva meta original); aplica o escopo **na transação atual** chamando `set_tenant_context_for_igreja`.
  - `mark_cross_tenant(session, *, actor_sub, source)` — marca sessão unscoped nomeada (D4); conflita se já pinada; **não** aplica escopo.
  - `promote_to_tenant(session, igreja_id, *, source)` — transição válida **só** a partir de cross-tenant; `TenantPromotionError` se já pinada/nunca cross.
  - `_reapply_tenant_scope(session, transaction, connection)` — o listener `after_begin`: **no-op** se `session.info` não tem a chave do tenant; senão reaplica GUC + role via `connection.exec_driver_sql` (evita reentrância vs `session.execute`), com `igreja_id` como **parâmetro de bind** (anti-injeção) e só formas transaction-local (`set_config(..., true)` / `SET LOCAL ROLE authenticated`) — semanticamente idêntico ao `set_tenant_context_for_igreja`.
  - `register_after_begin_listener(target=Session)` — idempotente via `event.contains` antes de `event.listen`.
- **`backend/app/db/session.py`** (modificado — só o registro): ao importar o módulo do pool, `register_after_begin_listener()` roda uma vez. Para sessões **não-marcadas** o listener é no-op ⇒ zero mudança de comportamento nos caminhos legados.
- **`backend/tests/test_tenant_session_unit.py`** (novo — 18 testes, offline, sem DB): contrato de `session.info`, coerção de id, idempotência mesmo-tenant, conflito outra-igreja, rejeição de vazio/None, exclusão mútua scoped×cross, promoção válida/inválida, hierarquia de exceções, listener no-op quando não-marcado e reaplicação quando marcado (assert do bind `(IGREJA_A,)`, `is_local` true, `SET LOCAL`).
- **`backend/tests/conftest_rls.py`** (modificado — seed): `CLERK_A`/`CLERK_B` + linhas em `app_users` mapeando cada clerk_sub↔igreja, para provar o caminho HTTP (claim Clerk) coexistindo com o GUC.
- **`backend/tests/test_rls_invariant.py`** (modificado — ativa T3/T5-seam/T6-seam + coexistência): modelo ORM local `_Pessoa`; `test_t3_seam_reopens_scope_after_commit` (marca A, lê, commit, nova query segue escopada A via listener — o valor do D2); `test_t5_seam_no_role_guc_leak_via_pool` (pool `pool_size=1`; sessão marcada fecha, sessão nova não-marcada reusa a conexão e **não** vaza role/GUC); `test_t6_seam_listener_fail_closed` (renomeia role `authenticated` → listener falha com `DBAPIError`, restaura no finally); `test_seam_http_readonly_path_coexists` e `test_seam_worker_readonly_path_coexists` (seam + legado no mesmo tenant, sem conflito). T4 segue skip (aguarda PR3-B).

## Decisões
- **Aplicar já vs listener**: `mark_*` aplica o escopo na transação **corrente** (o `after_begin` dela já disparou); o listener cuida das transações **futuras** (reasserção pós-commit = D2/T3).
- **`exec_driver_sql` no listener**: usar a `connection` em vez de `session.execute` evita reentrância no ciclo de eventos da sessão.
- **SQL "byte-fiel"**: única diferença vs `set_tenant_context_for_igreja` é o placeholder de bind (`%s` do driver vs `:name` do SQLAlchemy) — nome do GUC, função, flag `is_local`, `SET LOCAL ROLE` idênticos, ambos parametrizados.
- **Coexistência sem tocar produção**: routers/worker usam fakes de sessão (`FakeSession`/`FakeIngestSession`) **sem `.info`** — plugar `mark_tenant_scoped` neles quebraria a suíte. Por isso o seam é **provado por testes de integração** (sessões reais têm `.info`) que espelham os caminhos HTTP e worker, sem alterar runtime.
- **Fail-closed**: exceções propagam; nunca há `try/except` que siga em BYPASSRLS.

## Pendente / próximo passo
- **PR3**: plugar o seam num caminho HTTP real (deps/router) e no worker (ativa T4), aposentando gradualmente `ensure_tenant_context` sem big-bang.
- Depois: fiar `probe_tenant_scope`/`log_if_not_scoped` (PR1) num caminho de amostra.
- Dono: criar branch + revisar `git diff` + commitar (não commitado aqui por política).

## Verificação
- `pytest tests/test_tenant_session_unit.py tests/test_rls_invariant.py` → **18 passed, 11 skipped** (skips = integração RLS sem `RLS_TEST_DATABASE_URL` + T4).
- **Suíte completa**: `python -m pytest` → **1029 passed, 11 skipped, 0 falhas** (exit 0). Só os RLS integration pulam; import de `app.db.session` registrando o listener não introduz regressão.
- `git status`: aditivo — novo `tenant_session.py` + `test_tenant_session_unit.py`; modificados `session.py` (só o registro do listener), `conftest_rls.py` (seed app_users) e `test_rls_invariant.py` (ativa T3/T5-seam/T6-seam + coexistência). Nenhum router/worker de produção tocado.
