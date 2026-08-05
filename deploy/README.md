# Deploy do PastorAI na VPS (Docker Compose)

Stack: **VPS Hostinger** roda Evolution + backend + workers + Redis. O **banco** é o Supabase (externo) e o **frontend** vai na Vercel. Em produção, 8000/8080 ficam presos ao localhost e o acesso público passa por HTTPS/Nginx.

> VPS atual: `76.13.234.127` (`srv1728329.hstgr.cloud`, Campinas). O procedimento canônico de produção está em [`docs/ops/PRODUCTION-RUNBOOK.md`](../docs/ops/PRODUCTION-RUNBOOK.md).

---

## 1. Entrar na VPS (SSH)

Pelo terminal (Windows tem `ssh` nativo) ou pelo **Browser Terminal** no painel da Hostinger:

```powershell
ssh -i $env:USERPROFILE\.ssh\pastorai_vps root@76.13.234.127
```

## 2. Instalar Docker (uma vez)

```bash
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

## 3. Criar swap de 2GB (rede de segurança no 4GB)

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
free -h   # deve mostrar 2.0Gi de swap
```

## 4. Trazer o código pra VPS

Produção recebe um tarball do SHA revisado em `/opt/pastorai-releases/<sha>`;
não execute `git clone`/`git pull` na VPS. Preserve o `.env` existente e siga o
procedimento de release/rollback do runbook canônico.

## 5. Configurar as variáveis

Nunca sobrescreva um `.env` existente. Em primeira instalação, copie o template,
preencha os valores diretamente no console da VPS e mantenha o arquivo com modo
`600`; em upgrades, preserve o arquivo já validado.

Gere os segredos rápidos:

```bash
openssl rand -hex 16   # use p/ EVOLUTION_API_KEY, EVOLUTION_POSTGRES_PASSWORD, EVOLUTION_WEBHOOK_SECRET
# Fernet (SECRETS_ENCRYPTION_KEY):
docker run --rm python:3.13-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'"
```

Preencha também `DATABASE_URL` (pooler do Supabase, com a senha percent-encoded), `SUPABASE_SERVICE_ROLE_KEY`, `CLERK_SECRET_KEY`.

> 💡 Para o **1º teste** (só conectar o WhatsApp), você pode deixar `APP_ENV=development` para não precisar de todos os secrets ainda.

## 6. 🎯 Subir SÓ a Evolution e conectar o WhatsApp (QR)

```bash
docker compose up -d redis evolution-postgres evolution-api
docker compose logs -f evolution-api      # Ctrl+C quando ver "Server running"
```

Conectar o número (2 caminhos):

**A) Pela UI (mais fácil):** como a porta 8080 não é pública, abra um túnel no
PowerShell local e mantenha essa janela aberta:

```powershell
ssh -i $env:USERPROFILE\.ssh\pastorai_vps -L 8080:127.0.0.1:8080 root@76.13.234.127
```

Depois abra `http://127.0.0.1:8080/manager`, entre com a
`EVOLUTION_API_KEY`, crie a instância e **escaneie o QR** com o WhatsApp da
igreja (Aparelhos conectados → Conectar aparelho).

**B) Pela API:**
```bash
curl -X POST http://127.0.0.1:8080/instance/create \
  -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" \
  -d '{"instanceName":"filadelfia","integration":"WHATSAPP-BAILEYS","qrcode":true}'
# pegue o campo base64 do QR e escaneie, ou:
curl http://127.0.0.1:8080/instance/connect/filadelfia -H "apikey: $EVOLUTION_API_KEY"
```

✅ Quando o WhatsApp aparecer como conectado, a Evolution está no ar.

> ⚠️ **Nome da instância — leia antes de criar.** O worker só processa mensagens
> de uma instância **registrada** em `whatsapp_connections` (US-07: só o número
> oficial). O backend registra a instância com o nome **`igreja-<igreja_id>`**
> ao conectar **pela tela do painel** (Configuração → Conexão WhatsApp). Se você
> criar a instância manualmente com outro nome (ex.: `filadelfia`) e nunca
> conectar pela tela, **toda mensagem recebida é descartada em silêncio**
> (log: `Dropping message from non-official instance`). Para o fluxo real,
> **conecte o número pela tela do painel** — o `filadelfia` acima serve apenas
> para validar que a Evolution sobe e parea o QR. Alternativa: criar a instância
> manualmente já com o nome `igreja-<igreja_id>` da igreja piloto.

## 7. Subir a stack completa (backend + workers)

```bash
docker compose up -d --build
docker compose ps           # todos "running/healthy" (inclui queue-worker!)
docker compose logs -f backend
```

Na VPS, teste o backend: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`.

> 🔎 **Diagnóstico do recebimento de WhatsApp.** Se mensagens não entram nem são
> respondidas, confira nesta ordem:
> 1. `docker compose ps` — o **`queue-worker`** está `running`? Sem ele a
>    mensagem entra no Redis mas nunca é gravada.
> 2. `docker compose logs --tail=50 backend` — aparece `Rejected webhook with
>    invalid signature/token`? Então o `?token=` não bate: confira que
>    `EVOLUTION_WEBHOOK_SECRET` no `.env` é o mesmo que está na
>    `WEBHOOK_GLOBAL_URL` (a substituição `${...}` resolve isso automaticamente).
> 3. `docker compose logs --tail=50 queue-worker` — aparece `Dropping message
>    from non-official instance`? Então é o nome da instância (ver aviso acima).
> 4. Recebe no painel mas **não responde**? A igreja precisa de uma credencial
>    LLM **validada e ativa** (tela Agente IA, BYO OpenAI). Sem ela o agente
>    registra `agent_skipped_no_credential` e não responde.

---

## Comandos úteis

```bash
docker compose ps                 # status
docker compose logs -f <serviço>  # logs ao vivo
docker compose restart <serviço>  # reiniciar 1 serviço
docker compose down               # derrubar tudo (mantém volumes/dados)
docker compose up -d --build      # rebuild + subir
docker stats                      # uso de RAM/CPU por container
```

## Próximos passos (depois do MVP)
- **HTTPS + domínio:** adicionar Caddy (reverse proxy com TLS automático) e apontar `api.seudominio` → backend, `evo.seudominio` → Evolution.
- **Webhook seguro:** ✅ já validado pelo `?token=${EVOLUTION_WEBHOOK_SECRET}` na
  `WEBHOOK_GLOBAL_URL` (a Evolution v2 self-hosted não envia HMAC nem headers
  customizados, só preserva a query string). Ao migrar para domínio, trocar o
  host da `WEBHOOK_GLOBAL_URL` mantendo o `?token=`. Sobre HTTPS, o token na
  query fica protegido pelo TLS; rotacione o segredo se ele vazar em logs.
- **Firewall:** liberar só 80/443 (e 22) quando o Caddy estiver no ar; fechar 8080/8000 externos.
