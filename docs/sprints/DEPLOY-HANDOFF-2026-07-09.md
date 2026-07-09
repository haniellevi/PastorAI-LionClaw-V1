# Deploy handoff — backend `a7a04c8` — 2026-07-09

Handoff de deploy manual do backend em produção. **Deploy de backend + queue-worker executado e
validado em PROD** (registro abaixo) — feito pelo responsável, não por mim (sem SSH). Preparo local
feito inteiramente em `PastorAi-1.0-main-clean` (worktree local, validado). Ver também
`docs/sprints/PLANO-PRODUCAO-LIMPA-2026-07-09.md` (contexto completo) e
`docs/sprints/SNAPSHOT-RAIZ-SUJA-2026-07-09.md` (raiz suja, não tocada).

**Status final: `DEPLOY_PROD_BACKEND_AND_QUEUE_WORKER_PASS`.**

## Base / SHA

- Branch: `main` (worktree `main-clean` em detached HEAD)
- SHA alvo: **`a7a04c8`**
- `origin/main`: `a7a04c8` — idêntico, confirmado agora (`git status --short` limpo)
- Produção **NÃO tocada** nesta tarefa — SSH, `docker compose`, `.env`, migration em Supabase PROD: nenhum executado.

## Validações locais (feitas, ver seção 6b do PLANO)

- Backend: `.venv` provisionado, `pip install -r requirements.txt` sem conflito, `pytest -q` exit code 0
  (zero falha/erro; 13 skipped esperados).
- Frontend: `npm ci`, `npm run typecheck`, `npm run lint`, `npm run build` — todos exit code 0.

## Tarball gerado

- Caminho: `C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0-main-clean\pastorai-backend-a7a04c8-20260709.tar`
- Tamanho: 2.160.128 bytes (~2,1 MB)
- **SHA256: `35CA25D2B2BEC4EE12015CAA728308C28D95F4D60A88F887D1DF97DE1E39FD38`**
- Conteúdo: 235 arquivos, confirmado **sem** `.venv`, `__pycache__`, `.pytest_cache`, `.env` (só
  `.env.example`/`.env.staging.example`, sem segredo real).
- Gerado com `tar -cf ... backend` a partir do `main-clean` em `a7a04c8` (não da raiz suja).

## Migrations em `backend/migrations` — candidatas a conferência PROD

**Não afirmo status de aplicação em PROD sem prova direta** (query read-only no projeto
`pffafnchtxbimpwyaczq`) — só o Supabase MCP/SQL Editor de PROD confirma isso. Classificação:

### Históricas `0001`–`0017` — congeladas, fora de escopo desta rodada
Numeração antiga, aplicadas há muito tempo conforme convenção do projeto (`backend/migrations/README.md`).
Não recontroladas aqui.

### Timestampadas anteriores a este lote (features já concluídas em missões passadas) — exigem conferência
```
20260623_103319_pessoa_sem_interesse_csim.sql
20260623_122044_calendar_sync_oauth_por_igreja.sql
20260623_154500_pessoa_tipo_add_contato.sql
20260623_170000_igreja_dono_assinatura.sql
20260624_003030_current_igreja_id_guc_worker.sql
20260624_090102_current_igreja_id_guard_empty_claims.sql
20260624_171110_agent_config_requests_fila_requisicao_admin_master.sql
20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql
20260701_014654_evt6_google_event_dedup_index.sql
20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql
20260701_193000_evt7_pr2_agenda_alert_recipients.sql
20260703_123803_celula_schema_base_pr1.sql
20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql
20260705_120000_celula_pr3_reuniao_relatorio_campos.sql
20260705_120100_celula_pr3_reuniao_registro.sql
20260705_120200_celula_pr3_visitante.sql
20260705_120300_celula_pr3_solicitacao_evento.sql
20260705_120400_celula_pr3_aviso.sql
20260705_120500_celula_pr3_material.sql
20260705_120600_celula_pr3_multiplicacoes_evolucao.sql
20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql
20260706_230000_evt8_pr1_notify_config.sql
20260707_011455_igreja_logo_branding.sql
```
**Exige conferência no Supabase PROD** — cada uma, antes de qualquer nova aplicação.

### Lote mais recente (candidato direto ao "deploy acumulado" desta rodada) — **APLICADAS EM PROD, confirmado por conferência read-only** (ver seção seguinte)
```
20260708_160128_sec3a_app_users_password_changed_at.sql
20260708_164756_backfill_celula_membro_canonico.sql
20260708_172106_sec3b_password_reset_tokens_single_use.sql
20260708_221808_igreja_dono_id_grant_update.sql
```
As 4 foram aplicadas em PROD pelo responsável e confirmadas via query read-only rodada por ele mesmo no
Supabase SQL Editor de `pffafnchtxbimpwyaczq` (prints colados no chat) — não fui eu quem rodou, mas é
prova direta (resultado de query), não só relato verbal. Detalhe por migration na seção "Conferência PROD
read-only" abaixo.

### Achado à parte — NÃO fazem parte deste conjunto
3 migrations soltas, **não commitadas em nenhum branch**, vistas só na raiz suja (`PastorAi-1.0`, não
`main-clean`): `20260707_180000_app_user_password_changed_at.sql`,
`20260707_190000_agent_event_idempotency_marker_uidx.sql`, `20260707_200000_force_rls_tenant_tables.sql`.
Confirmado agora: **não existem** em `backend/migrations` do `main-clean`/`main` — são rascunho anterior
(provavelmente superado pelas versões `sec3a`/`sec3b` acima, com nomes diferentes) ou trabalho ainda não
formalizado. Não fazem parte deste tarball nem deste handoff.

## Conferência PROD read-only — **PROD_SCHEMA_CONFIRMED_READ_ONLY**

Queries rodadas pelo responsável no SQL Editor de `pffafnchtxbimpwyaczq` (não por mim — sem acesso a
PROD). Resultado colado no chat (prints), transcrito abaixo. Nenhuma migration foi aplicada por mim,
nenhuma conexão feita por mim — só recebi e registrei o resultado.

### 1/4 — `20260708_160128_sec3a_app_users_password_changed_at.sql` — **APLICADA, confirmado**
```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name = 'app_users'
  and column_name = 'password_changed_at';
```
Resultado: `password_changed_at` | `timestamp with time zone` | `is_nullable = YES`. Bate exato com o
esperado pela migration.

### 2/4 — `20260708_172106_sec3b_password_reset_tokens_single_use.sql` — **APLICADA, confirmado**
```sql
select column_name, data_type, is_nullable
from information_schema.columns
where table_schema = 'public' and table_name = 'password_reset_tokens'
order by ordinal_position;

select indexname, indexdef
from pg_indexes
where schemaname = 'public' and tablename = 'password_reset_tokens';

select conname, contype
from pg_constraint
where conrelid = 'public.password_reset_tokens'::regclass;
```
Resultado — colunas confirmadas: `id uuid not null`, `jti uuid not null`, `clerk_user_id text not null`,
`expires_at timestamptz not null`, `used_at timestamptz` (nullable), `created_at timestamptz not null`.
Índices confirmados: `idx_password_reset_tokens_clerk_user_id`, `idx_password_reset_tokens_expires_at`,
`password_reset_tokens_jti_key` (unique), `password_reset_tokens_pkey`. Estrutura completa bate com a
migration.

### 3/4 — `20260708_221808_igreja_dono_id_grant_update.sql` — **APLICADA, confirmado**
```sql
select grantee, table_name, column_name, privilege_type
from information_schema.role_column_grants
where table_schema = 'public'
  and table_name = 'igrejas'
  and column_name = 'dono_id';
```
Resultado: `authenticated` | `igrejas` | `dono_id` | `UPDATE` presente (junto com `postgres`/`anon`/
`service_role`, herdados do grant default de schema do Supabase — não específicos desta migration, só o
`authenticated`/`UPDATE` é o que essa migration garante). GRANT confirmado aplicado.

### 4/4 — `20260708_164756_backfill_celula_membro_canonico.sql` (PR-A2, #134) — **APLICADA e COMPLETA, confirmado**
```sql
-- Query 1: divergências entre pessoas.celula_id e o vínculo ativo
select count(*) as divergencias
from pessoas p
join celula_membro cm on cm.pessoa_id = p.id and cm.igreja_id = p.igreja_id and cm.ativo = true
where p.celula_id is not null and cm.celula_id <> p.celula_id;

-- Query 2: duplicata de vínculo ativo (violaria o índice único parcial)
select pessoa_id, igreja_id, count(*) as ativos
from celula_membro
where ativo = true
group by pessoa_id, igreja_id
having count(*) > 1;

-- Query 3: pessoas com celula_id no espelho mas sem NENHUMA linha canônica ainda
select count(*) as pessoas_sem_vinculo_canonico
from pessoas p
where p.celula_id is not null
  and not exists (
    select 1 from celula_membro cm
    where cm.pessoa_id = p.id and cm.celula_id = p.celula_id and cm.igreja_id = p.igreja_id
  );
```
Resultado: Query 1 (divergências) = **0**. Query 2 (duplicatas ativas) = **0 rows**. Query 3 (lacuna de
backfill) = **0**. As 3 confirmam: backfill aplicado, sem divergência, sem duplicata, sem lacuna.

**Status desta seção: PROD_SCHEMA_CONFIRMED_READ_ONLY** — schema de PROD confirmado por query real pras
4 migrations do lote. Nenhum deploy, nenhuma migration nova, nenhum commit feito.

## Ordem humana recomendada (comandos exatos)

1. ✅ **FEITO** (pelo responsável) — Confirmar alvo Supabase PROD: `pffafnchtxbimpwyaczq` (Pastor-Ai-LionClaw-v1, us-west-2).
2. ✅ **FEITO** (pelo responsável) — Rodadas as 4 conferências da seção "Conferência PROD read-only" —
   **PROD_SCHEMA_CONFIRMED_READ_ONLY**, as 4 migrations do lote já aplicadas.
3. ✅ **N/A** — Nada pendente pra aplicar neste lote (as 4 já confirmadas aplicadas no passo 2).
4. ✅ **FEITO** — Tarball copiado pra VPS (`/opt/pastorai-lionclaw`). Hash conferido na VPS via
   `sha256sum` — bateu com `35ca25d2b2bec4ee12015caa728308c28d95f4d60a88f887d1df97de1e39fd38`.
5. ✅ **FEITO** — Backup do backend atual: `/root/pastorai-backups/backend-before-a7a04c8-20260709.tar.gz`.
6. ✅ **FEITO** — Backend substituído pelo conteúdo do tarball, `Dockerfile`/`.dockerignore` remotos
   preservados (não sobrescritos).
7. ✅ **FEITO** — Rebuild do serviço `backend`:
   ```bash
   docker compose up -d --build --no-deps backend
   ```
   Resultado: build finalizado com sucesso, container `pastorai_backend` started.
8. ✅ **FEITO** — `docker compose ps`: `backend` Up/healthy (`pastorai-backend:latest`).
9. ⚠️ **AJUSTADO** — `curl http://localhost:8000/health` no host **falhou** (porta não publicada no
   host — comportamento esperado desta topologia, não é erro do deploy). Validação real feita **dentro**
   do container:
   ```bash
   docker compose exec -T backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).read().decode())"
   ```
   Resultado: `{"status":"ok"}`.
10. ✅ **FEITO** — Validar público:
    ```bash
    curl -s https://api.igreja12.com.br/health
    ```
    Resultado: `{"status":"ok"}`.

## Nota técnica — escopo real deste deploy

O deploy autorizado neste runbook (passo 7) é **somente** `backend`:
```bash
docker compose up -d --build --no-deps backend
```
Isso atualiza **só os caminhos HTTP/API** (rotas do FastAPI). `pastorai_queue_worker` e
`pastorai_cron_worker` continuam rodando a imagem/código anterior, intocados.

**Ressalva**: o caminho `vincular_celula` (fix do PR-A2, `agent/tools.py`) roda **dentro do**
`pastorai_queue_worker` (processamento assíncrono do WhatsApp/agente) — **não** dentro do `backend` HTTP.
Depois deste deploy, `vincular_celula` **continua com código antigo** até um deploy/restart controlado
do worker, separado.

**Consequência prática**: os outros 3 write-sites do PR-A2 (`auth.py`, `contacts.py`, `team.py` —
rodam no `backend`) passam a gravar em `celula_membro` corretamente assim que este deploy sair. O 4º
write-site (`agent/tools.py::vincular_celula`, worker) só corrige depois do gate abaixo.

## Gate separado — "Deploy controlado de workers" — **EXECUTADO**

Aberto e executado depois de validar o backend (passos 8-10 acima confirmados PASS).

1. ✅ **Verificado** estado dos workers antes do restart: logs mostravam `queue-worker` só com start
   antigo (nenhuma atividade recente registrada); `cron-worker` rodando ticks normais a cada 5 min
   (`sla=0, crons=0` — sem trabalho pendente no momento). Fila Redis checada:
   ```bash
   docker compose exec -T redis redis-cli LLEN pastorai:webhooks
   ```
   Resultado: **0** (fila vazia, sem mensagem em trânsito).
2. ✅ **Risco de envio externo avaliado**: fila vazia (item 1) = sem mensagem WhatsApp em processamento
   no momento do restart, risco mínimo.
3. ✅ **Backup/estado antes**: coberto pelo mesmo backup do passo 5 (backend e worker compartilham a
   mesma imagem `pastorai-backend:latest`).
4. ✅ **Decisão**: reiniciar **somente** `queue-worker` — é o único caminho que roda `vincular_celula`
   (fix do PR-A2, `agent/tools.py`). `cron-worker` não importa esse módulo, ficou **fora de escopo**,
   propositalmente **não reiniciado**.
   ```bash
   docker compose up -d --no-deps --force-recreate queue-worker
   ```
   Resultado: `pastorai_queue_worker` started.
5. ✅ **Validado** depois: log pós-recreate mostrou `Queue worker started, consuming pastorai:webhooks`
   (worker novo assumiu a fila corretamente). Health público reconferido pós-worker:
   `curl -s https://api.igreja12.com.br/health` → `{"status":"ok"}`.

`docker compose ps` final: `backend` (`pastorai-backend:latest`, Up/healthy) · `queue-worker`
(`pastorai-backend:latest`, recriado agora) · `cron-worker` (**não reiniciado**, permaneceu Up 19h,
rodando o código anterior — decisão deliberada, fora de escopo deste gate).

## Rollback básico

Se o health check falhar ou o smoke funcional pegar regressão:
```bash
cd /opt/pastorai-lionclaw
tar -xzf /root/pastorai-backups/backend-before-a7a04c8-<timestamp>.tar.gz -C /opt/pastorai-lionclaw/
cd /opt/pastorai-lionclaw/deploy
docker compose up -d --build --no-deps backend
```
`queue-worker` compartilha a mesma imagem `pastorai-backend:latest` do `backend` — o mesmo rollback do
backend, seguido de `docker compose up -d --no-deps --force-recreate queue-worker`, reverte os dois.
`cron-worker` não foi tocado, não precisa de rollback.

Migration: se alguma das aplicadas no passo 3 precisar reverter, não há rollback automático (migrations
deste projeto não têm `down`) — reversão é manual, avaliando cada `ALTER`/`CREATE` aplicado.

## Pós-deploy monitorado — **PASS**

Executado depois do gate de workers, confirma estabilidade do deploy:

```bash
docker compose logs --tail=80 backend
```
Resultado: só healthchecks `GET /health 200 OK`, sem erro.

```bash
docker compose logs --tail=80 queue-worker
```
Resultado: `Queue worker started, consuming pastorai:webhooks`, sem erro.

```bash
docker compose ps
```
Resultado: `backend` (`pastorai-backend:latest`, Up/healthy) · `queue-worker`
(`pastorai-backend:latest`, Up) · `cron-worker` (**preservado, não reiniciado**) · `redis` (healthy) ·
`caddy` (ativo).

```bash
curl -s https://api.igreja12.com.br/health
```
Resultado: `{"status":"ok"}`.

**Status desta seção: PASS.** Produção estável após o deploy + gate de workers.

## Limpeza local pós-deploy — **CONCLUÍDA**

Executada depois do pós-deploy monitorado, separada do deploy em si:

- Todos os worktrees órfãos/mergeados removidos. `git worktree list` final: só
  `C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0` em `main`.
- Raiz principal voltou pra `main`, `git status --short --branch` final: `## main...origin/main`, sem
  arquivos modificados. HEAD final: `a7a04c8` = `origin/main`.
- **Estado sujo preservado antes de limpar**: branch local `backup/raiz-suja-2026-07-09`, commit
  `d0b5053` ("backup: preserva estado sujo da raiz em 2026-07-09") — inclui todo o conteúdo descrito em
  `SNAPSHOT-RAIZ-SUJA-2026-07-09.md` (pacotes de routers, achado de segurança solto, refactor frontend,
  ferramental local, e os próprios 3 docs operacionais desta rodada, que tinham ficado como arquivo não
  commitado na raiz). **Não deletar essa branch ainda.**
- Branches locais já mergeadas em `origin/main` removidas. Preservadas (não mergeadas/duvidosas):
  `backup/raiz-suja-2026-07-09`, `feat/c1-rls-seam-integration`, `fix/igreja-dono-id-grant`,
  `claude/church-setup-checklist-0bcde9`, `claude/csim-ai-pause-inbox-order-049524`,
  `claude/trusting-kalam-a4869c`, `codex/antigravity-clean-main`, `docs/celulas-multiplicacao-spec`,
  `docs/infografico-onboarding-igreja`, `feat/agenda-evt8b-confirm-modal`,
  `wip/antigravity-resgate-2026-07-06`.

Verificado por mim via `git worktree list`/`git status`/`git branch -a` na raiz — bate exato com o
relatado.

⚠️ **Nota own-worktree**: minha própria sessão roda de dentro de
`PastorAi-1.0\.claude\worktrees\charming-sammet-71a75b`, que também foi varrido nesta limpeza — a pasta
ainda existe fisicamente (sessão com shell aberto ali), mas não é mais um worktree git registrado;
comandos git de dentro dela agora resolvem pro repo raiz em `main`, não mais pro branch
`feat/c1-rls-seam-integration`. Não fiz nenhuma escrita git nesta sessão além dos `git show`/`status`
read-only usados pra recuperar estes 2 arquivos — mas isso é relevante pra qualquer ação de commit
futura nesta conversa.

## Itens não executados (deliberadamente, fora de escopo desta rodada)

- `pastorai_cron_worker` **não foi reiniciado** — não importa `agent/tools.py`, fica com código anterior.
- Frontend **não foi redeployado**.
- **Nenhuma migration nova** aplicada nesta rodada (as 4 já estavam confirmadas antes, ver seção de
  conferência acima).
- **Nenhum commit** feito.
- Destino final dos arquivos preservados em `backup/raiz-suja-2026-07-09` — branch mantida, decisão
  pendente (descartar vs. formalizar em PR).

## Resultado operacional

Backend HTTP/API atualizado em produção. `queue-worker` atualizado de forma controlada (gate próprio,
fila vazia confirmada antes do restart). `cron-worker` preservado, deliberadamente fora de escopo.
Produção saudável — health público `{"status":"ok"}` antes e depois do restart do worker, e reconfirmado
no pós-deploy monitorado. Worktrees órfãos limpos, raiz local de volta a `main` limpo, estado sujo
anterior preservado em branch de backup.

## Smoke funcional autenticado em PROD — **SMOKE_PROD_READ_ONLY_PASS**

Executado (ver `docs/sprints/SMOKE-PROD-PLAN-2026-07-09.md` pra detalhe completo). Bloco A (admin) e
Bloco C (líder), ambos só read-only, via sessão PROD ativa no browser conectado — nunca digitei
credencial. Zero escrita, zero efeito externo disparado.

- **Bloco A (admin)**: login, dashboard, Pessoas (10), Central de Célula (1 ativa/saudável), Equipe (5
  usuários), Assinatura (Plano Célula R$199/mês), Agenda (eventos reais) — tudo PASS, zero 4xx/5xx, zero
  erro de console.
- **Bloco C (líder)**: badge "Líder G12"/"Líder de Célula", "Minha Célula" abriu, **4 discípulos ativos**
  (Raniel Lider Celula, Whatsapp Filadelfia Corrente, Pastor Raniel, Raniel Levi – Mkt Digital) — tudo
  PASS, zero 4xx/5xx, zero erro de console.
- **Prova cruzada do PR-A2**: os mesmos 4 nomes que o admin viu com `célula = Celula 1` na lista de
  Pessoas são os mesmos 4 que o líder viu como discípulos ativos em "Minha Célula" (leitura via
  `celula_membro`) — confirma o fix ponta-a-ponta em produção sem precisar criar dado novo.
- **Bloco B não executado**: decisão explícita — a prova cruzada A×C já bastou.
- Blocos com efeito externo (D parcialmente, E integralmente) seguem `DO_NOT_RUN_WITHOUT_APPROVAL`.

## Próximos itens pendentes

1. **SEC-0** — rotação manual da credencial/senha Clerk. Fora do alcance de automação, ação exclusiva do
   responsável.
2. Decidir futuramente se vale recriar `cron-worker` (hoje preservado, código anterior).
3. Decidir destino da branch local `backup/raiz-suja-2026-07-09` (`d0b5053`) — descartar ou formalizar
   parte em PR.
4. Encerrar deploy/smoke como PASS operacional (este documento é o fechamento).

## Status final

**`SMOKE_PROD_READ_ONLY_PASS`** (sobre `DEPLOY_PROD_BACKEND_AND_QUEUE_WORKER_PASS`) — tarball `a7a04c8`
(sha256 conferido na VPS) deployado em `backend` + `queue-worker` de forma controlada, com backup prévio,
`Dockerfile`/`.dockerignore` remotos preservados, health público confirmado antes e depois, pós-deploy
monitorado PASS, limpeza de worktrees/branches concluída, estado sujo preservado em
`backup/raiz-suja-2026-07-09` (não deletar). **Smoke funcional autenticado em PROD executado e PASS**
(admin + líder, só read-only, prova cruzada confirma PR-A2 funcionando ponta-a-ponta). `cron-worker`
preservado deliberadamente. Nenhuma migration nova, commit, ou efeito externo disparados em nenhuma etapa
desta rodada. Pendência humana separada: SEC-0 (rotação Clerk). Tudo executado pelo responsável (deploy)
ou por mim via browser já autenticado (smoke) — nunca toquei credencial/senha.
