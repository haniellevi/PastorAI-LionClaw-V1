# PastorAI V1 — runbook canônico de produção

Atualizado em 2026-11-12 (seção 12). Este é o procedimento operacional vigente para o
Igreja 12. Não contém segredos; valores reais ficam somente nos provedores e no
`.env` do release ativo, acessível por `/opt/pastorai-current/deploy/.env`.

Backup, teste de restauração e firewall: consulte
[BACKUP-FIREWALL-RUNBOOK.md](BACKUP-FIREWALL-RUNBOOK.md).

## 1. Alvos oficiais

| Camada | Produção |
|---|---|
| Supabase | `pffafnchtxbimpwyaczq` |
| VPS Hostinger | `srv2031318.hstgr.cloud` (VPS nova, produção desde out/2026; a `srv1728329` é a antiga e será desativada) |
| Backend público | `https://api.igreja12.com.br` |
| Releases na VPS | `/opt/pastorai-releases/<sha>` |
| Release ativo | `/opt/pastorai-current` (symlink para um release imutável) |
| Frontend Vercel | projeto `pastorai-frontend-prod`, escopo `raniel-levis-projects` |
| Frontends públicos | `app.`, `admin.` e `painel.igreja12.com.br` |

O Clerk está na instância PROD. Publishable key, secret key, issuer e JWKS
precisam pertencer à mesma instância; nunca misture prefixos `pk_test_` ou
`sk_test_` com o issuer de produção.

O modelo versionado único fica em `/.env.example`. Em um provisionamento inicial
autorizado, copie as seções **Comum/servidor** e **Produção/deploy** do modelo
para `/opt/pastorai-current/deploy/.env` e preencha as credenciais pelo canal
secreto aprovado. Em atualização de VPS, preserve o `deploy/.env` real já
validado; atualizar o código não substitui esse arquivo.

### Baseline imutável da V1

- estado: `V1_ENCERRADA`, piloto controlado;
- código backend/frontend: `281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`;
- tag e GitHub Release: `v1.0.0`;
- frontend: Vercel `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp`;
- Supabase PROD: `pffafnchtxbimpwyaczq`, PostgreSQL 17;
- evidência detalhada: [`../releases/v1/v1-closure-evidence.md`](../releases/v1/v1-closure-evidence.md).

Commits documentais posteriores em `main` não mudam esse SHA de release. O
acesso SSH temporário do fechamento foi revogado; uma nova manutenção na VPS
exige credencial temporária própria, alvo nominal, rollback e nova revogação ao
final. Mantenha o console de recuperação da Hostinger disponível.

## Incidente 23/10

Registro do incidente de 23/10/2026: a VPS nova estava com Clerk de teste e
Brevo desligado, além do IP remetente sem autorização. A correção informada foi
copiar as chaves Clerk da instância PROD, configurar `BREVO_SEND_MODE=live`,
autorizar o IP no Brevo e aplicar o override de logs na VPS (`json-file`, 10 MB,
cinco arquivos). Nenhum segredo é registrado aqui.

Na próxima troca de VPS, conferir que as chaves Clerk usam os prefixos
`sk_live_` e `pk_live_`, revisar `BREVO_SEND_MODE` conforme a autorização vigente,
confirmar os IPs de saída autorizados no Brevo e validar a rotação de logs
(`json-file`, `max-size: 10m`, `max-file: 5`). Mantenha os gates de efeito
fechados até uma autorização operacional própria.

## 2. Travas obrigatórias no primeiro deploy

```ini
APP_ENV=production
APP_BASE_URL=https://api.igreja12.com.br
FRONTEND_URL=https://app.igreja12.com.br
ALLOW_REAL_SENDS=false
ASAAS_BILLING_ENABLED=false
BROADCAST_ASYNC_ENABLED=false
CALENDAR_OAUTH_RETURN_ORIGINS=https://admin.igreja12.com.br
```

- `ALLOW_REAL_SENDS=false` bloqueia efeitos externos, mas o cron pode cancelar
  definitivamente pendências de `notification_outbox` em lotes. Somente após
  o agendador V3 observar o fechamento ele grava `gate_open=false`; a
  reabertura observada cria nova época e não reagenda consolidações anteriores.
  Sem essa observação, pendências antigas podem voltar a ficar elegíveis. Em produção,
  conexão Evolution e envios Brevo retornam erro controlado. Antes de fechar
  o gate, seguir o inventário e a decisão nominal de
  [BACKEND-RELEASE-MANUAL.md](../../deploy/BACKEND-RELEASE-MANUAL.md), inclusive
  o destino de itens cancelados, remanescentes e fontes V3 pré-época.
- `ASAAS_BILLING_ENABLED=false` mantém toda mutação financeira Asaas desligada
  mesmo depois de `ALLOW_REAL_SENDS=true`. Cobrança só é possível com os dois
  opt-ins; leituras de reconciliação e o webhook autenticado continuam ativos.
- `BROADCAST_ASYNC_ENABLED=false` mantém o worker persistente inativo e faz
  qualquer novo comunicado falhar antes de ser persistido; não existe fallback
  síncrono capaz de contornar o ledger/heartbeat.
- A ativação de cada flag exige recriar todos os processos da aplicação que a
  consomem (`backend`, `queue-worker`, `cron-worker` e `broadcast-worker`); elas
  são lidas no boot e ficam em cache por processo.

## 3. Variáveis secretas e integrações

Obrigatórias para o boot:

```text
CLERK_SECRET_KEY
CLERK_JWT_ISSUER
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
DATABASE_URL
SECRETS_ENCRYPTION_KEY
SESSION_JWT_SECRET
EVOLUTION_API_KEY
EVOLUTION_WEBHOOK_SECRET
EVOLUTION_POSTGRES_PASSWORD
REDIS_URL
```

Integrações:

```text
ASAAS_API_URL
ASAAS_API_KEY
ASAAS_WEBHOOK_TOKEN
ASAAS_BILLING_ENABLED
BREVO_API_KEY
BREVO_FROM_EMAIL
BREVO_FROM_NAME
BREVO_SEND_MODE
BREVO_CANARY_RECIPIENTS
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI
```

`OPENAI_API_KEY` pode ficar vazio porque a aplicação aceita credencial BYO por
igreja. `GOOGLE_CALENDAR_ACCESS_TOKEN` é legado e pode ficar vazio; o fluxo
novo usa OAuth por igreja. Nunca imprimir, versionar ou incluir o `.env` no
tarball de deploy. O pacote de backup é uma exceção operacional controlada:
fica restrito a root e só sai da VPS criptografado, conforme o runbook de
backup.

`AGENT_RUNTIME_DATABASE_URL` permanece vazio enquanto a D2A estiver inativa.
Merge ou deploy do código não provisiona credencial, não habilita login da
role e não conecta o worker ao runtime privado. Um gate posterior precisa
provar a migration no ambiente alvo, provisionar a credencial por canal
secreto, validar a role dedicada e manter a URL diferente de `DATABASE_URL`.

O Brevo inicia com `BREVO_SEND_MODE=off`. Para um teste controlado, usar
`canary` e preencher `BREVO_CANARY_RECIPIENTS` com a lista CSV de destinatários
autorizados; lista vazia ou malformada bloqueia o envio. Promover para `live`
só depois da verificação do canário e com reinício dos processos que consomem
essas variáveis.

## 4. Migrations do Supabase

### Estado corrente (2026-09-26)

- **Processo:** `backend/scripts/migrate.py` ([runbook de migrations](../../backend/migrations/README.md);
  planejamento em [ROADMAP.md](../../ROADMAP.md)): um arquivo por vez, numa transação, com o
  nome registrado no ledger na mesma transação. `apply_migrations.py` e os
  executores catalog-bound seguem pausados (`archive/governanca-2026-09`).
- **Ledger oficial único:** `public.schema_migrations` em PROD, criado em
  2026-09-26 (colunas `name`, `applied_at`, `origem`; RLS sem FORCE; nenhum
  privilégio para `anon`/`authenticated`). Registro nominal inicial de 69
  migrations: 63 `PROVA_OBJETO` (objetos conferidos no catálogo) e 6
  `BASELINE_V1_HISTORICO` (só dados, sem objeto a provar). As 6 são exceção
  aceita pelo proprietário em 2026-09-26: `0005_seed`, `0007_remove_demo_data`,
  `0009_unify_system_managers`, `20260708_164756`, `20260808_014425` e
  `20260808_023500`; o `migrate.py` nunca vai reaplicá-las. Linhas novas do
  `migrate.py` recebem `origem = MIGRATE_PY` (a primeira:
  `20260926_191500_agent_public_profile.sql`). O ledger nativo
  `supabase_migrations.schema_migrations` (32 linhas) passa a ser só histórico:
  não escrever nele nem usá-lo para decidir aplicação.
- **Pendentes em PROD, cada uma com gate próprio e nunca em lote:**
  `20260711_023515` e `20260711_152127` (só dados, sem prova de aplicação),
  `20260925_183811` e `20260926_120446`. A d1a `20260827_175634` e as 7 migrations
  do WhatsApp foram aplicadas em 2026-10-14 (ledger 70 -> 78; ver
  `docs/sprints/2026-10-14-migrations-hardening-ensaio.md`). Desde
  2026-09-27, d2a `20260827_230003`, d2b2 `20260828_045213` e d2b2b3
  `20260828_094914` estão pausadas (`OPERATIONAL_AUTHORIZATION=BLOCKED`, plano
  §3.3) e saíram do `status`.
- **Regras:** local primeiro: `./dev.sh reset` recria o banco local do zero
  com todas as migrations não pausadas e os dados fictícios
  ([`AMBIENTE-LOCAL.md`](AMBIENTE-LOCAL.md)). O DEV na nuvem está parado desde
  2026-09-27 e não é mais pré-requisito. PROD recebe migration só no release;
  backup verificado imediatamente
  antes; o pooler do Supabase ignora `PGOPTIONS` e o CLI não define
  `lock_timeout`, então migration que toma `ACCESS EXCLUSIVE` roda com
  `SET LOCAL lock_timeout` na mesma transação (até o `migrate.py` ganhar essa
  opção); os default privileges do Supabase concedem `arwdDxtm` a `anon` e
  `authenticated` em toda tabela nova de `public`, então migration que cria
  tabela revoga na mesma transação.
- Evidência: `docs/sprints/2026-09-26-prod-sessao-a-ledger-e-deploy.md`.

### Histórico (até 2026-09-25; não é procedimento corrente)

> **Bloqueio de 2026-09-04 (supersedido pelo processo do MVP e pelo estado
> acima):** não existia comando de aplicação operacional liberado.
> `apply_migrations.py` é legado e não deve ser invocado diretamente.
> `apply_migrations_catalog_bound_v2.py` bloqueava `status`, `harden-ledger`,
> `bootstrap-ledger` e `apply` antes da conexão. Os registros abaixo descrevem
> história, não autorização atual.

Existiam dois históricos diferentes:

- `supabase_migrations.schema_migrations`, ledger nativo do Supabase;
- `public.schema_migrations`, ledger de controle do executor local de arquivo
  único.

Eles não são equivalentes. Nome, ordem ou presença em um deles não autorizam
copiar, preencher, reaplicar ou registrar entradas no outro. (Em 2026-09-26 o
proprietário aceitou, como exceção nominal, registrar no ledger público as 6
migrations só de dados com evidência histórica; ver "Estado corrente".) O preflight PROD
de 2026-08-28 observou `public.schema_migrations` ausente e
`M06_MIGRATION_DATABASE_URL` não provisionada naquele executor. O estado vivo
atual desses itens não foi revalidado. `bootstrap-ledger` foi
integrado em `main` pela PR #323 e comprovado apenas offline, ainda não aplicado,
e não altera esse estado. O merge
`3a5789c784017ab15a43e28c4270d25af8618359` gerou Preview e Production
automáticos do frontend na Vercel; essa metadata não prova backend, banco,
runtime ou aplicação do bootstrap.

`bootstrap-ledger` cria somente um ledger público vazio no contrato owner-only;
ele não reconstrói histórico e não libera `status` ou `apply`.

O pacote deny-state e o verificador stdlib separado do runner, comprovados
offline sobre a base `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram
integrados pela PR #325, HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no
merge `ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](../decisions/2026-08-28-migration-history-reconciliation-contract.md).
O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES HUMANAS PENDENTES / NÃO
APLICADO`. O verificador não acessa banco, rede,
ambiente ou variáveis de ambiente, não executa SQL, DML ou escrita e todo
sucesso estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

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
[`2026-08-29-offline-canonical-schema-derivation.md`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não muda este runbook.
`OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`2026-08-29-offline-canonical-schema-derivation.md`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
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

Antes de qualquer aplicação futura, somente depois da abertura de um gate
nominal específico e da liberação de um executor catalog-bound:

1. provar o ref `pffafnchtxbimpwyaczq`;
2. listar separadamente, em preflight somente leitura autorizado, o ledger
   nativo e o ledger público, sem inferir equivalência;
3. materializar snapshot privado do SHA exato e validar o head corrente;
4. reproduzir o catálogo no PostgreSQL 17 descartável, validar a superfície
   `TENANT` coberta e revisar manualmente o SQL e seus limites não cobertos;
5. usar somente o entrypoint catalog-bound autorizado, primeiro em DEV;
6. verificar colunas, constraints, FORCE RLS, policies, ACLs e advisors;
7. abrir decisão e gate independentes antes de qualquer repetição em PROD.

Esta lista é uma pré-condição futura; ela não libera o runner atual.

Já registradas em PROD em 2026-08-05:

- `billing_setup_configuration_20260730`;
- `calendar_oauth_flows_pkce_20260731`;
- `calendar_account_identity_binding_20260801`;
- `broadcast_delivery_20260805`;
- `calendar_fk_indexes_20260805`;
- `security_definer_execute_hardening_20260805`.

Reconciliadas no ledger durante o fechamento da V1, sem reaplicar o DDL que já
estava presente:

- `20260810_031050_explicit_deny_policies_for_closed_tables` — versão
  `20260810031050`;
- `20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade` —
  versão `20260810042300`.

Em 2026-08-22, o preflight read-only reconfirmou 53/53 tabelas públicas com
RLS, quatro policies M06 exatas, nenhuma ACL efetiva de `anon`/`authenticated`
nas tabelas fechadas e zero operação automática `prepared` inválida. Não
reaplique essas migrations; qualquer correção futura é forward-only.

A migration de broadcasts não ativa broadcasts legados e não faz backfill.

A migration `20260824_180000_asaas_formal_isolation.sql` foi aplicada em
Supabase PROD em 2026-08-24 pelo mecanismo nativo de migrations, registrada no
ledger `supabase_migrations.schema_migrations` como versão `20260824202348` e
nome `asaas_formal_isolation_20260824`. O preflight confirmou ausência de IDs
Asaas duplicados em `subscriptions`. A verificação pós-aplicação confirmou:

- índices únicos parciais dos IDs remotos e das referências `pastorai-`;
- índices parciais das operações financeiras abertas por idade;
- tabela fechada `asaas_webhook_receipts`, com RLS, policy de negação e sem
  privilégios para `public`, `anon` ou `authenticated`;
- nenhuma atualização ou adoção automática de recursos Asaas legados.

### Isolamento da conta Asaas compartilhada

O PastorAI só pode alterar recursos cuja `externalReference` use o namespace
reservado `pastorai-`. O customer recebe uma referência estável por igreja; a
assinatura e cada cobrança recebem a chave da operação durável. Recursos sem
esse marcador são externos ou legados e devem ser apenas inventariados.

Toda mutação revalida a propriedade no Asaas antes do `POST` ou `PUT`. As
buscas de conciliação percorrem todas as páginas. O webhook exige o ID oficial
do evento e o grava em `asaas_webhook_receipts` na mesma transação da mudança
de domínio. Entrega duplicada retorna sucesso sem reaplicar o evento.

`restore_payment` não é tratado como idempotente. A aplicação persiste e
reclama uma operação durável antes do restore; requests concorrentes nunca
repetem o `POST` enquanto o resultado estiver ambíguo.

Após o hardening, o advisor de segurança mantém um único `WARN` intencional:
`authenticated` pode executar `current_igreja_id()`, pois as policies RLS
`tenant_isolation` dependem dessa função. `anon` não pode executá-la; as funções
de trigger `fn_subscription_autoupgrade()` e `rls_auto_enable()` também não são
executáveis por `anon` nem `authenticated`.

## 5. Deploy reproduzível do backend

A VPS não é a fonte de verdade. O artefato vem de um checkout limpo do SHA
mergeado. `backend/Dockerfile`, `backend/.dockerignore` e
`deploy/docker-compose.yml` são versionados.

Na estação de deploy:

```bash
git fetch origin
git worktree add --detach <diretorio-temporario> <SHA_EXATO_DE_MAIN>
```

Na VPS, cada SHA recebe um diretório novo. O diretório legado
`/opt/pastorai-lionclaw` é apenas rollback histórico e não é o alvo de novos
deploys. Antes de ativar um release:

- extrair o tarball em `/opt/pastorai-releases/<sha>`;
- copiar o `.env` do release ativo para o candidato, sem imprimi-lo;
- manter ambos os arquivos com modo `600`;
- não copiar `.git`, caches, testes, arquivos `.env*` nem dependências locais;
- não remover volumes `redis_data`, `evolution_pg_data` ou
  `evolution_instances`.

O procedimento manual de build/up foi substituído pelo
[`BACKEND-RELEASE-MANUAL.md`](../../deploy/BACKEND-RELEASE-MANUAL.md).
Usar somente o workflow manual e o script revisado no SHA exato, depois dos
gates nominais e do inventário read-only. O preflight registra banco, usuário,
endereço e porta, valida ledger nos dois sentidos e schema/RLS; os quatro
serviços são criados parados e têm seus gates inspecionados antes de start.
Não executar `docker compose up` sem `--no-start` como atalho: isso iniciaria efeitos antes da
comprovação dos gates. Allowlist e SHA mínimo seguros são configuração
obrigatória; CI não comprova o estado de PROD. Os SQLs verbatim de ledger e
inventário, definição do conjunto V3, prazo numérico e prova do cron estão no
runbook acima. Ausência de marcador ou prova insuficiente exige PARE.

Portas públicas proibidas:

- backend: somente `127.0.0.1:8000:8000`;
- Evolution: somente `127.0.0.1:8080:8080`.

Nginx é o único ponto público para `api.igreja12.com.br`. Depois do deploy,
confirmar que `IP:8000` e `IP:8080` recusam conexão externa.

## 6. Worker persistente de broadcasts

O serviço sobe no Compose padrão e fica ocioso enquanto as duas flags estão
desligadas. Ele publica heartbeat no Redis; a API só aceita `202` para envio
assíncrono/agendamento quando esse heartbeat está fresco.

Pré-condições:

- migration aplicada e verificada;
- backend novo saudável;
- Evolution conectada;
- `ALLOW_REAL_SENDS=true`;
- `BROADCAST_ASYNC_ENABLED=true` no backend e worker;
- canário com um único destinatário autorizado.

Ativação:

```bash
cd /opt/pastorai-current/deploy
docker compose config --quiet
docker compose up -d --build backend queue-worker cron-worker broadcast-worker
docker compose ps backend queue-worker cron-worker broadcast-worker
```

O ledger considera `aceito` apenas HTTP 2xx da Evolution. Resultado ambíguo
vira `desconhecido` e não recebe retry automático. O reaper de lease também
quarentena como `desconhecido`; nunca reenvia uma tentativa que possa ter
atravessado a rede. Falhas comprovadamente anteriores ao envio usam backoff
exponencial e respeitam `Retry-After`; indisponibilidade da Evolution não
consome o orçamento de retry.

## 7. Deploy do frontend

Implantar a partir do mesmo SHA exato de `main` usado como evidência:

```bash
cd <checkout-limpo>/frontend
vercel --prod
```

No projeto Vercel `pastorai-frontend-prod`, confirmar sem revelar valores:

- `NEXT_PUBLIC_API_URL` presente em Production, apontando para
  `https://api.igreja12.com.br`. É a única variável que o código do painel lê;
  sem ela o build de produção falha de propósito;
- aliases `app.`, `admin.` e `painel.igreja12.com.br`;
- publicação automática continua desligada (`frontend/vercel.json`,
  `git.deploymentEnabled: false`). Não religar.

O painel envia o login à API por `Authorization: Bearer`, sem cookie; a CSP
(só relatório) é definida pelo próprio painel. Na primeira virada, a publicação
do painel é o passo J8, com SIM próprio (seção 12.5).

## 8. Smokes sem efeitos externos

Com `ALLOW_REAL_SENDS=false` **e** `BREVO_SEND_MODE=off`:

```bash
curl -fsS https://api.igreja12.com.br/health
curl -fsS https://api.igreja12.com.br/ready
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
docker compose ps
```

Validar também:

- CORS para `app.`, `admin.` e `painel.`;
- login com usuário de teste que exista na instância Clerk PROD;
- recuperação de senha retorna resposta neutra e não envia e-mail (supressão
  esperada enquanto o gate estiver fechado);
- isolamento das portas 8000/8080;
- ausência de placeholders no `.env`;
- frontend sem referências ao Supabase DEV ou localhost.

Mesmo depois desses smokes, mantenha `ASAAS_BILLING_ENABLED=false` e
`BREVO_SEND_MODE=off` enquanto as igrejas-piloto estiverem em cortesia. Não
habilite a flag financeira sem inventário das assinaturas rastreadas, backup
fresco e canário financeiro separado.

Somente após esses smokes decidir, em gates separados, `ALLOW_REAL_SENDS=true`
para os provedores globais e `BREVO_SEND_MODE=canary` para e-mail. A leitura do
QR da Evolution e qualquer canário de e-mail/WhatsApp/cobrança ocorrem em uma
janela controlada. O recebimento real do e-mail de recuperação pelo Brevo exige
allowlist com uma conta de teste e um único envio observado; `live` continua
sendo uma promoção posterior.

## 9. Monitoramento e backup

`/health` é liveness barata. `/ready` verifica DB e Redis como dependências
obrigatórias; Evolution, workers e `billing_operations` aparecem como sinais
opcionais. Operações de pagamento ou criação de assinatura em `creating` ou
`reconciling` há mais de uma hora tornam `billing_operations=stale`. Uma falha
opcional gera `degraded` e alerta, mas não derruba a API nem cria restart loop.

Após o release ser aprovado e o symlink estável apontar para ele:

```bash
cd /opt/pastorai-current
MONITOR_ALERT_EMAIL=seu-email@dominio.com sh deploy/monitoring/install.sh
systemctl list-timers pastorai-monitor.timer pastorai-backup.timer --all
journalctl -u pastorai-monitor.service -n 50 --no-pager
```

O modo padrão preserva o cron M02, não habilita `pastorai-backup.timer`; o
primeiro tick do monitor ocorre depois do commit da instalação e uma degradação
operacional não desfaz os arquivos/timer válidos. Se houver cron legado junto de timer
habilitado ou ativo, o instalador aborta antes de escrever arquivos para impedir
dois backups diários. Arquivos, permissões e estado anterior dos timers são
restaurados se qualquer etapa da instalação falhar. Uma migração
futura para timer exige remover o cron em gate operacional próprio e então usar
explicitamente `PASTORAI_BACKUP_TIMER_MODE=enable`; essa opção apenas habilita o
timer e não executa um backup. A raiz canônica continua sendo
`/root/pastorai-backups`. O backup privilegiado compara o SHA-256 real do
pacote com seu sidecar antes de publicar o manifesto sanitizado
`/var/lib/pastorai-backup/backup-status.json`. A URL do banco é transformada em
arquivos libpq temporários `0600`, montados apenas para o `pg_dump`; URL e senha
não ficam em argv ou ambiente de Python, Docker, `pg_dump` ou outros auxiliares.
O cron M02 deve receber o pacote completo por `sudo bash
deploy/install-legacy-backup.sh`; o entrypoint em `/usr/local/sbin` verifica o
auxiliar fixo e seu checksum, ambos arquivos regulares sem symlink nem hardlink
(`nlink=1`), antes de qualquer backup ou pausa de containers.
As units usam `ProtectSystem=strict` e paths de escrita explícitos. O monitor
usa `DynamicUser`, `ProtectHome=true`, não acessa Docker, `.env` ou `/root` e
valida somente o manifesto. O backup é uma unidade privilegiada separada porque
o socket Docker é root-equivalente; esse residual é documentado e não deve ser
confundido com uma allowlist completa contra script comprometido.
O workflow `production-monitor.yml` faz os checks públicos e mantém uma issue
deduplicada no GitHub. Procedimento, estados e limites de disaster recovery:
[`deploy/monitoring/README.md`](../../deploy/monitoring/README.md).

### Diagnóstico de alerta do PostgREST

Em um alerta já analisado, a API de saúde reportou o componente `rest` como
`UNHEALTHY`, com uma mensagem genérica de falha. Os logs disponíveis não
permitiram identificar a causa.
[API de saúde](https://supabase.com/docs/reference/api/v1-get-services-health).

O `/ready` respondeu `200` nas amostras próximas do alerta. Essa rota verifica
PostgreSQL via SQL e Redis, sem passar pela Data API.

Uma resposta `401` da raiz OpenAPI (`/rest/v1/`) com chave pública é compatível
com a restrição de acesso a essa rota. Esse teste não mede a disponibilidade do
PostgREST. Os registros consultados não mostraram chamadas de consumidores da
Data API. A evidência disponível deixa o impacto indeterminado.
[Restrição da raiz OpenAPI](https://github.com/orgs/supabase/discussions/42949).

Se o alerta voltar, registre o horário e o estado de `rest` no registro
operacional interno. Compare com o `/ready` e com eventuais erros `5xx` de
consumidores no gateway. Use essa correlação para decidir se há evidência de
impacto antes de propor uma intervenção.

## 9.1. Atestação de ambiente permanece bloqueada

O tooling separado de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A decisão está em
[`2026-08-30-read-only-environment-attestation-tooling.md`](../decisions/2026-08-30-read-only-environment-attestation-tooling.md).
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
[`diagnóstico do preflight de identidade de DEV`](../decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
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
runtime. PROD continua fora. Nenhum comando deste runbook é liberado por esse
gate. Posteriormente, esse caminho foi supersedido pelos diagnósticos de fase e
pelo probe transport-only executados sob autorizações humanas nominais
próprias. O identificador permanece somente como registro histórico e não é
gate corrente nem próximo hoje.

A política de permissões foi implementada e comprovada offline pelo snapshot
privado descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](../decisions/2026-09-03-trusted-repository-snapshot-policy.md).
O gate
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE` foi
consumido somente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](../decisions/2026-09-03-migration-environment-attestation-executor-v2.md).
O executor não pode ser usado neste runbook enquanto autorização nominal,
runtime/dependências e anti-replay não tiverem trust anchors externos. Não
forneça DSN, CA, chave, nonce ou registro de autorização ao candidato atual.

O commit local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, filho de
`947af39d35544700188461d8c99332df70b57e07`, implementa autoria source-only
`draft`/`prepare-head` apenas `TENANT`, snapshot validado, wrapper catalog-bound
v2 somente `list` e replay em PostgreSQL 17 descartável/loopback. Não está
integrado e não houve push, PR ou CI remoto.

No mesmo SHA, o verificador longitudinal confirmou 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
A focal terminou `274 passed, 6 skipped`; a prova real PG17 terminou `6/6`, com
E2E sintético de 76ª migration `TENANT`; duas revisões independentes concluíram
`P0=0` e `P1=0`. O workflow candidato usa banco PG17 descartável para replay,
mas nunca banco compartilhado, DEV/PROD ou o runner legado de aplicação. Esses
resultados não autorizam o uso deste runbook.

`apply_migrations.py` continua invocável como risco residual. O replay não cobre
views, outros schemas, funções, roles/memberships, `BYPASSRLS`, grants nomeados,
schema/default ACL ou semântica ampla DML/DDL. A worktree/migrations foi
observada em `0755` e SQL em `0644`, mas ancestrais permanecem `0775` e o
`chmod` local não é durável; o P2 global segue aberto.

DEV continua `BLOCKED_LEDGER_DIVERGENCE`, PROD continua
`BLOCKED_EVIDENCE_INSUFFICIENT`, a falha TLS DEV histórica não foi resolvida e
revisão v3, cutover, atestações vivas e apply permanecem pendentes.
`operational_authorization=false` e `next_stage_authorized=false`.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto, não consumido e substituído. O único estágio corrente fechado é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, restrito a
preflight remoto read-only, push da branch, abertura de PR e observação do
CI/Preview. Não autoriza merge, banco compartilhado, DEV, PROD, migration,
runner de aplicação ou flags. Trust anchors externos permanecem futuros, não
correntes e não autorizados.

## 10. Rollback

- Backend: antes do release, comprovar checker e manifesto anterior válidos,
  além dos preflights anterior e candidato em modo somente leitura, cada um
  com seu próprio manifesto. Falha impede build e substituição dos serviços;
  ausência de checker ou manifesto é recusada antes da cópia da configuração.
  Um release legado sem checker requer recuperação revisada antes da janela.
  Se houver falha após a substituição, parar os quatro serviços e executar o preflight do código anterior
  com seu próprio manifesto e imagem antes de qualquer start, conforme
  [`BACKEND-RELEASE-MANUAL.md`](../../deploy/BACKEND-RELEASE-MANUAL.md).
  Ausência de checker, divergência do ledger ou incompatibilidade mantém gates
  fechados e exige plano adiante revisado. Conferir Compose e gates dos
  contêineres parados antes de iniciar; conferir novamente depois. Symlink só
  muda após saúde comprovada; preservar configuração ativa e volumes.
- Frontend: promover o deployment Vercel anterior.
- Banco: migrations aditivas não são revertidas automaticamente. Corrigir por
  nova migration revisada; não executar rollback destrutivo improvisado.
- Asaas: fechar imediatamente `ASAAS_BILLING_ENABLED=false` em todos os
  processos e depois `ALLOW_REAL_SENDS=false` se a janela exigir contenção
  global. Não apagar, cancelar, restaurar ou recriar recursos remotos durante
  o rollback; primeiro inventariar os IDs `pastorai-` e reconciliar as
  operações locais.
- Broadcast: fechar primeiro `BROADCAST_ASYNC_ENABLED=false` no backend,
  queue worker, cron worker e broadcast worker, recriar os quatro processos e
  confirmar que a interface voltou a exibir os envios como desativados. Usar
  `ALLOW_REAL_SENDS=false` somente se a contenção precisar abranger todos os
  provedores. Não apagar broadcasts, execuções ou entregas, não limpar leases e
  nunca reenviar automaticamente resultados `desconhecido`; registrar os
  totais por status antes e depois da contenção.

## 11. Evidência mínima de conclusão

Registrar:

- SHA de `main` implantado;
- IDs das migrations aplicadas;
- resultado de testes/CI;
- `docker compose ps`;
- liveness/readiness local e pública;
- timers do monitor/backup e data do último backup válido;
- CORS e login;
- deployment/aliases Vercel;
- estado explícito de `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED` e
  `BROADCAST_ASYNC_ENABLED`, incluindo a prova pós-restart de que billing
  permaneceu fechado por padrão, sem imprimir o `.env`.

## 12. Primeira virada da instalação legada (janela A1–A10)

Vale só para a primeira troca do sistema antigo pelo novo. Os releases
seguintes usam o [deploy manual](../../deploy/BACKEND-RELEASE-MANUAL.md).
Nada aqui autoriza executar: cada **SIM** abaixo é uma frase do Raniel no
chat, para aquela ação, aquele ambiente e aquele horário. Os códigos impressos
pela ferramenta (digests e `a10_token`) só evitam erro de digitação; não são
autorização.

Ferramenta: `deploy/first_transition_window.py` (modos `prepare`, `check`,
`check-bindings`, `rehearse-backup`, `run` e `a10`). O modo `run` vai da
contenção até a A9 numa execução só. O modo `a10` é uma execução separada.

### 12.0 A VPS é compartilhada: a janela para só a Igreja 12

A VPS de produção também roda outros sistemas do Raniel (leitura de
12/11/2026): `olaki-whatsapp` (Evolution, Postgres e Redis próprios),
`sites-api`, `site-emcorr` (PocketBase), `worker` do GravAI, o site Fowler
(contêineres parados; o nginx encaminha para fora) e o serviço
`hermes-gateway`. Cada sistema tem sua rede Docker, seus volumes e seu backup.
A Igreja 12 usa só a rede `pastorai_default` e os contêineres `pastorai_*`;
o banco dela é o Supabase, fora da VPS.

Compartilhados com os outros: o nginx (portas 80/443, um processo para todos
os sites), o daemon Docker, o firewall (ufw/nftables), o certbot e a CPU,
memória e disco (1 CPU, 4 GB).

O que a janela faz em cada um, e por que não atinge os outros:

| Ação da janela | Alcance |
|---|---|
| Site em manutenção (503) | Só o `server` da API da Igreja 12, pelo `include` que existe só no arquivo dela. Antes de qualquer efeito a ferramenta recusa (`window-nginx-shared`) se outro arquivo incluir ou puder carregar a pasta da manutenção, ou se outro site usar o mesmo nome. |
| `nginx -t` e `systemctl reload nginx` | Único efeito no nginx inteiro. É recarga sem queda; os arquivos dos outros sites não mudam. Se o `nginx -t` falhar, nada é recarregado. |
| Bloqueio Evolution→backend | Tabela nftables própria (`bridge igreja12_window`) que só derruba a porta 8000 dentro da bridge da rede `pastorai_default`. Não mexe no ufw nem nas regras do Docker. |
| Parar e religar processos | Só os quatro IDs fixos do manifesto, conferidos na rede da Igreja 12. Candidato com projeto Compose próprio e vazio; backup da janela com rede interna própria. |
| Pausar o backup automático | Só o arquivo `/etc/cron.d/pastorai-backup` (passo J2). Os backups dos outros são timers próprios e continuam. |

**Proibido na janela** (atinge todos os sistemas): `systemctl stop` ou
`restart` de `nginx`, `docker`, `containerd` ou `cron`; `ufw`/`iptables`;
`docker compose down` ou `docker system/network/volume prune`; reiniciar a VPS.

**Edição única do site (passo V6, SIM próprio):** o certificado continua
**dentro do arquivo da Igreja 12**, como o certbot deixou: nunca mover
`ssl_certificate` para o `nginx.conf` ou `conf.d`, porque isso muda o
certificado padrão dos outros sites. A pasta `/etc/nginx/igreja12-window`
só pode ser incluída pelo site da Igreja 12; a ferramenta confere isso a
cada observação.

**Carga:** o backup da janela com restore em clone usa CPU e disco da mesma
VPS. Os outros sistemas podem ficar mais lentos nesse trecho; o V7/J10 mostra
se algum deixou de responder.

#### Conferência dos outros sistemas (V7 antes, J10 depois; só leitura)

Na VPS, gravar a foto antes da janela e repetir no fim:

```bash
umask 077
{
  sudo docker ps -a --format '{{.Names}} {{.State}}' | grep -v -e '^pastorai_' -e '^igreja12-' | sort
  sudo docker ps -q | xargs sudo docker inspect -f '{{.Name}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' | grep -v -e '^/pastorai_' -e '^/igreja12-' | sort
  for name in $(sudo nginx -T 2>/dev/null | grep -oP '^\s*server_name\s+\K[^;]+' | tr ' ' '\n' | grep -v -x -e '_' -e 'api.igreja12.com.br' | sort -u); do
    printf '%s %s\n' "$name" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 --resolve "$name:443:127.0.0.1" "https://$name/")"
  done
  for url in http://127.0.0.1:8087/ http://127.0.0.1:8090/health http://127.0.0.1:18101/api/health; do
    printf '%s %s\n' "$url" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$url")"
  done
  systemctl is-active hermes-gateway nginx docker cron
} > ~/outros-sistemas-$(date -u +%Y%m%dT%H%MZ).txt
```

Comparar os dois arquivos (`diff`). Esperado: nenhuma diferença. O código
HTTP de cada sistema é comparado com o dele mesmo antes da janela (alguns
respondem 404 ou 500 na raiz por desenho). Qualquer diferença: parar, não
reiniciar nada de outro sistema por conta própria e avisar o Raniel. O
arquivo não tem segredo nem dado de pessoa; fica só na VPS.

### 12.1 Antes da janela (véspera)

| Passo | O que acontece | SIM do Raniel |
|---|---|---|
| V1 | Leitura só de metadados do alvo: serviços e IDs, gates **por nome e valor** dos quatro processos antigos, cron do host, Redis, `release_preflight.py`, `migrate.py status`, duplicidades = 0. Na sessão do aplicador (mesma DSN de `MIGRATION_DATABASE_URL`, sem `SET`): `SHOW statement_timeout` e `rolsuper`/`rolbypassrls` da role; a janela não confere nenhum dos dois e `migrate.py` herda o padrão da role. Timeout curto pode cortar backfill ou índice depois do ponto de não retorno: valor diferente de `0` exige decisão antes do SIM 3, sem alterar nada no SIM 1. | **SIM 1** (leitura no alvo) |
| V2 | Conferir que o arquivo privado do candidato tem os mesmos gates por finalidade do antigo (piloto, agenda, V1a, V3). Os quatro gates principais ficam fechados nele; a A10 os sobrepõe com os valores antigos. Se algum gate por finalidade diferir, a verificação da A10 pode acusar cancelamento e conter. | dentro do SIM 1 |
| V3 | Ensaio sintético verde no SHA escolhido e os quatro checks do CI. | — |
| V4 | Aviso à equipe: todos serão deslogados; painel e WhatsApp ficam pausados durante a janela. | Raniel envia |
| V5 | Pré-requisitos do painel (seção 12.5): Vercel CLI logada na conta certa, checkout limpo do SHA ligado ao projeto, variáveis conferidas por nome, publicação automática desligada e ID do deployment atual anotado. | dentro do SIM 1 (só leitura) |
| V6 | Edição única do site nginx da API: pasta vazia `/etc/nginx/igreja12-window` (root, 0755) e a linha `include /etc/nginx/igreja12-window/*.conf;` logo após `server_name` no bloco 443, com backup, `nginx -t` e reload. Certificado, IPv6, cabeçalhos de proxy e o bloco de redirecionamento da porta 80 continuam como estão: a ferramenta aceita esse formato do certbot (seção "Topologia nginx nominal" do `RELEASE-LOTE-2026-10.md`). Na configuração dos bindings: `site_path` = `/etc/nginx/sites-available/pastorai-api-http` e `enabled_path` = `/etc/nginx/sites-enabled/pastorai-api-http` (é atalho na VPS, conferido em 12/11). | **SIM próprio** (edição na VPS) |
| V7 | Foto dos outros sistemas da VPS (seção 12.0): contêineres, saúde e código HTTP de cada um. Tudo precisa estar respondendo antes de abrir a janela. | dentro do SIM 1 (só leitura) |
| V8 | Preparar a VPS com o kit (seção 12.6): ferramenta no SHA aprovado, três arquivos de configuração, pastas do backup, imagem do Postgres, arquivo privado do aplicador, correção da linha repetida no arquivo do candidato e `prepare-layout`. Não toca no sistema antigo, no banco, no nginx nem nos gates. | **SIM próprio** (escrita na VPS) |
| V9 | Conferências sem efeito com o kit instalado: `prepare`, `check` (duas leituras do banco) e `check-bindings`; ensaio do backup da janela (`rehearse-backup`: cópia do banco, restore e as 51 migrations num clone isolado, na própria VPS). Regra de parada do timeout: o `seconds` do recibo precisa ficar abaixo de 60 (§12.6, fato 2). | dentro do SIM V8 |

### 12.2 Janela

| Passo | O que acontece | SIM do Raniel |
|---|---|---|
| J1 | Registrar início (UTC), operador, duração máxima em minutos e SHAs. `prepare` e conferência dos digests. | **SIM 2** (abrir a janela) |
| J2 | Pausar o backup automático do host (cron M02) **só da Igreja 12**: `sudo mv /etc/cron.d/pastorai-backup /root/pastorai-backup.cron.pausado` (nunca parar o serviço `cron` nem os timers dos outros sistemas) e confirmar que ninguém mais usa console, SQL Editor, MCP ou CLI do Supabase. | dentro do SIM 2 |
| J3 | `run`: antes de tocar no sistema antigo, a ferramenta **fotografa os quatro gates de cada processo antigo** (`transition-gate-snapshot`). Valor desconhecido recusa aqui, antes de qualquer efeito. | **SIM 3** (o `run` inteiro, J3 a J6, inclui o ponto de não retorno) |
| J4 | Bloqueia as duas entradas (site 503 e Evolution→backend), `restart=no`, SIGTERM e saída 0 dos quatro processos antigos; duas observações sem nenhuma escrita; linha de base das pendências (`transition-pending-baseline`); backup da janela com restore e replay em clone. | dentro do SIM 3 |
| — | **Até aqui ainda dá para voltar ao sistema antigo** (`resume_legacy`). | — |
| J5 | **PONTO DE NÃO RETORNO:** marcador da DDL e primeira migration. Depois dele o sistema antigo nunca volta (`post-ddl-resume-forbidden`). | dentro do SIM 3 |
| J6 | 51 migrations, uma por vez; candidato criado parado; só o backend sobe, com envios fechados, e passa no smoke; workers continuam parados; entradas continuam bloqueadas (A9). O resultado imprime `a10_token`. | dentro do SIM 3 |
| J7 | A10 (seção 12.3). | **SIM 4** (religar workers e envios como estavam) |
| J8 | Publicar o painel no mesmo SHA do backend e fazer o smoke dele (seção 12.5). Se falhar, voltar só o painel ao deployment anterior. | **SIM 5** (publicar o painel; inclui voltar o painel se o smoke falhar) |
| J9 | Religar o backup do host (`sudo mv /root/pastorai-backup.cron.pausado /etc/cron.d/pastorai-backup`, dono root e modo 644), conferir `AgentConfig` e Jev, registrar o encerramento. | — |
| J10 | Repetir a foto dos outros sistemas (seção 12.0) e comparar com a do V7: nenhuma diferença. | — |

**SIM 3** cobre o `run` inteiro: contenção, backup, migrations e A9. Como o
`run` não para entre o backup e a primeira migration, dizer SIM 3 é aceitar o
ponto de não retorno. Decisão do Raniel em 12/11/2026: um SIM 3 único
basta; não haverá SIM separado para as migrations.

**Se o smoke falhar depois da primeira migration (J6):** não há volta ao
sistema antigo. A ferramenta para e mantém tudo contido: site em manutenção,
entradas bloqueadas, workers nunca iniciados, processos antigos parados. Nada
é enviado e nada é cancelado. Preservar diário, backup da janela e evidências.
Decidir, por SIM próprio: corrigir adiante (novo SHA revisado e testado) ou
restaurar o **backup da janela** (`window_backup_id` do marcador, nunca o do
A6). Nunca restaurar de improviso.

O "rollback imediato pré-autorizado se o smoke falhar" (ROADMAP, 12/11) só
pode significar, depois do J5, essa contenção automática: voltar ao sistema
antigo com o banco já migrado não é seguro e a ferramenta recusa. Corrigir
adiante ou restaurar o backup da janela continuam exigindo SIM próprio.

### 12.3 A10: workers e envios de volta como estavam

Comando (só depois do SIM 4; o token é o `a10_token` impresso pela A9;
variáveis `$PY`, `$T` e `$ARGS` da seção 12.6):

```bash
$PY -E -s $T a10 $ARGS --expect-plan-digest <plan> --expect-window-digest <window> --a10-token <a10_token>
```

Não usar `python3 -I` com o caminho do script: o `-I` tira a pasta do script
do caminho de importação e a ferramenta nem carrega. `-E -s` ignora variáveis
`PYTHON*` e pacotes do usuário, que é o que se quer.

O que a A10 faz, em ordem:

1. Confere, sem efeito: foto dos gates presente e válida; releitura dos
   processos antigos igual à foto (se alguém mudou, recusa:
   `a10-gate-snapshot-divergent`); A9 intacta; banco com todas as migrations.
   Qualquer recusa aqui não muda nada: envios continuam fechados.
2. Recria os quatro contêineres do candidato **parados**, com um arquivo
   público que repõe, papel por papel, os valores da foto. Gate que estava
   fechado ou ausente continua fechado. Nenhum valor vem do código.
3. Inicia backend (smoke de novo), queue-worker, broadcast-worker e, **por
   último**, o cron-worker.
4. Abre as entradas: primeiro Evolution→backend, depois o site.
5. Verifica: os quatro rodando sem reinício e com gates iguais à foto;
   antigos parados; entradas abertas; e, se o envio estava ligado antes,
   nenhum cancelamento novo por gate fechado (`gate_fechado`) nem ativação V3
   marcada como fechada desde a linha de base.

**Por que as pendências ficam protegidas:** o cron novo só cancela pendência
por gate fechado quando roda com o gate fechado. Na A9 ele nunca roda. Na A10
ele só roda depois de recriado com os mesmos valores do sistema antigo. Então a
virada não cancela nada que o sistema antigo não cancelaria. A regra do
produto continua igual: se o gate já estava fechado antes da janela, ele
continua fechado e continua cancelando, como antes.

**Se a verificação falhar:** a ferramenta contém sozinha. Bloqueia as duas
entradas e para cron, broadcast, queue e backend (`restart=no` e parada). Não
reescreve os gates para fechado, porque um cron ligado depois com gate fechado
cancelaria pendências. Não volta ao sistema antigo e não reabre nada sozinha.
Resultado: site em manutenção, nada enviado. Próximo passo por SIM próprio.

**Repetir a A10** depois de concluída só reverifica; não reinicia nada. Se a
execução for interrompida no meio, repetir o mesmo comando retoma do diário:
um passo interrompido só é aceito se a inspeção provar o resultado exato;
senão a ferramenta recusa e contém.

### 12.4 Riscos que o Raniel precisa aceitar por escrito

Aceite por escrito do Raniel em 12/11/2026, no chat da sessão da A10: riscos 1,
2 e 3 abaixo. O 4 é decisão anterior dele (sem volta ao legado depois da
primeira migration); o 5 é limite técnico registrado.

1. **Escrita direta no Supabase durante a janela:** quem tem chave (SQL
   Editor, MCP, CLI, Data API, Storage) consegue escrever por fora do sistema.
   O código só confere zero sessões de escrita antes da DDL; escrita por Data
   API ou Storage pode não aparecer. O controle é a regra combinada: ninguém
   além do operador usa essas ferramentas na janela.
2. **WhatsApp e cobranças que chegarem durante a janela:** as entradas
   respondem 503. Não está verificado se a Evolution e o Asaas reenviam depois;
   mensagens e avisos de pagamento podem se perder.
3. **Backup automático da VPS:** precisa ser pausado no J2 e religado no
   J9 (só o arquivo da Igreja 12; seção 12.0). Um `pg_dump` durante as migrations pode segurar lock e fazer uma
   migration falhar (`lock_timeout` de 2 s), o que para a janela depois do
   ponto de não retorno.
4. **Depois da primeira migration não há volta ao sistema antigo:** só manter
   contido e corrigir adiante, ou restaurar o backup da janela por decisão.
5. **Proteção das pendências é por contagem:** a verificação olha dois
   contadores. Ela não substitui o inventário por finalidade do item V1.

### 12.5 J8: publicar o painel (SIM 5)

Decisão do Raniel em 12/11/2026: o painel novo vai ao ar logo depois da A10,
na mesma janela e com o **mesmo SHA** do backend. Só começa depois que a A10
terminou verde. Não mexe no backend, no banco nem nos gates.

**Pré-requisitos (V5, na véspera, só leitura):**

1. Vercel CLI instalada no computador do operador (`vercel --version`) e
   logada na conta/equipe dona do projeto `pastorai-frontend-prod`
   (`vercel whoami`; conferir a equipe com `vercel teams ls`).
2. Checkout limpo do SHA do backend, fora do checkout de trabalho, por
   exemplo `git worktree add --detach <pasta> <SHA>`; `git status` sem
   alterações. Em `<pasta>/frontend`, `vercel link` escolhendo o projeto
   `pastorai-frontend-prod` (nunca criar projeto novo).
3. Variáveis de Production conferidas **só por nome**
   (`vercel env ls production`): `NEXT_PUBLIC_API_URL` presente. Não usar
   `vercel env pull` nem imprimir valores.
4. Publicação automática segue desligada (`git.deploymentEnabled: false` em
   `frontend/vercel.json` do SHA) e nenhum deploy por Git foi religado.
5. Anotar o ID/URL do deployment de produção atual (hoje: o de 27/10, SHA
   `afdfb78d`). É o alvo da volta.

**Regra do painel sobre o backend `afdfb78d` (decisão de 12/11/2026):** o
backend da janela é `afdfb78d` e o painel vem do SHA da `main`. O J8 só
publica se o contrato da API do backend `afdfb78d` for igual ao que tipa o
painel (`frontend/openapi.json` do SHA do painel). Se houver **qualquer**
diferença, o J8 não publica nada: o painel atual fica no ar e o novo vai junto
com o backend no release seguinte. Conferência (no V5, no computador do
operador, na raiz do checkout, com a venv do backend ativa; sem acesso a
produção):

```bash
D=$(mktemp -d) && git archive afdfb78d backend/app | tar -x -C $D && mkdir -p $D/backend/scripts && git show <SHA>:backend/scripts/export_openapi.py > $D/backend/scripts/export_openapi.py && git show <SHA>:frontend/openapi.json > $D/painel.json && (cd $D/backend && python scripts/export_openapi.py --check --output $D/painel.json)
```

Esperado: `OPENAPI_OK`. Resultado de 12/11 (`afdfb78d` x `e9a8fc4a`):
idêntico byte a byte (sha256 `751108f0…70aa`). As mudanças de backend entre
os dois SHAs são internas (paginação do histórico feita no banco com a mesma
resposta, "dia da igreja" na data do DPA do Jev, tipos e consultas), sem rota,
parâmetro ou campo de resposta novo ou alterado. O E2E do painel roda contra
API simulada, então não testa o backend real; a prova é o contrato.

**Passo (depois do SIM 5):**

```bash
cd <pasta>/frontend
vercel --prod
```

Conferir que o deployment novo ficou em Production e que `app.`, `admin.` e
`painel.igreja12.com.br` apontam para ele.

**Smoke do painel contra a API nova (o Raniel entra com a conta dele; ninguém
digita senha por ele):** abrir `app.` e `admin.`; entrar; a tela inicial
carrega nome, igreja e menus do papel, sem "sessão indisponível"; abrir as
telas principais do menu (inclusive `/gestao`) só para leitura; sair e
confirmar que voltou ao login. Não enviar mensagem, não confirmar ações e não
mudar configurações durante o smoke. Registrar horário, deployment e resultado.

**Se o smoke falhar:** voltar só o painel ao deployment anotado no V5, pelo
Instant Rollback da Vercel (painel do projeto ou `vercel rollback <url>`).
É reversível e está coberto pelo SIM 5. Não mexer no backend, nos workers nem
nos gates: a A10 já terminou e continua valendo. Depois de um rollback, a
Vercel deixa de apontar os domínios para deploys novos até um "undo"/promote;
a próxima tentativa exige SIM próprio. Registrar o motivo.

**Janela de incompatibilidade entre o SIM 3 e o J8:** a comparação do código
de `afdfb78d` (painel no ar) com o SHA da janela não achou mudança no login
nem na sessão: as rotas `/auth/*` usadas pelo painel antigo e pelo novo são as
mesmas; `routers/auth.py`, `main.py` (CORS) e `config.py` do backend não
mudaram; nenhuma rota foi criada ou removida; o token vai por `Bearer`, sem
cookie; a CSP é do próprio painel, em modo relatório; e a única variável do
painel continua `NEXT_PUBLIC_API_URL`. Do J4 até a A10 a API responde 503 e o
painel antigo só mostra indisponibilidade. Entre a A10 (que reabre o site) e o
fim do J8, o painel antigo fala com a API nova: pelo código deve funcionar,
mas não foi testado ao vivo e não tem as correções de tela feitas depois de
`afdfb78d`. Para encurtar esse intervalo: V5 feito na véspera, J8 logo depois
da A10 e o aviso V4 pedindo que a equipe só use o painel depois do smoke do J8.
Manter o site em manutenção até o J8 não é possível sem mudar a A10, que reabre
as entradas do WhatsApp e do site juntas; pelo resultado acima, não é
necessário.

### 12.6 Kit e roteiro do dia

Preparado em 12/11/2026 com leitura só de metadados da VPS e do banco (nada
alterado). **Dois SHAs diferentes, por desenho:**

- **Backend publicado:** `afdfb78d71a53f2861632806e13cdda4662d7d63`, fixo na
  ferramenta (`APPLICATION_SHA`; aplicador `37c7d68d`). Outro SHA é recusado
  (`unreviewed-release`). As 51 migrations são as mesmas da `main`; as
  correções de backend feitas depois de `afdfb78d` só entram no release
  seguinte.
- **Ferramenta e painel:** o SHA da `main` que contém esta seção (`<SHA>`
  abaixo). Os quatro checks e o `synthetic-release` precisam estar verdes nele
  (V3).

**Kit (onde cada item fica na VPS):**

| Item | Local na VPS | Estado em 12/11 |
|---|---|---|
| Ferramenta no `<SHA>` (só a pasta `deploy/`) | `/opt/pastorai-releases/tool-<SHA>/deploy` | falta copiar (V8) |
| Repositório com os blobs de `afdfb78d` e `37c7d68d` | `/opt/pastorai-releases/repo` | pronto (clone de 31/10) |
| Python 3.13 com psycopg2 2.x | `/var/lib/pastorai-first-transition/venv/bin/python` | pronto (3.13.15, 2.9.12) |
| Configuração da transição | `/var/lib/pastorai-first-transition/window/first-transition.json` | gerado no kit; falta copiar |
| Configuração do backup da janela | `/var/lib/pastorai-first-transition/window/backup.json` | gerado no kit; falta copiar |
| Configuração das entradas e escritores | `/var/lib/pastorai-first-transition/window/bindings.json` | gerado no kit; falta copiar |
| Pastas do backup e do clone (root, 0700) | `/var/lib/pastorai-first-transition/window-backups` e `.../clone-work` | falta criar |
| Imagem do backup e do clone | `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929` (a mesma do CI) | falta baixar |
| Imagem do candidato | `sha256:b795374e…501c` (`pastorai-backend:afdfb78d`, revisão `afdfb78d`) | pronta |
| Pacote do backend | igual ao gerado pela ferramenta do repositório; manifesto `08c7696f…cbb`, tarball `5780362531fc8550c3e71cb6a99f4c4170694999263b1d86edf2b2d948116b7d` | pronto (`/var/lib/pastorai-first-transition/package`) |
| Layout do candidato e arquivo de espera da A9 | `/opt/pastorai-releases/afdfb78d…/` e `/var/lib/pastorai-first-transition/state/a9-hold.override.yml` | falta (`prepare-layout`, V8) |
| Arquivo privado do candidato | `/opt/pastorai-lionclaw/deploy/.env.v2` (root 0600) | existe; tem `ALLOW_REAL_SENDS=false` repetido: corrigir no V8 |
| Arquivo privado do aplicador | `/root/igreja12-janela.conf` (root 0600, uma linha `MIGRATION_DATABASE_URL=`) | falta; criado no V8 a partir do `DATABASE_URL` do `.env.v2`, sem ninguém ver o valor |
| Diário da janela | `/var/lib/pastorai-first-transition/state/journal` | vazio (não pode existir diário velho) |

Valores lidos em 12/11 que já estão nos arquivos: daemon `cca7e973…`, rede
`pastorai_default` (`3f9e8901…`, ponte `br-3f9e89014eac`), os quatro IDs
antigos e os três de apoio (iguais aos de 31/10), identidade do banco
`9b48b837…` e catálogo `b561d41f…` (o de 31/10 era de uma versão anterior da
consulta), 78 migrations no ledger, banco com 23 MB, PostgreSQL 17.6.

**Fatos de 12/11 que pedem atenção:**

1. O `broadcast-worker` antigo tem `ALLOW_REAL_SENDS=true` duas vezes. A
   ferramenta agora trata o valor repetido igual como um só; valores
   diferentes continuam recusando.
2. Na sessão do aplicador (`postgres` pelo pooler, porta 5432):
   `statement_timeout` = **2 min**, `lock_timeout` = 0, sem superusuário,
   com BYPASSRLS e CREATEROLE. Pela regra do V1, decidir antes do SIM 3:
   com 23 MB de banco nenhuma migration deve chegar perto de 2 min, e o
   ensaio V9 mede isso no clone. Se alguma passar de 60 s no clone, parar e
   decidir antes da janela.
   - Não altere a role (`ALTER ROLE` nem outro ajuste persistente).
   - `PGOPTIONS` não serve aqui. O executor da janela monta o ambiente do
     processo do `migrate.py` do zero e só aceita `PATH`, `LC_ALL`, `LANG`,
     `PYTHON_DOTENV_DISABLED`, `MIGRATION_DATABASE_URL`, `PGAPPNAME` e
     `PGCONNECT_TIMEOUT`.
   - A URL do aplicador também recusa o parâmetro `options`.
   - O `migrate.py` fixo (`37c7d68d`) só define `lock_timeout` (2 s, `SET
     LOCAL`) e não mexe no `statement_timeout`. Cada migration roda, portanto,
     com os 2 min da role.
   - O pooler do Supabase também ignora `PGOPTIONS` (regra no topo deste
     runbook).
   - Conferido no código em 12/11.
   - **Decisão de 12/11 (orquestrador, opção a):** ficam os 2 min da role.
     Não muda o executor nem a role.
   - **Regra de parada do V9:** o `rehearse-backup` não mostra o tempo de cada
     migration. O recibo mostra só `seconds`, que é o total do ensaio (cópia,
     restore e as 51 migrations no clone). Como nenhuma migration dura mais
     que o total:
     - `seconds` abaixo de 60: todas ficaram abaixo de 60 s. Segue.
     - `seconds` de 60 ou mais: não dá para provar que cada uma ficou abaixo
       de 60 s. A janela **não abre**. Volta para a opção (b): a ferramenta
       passa a aceitar o timeout explícito, com nova revisão.
     - Quem dá o SIM do V8/V9 confere esse número antes do SIM 2.
3. Risco conhecido, aceito pelo orquestrador em 12/11: no backend
   `afdfb78d`, o envio humano pelo painel para contato com opt-out **não** é
   bloqueado, igual à produção de hoje. O bloqueio (#665) existe só no backend
   da `main` e chega no release seguinte. O painel da `main` não muda isso: o
   bloqueio é do backend.

#### Preparação (V8, SIM próprio; V9 dentro dele)

No computador do operador, com o checkout na `main` em `<SHA>`:

```bash
git archive --format=tar <SHA> deploy | ssh vps "sudo install -d -m 755 /opt/pastorai-releases/tool-<SHA> && sudo tar -x --no-same-owner -C /opt/pastorai-releases/tool-<SHA>"
```

```bash
scp first-transition.json backup.json bindings.json vps:/tmp/
```

Na VPS (`ssh vps`, depois `sudo -i`):

```bash
W=/var/lib/pastorai-first-transition
install -d -m 700 $W/window $W/window-backups $W/clone-work
install -m 600 /tmp/first-transition.json /tmp/backup.json /tmp/bindings.json $W/window/ && rm /tmp/first-transition.json /tmp/backup.json /tmp/bindings.json
docker pull postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929
B=/root/env.v2.bak-$(date -u +%Y%m%dT%H%M)
cp -p /opt/pastorai-lionclaw/deploy/.env.v2 $B
awk '!(/^ALLOW_REAL_SENDS=false$/ && seen++)' $B > /opt/pastorai-lionclaw/deploy/.env.v2
grep -c '^ALLOW_REAL_SENDS=' /opt/pastorai-lionclaw/deploy/.env.v2
(umask 077; grep -E '^DATABASE_URL=' /opt/pastorai-lionclaw/deploy/.env.v2 | sed 's/^DATABASE_URL=/MIGRATION_DATABASE_URL=/' > /root/igreja12-janela.conf)
stat -c '%U %a' /opt/pastorai-lionclaw/deploy/.env.v2 /root/igreja12-janela.conf
```

Esperado: o `grep -c` mostra `1`; os dois arquivos `root 600`.

Variáveis usadas em todos os comandos seguintes (na VPS, como root):

```bash
PY=/var/lib/pastorai-first-transition/venv/bin/python
T=/opt/pastorai-releases/tool-<SHA>/deploy/first_transition_window.py
W=/var/lib/pastorai-first-transition/window
ARGS="--config $W/first-transition.json --backup-config $W/backup.json --bindings-config $W/bindings.json --env-file /root/igreja12-janela.conf --env-var MIGRATION_DATABASE_URL"
```

Layout do candidato e conferências (V9):

```bash
$PY -E -s $T prepare-layout --config $W/first-transition.json
$PY -E -s $T prepare $ARGS
$PY -E -s $T check $ARGS
$PY -E -s $T check-bindings $ARGS
$PY -E -s $T rehearse-backup $ARGS
```

Esperado: `prepare-layout` com `files` 144; `prepare` imprime `plan_digest`
e `window_digest` (anotar os dois); `check` com `same_database` e `ddl_free`
`ok` nas duas leituras; `check-bindings` com as duas entradas `open` e
`unknown_writers` 0; `rehearse-backup` termina com recibo e as 51 migrations
no clone (o recibo traz `restore_excluded`: quantas entradas do dump o restore
deixou de fora e os nomes dos event triggers deixados de fora; quem dá o SIM
confere essa lista: o ensaio das migrations **não exercita** esses triggers,
que em produção disparam a cada DDL). O restore usa uma lista de conteúdo filtrada:
fora ficam só a extensão `supabase_vault` (e o que está no schema `vault`) e
os event triggers cujo dono não é superusuário no clone, porque a imagem
oficial do Postgres não restaura isso. Tabelas, dados, policies, funções,
publication e o schema `public` (que o catálogo confere) ficam. Qualquer
`refused`: parar e trazer o código inteiro para a equipe (por exemplo
`window-backup-restore-failed-extension`; pode aparecer uma recusa por vez,
então outras extensões do Supabase podem exigir novo ensaio; o sufixo é o tipo de objeto que
parou o restore, nunca nome ou valor). O restore copia o dump também para
dentro do clone (some com ele; mais disco e um pouco mais de tempo, que conta
no `seconds`); nada foi alterado no sistema antigo. O `rehearse-backup` guarda uma cópia do banco em
`window-backups` (root 0700); ela fica até o fim da janela. Na mesma pasta
ficam também `restore-full.list` e `restore.list` (só nomes de objetos do
banco, sem dados; 0600).

**Travar os números do restore no `backup.json` (ao dar o SIM 2).** O recibo
do V9 traz `restore_excluded` (`vault_extension`, `vault_schema`,
`event_triggers`, `event_trigger_names`) e `restore_seconds` (só o restore;
`seconds` continua sendo o total). O operador confere os nomes e copia o
`restore_excluded` do recibo, sem mudar nada, para o campo
`restore_excluded_expected` do `$W/backup.json` na VPS (arquivo do kit, fora
do Git; o `rehearse-backup` funciona sem o campo, é assim que se descobre o
valor). No modo `run` o campo é **obrigatório**: sem ele, ou com números
diferentes dos do dump da hora, a janela recusa com
`window-backup-restore-excluded`, antes de copiar ou restaurar qualquer coisa
no clone. Mudou o `backup.json`? Refazer o `prepare` e conferir os digests.

#### Roteiro do dia

Horário de exemplo: início às 10:00 (Brasília), em dia útil. Duração prevista
do SIM 2 ao fim: cerca de **80 min**; reservar **2 h**. Duração máxima a
registrar no J1: 120 min. Em todos os passos, os comandos rodam na VPS como
root com as variáveis acima.

| Hora | Passo | Duração | Comando que o operador dispara | Se falhar |
|---|---|---|---|---|
| 09:30 | V4 lembrado, V7 foto dos outros sistemas | 10 min | bloco da seção 12.0 | Algum outro sistema fora do ar: não abrir a janela. |
| 10:00 | **SIM 2** — J1 abrir a janela | 5 min | `$PY -E -s $T prepare $ARGS` e conferir que os digests são os do V9; registrar início UTC, operador, 120 min e SHAs | Digest diferente: parar; algo mudou desde a véspera. |
| 10:05 | J2 pausar só o backup da Igreja 12 | 2 min | `mv /etc/cron.d/pastorai-backup /root/pastorai-backup.cron.pausado` | Se não existir, conferir com `ls /etc/cron.d/` e anotar. Nunca parar o serviço `cron`. |
| 10:07 | **SIM 3** — J3 a J6 (`run`, inclui o ponto de não retorno) | 20–35 min | `$PY -E -s $T run $ARGS --expect-plan-digest <plan> --expect-window-digest <window>` | Saída com `refused`: ler `recovery.state`. Antes da DDL (`contained-pre-ddl`, `backup-window-used`): a equipe decide `resume_legacy` (volta o sistema antigo). Depois da DDL: tudo fica contido (site em manutenção, nada enviado); nada de reiniciar, restaurar ou voltar sem SIM próprio. |
| 10:40 | anotar `a10_token` do resultado | 1 min | — | Resultado sem `a10_token`: não seguir para a A10. |
| 10:42 | **SIM 4** — J7 A10 | 5–10 min | `$PY -E -s $T a10 $ARGS --expect-plan-digest <plan> --expect-window-digest <window> --a10-token <a10_token>` | A ferramenta contém sozinha (site em manutenção, workers parados). Não repetir nem reabrir por conta própria; repetir o mesmo comando só se ela parou no meio (retoma do diário). |
| 10:52 | **SIM 5** — J8 painel | 15 min | no computador do operador: `cd <pasta>/frontend` e `vercel --prod` (seção 12.5) | Smoke falhou: `vercel rollback <deployment anotado no V5>`; backend e gates ficam como estão. |
| 11:07 | J9 religar o backup e conferir | 5 min | `mv /root/pastorai-backup.cron.pausado /etc/cron.d/pastorai-backup && chown root:root /etc/cron.d/pastorai-backup && chmod 644 /etc/cron.d/pastorai-backup` | Se o arquivo não voltar, o backup diário de amanhã não roda: corrigir no mesmo dia. |
| 11:12 | J10 foto dos outros sistemas e `diff` com a das 09:30 | 10 min | bloco da seção 12.0 | Diferença: não mexer em outro sistema; avisar o Raniel. |
| 11:22 | Encerramento | — | registrar horários, resultado do `run`, da A10 e do J8 | — |

**Painel (J8):** publicar **somente** no projeto Vercel
`pastorai-frontend-prod`, a partir de um checkout limpo do `<SHA>` ligado a
ele por `vercel link` (seção 12.5). Nunca criar projeto novo nem usar o
projeto antigo `pastorai-frontend`.

O kit gerado (três JSON, tarball do backend e notas) fica fora do Git, com a
equipe; o caminho exato está na descrição da PR que criou esta seção.
