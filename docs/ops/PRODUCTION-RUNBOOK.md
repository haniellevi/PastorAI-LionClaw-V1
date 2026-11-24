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
| Frontend Cloudflare Workers | Worker `igreja12-frontend-prod` (V5/J8, §12.5) |
| Frontends públicos | `app.igreja12.com.br`, `admin.igreja12.com.br` e `painel.igreja12.com.br` |

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

Para a primeira virada, seguir V5/J8 no Cloudflare Workers (§12.5). O
painel usa `NEXT_PUBLIC_API_URL=https://api.igreja12.com.br` no build e envia
`Authorization: Bearer` à API. No SHA A, o middleware do próprio painel
define a CSP bloqueante de documento e o nonce da resposta. Manter
desligada a publicação automática da antiga integração Vercel.

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
- Frontend na primeira virada: se a compatibilidade for confirmada, promover
  a versão anterior no mesmo Worker (§12.5 e §12.7).
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
- versão e deployment do Worker e conferência dos três Custom Domains no J8;
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

Ferramenta: `deploy/first_transition_window.py` (modos somente leitura `status`,
`prepare`, `check`, `check-bindings`, além de `prepare-layout`, `rehearse-backup`,
`resume-legacy`, `run` e `a10`). Alvo desta virada (Fase 5, após retarget do
bloco 5.2 em 24/11/2026): SHA **A** =
`e1c63ed1dfaaacf26c21a3cc8d9c8c3151c0aae0` (`130` migrations = `78` de base +
`52` pendentes, sendo `44` transacionais e `8` `CONCURRENTLY`). Recibo:
[RECIBO-5-2-20261124.md](RECIBO-5-2-20261124.md). O SHA anterior `6af9f75c8d673cb3454de1f8740a0acc509937ff`
foi o candidato A até esse retarget e permanece só como referência histórica
nas conferências estáticas da §12.7. O modo `run` vai
da contenção até a A9 numa execução só, parando sempre após gravar `ddl-marker`
em qualquer queda ou recusa (`transition-stopped` no orquestrador; JSON da CLI com `"refused": "window-transition-refused"` e estado em `recovery.state`). O modo `a10` é uma execução
separada, e `resume-legacy` atua exclusivamente antes do marcador.

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
| V1 | Leitura só de metadados do alvo: serviços e IDs, gates **por nome e valor** dos quatro processos antigos, cron do host, Redis, `release_preflight.py`, `migrate.py status`, duplicidades = 0 e inventário das variáveis obrigatórias de A por nome (seção 12.7). Na sessão do aplicador (mesma DSN de `MIGRATION_DATABASE_URL`, sem `SET`): `SHOW statement_timeout`, `SHOW lock_timeout`, `pg_roles` (`rolsuper`, `rolbypassrls`, `rolcreaterole`, `rolcreatedb`, `rolinherit`), `pg_auth_members` (inclui `ADMIN OPTION` nas roles `anon`, `authenticated`, `service_role`), `server_version_num`, roles de runtime e proprietários dos objetos afetados. O clone da `T` replica role aplicadora sem `SUPERUSER` e com `statement_timeout = '2min'`; o V1 confirma equivalência no alvo antes do SIM 3, sem alterar nada no SIM 1. | **SIM 1** (leitura no alvo) |
| V2 | Conferir que o arquivo privado efetivo do candidato tem os mesmos gates por finalidade do antigo (piloto, agenda, V1a, V3). Os quatro gates principais ficam fechados nele; a A10 os sobrepõe com os valores antigos. Se algum gate por finalidade diferir, a verificação da A10 pode acusar cancelamento e conter. | dentro do SIM 1 |
| V3 | Ensaio sintético verde no SHA escolhido (`synthetic-release`), ensaio Docker das 52 migrations (`test_first_transition_window_backup_docker`, item 4.6) e os quatro checks do CI. | — |
| V4 | Aviso à equipe **dispensado** nesta janela (`ROADMAP` Decisão D13 / item 4.2 d: instalação interna com dados de teste, sem prejuízo a usuário final externo); a janela ainda mantém manutenção 503 durante `J4`–`A10`. | dispensado (D13) |
| V5 | Pré-requisitos do painel (§12.5): confirmar conta, Worker `igreja12-frontend-prod`, três Custom Domains e versão ativa anterior. Conferir artefato de **A** e contrato OpenAPI, com compatibilidade parcial de volta na §12.7. | dentro do SIM 1 (só leitura no alvo) |
| V6 | Edição única do site nginx da API: pasta vazia `/etc/nginx/igreja12-window` (root, 0755) e a linha `include /etc/nginx/igreja12-window/*.conf;` logo após `server_name` no bloco 443, com backup, `nginx -t` e reload. Certificado, IPv6, cabeçalhos de proxy e o bloco de redirecionamento da porta 80 continuam como estão: a ferramenta aceita esse formato do certbot (seção "Topologia nginx nominal" do `RELEASE-LOTE-2026-10.md`). Na configuração dos bindings: `site_path` = `/etc/nginx/sites-available/pastorai-api-http` e `enabled_path` = `/etc/nginx/sites-enabled/pastorai-api-http` (é atalho na VPS, conferido em 12/11). | **SIM próprio** (edição na VPS) |
| V7 | Foto dos outros sistemas da VPS (seção 12.0): contêineres, saúde e código HTTP de cada um. Tudo precisa estar respondendo antes de abrir a janela. | dentro do SIM 1 (só leitura) |
| V8 | Preparar a VPS com o kit (seção 12.6): ferramenta **T**, transferência e conferência dos objetos Git de **A** (`6af9f75c...`), **T integrado** e `EXECUTOR_SHA` do aplicador (`37c7d68d...`) em `/opt/pastorai-releases/repo` (4.2 h), três arquivos de configuração, pastas do backup, imagem do Postgres, arquivo privado do aplicador, correção da linha repetida se aplicável e `prepare-layout`. Não toca no sistema antigo, no banco, no nginx nem nos gates. | **SIM próprio** (escrita na VPS) |
| V9 | Conferências sem efeito com o kit instalado: `prepare`, `check` (duas leituras do banco) e `check-bindings`; ensaio do backup da janela (`rehearse-backup`: cópia do banco, restore em clone com role aplicadora sem `SUPERUSER` e `statement_timeout = '2min'`, replay das **52 migrations** com conferência de RLS/grants e `final_schema_digest`). Regra de parada D9 (item 4.2 d): mede cópia, restore e **cada migration**; barra apenas se alguma migration individual (`max_migration_seconds`) passar de **60 s** (o total do ensaio não barra). Cópia externa do `window.dump` dispensada (D13). | dentro do SIM V8 |

### 12.2 Janela

| Passo | O que acontece | SIM do Raniel |
|---|---|---|
| J1 | Registrar início (UTC), operador, duração máxima em minutos e SHAs. `prepare` e conferência dos digests. | **SIM 2** (abrir a janela) |
| J2 | Pausar o backup automático do host (cron M02) **só da Igreja 12**: `sudo mv /etc/cron.d/pastorai-backup /root/pastorai-backup.cron.pausado` (nunca parar o serviço `cron` nem os timers dos outros sistemas) e confirmar que ninguém mais usa console, SQL Editor, MCP ou CLI do Supabase. | dentro do SIM 2 |
| J3 | `run`: antes de tocar no sistema antigo, a ferramenta **fotografa os quatro gates de cada processo antigo** (`transition-gate-snapshot`). Valor desconhecido recusa aqui, antes de qualquer efeito. | **SIM 3** (o `run` inteiro, J3 a J6, inclui o ponto de não retorno) |
| J4 | Bloqueia as duas entradas (site 503 e Evolution→backend), `restart=no`, SIGTERM e saída 0 dos quatro processos antigos; duas observações sem nenhuma escrita; linha de base das pendências (`transition-pending-baseline`); backup da janela com restore e replay em clone. | dentro do SIM 3 |
| — | **Até aqui ainda dá para voltar ao sistema antigo** (`resume-legacy`). | — |
| J5 | **PONTO DE NÃO RETORNO:** marcador da DDL (`ddl-marker`) e primeira migration. Depois dele, o sistema antigo nunca volta (`post-ddl-resume-forbidden`) e qualquer nova chamada a `run()` recusa incondicionalmente com `transition-stopped` (inclusive após queda brusca sem evento de falha posterior). | dentro do SIM 3 |
| J6 | **52 migrations** (`44` transacionais + `8` `CONCURRENTLY`), uma por vez; ao final compara o catálogo vivo (`final['catalog']`, query `Q_CATALOG`) ao `final_schema_digest` do clone vinculado ao `ddl-marker` (recusando divergências com `clone-source-schema-divergence`); candidato criado parado; só o backend de **A** sobe, com envios fechados, e passa no smoke; workers continuam parados; entradas continuam bloqueadas (A9). O resultado imprime `a10_token`. | dentro do SIM 3 |
| J7 | A10 (seção 12.3; revalida `final_schema_digest` antes de liberar o tráfego). | **SIM 4** (religar workers e envios como estavam) |
| J8 | Com A10 verde, publicar o painel no **mesmo SHA A** do backend no Worker e fazer o smoke nos três hosts (§12.5). Se falhar, confirmar a compatibilidade da §12.7 antes de voltar o painel ou corrigir adiante. | **SIM 5** (publicar o painel e autorizar eventual volta compatível) |
| J9 | Configurar `/opt/pastorai-current` para **A**, confirmar Compose efetivo, overrides externos e arquivo privado modo `0600` fora do layout verificado (`PASTORAI_ENV_FILE`), executar **manualmente uma vez** o comando do backup provando `BACKUP_OK`, `sha256sum -c`, status `"verified"` e os três serviços de apoio despausados, e então religar `/etc/cron.d/pastorai-backup` (`root:root`, `0644`); conferir `AgentConfig` e Jev e registrar o encerramento (seção 12.2.2). | — |
| J10 | Repetir a foto dos outros sistemas (seção 12.0) e comparar com a do V7: nenhuma diferença. | — |

**SIM 3** cobre o `run` inteiro: contenção, backup, migrations e A9. Como o
`run` não para entre o backup e a primeira migration, dizer SIM 3 é aceitar o
ponto de não retorno. Decisão do Raniel em 12/11/2026: um SIM 3 único
basta; não haverá SIM separado para as migrations.

**Se o smoke ou qualquer etapa falhar depois da primeira migration (J5–J6):**
não há volta ao sistema antigo, e qualquer repetição de `run()` é recusada com
`transition-stopped` (mesmo após interrupção abrupta com `ddl-marker` gravado).
A ferramenta mantém tudo contido: site em manutenção, entradas bloqueadas,
workers nunca iniciados, processos antigos parados. Nada é enviado e nada é
cancelado. Preservar diário, backup da janela e evidências. Decidir, por SIM
próprio: corrigir adiante (novo SHA revisado e testado) ou restaurar o **backup
da janela** (`window_backup_id` do marcador, nunca o do A6). Nunca restaurar de
improviso.

O "rollback imediato pré-autorizado se o smoke falhar" (ROADMAP, 12/11) só
pode significar, depois do J5, essa contenção automática: voltar ao sistema
antigo com o banco já migrado não é seguro e a ferramenta recusa. Corrigir
adiante ou restaurar o backup da janela continuam exigindo SIM próprio.

**Escopo da comparação de schema (`final_schema_digest`, item 4.2 g):** antes
de criar a A9 e novamente na A10, a ferramenta compara `final['catalog']` com
`window_backup['clone_rehearsal']['final_schema_digest']` vinculado ao
`ddl-marker` (erro `clone-source-schema-divergence`). A query `Q_CATALOG` agrega
apenas objetos do schema `public` (relações, índices, constraints, policies,
triggers, funções, colunas) e `pg_default_acl` dos namespaces `0` ou `public`.
Portanto, as exclusões esperadas do restore (`restore_excluded_expected`: extensão
`supabase_vault`, schema `vault` e event triggers de superusuário fora de
`public`) ficam **fora** do escopo comparado e não causam falso divergência.

#### 12.2.1 Estados de recuperação (`classify_recovery`) e rotas pré/pós-marcador

Consulta somente leitura do estado atual do diário (não muta diário, banco nem
host; preenche `resume_token` apenas quando `legacy_resume_allowed` é `true`):

```bash
$PY -E -s $T status --config $W/first-transition.json
```

Retomada pré-marcador do sistema antigo pelo mesmo diário (`resume_legacy` /
subcomando CLI `resume-legacy`, permitida somente nos estados
`contained-pre-ddl`, `backup-window-used` e `resume-partial`; recusa com
`post-ddl-resume-forbidden` no orquestrador — emitido pela CLI como
`"refused": "window-transition-refused"` com `legacy_resume_allowed: false` —
se houver `ddl-marker`):

```bash
$PY -E -s $T resume-legacy $ARGS --expect-plan-digest <plan> --expect-window-digest <window> --resume-token <RESUME:...> [--allow-queue-drift]
```

Estados exatos retornados por `classify_recovery()` (`status` e campo
`recovery` de recusas) e ação operacional correspondente (`automatic_undo`,
`destructive_retry` e `automatic_restore` são sempre `false`):

| `recovery.state` | Fase | `legacy_resume_allowed` | Comportamento da CLI e rota operacional |
|---|---|---|---|
| `not-started` | Pré-marcador | `false` | Nada gravado. Conferir inputs e executar `run`. |
| `containment-partial` | Pré-marcador | `false` | Queda durante a contenção (antes de `observed-host-contained`). Re-executar `run` se saída limpa; saída suja requer inspeção humana. |
| `contained-pre-ddl` | Pré-marcador | `true` | Legado contido, sem backup solicitado. Pode prosseguir com `run` ou reverter o legado via `resume-legacy --resume-token ...`. |
| `backup-window-used` | Pré-marcador | `true` | Solicitação/backup da janela já registrada (`run` recusa reusar a solicitação). Executar `resume-legacy`; nova tentativa exige novo diário. |
| `resume-partial` | Pré-marcador | `true` | Retomada pré-marcador interrompida no meio. Repetir `resume-legacy` com o mesmo `--resume-token` (usar `--allow-queue-drift` só se houver autorização explícita para drift após assentamento). |
| `legacy-resumed` | Pré-marcador | `false` | Sistema antigo religado e ingress aberto. Qualquer nova janela exige novo diário limpo. |
| `ddl-ambiguous` | Pós-marcador | `false` | Migration aberta ou resultado ambíguo (`run` recusa no orquestrador com `transition-stopped`; JSON da CLI `"refused": "window-transition-refused"` + `recovery.state`). Sem retry e sem legado. Inspecionar ledger e índices inválidos em leitura; decidir por SIM próprio entre correção adiante ou restore manual de `window_backup_id`. |
| `ddl-failed` | Pós-marcador | `false` | Falha transacional definitiva (`definite=true`, `run` recusa no orquestrador com `transition-stopped`; JSON da CLI `"refused": "window-transition-refused"` + `recovery.state`). Sem retry e sem legado. Decidir por SIM próprio entre restore manual do `window.dump` ligado ao `window_backup_id` do marcador ou correção adiante. |
| `post-ddl-failed` | Pós-marcador | `false` | Falha ou queda brusca pós-`ddl-marker` fora de migration/layout (inclui divergência `clone-source-schema-divergence` ou queda antes do layout). `run` recusa no orquestrador com `transition-stopped` (JSON da CLI `"refused": "window-transition-refused"` + `recovery.state`); manter ingress bloqueado e inspecionar ledger/catálogo em leitura. |
| `candidate-failed` | Pós-marcador | `false` | Falha após criação do layout do candidato (`transition-done: layout` + `transition-failed`). Consumidores permanecem held, ingress bloqueado; decisão humana. |
| `candidate-ambiguous` | Pós-marcador | `false` | Passo `a9:*` interrompido/ambíguo. Nada é reiniciado ou removido automaticamente; inspecionar o projeto candidato em leitura. |
| `a9-complete` | Pós-marcador | `false` | 130 migrations aplicadas, catálogo conferido, backend **A** no ar com envios fechados e smoke verde, workers held e ingress bloqueado. Seguir para `a10` após **SIM 4**. |
| `a10-partial` | A10 | `false` | Passo `a10:*` interrompido sem fechamento (`run` recusa com `transition-a10-started`). Repetir o **mesmo comando `a10`** com o mesmo diário e `--a10-token`: passos com recibo são re-verificados e passo aberto só é adotado com prova exata; caso contrário recusa e contém. |
| `a10-complete` | A10 | `false` | Os quatro contêineres de **A** ativos com os gates da foto e ingress aberto. Repetir `a10` apenas re-verifica sem reiniciar processos. |
| `a10-contained` | A10 | `false` | A10 falhou e a contenção automática completou (entradas bloqueadas; cron, broadcast, queue e backend com `restart=no` e parados, **sem** reescrever gates para fechado). Sem legado e sem reabertura automática; corrigir adiante por decisão humana e novo diário. |
| `a10-containment-incomplete` | A10 | `false` | **Ação humana urgente:** contenção automática da A10 falhou parcialmente; bloquear ambas as entradas e parar manualmente cron, broadcast, queue e backend. Nunca reabrir nem voltar ao legado. |

**Rota para falhas de DDL (4.2 e–f):** em `ddl-failed`, `ddl-ambiguous` ou
`post-ddl-failed`, manter as entradas bloqueadas e os consumidores contidos.
Preservar diário e dump da janela. `status` mostra o estado e os passos
abertos. Conferir em leitura o ledger, o catálogo e os índices inválidos
em `pg_index`. Em `ddl-ambiguous`, conferir também se a migration aberta
está no ledger e se deixou objetos ou índices. Mesmo uma migration
confirmada no ledger pode ter perdido o recibo. `run` e `resume-legacy`
continuam proibidos após o marcador. Para falhas de candidato e A10,
seguir as linhas próprias da tabela acima.

Se o dono aprovar **restore do backup da janela** com **SIM próprio**:

1. Localizar `window.dump` pelo recibo da mesma janela, vinculado a
   `backup_request_digest` e `backup_digest` no `ddl-marker`. O
   `sha256sum` do dump deve ser igual ao `window_backup_id` do marcador.
   Qualquer divergência exige parar e preservar as evidências.
   Para as exclusões, preservar o `backup.json` final de V9 junto aos
   demais insumos usados pela janela. No checkout do executor original,
   rodar `prepare $ARGS` em leitura com os mesmos caminhos e comparar
   `window_digest` e `plan_digest` com o primeiro evento `window-init`
   do mesmo diário. O `backup_digest` de `window-init` cobre a
   configuração de backup normalizada, inclusive `restore_excluded_expected`.
   Esse digest de configuração tem finalidade distinta do `backup_digest`
   do marcador, que identifica o recibo. Conferir também se
   `transition-backup-request.request.config_digest` bate com
   `window-init.transition_digest` e se o digest do pedido bate com
   `backup_request_digest` do marcador. O provedor compara as exclusões
   observadas com o pin antes de emitir o recibo. Usar o pin conferido
   como fonte das exclusões, pois o recibo no diário não as projeta.
   Se faltar o JSON exato ou algum vínculo divergir, parar.
2. Registrar e avaliar escritas posteriores ao dump e a situação das filas.
   A aprovação precisa identificar o alvo e sua identidade, o mecanismo e
   a role de restauração, as exclusões verificadas no passo 1 que se aplicam ao alvo e o
   artefato de serviço legado com proveniência conferida. O mecanismo
   precisa garantir a ausência de objetos que só surgiram após o backup.
3. Executar o procedimento aprovado mantendo o alvo isolado e sem
   redirecionar tráfego. Antes de apontar qualquer serviço para ele,
   conferir a lista nominal das 78 migrations de base, zero índices
   inválidos, `Q_CATALOG` idêntico ao baseline pré-janela e as verificações
   de dados acordadas para o escopo da restauração.
4. Validar a saúde e uma leitura funcional do serviço legado contido com
   o alvo restaurado, mantendo ingress bloqueado, consumidores contidos e
   gates de efeito fechados. Verificar filas e ausência de reenvio, guardar
   os recibos e submeter qualquer reabertura a decisão própria.

O ensaio sintético `test_recovers_legacy_service_from_marker_dump_after_committed_ddl`
usa o orquestrador, o backup da janela e PG17 reais. Injeta perda do resultado
depois do commit de DDL, confirma as recusas e restaura o mesmo dump em
outro PG17 limpo com rede interna. Prova ledger, catálogo, dados fictícios e
retomada de um processo de serviço sintético com envio bloqueado. O alvo
e o mecanismo desse teste são descartáveis. A escolha operacional do alvo,
da forma de restauração e do artefato legado continua sob aprovação própria.

#### 12.2.2 J9: backup diário e topologia efetiva após a virada (4.3)

Sem modificar `deploy/backend-release.sh` (Decisão 9 e contrato com
`deploy/BACKEND-RELEASE-MANUAL.md`):

- **Topologia e Compose efetivos após a virada (`A` = `6af9f75c`):**
  - Link ativo `/opt/pastorai-current` apontando para o diretório do release
    ativo de **A** (fora do legado `/opt/pastorai-lionclaw`), onde reside o
    Compose efetivo `/opt/pastorai-current/deploy/docker-compose.yml` +
    `/opt/pastorai-current/deploy/docker-compose.override.yml` (projeto
    `candidate.project` do `first-transition.json`, fixado em `name:` pelo
    override; os apoios continuam no projeto legado).
  - **Overrides:** `/opt/pastorai-current/deploy/docker-compose.override.yml`
    **faz parte obrigatória do layout verificado do release**
    (`initial_transition_files.layout_files()` / `release_topology.overlay`,
    carregado por `CandidateSpec.compose_argv()` e `a10_compose_argv()`) e
    **deve ser preservado** dentro de `/opt/pastorai-current/deploy/`. Apenas
    os overrides **transitórios da janela** (`a9-hold.override.yml` e
    `a10-gates.override.yml`) ficam fora desse layout (em
    `/var/lib/pastorai-first-transition/state/`), e nenhum outro override
    manual/avulso pode existir dentro do release.
  - **Dependências de runtime:** serviços de apoio `redis` (`pastorai_redis`),
    `evolution-postgres` (`pastorai_evo_postgres`) e `evolution-api`
    (`pastorai_evolution`), além dos 4 processos da aplicação (`backend`,
    `queue-worker`, `cron-worker`, `broadcast-worker`) na mesma rede do Compose
    efetivo (`pastorai_default`).
- **Arquivo privado efetivo (`0600`, fora do layout verificado):**
  - O arquivo privado com as credenciais e gates do runtime (no arranjo de
    Decisão 9, `--env-file /etc/pastorai/.env.v2`, ou
    `/etc/pastorai-private/runtime.env` após consolidação do modo externo em
    `deploy/BACKEND-RELEASE-MANUAL.md`) permanece fora de
    `/opt/pastorai-current`, pertencente a `root:root`, arquivo regular com
    `nlink=1` e modo `0600` (diretório pai `0700`). É o mesmo
    `candidate.env_file` do `first-transition.json`, e o `backup-production.sh`
    só confere que ele não está vazio: conferir dono, modo e `nlink` com
    `stat -c '%U:%G %a %h'` (esperado `root:root 600 1`) e contar com
    `grep -c '^DATABASE_URL=' <arquivo>` (idem `SUPABASE_URL` e
    `SUPABASE_SERVICE_ROLE_KEY`) exatamente `1` de cada, pois o auxiliar do
    banco usa a primeira ocorrência e o leitor do Storage a última. Estes
    comandos só imprimem contagens e modos, nunca valores; não usar `cat`,
    `grep` sem `-c`, `env`, `set -x` nem `docker compose config` sem
    `--quiet` sobre esse arquivo.
  - `deploy/docker-compose.yml` lê `env_file: ${PASTORAI_ENV_FILE:-.env}` e
    `deploy/backup-production.sh` (instalado em
    `/usr/local/sbin/pastorai-backup.sh`) lê
    `ENV_FILE="${PASTORAI_ENV_FILE:-/opt/pastorai-current/deploy/.env}"` e
    `COMPOSE_FILE="${PASTORAI_COMPOSE_FILE:-/opt/pastorai-current/deploy/docker-compose.yml}"`.
  - Portanto, conferir o Compose efetivo com o mesmo argv de
    `CandidateSpec.a10_compose_argv()` (`--env-file /dev/null` só para
    interpolação; o arquivo privado entra por `PASTORAI_ENV_FILE`):
    `sudo PASTORAI_ENV_FILE=/etc/pastorai/.env.v2 docker compose --project-name <candidate.project> --env-file /dev/null --project-directory /opt/pastorai-current/deploy -f /opt/pastorai-current/deploy/docker-compose.yml -f /opt/pastorai-current/deploy/docker-compose.override.yml -f /var/lib/pastorai-first-transition/state/a10-gates.override.yml config --quiet`
    (ou com o caminho externo efetivo confirmado no V1/1.2).
  - O cron novo **não é** o arquivo pausado: `/root/pastorai-backup.cron.pausado`
    é o cron antigo e fica preservado como evidência. Preparar
    `/root/pastorai-backup.cron.novo` (`umask 077`) com **uma** linha
    terminada em newline, copiando literalmente os cinco campos de
    agendamento do `.pausado` (`<MIN> <HORA> <DIA> <MES> <DOW>`; o roteiro J9
    cita `15 6 * * *`). Não converter nem inferir fuso: o `cron` interpreta
    esses campos no fuso do host, que se registra com `date +%Z` (o `STAMP`
    do backup é sempre UTC, independente disso). `<ENV>` = o caminho `0600`
    efetivo (só caminho, sem valores):
    `<MIN> <HORA> <DIA> <MES> <DOW> root /usr/bin/env -i HOME=/root SHELL=/bin/sh LC_ALL=C PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PASTORAI_ENV_FILE='<ENV>' PASTORAI_COMPOSE_FILE=/opt/pastorai-current/deploy/docker-compose.yml /usr/local/sbin/pastorai-backup.sh >>/var/log/pastorai-backup.log 2>&1`
    Conferir o arquivo sem imprimir valores: `wc -l` = `1`,
    `tail -c1 /root/pastorai-backup.cron.novo | od -An -c` = `\n` (o `cron.d`
    ignora entrada sem newline final) e `grep -c 'PASTORAI_ENV_FILE='` = `1`.
    O `umask 077` **não** reduz o modo de um log que já existe: antes de
    religar, exigir que `/var/log/pastorai-backup.log` seja arquivo regular,
    sem symlink, `root:root`, `0600`, `nlink=1`:
    `test ! -L /var/log/pastorai-backup.log && { test -e /var/log/pastorai-backup.log || install -m 0600 -o root -g root /dev/null /var/log/pastorai-backup.log; } && stat -c '%F %U:%G %a %h' /var/log/pastorai-backup.log`
    (esperado `regular file root:root 600 1`, ou `regular empty file …` se
    novo). Se divergir, parar: corrigir com `chmod 0600`/`chown root:root`
    (ou mover o log antigo para `_lixeira`) só dentro do SIM da 5.5, sem
    abrir o conteúdo. Exigir também `prepare-database-service.py` + sidecar
    `.sha256` válidos em `/usr/local/libexec/pastorai-backup/`.
  - Com o cron ainda pausado e dentro do SIM da 5.5, usar
    `deploy/install-legacy-backup.sh` do executor **T integrado** para
    instalar o pacote revisado. Conferir que o SHA-256 do
    `/usr/local/sbin/pastorai-backup.sh` é o do `deploy/backup-production.sh`
    de T. A prova manual e o cron precisam executar essa mesma versão.
- **Execução manual única e critérios de prova antes de religar o cron.**
  Todos os comandos abaixo agem na VPS e só rodam na 5.5, depois do SIM 4 e
  do SIM 5; fora disso, nada aqui é executado.
  0. Antes de rodar: anotar a hora UTC e, do manifesto atual
     `/var/lib/pastorai-backup/backup-status.json` (ou "ausente"), só
     `archive` e `completed_at`. Anotar também o alvo atual de
     `/opt/pastorai-current`, e o ID de cada um dos três apoios
     (`docker inspect --format '{{.Name}} {{.Id}}' pastorai_evolution pastorai_evo_postgres pastorai_redis`;
     só nome e ID). Rodar também o `inspect` do passo 5 e exigir os três
     em `running` e `paused=false` antes de iniciar. Um `"verified"` antigo
     não prova o backup novo.
  1. Em shell `root` (seção 12.6; os redirecionamentos abaixo abrem o log
     como root, por isso sem `sudo` no meio), com `/opt/pastorai-current`
     apontando para **A** e os serviços de apoio em execução, criar um log
     **exclusivo da tentativa** e exigir que seja regular, sem symlink,
     `root:root`, `0600`:
     `LOG_J9=/root/j9-backup-$(date -u +%Y%m%dT%H%M%SZ).log; test ! -e "$LOG_J9" && test ! -L "$LOG_J9" && install -m 0600 -o root -g root /dev/null "$LOG_J9" && stat -c '%F %U:%G %a %h' "$LOG_J9"`
     (esperado `regular empty file root:root 600 1`; qualquer outra coisa:
     parar). Em seguida rodar **uma vez** exatamente o argv e o ambiente
     mínimo do cron (o mesmo `env -i`), mudando só o destino da saída
     (`>>"$LOG_J9"` em vez do log do cron):
     `/usr/bin/env -i HOME=/root SHELL=/bin/sh LC_ALL=C PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin PASTORAI_ENV_FILE='<ENV>' PASTORAI_COMPOSE_FILE=/opt/pastorai-current/deploy/docker-compose.yml /usr/local/sbin/pastorai-backup.sh >>"$LOG_J9" 2>&1; echo "rc=$?"`
     (`<ENV>` = o caminho `0600` efetivo; `/etc/pastorai-private/runtime.env`
     se consolidado). Anotar o rc e a hora UTC final e fazer o `inspect`
     do passo 5 imediatamente, inclusive se `rc != 0`. Se o rc ou a inspeção
     falhar, seguir o passo 7 antes de qualquer nova tentativa. O comando lê
     banco e Storage reais, faz pull de imagens, pausa os três apoios e
     grava artefatos: é um efeito real da 5.5. Nunca abrir, colar nem
     anexar o log; se for preciso mostrar, filtrar apenas os marcadores
     `BACKUP_OK` do passo 2 ou os marcadores de pausa do passo 7.
  2. Exigir no log da tentativa a linha final `BACKUP_OK stamp=<STAMP> archive=<ARCHIVE>`
     (`grep -F -- 'BACKUP_OK stamp=' "$LOG_J9" | tail -n 1`). Com `rc=0` mas sem
     essa linha (ex.: `INFO: outro backup já está em execução`, lock
     ocupado: o script sai com 0 sem criar pacote), não há backup novo:
     aguardar o outro backup terminar e repetir. Exigir `<STAMP>` dentro do
     intervalo UTC anotado e `<ARCHIVE>` diferente do anotado no passo 0.
  3. Validar integridade dos checksums:
     `sudo sha256sum -c <ARCHIVE>.sha256` e
     `(cd /root/pastorai-backups/<STAMP> && sudo sha256sum -c SHA256SUMS)`.
  4. Conferir o manifesto de monitoramento `/var/lib/pastorai-backup/backup-status.json`
     com `"version":1`, `"status":"verified"`, `archive` = `basename` de
     `<ARCHIVE>`, `sha256` igual ao do `.sha256` e `completed_at` dentro do
     intervalo UTC da tentativa (só esses campos; o manifesto não tem segredo).
     A prova do backup novo exige que o `BACKUP_OK` do log exclusivo,
     os checksums e o manifesto correspondam ao mesmo `<ARCHIVE>` e à
     mesma tentativa. Um `"verified"` antigo, mesmo com checksum válido,
     não aprova os passos 2–5 nem autoriza religar o cron no passo 6.
  5. Confirmar que os três serviços de apoio pausados temporariamente durante o
     snapshot dos volumes foram **despausados** pelo script:
     `sudo docker inspect --format '{{.Name}} {{.Id}} paused={{.State.Paused}} status={{.State.Status}}' pastorai_evolution pastorai_evo_postgres pastorai_redis`
     (exatamente os três nomes e os mesmos IDs anotados no passo 0, todos
     `paused=false`, `status=running`).
  6. Só com `rc=0` e os passos 2–5 aprovados, religar o cron **com a entrada nova**
     (nunca devolver o `.pausado` com `mv`, que repõe o cron antigo sem
     `PASTORAI_ENV_FILE` e faria o backup ler `.env` do release). A linha
     deve ser idêntica ao comando do passo 1, trocando só o destino da saída
     (log do cron já conferido acima):
     `sudo install -m 0644 -o root -g root /root/pastorai-backup.cron.novo /etc/cron.d/pastorai-backup`
     (publicação por arquivo temporário no mesmo diretório e `mv` atômico é
     aceitável). Manter `/root/pastorai-backup.cron.pausado` intacto. Conferir
     `stat -c '%U:%G %a' /etc/cron.d/pastorai-backup` = `root:root 644`,
     `grep -c 'PASTORAI_ENV_FILE=' /etc/cron.d/pastorai-backup` = `1`, o
     serviço `cron` ativo e o `pastorai-backup.timer` inativo e desabilitado.
  7. Se `rc != 0` ou qualquer prova falhar, manter o cron pausado e
     conferir os três apoios pelo `inspect` do passo 5. O script manual e
     o cron verificam nome, ID e estado antes de pausar por ID, um por vez.
     Em falha parcial ou erro posterior, o cleanup verifica os IDs e
     desfaz apenas as pausas que a própria tentativa confirmou. Cada
     `BACKUP_PAUSE_OWNED name=... id=...` registra essa confirmação.
     `BACKUP_PAUSE_RELEASED name=... id=...` registra que o mesmo apoio
     voltou a ser observado em execução e sem pausa.
     `BACKUP_PAUSE_UNCONFIRMED` ou falta de confirmação não autoriza
     despausar. Um apoio já pausado, parado, ausente ou com outro ID
     exige inspeção humana, sem iniciar ou recriar serviço aqui.
     Se restar pausa comprovadamente dessa tentativa, tratar no SIM
     correspondente, conferindo nome, ID do passo 0, estado pausado e o
     marcador de ownership sem marcador de liberação desse ID antes de
     qualquer `docker unpause <ID>` individual. Se houver dúvida sobre
     outro operador, avisar o Raniel.
     Recuperar um apoio por vez e repetir o `inspect` do passo 5 após
     cada `unpause`, antes de passar ao seguinte; não usar comando em lote
     nem tratar um erro de despausa como sucesso. Serviço parado, ausente
     ou com ID diferente do passo 0 exige parar e avisar o Raniel,
     preservando a exigência de ownership acima.
     Ao final exigir os três `paused=false`, `status=running`, preservar
     backup, kit, diário e `.pausado` e tratar a causa antes de pedir
     uma nova tentativa. No cron, erro de cleanup também fica registrado
     e a tentativa falha.
  8. Recuperação: o pacote arquiva só `docker-compose.yml` e o arquivo privado
     (`deploy.env`, modo `0600`), **não** os overrides. Guardar à parte, com
     SHA-256 e ligados ao SHA **A** e ao `<STAMP>`, os arquivos de
     `docker-compose.override.yml` e `a10-gates.override.yml` (e
     `release-topology.json`) e a ordem dos `-f` acima; só caminhos e hashes
     entram no recibo, nunca valores.
  9. Retenção: `14 dias` locais em `/root/pastorai-backups` (`-mtime +14` em
     `deploy/backup-production.sh`); **nenhuma cópia externa** é feita ou
     exigida dentro da janela (Decisão D13).

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

### 12.5 V5 e J8: painel no Cloudflare Workers (SIM 5)

O backend e o painel desta virada usam o SHA **A**
(`6af9f75c8d673cb3454de1f8740a0acc509937ff`). J8 publica o painel assim
que a A10 de A estiver verde. O backend, o banco e os gates continuam como
foram deixados pela A10.

#### V5: conferências e preparo

1. No SIM 1, confirmar em leitura a conta Cloudflare
   `f3e9829232eb12ca3142d704d9455ce2`, o Worker `igreja12-frontend-prod` e
   os três Custom Domains `app.igreja12.com.br`, `admin.igreja12.com.br` e
   `painel.igreja12.com.br`. Registrar a versão ativa a 100% e o ID do
   deployment. A versão esperada de retorno é
   `edee314b-7be2-4d49-86ce-f4d9ceb0bb1a`, do SHA
   `afdfb78d71a53f2861632806e13cdda4662d7d63`. Se a versão ou os vínculos
   mudarem, parar, confirmar a proveniência e a compatibilidade da nova
   versão de volta, atualizar o recibo e reconfirmar o SIM 5.
2. Preparar o pacote de produção em cópia isolada do frontend de A com o
   patch de infraestrutura Workers revisado, SHA-256
   `7d4c5cf121577800b1206d02c2038206f470962b0c7b5eeea0d39d87b500f274`.
   A #697 preservou a árvore `frontend/`, portanto o mesmo patch se aplica
   ao archive de `6af9f75c`. O manifesto e a tag de publicação devem
   identificar este A. Guardar o recibo anterior com seu SHA original.
   O build Next/OpenNext e o `npm ci` do ensaio usaram Node 24.19.0. Usar
   `cf` fixado pelo lock (1.0.0-rc.2) com Node 26.13.1 para preparar e
   enviar o prebuilt. Conferir os hashes do manifesto do pacote autorizado
   em `frontend/cloudflare/.cloudflare/output/v1` e registrar SHA de A,
   hash do patch e manifesto no recibo. O `j8-artifact-manifest.json`
   do prebuilt local de `6af9f75c` tem SHA-256
   `d726c7f9166c8d157d7756d3dda58f47b1e013487edded1bc7992e6f5723f789`.
   Um novo build exige nova conferência dos hashes e recibo do artefato.
   A origem pública de build é
   `NEXT_PUBLIC_API_URL=https://api.igreja12.com.br`. Conferir somente o
   binding `ASSETS`, `workersDev=false` e `previewUrls=false`, sem
   domínios, rotas ou triggers no pacote. O prefixo `frontend/` do Git em
   T continua no SHA A. O patch de infraestrutura é aplicado apenas na
   cópia de build.
3. Conferir a integridade de OpenAPI em checkout isolado de A, com as
   dependências de A. Da raiz, rodar
   `python backend/scripts/export_openapi.py --check` e confirmar SHA-256
   `384b3b93606c9ff7e81221214fd08d01fe87d527f4c31fbee780fe31f8209aa8`
   no `frontend/openapi.json`. Conferir também a compatibilidade parcial
   da versão anterior com A (§12.7). O smoke com mock do build é uma prova
   local de frontend. A volta exige o contrato conferido e smoke nos três
   hosts contra A.
4. Antes de publicar, confirmar **SIM 5 nominal** para upload, promoção
   e eventual volta da versão do painel. Registrar operador, contas e
   conversa de teste autorizadas, papéis e efeitos permitidos. O login
   pode gravar sessão e auditoria, e abrir Conversas pode marcar leitura.
   Ausência de autorização, A10 verde ou prova de compatibilidade
   suspende J8.

#### J8: dry run, upload e promoção

Com a A10 verde e o SIM 5 confirmado, apontar `J8_FRONTEND` para o diretório
`frontend` da cópia revisada. O dry run do prebuilt é obrigatório.
Conferir a tag `j8-6af9f75c` e somente `ASSETS` na saída. O comando
`cf deploy` direto fica fora deste procedimento.

```bash
cd "${J8_FRONTEND:?informe o diretório frontend da cópia revisada}/cloudflare" || exit 1
cf_node=/home/raniel-linux/.local/share/mise/installs/node/26.13.1/bin/node
cf_cli=../node_modules/cf/bin/cf
export CLOUDFLARE_ACCOUNT_ID=f3e9829232eb12ca3142d704d9455ce2
export CLOUDFLARE_SEND_METRICS=false
"$cf_node" "$cf_cli" workers versions create --prebuilt --dry-run --tag j8-6af9f75c
```

Só avançar após o dry run passar e a conferência confirmar o prebuilt.

```bash
"$cf_node" "$cf_cli" workers versions create --prebuilt --tag j8-6af9f75c --message "J8 frontend A 6af9f75c"
```

Conferir em leitura o UUID retornado, sua conta, Worker, tag e o binding.
Antes de promover, confirmar que a versão anterior registrada no V5 ainda
recebe 100%. Usar o UUID novo conferido:

```bash
read -r -p "UUID da nova versão conferida: " j8_version
[[ "$j8_version" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || exit 1
j8_versions=$(printf '[{"version_id":"%s","percentage":100}]' "$j8_version")
"$cf_node" "$cf_cli" workers deployments create --worker igreja12-frontend-prod --strategy percentage --versions "$j8_versions"
```

Confirmar o deployment e a versão a 100%, os três domínios existentes e
`workers.dev` e previews desligados. Registrar o UUID da versão e o ID do
deployment. Preservar DNS, domínios, rotas e triggers.

#### Smoke pós-J8 e volta do painel

1. Nos três hosts públicos, verificar HTTPS/TLS, o destino Cloudflare e
   HTML, JS, CSS e manifesto. Conferir o redirect legado `app/admin`
   (`https://app.igreja12.com.br/admin`) para `painel.igreja12.com.br`.
   Na API de A, verificar `/health`, `/ready` e preflight CORS a partir
   das três origens.
2. Em sessões novas com papéis autorizados, verificar login e sessão,
   Hoje, Conversas, `/gestao`, detalhe e alerta de célula e Console Master.
   Usar somente a conversa e as contas aprovadas. Preservar os gates e
   evitar envios ou outras mutações fora do smoke autorizado.
3. Provar CSP nos documentos. Registrar **zero eventos
   `securitypolicyviolation` e zero mensagens de violação de CSP no
   console**. Registrar horários, versão, deployment e resultados antes
   de seguir para J9/J10.

Se o smoke falhar, a volta só do painel requer que V5/5.1 e §12.7 tenham
confirmado a compatibilidade da versão anterior e que o SIM 5 cubra a
volta. No mesmo Worker, promover a 100% a versão anterior anotada no V5.
Para o UUID esperado:

```bash
"$cf_node" "$cf_cli" workers deployments create --worker igreja12-frontend-prod --strategy percentage --versions '[{"version_id":"edee314b-7be2-4d49-86ce-f4d9ceb0bb1a","percentage":100}]'
```

A troca cria um novo deployment. DNS e Custom Domains permanecem, e a
Vercel fica fora da rota de retorno. Repetir o smoke nos três hosts e em
sessão nova, considerando a propagação e caches de abas abertas. Registrar
o ID do deployment de volta. Sem compatibilidade confirmada ou se a
volta falhar, parar para decisão de correção adiante. O backend, os
workers e os gates da A10 permanecem.

Entre J4 e A10 a API responde `503`. Entre A10 e J8, a versão anterior
opera com as limitações da §12.7. Deixar V5 pronto para executar J8 logo
depois da A10.

### 12.6 Kit e roteiro do dia

Referência atualizada na Fase 4 para **A** =
`6af9f75c8d673cb3454de1f8740a0acc509937ff` (`EXECUTOR_SHA` =
`37c7d68d60b6f86cfb1fe75d4c720530537845d6`). Os valores de runtime da VPS
(IDs dos contêineres, gates, arquivo privado efetivo, digest do catálogo e
imagem do candidato) são revalidados e fixados no kit durante os blocos `5.1`
e `5.2`.

- **Backend e painel publicados:** SHA **A**
  (`6af9f75c8d673cb3454de1f8740a0acc509937ff`), fixo na ferramenta
  (`TARGET_COMMIT_SHA` / `APPLICATION_SHA`; aplicador `EXECUTOR_SHA` =
  `37c7d68d60b6f86cfb1fe75d4c720530537845d6`). Outro SHA é recusado
  (`unreviewed-release`). O plano soma **130 migrations** (`78` de base +
  **52 pendentes**: `44` transacionais e `8` `CONCURRENTLY`, terminando em
  `20261112_160000_celula_alerta_regras.sql`).
- **Ferramenta da virada:** SHA integrado da PR **T** sobre **A** na `main`
  (`<SHA_T>`). Os checks `backend-tests`, `frontend-ci`, `e2e-critical`,
  `rls-integration` e `synthetic-release`, além do ensaio Docker da 4.6
  (`test_first_transition_window_backup_docker`), precisam estar verdes antes
  de gerar e copiar o kit.

**Kit (onde cada item fica na VPS):**

| Item | Local na VPS | Observação |
|---|---|---|
| Ferramenta no `<SHA_T>` (só a pasta `deploy/`) | `/opt/pastorai-releases/tool-<SHA_T>/deploy` (5.2 usou `tool-9ca15e783870a1c7349c61d6b1bae227fed5f37e`) | copiada no V8 |
| Repositório com os objetos Git de **A** (`e1c63ed1`), **T** do 5.2 (`9ca15e78`) e `EXECUTOR_SHA` do aplicador (`37c7d68d`) | `/opt/pastorai-releases/repo` | atualizar e conferir os três commits com `git cat-file -e` no V8 (`4.2 h`) |
| Python 3.13 com psycopg2 2.x | `/var/lib/pastorai-first-transition/venv/bin/python` | venv isolada da ferramenta |
| Configuração da transição | `/var/lib/pastorai-first-transition/window/first-transition.json` | gerada no kit com `sha` = `6af9f75c...`, fora do Git |
| Configuração do backup da janela | `/var/lib/pastorai-first-transition/window/backup.json` | gerada no kit; `restore_excluded_expected` fixado após V9 |
| Configuração das entradas e escritores | `/var/lib/pastorai-first-transition/window/bindings.json` | atualizada após fechamento de envios da `5.2` se os IDs mudarem |
| Pastas do backup e do clone (root, 0700) | `/var/lib/pastorai-first-transition/window-backups` e `.../clone-work` | criadas no V8 |
| Imagem do backup e do clone | `postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929` (a mesma do CI) | `docker pull` no V8 |
| Imagem e pacote do candidato **A** (`e1c63ed1...`) | imagem `igreja12-v8-a:e1c63ed1-52` = `sha256:de4a6b234e0cda9dadbeec0dd93df8a35f275bcdba862adfc20218d0af999434` (não retaguar `pastorai-backend:latest`) | layout e digest conferidos antes do `prepare-layout` |
| Layout do candidato e arquivo de espera da A9 | `/opt/pastorai-releases/e1c63ed1dfaaacf26c21a3cc8d9c8c3151c0aae0/` e `/var/lib/pastorai-first-transition/state/a9-hold.override.yml` | criados por `prepare-layout` no V8 |
| Arquivo privado efetivo do runtime (`0600`, `root`) | caminho efetivo externo ao layout verificado (ex.: `/etc/pastorai/.env.v2` ou `/etc/pastorai-private/runtime.env`) | conferir variáveis obrigatórias de **A** só por nome (`12.7`) e gates fechados no `V2`/`5.2` |
| Arquivo privado do aplicador | `/root/igreja12-janela.conf` (`root`, `0600`, uma linha `MIGRATION_DATABASE_URL=`) | derivado da `DATABASE_URL` efetiva sem imprimir valor |
| Diário da janela | `/var/lib/pastorai-first-transition/state/journal` | vazio no início (não pode existir diário velho) |

**Fatos operacionais vigentes (atualizados na Fase 4):**

1. Gates repetidos idênticos nos contêineres legados (ex.: `ALLOW_REAL_SENDS=true`
   repetido em `broadcast-worker`): tratados como um só por `_unique_gates`;
   valores divergentes no legado recusam com `driver-inspect-gates`, enquanto
   no candidato qualquer repetição de gate recusa com `candidate-inspect-gates`.
2. Na sessão do aplicador (`postgres` sem `SUPERUSER`, `rolbypassrls=true`,
   `rolcreaterole=true`, `statement_timeout = '2min'`, `lock_timeout = 0`):
   - **Não alterar a role persistente no Supabase** (`ALTER ROLE`). `PGOPTIONS`
     não passa no executor nem no pooler do Supabase; `migrate.py` define apenas
     `SET LOCAL lock_timeout = '2s'`, herdando o `statement_timeout = '2min'`
     da role.
   - **Paridade do clone (Decisão 7):** `WindowBackup` separa `restore_user =
     'clone_admin'` (usada só no `pg_restore` e setup do clone) de
     `migration_user = 'postgres'` **sem `SUPERUSER`**, configurada com
     `BYPASSRLS`, `CREATEROLE`, `CREATEDB`, `INHERIT`, `ADMIN OPTION` nas roles
     `anon`/`authenticated`/`service_role`, `ALTER ROLE service_role BYPASSRLS` e
     `statement_timeout = '2min'`, verificados na conexão antes do replay e
     registrados em `clone_rehearsal['applicator_role']`. Também verifica RLS/grants
     das roles de runtime em `clone_rehearsal['rls_grants_verified']`. O `V1`/`1.2`
     em PROD confirma `pg_roles` e `pg_auth_members` equivalentes na role `postgres`
     de PROD.
   - **Regra de parada do V9 (Decisão D9, item 4.2 d):** o recibo de
     `rehearse-backup` registra `dump_seconds`, `restore_seconds`,
     `migrations_seconds`, `max_migration_seconds`, `seconds` (total) e
     `migration_timings` (todas as **52 migrations**). A regra D9 barra **apenas
     se alguma migration individual (`max_migration_seconds`) ultrapassar
     `60 s`** (o tempo total do ensaio não barra).

#### Estado após a recriação canônica e o 5.3 (24/11/2026)

Os quatro processos de aplicação voltaram ao projeto Compose `pastorai`,
na mesma imagem legada `sha256:4a65f30e…`, com os gates de envio fechados.
IDs, `window_digest` de referência do J1
(`97a3efe110810da59403fa6615ccf811f4f09c259a5c9949f5de2482867c358c`) e o
roteiro J1–J2 estão em [RECIBO-5-3-20261124.md](RECIBO-5-3-20261124.md).
O `plan_digest` permanece o do 5.2.

#### Estado após o bloco 5.2 (24/11/2026)

O bloco 5.2 adotou a pilha viva `j120776b1afbddd466anew_*` como topologia
oficial (IDs no recibo), retargetou A para `e1c63ed1…`, instalou o layout
sem trocar o tráfego, refez o ensaio das 52 migrations num clone
(`final_ledger=130`, `max_migration_seconds=0,219`) e fechou
`ALLOW_REAL_SENDS=false` (duas ocorrências) e `BREVO_SEND_MODE=off` no
`.env` do cron/legado. Detalhes, rollback e o aviso de `compose_project`
para o `run`: [RECIBO-5-2-20261124.md](RECIBO-5-2-20261124.md). Os
containers `pastorai_*` de aplicação continuam parados e preservados.

#### Preparação (V8, SIM próprio; V9 dentro dele)

No computador do operador, substituir `<SHA_T>` pelo SHA integrado de T.
O checkout precisa conter esse commit, **A**
(`6af9f75c8d673cb3454de1f8740a0acc509937ff`) e `EXECUTOR_SHA` do aplicador
(`37c7d68d60b6f86cfb1fe75d4c720530537845d6`).

```bash
SHA_T='<SHA_T>'
git archive --format=tar "$SHA_T" deploy | ssh vps "sudo install -d -m 755 /opt/pastorai-releases/tool-${SHA_T} && sudo tar -x --no-same-owner -C /opt/pastorai-releases/tool-${SHA_T}"
git update-ref refs/transition/a 6af9f75c8d673cb3454de1f8740a0acc509937ff &&
  git update-ref refs/transition/tool "$SHA_T" &&
  git update-ref refs/transition/executor 37c7d68d60b6f86cfb1fe75d4c720530537845d6 &&
  git bundle create /tmp/first-transition.bundle refs/transition/a refs/transition/tool refs/transition/executor &&
  git update-ref -d refs/transition/a &&
  git update-ref -d refs/transition/tool &&
  git update-ref -d refs/transition/executor
```

```bash
scp /tmp/first-transition.bundle first-transition.json backup.json bindings.json vps:/tmp/ && rm -f /tmp/first-transition.bundle
ssh vps "sudo git -C /opt/pastorai-releases/repo fetch /tmp/first-transition.bundle 'refs/transition/*:refs/transition/*' && sudo git -C /opt/pastorai-releases/repo cat-file -e 6af9f75c8d673cb3454de1f8740a0acc509937ff^{commit} && sudo git -C /opt/pastorai-releases/repo cat-file -e ${SHA_T}^{commit} && sudo git -C /opt/pastorai-releases/repo cat-file -e 37c7d68d60b6f86cfb1fe75d4c720530537845d6^{commit} && sudo rm -f /tmp/first-transition.bundle"
```

Na VPS (`ssh vps`, depois `sudo -i`):

```bash
W=/var/lib/pastorai-first-transition
install -d -m 700 $W/window $W/window-backups $W/clone-work
install -m 600 /tmp/first-transition.json /tmp/backup.json /tmp/bindings.json $W/window/ && rm /tmp/first-transition.json /tmp/backup.json /tmp/bindings.json
docker pull postgres@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929
# ENV_EFETIVO = arquivo privado 0600 fora de /opt/pastorai-current (ex.: /etc/pastorai/.env.v2 ou /etc/pastorai-private/runtime.env)
(umask 077; grep -E '^DATABASE_URL=' "$ENV_EFETIVO" | sed 's/^DATABASE_URL=/MIGRATION_DATABASE_URL=/' > /root/igreja12-janela.conf)
stat -c '%U %a' "$ENV_EFETIVO" /root/igreja12-janela.conf
```

Esperado: os dois arquivos pertencem a `root` com permissão `600`.

Variáveis usadas em todos os comandos seguintes (na VPS, como root):

```bash
PY=/var/lib/pastorai-first-transition/venv/bin/python
T=/opt/pastorai-releases/tool-<SHA_T>/deploy/first_transition_window.py
W=/var/lib/pastorai-first-transition/window
ARGS="--config $W/first-transition.json --backup-config $W/backup.json --bindings-config $W/bindings.json --env-file /root/igreja12-janela.conf --env-var MIGRATION_DATABASE_URL"
```

Layout do candidato (V8) e conferências (V9):

```bash
$PY -E -s $T prepare-layout --config $W/first-transition.json
$PY -E -s $T prepare $ARGS
$PY -E -s $T check $ARGS
$PY -E -s $T check-bindings $ARGS
$PY -E -s $T rehearse-backup $ARGS
```

Esperado: `prepare-layout` grava o pacote exato de **A** (`e1c63ed1...`);
`prepare` imprime `plan_digest` e `window_digest` (anotar os dois; o
`window_digest` de referência para o SIM 2 é o do `prepare` refeito **depois**
de gravar `restore_excluded_expected`, com `restore_excluded_pinned: true`);
`check` com `same_database` e `ddl_free` `ok` nas duas leituras;
`check-bindings` com as duas entradas `open` e `unknown_writers: 0`;
`rehearse-backup` termina com recibo das **52 migrations** no clone
(`applied: 52`, `final_ledger: 130`, `concurrent: 8`, `max_migration_seconds <= 60.0`,
`applicator_role.rolsuper: false`, `applicator_role.statement_timeout: "2min"`,
`rls_grants_verified`), além de `restore_excluded`, `final_schema_digest` e tempos
de cópia, restore e cada migration. Cópia externa do `window.dump` fica
dispensada (`4.2 d` / D13); `window-backups` (0700) guarda o dump e as listas
`restore-full.list` / `restore.list` (0600) até o fim da janela.

**Travar os números do restore no `backup.json` (antes de pedir o SIM 2):**
conferir `restore_excluded` do recibo do `V9` e copiar exatamente para
`restore_excluded_expected` em `$W/backup.json`, repetindo `prepare` e
`rehearse-backup` na véspera (nunca editar no horário da janela). Como `Q_CATALOG`
compara apenas o schema `public` + default ACLs em namespace `0`/`public`, os itens
excluídos do restore (`supabase_vault`, schema `vault` e event triggers de
superusuário) ficam fora do escopo comparado e não causam divergência em
`final['catalog'] == final_schema_digest`.

#### Roteiro do dia

Horário de exemplo: início às 10:00 (Brasília), em dia útil. Duração máxima a
registrar no J1: 120 min. Em todos os passos, os comandos rodam na VPS como
root com as variáveis acima.

| Hora | Passo | Duração | Comando que o operador dispara | Se falhar |
|---|---|---|---|---|
| 09:30 | V7 foto dos outros sistemas (V4 dispensado, D13) | 10 min | bloco da seção 12.0 | Algum outro sistema fora do ar: não abrir a janela. |
| 10:00 | **SIM 2** — J1 abrir a janela | 5 min | `$PY -E -s $T prepare $ARGS` e conferir `plan_digest` e `window_digest` do V9 final; registrar início UTC, operador, 120 min e SHAs | Digest diferente: parar; algo mudou desde o V9. |
| 10:05 | J2 pausar só o backup da Igreja 12 | 2 min | `mv /etc/cron.d/pastorai-backup /root/pastorai-backup.cron.pausado` | Se não existir, conferir com `ls /etc/cron.d/` e anotar. Nunca parar o serviço `cron`. |
| 10:07 | **SIM 3** — J3 a J6 (`run`, inclui o ponto de não retorno) | 20–35 min | `$PY -E -s $T run $ARGS --expect-plan-digest <plan> --expect-window-digest <window>` | Consultar `$PY -E -s $T status --config $W/first-transition.json`. Pré-marcador (`contained-pre-ddl`, `backup-window-used`): `resume-legacy` se autorizado. Pós-marcador (`ddl-marker`): `run` recusa sempre (`transition-stopped` no orquestrador; JSON da CLI `"refused": "window-transition-refused"` e estado em `recovery.state`); seguir tabela 12.2.1. |
| 10:40 | anotar `a10_token` do resultado | 1 min | — | Resultado sem `a10_token`: não seguir para a A10. |
| 10:42 | **SIM 4** — J7 A10 | 5–10 min | `$PY -E -s $T a10 $ARGS --expect-plan-digest <plan> --expect-window-digest <window> --a10-token <a10_token>` | Se `a10-partial`, repetir o mesmo comando `a10`. Se `a10-contained` ou `a10-containment-incomplete`, seguir tabela 12.2.1 sem reabrir sozinho. |
| 10:52 | **SIM 5** — J8 painel de **A** (`6af9f75c`) | 15 min | após A10 verde, dry run, upload de versão, promoção a 100% no Worker e smoke nos três hosts (§12.5) | Se falhar, voltar à versão anterior no mesmo Worker somente quando a compatibilidade estiver confirmada (§12.7). |
| 11:07 | J9 configurar `/opt/pastorai-current`, provar 1 backup manual e religar cron | 10 min | comandos da seção 12.2.2 (mesmo `env -i` do cron com `PASTORAI_ENV_FILE='<ENV>'` e `/usr/local/sbin/pastorai-backup.sh`, `sha256sum -c`, `backup-status.json`, `docker inspect`, depois instalar o cron novo em `/etc/cron.d/pastorai-backup`) | Sem `BACKUP_OK` novo (stamp/archive/intervalo), `"status":"verified"` e apoio despausados, não religar cron nem fechar janela. |
| 11:17 | J10 foto dos outros sistemas e `diff` com a das 09:30 | 10 min | bloco da seção 12.0 | Diferença: não mexer em outro sistema; avisar o Raniel. |
| 11:27 | Encerramento | — | registrar horários, resultado do `run`, da A10, do J8, do J9 e `window_backup_id` | — |

### 12.7 Conferências estáticas da fase 4.4 (SHA **A** = `6af9f75c8d673cb3454de1f8740a0acc509937ff`)

Resultado das conferências locais no código de **A** (`6af9f75c`) para
V1, V5 e 5.1–5.2. A leitura da configuração efetiva, a comparação
nominal do ledger e da role aplicadora, e a prova do fechamento dos
envios na imagem legada ainda são gates da 1.2/5.1–5.2.

1. **Variáveis obrigatórias do backend em produção (`backend/app/config.py`, `Settings.assert_production_ready()` e `_validate_whatsapp_transporte()` — apenas NOMES, nunca valores):**
   - `APP_ENV` (`production`)
   - `CLERK_SECRET_KEY`, `CLERK_JWT_ISSUER`
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL`
   - `SECRETS_ENCRYPTION_KEY`
   - `EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_WEBHOOK_SECRET`
   - `WHATSAPP_TRANSPORTE` (não pode ser `"simulado"` em produção)
   - `REDIS_URL` deve estar configurada para o Redis efetivo. O default
     loopback pode satisfazer a checagem de presença no settings sem
     apontar para o Redis correto. Registrar presença e origem do
     override, e validar conectividade no teste autorizado.
   - `SESSION_JWT_SECRET` (mínimo `MIN_SESSION_SECRET_LEN` = 32 caracteres e diferente de `CLERK_SECRET_KEY`)
   - `FRONTEND_URL`, `APP_BASE_URL` (URLs `https://` explícitas, sem wildcard/loopback/path/query)
   - `CALENDAR_OAUTH_RETURN_ORIGINS` é obrigatória no boot de produção,
     inclusive com Google OAuth sem credenciais. Exige ao menos uma
     origem `https://` explícita, presente em `cors_origins`, diferente de
     `APP_BASE_URL` e fora de `painel.*`.
   - Além das travas operacionais preservadas nos gates (`ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off`, `BROADCAST_ASYNC_ENABLED=false`, `CELULAS_REQUESTS_ENABLED=false`, `WHATSAPP_SLA_ENABLED=false`).
   - Antes e depois do fechamento, conferir nos quatro processos presença,
     fonte do override e estado efetivo dos gates. A duplicidade de
     `ALLOW_REAL_SENDS` observada no broadcast impede inferir o estado.
     Resolver a duplicidade no Compose/arquivo privado efetivo e confirmar
     um único valor aprovado antes de fotografar os gates. Registrar
     ausência separadamente de um valor explicitamente fechado.

2. **Auditoria estática das 52 migrations pendentes (`plan.pending` de `A`):**
   - **Ledger e sessão:** o inventário local de A confere 78 nomes de base
     e 52 pendentes, com os 52 hashes verificados. Comparar os **nomes**
     com o ledger autorizado da 1.2; a contagem não basta. Nenhuma das 52
     altera `statement_timeout`. Conferir `SHOW statement_timeout` na
     conexão efetiva do aplicador (`2min` no ensaio). **D9** mantém o
     teto externo de **60 s por migration**.
   - **`lock_timeout`:** **46** definem `lock_timeout` explicitamente no SQL (`2s`), e **6** não possuem `lock_timeout` explícito no SQL (`20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`, `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`, `20260925_183811_preserve_platform_admins_on_tenant_deletion.sql`, `20260926_120446_platform_jev_settings.sql`, `20261023_110000_operations_outbox_pending_metrics_fn.sql`, `20261023_120000_auth_session_revocation.sql`; o executor `migrate.py` aplica `SET LOCAL lock_timeout = '2s'` por padrão em transações).
   - **`CONCURRENTLY` (8 não transacionais, 44 restantes transacionais):**
     todas as oito definem `SET lock_timeout='2s'` no SQL. O parâmetro
     `--lock-timeout 0` desliga só o ajuste do executor. O `SET lock_timeout`
     inicial do SQL continua aplicado à sessão fora de transação.
     Conferir o SQL de cada migration
     antes de registrar o timeout efetivo, sem presumir `0` pelo argumento
     do executor (por exemplo, `20261023_100001` define `2s`). A escrita no ledger
     é um efeito separado. Índice inválido ou sem ledger após o marcador
     segue §12.2.1. Lista: `20261023_100001_ai_usage_tenant_created_idx.sql`, `20261023_110001_notification_outbox_pending_created_idx.sql`, `20261023_110002_notification_outbox_retry_created_idx.sql`, `20261023_110003_notification_outbox_expired_lease_idx.sql`, `20261023_110004_messages_pending_agent_created_idx.sql`, `20261023_110005_work_queue_pending_created_idx.sql`, `20261028_100001_private_erasure_requests_overview_idx.sql`, `20261028_100002_private_resume_delivered_overview_idx.sql`.
   - **Tabelas pré-existentes/críticas com `ALTER TABLE` nas 52 pendentes:** `app_users` (`20260925_183811`), `agent_action_receipts` (`20261017_180100`), `pessoas` (`20261017_230000`, além dos `UPDATE` de `20260711_*`), `celula_solicitacao` (`20261018_060000`/`070000`/`080000`), `conversations` (`20261018_090000`, `20261019_120001`), `messages` (`20261018_120000`), `ai_usage_logs` (`20261023_100000` `FORCE ROW LEVEL SECURITY`), e `cell_alerts` (`20261112_160000_celula_alerta_regras.sql`: remove `NOT NULL` de `pessoa_id`, adiciona `regra_tipo`/`fato_chave`, habilita `FORCE ROW LEVEL SECURITY`, restringe política e revoga `DELETE`).

   - **Role aplicadora na VPS:** conferir `session_user` e `current_user`,
     ownership ou autoridade efetiva sobre `cell_alerts` e outros objetos
     do DDL, criação em `public` e `extensions`, disponibilidade e permissões
     das extensões `unaccent` e `btree_gist`, `CREATEROLE` ou autoridade
     equivalente e `ADMIN OPTION` para conceder `authenticated` se o
     membership precisar ser criado. Conferir `SELECT`/`INSERT` no ledger
     e acesso de preflight sob RLS. `BYPASSRLS` de runtime sozinho não
     comprova autoridade de aplicar. A role sintética do replay não
     substitui a prova da conexão, dos owners e dos grants efetivos.
   - **Roles preexistentes:** conferir os atributos e memberships efetivos
     das roles envolvidas, incluindo `authenticated`, e verificar se
     correspondem aos pré-requisitos das migrations.
   - **Funções `SECURITY DEFINER`:** conferir por assinatura o owner efetivo
     e as permissões `EXECUTE` (ACL) das roles que precisam chamar cada
     função. Para as que usam `row_security=off`, confirmar que o owner
     pode fazer a leitura prevista nas tabelas com `FORCE RLS`.
     `release_preflight.py` sozinho deixa assinaturas pendentes de
     verificação e não testa as ACLs de execução. Essas provas no alvo
     seguem pendentes para os blocos autorizados antes da janela.

3. **Contrato da API e volta do painel (`afdfb78d` contra A):**
   - Os OpenAPI gerados offline pelo exportador de A preservam os objetos
     das **279 operações comuns**. A tem 282 e adiciona somente
     `GET /cell-alert-rules`, `PUT /cell-alert-rules/{tipo}` e
     `GET /cells/me/alerts`. Essas três operações ficam fora da interface
     antiga.
   - Entre os schemas comuns, só muda `AlertOut.pessoaId`, agora nullable.
     A tela antiga conferida renderiza e baixa o alerta por ID, sem
     depender de `pessoaId`, e tolera `null` nesse fluxo. Igualdade das
     operações declaradas não comprova equivalência de comportamento.
   - P1.1 recusa login/acesso de operador revogado no Console Master e
     responde 409 à tentativa de revogar um operador da plataforma pela
     gestão da igreja. São recusas esperadas, inclusive com painel antigo.
   - A #697 aplica a política de senha do Clerk na ativação, redefinição
     e troca de senha. A recusa confirmada de política passa a retornar
     400 com mensagem controlada. Os objetos OpenAPI permanecem iguais
     aos do A anterior. O fallback parcial preserva essa regra de
     backend, e o smoke autorizado continua necessário.
   - A versão anterior no Worker é **parcialmente utilizável** para as
     superfícies comuns, se V5 confirmar sua proveniência e houver smoke
     autorizado nos três hosts contra A após a volta. Conferir sessão
     Bearer, origens CORS, Hoje, Conversas, gestão, células, Console Master
     e CSP conforme §12.5. Versão desconhecida ou smoke reprovado impede
     admitir a volta como concluída.

4. **Procedimento de fechar os envios antes da foto final dos gates (`5.2`, sem tocar em PROD na Fase 4):**
   - A prova viva do fechamento na imagem legada `sha256:4a65f30e...`
     segue pendente na 1.2/5.1–5.2. Confirmar a identidade efetiva antes
     de usar o procedimento. O SHA-fonte da imagem ainda é indeterminado.
   - Antes de gerar o snapshot de gates (`V8`/`V9`/`5.2`), consultar em leitura a fila por tipo e situação (`notification_outbox`, `work_queue`, agendamentos/campanhas).
   - Se algum dos quatro contêineres legados (`backend`, `cron-worker`, `broadcast-worker`, `queue-worker`) ainda estiver com gate de envio aberto, aplicar **exclusivamente com a mesma imagem já em execução observada no `5.1`** o arquivo privado/compose legado com `ALLOW_REAL_SENDS=false`, `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e `BROADCAST_ASYNC_ENABLED=false` (e removendo duplicidade divergente).
   - Se a aplicação do fechamento recriar contêineres, os IDs do Docker mudam: atualizar `bindings.json` / manifesto do kit com os **novos container IDs resultantes**, rodar `$PY -E -s $T check-bindings $ARGS`, `$PY -E -s $T prepare $ARGS` e repetir `rehearse-backup` antes de pedir **SIM 2** (`5.3`).

O kit gerado (três JSON, tarball do backend e notas) fica fora do Git, com a
equipe; o caminho exato está na descrição da PR que criou esta seção.
