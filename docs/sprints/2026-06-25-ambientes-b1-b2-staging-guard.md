# Confiabilidade de ambientes: B1 staging + B2 guard não-prod — 2026-06-25

**Branches:** `chore/staging-b1-artefatos` (B1) · `feat/b2-guard-envios-naoprod` (B2)
· **Commits:** B1 `7293827` (merge `9726e06`, PR #40) · B2 `91736bd` (merge `7cd30bb`, PR #41)
· **Deploy:** não (só código/docs na `main`; ativação de staging é ação manual pendente)

## Objetivo do bloco
Tornar seguro testar mudanças fora de produção **antes** de liberar as fases visuais
F2/F3 do redesign. Dois blocos complementares:

- **B1 — staging isolado:** ter um ambiente espelho de produção (Supabase/Clerk
  próprios) onde dá pra validar sem risco a dados reais de fiéis nem a serviços externos.
- **B2 — guard de envios não-prod:** trava no código que impede efeitos externos reais
  (WhatsApp, cobrança, e-mail, LLM, agenda) de disparar fora de produção, mesmo que
  alguma credencial acabe presente.

## Por que B1/B2 antes de F2/F3
F2/F3 mexem na UI e em fluxos que disparam envios (inbox, checkout, convite, evento).
Sem ambiente isolado **e** sem trava de envios, testar o redesign arriscaria mandar
WhatsApp/cobrança/e-mail reais ou contaminar produção. B1 dá o ambiente; B2 dá a rede de
segurança. Por isso F2/F3 ficaram **bloqueadas** até B1+B2 estarem prontos.

## B1 — artefatos de staging (PR #40, merge `9726e06`)
Entregou os **artefatos versionáveis** que documentam e operacionalizam um staging isolado
(sem segredos no repo):

- **`deploy/STAGING.md`** — guia operacional: princípio do **projeto Supabase dedicado**
  (um Postgres genérico não reproduz roles/grants/GUCs da RLS), ordem de bootstrap,
  ações manuais por painel, gates de isolamento, riscos e "o que NÃO fazer".
- **Runner de migrations** (`backend/scripts/apply_migrations.py`) — aplica migrations
  **em ordem de nome** contra um `DATABASE_URL` alvo; não roda sozinho, não embute
  connection string, exige confirmação interativa do host, mantém tabela `schema_migrations`.
- **Templates de env** — `backend/.env.staging.example` e `frontend/.env.staging.example`
  (placeholders, sem segredos), com legenda `[ISOLAR]/[VAZIO]/[DEFAULT]` por bloco.

## B2 — guard de envios não-prod (PR #41, merge `7cd30bb`, commit `91736bd`)
Trava na **camada de serviço** (não nos routers), de propósito: envios autônomos
(worker do agente, cron de SLA) não passam por router — um guard só nos endpoints não
cobriria esses caminhos.

- **Flag + trava dupla** (`backend/app/config.py`):
  - `ALLOW_REAL_SENDS` (env) — default **`false`**.
  - `external_sends_enabled = is_production or allow_real_sends` — produção sempre permite;
    fora de produção, bloqueado por padrão; só liga com `ALLOW_REAL_SENDS=true` **e**
    credenciais sandbox.
- **Helper** (`backend/app/services/outbound_guard.py`): `external_sends_allowed()` +
  `log_suppressed()` — loga `[SANDBOX] <canal> suprimido...: <ação>`, sem segredo nem PII.
- **12 métodos protegidos** (retorno neutro + log, sem tocar a rede):
  - Evolution (WhatsApp): `send_text`, `send_media`, `set_webhook`, `connect`, `reconnect`, `disconnect`
  - Asaas (billing): `create_checkout`
  - Brevo (e-mail): `send_invite`, `send_password_reset`
  - LLM (OpenAI): `complete`
  - Google Calendar: `create_event`, `delete_event`
- **Sempre ativos (auth/infra do ambiente, senão staging não sobe):** Clerk
  `create_user`, OAuth Google, Supabase Storage, leituras da Evolution e
  `validate_credential` do LLM (custo ~zero) — exclusões conscientes, documentadas no STAGING.md.

## Decisões
- **Guard na camada de service, não nos routers** — para cobrir envios autônomos
  (worker/cron) que não passam por endpoint.
- **Default seguro** — `ALLOW_REAL_SENDS=false`; produção permite por `is_production`.
  Local/staging só envia com override explícito + credencial sandbox.
- **`create_event` levanta `GoogleCalendarError`** (em vez de retorno neutro) porque o
  único caller (`backend/app/routers/events.py:114-121`) já trata o erro como
  "evento salvo, sync falhou" — reaproveita o caminho existente.
- **B1 = artefatos versionáveis**, não o ambiente em si: criar Supabase/Clerk e aplicar
  migrations é ação manual de painel, fora do que o repo deve guardar.

## Verificação
- **B2 testes:** `backend/tests/test_outbound_guard.py` (novo) + ajuste em
  `test_evolution_service.py`. Suíte completa **531 passed** (venv backend). Os testes do
  guard usam `httpx.MockTransport` que **falha se o guard vazar** — prova adversarial de
  que nada toca a rede em sandbox; e asseguram que log `[SANDBOX]` não vaza telefone,
  e-mail ou chaves.
- **Revisão independente do PR #41:** conclusão `APTO PARA SAIR DE DRAFT` — confirmou os
  12 métodos, default seguro, exclusões conscientes, worker/cron cobertos pelos métodos
  guardados (`queue_worker.py:445`, `sla_engine.py:280`, `agent/runtime.py:325`).
- **Scan de segredos no diff:** limpo (só placeholders `_xxx` e fakes de teste).
- **Sem banco/serviço externo tocado** durante revisão e merge.
- **Estratégia de merge:** merge commit (padrão do repo). `origin/main` final = `7cd30bb`.

## Pendente / próximo passo
- **B1 manual ainda NÃO executado** (ações de painel, fora do código):
  1. criar **projeto Supabase de staging** dedicado;
  2. criar bucket privado **`whatsapp-media`**;
  3. criar **instância Clerk dev/test** (`pk_test`/`sk_test`) + usuário de teste;
  4. **aplicar migrations** em staging (via runner ou SQL editor);
  5. **validar os gates de isolamento** do `deploy/STAGING.md` (ref distinto, Clerk de
     teste, cripto exclusiva, volume = seed, externos sem credencial, RLS efetiva,
     **guard off → só loga `[SANDBOX]`**).

## Gate para liberar F2/F3
Liberar o redesign F2/F3 **somente quando**:
- [x] B1 manual concluído (Supabase staging + bucket + Clerk dev/test + usuário + migrations);
- [x] gates de isolamento do `deploy/STAGING.md` validados (em especial RLS efetiva e
      guard off comprovado por log `[SANDBOX]`).

Com B2 já na `main` (`7cd30bb`) e os gates B1 fechados, F2/F3 ficam desbloqueadas.

> Detalhe de contagem: a descrição do PR #41 mencionava "11 métodos"; a contagem real é
> **12** (subcontagem benigna — mais protegido, não menos).

---

## B1 manual — execução e gates fechados (2026-06-25)

Execução dos passos operacionais descritos em `deploy/STAGING.md`. Projeto de staging:
**Igreja12-dev** (ref distinto de produção — verificado caractere a caractere antes de
qualquer escrita no banco).

### Sequência executada

| Passo | Ação | Resultado |
|-------|------|-----------|
| 1 | Projeto Supabase de staging criado (free tier) | ref staging ≠ ref prod ✅ |
| 2 | `backend/.env` preenchido a partir de `.env.staging.example` | `APP_ENV=staging`, `ALLOW_REAL_SENDS=false`, URLs/keys de staging, Fernet exclusivo ✅ |
| 3 | Bucket privado `whatsapp-media` criado no Storage de staging | `public=False` confirmado via API ✅ |
| 4 | Instância Clerk dev criada; chaves `pk_test_`/`sk_test_` configuradas em back e front | Clerk de teste em ambos ✅ |
| 5 | Migrations aplicadas via runner (`apply_migrations.py apply`) com confirmação interativa do host | 24/24 migrations aplicadas, tabela `schema_migrations` criada ✅ |
| 6 | `app_users.clerk_user_id` atualizado de `user_seed_pastor_clerk_id` → id real do Clerk dev | `SELECT` confirmou a troca ✅ |
| 7 | Backend iniciado (`uvicorn app.main:app --port 8000`) | `env=staging`, `startup complete` ✅ |

### Gates de isolamento — todos fechados

| Gate (`deploy/STAGING.md`) | Evidência | Status |
|-----------------------------|-----------|--------|
| Ref distinto | ref staging ≠ `pffafnchtxbimpwyaczq` (prod) | ✅ |
| Clerk de teste | `pk_test_`/`sk_test_` nos dois arquivos; validado por script | ✅ |
| Cripto exclusiva | `SECRETS_ENCRYPTION_KEY` gerado localmente, Fernet válido, ≠ prod | ✅ |
| Volume = seed | `igrejas=1`, `pessoas=1`, `app_users=1` — apenas dados fictícios | ✅ |
| Externos sem credencial | Evolution/OpenAI/Asaas/Brevo/Google vazios no `.env` | ✅ |
| Produção intocada | Nenhuma migration, linha ou credencial tocada no projeto de prod | ✅ |
| Migrations 24/24 | Runner aplicou em ordem, registrado em `schema_migrations` | ✅ |
| Login + seed casado | `POST /auth/login` → `churchId = 00000000-…-000001` (igreja piloto) | ✅ |
| RLS efetiva | `GET /contacts` autenticado → só a pessoa do seed, zero cross-tenant | ✅ |
| Guard `[SANDBOX]` | `POST /auth/forgot-password` → `[SANDBOX] Brevo suprimido em nao-producao: send_password_reset` no log | ✅ |
| `/health` | `{"status":"ok"}` | ✅ |

### Ressalvas pós-B1

- **Workers não sobem nesta fase:** `queue_worker` e `cron_worker` permanecem parados
  conforme orientação do `STAGING.md`. Iniciá-los exigiria credenciais sandbox de
  Evolution/Asaas (ausentes por design neste estágio).
- **`frontend/.env.local`** preenchido com `pk_test_` e `NEXT_PUBLIC_API_URL`; o frontend
  Next não foi iniciado no B1 (os gates de ambiente provam pelo backend).
- **venv ausente:** `pip install` foi feito no Python global (Windows, sem venv), o que
  rebaixou pacotes globais (`langgraph`, `openai`). Não afeta o B1 nem produção, mas
  deve ser corrigido antes de F2/F3 (criar `backend/.venv`).

### Decisão: F2/F3 liberadas do ponto de vista de ambiente

Todos os gates do `deploy/STAGING.md` estão fechados. O ambiente de staging está isolado,
funcional e com o guard B2 ativo. **F2 e F3 podem ser iniciadas.**
