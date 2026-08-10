# PastorAI V1 — runbook canônico de produção

Atualizado em 2026-08-07. Este é o procedimento operacional vigente para o
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
| Frontend Vercel | projeto `pastorai-frontend`, escopo `raniel-levis-projects` |
| Frontends públicos | `app.`, `admin.` e `painel.igreja12.com.br` |

O Clerk permanece deliberadamente na instância DEV durante esta promoção. Não
misture `pk_live/sk_live` com o issuer DEV: publishable key, secret key, issuer
e JWKS precisam pertencer à mesma instância.

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

A migration de broadcasts não ativa broadcasts legados e não faz backfill.

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
# processos capazes de faturar devem confirmar as duas travas fechadas.
for service in backend queue-worker cron-worker; do
  docker compose exec -T "$service" sh -lc '
    [ "${ALLOW_REAL_SENDS:-false}" = "false" ] &&
    [ "${ASAAS_BILLING_ENABLED:-false}" = "false" ] &&
    echo "billing gates: CLOSED"'
done
curl -fsS http://127.0.0.1:8000/health
ln -sfn "/opt/pastorai-releases/${PASTORAI_RELEASE_SHA}" /opt/pastorai-current
```

O esperado é uma linha `billing gates: CLOSED` por serviço. Qualquer ausência
ou valor diferente de `false` interrompe o deploy: mutações Asaas só podem
existir quando `ALLOW_REAL_SENDS=true` **e** `ASAAS_BILLING_ENABLED=true`, em um
gate financeiro posterior e explicitamente aprovado.

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
- publishable key Clerk da mesma instância DEV usada pelo backend;
- aliases `app.`, `admin.` e `painel.igreja12.com.br`.

## 8. Smokes sem efeitos externos

Com `ALLOW_REAL_SENDS=false`:

```bash
curl -fsS https://api.igreja12.com.br/health
curl -fsS http://127.0.0.1:8000/health
docker compose ps
```

Validar também:

- CORS para `app.`, `admin.` e `painel.`;
- login com usuário que exista na instância Clerk DEV;
- recuperação de senha retorna resposta neutra e não envia e-mail (supressão
  esperada enquanto o gate estiver fechado);
- isolamento das portas 8000/8080;
- ausência de placeholders no `.env`;
- frontend sem referências ao Supabase DEV ou localhost.

Mesmo depois desses smokes, mantenha `ASAAS_BILLING_ENABLED=false` enquanto as
igrejas-piloto estiverem em cortesia. Não habilite a flag sem inventário das
assinaturas rastreadas, backup fresco e canário financeiro separado.

Somente após esses smokes decidir o gate separado
`ALLOW_REAL_SENDS=true`. A leitura do QR da Evolution e qualquer canário de
e-mail/WhatsApp/cobrança ocorrem em uma janela controlada. O recebimento real
do e-mail de recuperação pelo Brevo pertence a esse canário pós-gate, usando
uma conta de teste e um único envio observado.

## 9. Rollback

- Backend: apontar `/opt/pastorai-current` para o SHA anterior e recriar os
  containers a partir desse release; nunca restaurar ou apagar `deploy/.env` e
  volumes por engano.
- Frontend: promover o deployment Vercel anterior.
- Banco: migrations aditivas não são revertidas automaticamente. Corrigir por
  nova migration revisada; não executar rollback destrutivo improvisado.

## 10. Evidência mínima de conclusão

Registrar:

- SHA de `main` implantado;
- IDs das migrations aplicadas;
- resultado de testes/CI;
- `docker compose ps`;
- health local e público;
- CORS e login;
- deployment/aliases Vercel;
- estado explícito de `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED` e
  `BROADCAST_ASYNC_ENABLED`, incluindo a prova pós-restart de que billing
  permaneceu fechado por padrão, sem imprimir o `.env`.
