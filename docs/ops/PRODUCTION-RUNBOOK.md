# PastorAI V1 — runbook canônico de produção

Atualizado em 2026-08-27. Este é o procedimento operacional vigente para o
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

Antes de aplicar:

1. provar o ref `pffafnchtxbimpwyaczq`;
2. listar o ledger remoto;
3. ler o SQL versionado do SHA que será implantado;
4. aplicar em ordem, uma migration por vez;
5. verificar colunas, constraints, RLS e advisors.

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
