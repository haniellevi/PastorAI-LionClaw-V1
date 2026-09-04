# Staging isolado do PastorAI (B1)

Guia para levantar um ambiente de **staging/dev isolado** antes das fases F2/F3.
O objetivo é poder testar mudanças (e, depois, ativar o guard de envios do B2)
sem nenhum risco para produção, dados reais de fiéis ou serviços externos.

> **Estado atual do bootstrap de schema:** o procedimento original de aplicação
> genérica foi substituído pelo executor fail-closed. Não use este guia para
> aplicar o catálogo completo. O código de `bootstrap-ledger` está integrado,
> mas foi comprovado somente offline e nenhum comando de banco está autorizado em DEV, staging ou PROD
> antes da reconciliação histórica humana versionada. O
> `bootstrap-ledger` está integrado e comprovado somente offline, ainda não aplicado.

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

`backend/scripts/apply_migrations.py` é um runner histórico de hash congelado e
não é o entrypoint corrente: isoladamente ele enumera `*.sql` sem consumir o
head aprovado. O candidato `apply_migrations_catalog_bound_v2.py` autentica o
runner legado e a API de snapshot antes de executá-los, e vincula todo SQL ao
snapshot validado do catálogo, mas ainda bloqueia qualquer comando que abriria
conexão por falta de trust anchor e autorização operacional externos.

```bash
# a partir de backend/ (com o venv ativo)

# Única operação disponível sem conexão:
python -P scripts/apply_migrations_catalog_bound_v2.py list
```

`status`, `harden-ledger`, `bootstrap-ledger` e `apply` não estão disponíveis em
staging, DEV ou PROD neste SHA. O código legado de `bootstrap-ledger` implementa
a criação somente do ledger vazio
`public.schema_migrations` no contrato owner-only, após confirmação literal
`BOOTSTRAP_LEDGER`. Ele não descobre o catálogo, não consulta
`supabase_migrations`, não reconcilia histórico e não aplica ou registra
migration, mas isso é evidência histórica, não instrução de execução.

A implementação foi testada somente offline: 42/42 testes unitários, 87/87 em
PostgreSQL 17-alpine descartável em duas execuções independentes, 87/87 em
Supabase PG17 17.6.1.159 descartável em duas execuções independentes e revisão
de segurança `GO`. A suíte RLS completa, em execução serial limpa no PostgreSQL
17 descartável, passou em 326/326, com 3803 deselecionados e 2 warnings
preexistentes, em 162.77s. A suíte offline integral foi interrompida após 5
min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem falha
e não foi reclassificado. Os workflows Backend Tests da PR #323 e do pós-merge
concluíram com `SUCCESS`. O merge
`3a5789c784017ab15a43e28c4270d25af8618359` gerou Preview e Production
automáticos do frontend na Vercel. Essa metadata não prova backend, banco ou
runtime. Não houve deploy manual ou do backend, acesso aos bancos DEV ou PROD,
bootstrap, migration, restart ou mudança de flag.

O pacote deny-state versionado e o verificador stdlib separado do runner, comprovados
offline sobre a base `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram
integrados pela PR #325, HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no
merge `ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`. O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES
HUMANAS PENDENTES / NÃO APLICADO`, e o contrato está em
[`2026-08-28-migration-history-reconciliation-contract.md`](../docs/decisions/2026-08-28-migration-history-reconciliation-contract.md).
O verificador não usa banco, rede, ambiente, variáveis de ambiente, SQL, DML ou
escrita, não infere migration aplicada e todo sucesso estrutural conserva
`OPERATIONAL_AUTHORIZATION=BLOCKED`.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador foi integrado pela PR #327 e o hotfix pela PR #328, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. As saídas locais foram originalmente
materializadas com modo `0600` e `O_EXCL`; depois do versionamento, a proteção
dos seis artefatos depende da sanitização e da ACL do repositório, não do modo
do checkout. Eles registram inventários DEV e PROD capturados, não revisados e
bloqueados. Em PostgreSQL 17, DEV contém 33 linhas no ledger público e 6 no
nativo; PROD registra o ledger público `ABSENT_CONFIRMED`, com 0 linhas, e 32
linhas no nativo.
`native.name` permanece `null`. Ambos os pacotes estão
`EVIDENCE_CAPTURED_UNREVIEWED`, e ambos terminaram no verificador com exit `8`,
`HUMAN_EVIDENCE_BLOCKED`; a checagem conjunta terminou `CROSS_PACKAGE_OK`. A
matriz focal offline pós-captura passou com `163 passed, 2 skipped` em `1.40s`,
sem representar suíte integral ou reexecução PostgreSQL.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. O merge
gerou o deployment automático Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integração versiona
a evidência sanitizada já capturada, mas não revisa os inventários, não aplica
migration e não libera o runner ou qualquer autorização operacional.

A revisão independente bloqueada foi concluída; o registro externo de SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`
bloqueou DEV por divergência e PROD por evidência insuficiente. A decisão
OWNER-01 registrada está vinculada ao SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve a autorização operacional falsa e abriu somente a proposta offline.

O manifesto estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
Ele é `SOURCE_LEVEL_EXPECTATION_ONLY`, não prova o schema final de DEV ou PROD
e permanece com `OPERATIONAL_AUTHORIZATION=BLOCKED`. A revisão técnica foi
feita pelo mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. A decisão, as provas A/B idênticas
e os limites estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](../docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não muda este procedimento de
staging. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`2026-08-29-offline-canonical-schema-derivation.md`](../docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

Naquele recorte histórico, foi proposto o gate
`SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION`. O gate
proposto não foi consumido. Ele exigiria uma autorização humana nova, nominal,
exclusiva e separada, com fonte, filtros e janela temporal mínima delimitados
antes de uma única revisão read-only e sanitizada dos logs da falha DEV.
Nenhum log foi acessado nesta PR. O gate proposto não
autoriza retry, nova invocação DEV, consulta a PROD, banco ou SQL, exportação ou
persistência de logs, captura, materialização, DML, reconciliação de ledger,
corte de época,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, SQL Editor,
`apply_migration`, `db push`, MCP, deploy, flag ou runtime. PROD continua fora.
UV e CD permanecem fora. Posteriormente, esse caminho foi supersedido pelos
diagnósticos de fase e pelo probe transport-only executados sob autorizações
humanas nominais próprias. O identificador permanece somente como registro
histórico e não é gate corrente nem próximo hoje.

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

## Atestação de ambiente permanece bloqueada

O tooling separado de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A decisão está em
[`2026-08-30-read-only-environment-attestation-tooling.md`](../docs/decisions/2026-08-30-read-only-environment-attestation-tooling.md).
As provas terminaram em `81 passed` de `81` no foco offline,
`367 passed, 47 skipped` na seleção relacionada e `82 passed` de `82` no foco
PostgreSQL 17 TLS descartável. Sarah/Terra concluiu `GO`; Claude Opus passou no
healthcheck, mas a revisão completa travou com `Execution error` e não conta
como concluída.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluíram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e não
prova backend, banco ou runtime. O estado corrente é
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O JSON Schema valida somente o envelope; o verificador Python é obrigatório.
O HMAC é correlação e anti-swap, não autorização humana nem observação direta
do project ref. Data API e Realtime permanecem
`PLATFORM_SURFACES_UNATTESTED`, `OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false`.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integração.
Os SHA-256
congelados são: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitários `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestação existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitários passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestação existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e não prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado à autorização. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorização nominal para cada invocação.
O HMAC serve somente correlação e anti-swap e não substitui autorização humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materialização. Os buffers de chave e nonce são zerados, os descritores são
fechados e os certificados TLS temporários são removidos após a prova. DEV e
PROD não foram consultados. PROD está explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

Em 2026-08-30, já no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocações DEV foram feitas
sob autorizações humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso não foi preservado;
nenhum horário UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos não
provam se houve conexão, não provam sucesso ou falha de autenticação e não
identificam a causa raiz.

O diagnóstico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartável e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local não reclassifica DEV nem determina a causa do bloqueio. A
evidência detalhada está em
[`2026-08-30-dev-identity-preflight-diagnostics.md`](../docs/decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnóstica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e não prova backend, banco ou runtime.

A integração não repetiu o preflight, não consultou logs, não fez novo acesso a
DEV ou PROD e não determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

Naquele recorte histórico, foi proposto o gate
`SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION`. O gate
proposto não foi consumido. Ele exigiria uma autorização humana nova, nominal,
exclusiva e separada para uma única revisão read-only e sanitizada dos logs da
falha DEV. A fonte, os filtros e a janela temporal mínima ainda não foram
delimitados e precisariam constar da autorização antes de qualquer acesso;
nenhum horário é inferido. Nenhum log foi acessado nesta PR. O gate proposto
não autoriza retry, nova invocação DEV, consulta a
PROD, banco ou SQL, exportação ou persistência de logs, captura,
materialização, DML, migration, reconciliação, backfill, deploy, flag ou
runtime. PROD continua fora. Posteriormente, esse caminho foi supersedido pelos
diagnósticos de fase e pelo probe transport-only executados sob autorizações
humanas nominais próprias. O identificador permanece somente como registro
histórico e não é gate corrente nem próximo hoje.

A política de permissões foi implementada e comprovada offline pelo snapshot
privado descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](../docs/decisions/2026-09-03-trusted-repository-snapshot-policy.md).
O gate
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE` foi
consumido somente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](../docs/decisions/2026-09-03-migration-environment-attestation-executor-v2.md).
Ele não deve receber DSN, CA, chave, nonce ou registro de autorização antes de
existirem trust anchors externos para autorização nominal, runtime/dependências
e anti-replay.

O commit local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, parent
`947af39d35544700188461d8c99332df70b57e07`, acrescenta autoria
`draft`/`prepare-head` `TENANT` source-only, snapshot validado, wrapper
catalog-bound v2 somente `list` e replay do head em PostgreSQL 17 descartável e
loopback. O mesmo SHA confirmou 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`;
a focal concluiu `274 passed, 6 skipped`, a prova PG17 real `6/6` com E2E
sintético de 76ª migration, e duas revisões independentes `P0=0`/`P1=0`. Isso é
local: não houve integração, push, PR ou CI remoto e não libera staging.

O workflow candidato usa PostgreSQL 17 descartável e replay, mas nunca banco
compartilhado, DEV/PROD ou o runner legado de aplicação. O
`apply_migrations.py` legado ainda é invocável como risco residual. O replay não
cobre views, outros schemas, funções, roles/memberships, `BYPASSRLS`, grants
nomeados, schema/default ACL ou semântica DML/DDL ampla. Worktree/migrations
foram observadas em `0755` e SQL em `0644`, mas ancestrais permanecem `0775` e
o `chmod` local não é durável; P2 global permanece.

DEV está `BLOCKED_LEDGER_DIVERGENCE`, PROD
`BLOCKED_EVIDENCE_INSUFFICIENT`, TLS DEV histórico sem solução, e revisão v3,
cutover, atestação viva e aplicação pendentes. `operational_authorization=false`
e `next_stage_authorized=false`.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto, não consumido e substituído. O único estágio corrente fechado é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, limitado ao
preflight remoto read-only, push, abertura de PR e observação do CI/Preview. Não
autoriza merge, banco, DEV, PROD, migration, runner de aplicação ou flags.
Trust anchors externos permanecem futuros, não correntes e não autorizados.

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
