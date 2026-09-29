# Ambiente local e fim do DEV na nuvem — 2026-09-27

**Branch:** `claude/dev-prod-separation-21c3e8`  ·  **Deploy:** não (só a máquina local)

## Por quê

Só a produção funcionava de ponta a ponta. O DEV na nuvem tinha 44 migrations
pendentes, sem backend nem WhatsApp próprios, então todo teste real acontecia em
PROD e cada mudança era feita duas vezes. O proprietário aprovou o modelo
"desenvolver no computador, PROD só por release" (plano §3.5) e mandou encerrar
a frente do DEV na nuvem.

## O que foi feito

- **`./dev.sh`** (`up`, `reset`, `seed`, `migrate`, `down`, `status`, `logs`,
  `psql`). Sobe o Supabase local; backend e os três workers em Docker
  (`deploy/docker-compose.dev.yml`, projeto `pastorai-dev`, rede do host, só
  `127.0.0.1`), com o código montado, API com `--reload` e workers com
  `watchfiles`; e o frontend com `next dev` na porta 3012. O `.env.dev` fica na
  raiz do checkout principal (modelo em `deploy/.env.dev.example`). Os segredos
  locais são gerados na 1ª execução, e o arquivo é protegido pelo `info/exclude`
  do Git e recusado se tiver chave ou endereço de produção.
- **`backend/scripts/dev_local.py`**, que recusa qualquer banco que não seja o
  Supabase local:
  - `migrate` cria o ledger e aplica as migrations não pausadas;
  - `seed` cria duas igrejas fictícias com ids estáveis. Reaproveita o código
    do app (`ensure_active_membro`, `_build_report_out`, `canonical_public_info`,
    `compute_progresso`, `_seed_role_permissions`, `_seed_agent_from_template`)
    e liga as contas do Clerk de desenvolvimento por e-mail
    (`DEV_SEED_EMAIL_*`).
- Migrations d2a, d2b2 e d2b2b3 marcadas como pausadas, conforme o §3.3 do
  plano. Saem do `status`. Em PROD continuam pendentes só as duas `20260711` de
  dados, d1a, `183811` e `120446`.
- **Frente do DEV na nuvem encerrada:**
  - a sessão "Recriar o DEV a partir do schema de PROD" foi interrompida. Ela já
    tinha recriado o DEV como espelho de PROD ([PR #431](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/431),
    aberta; destino a decidir);
  - a sessão do Maestri parou o roteiro "arrumar o DEV" no Bloco 1, que só
    copiou arquivos locais, sem URL nem conexão.
- **Limpeza** (tudo preservado em `archive/governanca-2026-09`):
  `deploy/STAGING.md`, `docs/ops/DEV-SMOKE-USERS.md`, os dois
  `.env.staging.example`, `docs/ops/dev-migration-history-remediation/`
  (61 arquivos) e `docs/ops/migration-head77-dev-apply-readiness/` (12).
- **Docs:**
  - novo [`AMBIENTE-LOCAL.md`](../ops/AMBIENTE-LOCAL.md);
  - plano do MVP: §3.4, nova §3.5, item da Fase 0, Fase 4, B10 e decisão 7;
  - runbook de produção, README de migrations, `CLAUDE.md`, `AGENTS.md` e
    `AI-MCP-SETUP.md`;
  - `tooling-static` passa a validar o `dev.sh` e o compose de dev.

## Decisões

- **Supabase local, não Postgres puro:** a RLS depende das roles do Supabase.
  Além disso, o `migrate` repõe os privilégios padrão antigos do Supabase antes
  da 1ª migration. O PROD nasceu com eles, e o runbook registra que tabela nova
  recebe `arwdDxtm` para `anon`/`authenticated`. O Supabase local (CLI 2.115)
  não os concede, e sem isso toda rota autenticada dava 500 (`permission
  denied for table app_users`).
- **Rede do host para backend e workers:** as URLs de mídia e de logo são
  montadas a partir de `SUPABASE_URL` e precisam abrir no navegador. O WhatsApp
  local (próximos itens) alcança o webhook sem túnel.
- **Só dados fictícios:** telefones com DDD 00, que não existe, e e-mails
  `.test`. Nada de PROD no local (LGPD).
- **`ALLOW_REAL_SENDS=false` no local até o simulador:** a trava também libera o
  LLM, então só abre quando o WhatsApp local for o simulador ou o chip de
  teste.

## Pendente / próximo passo

- **Proprietário:**
  - preencher no `.env.dev` as chaves do Clerk de desenvolvimento e os
    `DEV_SEED_EMAIL_*`, rodar `./dev.sh seed` e testar o login;
  - decidir o destino da PR #431 e do projeto DEV na nuvem (pausar ou apagar no
    painel do Supabase);
  - aplicar a correção do perfil AppArmor do sandbox (ver abaixo).
- **Itens 2 a 4 da §3.5:** simulador de WhatsApp, chip de teste e release (a
  Vercel publicando só a branch `producao` e o script de deploy).
- **PRs retidas:**
  - #426 e #428 têm frontend e só entram na `main` depois do item 4. Até lá, o
    merge publica o frontend em PROD na hora (B13);
  - #430 é só backend e pode entrar após o teste local.
- **Sandbox do Claude Code nesta máquina:** o perfil AppArmor
  `bwrap-userns-restrict-patched` (do `zorin-os-default-settings`) nega
  capabilities aos processos dentro do bwrap (`unpriv_bwrap`), e o passo de
  seccomp do sandbox falha. O Zorin já deixa
  `kernel.apparmor_restrict_unprivileged_userns=0`, então desativar esse
  perfil resolve sem abrir nada além do padrão do sistema. É mudança de
  segurança do sistema: fica com o proprietário.

## Verificação

- Prova de viabilidade: 78 migrations do zero em 5 s num Supabase Postgres
  17.6.1.159 descartável. Com as 3 pausadas, 75 em 1,2 s no Supabase local.
- `./dev.sh reset`: cerca de 1 min, com seed de 26 pessoas, 3 células,
  12 reuniões, 3 consolidações e 4 conversas, e 3 pessoas na igreja vizinha.
  `./dev.sh up`: cerca de 25 s.
- API local, com token de teste gerado pelo segredo local e ids de Clerk
  temporários, desfeitos depois: 28/28 rotas autenticadas com 200 como pastor,
  líder, membro e admin da igreja vizinha. A igreja vizinha vê só as suas 3
  pessoas e nenhuma célula, conversa ou item de fila da outra.
- O cron worker criou sozinho um escalonamento de SLA para a consolidação
  atrasada, 4 s depois do seed, sem WhatsApp.
- Navegador: Painel de Hoje, Conversas e Consolidar mostram os dados do seed.
- Backend: `pytest -m "not rls_integration"` com Python 3.13 terminou com
  código 0 (5473 testes). `tests/test_dev_local_script.py` e
  `tests/test_migrate_script.py`: 24 passed. `bash -n dev.sh` e o `compose
  config` do arquivo de dev passaram.
