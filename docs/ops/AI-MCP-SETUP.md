# PastorAI — Linux, Codex, Devin e MCPs

Este runbook separa o **runtime do produto** das ferramentas administrativas
usadas por agentes. MCP não é dependência do backend e não recebe automaticamente
os segredos de `deploy/.env`.

## Estado auditado em 2026-08-20

| Item | Estado | Decisão |
|---|---|---|
| Docker Engine / Compose | 29.7.2 / 5.5.0; daemon ativo; acesso validado com grupo `docker` | nenhuma reinicialização do Linux necessária |
| Node local | 24.19.0 instalado e padrão no NVM | `.nvmrc` e Frontend CI fixam a mesma versão |
| Python local | 3.13.14 instalado via `uv` | venv runtime em `backend/.venv-runtime` |
| Vercel CLI | ausente | dispensável: deploy via Git e operação via MCP oficial |
| Supabase CLI | 2.115.0 instalado; audit npm limpo | fixado como devDependency da raiz |
| Vercel MCP | oficial; registrado no Codex e Devin | OAuth é pessoal; reautenticar somente se a sessão expirar |
| Hostinger MCP | oficial; registrado no Codex e Devin | OAuth é pessoal; evitar token local e reautenticar somente se a sessão expirar |
| Brevo MCP | oficial; token MCP próprio | manter desligado até criar `BREVO_MCP_TOKEN` |
| Supabase local | Postgres 17 e MCP ativos em `127.0.0.1:54321`; registrado no Codex e Devin CLI | cópia vazia para tooling; não substitui o DEV hospedado |
| Supabase DEV hospedado | configuração preservada, mas desabilitada; ref histórico sem acesso na conta conectada | recuperar acesso ou criar novo projeto antes de habilitar |
| Supabase PROD | configuração somente leitura preservada, mas desabilitada | habilitar só para diagnóstico explícito, com escopo por projeto |
| Asaas | integração HTTP do backend já existe; nenhum MCP oficial localizado | testar somente no Sandbox; não instalar MCP comunitário financeiro |

Documentação primária:

- Vercel MCP: <https://vercel.com/docs/agent-resources/vercel-mcp>
- Hostinger MCP: <https://www.hostinger.com/support/11079316-hostinger-api-mcp-server/>
- Brevo MCP: <https://developers.brevo.com/docs/mcp-protocol>
- Supabase MCP: <https://supabase.com/docs/guides/ai-tools/mcp>
- Supabase CLI: <https://supabase.com/docs/guides/local-development/cli/getting-started>
- Docker pós-instalação: <https://docs.docker.com/engine/install/linux-postinstall/>
- Devin MCP: <https://docs.devin.ai/work-with-devin/mcp>
- Asaas autenticação: <https://docs.asaas.com/docs/authentication>

## 1. Preparar o Linux

Carregue o NVM e instale a versão usada pelo CI:

```bash
source "$HOME/.nvm/nvm.sh"
nvm install 24.19.0
nvm use
npm ci
```

Node 24.19.0 é a versão fixa do tooling e do Frontend CI. A CLI do Supabase
2.115.0 exige Node 20 ou superior; não use Node 20, que está EOL.

Instale o Python revisado e o ambiente runtime do backend:

```bash
uv python install 3.13.14
uv venv --seed --python 3.13.14 backend/.venv-runtime
backend/.venv-runtime/bin/python -m pip install --require-hashes -r backend/requirements.lock
backend/.venv-runtime/bin/python -m pip check
backend/.venv-runtime/bin/python backend/scripts/verify_manifest_requirements.py backend/requirements.txt
```

O `npm ci` da raiz instala a versão fixa da Supabase CLI. Use:

```bash
npm run supabase -- --version
```

`npm run doctor` procura `backend/.venv-runtime/bin/python` por padrão. Em uma
worktree isolada, só para reutilizar um ambiente Python já verificado, informe
o caminho explicitamente sem copiar nem alterar o ambiente original:

```bash
PASTORAI_RUNTIME_PYTHON=/caminho/para/backend/.venv-runtime/bin/python npm run doctor
```

Não instale Supabase CLI com `npm -g`; a instalação npm oficial é dependência de
projeto e deve ser chamada pelo package runner.

A Vercel CLI 59.1.4 foi avaliada, mas seu grafo transitivo atual reportou 30
advisories no `npm audit` (incluindo `tar` crítico). Como o projeto publica pela
integração Git e usa o MCP remoto oficial, a CLI não foi mantida como dependência.
Reavalie quando a Vercel publicar uma árvore corrigida; não use `npm audit
fix --force`, que hoje propõe um downgrade incoerente para 54.17.3.

## 2. Reparar o Docker local

O usuário já pertence ao grupo `docker` e `/run/docker.sock` está corretamente
como `root:docker`. O daemon foi validado na sessão renovada e pelo contexto de
host do Codex (versão 29.7.2). O sandbox interno pode representar o socket como
`nobody:nogroup`, mas isso não reflete o estado do host.

As unidades já foram recarregadas e não é necessário reiniciar o Linux. Em um
terminal novo, a verificação é:

```bash
sudo systemctl daemon-reload
stat -c '%A %U %G %n' /run/docker.sock
newgrp docker
docker info
docker compose version
```

O resultado esperado do `stat` é grupo `docker`. `newgrp` vale apenas para o
novo shell; reabrir um app é suficiente se ele tiver nascido antes da associação
ao grupo. Só reinicie `docker.socket`/`docker.service` se o socket voltar a
ficar incorreto, pois o restart interrompe containers. O grupo `docker` equivale
a privilégio de root, portanto não adicione usuários não confiáveis.

Docker Engine com Compose é suficiente para a stack local. Docker Desktop não
é necessário no Linux e não deve ser instalado apenas para usar Supabase.

Para validar o Compose sem criar um arquivo de segredos:

```bash
PASTORAI_ENV_FILE=.env.example docker compose \
  --env-file deploy/.env.example \
  -f deploy/docker-compose.yml config --quiet
```

Para subir serviços, copie o template para `deploy/.env`, use modo `600` e
preencha somente esse arquivo ignorado pelo Git. Não execute a stack completa
enquanto o Supabase DEV e o Clerk de teste não estiverem definidos. Mantenha
`ALLOW_REAL_SENDS=false`.

## 3. Codex no Linux

O workspace fornece `.mcp.json` como inventário portável. Como `.codex/` está
montado como somente leitura no Codex Desktop, os servidores nativos do Codex
devem ser adicionados à configuração global:

```bash
codex mcp add code-review-graph -- code-review-graph serve --repo "$PWD"
codex mcp add vercel --url https://mcp.vercel.com
codex mcp add hostinger --url https://mcp.hostinger.com
```

Após adicionar:

```bash
codex mcp login vercel
codex mcp login hostinger
codex mcp list
```

O MCP `supabase-local` está inventariado em `.mcp.json` usando transporte HTTP
nativo e também registrado globalmente no Codex. Ele funciona quando a stack
local estiver ativa. Não registre
`supabase-dev` globalmente enquanto o ref histórico estiver sem acesso.
O Codex CLI atual não oferece `enable/disable`; por isso PROD não deve ficar
registrado globalmente. Em diagnóstico explícito, registre a URL somente leitura
mostrada em `.mcp.json`, autentique, execute a análise e remova o servidor ao
terminar.

O Brevo exige um **token MCP**, criado separadamente em Account > SMTP & API >
API Keys com a opção MCP. Não reutilize a `BREVO_API_KEY` usada pelo backend.
Exporte `BREVO_MCP_TOKEN` no processo que inicia o Codex; nunca grave o valor em
`config.toml`, `.mcp.json` ou no repositório. Somente depois disso, registre:

```bash
codex mcp add brevo --url https://mcp.brevo.com/v1/brevo/mcp \
  --bearer-token-env-var BREVO_MCP_TOKEN
```

## 4. Devin CLI e Devin AI

O inventário do Devin CLI habilita Vercel, Hostinger, `code-review-graph` e
`supabase-local`; mantém `supabase-dev` e `supabase-prod-readonly` desligados.
O Devin AI em nuvem continua usando configuração organizacional separada.

No CLI:

```bash
devin mcp list
devin mcp login vercel
devin mcp login hostinger
devin mcp enable -s project supabase-dev
devin mcp login supabase-dev
```

Não habilite o último bloco até o projeto DEV estar acessível. Para uma análise
excepcional de produção:

```bash
devin mcp enable -s project supabase-prod-readonly
devin mcp login supabase-prod-readonly
# ao terminar
devin mcp disable -s project supabase-prod-readonly
```

No Devin AI em nuvem, a configuração é organizacional e não vem do arquivo
local. Em **Settings > MCP Marketplace**:

1. habilite Vercel pelo marketplace e autentique uma conta de serviço;
2. adicione Hostinger como HTTP/OAuth em `https://mcp.hostinger.com`;
3. adicione Supabase DEV como HTTP/OAuth com `project_ref` e grupos mínimos;
4. para Brevo, crie um secret `BREVO_MCP_TOKEN` e um MCP HTTP com o header
   `Authorization: Bearer $BREVO_MCP_TOKEN`;
5. não compartilhe conexão pessoal em modo Organization; use contas de serviço.

O callback OAuth customizado do Devin é
`https://api.devin.ai/mcp/oauth/callback` quando o provedor exigir cliente OAuth
pré-registrado.

## 5. Supabase DEV e PROD

O MCP oficial recomenda não conectar dados de produção a LLMs. Quando uma
exceção de diagnóstico for necessária, use simultaneamente:

- `project_ref=pffafnchtxbimpwyaczq`;
- `read_only=true`;
- `features=database,debugging,docs`;
- aprovação manual de toda ferramenta;
- nenhuma consulta a linhas de fiéis se metadados/advisors bastarem.

O ref DEV histórico `cxmjojnocigekgcxhubi` não aparece entre os projetos da
conta Supabase atualmente conectada e retorna falta de permissão. As opções são:

1. autenticar a conta/organização que ainda possui esse projeto;
2. recuperar o projeto, caso pausado/transferido;
3. criar um novo `PastorAI-DEV` em `sa-east-1`, depois aplicar migrations e seed
   sintético conforme `deploy/STAGING.md`.

Criar projeto pode ter custo recorrente. Confirme organização, região e custo no
painel antes de qualquer criação.

Uma stack local vazia foi inicializada deliberadamente para disponibilizar o MCP
em `http://127.0.0.1:54321/mcp`. Ela usa a rede Docker
`pastorai-supabase-local`, vinculada ao localhost, e não está ligada a nenhum
projeto hospedado. Operação diária:

```bash
npm run supabase:start
npm run supabase:status
npm run supabase:stop
```

O GET de diagnóstico ao endpoint MCP local retorna `405 Method Not Allowed`, o
que é esperado: o transporte MCP usa outro método HTTP. O `npm run doctor`
aceita esse código como prova de que o endpoint está acessível, mas não aceita
`404` como sucesso.

`supabase/config.toml` fixa apenas o major `17`, porque a imagem local é gerida
pela própria CLI. O job RLS usa separadamente a imagem descartável
`postgres:17.6-trixie@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`;
não substitua a imagem da CLI manualmente.

O repositório continua usando migrations em `backend/migrations/` e um ledger
próprio. A configuração local mantém migrations e seed automáticos desligados.
Não rode `db push`, `db reset --linked` nem migre o histórico para
`supabase/migrations/` como efeito colateral desta configuração.

## 6. Brevo e Asaas no runtime

Brevo e Asaas já existem em:

- `backend/app/services/brevo.py`;
- `backend/app/services/asaas.py`;
- `backend/app/routers/subscription.py`;
- testes dedicados em `backend/tests/`.

Brevo runtime usa `BREVO_API_KEY`; o MCP usa `BREVO_MCP_TOKEN`. O remetente e o
domínio precisam estar verificados no Brevo antes do canário.

Asaas deve começar com:

```ini
ASAAS_API_URL=https://api-sandbox.asaas.com/v3
ALLOW_REAL_SENDS=false
```

O webhook do produto é `POST /subscription/webhook`, publicado como
`https://api.igreja12.com.br/subscription/webhook` em produção. Configure um
`authToken` forte de 32 a 255 caracteres e use o mesmo valor em
`ASAAS_WEBHOOK_TOKEN`. Nunca reutilize a chave da API como token do webhook.

Não foi localizado MCP oficial do Asaas. Como se trata de dinheiro, não instale
um pacote comunitário genérico nem dê acesso de produção a um agente. Se um MCP
Asaas for realmente necessário, ele deve ser um adaptador próprio, inicialmente
somente leitura e restrito ao Sandbox, com allowlist de operações e testes.

## 7. Verificação

```bash
npm run doctor
npm run doctor -- --network
git status --short
```

O doctor nunca imprime tokens. Um ambiente pronto deve mostrar Node 24.19.0,
Python 3.13.14, daemon Docker acessível, CLIs locais instaladas e os MCPs remotos
alcançáveis.

## 8. Evidência da auditoria

Validações executadas em 2026-08-20:

- `docker compose config --quiet` passou usando `deploy/.env.example`;
- Docker Engine 29.7.2 respondeu pelo grupo `docker`; a stack Supabase local
  subiu saudável e todas as portas publicadas ficaram vinculadas a `127.0.0.1`;
- `npm audit` da raiz e do frontend: 0 vulnerabilidades;
- frontend: lint e typecheck limpos, 732 testes aprovados e build de produção
  concluído;
- backend: 2.371 testes aprovados e 166 ignorados na suite completa;
- gate RLS reproduzido contra PostgreSQL 17 descartável: 135 testes aprovados,
  7 desmarcados, mais 9 testes de rota offline;
- ambiente Python criado com `uv venv --seed`, lock instalado com hashes,
  `pip check` limpo e manifesto validado (15 dependências diretas e 9 extras
  ativados);
- MCPs responderam sem token como esperado: Supabase local/Hostinger `405`, e
  Vercel/Supabase hospedado/Brevo `401`, confirmando DNS, TLS e alcance de rede;
- inventários do Codex e Devin CLI conferidos; no Devin, Supabase genérico, DEV
  e PROD permanecem configurados porém desabilitados por padrão.

O backend emitiu warnings de depreciação do Starlette: `TestClient` com `httpx`
deve migrar futuramente para `httpx2`, e a constante HTTP 422 antiga deve ser
substituída. Não são falhas atuais, mas entram na próxima atualização planejada
de dependências.

Nenhuma linha do Supabase PROD foi lida nesta validação. O MCP de produção
permanece desligado até que um diagnóstico específico justifique habilitá-lo.

Gates externos restantes:

1. criação do token MCP específico da Brevo;
2. recuperar o projeto Supabase DEV ou autorizar um novo projeto/custo;
3. configurar os mesmos MCPs no Devin AI em nuvem, que usa configuração
   organizacional separada do Devin CLI local.
