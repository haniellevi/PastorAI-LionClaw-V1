# Staging isolado do PastorAI (B1)

Guia para levantar um ambiente de **staging/dev isolado** antes das fases F2/F3.
O objetivo é poder testar mudanças (e, depois, ativar o guard de envios do B2)
sem nenhum risco para produção, dados reais de fiéis ou serviços externos.

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
2. **[runner]** Aplicar as migrations em ordem (ver "Runner de migrations").
   Cria o schema, a RLS e a tabela de controle `schema_migrations`.
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

`backend/scripts/apply_migrations.py` aplica as migrations **em ordem de nome**
contra um `DATABASE_URL` alvo informado pelo operador. Ele **não roda sozinho**,
**não embute** nenhuma connection string e **só aplica** com o subcomando
`apply` + confirmação interativa (digitar o host de destino).

```bash
# a partir de backend/ (com o venv ativo)

# 1) Conferir a ordem das migrations (não conecta ao banco):
python scripts/apply_migrations.py list

# 2) Ver aplicadas x pendentes (read-only):
python scripts/apply_migrations.py status --database-url "postgresql://...STAGING..."

# 3) Aplicar as pendentes (vai pedir para você digitar o host de staging):
python scripts/apply_migrations.py apply --database-url "postgresql://...STAGING..."
```

O destino também pode vir da env `STAGING_DATABASE_URL` (a flag tem prioridade).
A senha nunca é impressa. O runner mantém uma tabela `schema_migrations` no banco
alvo para registrar o que já subiu — assim `status`/`apply` sabem o que falta.

Se algo falhar, o `apply` para no primeiro erro e mantém em `schema_migrations`
o registro das que concluíram; como as migrations são idempotentes, basta
corrigir a causa e rodar `apply` de novo para retomar as pendentes.

> As migrations continuam podendo ser aplicadas à mão no SQL editor do Supabase
> (ver `backend/migrations/README.md`); o runner é uma conveniência para
> reconstruir staging do zero, na ordem certa, com registro.

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

---

## Riscos

| Risco | Severidade | Mitigação |
| ----- | ---------- | --------- |
| `.env` de staging apontando para Supabase/Clerk de **produção** por engano | Alta | Gates "ref distinto" + "Clerk de teste" antes de qualquer escrita; `.env.staging` próprio, nunca derivado do de prod. |
| Postgres genérico não reproduz roles/grants → RLS "passa" mas vaza | Alta | Usar **projeto Supabase** dedicado; gate "RLS efetiva". |
| Copiar dados reais de fiéis para staging (LGPD) | Alta | Só o seed fictício (`0005_seed.sql`); gate "volume = seed". |
| Subir `queue_worker`/`cron_worker` com credencial real → envia WhatsApp/cobra | Média | Não subir workers nesta fase; externos vazios. Endurecimento formal é o **B2**. |
| Migration fora de ordem / pulada → schema divergente | Média | Aplicar via runner (ordem garantida) + tabela `schema_migrations`. |
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
