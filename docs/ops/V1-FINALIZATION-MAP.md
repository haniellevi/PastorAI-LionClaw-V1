# PastorAI / Igreja 12 — mapa central de finalização da V1

Atualizado e revalidado em 2026-08-22 (America/Sao_Paulo).
**V1_ENCERRADA.**

Este é o mapa histórico do fechamento da V1 e a base de transição para o
pós-V1. Ele centraliza a ordem de trabalho, os gates, o paralelismo permitido
e as decisões de escopo. Dados de
GitHub, CI, ambiente e produção são temporais: antes de agir, faça preflight
vivo. Relatórios antigos continuam úteis como evidência, mas não definem a
prioridade atual nem autorizam ações.

## 1. Decisão de V1 e critério de conclusão

A V1 será entregue como **piloto controlado implantado**, mantendo o Clerk DEV
atual. Não é um lançamento público amplo.

Para declarar V1_ENCERRADA, todos os itens abaixo precisam ter evidência no SHA
efetivamente implantado:

1. M08 está operacional em produção, inclusive GET /ready; a issue #259 foi
   encerrada após duas verificações saudáveis documentadas.
2. M00 torna Linux, Docker, MCPs, Node, Supabase local e CI reproduzíveis.
3. M09, M01, M06 e Brevo estão revisadas, integradas em série, verdes e sem
   findings P0--P2 abertos.
4. O release candidate passa em PostgreSQL 17 local, Supabase DEV e produção,
   com migrations verificadas individualmente.
5. Backend e frontend de produção apontam para o mesmo SHA, com backup,
   rollback, monitoramento e canários registrados.
6. O mapa, runbooks e evidências de encerramento foram atualizados; a tag
   v1.0.0 foi criada somente depois dos gates anteriores.

Itens explicitamente **pós-V1**:

- PR #257 e o trabalho de transferência/remoção de membros de Células;
- migração de Clerk DEV para Clerk Production;
- cobrança real Asaas em produção;
- ativação do broadcast assíncrono e dos envios reais via Evolution;
- promoção do Brevo de `off`/canário para `live`.

O piloto Clerk DEV deve permanecer limitado e controlado. Antes de uma abertura
pública, a migração para Clerk Production será uma missão própria; não há
transferência automática das identidades DEV existentes.

## 2. Snapshot vivo de partida

| Item | Estado verificado | Consequência operacional |
|---|---|---|
| Código V1 / tag `v1.0.0` | 281e69c2fef80cfbcb27eab5ca4f85981e4adc0c | Código congelado, cinco workflows verdes e backend/frontend implantados no mesmo SHA. Commits documentais posteriores em `main` não alteram o artefato da V1. |
| Documentação de fechamento | PR #274 em ea40cda3... e PR #275 em ba9dba77... | Evidência, tag/release e declaração `V1_ENCERRADA` estão versionadas em `main`. |
| PR #260 / M08 | MERGED em fd1cf373... | O corretivo de concorrência de claims recuperados está integrado; não reabrir esse código por um estado histórico. |
| PR #261 / monitor M08 | MERGED em 5d7059df... | O workflow de monitor agora falha fechado quando produção não está saudável. |
| PR #262 / readiness Supabase | MERGED em f2c3132... e implantada | Readiness tolera conexão saudável lenta via Supavisor sem relaxar Redis/Evolution. |
| Issue #259 | CLOSED em 2026-08-20 | Incidente resolvido após health/ready locais e públicos, backup verificado e duas execuções saudáveis do monitor. |
| PR #258 | MERGED em 1b9acb42... | Este mapa é o guia operacional canônico; seus estados são atualizados por preflight vivo. |
| M00 / PR #263 | MERGED em 5a0f12f... | Tooling Linux/Docker/MCPs, Node 24, Python 3.13, PostgreSQL 17 e CI base foram validados e integrados. |
| PR #245 / M09 | MERGED em 25d3876... | Baseline E2E/performance foi atualizado para a main vigente, revalidado e integrado. |
| PR #234 / M01 | MERGED em cc89c0c... | Cortesia administrada pelo master, billing durável e migration PG17 foram revalidados e integrados. |
| PR #244 / M06 | MERGED em a292b5e... | Hardening de frontend, RLS/policies e executor de migrations foi revalidado e integrado. |
| PR #257 | OPEN/não draft, 87 commits atrás e 1 à frente no preflight | Missão pós-V1; atualizar contra `main`, revisar e revalidar antes de qualquer integração. |
| Brevo | PR #237 integrou a base de e-mail em 9987bf10...; PR #266 foi MERGED em 8427ece... | O SHA histórico 6dd42a... não existe no repositório; gate dedicado, revisão P1 e cinco checks foram concluídos. |
| Células | Referência histórica 05c0aad... não encontrada no clone nem no GitHub | Recuperação pós-V1 ainda não comprovada; não tratar esse SHA como artefato preservado. |
| Clerk | DEV em produção, seis vínculos reconciliados | Piloto alinhado à decisão aprovada; configuração LIVE e vínculos anteriores preservados para rollback. |
| Supabase PROD | M06/M01 verificadas e ledger reconciliado | Recibos metadata-only registrados no ledger oficial, sem reaplicar DDL. |
| Frontend PROD | `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp` | Três aliases no RC, headers M06 presentes e zero erro de runtime na janela verificada. |
| Estado de release | V1_ENCERRADA | Tag `v1.0.0` publicada no SHA de código `281e69c2...`, GitHub Release criado, evidência integrada em `ea40cda3...` (PR #274) e housekeeping concluído. |

O número de checks verdes, review threads e distância de cada branch em relação
à main não é reproduzido aqui como fato permanente. Deve ser consultado no
preflight de cada gate. O token atual pode não listar detalhes de checks; nesse
caso, use GitHub Actions/CLI autorizado e registre a limitação, sem assumir
sucesso a partir de um snapshot antigo.

## 3. Fontes de verdade e regras invariáveis

Ordem de precedência quando houver divergência:

1. GitHub e origin/main consultados no momento da ação;
2. árvore Git e diff do worktree proprietário;
3. testes reproduzidos no SHA exato;
4. runbooks e documentação versionada;
5. este mapa na versão já integrada à main;
6. relatórios históricos, conversas e grafos.

Regras que valem para todas as sessões:

- usar worktree isolado e limpo; nunca desenvolver na raiz suja;
- não resetar, limpar, restaurar ou sobrescrever alterações desconhecidas;
- não abrir, imprimir ou versionar .env, tokens, JWTs, DSNs ou dados de
  usuários;
- revisão, correção, commit, push, PR, Ready, merge, migration, deploy, flag
  e canário são gates independentes;
- nenhuma ação externa em Supabase, Hostinger/VPS, Vercel, Brevo, Asaas,
  Evolution, Google ou produção ocorre sem alvo definido e autorização
  explícita;
- toda prova concorrente de banco usa PostgreSQL real e descartável;
- grafos só são evidência quando raiz, SHA, integridade e frescor forem
  comprovados;
- a sessão Central é a única que altera este mapa e consolida SHAs/evidências.

## 4. Sessões, worktrees e paralelismo

| Sessão | Escopo | Pode ocorrer em paralelo com | Regra de integração |
|---|---|---|---|
| Central-Map | mapa, sequência, preflights e evidência | todas as sessões read-only | só esta sessão edita o mapa; não integra código |
| M08-OPS | M08, monitor e recuperação operacional | — | concluída em f2c3132...; preservar evidência, sem abrir novo código nesta trilha |
| M00-Tooling | Linux, Docker, MCPs, Node, Supabase local e CI base | Acessos | concluída na PR #263 / 5a0f12f... |
| Acessos | Supabase DEV, Vercel, Hostinger, Brevo e recuperação de artefatos | todas as fases de código | read-only até haver autorização específica |
| M09 | PR #245, E2E e performance | auditoria read-only de M01/M06 e recuperação Brevo | concluída na PR #245 / 25d3876... |
| M01 | PR #234, planos cortesia e billing | auditoria read-only de M06/Brevo | concluída na PR #234 / cc89c0c... |
| M06 | PR #244, RLS, executor e hardening | recuperação Brevo | concluída na PR #244 / a292b5e... |
| Brevo | gate de e-mail transacional | preparação de RC/acessos read-only | concluída na PR #266 / 8427ece... |
| RC/Release | candidate, DEV, produção e encerramento | nenhuma escrita de missão | estritamente serial |
| Revisão | revisão independente no SHA final de cada missão | implementação de outras worktrees sem sobreposição | read-only; não reutiliza o worktree do implementador |

Paralelismo permitido não equivale a merge paralelo. A ordem de integração é
impositiva:

~~~text
M00 e preparação de acessos read-only
                    |
                    v
        M09  ->  M01  ->  M06  ->  Brevo
                    |
                    v
         RC local  ->  Supabase DEV  ->  Produção
~~~

PR #257 e Células não entram nessa cadeia. A branch da PR #257 deve ser
preservada para o backlog pós-V1. A implementação histórica de Células precisa
ser localizada e validada novamente, pois o SHA citado antes não existe nas
fontes Git disponíveis; não há artefato comprovado para integrar.

## 5. Sequência de execução aprovada

### Fase A — M08 operacional e issue #259 — CONCLUÍDA

M08 foi encerrada em 2026-08-20 sem migrations nem alteração de flags:

1. PR #260 corrigiu a reentrada de advisory lock de claims recuperados e foi
   integrada em `fd1cf37337ff904e86b9d5880d9cc6e30760947a`.
2. PR #261 tornou o workflow de monitor fail-closed e foi integrada em
   `5d7059dfc178f5605d0e12fe3cf58fb2d9a005aa`.
3. PR #262 corrigiu o timeout de readiness para conexões Supabase/Supavisor
   saudáveis e lentas, integrada e implantada em
   `f2c3132b2a1d5060c4ba236374f0475416973be2`.
4. O release ativo respondeu `/health` e `/ready` local e publicamente; banco,
   Redis e workers ficaram saudáveis, e as portas internas 8000/8080 seguiram
   sem exposição externa.
5. O backup fresco teve checksum e manifesto verificados; o monitor foi
   instalado preservando o cron legado, executou duas verificações saudáveis e
   a issue #259 foi encerrada.

O acesso SSH temporário criado apenas para esse deploy foi mantido durante os
gates seguintes e revogado no fechamento final. A chave foi retirada da VPS e
do Hostinger, o material local foi removido e uma nova tentativa de conexão foi
negada, conforme a evidência da PR #275.

### Fase B — M00: tooling, Docker, MCPs e runtime — CONCLUÍDA

A PR #263 foi integrada em `5a0f12f5062bfd45d780dacf29090c8f34a66da8` após
validação local e quatro checks verdes. Ela versiona Node 24.19.0, Python
3.13.14, Supabase CLI 2.115.0, o doctor, Docker Engine + Compose, PostgreSQL
17 descartável para RLS, Supabase local em loopback e o inventário MCP sem
segredos. Docker Desktop segue dispensável no Linux.

O template seguro `deploy/.env.example` permite validar Compose sem abrir ou
criar `.env` real. O Supabase local, Vercel, Hostinger e Brevo foram testados
por reachability sem credenciais; no Devin, os MCPs genérico/DEV/PROD do
Supabase permanecem preservados, porém desabilitados por padrão. Os arquivos
não rastreados do checkout principal não foram removidos e ficam para o
fechamento final do projeto.

### Fase C — mapa e acessos

Este mapa foi integrado pela PR #258 em `1b9acb42...` e é o guia operacional
canônico de encerramento da V1. Atualizações de estado só entram depois do
preflight, CI e merge da missão correspondente.

Em paralelo e sem mutação externa:

- recuperar o Supabase DEV histórico; se ele não existir, parar e pedir
  autorização para projeto, organização, região e custo antes de criar outro;
- limitar todo diagnóstico de Supabase PROD ao projeto
  pffafnchtxbimpwyaczq, preferencialmente por metadados/advisors read-only e
  sem consultar linhas de usuários;
- obter acesso ao projeto Vercel pastorai-frontend no time correto;
- obter SSH/terminal do Hostinger, pois o conector disponível não administra a
  VPS;
- preparar token MCP Brevo separado da chave de runtime e confirmar
  domínio/remetente;
- tratar a PR #237 (`9987bf10e06d5015c832a58b45f55e366a1f307a`) como a base
  já integrada de e-mail transacional. O SHA de recuperação `6dd42a...` não
  existe localmente nem no GitHub e não deve ser usado como evidência;
- não usar a referência histórica de Células `05c0aad...` como prova: ela não
  está no clone nem no GitHub e precisa ser recuperada da origem que ainda
  possua o objeto ou reconstruída em missão pós-V1.

### Fase D — M09 / PR #245 — CONCLUÍDA

A PR #245 foi atualizada contra M00, revalidada e integrada em
`25d3876771bb8ffb0b160d79d6b548f31510186e`. O workflow E2E agora usa Node
24.19.0, Ubuntu 24.04 e Actions fixadas por SHA. Os cinco fluxos rodam em
Chromium contra API mock estritamente loopback; cada tentativa preserva
snapshot sanitizado mesmo após falha de asserção.

A revalidação local no SHA `e7e20837e7aba333d91b3b3d07bd59319644f655` passou
audit, lint, typecheck, 783 testes Vitest, build e cinco E2E, sem requests
externos ou pendentes. Backend, frontend, RLS, tooling e E2E ficaram verdes no
GitHub, sem comentários. A Fase B de performance autenticada continua sendo
prova do SHA efetivamente implantado, não uma razão para antecipar deploy.

### Fase E — M01 / PR #234 — CONCLUÍDA

A PR #234 foi atualizada contra a main, revalidada e integrada em
`cc89c0c1b9966219f921f80c9ee28e03ba152537`. O aceite agora cobre plano de
preço zero como cortesia administrada pelo master, ausência da cortesia no
catálogo do tenant, bloqueio de checkout/troca antes de qualquer chamada Asaas,
concorrência/reconciliação fail-closed e a migration
`20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql`.

No SHA da PR, a validação local passou backend completo (2.458 passed, 175
skipped), 175 testes RLS em PostgreSQL 17 descartável, seis cenários da
migration real, lint, typecheck, 784 testes Vitest, build, cinco E2E locais e
`npm audit --omit=dev --audit-level=high` sem vulnerabilidades. Os cinco gates
do GitHub passaram sem comentários. Nenhuma credencial ou chamada Asaas real
foi usada nessa missão.

`ASAAS_BILLING_ENABLED=false` continua o padrão. Não há teste ou cobrança Asaas
em produção nesta V1.

### Fase F — M06 / PR #244 — CONCLUÍDA

A PR #244 foi atualizada contra M01 e integrada em
`a292b5ee250e24c8e5d76abc6199b32265604429`. O aceite cobriu CSP
frame-ancestors, Referrer-Policy, Permissions-Policy, policies deny, ACL/RLS,
ausência de caminhos `SET ROLE` e executor de migrations fail-closed por
arquivo, nome e SHA.

A validação local passou os 58 cenários focados do executor/RLS, 233 testes
RLS em PostgreSQL 17 descartável, backend completo (2.497 passed, 233 skipped),
lint, typecheck, 786 testes Vitest, build, smoke de headers, cinco E2E e audit
npm sem high vulnerabilities. Os cinco checks da PR passaram. Depois de o
endpoint do GitHub manter um merge pendente, o mesmo HEAD revisado foi integrado
por avanço rápido verificado, sem `--force`; o GitHub reconheceu a PR como
merged em 2026-08-20.

### Fase G — Brevo / PR #266 — CONCLUÍDA

A base de e-mails transacionais já veio da PR #237, cujo commit
`9987bf10e06d5015c832a58b45f55e366a1f307a` é ancestral de main. O SHA histórico
`6dd42a8356ecd94908d794d7eac4e8f237fd2325` não existe localmente nem no GitHub;
portanto, não há artefato a recuperar nem fixture herdada a concluir.

A PR #266 foi integrada em `8427ece74d9620b85177c347a0e4db707551f48c`. Seu
HEAD revisado foi `5f1c403b11664233358fbefdd03200cab08e0a99`. A suíte completa
do backend e os testes focados de Brevo, outbound guard, configuração e runbook
passaram localmente; os cinco checks do GitHub passaram no HEAD final.

Uma revisão P1 identificou que o loop pós-restart ainda não validava o gate
independente. A correção exige `BREVO_SEND_MODE=off` em backend, queue-worker e
cron-worker antes dos health/smokes, e o teste do runbook prova que ausência,
vazio, `canary`, `live` ou `OFF` falham fechado. A thread foi respondida e
resolvida antes do merge.

Depois de M06, o gate Brevo mantém o contrato mínimo:

- BREVO_SEND_MODE=off|canary|live, padrão off;
- BREVO_CANARY_RECIPIENTS vazio bloqueia todos os envios no modo canary;
- o gate Brevo é independente de ALLOW_REAL_SENDS, para não liberar outros
  provedores no canário de e-mail;
- erro de configuração ou upstream falha fechado e nunca simula sucesso.

O aceite cobriu convite, recuperação de senha, configuração ausente,
destinatário fora da allowlist, falha HTTP e ausência de rede nos modos
bloqueados. O próximo gate serial é o release candidate local.

### Fase H — release candidate, DEV e produção — OPERACIONALMENTE CONCLUÍDA

O RC foi congelado em `281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`. A
validação local passou backend completo, frontend completo, cinco E2E, RLS em
PostgreSQL 17, Docker/Compose e auditorias. O CRG foi comprovado nesse SHA;
Graphify ficou `NAO_COMPROVADO` e não foi usado como evidência.

No Supabase PROD `pffafnchtxbimpwyaczq`, o DDL de M06 e M01 já estava presente
e correspondia aos arquivos do RC. Os hashes foram reconfirmados e o ledger
oficial recebeu somente recibos metadata-only nas versões `20260810031050` e
`20260810042300`; o DDL não foi reaplicado. A pós-condição manteve 53/53 tabelas
com RLS, quatro policies fechadas exatas, ACLs negadas e função de autoupgrade
endurecida.

O backup `pastorai-backup-20260821T213637Z.tar.gz`, SHA-256
`940e14a331838cd1499c47d7bc2adea3bd897cc2f292e6e3f326f67612459c0e`, foi
restaurado em PostgreSQL 17 e PostgreSQL 16 descartáveis. Storage e volumes
foram verificados estruturalmente, e uma cópia cifrada externa à VPS teve
checksum e leitura comprovados.

Produção ficou alinhada no RC:

- backend: `/opt/pastorai-releases/281e69c2fef80cfbcb27eab5ca4f85981e4adc0c`;
- frontend: `dpl_CdwTcTE8HZHvxs9t92Ak6sHxebAp`;
- aliases: `app.`, `admin.` e `painel.igreja12.com.br`;
- Clerk DEV: seis vínculos auditados reconciliados em uma transação, sem criar,
  excluir ou alterar identidades no Clerk;
- smokes read-only: administrador, pastor, líder, membro e master aprovados;
- Brevo: exatamente um canário recebido, seguido de retorno para `off` e
  allowlist vazia;
- rollback: backend `f2c3132...` e frontend `dpl_3Xs...` aprovados;
- roll-forward: RC restaurado, health/readiness/login/headers/flags aprovados;
- estabilidade: duas execuções locais saudáveis e workflows GitHub
  `32543076877` e `32543098661` verdes após o roll-forward.

A evidência completa está em `docs/releases/v1/v1-closure-evidence.md`. A tag
anotada `v1.0.0` foi publicada no SHA de código `281e69c2...`, referenciando o
SHA documental `ea40cda3...` (PR #274, squash merge). O GitHub Release foi
criado em
https://github.com/haniellevi/PastorAI-LionClaw-V1/releases/tag/v1.0.0. O
estado é `V1_ENCERRADA`. Migrations são forward-only e continuam exigindo
forward-fix ou restauração aprovada em incidente.

Revalidação independente em 2026-08-22 confirmou: Release/tag remotos no SHA
de código; monitor agendado `32544604262` verde; `/health` e `/ready` públicos
saudáveis; deployment Vercel ainda `READY` no SHA de código, três aliases HTTP
200, headers M06 presentes e zero erro de runtime agregado em 24h; Supabase
PROD `ACTIVE_HEALTHY` em PostgreSQL 17, 53/53 tabelas públicas com RLS, M06/M01
íntegras e ledger reconciliado. Como o SSH temporário já foi revogado, symlink,
flags, contadores de reinício e manifesto de backup não foram relidos nessa
revalidação; permanecem cobertos pela evidência de fechamento.

## 6. Gates de migrations, deploy e integrações externas

Nenhuma migration, deploy ou canário pode ser inferido da conclusão de uma PR.
Antes de cada escrita, registrar:

- alvo, ambiente, SHA de código, migration/artefato e autorização nominal;
- backup fresco, checksum, restauração comprovada e rollback de código;
- ledger reconciliado e hash do SQL lido no SHA candidato;
- resultado pós-ação, logs sanitizados e próximo gate único.

Ordem obrigatória de dados: PostgreSQL descartável → Supabase DEV → Supabase
PROD. O único ref de produção autorizado para preflight é
pffafnchtxbimpwyaczq; qualquer outro projeto exige confirmação explícita.

Para o piloto, manter:

- Clerk DEV, com acesso controlado e risco documentado;
- Asaas somente Sandbox e ASAAS_BILLING_ENABLED=false em produção;
- Brevo off por padrão, depois canário limitado e promoção separada;
- demais integrações externas desligadas até seus próprios canários.

## 7. Evidência e atualização contínua

Cada sessão encerra seu trabalho com:

~~~text
MISSAO: <nome>
STATUS: PASS, FAIL ou BLOCKED
SHA/PR/BRANCH: <valores exatos>
EVIDENCIAS: <testes, checks e revisão>
MUTACOES: <arquivos/recursos exatos>
RISCOS: <residuais e aceites>
PROXIMO GATE: <uma única ação que exige autorização>
~~~

A sessão Central atualiza este documento somente após resultados finais, sem
reformular registros passados para esconder falhas. O relatório final precisa
conter SHA de main, PRs/commits, migrations, releases backend/frontend,
health/readiness, login/CORS/RLS, flags, canários, backup/restauração,
monitoramento, riscos aceitos e rollback.

Use V1_CODE_COMPLETE, V1_RELEASE_CANDIDATE, V1_RELEASE_READY ou V1_BLOCKED
enquanto algum gate estiver pendente. Em 2026-08-22 o estado é
`V1_ENCERRADA`: todos os gates da seção 1 foram comprovados, a tag `v1.0.0`
foi publicada no SHA de código `281e69c2...`, o GitHub Release foi criado, a
evidência foi integrada em `ea40cda3...` (PR #274) e o housekeeping foi
concluído com revogação dos acessos temporários.

## 8. Histórico preservado

- A fundação de readiness/observabilidade M08 foi integrada inicialmente pela
  PR #249 em 9e5bab9962c83628bf30d427921ad6125134511a.
- A correção de concorrência de claims recuperados foi integrada pela PR #260
  em fd1cf37337ff904e86b9d5880d9cc6e30760947a.
- A recuperação do monitor foi integrada pela PR #261 em
  5d7059dfc178f5605d0e12fe3cf58fb2d9a005aa.
- A prontidão Supabase/Supavisor foi endurecida e implantada pela PR #262 em
  f2c3132b2a1d5060c4ba236374f0475416973be2; a issue #259 foi encerrada após
  verificações saudáveis e backup/monitor validados.
- M00 foi integrado pela PR #263 em
  5a0f12f5062bfd45d780dacf29090c8f34a66da8, sem remover os arquivos locais
  não rastreados do checkout principal.
- M09 foi integrada pela PR #245 em
  25d3876771bb8ffb0b160d79d6b548f31510186e, com o baseline E2E atualizado
  para Node 24 e evidência por tentativa.
- M01 foi integrada pela PR #234 em
  cc89c0c1b9966219f921f80c9ee28e03ba152537, após atualização para a main e
  validação de billing, concorrência, migration real em PostgreSQL 17 e CI.
- A falha concorrente que motivou #260 é histórica como problema de código;
  ela não reabre M08 enquanto a main atual permanecer comprovada. O problema
  era a aceitação operacional registrada na issue #259, agora resolvida.
- Registros que dependiam de paths Windows, worktrees efêmeros e IDs de tarefas
  antigos foram removidos da execução ativa. Eles podem servir como pista para
  recuperação de Brevo/Células, mas nunca como instrução operacional atual.
