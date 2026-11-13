# Inventário de conclusão — leitura de 12/11/2026

Fotografia do projeto para fechar o que falta: branches, lacunas do PRD,
lixo e ambientes. É **inventário de fatos**, não plano: o planejamento fica
só no [ROADMAP](../../ROADMAP.md).

- Leitura feita em 12/11/2026, entre 22:15 e 23:00 (horário de Brasília),
  somente leitura, por cinco agentes em paralelo, com conferência por amostra.
- Referência: `origin/main` em `afa625e4` (merge da #671).
- Produção **não foi tocada**: nenhum acesso à VPS, ao banco remoto ou aos
  domínios de produção. Tudo o que é estado vivo de PROD está marcado
  "não verificado".
- Tamanhos: P = 1 PR pequena; M = 2 a 4 PRs; G = mais que isso. São
  estimativas, sem medida.
- Este arquivo envelhece. Antes de apagar, mesclar ou publicar qualquer
  coisa, refaça a prova daquele item.

## 1. Estado da `main`

| Item | Fato | Fonte |
|---|---|---|
| CI no SHA atual | `backend-tests`, `frontend-ci`, `e2e-critical` e `rls-integration` verdes em `afa625e4`; também `tooling-static` e `synthetic-release` | GitHub Actions, 12/11 23:01 UTC |
| Commit anterior | `94622580` (merge da #670) teve `e2e-critical` vermelho; causa não investigada | GitHub Actions |
| PRs | 632 no total: 617 mescladas, 14 fechadas sem merge, 1 aberta (#672, da janela de produção) | `gh pr list` |
| Checkout principal | `main` local em `2bc89f89`, 8 commits atrás da remota (só ROADMAP, runbook e `deploy/first_transition*`) | Git local |

## 2. Worktrees, branches e referências

### 2.1 Worktrees

| Pasta | Estado | Situação |
|---|---|---|
| checkout principal | `main` `2bc89f89`, limpo | manter |
| `.claude/worktrees/filtro-vault-dono-vazio` | `fix/filtro-vault-dono-vazio` `ba6199a1`, PR #672 aberta | em uso pela sessão da janela; não tocar |
| `.claude/worktrees/keen-darwin-5dc5cb` | detached `b0bd023b`, limpa, commit já na `main` | pode ser removida com `git worktree remove` quando a sessão dona liberar |
| worktree do Orca (`.orca-preparing/901169-…`) | não existe mais; sobrou só o registro vazio em `.git/worktrees` | nada a avaliar |

### 2.2 Contagem por classe (226 locais, 165 remotas)

| Classe | Locais | Remotas | Prova usada |
|---|---|---|---|
| Integrada | 167 | 148 | PR mesclada com head igual ao tip (142 nomes), tip ancestral da `main` (37), `git cherry` sem diferença (11), ancestral do head de PR mesclada (1) |
| Integrada (parcial) | 12 | 0 | conteúdo igual ao merge da PR, menos 1 a 3 arquivos de base empilhada |
| A integrar | 1 | 1 | PR #672 aberta |
| Preservar por decisão | 1 | 1 | ROADMAP |
| Candidata a descartar | 25 | 8 | PR fechada sem merge, ou commit preservado em outra referência |
| Duvidosa | 20 | 7 | sem PR ou sem prova de conteúdo |

A lista nominal das integradas está no apêndice. As demais estão abaixo.

### 2.3 Integradas parciais (12, só locais)

`feat/cd-contrato-v1` (#495), `feat/cd-turmas-v1` (#497), `feat/cd-matricula-v1`
(#498), `feat/cd-presenca-v1` (#499), `feat/cd-conclusao-v1` (#500),
`feat/cd-whatsapp-v1` (#501), `feat/enviar-contrato-v1` (#502),
`feat/enviar-avaliacao-v1` (#503), `feat/enviar-nomeacao-v1` (#504),
`feat/enviar-abertura-v1` (#505), `feat/enviar-multiplicacao-v1` (#506),
`feat/enviar-tela-v1` (#507).

O tip local difere do head da PR mesclada. Em cada uma, 1 a 3 arquivos
diferem do commit de merge (`ROADMAP.md`, `main.py`, `ScreenView.tsx`),
por causa da base empilhada. Existe tag `backup/pre-merge-*` para cada uma.
Falta conferir os arquivos diferentes antes de apagar.

### 2.4 A integrar

| Branch | PR | Observação |
|---|---|---|
| `fix/filtro-vault-dono-vazio` | #672 aberta | da janela de produção; outra sessão conduz |

### 2.5 Preservar por decisão registrada no ROADMAP

| Item citado no ROADMAP | O que existe | Situação |
|---|---|---|
| branch da #619 em `9ce9a5d9` | `origin/codex/igreja12-native49-local` (só remota), 7 commits e 94 arquivos fora da `main` | existe; preservar |
| `vps07a-source-20261005` | `codex/vps07a-source-20261005` `4962c05e`, **só local**, 2 commits fora da `main`; também em `refs/archive/checkout-principal-20261016` | existe; preservar |
| `vps04a-network-guard` | `codex/vps04a-network-guard` `d36ab813`, local; tip é ancestral da `main` | existe |
| `integracao-incremental-20261013` | `codex/integracao-incremental-20261013` `75c47ed4`, local; tip é ancestral da `main` (#473) | existe; o trabalho não salvo citado no ROADMAP: não verificado |
| `arquitetura-performance-seguranca-20261003` | nome exato não existe; candidato `codex/auditoria-arquitetura-20261003` `d36ab813`, ancestral da `main` (#458) | não confirmado que seja a mesma referência |
| `elastic-kirch-0de4a3` | nenhuma referência com esse nome; o `lock_timeout` está na `main` (`7a53ecc7`) e em `refs/archive/organization-20261103-batch1/fix/migrate-lock-timeout-20261027` | nome não encontrado; conteúdo equivalente na `main` |
| `refs/archive/checkout-principal-20261016` | `6d75e085` | existe |
| `deploy/offsite-encrypt-backup.sh` e `deploy/pull-offsite-backup.sh` | não aparecem em `deploy/` na `main` | segundo o ROADMAP, só em `refs/archive/checkout-principal-20261016`; não conferido |

### 2.6 Duvidosas (27): precisam de leitura do conteúdo antes de qualquer decisão

Só existem neste computador (20):

| Branch | Último commit | Commits únicos | Arquivos |
|---|---|---|---|
| `chore/devin-supabase-skills` | 30/08 | 15 | 46 |
| `codex/maestri-persistence` | 22/08 | 19 | 43 |
| `codex/ai-orchestration` | 22/08 | 9 | 22 |
| `feat/cell-report-application-service-offline` | 31/08 | 1 | 44 |
| `feat/cell-report-human-writer-lock-offline` | 31/08 | 1 | 46 |
| `feat/cell-report-snapshot-v2-offline` | 31/08 | 1 | 36 |
| `feat/cell-report-turn-uow-offline` | 31/08 | 1 | 46 |
| `feat/cell-report-workflow-offline` | 31/08 | 1 | 29 |
| `feat/d3-trusted-inbound-identity-wiring-offline` | 31/08 | 1 | 25 |
| `feat/d3-turn-execution-contract-offline` | 31/08 | 1 | 18 |
| `feat/agent-reply-reservation-v2-offline` | 31/08 | 1 | 44 |
| `feat/audio-retencao-v1` (tip diferente do head da #512 mesclada) | 19/10 | 3 | 18 |
| `worktree-fix-migrations-hardening` (tip diferente do head da #474 mesclada) | 14/10 | 1 | 9 |
| `archive/conhecimento-painel-before-reposition-20261019` | 19/10 | 2 | 20 |
| `docs/igreja12-wiki-audit-20260825` | 26/08 | 2 | 16 |
| `docs/pr352-postmerge-reconciliation` | 31/08 | 1 | 14 |
| `docs/prod-readonly-nominal-policy-20260922` | 22/09 | 3 | 7 |
| `docs/v1-cell-report-whatsapp-plan` | 27/09 | 1 | 1 |
| `docs/whatsapp-consolidation-v3-plan` | 28/09 | 2 | 1 |
| `perf/pos-v1-2026-08-31` | 31/08 | 1 | 4 |

Só existem no GitHub, sem PR (7):

| Branch | Último commit | Arquivos |
|---|---|---|
| `backup/ds-adocao-componentes-rascunho-20261112` | 12/11 | 15 |
| `chore/release-preflight` (pode ter sido superada pela #563; não verificado) | 23/10 | 5 |
| `codex/backend-maintenance-base-eb5a09` | 02/10 | 41 |
| `wip/antigravity-resgate-2026-07-06` | 06/07 | 16 |
| `codex/antigravity-clean-main` | 27/06 | 7 |
| `codex/docs-hermes-agent-architecture` | 20/08 | 2 |
| `claude/omni-route-llm-fallback-t1h9h1` | 31/08 | 1 |

### 2.7 Candidatas a descartar (33)

PR fechada sem merge (existem no GitHub):

| Branch | PR | Observação |
|---|---|---|
| `feat/origin-preflight-window` | #618 | commits são ancestrais da #619, que é preservada |
| `fix/nginx-http-https-window` | #617 | idem |
| `fix/created-network-identity` | #616 | idem |
| `ops/dev-espelho-prod-20260927` (local e remota) | #431 | 7 commits, 13 arquivos |
| `docs/d6-audio-caller-contract-v5` (local e remota) | #362 | 1 commit, 1 arquivo |
| `cursor/cloud-agent-notes-a8af` | #460 | 2 commits |
| `devin/mission-orchestrator` | #281 | 1 commit |
| `backup/e4b-c3-catalog-bound-executor-v3` | sem PR | mesmo commit em `refs/archive/worktrees-20261015/*` |

Só locais, com o mesmo commit guardado em outra referência **local**
(`refs/archive`, tag `backup/*` ou `refs/codex/snapshots`):
`chore/filadelfia-agent-setup`, `chore/maestri-setup`, `chore/neon-dev-setup`,
`codex/maestri-astra-workspace-plan`, `codex/maestri-cofre`,
`codex/maestri-forja`, `codex/maestri-lente`, `codex/maestri-nexo`,
`codex/maestri-sentinela`, `codex/painel-performance-20261002`,
`codex/painel-performance-maintenance-20261002`,
`codex/reconciliacao-documental-20261004`, `design/capacitacao-destino`,
`docs/acompanhamento-registro-20261009`, `docs/e4b-replay77-receipt-20260913`,
`docs/e4b-tarefas-operacionais-source-readiness-20260914`,
`docs/reconciliacao-regras-locais-20261031`,
`feat/e4b-c3-catalog-bound-executor-v3`,
`feat/e4b-filadelfia-catalog-materialization-20260917`,
`feat/whatsapp-canary-preparation-v1`,
`feat/whatsapp-cell-report-coordinator-v1`.

Com cópia no GitHub: `backup/ds-adocao-componentes-rascunho-20261112` e
`chore/release-preflight` (as duas aparecem como duvidosas na remota).

### 2.8 Stashes e referências fora de branches

- 2 stashes: `root-local-AGENTS-authtest-consolidation-20261027-aff7fd48` e
  `pre-sync-v1-audit-20260822`.
- `refs/archive`: 59 referências (checkout principal de 16/10, organização de
  03/11, reconciliações e 40 worktrees de 15/10).
- `refs/codex`: 8 snapshots e 9 checkpoints do aplicativo Codex.
- 23 tags `backup/pre-merge-20261018|19/*`, `refs/pr670`,
  `refs/preserve/worktrees/*` e a tag `v1.0.0`.
- `.git/local-preservation/` tem 12 KB, vazia. O ROADMAP fala em ~19 GB nesse
  caminho: não estão lá. Onde foram parar: não verificado.

### 2.9 Risco de perda

40 branches locais não existem no GitHub (20 duvidosas, 19 candidatas a
descartar e `codex/vps07a-source-20261005`, que é para preservar). `refs/archive`,
as tags `backup/*`, `refs/codex` e os stashes também são só locais. Estar em
`refs/archive` protege contra apagar a branch, não contra perda do disco.

## 3. Lacunas do PRD

Nenhum item que a [cobertura do PRD](../ai/PRD-COVERAGE.md) marca como
entregue foi desmentido pelo código. As diferenças são de omissão ou precisão
(seção 3.4).

### 3.1 Falta código

Produto e agente:

| Id | Lacuna | Estado real | Tam. | Risco | Arquivos que tocaria |
|---|---|---|---|---|---|
| A1 | Conhecimento oficial por texto livre no WhatsApp | só o comando fechado `CONHECIMENTO buscar`; pergunta livre não consulta a base | M | privacidade, autorização | `conhecimento_whatsapp/*`, `services/conhecimento.py`, `agent/nodes.py`, `prayer/catalog.py`, `workers/queue_worker.py` |
| A2 | Ingestão de arquivo e áudio no conhecimento | só texto; sem upload nem parser | M | Storage, migration, RLS | `routers/conhecimento.py`, `services/conhecimento_editorial.py`, painel de conhecimento, migration |
| A3 | Contagem de lacunas de conhecimento no Hoje | não existe | P | baixo | `services/hoje.py`, `routers/dashboard.py`, painel |
| A4 | Outbox única: SLA | `sla_engine.py` envia direto | M | envio real, migration do `purpose` | `services/notification_outbox.py`, `services/sla_engine.py`, `workers/cron_worker.py`, migration |
| A5 | Outbox única: aviso de upgrade da cobrança | `billing_worker.py` envia direto | P | envio real | `services/billing_worker.py`, `notification_outbox.py`, migration |
| A6 | Outbox única: broadcast | ledger próprio com recorrência e retry | G | envio em massa, concorrência | `services/broadcast_delivery.py`, `workers/broadcast_worker.py`, `routers/broadcasts.py` |
| A7 | Janela de envio 08–21h fora da outbox | só a outbox aplica; SLA, broadcast e cobrança não | P | envio real | dentro de A4 a A6 |
| A8 | Especialista Central de Células no WhatsApp | só `consultar_celulas`, que lista até 10 nomes | M a G | autorização por célula | pacote novo; `prayer/catalog.py`, `cell_suggest/catalog.py`, `queue_worker.py`, `agent_privilege_catalog.py`, `agent_privilege_routing.py` |
| A9 | Especialistas de Hoje/pendências, visitantes e comunicados | nenhuma ferramenta do agente | G | autorização, privacidade | mesmos de A8 |
| A10 | RF-33: executores dos agendamentos do agente | só roda ação com "sla/cobranca/prazo"; 7 gatilhos não avaliados; último disparo só em memória | M | envio real, concorrência, migration | `workers/cron_worker.py`, `routers/agent.py`, `AgenteScreen.tsx`, `db/models.py`, migration |
| A11 | RF-47: tela do assistente do sistema | backend pronto; nenhuma tela chama | P | baixo | `frontend/src/components/shell/*`, componente novo |
| A12 | Google Agenda: revogar ao desconectar, reduzir escopo, limpeza em lote | escopo `calendar.events`; desconectar só apaga a linha local | P a M | OAuth, migration | `routers/calendar.py`, `services/google_oauth.py`, `routers/events.py`, migration |
| A13 | B15: gatilho de interpretação de relatório | #592 corrigiu só a extração | P | baixo | `agent/nodes.py`, `services/cell_report_v1a_service.py`, `domain/cell_report_v1a.py` |
| A14 | RF-D4: ranking de líderes aptos | não encontrado; pode ter sido superado pelo convite de consolidação | M | privacidade | `routers/work_queue.py`, serviços, painel |
| A15 | Onboarding: ações nos estados vazios, importação CSV, runbook de provisionamento | checklist existe; sem CSV | M | PII em CSV, RLS | `DataTable.tsx`, contatos, `routers/contacts.py`, `docs/ops` |
| A16 | RF-26: alertas ao líder pelo WhatsApp | alertas só no painel | M | envio real | `services/cell_alert_rules.py`, `notification_outbox.py`, migration |
| A17 | EVT-7: consulta somente leitura dos 11 eventos (opcional) | não existe | P | baixo | `backend/scripts/*` |
| A18 | Comentário velho em `semantic_triage.py` | diz "não ligado ao turno", mas o worker usa | P | nenhum | `services/semantic_triage.py` |

Plataforma:

| Id | Lacuna | Estado real | Tam. | Risco | Arquivos que tocaria |
|---|---|---|---|---|---|
| T1 | Corrida em `cd.create_turma` | `cd.py:118` usa `on conflict(id)` com `unique(igreja_id,id)`: mesmo defeito das #595/#596; o teste atual não sincroniza no INSERT. `uv_matriculas` (`uv.py:227`) tem o mesmo árbitro, mitigado pela trava da turma | P | concorrência | `services/cd.py`, `services/uv.py`, `tests/test_cd_turmas_pg.py`, `tests/test_uv_turmas_pg.py` |
| T2 | CSP bloqueando | hoje `content-security-policy-report-only` em `frontend/src/middleware.ts`; o painel não carrega SDK do Clerk; sobra `style-src-attr 'unsafe-inline'`; sem coletor de violações | P a M | painel em branco se bloquear recurso | `frontend/src/middleware.ts`, `lib/csp.mjs`, `next.config.mjs`, `e2e/csp-report-only.spec.ts` |
| T3 | Cookie de sessão HttpOnly | login devolve o token no JSON; API só aceita Bearer; painel grava cookie legível e `localStorage`; backend não lê cookie. Exige `Set-Cookie`, leitura do cookie, proteção CSRF e `credentials: include` nos 4 clientes | M | autenticação; muda o contrato da API | `routers/auth.py`, `routers/platform_admin.py`, `deps.py`, `main.py`, `frontend/src/lib/{auth-context,admin-auth-context,api,admin-api,dashboard-api,lookup-api}` |
| T4 | Métricas, retenção e metas de serviço | histogramas por rota já existem (`performance.py`), só em log e sem endpoint; falta coletor, retenção e metas escritas | M | baixo | `performance.py`, `routers/operations.py`, `deploy/monitoring/*`, `docs/ops/OBSERVABILIDADE-IA.md` |
| T5 | Pausa de release que preserva a fila | fechar `ALLOW_REAL_SENDS` cancela pendências da outbox; só a primeira virada contorna (foto dos gates); não existe modo de pausa | M a G | produção, fila | `notification_outbox.py`, `deploy/backend-release.sh`, manual de release |
| T6 | E2E do painel contra a API real | Playwright usa API simulada | M | baixo | `frontend/e2e/*`, `playwright.config.ts` |
| T7 | Auditoria de dependências de desenvolvimento | `npm audit` do CI exclui dev; sem Dependabot; `braces` está em 3.0.3 no lock | P | baixo | `.github/workflows/frontend-ci.yml`, `.github/dependabot.yml` |
| T8 | Expiração de tombstones | não existe rotina; depende de política de retenção | M | RLS, LGPD | `services/private_deletion.py`, migration |
| T9 | URL de banco separada por processo | API, fila, cron e broadcast usam o mesmo `env_file` | P a M | produção | `deploy/*compose*`, runbooks |
| T10 | MFA: tratar segundo fator no login do servidor | sem código; depende de ligar no Clerk | P | autenticação | `routers/platform_admin.py`, `services/clerk*` |

Pontos de colisão (tarefas que tocam o mesmo arquivo precisam de ordem):
`workers/queue_worker.py` (A1, A8, A9); `prayer/catalog.py` e
`cell_suggest/catalog.py` (todo pacote novo do agente);
`agent_privilege_catalog.py` e `agent_privilege_routing.py` (A8, A9, A16);
`notification_outbox.py` e a migration do `purpose` (A4, A5, A6, A16, T5);
`workers/cron_worker.py` (A4, A10); `routers/auth.py` e `deps.py` (T3, T10).

### 3.2 Código pronto; falta release, gate ou aceite

Não é tarefa de programação. Todos com gate fechado no código.

| Item | O que falta |
|---|---|
| Pedido de oração (V4), células próximas, fluxo G12 | aceite pastoral e lista por igreja |
| UV, CD e Enviar (WhatsApp desligado) | migrations em PROD, gates, coordenação vinculada a Pessoa, aceite |
| Memória privada (resumos, retomada, exclusão) | provisionar os logins dedicados e validar a operação |
| Conhecimento oficial (comando fechado e decisão 21) | gate e aceite |
| Relatório texto/áudio, Agenda V2, Consolidação V3, presença, expectativa | ativação e aceite por igreja |
| RF-26 alertas ao líder | aplicar a migration `20261112_160000`; lista por igreja vazia |
| B3 (inbox só papéis fixos) e B4 (opt-out no envio humano) | release |
| Triagem Jev S1 / Tier A | avaliação real e decisão nominal; depende do DPA |
| Broadcast, Asaas, Brevo | canários independentes, domínio/remetente, credencial de produção |
| Lembretes da agenda (G2) | gate e aceite |
| EVT-7 | conciliar os 11 eventos com o provedor antes de decidir reenvio |
| Aceite pastoral das 20 conversas | Raniel executa após o deploy; pode gerar correções |
| Acessibilidade em campo | leitor de tela, celular real e zoom |
| Exclusão de pessoa, igreja e reset | validar a operação em ambiente isolado |
| Alerta `stuck_flow` | credencial dedicada de leitura |
| Backup diário | restaurar em alvo isolado; chave do host novo no backup externo |

### 3.3 Depende de decisão do dono ou de terceiro

| Id | Assunto | O que decidir |
|---|---|---|
| C1 | D2C "propostas" | Hoje há 4 mecanismos de proposta com SIM, expiração, recibo e teste (`agent_action_proposals`, contexto da mensagem, `pedido_oracao_proposta`, `cell_report_drafts`). Falta só unificar, sem ganho visível. Aceitar o modelo atual como atendido, ou unificar (G) |
| C2 | Governança E4B | A #651 arquivou o código em 11/11; a decisão de 12/11 manda retomar. Dizer qual vale e o escopo (finalidades, base legal). Ligado ao consentimento por finalidade (RF-36), hoje sem uso em runtime |
| C3 | "G2b" e "F1/F2 de governança" | Não estão definidos em nenhum arquivo, referência ou histórico. "G2b" surgiu em 22/10 ao lado dos lembretes da agenda (G2). Só o autor sabe o que eram |
| C4 | Checkpointer do agente | Não existe (`private_checkpoint.py` é só contrato com 7 bloqueios). O estado entre turnos vive no contexto da mensagem e nos resumos. Decidir se é necessário (G) |
| C5 | Memória privada além de 3 assuntos | Resumo hoje é de 3 frases fixas (UV, CD, cultos). Resumo livre exige enviar texto ao modelo |
| C6 | Embeddings para o conhecimento | Não existe; busca é por palavras. Decidir se vale o custo e a privacidade dos vetores |
| C7 | Controlador A8/C2 (#619) | ~25 mil linhas em 94 arquivos; o ROADMAP diz que não é necessário para a janela. Retomar inteiro, só um recorte, ou encerrar |
| C8 | Atestações e catálogos de migration | O processo simples (`migrate.py`) foi adotado de propósito; o AGENTS proíbe os wrappers pausados. Manter arquivado ou reduzir a preflight |
| C9 | Especialistas por área (A9) | Quais áreas entram agora |
| C10 | Catálogo de ações do RF-33 (A10) | Quais ações o agendador pode executar |
| C11 | RF-D4 ranking de líderes (A14) | Se o requisito ainda vale |
| C12 | RF-49 provisionamento após pagamento | Hoje é manual; decidir se quer autoatendimento |
| C13 | Outbox do broadcast (A6) e pausa de fila (T5) | Convergir o broadcast para a outbox; criar modo de pausa ou aceitar cancelar pendências no release |
| C14 | EVT-7 | Reenviar ou não, depois de conciliar |
| C15 | Jev | DPA assinado antes de listar igreja |
| C16 | Metas de serviço e ferramenta de métricas (T4) | Números das metas, onde guardar, custo |
| C17 | Terceiros | MFA no Clerk; gates externos do Google (G3, G4, G8, G9); credenciais OpenAI por igreja, Brevo, Asaas e Evolution; DEV online (custo e região); banco em São Paulo (B17) |
| C18 | Limpeza | Itens da seção 4 que exigem SIM; destino das 40 branches só locais |

### 3.4 Diferenças entre documentos e código

1. Consulta ao conhecimento pelo WhatsApp é só o comando fechado; a cobertura
   não deixa isso claro.
2. "Resumos privados por conversa" são 3 frases fixas.
3. Além de SLA e broadcast, o aviso de upgrade da cobrança também envia direto.
   A janela 08–21h existe na outbox; "não verificado" pode virar fato.
4. "Falta credencial Google isolada por igreja": o código já guarda o token por
   igreja. Faltam os gates externos e A12.
5. "Faltam métricas por rota": a medição existe em log; faltam coletor,
   retenção e metas.
6. "`uv_matriculas` e `cd.create_turma` a diagnosticar": diagnóstico fechado
   em T1.
7. "~19 GB em `.git/local-preservation/`": a pasta tem 12 KB.
8. RF-D4 não aparece na cobertura nem no código.
9. Comentário de `semantic_triage.py` está velho (A18).

## 4. Lixo

Nada foi movido nem apagado. Mover para `_lixeira` exige o SIM do dono;
remover do Git exige PR, CI verde e SIM.

### 4.1 Seguro mover, sem PR (ignorados pelo Git; cerca de 440 MB)

| Caminho | Tamanho | Observação |
|---|---|---|
| `frontend/.next` | 336 MB | cache de build; parar o servidor de desenvolvimento antes |
| `output/codex` | 74 MB | logs de execuções de 06/11; conteúdo não aberto |
| `backend/**/__pycache__` | ~24 MB | regenera |
| `output/diagramas` | 3,3 MB | diagramas locais |
| `output/limpeza-worktrees-20261026`, `output/pdf`, `output/retomada-597`, `output/*.md` soltos | ~1,1 MB | registros e rascunhos locais |
| `.ruff_cache`, `.pytest_cache`, `frontend/tsconfig.tsbuildinfo`, `.playwright-mcp`, `.agy-acp` | ~0,6 MB | regeneram ou são resíduo de ferramenta |
| pastas vazias: `frontend/.claude`, `backend/.claude`, `.claude/.claude`, `.agents`, `.codex/worktrees`, `.mission-orchestrator-staging`, `.reticle` | ~0 | sem conteúdo |

### 4.2 Mover com ajuste

| Caminho | Estado | Ajuste necessário |
|---|---|---|
| Entrada do acompanhamento antigo | arquivada | O script aposentado e seu teste estão no [histórico do Git](https://github.com/haniellevi/PastorAI-LionClaw-V1/tree/16be7829e429671bbbef643afc6f45b92c9a48e1). O planejamento atual fica no ROADMAP. |
| `tools/render_progress.py` | rastreado | o ROADMAP manda rodá-lo; só sai se o painel local for encerrado e o ROADMAP editado |
| `backend/scripts/apply_migrations.py` | rastreado | proibido pelo AGENTS, mas citado em `docs/ai/AI-BOOTSTRAP.md` e na cobertura |
| `output/painel` | ignorado | saída do `render_progress.py`; ajustar o ROADMAP |

### 4.3 Duvidosos

| Caminho | Tamanho | O que falta saber |
|---|---|---|
| `.git/local-test-envs` | 136 MB | ambientes de auditoria de 27/10; reconstruíveis |
| `.git/cursor` | 35 MB | cache de editor de 07/10 |
| `output/release` (parte ignorada) | ~3,5 MB | evidência do lote e da primeira virada; a sessão da janela pode usar |
| ~35 scripts de governança de migrations em `backend/scripts/` | ~1 MB, rastreados | sem uso em teste, CI ou app; citados em `docs/governance` e `docs/decisions`. `new_migration.py` e `migrate.py` ficam |
| PRD do PR2 de Células e anexos (04/07) | 10 arquivos, 208.541 bytes | Arquivados na [versão histórica de `docs/`](https://github.com/haniellevi/PastorAI-LionClaw-V1/tree/9b0ee2fb0fc31c08ac9276ccac54121a166080c9/docs). O pacote é a subárvore `c17d81d904f5e65df63a2012fd22a78ed78ffa20`. A [PR #99](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/99) integrou reuniões, presença e expectativa nominal de visitantes. |
| Discovery do PR2 de Células (04/07) | 13.827 bytes | Planejamento encerrado na [PR #99](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/99). A [decisão de Células](../design/CELULAS-DECISOES-FINAIS.md#35--ocorrência--reunião-resolve-45--estrutural) e o [contrato de UX](../design/CONTRATO-UX-CELULAS-CENTRAL.md) preservam a reunião materializada e os fluxos de presença e expectativa nominal. A migration do PR2 e os testes `test_cell_meetings.py` e `test_celulas_pr2_models.py` registram autorização, dia da semana, estados de presença e unicidade com hora nula. O original é recuperável pelo blob Git `2b5bf51c1083e24bde05abf8ec8ebe4dd4e8deb8` em `a510ea9d`. |
| `.maestro`, `.maestri`, `.devin` | < 100 KB cada | configurações locais de ferramentas; não abertas |

### 4.4 Manter

`node_modules` da raiz (CLI do Supabase) e do `frontend/` são coisas diferentes
e estão em uso; não há duplicata. `backend/.venv` e `backend/.venv-runtime`,
`docs/historico`, `docs/sprints` (migrations citam o caminho), `docs/audits`,
`output/release/a3-final-local` (rastreado e citado), `dev.sh`, `test-local.sh`,
`.dev`, `_lixeira` do repositório e todo `deploy/first_transition*`.

Fora do repositório: `workspace/_lixeira` (489 MB, já é lixeira) e
`.claude/worktrees` (216 MB).

### 4.5 Segredos e dados soltos (só o caminho)

- `usuario-dev.md` (raiz, ignorado pelo Git): logins e senhas de DEV em texto.
  Não é lixo; o lugar é um gerenciador de senhas.
- `docs/ops/prod-ledger-20260926/prova_prod_resultado_20260926.csv`: rastreado
  e trata de PROD. Conteúdo não aberto.
- Padrão de senha em URL de banco em `dev.sh`, em arquivos de `deploy/` e em
  `.github/workflows/rls-integration.yml`: provavelmente senhas sintéticas de
  teste. Não verificado.
- Não foram achados dumps, `*.pem`, `*.key`, mídias nem `target_users*`.

## 5. Ambientes

### 5.1 Migrations na `main`

- 135 arquivos `.sql` em `backend/migrations/`; 5 pausadas pelo marcador
  `OPERATIONAL_AUTHORIZATION=BLOCKED` (d2a, d2b2, d2b2b3,
  `consent_evidence_store_lab` e e4b), que o `migrate.py` pula. Ativas: 130.
- Em `afdfb78d` eram 129. Depois dele entrou uma:
  `20261112_160000_celula_alerta_regras.sql` (RF-26).
- Ledger: `public.schema_migrations`.

### 5.2 Produção: último estado registrado (não é leitura viva)

| Dado | Valor registrado | Data do registro |
|---|---|---|
| Ledger | 78 aplicadas, 51 pendentes | leitura de 27/10 |
| Backend legado em execução | `07a3f4d` | 24/10 |
| Backend da janela | `afdfb78d`, executor `37c7d68d` | decisão de 12/11 |
| Painel | deployment Production do GitHub de 27/10, SHA `afdfb78d` | GitHub, lido em 12/11 |
| Gates | não verificado | — |

A janela A1–A10 aplica 51 migrations (43 transacionais e 8 `CONCURRENTLY`),
até `afdfb78d`. Depois dela o esperado é 129 no ledger e **1 pendente** para o
release seguinte (`celula_alerta_regras`), que precisa entrar antes do backend
novo.

### 5.3 GitHub (leitura viva de 12/11)

- Environments: `backend-production`, `production`, `Preview`.
- Secrets: nenhum cadastrado, nem no repositório nem em `backend-production`.
  Faltam os quatro do release: `BACKEND_DEPLOY_HOST`, `BACKEND_DEPLOY_USER`,
  `BACKEND_DEPLOY_SSH_KEY` e `BACKEND_DEPLOY_KNOWN_HOSTS`.
- `BACKEND_DEPLOY_SAFE_BASE_SHA` está em `c5f99b54`, de 02/10, anterior à
  segurança v3. O workflow exige v3, que entrou em `27250ef7`. O valor novo é
  decisão do dono.
- O workflow "Backend release (manual)" nunca rodou.
- `DEV_PIPELINE_ENABLED=false`.

### 5.4 Painel

Publicado à mão pela Vercel CLI no projeto `pastorai-frontend-prod`; a
publicação automática está desligada em `frontend/vercel.json`. Na janela, o
painel só vai ao ar se `frontend/openapi.json` do SHA do painel for igual ao
contrato do backend `afdfb78d`. A conferência registrada no runbook usou
`e9a8fc4a`; depois dele a `main` recebeu mudanças em `frontend/openapi.json`
(RF-26, #666). Para o SHA atual da `main` a igualdade está **não verificada**.

### 5.5 Gates no código

Todos fechados por padrão: `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED` e
`BROADCAST_ASYNC_ENABLED` em falso; `BREVO_SEND_MODE=off`;
`QUEUE_WORKER_DATABASE_MODE=legacy`; todos os `*_APPROVED_RELEASE_ID` em
`None`; listas por igreja vazias. `AgentConfig.ativo` tem padrão verdadeiro
na coluna. Valor em PROD: não verificado.

### 5.6 DEV

DEV remoto não existe (parado desde 27/09; sem environment no GitHub). O
ambiente local sintético sobe com `./dev.sh up` e aplica as migrations com
`migrate.py`. Se há stack local de pé: não verificado.

### 5.7 O que precisa de leitura viva em PROD para provar o pronto

| O que provar | Procedimento do runbook |
|---|---|
| Ledger de migrations | `migrate.py status` (§12.1, V1) |
| SHA e imagem dos contêineres | `docker compose ps` (§11) e verificação da A10 (§12.3) |
| Gates por nome e valor | V1 e foto dos gates (J3) |
| `AgentConfig` e Jev | J9 |
| SHA do painel e aliases | §12.5, V5 |
| Saúde | `/health` e `/ready` (§8); foto dos outros sistemas da VPS (§12.0) |
| `statement_timeout`, `rolbypassrls`, duplicidades | V1 |

## 6. Não verificado

- Todo estado vivo de PROD: ledger, SHA do backend e do painel, gates, saúde.
- Conteúdo das 27 branches duvidosas e dos arquivos diferentes das 12 parciais.
- Onde estão os ~19 GB citados no ROADMAP.
- Se os dois scripts de backup externo existem em `refs/archive`.
- Conteúdo de `output/codex`, `.devin`, `.maestro`, `.maestri` e do CSV de
  `docs/ops/prod-ledger-20260926/`.
- `npm audit` completo; causa do `e2e-critical` vermelho em `94622580`.
- Violações de CSP fora das rotas cobertas pelo E2E.
- Se cada ferramenta do catálogo do agente tem E2E próprio; RF-D3; PWA
  (há manifesto, não foi achado service worker).
- Igualdade do contrato da API entre `afdfb78d` e o painel no SHA atual.
- Stack local de DEV de pé.

## Apêndice: branches classificadas como integradas (191 nomes)

Classificação automática de 12/11. Antes de apagar qualquer uma, refazer a
prova daquele nome.

| Branch | Onde | PR | Prova |
|---|---|---|---|
| `chore/arquivar-e4b` | local+remota | #651 | PR mesclada, head igual |
| `chore/backend-ruff-ampliado` | local+remota | #648 | PR mesclada, head igual |
| `chore/backend-tipagem` | local+remota | #653 | PR mesclada, head igual |
| `chore/env-unico` | local+remota | #551 | PR mesclada, head igual |
| `chore/painel-formatador` | local+remota | #654 | PR mesclada, head igual |
| `chore/release-preflight-checks` | local+remota | #563 | PR mesclada, head igual |
| `chore/release-runbook` | local+remota | #565 | PR mesclada, head igual |
| `chore/ruff-backend` | local+remota | #554 | PR mesclada, head igual |
| `ci/backend-sem-apt` | local+remota | #553 | PR mesclada, head igual |
| `ci/backend-tests-paralelo` | local+remota | #649 | PR mesclada, head igual |
| `ci/rls-shards` | local+remota | #550 | PR mesclada, head igual |
| `ci/rls-timeout-40` | local+remota | #522 | PR mesclada, head igual |
| `claude/admiring-allen-5d3d70` | local | - | ancestral da main |
| `claude/busy-burnell-2364af` | local | - | ancestral da main |
| `claude/cool-lamport-a6430b` | local | - | ancestral da main |
| `claude/funny-benz-a5d25e` | local | - | ancestral da main |
| `claude/goofy-pascal-02dfc4` | local+remota | #659 | PR mesclada, head igual |
| `claude/happy-blackwell-68e3db` | local | - | ancestral da main |
| `claude/keen-darwin-5dc5cb` | local | - | ancestral da main |
| `claude/oauth-calendar-implementation-1` | remota | #222 | PR mesclada, head igual |
| `claude/strange-burnell-77c834` | local | - | ancestral da main |
| `claude/vigilant-elion-698f62` | local | - | ancestral da main |
| `claude/wonderful-rhodes-21b3e9` | local | - | ancestral da main |
| `codex/a9-created-network-main` | local+remota | #634 | ancestral da main |
| `codex/asaas-pr284-p1` | local | - | PR mesclada, head igual |
| `codex/auditoria-arquitetura-20261003` | local | - | ancestral da main |
| `codex/backend-performance-maintenance` | local+remota | #455 | PR mesclada, head igual |
| `codex/brand-favicon` | remota | #241 | PR mesclada, head igual |
| `codex/configuracao-dev-20261004` | local | - | ancestral da main |
| `codex/consolidar-performance-painel` | local+remota | #642 | PR mesclada, head igual |
| `codex/consolidar-preload-admin` | local+remota | #641 | PR mesclada, head igual |
| `codex/consolidation-fixture-isolation-20261109` | local+remota | #635 | ancestral da main |
| `codex/integracao-incremental-20261013` | local | - | ancestral da main |
| `codex/move-admin-nav-g12` | remota | #242 | PR mesclada, head igual |
| `codex/pr257-refresh` | local | - | PR mesclada, head igual |
| `codex/private-send-pg-fixture-20261110` | local+remota | #636 | ancestral da main |
| `codex/report-parser-field-boundaries` | local+remota | #638 | PR mesclada, head igual |
| `codex/roadmap-consolidacao-638` | local+remota | #639 | PR mesclada, head igual |
| `codex/runbook-postgrest-diagnostico` | local+remota | #637 | ancestral da main |
| `codex/snapshots-painel-seguros` | local+remota | #644 | PR mesclada, head igual |
| `codex/v1-closure-evidence` | local | #274 | PR mesclada, head igual |
| `codex/v1-encerrada` | local | #275 | PR mesclada, head igual |
| `codex/v1-production-audit-20260821` | local | #276 | PR mesclada, head igual |
| `codex/v1a-central-browser-20261109` | local+remota | #633 | ancestral da main |
| `codex/v1a-central-http-closure-20261109` | local+remota | #632 | ancestral da main |
| `codex/vps04a-network-guard` | local | - | ancestral da main |
| `codex/vps07a-diretorio-backup` | local+remota | #643 | PR mesclada, head igual |
| `docs/arquivo-documental-lote1-20261015` | local+remota | #481 | PR mesclada, head igual |
| `docs/asaas-formal-isolation-deploy` | local | #288 | PR mesclada, head igual |
| `docs/asaas-register-source-truth` | local | #289 | PR mesclada, head igual |
| `docs/checklist-aplicacao-prod-20261014` | local+remota | #476 | PR mesclada, head igual |
| `docs/consolidacao-release-20261027` | local | #597 | ancestral da main |
| `docs/decisoes-dono-20261112` | local+remota | #658 | PR mesclada, head igual |
| `docs/decisoes-janela-a10` | local+remota | #660 | ancestral da main |
| `docs/historico-planejamento` | local+remota | #650 | PR mesclada, head igual |
| `docs/kit-janela-primeira-virada` | remota | #668 | ancestral da main |
| `docs/mission5-broadcast-preflight` | local+remota | #291 | PR mesclada, head igual |
| `docs/orquestracao-roadmap-20261024` | local | - | ancestral da main |
| `docs/painel-na-janela` | local+remota | #661 | ancestral da main |
| `docs/plano-a7-a10-20261031` | local | #608 | ancestral da main |
| `docs/pr350-postmerge-reconciliation` | local | - | git cherry sem diferença |
| `docs/pr354-postmerge-reconciliation` | local+remota | #355 | PR mesclada, head igual |
| `docs/reconciliar-cutover-v2b` | local | #477 | PR mesclada, head igual |
| `docs/registro-aplicacao-prod-20261014` | local+remota | #475 | PR mesclada, head igual |
| `docs/release-decisao-4-migrations` | local+remota | #566 | PR mesclada, head igual |
| `docs/roadmap-ajuste-20261019` | local+remota | #523 | PR mesclada, head igual |
| `docs/roadmap-formacao-enviar-20261018` | local+remota | #508 | PR mesclada, head igual |
| `docs/roadmap-lote-23-10` | local+remota | #564 | PR mesclada, head igual |
| `docs/roadmap-revisao-20261022` | local+remota | #549 | PR mesclada, head igual |
| `docs/v1-timeout-aplicador` | local+remota | #664 | ancestral da main |
| `docs/v2b-verificacao-pos-cutover` | local | #478 | PR mesclada, head igual |
| `docs/vps-nova-20261021` | local+remota | #545 | PR mesclada, head igual |
| `feat/agenda-avisos-v1` | local+remota | #547 | PR mesclada, head igual |
| `feat/agenda-especialista-v1` | local+remota | #540 | PR mesclada, head igual |
| `feat/agenda-lembretes-janela` | local+remota | #560 | PR mesclada, head igual |
| `feat/audio-retencao-v1` | remota | #512 | PR mesclada, head igual |
| `feat/b3-inbox-papeis-fixos` | local+remota | #667 | PR mesclada, head igual |
| `feat/b4-optout-envio-humano` | local+remota | #665 | PR mesclada, head igual |
| `feat/cd-conclusao-v1` | remota | #500 | PR mesclada, head igual |
| `feat/cd-contrato-v1` | remota | #495 | PR mesclada, head igual |
| `feat/cd-matricula-v1` | remota | #498 | PR mesclada, head igual |
| `feat/cd-presenca-v1` | remota | #499 | PR mesclada, head igual |
| `feat/cd-turmas-v1` | remota | #497 | PR mesclada, head igual |
| `feat/cd-versoes-v1` | local+remota | #511 | PR mesclada, head igual |
| `feat/cd-whatsapp-v1` | remota | #501 | PR mesclada, head igual |
| `feat/cell-report-audio-transcription` | local+remota | #356 | PR mesclada, head igual |
| `feat/cell-report-transactional-staging-offline` | local+remota | #354 | PR mesclada, head igual |
| `feat/conhecimento-api-v1` | local+remota | #514 | PR mesclada, head igual |
| `feat/conhecimento-base-v1` | local+remota | #513 | PR mesclada, head igual |
| `feat/conhecimento-busca-v1` | local+remota | #516 | PR mesclada, head igual |
| `feat/conhecimento-excluir-v1` | local+remota | #524 | PR mesclada, head igual |
| `feat/conhecimento-painel-v1` | local+remota | #517 | PR mesclada, head igual |
| `feat/conhecimento-whatsapp-v1` | local+remota | #525 | PR mesclada, head igual |
| `feat/convites-isolamento-v1` | local+remota | #538 | PR mesclada, head igual |
| `feat/d21-duvida-responsavel-setor` | remota | #669 | PR mesclada, head igual |
| `feat/d2b2b3-master-governance-workflow` | local+remota | #320 | PR mesclada, head igual |
| `feat/d3-private-memory-contract-offline` | local | - | git cherry sem diferença |
| `feat/d3-turn-identity-offline` | local | - | ancestral do head de PR mesclada |
| `feat/ds-adocao-areas` | local+remota | #656 | PR mesclada, head igual |
| `feat/ds-adocao-componentes` | local+remota | #640 | PR mesclada, head igual |
| `feat/e4-consent-ledger-receipt-v1` | local | - | git cherry sem diferença |
| `feat/e4b-c2-boundary-v1` | local | - | git cherry sem diferença |
| `feat/e4b-c3-persistence-v1` | local | - | git cherry sem diferença |
| `feat/e4b-domain-c0-luna-v1` | local | - | git cherry sem diferença |
| `feat/e4b-domain-c0-nexo-v1` | local | - | git cherry sem diferença |
| `feat/e4b-domain-c0-v1` | local | - | git cherry sem diferença |
| `feat/enviar-abertura-v1` | remota | #505 | PR mesclada, head igual |
| `feat/enviar-avaliacao-v1` | remota | #503 | PR mesclada, head igual |
| `feat/enviar-contrato-v1` | remota | #502 | PR mesclada, head igual |
| `feat/enviar-evidencias-v1` | local+remota | #510 | PR mesclada, head igual |
| `feat/enviar-multiplicacao-v1` | remota | #506 | PR mesclada, head igual |
| `feat/enviar-nomeacao-v1` | remota | #504 | PR mesclada, head igual |
| `feat/enviar-tela-v1` | remota | #507 | PR mesclada, head igual |
| `feat/enviar-whatsapp-p2-v1` | local+remota | #521 | PR mesclada, head igual |
| `feat/enviar-whatsapp-v1` | local+remota | #520 | PR mesclada, head igual |
| `feat/equipe-sem-pessoa` | local+remota | #557 | PR mesclada, head igual |
| `feat/evento-visita-celula-v1` | local+remota | #487 | PR mesclada, head igual |
| `feat/evolution-agent-foundation` | local | #294 | PR mesclada, head igual |
| `feat/fonovisita-aceite-v1` | local+remota | #488 | PR mesclada, head igual |
| `feat/gestao-responsabilidades-v1` | local+remota | #539 | PR mesclada, head igual |
| `feat/hoje-responsabilidade-v1` | local+remota | #534 | PR mesclada, head igual |
| `feat/indicacao-celula-bairro-v1` | local+remota | #486 | PR mesclada, head igual |
| `feat/logout-servidor` | local+remota | #568 | PR mesclada, head igual |
| `feat/memoria-6b-v1` | local+remota | #546 | PR mesclada, head igual |
| `feat/memoria-exclusao-pessoa-v1` | local+remota | #518 | PR mesclada, head igual |
| `feat/memoria-exclusao-v1` | local+remota | #509 | PR mesclada, head igual |
| `feat/memoria-painel-reset-v1` | local+remota | #541 | PR mesclada, head igual |
| `feat/memoria-pedido-exclusao-v1` | local+remota | #535 | PR mesclada, head igual |
| `feat/memoria-reset-igreja` | local+remota | #561 | PR mesclada, head igual |
| `feat/memoria-resumo-v1` | local+remota | #526 | PR mesclada, head igual |
| `feat/memoria-retomada-v1` | local+remota | #531 | PR mesclada, head igual |
| `feat/migration-epoch-v3-decision-offline` | local | - | git cherry sem diferença |
| `feat/obs-outbox-webhooks` | local+remota | #562 | PR mesclada, head igual |
| `feat/observabilidade-pendencias-v1` | local+remota | #544 | PR mesclada, head igual |
| `feat/observabilidade-v1` | local+remota | #537 | PR mesclada, head igual |
| `feat/onboarding-acessos-v1` | local+remota | #536 | PR mesclada, head igual |
| `feat/oracao-audio-v1` | local+remota | #529 | PR mesclada, head igual |
| `feat/oracao-inbox-ui-v1` | local+remota | #519 | PR mesclada, head igual |
| `feat/oracao-sigilo-v1` | local+remota | #515 | PR mesclada, head igual |
| `feat/painel-csp-estilos` | local+remota | #657 | PR mesclada, head igual |
| `feat/painel-csp-nonce` | local+remota | #655 | PR mesclada, head igual |
| `feat/painel-csp-report-only` | local+remota | #647 | PR mesclada, head igual |
| `feat/painel-tipos-openapi` | local+remota | #652 | PR mesclada, head igual |
| `feat/pedido-oracao-whatsapp-v1` | local+remota | #484 | PR mesclada, head igual |
| `feat/pessoas-central-v1` | local+remota | #528 | PR mesclada, head igual |
| `feat/queue-worker-runtime-20261026` | local | - | ancestral da main |
| `feat/relatorio-atraso-lembrete-v1` | local+remota | #490 | PR mesclada, head igual |
| `feat/responsabilidade-vigencia-v1` | local+remota | #530 | PR mesclada, head igual |
| `feat/rf26-alertas-lider` | remota | #666 | ancestral da main |
| `feat/uv-conclusao-marcos-v1` | local+remota | #494 | PR mesclada, head igual |
| `feat/uv-presenca-v1` | local+remota | #493 | PR mesclada, head igual |
| `feat/uv-turmas-v1` | local+remota | #492 | PR mesclada, head igual |
| `feat/uv-whatsapp-v1` | local+remota | #496 | PR mesclada, head igual |
| `feat/ux-acessibilidade-v1` | local+remota | #527 | PR mesclada, head igual |
| `feat/ux-atendimento-v1` | local+remota | #532 | PR mesclada, head igual |
| `feat/vincular-pessoa-v1` | local+remota | #543 | PR mesclada, head igual |
| `feat/visita-vinculo-celula-v1` | local+remota | #489 | PR mesclada, head igual |
| `fix/asaas-formal-isolation` | local | #287 | PR mesclada, head igual |
| `fix/asaas-pre-network-gate-hardening` | local+remota | #284 | PR mesclada, head igual |
| `fix/ativacao-vinculo-lock` | local+remota | #556 | PR mesclada, head igual |
| `fix/audit-filelock` | local+remota | #570 | PR mesclada, head igual |
| `fix/auditoria-seguranca` | local+remota | #558 | PR mesclada, head igual |
| `fix/auth-email-links` | local+remota | #280 | PR mesclada, head igual |
| `fix/backend-data-igreja-paginacao` | local+remota | #645 | PR mesclada, head igual |
| `fix/calendar-connection-version-p2` | remota | #224 | PR mesclada, head igual |
| `fix/catalogo-clarify-pendente` | local+remota | #542 | PR mesclada, head igual |
| `fix/central-celulas-hoje` | remota | #257 | PR mesclada, head igual |
| `fix/certifi-20261020` | local+remota | #533 | PR mesclada, head igual |
| `fix/created-network-identity` | local | #616 | git cherry sem diferença |
| `fix/dev-transport-probe-timeout-classification` | local | - | git cherry sem diferença |
| `fix/first-transition-window-preflight` | local+remota | #615 | ancestral da main |
| `fix/janela-nginx-certbot` | remota | #662 | ancestral da main |
| `fix/janela-vps-compartilhada` | local+remota | #663 | ancestral da main |
| `fix/next-15-5-28` | local+remota | #552 | PR mesclada, head igual |
| `fix/painel-logout-api-harness` | local+remota | #646 | PR mesclada, head igual |
| `fix/reconcile-team-legacy-20261024` | local+remota | #572 | PR mesclada, head igual |
| `fix/rehearse-backup-excluidos-esperados` | local+remota | #671 | ancestral da main |
| `fix/rehearse-backup-restore-filtrado` | local+remota | #670 | ancestral da main |
| `main` | local+remota | - | ancestral da main |
| `ops/alerta-queda-e-logs` | local+remota | #569 | PR mesclada, head igual |
| `perf/frontend-navigation-under-1s` | remota | #239 | PR mesclada, head igual |
| `prep/integration-597-603-20261028` | local | - | ancestral da main |
| `prep/pr597-after603-20261028` | local | - | ancestral da main |
| `refactor/camadas-invertidas` | local+remota | #555 | PR mesclada, head igual |
| `test/a11y-axe` | local+remota | #559 | PR mesclada, head igual |
| `test/legacy-containment-rehearsal-20261024` | local+remota | #573 | PR mesclada, head igual |
| `test/legacy-cron-active-20261025` | local+remota | #576 | PR mesclada, head igual |
| `test/legacy-queue-active-ingestion-20261025` | local+remota | #575 | PR mesclada, head igual |
| `test/legacy-queue-entrypoint-20261024` | local+remota | #574 | PR mesclada, head igual |
| `test/queue-uow-identity-probe-20261026` | local | - | ancestral da main |
| `worktree-fix-migrations-hardening` | remota | #474 | PR mesclada, head igual |
