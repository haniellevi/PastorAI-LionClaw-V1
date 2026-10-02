# Igreja12: recibo do release de desempenho

Registro observado em 02/10/2026, UTC. Fonte, CI, publicação frontend e backend
possuem provas distintas. As metas de campo permanecem abertas.

## Backend publicado: manutenção compatível com o legado

Em 02/10 o proprietário reiterou autorização de produção e acesso ao ambiente.
O preflight privado, por conexão existente na VPS em transação read-only,
confirmou 70 entradas de ledger, schema legado e ausência de tabelas exigidas
pelo backend da main. O estado do PostgreSQL observado foi 17.6. Não houve
mutação de dados, schema, gates ou serviços durante esse diagnóstico.

A imagem anterior à troca foi comparada ao snapshot privado de
`eb5a09b975160f993a3c31bd3c28edc89d9a38ff`: 145 arquivos Python e o lock de
dependências coincidiram, sem arquivos extras. As colunas e políticas das 13
tabelas necessárias aos caminhos otimizados foram consultadas sem ler dados
de domínio. Esse recorte não atesta migrations antigas ausentes ou módulos
futuros e não substitui a revisão dos dados.

O [perfil de manutenção da API](../../deploy/BACKEND-MAINTENANCE-RELEASE.md)
publicou o backport `07a3f4d9a4fe510cf83fd48d5deaa52dcfbb7e02`, revisado na
[PR #455](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/455).
O orquestrador veio da main `9f2e87da62255e2bc53a7052be3018c0b51c189b`, merge da
[PR #456](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/456), com árvore
igual à do candidato operacional revisado `ced644f1813cbcb8b5842f373b1634d73ce5799b`.
Ambas as PRs concluíram todos os checks com sucesso; links, SHAs e digests
constam no [recibo sanitizado de produção](2026-10-02-backend-maintenance-production.json).

A execução começou às `2026-10-02T16:43:23.884529Z`, terminou com código `0`
às `16:45:01Z` e foi pós-verificada às `16:46:26.929711Z`. A imagem da API é
`sha256:4a65f30e1c2dfbcf84c88e9c88203a4176a8d10f7d1b345248bc367ec9a9b241`.
Somente a API foi substituída. Os seis serviços protegidos, incluindo os três
workers, mantiveram IDs, imagens, início e contadores de reinícios. Os workers
e o symlink da stack permanecem no release legado. Os gates foram preservados:
`ALLOW_REAL_SENDS=true`, `ASAAS_BILLING_ENABLED=false`, `BREVO_SEND_MODE=off` e
`BROADCAST_ASYNC_ENABLED=false`; não houve migration, mudança de `AgentConfig`
ou ativação V1a/V2b/V3.

O checker read-only confirmou o contrato de 70 entradas no ledger, 13 tabelas
e 153 tipos de coluna. O monitor da troca registrou dez observações, três com
`HTTPError` entre `16:44:36.238978Z` e `16:44:46.653555Z`; voltou a receber 200
com o SHA novo às `16:44:51.831911Z`. Isso comprova breve indisponibilidade,
sem estabelecer duração exata ou códigos HTTP das falhas.

No smoke posterior, `/health` e `/ready` retornaram 200; `/auth/bootstrap`,
`/cells/lookup`, `/cells/summary` e `/contacts/lookup` retornaram 401 sem sessão.
Todas as seis respostas trouxeram `X-Backend-Release` igual ao SHA da API.
A prontidão confirmou banco, Redis, dependências opcionais e os três workers.
Sua amostra pública de 2.034,7 ms é um probe de prontidão, sem valor de benchmark
do produto. Não houve teste autenticado de latência nem encerramento dos RNFs.

Não houve rollback. A imagem anterior
`sha256:bab6320c33315aa5948290867b18ae5b1fe5d980f3d843825f529d36a2a9ae27`
foi preservada para recuperação; o checksum do backup foi conferido, mas a
restauração do banco não foi exercitada. A nova API contém os locks corrigidos;
os workers mantêm as dependências anteriores. As oito migrations antigas
ausentes no ledger continuam pendentes.

## Fonte e CI

- Base: `35c79663f706a9db489b3a896e0f4b1ec96f8b1c`.
- Candidato revisado: `a447972a4d9cf7c4077188a877e934fd11697703`.
- Árvore do candidato: `f32d19f18e2a8ad21f0e344e2f757878549e0635`.
- Integração: `e59feb5e2afc3c93e414f09e709ace1e225dbca5`, pela
  [PR #451](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/451), em
  `2026-10-02T13:39:43Z`. A árvore do merge é igual à do candidato.

Todos os checks obrigatórios do candidato foram aprovados antes do merge:

| Check | Evidência do candidato |
|---|---|
| backend-tests | [Run 37013589500](https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37013589500), 6.142 testes offline aprovados |
| frontend-ci | [Run 37013588578](https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37013588578), lint, typecheck, testes e build aprovados |
| e2e-critical | [Run 37013588720](https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37013588720), 69 testes aprovados |
| rls-integration | [Run 37013588455](https://github.com/haniellevi/PastorAI-LionClaw-V1/actions/runs/37013588455), 821 executados, zero skip, falha ou erro |
| Vercel | [Prévia do candidato](https://vercel.com/raniel-levis-projects/pastorai-frontend-prod/3X9aUJxHJLTyuCZ3Yh7WGsHmmMd3), READY |

No ambiente local, Node 24.19.0 e Python 3.13.14, passaram 6.142 testes backend,
1.165 testes frontend em 126 arquivos, 69 E2E com build de produção e os 13
guards de privacidade. Os dez casos adicionais de busca por líder tiveram RED
antes da correção e GREEN em PostgreSQL 17; o módulo final teve 26 PASS.

A revisão independente confirmou autorização, busca por líder além do registro
200, paginação, contagens, cancelamento e foco durante import dinâmico. O E2E
reconstruído confirmou teclado/foco no console em celular e desktop. Nenhum
assert de E2E foi enfraquecido. Dados de teste são sintéticos e descartáveis.

## Frontend publicado

Em `2026-10-02T13:41:38Z`, a Vercel confirmou:

- deployment `dpl_FwC5LUNJyUjxGZNcaFtngY2e95Ui`;
- `target=production`, estado `READY`;
- commit `e59feb5e2afc3c93e414f09e709ace1e225dbca5`;
- aliases [app](https://app.igreja12.com.br/),
  [admin](https://admin.igreja12.com.br/) e
  [painel](https://painel.igreja12.com.br/).

O QA público terminou em `2026-10-02T13:42:44Z`: 18 contextos Chromium isolados,
sem cookies ou sessão, três amostras por domínio/perfil, todos com HTTP 200,
formulário visível, zero erro de JavaScript e nenhuma requisição bloqueada.
O teste permitiu somente GETs públicos e assets do mesmo domínio, sem login,
consulta autenticada ou efeito externo.

O perfil móvel usou viewport 390x844, CPU 4x, rede 1,6 Mbps de download,
0,75 Mbps de upload e latência de 150 ms. Medianas de LCP da pequena amostra:

| Domínio | Desktop | Móvel limitado |
|---|---:|---:|
| app | 2.000 ms | 2.200 ms |
| admin | 952 ms | 2.132 ms |
| painel | 1.132 ms | 2.088 ms |

Essas amostras públicas não estabelecem RUM, INP, p75/p95 autenticado ou melhora
percentual sobre a versão anterior. O tempo de espera pelo formulário foi
observado depois de `load`, portanto é apenas limite superior de sua aparição.
O orçamento de navegação aquecida aprovado no E2E é evidência de laboratório.

Rollback frontend disponível: release anterior
`35c79663f706a9db489b3a896e0f4b1ec96f8b1c`, deployment
`dpl_2FMcWy82H7ydNzgq2QsBSrZbuBCy`. Nenhum rollback foi executado.

O recibo documental foi integrado pela
[PR #452](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/452).
O frontend de `379a4dc51bfd46d25d68e5cb43a0699b48d12bc1`, deployment
`dpl_8qZDU3BgKXMjUnowvKXn7CJgYhrv`, foi confirmado `READY`, Production,
com os três aliases em `2026-10-02T13:55:31Z`. Os diretórios `frontend`,
`backend` e `deploy` conservam os mesmos bytes do merge `e59feb5`.
Os cinco workflows de CI do SHA `379a4dc` terminaram em `SUCCESS`,
conferidos em `2026-10-02T14:01:26Z`.
O smoke público desse deployment teve seis amostras com HTTP 200 e sem erros
de JavaScript. Uma medição desktop do app teve LCP de 6.072 ms; três novas
amostras isoladas tiveram 1.228, 940 e 1.512 ms. A causa da variação não foi
estabelecida e a pequena amostra não demonstra um SLO de campo.

## Histórico do preflight e limites de campo

Até o preflight relatado abaixo, o backend ainda não havia sido publicado.
A publicação posterior da API de manutenção está comprovada na seção inicial;
o backend integral da main continua fora dessa execução. Este histórico
preserva a sequência de diagnóstico e os requisitos da rota integral.

A ausência de `backend-production`, registrada às `13:36Z`, foi resolvida em
02/10 sob o pedido de continuidade do backend. A leitura REST em
`2026-10-02T14:12:19Z`, seguida de conferência independente, confirmou:

| Configuração de `backend-production` | Estado observado |
|---|---|
| Reviewer obrigatório | `haniellevi`, User `8795157` |
| Bypass administrativo | Desativado, `can_admins_bypass=false` |
| Origem permitida | Uma branch `main`, zero tags |
| `BACKEND_DEPLOY_ALLOWED_ACTORS` | `haniellevi` |
| `BACKEND_DEPLOY_SAFE_BASE_SHA` | `49abfa86f2ff80bbf85d41fbc8cdb1778c583b56` |
| Nomes de secrets do environment | Lista vazia |

O piso é o merge revisado da PR #443, que inclui o endurecimento de timeout e
rollback, e é ancestral do candidato `379a4dc`. Piso e candidato contêm
`BACKEND_RELEASE_SAFETY_VERSION=2`; candidatos anteriores ao endurecimento
ficam recusados. `prevent_self_review=false` mantém a aprovação humana viável
com a única identidade operacional confirmada, sem dispensar a revisão
obrigatória. O agente não aprova o próprio dispatch.

Após a revisão da correção de preflight da PR #453, o piso foi elevado para
`c5f99b5463b128e4c7749dcd876ffa03164a1d34`, confirmado pela API do environment
às `2026-10-02T14:45:30Z`. Esse commit contém os bytes revisados da nova guarda;
até sua integração na `main`, o workflow recusa candidatos dessa branch.
O piso novo impede selecionar versões anteriores que descobriam a ausência
do checker de rollback somente depois de interromper serviços. Os demais
controles permanecem iguais; nenhum dispatch foi executado.

Nenhum arquivo privado foi lido. Não foi disparado o workflow manual nem
executada conexão SSH/banco de produção. A configuração do GitHub não comprova
schema ou recuperação. A inspeção do console às `2026-10-02T14:27:07Z`
confirmou os quatro contêineres saudáveis, a imagem
`sha256:bab6320c33315aa5948290867b18ae5b1fe5d980f3d843825f529d36a2a9ae27`
e o diretório de trabalho em
`/opt/pastorai-releases/eb5a09b975160f993a3c31bd3c28edc89d9a38ff/deploy`.
O symlink ativo aponta para esse release; nome de diretório e label não provam
sozinhos todos os bytes executados. Nos quatro processos,
`ALLOW_REAL_SENDS=true`; os outros três gates estão fechados. Fechar envios
exige inventário e janela próprios porque pode cancelar avisos pendentes.

O host usava Compose `2.40.3+ds1-0ubuntu1~24.04.1`, sem as opções de espera
exigidas pelo procedimento. Às `2026-10-02T14:39:45Z`, foi instalado Compose
`5.0.0` oficial em `/usr/local/lib/docker/cli-plugins/docker-compose`, com
SHA-256 `5091bac5729ce968c602d157c2f0b959b7b367d4efb70aa864eb9ae78eebe13e`.
Versão, `start --wait`, `--wait-timeout` e probe GNU `timeout` passaram.
O plugin anterior em `/usr/libexec/docker/cli-plugins/docker-compose` foi
preservado. IDs, horário de início e saúde dos quatro contêineres permaneceram
iguais; nenhum serviço foi reiniciado. Essa atualização do cliente não prova
deploy, schema ou rollback da aplicação.

O hPanel mostrou backup semanal de `30/09/2026 01:51`, com `23,80 GB`, no
horário exibido pelo provedor, e nenhum snapshot. Isso comprova a listagem,
sem atestar restaurabilidade ou compatibilidade de banco. O arquivo de status
do backup local existia com mtime `2026-10-02T06:16:05Z`; seu conteúdo e os
backups não foram abertos.

O release ativo não contém `deploy/check_backend_schema.py`, confirmado no
console às `2026-10-02T14:32:38Z` e na árvore Git histórica. A correção preparada
na PR #453 recusa checker/manifesto anterior ausente ou inválido antes da cópia
da configuração e exige os dois checkers, com seus próprios manifestos, antes
de build ou substituição. Ela preserva a revalidação do rollback em sua própria
imagem e não cria compatibilidade para o legado. A recuperação desse legado
precisa de um contrato revisado após a consulta do schema vivo.
Validação da correção: RED com cinco testes e dez falhas de assertions na
fonte anterior; GREEN com 52 testes sintéticos de release, incluindo 14 do
workflow, sem skips, no
Python 3.13.14, repetido por revisão independente dos mesmos hashes.
Os 18 contratos do runbook também passaram; os 14 testes do workflow foram
reexecutados isoladamente após a atualização documental.
Essas verificações usam dublês de comandos e não atestam banco ou recuperação
real da VPS. A mudança de preflight não altera a classificação de cobertura
do produto na matriz PRD.

O cliente conserva fallbacks para a API anterior. O backport publicado oferece
bootstrap combinado, paginação/agrupamento SQL, snapshots da fila, cursores e
assinatura de mídia desacoplada. A melhoria percebida em tarefas autenticadas
ainda precisa ser medida; os fallbacks continuam disponíveis.

O pool da API passou a verificar conexões ociosas e os clientes HTTP reutilizam
conexões. Região, capacidade e infraestrutura de banco/Redis foram preservadas,
assim como os gates de envio, billing e agente. O lock do envio humano permanece.
As decisões condicionadas e o bug preexistente de código opaco estão no
[plano e seus limites](2026-10-02-fluidity-plan.md).

Registro histórico anterior à autorização deste turno e ao perfil de manutenção:
naquele momento, o próximo gate era autorização específica de Raniel para o
preflight privado da configuração ativa e consultas somente leitura de schema
e inventário agregado no Supabase PROD, incluindo a delegação excepcional das
consultas reservadas ao operador. Esse gate não autoriza fechamento de envios,
alteração de banco ou restart. Depois do diagnóstico, registrar a recuperação
revisada e a janela nominal, igrejas-alvo, contenção e backup/rollback conforme
[runbook manual](../../deploy/BACKEND-RELEASE-MANUAL.md) e
[runbook de produção](../ops/PRODUCTION-RUNBOOK.md).
As quatro credenciais `BACKEND_DEPLOY_HOST`, `BACKEND_DEPLOY_USER`,
`BACKEND_DEPLOY_SSH_KEY` e `BACKEND_DEPLOY_KNOWN_HOSTS` precisam ser configuradas
no environment por um caminho privado autorizado, com host-key conferida.
O acesso pelo console foi resolvido; as credenciais da Action continuam ausentes.
O runbook reserva as consultas de PROD ao operador. A publicação genérica não
define alvos, duração nem a decisão nominal de fechamento de envios, que pode
cancelar avisos pendentes. Reabertura exige decisão humana separada.
O próximo trabalho de validação é medir tarefas autenticadas antes de decidir mudanças
de infraestrutura ou encerrar os RNFs de desempenho.
