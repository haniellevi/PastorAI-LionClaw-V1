# PastorAI V1 — runbook canônico de produção

Atualizado em 2026-08-28. Este é o procedimento operacional vigente para o
Igreja 12. Não contém segredos; valores reais ficam somente nos provedores e no
`.env` do release ativo, acessível por `/opt/pastorai-current/deploy/.env`.

Backup, teste de restauração e firewall: consulte
[BACKUP-FIREWALL-RUNBOOK.md](BACKUP-FIREWALL-RUNBOOK.md).

## 1. Alvos oficiais

| Camada | Produção |
|---|---|
| Supabase | `pffafnchtxbimpwyaczq` |
| VPS Hostinger | `76.13.234.127` — `srv1728329.hstgr.cloud` — Campinas |
| Backend público | `https://api.igreja12.com.br` |
| Releases na VPS | `/opt/pastorai-releases/<sha>` |
| Release ativo | `/opt/pastorai-current` (symlink para um release imutável) |
| Frontend Vercel | projeto `pastorai-frontend-prod`, escopo `raniel-levis-projects` |
| Frontends públicos | `app.`, `admin.` e `painel.igreja12.com.br` |

O Clerk está na instância PROD. Publishable key, secret key, issuer e JWKS
precisam pertencer à mesma instância; nunca misture prefixos `pk_test_` ou
`sk_test_` com o issuer de produção.

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

- `ALLOW_REAL_SENDS=false` bloqueia os efeitos externos até os smokes de
  saúde/login terminarem. Em produção, conexão Evolution e envios Brevo
  retornam erro controlado em vez de simular sucesso.
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

> **Bloqueio corrente (2026-09-04):** não existe comando de aplicação
> operacional liberado neste SHA. `apply_migrations.py` é legado e não deve ser
> invocado diretamente. `apply_migrations_catalog_bound_v2.py` valida o catálogo,
> mas bloqueia `status`, `harden-ledger`, `bootstrap-ledger` e `apply` antes da
> conexão até existirem trust anchors externos, evidências separadas DEV/PROD e
> decisão humana de cutover. Os registros abaixo descrevem história, não
> autorização atual.

Existem dois históricos diferentes:

- `supabase_migrations.schema_migrations`, ledger nativo do Supabase;
- `public.schema_migrations`, ledger de controle do executor local de arquivo
  único.

Eles não são equivalentes. Nome, ordem ou presença em um deles não autorizam
copiar, preencher, reaplicar ou registrar entradas no outro. O preflight PROD
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

Validar e subir pelo caminho exato do candidato. Só depois do health local
trocar o symlink estável:

```bash
PASTORAI_RELEASE_SHA=<sha-exato-de-main>
cd "/opt/pastorai-releases/${PASTORAI_RELEASE_SHA}/deploy"
chmod 600 .env
docker compose config --quiet
docker compose build backend
docker compose up -d
docker compose ps
# Prova pós-restart sem imprimir o .env nem qualquer segredo. Todos os
# processos capazes de enviar/faturar devem confirmar as travas fechadas.
for service in backend queue-worker cron-worker; do
  if ! docker compose exec -T "$service" sh -lc '
      [ "${ALLOW_REAL_SENDS+x}" = "x" ] &&
      [ "$ALLOW_REAL_SENDS" = "false" ] &&
      [ "${ASAAS_BILLING_ENABLED+x}" = "x" ] &&
      [ "$ASAAS_BILLING_ENABLED" = "false" ] &&
      [ "${BREVO_SEND_MODE+x}" = "x" ] &&
      [ "$BREVO_SEND_MODE" = "off" ] &&
      echo "external-send gates: CLOSED"'; then
    echo "external-send gates: OPEN or unverifiable for ${service}" >&2
    exit 1
  fi
done
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/ready
ln -sfn "/opt/pastorai-releases/${PASTORAI_RELEASE_SHA}" /opt/pastorai-current
```

O esperado é uma linha `external-send gates: CLOSED` por serviço. Qualquer
ausência ou valor diferente de `false`/`off` interrompe o deploy: mutações
Asaas só podem existir quando `ALLOW_REAL_SENDS=true` **e**
`ASAAS_BILLING_ENABLED=true`, em um gate financeiro posterior e explicitamente
aprovado. Brevo permanece em `BREVO_SEND_MODE=off` até seu canário separado;
`canary` e `live` não são estados aceitáveis antes dos smokes sem efeitos
externos.

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

No projeto Vercel, confirmar sem revelar valores:

- `NEXT_PUBLIC_API_URL=https://api.igreja12.com.br`;
- autenticação apontando para a mesma instância Clerk PROD usada pelo backend;
- aliases `app.`, `admin.` e `painel.igreja12.com.br`.

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

A cadeia auditada é `c2fb16ad9a6b028c317c56a0b02c4362ae903e26` ->
`11ae294fd4459e55cb31b3342fb8f0a766ac0a03` ->
`1b299e7fcc709ae2528db1c3f76aa15f14dbcf06`; somente `c2fb16ad` está
integrado em `main`. Os dois commits seguintes são candidatos locais. No
snapshot privado `0700/0600` do SHA `1b299e7`, a seleção ampla contabilizou 961
testes (801 aprovados, 160 skips, zero falhas e zero erros). A regressão separada
do probe histórico de transporte TLS passou `125/125`, sem testar o executor v2
ou o job PG17. A seleção focal no checkout compartilhado coletou 186 itens, com
183 aprovados, três skips PG17 e zero falhas após a reconciliação documental. A
decisão do executor v2 registra composição, runtime e horários. Esses resultados
não autorizam uso deste runbook, segredos, DEV, PROD ou migration.

O único estágio corrente global é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`,
restrito à consulta remota somente leitura de `refs/heads/main`, ao preflight da
base, ao push da branch candidata, à abertura da PR e à observação do CI e do
Vercel Preview automáticos. Não autoriza merge, banco compartilhado, DEV, PROD,
migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

Somente após a integração posterior sob gate próprio e o CI verde, o estágio
funcional futuro poderá ser
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`;
ele não é o estágio corrente nem está autorizado.

## 10. Rollback

- Backend: apontar `/opt/pastorai-current` para o SHA anterior e recriar os
  containers a partir desse release; nunca restaurar ou apagar `deploy/.env` e
  volumes por engano.
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
