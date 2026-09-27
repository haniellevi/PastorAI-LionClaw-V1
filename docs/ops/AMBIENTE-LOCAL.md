# Ambiente local de desenvolvimento

Desde 27/09/2026 o PastorAI é desenvolvido e testado **no seu computador**, com
dados fictícios. A produção só muda por release, quando você decide subir. O DEV
na nuvem (`Igreja12-dev`) está parado e não recebe mais migrations nem testes.

Um comando sobe o sistema inteiro:

```bash
./dev.sh up
```

## O que roda e onde

Tudo escuta só em `127.0.0.1`.

| Peça | Endereço | Observação |
|---|---|---|
| Painel (uso diário) | http://localhost:3012 | `npm run dev`, recarrega a cada mudança |
| Admin da igreja | http://localhost:3012/gestao | |
| Console da plataforma | http://localhost:3012/admin | |
| API | http://localhost:8000 (`/docs`) | recarrega sozinha quando um `.py` muda |
| Workers | `queue-worker`, `cron-worker`, `broadcast-worker` | reiniciam sozinhos quando um `.py` muda |
| Banco | Supabase local, Studio em http://127.0.0.1:54323 | Postgres 17.6, o mesmo do PROD |
| Redis | porta 6380 | |

Backend e workers rodam em Docker (`deploy/docker-compose.dev.yml`, projeto
`pastorai-dev`) com o código do checkout atual montado. Só um worktree por vez
roda a stack: `./dev.sh up` em outro worktree passa a usar o código de lá.

## Primeira vez

Precisa de Docker, Node 24 (`nvm install`) e da CLI do Supabase, que vem com o
`npm ci` na raiz do checkout principal.

1. Rode `./dev.sh up`. Ele cria o `.env.dev` na raiz do checkout principal (vale
   para todos os worktrees e é ignorado pelo Git), gera os segredos locais, sobe
   o Supabase local, cria o banco com os dados de teste e sobe o resto.
2. Para o login funcionar, preencha no `.env.dev`:
   - `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` e `CLERK_JWT_ISSUER` da
     instância de **desenvolvimento** do Clerk (`pk_test_`/`sk_test_`);
   - `DEV_SEED_EMAIL_*`: os e-mails das contas de teste que já existem nesse
     Clerk, as mesmas do `usuario-dev.md`. A senha nunca vai para o `.env.dev`.
3. Rode `./dev.sh seed` para ligar as contas e `./dev.sh down && ./dev.sh up`
   para o backend e o frontend lerem as chaves.

O `dev.sh` recusa um `.env.dev` com chave ou endereço de produção
(`sk_live_`, `pk_live_`, o projeto de PROD ou qualquer Supabase hospedado).

## Comandos

| Comando | O que faz |
|---|---|
| `./dev.sh up` | sobe tudo e aplica as migrations pendentes |
| `./dev.sh reset` | apaga o banco local e recria: migrations do zero e dados de teste (~1 min) |
| `./dev.sh seed` | recria os dados que faltarem e religa as contas do Clerk |
| `./dev.sh migrate` | aplica só as migrations pendentes |
| `./dev.sh status` | mostra o que está rodando e os endereços |
| `./dev.sh logs [serviço]` | acompanha os logs (`backend`, `queue-worker`, `cron-worker`, `broadcast-worker`, `redis`, `frontend`) |
| `./dev.sh psql` | abre o psql no banco local |
| `./dev.sh down [--tudo]` | para backend, workers e frontend; `--tudo` para também o Supabase local |

Migration nova: crie o arquivo e rode `./dev.sh migrate`. Se precisar mudá-la
depois, edite e rode `./dev.sh reset`: no local o banco é descartável. Ao trocar
para uma branch que não tem uma migration já aplicada, rode `./dev.sh reset`.

## Dados de teste

O seed (`backend/scripts/dev_local.py`) cria:

- **Igreja Local (teste):** 26 pessoas em todas as etapas do G12; 3 células com
  líder, anfitrião, auxiliar e membros; 3 reuniões passadas por célula, com
  presença e relatório enviado, e a próxima planejada; o último relatório da
  Célula Jovens em Cristo fica pendente. Também cria 3 consolidações, uma delas
  atrasada, a fila pastoral, a agenda, o perfil público do agente e 4 conversas
  de WhatsApp: uma aguardando atendimento humano, uma assumida pelo pastor, uma
  com o termo aceito e um opt-out.
- **Igreja Vizinha (teste):** outra igreja, para conferir que uma não vê os
  dados da outra.

Os telefones usam o DDD 00, que não existe, e os e-mails o domínio `.test`. Nada
vem de produção: **nunca copie dados reais para o local** (LGPD).

Logins que o seed liga ao Clerk, pela variável `DEV_SEED_EMAIL_*`
correspondente:

| Variável | Pessoa no seed | Papéis |
|---|---|---|
| `PASTOR` | Pr. André Luiz | admin, pastor (dono da igreja) |
| `ADMIN` | Secretaria da Igreja | admin |
| `LIDER` | Marcos Oliveira, Célula Esperança | líder de célula, líder G12 |
| `CONSOLIDACAO` | Patrícia Lima | líder de consolidação |
| `MEMBRO` | Ana Beatriz Rocha | membro |
| `PLATAFORMA` | Equipe PastorAI | console da plataforma |

Se o e-mail de `PLATAFORMA` for o mesmo de outro papel, essa conta também ganha
o console.

## WhatsApp no local

Por enquanto o WhatsApp local aparece "offline" e `ALLOW_REAL_SENDS=false`.
Os próximos passos do plano são um simulador de WhatsApp no navegador e o guia
do chip de teste com a Evolution local.

**Nunca conecte o número da Filadélfia no ambiente local.** O WhatsApp aceita
vários aparelhos no mesmo número, e aí os dois bots responderiam.

## Problemas comuns

- **Toda rota autenticada dá 500 com `permission denied`:** o banco foi criado
  sem os privilégios padrão antigos do Supabase, que o PROD tem. Rode
  `./dev.sh reset`, que os repõe antes da 1ª migration.
- **Login devolve 401:** a conta não está ligada. Confira se o e-mail existe no
  Clerk de desenvolvimento, preencha `DEV_SEED_EMAIL_*` e rode `./dev.sh seed`.
- **Porta ocupada:** troque `DEV_FRONTEND_PORT`, `DEV_BACKEND_PORT` ou
  `DEV_REDIS_PORT` no `.env.dev`. Se mudar a porta do frontend, ajuste também
  `FRONTEND_URL` e `CALENDAR_OAUTH_RETURN_ORIGINS`.
- **O frontend não abre:** `./dev.sh logs frontend`.
- **Supabase CLI ausente:** `npm ci` na raiz do checkout principal.
