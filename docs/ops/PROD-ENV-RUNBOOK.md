# PROD/DEV — Runbook operacional (ambientes, deploy, comandos)

Estado operacional **real** dos ambientes do PastorAI / Igreja 12 e o processo de
deploy de cada camada, como executado na promoção da **Agenda MVP (EVT-1..5)** em
2026-06-30. Documento operacional — **não contém segredos** (sem connection
strings, tokens ou chaves; só refs de projeto, hosts e domínios públicos).

> Regra de ouro: **produção `pffafnchtxbimpwyaczq` nunca é tocada sem prova do
> alvo + autorização explícita.** Migration e deploy de backend em prod são
> **ações manuais do responsável**; ferramentas automáticas/IA não escrevem em
> prod sem o alvo nomeado por humano.

---

## 1. Ambientes (refs reais)

| Camada | DEV / staging | PRODUÇÃO |
|--------|---------------|----------|
| **Supabase** (ref) | `cxmjojnocigekgcxhubi` — projeto **Igreja12-dev** (conta dev separada) | `pffafnchtxbimpwyaczq` — projeto **Pastor-Ai-LionClaw-v1**, região **us-west-2** |
| **Conexão DB** | Pooler Supavisor `…pooler.supabase.com:6543` (host direto `db.<ref>` é **IPv6-only**, não conecta local) | idem (pooler) |
| **Clerk** | instância **dev/test** `lenient-bat-59.clerk.accounts.dev` (`pk_test`/`sk_test`) | instância de **produção** (≠ dev — chaves `pk_live`/`sk_live`) |
| **Backend** | local `127.0.0.1:8001` (`APP_ENV=staging`, `ALLOW_REAL_SENDS=false`) | `https://api.igreja12.com.br` (VPS, `APP_ENV=production`) |
| **Frontend** | local `127.0.0.1:3001` (Next dev) | Vercel projeto **pastorai-frontend** → `https://app.igreja12.com.br` |

⚠️ **Envios externos em produção:** como `external_sends_enabled = is_production OR
allow_real_sends`, em prod (`is_production=true`) **os envios reais estão ligados**
independente de `ALLOW_REAL_SENDS`. WhatsApp/e-mail/cobrança/Google podem disparar
de verdade. Fora de prod, ficam travados por padrão (guard B2).

---

## 2. Infra de produção (VPS)

- **VPS:** Hostinger, `2.25.167.107` (Ubuntu, KVM).
- **Caminho real do projeto:** `/opt/pastorai-lionclaw` (⚠️ **não** `/opt/pastorai`).
- **A VPS NÃO tem `.git`** — o código não é versionado lá; deploy é por **cópia/tarball**
  do backend versionado (ver §3).
- **Compose:** `/opt/pastorai-lionclaw/deploy/docker-compose.yml` **+ override**.
- **Backend source:** `/opt/pastorai-lionclaw/backend`.
- **Serviços (containers):** `backend`, `pastorai_queue_worker`, `pastorai_cron_worker`,
  `redis`, `evolution` (Evolution API/WhatsApp).
- Acesso SSH: chave dedicada `~/.ssh/pastorai_vps` (na máquina do responsável).
  SSH para esta prod **não é executado por IA** — o harness bloqueia alvo inferido.

---

## 3. Deploy do BACKEND em produção (processo real)

Como a VPS não tem `.git`, o deploy é por **tarball do backend versionado**,
**preservando** o `Dockerfile` e o `.dockerignore` remotos (eles vivem na VPS,
não vêm no tarball), com **backup antes**.

Sequência executada na promoção `27f7e7d` (2026-06-30):

1. **Backup** do backend atual antes de sobrescrever:
   `/root/pastorai-backups/backend-before-27f7e7d-20260630-122910.tar.gz`
2. Copiar o `backend/` versionado (do SHA alvo) para `/opt/pastorai-lionclaw/backend`,
   **sem** sobrescrever `Dockerfile`/`.dockerignore` remotos.
3. Rebuild **somente** do serviço backend (workers intocados):
   ```bash
   cd /opt/pastorai-lionclaw/deploy
   docker compose up -d --build --no-deps backend
   ```
4. Verificar:
   ```bash
   docker compose ps                 # backend running/healthy
   curl -s http://localhost:8000/health   # {"status":"ok"}
   ```

**Workers preservados:** `pastorai_queue_worker` e `pastorai_cron_worker`
mantiveram **container ID e StartedAt** (não reiniciados) — `--no-deps backend`
toca só o backend.

**Verificação pública pós-deploy** (read-only, de fora):
- `https://api.igreja12.com.br/health` → `{"status":"ok"}`
- `https://api.igreja12.com.br/openapi.json` contém `/events/{event_id}`,
  `/events/{event_id}/confirm`, `recorrencia`, `a_confirmar`, `confirmado_por`
  → prova EVT-2..5 no ar.

---

## 4. Deploy do FRONTEND em produção (Vercel)

- Projeto Vercel **`pastorai-frontend`** (org `raniel-levis-projects`), link em
  `frontend/.vercel/project.json`. Env de produção (`NEXT_PUBLIC_API_URL=
  https://api.igreja12.com.br`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` live) ficam
  **no projeto Vercel**, não no repo.
- Deploy de um SHA específico, a partir de um checkout **limpo** desse SHA:
  ```bash
  git worktree add --detach <tmp> <SHA>           # ex.: 27f7e7d
  cp frontend/.vercel/project.json <tmp>/frontend/.vercel/project.json
  cd <tmp>/frontend
  vercel --prod                                   # build remoto na Vercel
  git worktree remove --force <tmp>               # limpa depois
  ```
- O `vercel --prod` **builda remoto** (não precisa `node_modules` local), gera o
  deployment de produção e **faz alias do domínio** `app.igreja12.com.br`.
- **Verificação pública pós-deploy:** `app.igreja12.com.br` HTTP 200; bundle
  servido (`/_next/static/chunks/app/page-*.js`) contém `"A confirmar"` e a URL
  `api.igreja12.com.br`; **nenhuma** ref de dev (`cxmjojnocigekgcxhubi`/`127.0.0.1`).
- Reversível: histórico/rollback no dashboard Vercel.

---

## 5. Migration em produção (Supabase)

- Migrations são aplicadas **manualmente** pelo responsável, via **SQL Editor** do
  projeto de produção (`pffafnchtxbimpwyaczq`), **em ordem de nome de arquivo**.
- ⚠️ **Produção NÃO tem tabela `public.schema_migrations`** (as migrations base
  0001–0017 foram aplicadas sem ledger). Aplica-se **só o DDL** do arquivo; não há
  linha de ledger a inserir em prod (≠ DEV, que tem o ledger).
- A EVT-1 (`20260629_222635_evt1_…sql`) é **idempotente** (enums via
  `DO/duplicate_object`, colunas `IF NOT EXISTS`, constraints com guard) e roda em
  transação única — segura para reexecução, mas **não reaplicar sem necessidade**.

---

## 6. Comandos seguros (read-only / não destrutivos)

```bash
# Estado público de produção (de qualquer lugar)
curl -s https://api.igreja12.com.br/health
curl -s https://api.igreja12.com.br/openapi.json | grep -o '/events/{event_id}[^"]*'
curl -s -o /dev/null -w '%{http_code}' https://app.igreja12.com.br/

# Na VPS (read-only)
cd /opt/pastorai-lionclaw/deploy && docker compose ps
docker compose logs --tail=80 backend

# Verificação de schema em prod (read-only, via SQL Editor ou MCP só-SELECT)
select column_name,is_nullable from information_schema.columns
  where table_schema='public' and table_name='events' order by ordinal_position;
```

## 7. Comandos PROIBIDOS (sem autorização explícita do responsável)

- ❌ `docker compose up -d --build` **sem `--no-deps backend`** — reinicia os workers
  (`queue_worker`/`cron_worker`). Para deploy de backend use sempre `--no-deps backend`.
- ❌ `git pull` / qualquer git **na VPS** — ela não tem `.git`; deploy é por tarball.
- ❌ Reaplicar migration em prod sem verificar que já está aplicada.
- ❌ Editar o `.env` de produção / mexer em `ALLOW_REAL_SENDS`.
- ❌ SSH automatizado/IA para a VPS com IP **inferido** (o harness bloqueia; o alvo
  precisa ser nomeado e autorizado por humano).
- ❌ Qualquer escrita em `pffafnchtxbimpwyaczq` sem provar o ref e ter autorização.

---

## 8. Riscos do smoke funcional em PRODUÇÃO

O smoke funcional da Agenda em prod **ainda não foi feito** (decisão: só read-only
até aqui). Antes de fazê-lo, ciente de:

- **Precisa de usuário Clerk de PRODUÇÃO** (instância ≠ dev `lenient-bat-59`).
- **`POST /events` pode criar evento REAL no Google Calendar** se o Google estiver
  configurado em prod (em prod os envios estão ligados). O `DELETE` do app **não
  remove** o evento espelhado no Google nesta fase (escopo EVT-6+) → risco de
  **órfão** ("lixo") no Google.
- `PUT`, `DELETE` e `POST /events/{id}/confirm` **não** disparam envio externo
  (confirm só grava `status`+timestamps).
- **Mitigações:** ou confirmar que prod **não** tem Google configurado, ou
  restringir o smoke a operações que não criam evento, ou aceitar e **limpar
  manualmente** o órfão no Google. Qualquer dado de smoke criado deve ser removido
  e o estado voltar ao baseline.

---

## 9. Estado final da Agenda MVP (2026-06-30)

| Item | Estado |
|------|--------|
| Código no main | `27f7e7d` (EVT-1..5) |
| Migration EVT-1 em prod | ✅ aplicada e verificada (`events` 18 colunas, `data` nullable, 4 enums, 4 constraints, FK `confirmado_por`, RLS + `tenant_isolation` intactos, dados reais inalterados) |
| Backend prod | ✅ `27f7e7d` (api.igreja12.com.br/health 200; openapi com rotas EVT-2..5; workers preservados) |
| Frontend prod | ✅ `27f7e7d` (Vercel `dpl_66e4fhmGyg9cp8zBAFaP9KP33Rj6`; app.igreja12.com.br 200; bundle com "A confirmar") |
| Smoke funcional prod | ⏳ **pendente** (ver §8) |

**Pendências:** smoke funcional em produção (com usuário Clerk de prod e cuidado
com o Google); pós-MVP = EVT-6 (import Google, exige fix do token por-igreja) e
EVT-7 (lembrete/planejamento, worker + envio).
