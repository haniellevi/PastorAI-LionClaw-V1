# Revalidação dos findings BAIXO-001..010 — Seg-Igreja12 (M7 SEC-BAIXO-REVAL)

- **Data:** 2026-07-18
- **Base de código:** `origin/main` @ `ceef64d` (contém `b5b990d`/PR#188 e `fd651f9`/PR#186)
- **Plano de origem:** `docs/security/2026-07-08-seg-igreja12-remediation-plan.md` (§2.3) — os 10 BAIXO nunca haviam sido revalidados desde 2026-07-08.
- **Tipo:** docs-only. Nenhum código de aplicação alterado. Cada veredito abaixo foi reproduzido por leitura/grep no código **atual** do worktree, com `file:line` do estado de hoje — nunca por memória ou mensagem de commit isoladamente.

Legenda de veredito: **(a) corrigido** — o problema descrito não existe mais no código atual, com PR/release identificado · **(b) ainda válido** — reproduzido no código atual como descrito · **(c) obsoleto/superado** — a arquitetura mudou e o finding não se aplica mais na forma original · **(d) não comprovável sem ambiente** — exige runtime/infra para provar.

---

## 1. Tabela-resumo

| ID | Veredito | Evidência (file:line atual) | Destino |
|----|----------|------------------------------|---------|
| BAIXO-001 | **(a) corrigido** — PR#129 (SEC-1), endurecido em `699d328`; deployado 2026-07-09 (`a7a04c8`) | `backend/app/config.py:248-258` (`effective_session_secret` sem fallback em produção), `:294-306` (`assert_production_ready` exige `SESSION_JWT_SECRET` >=32 chars e != `CLERK_SECRET_KEY`) | Fechado. Nenhuma ação |
| BAIXO-002 | **(b) ainda válido** | `backend/migrations/` — 22 ocorrências de `ENABLE ROW LEVEL SECURITY`, **zero** `FORCE` (ex.: `0003_rls_policies.sql:55,72`) | **Gate SEC-5 registrado** (§3). Não executar nesta rodada |
| BAIXO-003 | **(b) ainda válido** | `backend/app/services/clerk.py:143-149`, `:301-306`, `:326-331`, `:352-357` — 4 montagens idênticas de headers + `httpx.Client` | **Ficha candidata F1** (§2.1) — PR pequeno, sem migration |
| BAIXO-004 | **(a) corrigido** — commit `90f77b5`, PR#156 (`dca7039`); deployado via `82e1c6f` (doc de release 2026-07-16) | `backend/app/routers/events.py:323` (`with_for_update` em `_get_event`), `:579` (`confirm_event` carrega com `for_update=True` na mesma transação da validação) | Fechado. Nenhuma ação |
| BAIXO-005 | **(a) corrigido** — commit `eb5d637`, PR#144 (mesmo commit do ALTO-005); deployado via `8cbf78f` (doc de release 2026-07-11) | `backend/app/routers/subscription.py:170-241` — `reserve_agent_event` (INSERT+commit) **antes** do `send_text`; `release_agent_event` em falha total; leituras todas antes da reserva (gap-2) | Fechado. Nenhuma ação |
| BAIXO-006 | **(b) ainda válido** | `backend/app/routers/events.py:345` — `total = len(db.execute(select(Event.id)).scalars().all())` materializa todos os IDs do tenant para contar | **Ficha candidata F2** (§2.2) — PR pequeno, sem migration |
| BAIXO-007 | **(b) ainda válido** (piorou) | `backend/app/routers/platform_admin.py` — **1777 linhas** hoje (era ~1754 em 2026-07-08) | Pós-MVP (refactor estrutural SEC-7c). Não bloqueia nada |
| BAIXO-008 | **(b) ainda válido** | 20+ arquivos >500 linhas hoje; maiores: `backend/app/routers/cell_meetings.py` (1628), `frontend/src/components/dashboard/DashboardScreen.tsx` (890), `frontend/src/components/admin/ChurchPage.tsx` (849), `backend/app/routers/cells.py` (815) | Pós-MVP (SEC-7c). Não bloqueia nada |
| BAIXO-009 | **(b) ainda válido** (piorou) | `backend/app/db/models.py` — **1736 linhas** hoje (era ~1562) | Aceitar risco (o próprio plano marcou como opcional). Pós-MVP se incomodar |
| BAIXO-010 | **(b) ainda válido, parcialmente mitigado** | `frontend/src/lib/auth-context.tsx:92-122` — token em cookie **não-HttpOnly** (necessário: cliente lê para o header `Authorization`, compartilhado entre `app.`/`admin.` via domínio-pai) com `max-age=28800` (8h) + `localStorage` como fallback (`:118-119`); `frontend/src/lib/admin-auth-context.tsx:42-51` idem | Pós-MVP (SEC-6). Mitigações já ativas reduzem o impacto (§2.3) |

Placar: **3 corrigidos** (001, 004, 005) · **7 ainda válidos** (002, 003, 006, 007, 008, 009, 010) · 0 obsoletos · 0 não-comprováveis.

Nota sobre (d): nenhum item caiu em "não comprovável sem ambiente". O único com componente de ambiente é o BAIXO-002 — o código prova a **ausência** do `FORCE` nas migrations versionadas, mas o estado efetivo das tabelas em PROD/DEV só seria comprovável com query read-only no banco (`pg_class.relforcerowsecurity`); isso não muda o veredito (a migration não existe), apenas seria pré-requisito do gate SEC-5.

---

## 2. Fichas de missão candidatas (pequenas, sem migration)

Somente os "ainda válidos" pequenos ganham ficha. BAIXO-007/008/009 são refactors estruturais grandes (destino pós-MVP) e BAIXO-010 é mudança de arquitetura de sessão (SEC-6, pós-MVP) — sem ficha.

### 2.1 Ficha F1 — BAIXO-003: helper único do HTTP client Clerk

- **Escopo:** extrair um helper privado (ex.: `_api_request(method, path, json)` ou `_auth_headers()` + context manager) em `ClerkClient`, usado por `authenticate_password`, `find_user_id_by_email`, `set_user_password` e `create_user`. Zero mudança de contrato público, zero mudança de comportamento HTTP (mesma base URL, timeout 10s, headers).
- **Arquivos:** `backend/app/services/clerk.py` (único arquivo de código); testes existentes em `backend/tests/` que mockam `httpx` continuam passando.
- **Critérios de aceite:** (1) uma única montagem de headers/cliente no módulo; (2) `pytest` completo verde; (3) diff sem mudança de assinatura pública nem de mensagem de erro; (4) sem migration, sem mudança de env.
- **Tamanho estimado:** ~30 linhas movidas. 1 PR isolado (SEC-7a).

### 2.2 Ficha F2 — BAIXO-006: contagem no banco em `list_events`

- **Escopo:** substituir `total = len(db.execute(select(Event.id)).scalars().all())` por `select(func.count()).select_from(Event)` (mesma sessão, mesma RLS de tenant). Comportamento observável idêntico (mesmo `total`).
- **Arquivos:** `backend/app/routers/events.py` (linha 345).
- **Critérios de aceite:** (1) `total` idêntico ao anterior nos testes de listagem existentes; (2) nenhum ID materializado (query única de `count`); (3) `pytest` completo verde; (4) sem migration.
- **Tamanho estimado:** ~2 linhas. 1 PR isolado (SEC-7b) — pode ir junto com F1 se preferirem 1 PR só, mas o plano de 08/07 recomenda PRs separados por sub-bucket.

---

## 3. Gate SEC-5 (BAIXO-002 — FORCE ROW LEVEL SECURITY)

Registro do gate, **sem proposta de execução nesta rodada** (regra da missão M7):

1. Pré-condição já satisfeita: C1/RLS seam fechado e em produção (Missão 6).
2. Antes de qualquer migration `ALTER TABLE ... FORCE ROW LEVEL SECURITY`: validar em **DEV** que os fluxos legítimos cross-tenant (worker, `platform_admin`) usam `mark_cross_tenant`/service role e que nenhuma query legítima passa a retornar vazio.
3. Só depois aplicar em **PROD**, com rollback documentado (`NO FORCE`).
4. Riscos e rollback detalhados no plano de 08/07, §4 e §5 (linha SEC-5).

---

## 4. Método

- Worktree limpo em `origin/main` @ `ceef64d`; cada finding reproduzido por grep/leitura direta (evidências `file:line` na tabela §1).
- Correções foram atribuídas a PR/release apenas quando (a) o código atual mostra o fix e (b) o commit é ancestral de um release com doc versionado em `docs/sprints/` (`82e1c6f`, `8cbf78f`, `a7a04c8`).
- Contagens de linhas via `wc -l` no worktree; contagem de `ENABLE`/`FORCE` via grep em `backend/migrations/`.
