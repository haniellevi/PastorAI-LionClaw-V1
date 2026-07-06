# Células PR3 — Backend: auth + Minha Célula (Discípulo) — 2026-07-05

**Escopo:** backend-only (auth deps + router do Discípulo) · **Deploy:** não (código; sem migration/env/worker) · **Sobre:** modelo de dados de Células PR2 já em `main`

## O que foi feito

### 1. Dependências de autorização (`app/deps.py`)
- **`require_central`** — dependency nomeada que só deixa passar a Central de Células (`CENTRAL_ROLES = ["pastor"]` + `admin` implícito via `has_any_role`); demais papéis → **403**. igreja_id/papel derivam sempre do contexto Clerk autenticado, nunca do payload.
- **`resolve_actor_pessoa_id`** — resolve a `Pessoa` vinculada ao `app_user` (`AppUser.pessoa_id`), ou `None` (SEC-DEC-04). Helper standalone em `deps.py` para evitar import circular (`routers.cells` importa de `deps`).
- **`get_current_cell_for_leader`** — resolve a célula exigindo que o usuário seja seu **líder**. "É líder desta célula" deriva **de `celulas.lider_id` ligado à Pessoa do app_user** (E9/6.6), nunca de flag do cliente nem de `celula_membro.papel`. Outra célula/tenant, id malformado, célula sem líder ou liderada por outro resultam **todos no mesmo 404** (não vaza existência do recurso).

### 2. Domínio de agenda (`app/domain/cell_meetings_schedule.py`)
- **`meeting_has_passed(data, hora, now=None)`** — reusa `_now_in_sao_paulo`/`_parse_hora`; decide "passada"/"futura" no fuso **America/Sao_Paulo** (E4). Sem `hora` (ou malformada), a reunião conta como futura durante todo o dia — nunca infere ocorrência sem horário. `now` injetável para determinismo.

### 3. Router do Discípulo (`app/routers/cell_discipulo.py`, novo)
Router próprio que **reusa** os helpers de PR2 (`_find_presenca`, `_get_reuniao_or_404`, `_has_active_membership`, `RegisterExpectativaRequest`, `ESTADO_CONFIRMADA`) — sem duplicar lógica. Registrado em `main.py`. Contrato **snake_case** (conforme critérios da sprint). Projeção **minimizada server-side** (RF-05/RF-30): o discípulo nunca recebe decisões/oração/relatório da reunião nem presença/expectativa de terceiros.

- **GET `/cells/me/next-meeting`** → `{ meeting: {id, celula_id, data, hora, local, tema} }` ou `meeting: null`. "Sem célula"/"sem ocorrência futura" são estados válidos (não erro). `local` deriva de `celulas.endereco`. Soonest futura por E4.
- **GET `/cells/me/notices`** → avisos ativos que o discípulo lê: escopo `igreja` (broadcast) + `celula` só da própria célula ativa. Exclui inativos e avisos de outras células.
- **GET `/cells/me/history`** → histórico paginado (`?page&page_size`, default 20, máx 100) das reuniões **passadas** (E4). Por reunião só `data`, `tema`, `minha_presenca` (E5) e `meus_visitantes_indicados` (só do próprio membro).
- **POST/DELETE `/cell-meetings/{id}/attendance/confirm`** → confirma/reverte a **própria** presença (`estado='confirmada'`, `origem='auto'`), upsert idempotente last-write-wins. **404** sem reunião no tenant, **403** sem Pessoa/vínculo ativo (E11), **409** se a reunião já ocorreu (E4). DELETE remove a linha enquanto não ocorreu.
- **POST `/cell-meetings/{id}/visitor-expectations`** → registra expectativa nominal de visitante do próprio membro (reusa `celula_expectativa_visitante`), sempre **201**; **404** sem reunião, **422** nome inválido (borda no Pydantic), **403** sem Pessoa/vínculo ativo. Permite N registros por reunião; sem efeito externo.

### Mapeamento E5 (presença → rótulo do Discípulo)
`compareceu→participou`, `ausente→faltou`, `confirmada→confirmou`, **sem linha → `nao_confirmou`** (nunca infere falta sem `ausente` explícito).

## Verificação técnica
- **Suíte completa:** `788 passed` (pytest, ~2m38s). Novo `tests/test_cell_discipulo.py` = **47 testes** (fake-session espelhando WHERE + filtro `ativo` + ORDER BY; datas extremas 2000/2999 para determinismo do relógio real).
- Cobertura dos testes: deps (`require_central` 403/pastor/admin; `get_current_cell_for_leader` ownership + 404 para outro líder/tenant/id malformado/sem líder/sem pessoa) e os 6 endpoints (soonest futura, `meeting:null`, escopo de avisos, paginação + projeção mínima, E5, isolamento de visitantes, 404/409/403/401, idempotência, criação 201/422/404).
- `py_compile` OK nos arquivos tocados; `create_app()` registra as 6 rotas.
- **Sem ruff/mypy/CI** configurados no repo (verificado). Sem `git` de escrita.

## Não feito / pendente
- **Sem migration/env/worker/deploy** — usa o schema PR2 já aplicado em DEV/PROD.
- Frontend do Discípulo (telas) — sprint separada.
- `get_current_cell_for_leader`/`require_central` ficam disponíveis para as sprints de Líder/Central (PR4+).

## Arquivos
- `backend/app/deps.py` (+`require_central`, `resolve_actor_pessoa_id`, `get_current_cell_for_leader`, `CENTRAL_ROLES`)
- `backend/app/domain/cell_meetings_schedule.py` (+`meeting_has_passed`)
- `backend/app/routers/cell_discipulo.py` (novo)
- `backend/app/main.py` (registro do router)
- `backend/tests/test_cell_discipulo.py` (novo)
