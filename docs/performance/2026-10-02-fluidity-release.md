# Igreja12: recibo do release de desempenho

Registro observado em 02/10/2026, UTC. Fonte, CI, publicação frontend e backend
possuem provas distintas. As metas de campo permanecem abertas.

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

## Backend e campo pendentes

O backend deste pacote **não foi publicado**. O acesso à VPS pelo console web
da Hostinger foi confirmado em 02/10. Código integrado, testes PG17 e deployment
frontend não comprovam aplicação do backend ou estado de schema em produção.

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
`sha256:bab6320c33315aa5948290867b18ae5b1fe5d980f3d843825f529d362a2a9ae27`
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

O cliente conserva fallbacks para a API anterior. Os ganhos de bootstrap
combinado, paginação/agrupamento SQL, snapshots da fila, cursores e assinatura
de mídia desacoplada dependem da implantação verificável do novo backend.
Os fallbacks completos mantêm conteúdo, com custo maior onde necessário.

Nenhuma migration, região, capacidade, pool de banco, Redis ou gate de envio,
billing ou agente foi alterado. O lock do envio humano permanece. As decisões
condicionadas e o bug preexistente de código opaco estão no
[plano e seus limites](2026-10-02-fluidity-plan.md).

Próximo gate operacional único: autorização específica de Raniel para o
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
Depois da implantação, medir tarefas autenticadas antes de decidir mudanças
de infraestrutura ou encerrar os RNFs de desempenho.
