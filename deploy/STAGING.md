# Staging isolado do PastorAI (B1)

Guia para levantar um ambiente de **staging/dev isolado** antes das fases F2/F3.
O objetivo é poder testar mudanças (e, depois, ativar o guard de envios do B2)
sem nenhum risco para produção, dados reais de fiéis ou serviços externos.

> **Estado atual do bootstrap de schema:** o procedimento original de aplicação
> genérica foi substituído pelo executor fail-closed. Não use este guia para
> aplicar o catálogo completo. O candidato `bootstrap-ledger` existe somente
> offline e nenhum comando de banco está autorizado em DEV, staging ou PROD
> antes da reconciliação histórica humana versionada. O
> `bootstrap-ledger` está implementado e comprovado somente offline, ainda não aplicado.

> Plano completo (diagnóstico, fluxo e gates) em `plano-b1-staging-isolado.html`
> (abra no browser). Este README é a versão operacional.

---

## Princípio: staging usa um PROJETO SUPABASE DEDICADO

O schema **não cria** os roles nem os GRANTs de que a RLS depende — eles vêm dos
*default privileges nativos do Supabase* (roles `authenticated`/`anon`/
`service_role` e o GUC `request.jwt.claims`). A função `current_igreja_id()` +
`SET LOCAL ROLE authenticated` (em `app/db/rls.py`) só isolam os tenants porque
esses roles existem.

Consequência: **um Postgres genérico (container `postgres:16` local) NÃO
reproduz o isolamento** sem recriar roles, grants e GUCs à mão — e ainda assim
ficaria sem o Storage e a stack de signed URLs. **Por isso staging deve ser um
projeto Supabase dedicado**, que já traz tudo idêntico a produção com esforço
mínimo. Não use Postgres local para isto.

---

## Ordem de bootstrap

Cada passo `[manual]` é uma ação sua num painel externo; `[runner]`/`[local]`
usam os artefatos deste repositório.

1. **[manual · Supabase]** Criar um **projeto Supabase de staging** (free tier
   serve). Anotar `ref`, `SUPABASE_URL`, anon key, service-role key e a
   `DATABASE_URL` do **pooler** (senha percent-encoded).
2. **[bloqueado]** Não aplicar migrations nem criar o ledger público enquanto a
   reconciliação histórica humana não formar um prefixo íntegro e aprovado. O
   bootstrap vazio não reconstrói o schema e não libera `status` ou `apply`.
3. **[manual · Supabase]** Criar o **bucket de Storage `whatsapp-media`**,
   **privado** (não há migration que faça isso; o chat com mídia depende dele).
4. **[manual · Clerk]** Criar/confirmar uma **instância Clerk dev/test**. Pegar
   `pk_test_*`, `sk_test_*`, o issuer e o JWKS. Criar **um usuário de teste** e
   anotar o `clerk_user_id`.
5. **[local · SQL]** Casar o seed com o usuário de teste: atualizar
   `app_users.clerk_user_id` da igreja piloto para o id real do Clerk dev (o
   `0005_seed.sql` grava o placeholder `user_seed_pastor_clerk_id`). Sem isso,
   `current_igreja_id()` não resolve o tenant e o login "entra mas não vê nada".
6. **[local]** Montar os `.env`: copiar `backend/.env.staging.example` →
   `backend/.env` e `frontend/.env.staging.example` → `frontend/.env.local`,
   preenchendo os valores de staging. Use exatamente esses destinos (é o que o
   app lê) e nunca commite um arquivo com valores reais. Gerar uma
   `SECRETS_ENCRYPTION_KEY` **nova** só para staging. Deixar os serviços externos
   **vazios** nesta fase.
7. **[local]** Subir o backend (`uvicorn app.main:app --reload`) e o frontend
   (`npm run dev`). `GET /health` deve responder `{"status":"ok"}`.
8. **[local]** Logar com a conta de teste e rodar a **checklist de gates** abaixo.
   **Não** inicie os workers (`queue_worker`/`cron_worker`) nesta fase.

---

## Ações manuais por painel

| Painel | O que fazer |
| ------ | ----------- |
| **Supabase** | Criar o projeto de staging; criar o bucket privado `whatsapp-media`; copiar URL + keys + `DATABASE_URL` do pooler. |
| **Clerk** | Criar/confirmar a instância **dev**; copiar `pk_test`/`sk_test`, issuer e JWKS; criar o usuário de teste e pegar o `clerk_user_id`. |
| **Vercel** *(se hospedar o front de staging)* | Criar o ambiente de Preview com os `NEXT_PUBLIC_*` de staging. |
| **Local** | Gerar uma `SECRETS_ENCRYPTION_KEY` Fernet nova, exclusiva de staging. |

---

## Variáveis de ambiente

Use os exemplos versionados como referência (**não contêm segredos**):

- Backend: [`backend/.env.staging.example`](../backend/.env.staging.example)
- Frontend: [`frontend/.env.staging.example`](../frontend/.env.staging.example)

`APP_ENV=staging` mantém o backend tolerante a envs vazias (o
`assert_production_ready()` só exige secrets quando `APP_ENV=production`). Os
blocos marcados `[VAZIO]` ficam sem credencial de propósito — nenhuma mensagem,
cobrança ou e-mail real sai de staging.

---

## Runner de migrations

`backend/scripts/apply_migrations.py` não aplica uma lista de pendências e não
aceita URL em argv. O destino vem exclusivamente de
`M06_MIGRATION_DATABASE_URL`, injetada pelo canal secreto do processo. Não cole
DSN, senha, token ou host em terminal compartilhado, conversa ou documentação.

```bash
# a partir de backend/ (com o venv ativo)

# Única operação disponível sem conexão:
python scripts/apply_migrations.py list
```

`bootstrap-ledger` implementa a criação somente do ledger vazio
`public.schema_migrations` no contrato owner-only, após confirmação literal
`BOOTSTRAP_LEDGER`. Ele não descobre o catálogo, não consulta
`supabase_migrations`, não reconcilia histórico e não aplica ou registra
migration. Com múltiplos arquivos locais e ledger vazio, `status` e `apply`
falham fechados.

A implementação foi testada somente offline: 42/42 testes unitários, 87/87 em
PostgreSQL 17-alpine descartável em duas execuções independentes, 87/87 em
Supabase PG17 17.6.1.159 descartável em duas execuções independentes e revisão
de segurança `GO`. A suíte RLS completa, em execução serial limpa no PostgreSQL
17 descartável, passou em 326/326, com 3803 deselecionados e 2 warnings
preexistentes, em 162.77s. A suíte offline integral foi interrompida após 5
min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem falha,
e o workflow Backend Tests da PR permanece gate. Não houve acesso a DEV ou PROD, deploy, migration ou mudança
de flag.

O próximo gate é uma PR offline e versionada de reconciliação histórica humana,
sem DML e sem inferência. Até ela terminar, não execute `bootstrap-ledger`,
`harden-ledger`, `status`, `apply`, SQL Editor, `apply_migration`, `db push` ou
MCP para preencher ou reaplicar histórico em staging ou ambiente compartilhado.

---

## Gates de isolamento

Marque **todos** antes de considerar staging pronto:

- [ ] **Ref distinto** — o `ref` em `SUPABASE_URL`/`DATABASE_URL` de staging é
      diferente do projeto de produção.
- [ ] **Clerk de teste** — back e front usam `pk_test_*`/`sk_test_*` (nunca
      `pk_live`/`sk_live`).
- [ ] **Cripto exclusiva** — `SECRETS_ENCRYPTION_KEY` de staging ≠ a de produção.
- [ ] **Volume = seed** — a contagem de `igrejas`/`pessoas` bate com o seed
      fictício, não com o volume de produção; nenhum dado real de fiéis presente.
- [ ] **Externos sem credencial** — Evolution/Asaas/Brevo/OpenAI/Google vazios;
      uma tentativa de envio falha de forma controlada.
- [ ] **Produção intocada** — nenhuma migration nova nem linha nova aplicada no
      projeto de produção durante o B1.
- [ ] **RLS efetiva** — após o login da conta de teste, uma consulta cross-tenant
      retorna só a igreja piloto (prova que a RLS funciona no clone).
- [ ] **Guard de envios off** — com `APP_ENV=staging`,
      `ALLOW_REAL_SENDS=false` e `BREVO_SEND_MODE=off`, uma ação de envio
      (responder no inbox, abrir checkout, convidar membro, criar evento) não
      toca a rede; Brevo falha fechado e os demais provedores são suprimidos.
      Nenhuma mensagem, cobrança, e-mail, custo de LLM ou evento real dispara.

---

## Guard de envios (B2)

Em todos os ambientes, os efeitos externos reais ficam **desligados por padrão**.
O guard em `app/services/outbound_guard.py` cobre WhatsApp, Asaas, LLM e
Calendar; em staging/dev eles são no-op logado (`[OUTBOUND_DISABLED] …`). Brevo
tem gate dedicado e falha fechado em qualquer modo bloqueado, para nunca simular
sucesso de e-mail.

Trava global explícita: `external_sends_enabled = ALLOW_REAL_SENDS`. Produção,
staging e desenvolvimento só executam esses provedores globais quando o operador
muda `ALLOW_REAL_SENDS=true`; em staging/dev use apenas credenciais sandbox.
Asaas tem uma segunda trava: mutações financeiras também exigem
`ASAAS_BILLING_ENABLED=true`. Brevo exige `BREVO_SEND_MODE=canary` com allowlist
explícita ou `live`; `off` é obrigatório nos smokes sem efeitos externos.

Permanecem sempre ativos (auth/infra do próprio ambiente, senão staging não
funciona): login/identidade Clerk, OAuth do Google, Supabase Storage, leituras da
Evolution e o `validate_credential` do LLM (custo ~zero).

---

## Riscos

| Risco | Severidade | Mitigação |
| ----- | ---------- | --------- |
| `.env` de staging apontando para Supabase/Clerk de **produção** por engano | Alta | Gates "ref distinto" + "Clerk de teste" antes de qualquer escrita; `.env.staging` próprio, nunca derivado do de prod. |
| Postgres genérico não reproduz roles/grants → RLS "passa" mas vaza | Alta | Usar **projeto Supabase** dedicado; gate "RLS efetiva". |
| Copiar dados reais de fiéis para staging (LGPD) | Alta | Só o seed fictício (`0005_seed.sql`); gate "volume = seed". |
| Subir `queue_worker`/`cron_worker` com credencial real → envia WhatsApp/cobra | Média | Não subir workers nesta fase; externos vazios. Endurecimento formal é o **B2**. |
| Migration fora de ordem / pulada → schema divergente | Alta | Manter `status` e `apply` bloqueados até a reconciliação histórica humana versionada comprovar o prefixo íntegro. |
| `.env` real commitado por engano | Baixa | Versionar só `*.staging.example` (sem valores). O `.gitignore` cobre `.env`, `.env.local`, `.env.*.local` e `.env.staging` — use exatamente esses destinos; nunca um arquivo com valores reais fora desses nomes. |

---

## O que NÃO fazer

- **Não** reutilizar service-role key, `DATABASE_URL` ou `SECRETS_ENCRYPTION_KEY`
  de produção em staging.
- **Não** copiar dados reais de produção para staging (LGPD) — só o seed fictício.
- **Não** apontar webhooks de produção (Evolution/Asaas) para staging, nem o
  contrário.
- **Não** rodar os workers de staging contra Evolution/OpenAI/Asaas reais.
- **Não** aplicar migrations não validadas direto em produção a partir deste fluxo.
- **Não** commitar `.env` de staging com valores — apenas o `.example` sem segredos.
- **Não** usar o mesmo Redis/DB da produção.
- **Não** iniciar F2/F3/F4 antes de fechar os gates do B1.

---

## Próximo (fora do B1)

**B2** — guard/sandbox que impede envios, cobranças e e-mails reais fora de
produção (hoje o único interruptor é `is_production` em `app/config.py`). Só
depois do B2 verde é seguro liberar F2/F3.
