# PastorAI V1 — runbook canônico de produção

Atualizado em 2026-08-05. Este é o procedimento operacional vigente para o
Igreja 12. Não contém segredos; valores reais ficam somente nos provedores e em
`/opt/pastorai-lionclaw/deploy/.env`.

## 1. Alvos oficiais

| Camada | Produção |
|---|---|
| Supabase | `pffafnchtxbimpwyaczq` |
| VPS Hostinger | `76.13.234.127` — `srv1728329.hstgr.cloud` — Campinas |
| Backend público | `https://api.igreja12.com.br` |
| Projeto na VPS | `/opt/pastorai-lionclaw` |
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
BROADCAST_ASYNC_ENABLED=false
CALENDAR_OAUTH_RETURN_ORIGINS=https://admin.igreja12.com.br
```

- `ALLOW_REAL_SENDS=false` bloqueia WhatsApp, Asaas, Brevo, LLM e Google até
  os smokes de saúde/login terminarem. Em produção, mutações de billing Asaas
  retornam erro controlado e não alteram plano/assinatura localmente.
- `BROADCAST_ASYNC_ENABLED=false` mantém o worker persistente inativo e faz
  qualquer novo comunicado falhar antes de ser persistido; não existe fallback
  síncrono capaz de contornar o ledger/heartbeat.
- A ativação de cada flag exige recriar backend e worker; elas são lidas no boot.

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
BREVO_API_KEY
BREVO_FROM_EMAIL
BREVO_FROM_NAME
GOOGLE_OAUTH_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET
GOOGLE_OAUTH_REDIRECT_URI
```

`OPENAI_API_KEY` pode ficar vazio porque a aplicação aceita credencial BYO por
igreja. `GOOGLE_CALENDAR_ACCESS_TOKEN` é legado e pode ficar vazio; o fluxo
novo usa OAuth por igreja. Nunca imprimir, versionar ou transportar o `.env`
em tarball.

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
- `calendar_account_identity_binding_20260801`.

A migration de broadcasts só pode ser aplicada depois de o PR correspondente
estar revisado e mergeado. Ela não ativa broadcasts legados e não faz backfill.

## 5. Deploy reproduzível do backend

A VPS não é a fonte de verdade. O artefato vem de um checkout limpo do SHA
mergeado. `backend/Dockerfile`, `backend/.dockerignore` e
`deploy/docker-compose.yml` são versionados.

Na estação de deploy:

```bash
git fetch origin
git worktree add --detach <diretorio-temporario> <SHA_EXATO_DE_MAIN>
```

Antes de substituir arquivos na VPS:

- criar backup de `backend/` e `deploy/docker-compose.yml`;
- preservar `deploy/.env`;
- não copiar `.git`, caches, testes, arquivos `.env*` nem dependências locais;
- não remover volumes `redis_data`, `evolution_pg_data` ou
  `evolution_instances`.

Na VPS:

```bash
cd /opt/pastorai-lionclaw/deploy
chmod 600 .env
docker compose config --quiet
docker compose build backend
docker compose up -d
docker compose ps
curl -fsS http://127.0.0.1:8000/health
```

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
cd /opt/pastorai-lionclaw/deploy
docker compose config --quiet
docker compose up -d --build backend broadcast-worker
docker compose ps backend broadcast-worker
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

Somente após esses smokes decidir o gate separado
`ALLOW_REAL_SENDS=true`. A leitura do QR da Evolution e qualquer canário de
e-mail/WhatsApp/cobrança ocorrem em uma janela controlada. O recebimento real
do e-mail de recuperação pelo Brevo pertence a esse canário pós-gate, usando
uma conta de teste e um único envio observado.

## 9. Rollback

- Backend: restaurar o backup do código/Compose e recriar os containers; nunca
  restaurar ou apagar `deploy/.env` e volumes por engano.
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
- estado explícito de `ALLOW_REAL_SENDS` e `BROADCAST_ASYNC_ENABLED`.
