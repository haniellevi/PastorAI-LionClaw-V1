# Igreja 12 — roteiro único

Atualizado em 23/10/2026 sobre a `main` `4fd83232` (registra #517–#562). Esta é a única fonte ativa
de planejamento; substitui os planos de MVP e refatoração e seu acompanhamento.
O [PRD canônico](docs/Docs20260611_163530/PRD20260611_163530.md) conserva os
requisitos. As decisões de 15/10 prevalecem sobre os cortes antigos de escopo,
inclusive a entrada de Universidade da Vida e Capacitação Destino.

**Objetivo:** cuidar das pessoas e organizar a rotina G12 pelo WhatsApp oficial;
o painel serve à configuração, supervisão, exceções e ações sensíveis.
A V1 encerrou como piloto controlado; o produto completo ainda está em construção.

**Como ler:** **feito** = entrega delimitada implementada; **em andamento** =
entrega parcial; **falta** = trabalho ou decisão pendente. A coluna de produção
é separada: código e teste local não provam publicação ou ativação. Os testes e
publicações citados abaixo são registros anteriores, não repetidos nesta entrega.
Quando falta prova, usamos **não verificado**. Produção é o sistema em uso;
`main` é o código integrado; teste local exercita uma simulação no computador.

**Piloto:** Filadélfia, restrito a testadores internos. A decisão de 15/10 mantém
o agente ligado como está, sem ampliar o piloto. O registro informa resposta em
cerca de 28 s e monitor verde desde 14/10; o estado atual é **não verificado**.
O último backend registrado é `eb5a09b` (27/09); versão atual: **não verificado**.

## 1. Organização (histórico)

Roteiro único (#480) e arquivamento documental (lotes 1 e 2, #481/#482) feitos.
Checkout principal em `main` com estado anterior preservado em
`refs/archive/checkout-principal-20261016`. **Falta (dono):** decidir arquivos
locais restantes (`output/`, configurações locais e exemplos de ambiente) e
limpar worktrees antigas de forma recuperável. Nada de limpeza global, apagar
migrations ou branches remotas sem ordem própria.

## 2. Critério de pronto e saúde técnica

Atualização operacional de 24/10: a reconciliação excepcional de vínculos
Pessoa foi integrada pela #572 (`830decc1`), com checks aprovados; não foi
executada em produção. A fatia local de contenção pré-DDL passou em 54 testes
unitários e sete cenários Docker, com revisão Claude Opus e limpeza completa.
Cobre controlador/topologia sintéticos, não os entrypoints legados nem
recuperação após DDL real; `production_ready=false`. Integrada pela #573
(`c5c180ca`), com backend-tests, frontend-ci, e2e-critical e rls-integration
aprovados. A fatia seguinte passou localmente: ciclo de vida do entrypoint
real do queue-worker de `07a3f4d`, Redis descartável e dependências do legado;
88 testes (novo controlador + regressão da contenção) e sete verificações
físicas aprovados, limpeza sem sobras. Entrega na branch
`test/legacy-queue-entrypoint-20261024`; integração depende dos checks da PR.
Não inclui turno ativo, envio externo ou produção. Próxima prova: ingestão
ativa com barreira transacional em PostgreSQL sintético.
Ver [runbook atualizado e limites](docs/ops/RELEASE-LOTE-2026-10.md).

Em 25/10, a #574 (`94a4b9ec`) está aberta com todos os checks aprovados.
A etapa de ingestão ativa foi validada localmente na branch
`test/legacy-queue-active-ingestion-20261025`, baseada nesse commit.
Prova independente de ingestão ativa passou localmente em 25/10: espera no
lock observada, nenhuma mensagem antes da liberação, commit único, consentimento,
ACK e saída zero; limpeza concluída. A extensão independente também passou:
reenvios após reinício com e sem marcador Redis, contagens/não lidas
preservadas e sessão legada autenticada com leitura de outra igreja vazia
e INSERT recusado por RLS (`42501`), com escrita permitida na própria igreja.
O ensaio permanente passou em 130 testes (42 novos + 88 de regressão) e 20
verificações físicas, limpeza sem erros/sobras, revisão Claude incorporada
e verificação final pelo Codex. A barreira fica antes das escritas do domínio;
não prova turno completo do agente nem produção. Integração depende dos
checks do SHA publicado e da #574. Sem alterações em PROD.


**Um módulo só está concluído** quando tem, nesta ordem: (1) código na `main`
com os quatro checks e E2E do turno completo quando envolve o agente;
(2) release controlado para o piloto interno: migrations aplicadas com backup
prévio, runbook e gate aberto só para as igrejas/testadores listados, por
decisão nominal do dono; (3) aceite pastoral registrado com conversas/telas
reais desse piloto; (4) abertura ampliada por nova decisão nominal;
(5) monitoramento e procedimento de desligamento conhecidos.
"Feito (código)" abaixo cobre só o passo 1; os passos 2 e 4 exigem autorização
humana nominal e nunca são inferidos de merge ou teste verde.

**Estoque desligado:** UV, CD, Enviar, oração, células próximas, memória,
conhecimento e agenda pelo WhatsApp estão prontos só no passo 1. Antes de abrir
novas frentes grandes, priorizar o aceite das 20 conversas e um release em lote
planejado (migrations acumuladas, backup, reconciliação de duplicidades de
vínculo Pessoa e ordem de aplicação), para transformar estoque em uso real.

**Saúde técnica (metas medidas, uma fatia por PR, sem reescrita geral):**

| Meta | Medida em 22/10 (atualizada em 23/10) | Alvo |
|---|---|---|
| Tempo do `rls-integration` | 16–23 min serial em 22/10; 23/10: ~9–10 min com 4 partes paralelas (#550) e `backend-tests` ~4 min sem apt (#553), 0 skip | ≤ 8 min com divisão em partes paralelas, sem `skip` |
| Verificação estática do backend | ruff com regras de erro no CI (#554); tipagem ainda não | ruff só com regras de erro no CI; tipagem depois, por pasta |
| Arquivos de produção gigantes | `models.py` 5,0k, `queue_worker.py` 5,0k, `cell_report_audio_service.py` 4,1k, `routers/subscription.py` 3,7k, `notification_outbox.py` 3,5k, `agent/runtime.py` 2,3k linhas | arquivo tocado não cresce além de ~800 linhas; extrair uma responsabilidade coesa por PR quando a área for tocada |
| Camadas | acesso direto ao banco em 31/41 routers; inversões serviço→router eliminadas, com teste de camadas que cobre import relativo e alias (#555) | eliminar as 2 inversões; mover consulta para o serviço ao tocar a rota |
| Isolamento por igreja | helpers RLS novos e legados convivem | migrar um caminho por PR com teste PG de duas igrejas |
| Código pausado | ~5k linhas E4B/purpose consent no app | decidir: manter isolado ou arquivar em PR própria |
| Migrations | 17 nomes legados | checar padrão só nos arquivos novos; não renomear histórico |
| E2E do painel | Playwright usa API simulada | um E2E sintético navegador → FastAPI de um fluxo crítico |

## 3. Próximas funcionalidades

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Pedido de oração pelo WhatsApp (V4) | feito | Primeira versão de texto e pedido próprio integrada na main pela [PR #484](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/484), merge `2d408d92`; implementação e testes registrados. DESLIGADO por igreja e por trava de release; sem produção. Sigilo da coleta/histórico integrado pela #515; áudio protegido retido e excluído pela fila privada (#529) (backend/RLS, marcador, prévia e mídia; exclusão privada #509 e fila durável). Fatia 2 integrada pela #519: inbox mostra marcador acessível e orientação ao pastor, reconcilia a cada poll (texto e mídia protegidos somem no mesmo ciclo), mantém leitura autorizada pelo servidor, paginação/handoff/busca e mostra recibo de exclusão atualizável; sem backend/migration ou ativação. Decisões pastorais provisórias. Pendente: aceite pastoral (áudio já integrado pela #529). | não verificado em produção |
| Indicar células próximas | feito | Indicação guiada somente por bairro integrada na main pela [PR #486](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/486), merge `1caf4a36`; implementação e testes registrados. Só células ativas com divulgação autorizada, sem endereço ou dados do líder; sem cálculo de distância ou vínculo automático. DESLIGADO por igreja e por trava de release; sem produção. | não verificado em produção |
| Fluxo G12: ganhar, consolidar e célula | em andamento | Implementado na main, desligado e sem produção: evento real de visita de célula ligado à Pessoa ([PR #487](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/487), merge `05eb07b9`); aceite explícito da fonovisita com convite de 24h, troca após aceite e autoatribuição ([PR #488](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/488), merge `8d3d13f2`); primeira visita sugere vínculo com a célula, confirmado por pastor/admin ([PR #489](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/489), merge `b3fdd6fc`). G12 PR 5 integrada na [PR #490](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/490): percurso reunião → atraso → lembrete → baixa comprovado pelo agente e painel com provedor simulado; supressão terminal registrada só para igrejas da release/lista V1a; handoff e conexão indisponível são transitórios; nenhum gate aberto. Falta aceitar com o piloto o caminho completo. | Fluxo completo: não verificado |
| Aceite pastoral do atendimento | falta | Aprovar 20 conversas reais, incluindo visitante, oração, horário, opt-out e crise; corrigir os problemas encontrados. | não verificado |

## 4. Demais funcionalidades e qualidade

Modularizar a área quando ela for tocada, preservando os serviços existentes,
segundo as metas de saúde técnica da seção 2.
Sem reescrita geral, renomeio em massa ou refatoração como pré-requisito de tudo.

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Atendimento básico, consentimento, opt-out, passagem para humano e informações públicas | feito | Resposta de IA ao texto atual, contexto curto da conversa e consultas determinísticas registrados; isolamento e controles mantidos. | Piloto registrado; estado atual não verificado. |
| Ações por papel (S3) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por texto (V1a) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por áudio (V1b) | feito | Versão base na main, com testes sintéticos registrados. Decisão pastoral 15 (18/10, Raniel), integrada pela #512: mídia, transcrição e hashes sob consentimento v2 sem purga automática de 24h; saída por exclusão admin/aprovação de pedido da pessoa. Capturas v1/sem versão v2 preservam purga de até 24h. Via conversa preserva #509; pessoa/igreja seguem pendentes. Risco: maior volume retido; sem migration/backfill. Ver [política](docs/ops/EXCLUSAO-PRIVADA.md). Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Agenda V2 | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Consolidação V3 | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Presença própria (V4) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Expectativa de visitante (V4) | feito | Na main, com testes sintéticos registrados. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Simulador e prova integrada de visitante | feito | Transporte falso, fila Redis, worker, catálogo, autorização, banco com isolamento entre igrejas e acesso autenticado; testes locais/CI registrados (#462/#466). Não prova aceite online pelo navegador nem lembretes com gates fechados. | Simulador não se destina a PROD. |
| Ferramentas de desenvolvimento e testes | feito | Versões alinhadas ao CI; `test-local.sh` recusa alvo desconhecido (#464), com teste registrado. Corrige o falso sucesso sem executar testes. | Ferramenta de desenvolvimento. |
| Refatorações de visitante e leitura da resposta | feito | Validação de nome no domínio e leitura fora do worker, com regressão registrada (#465/#467). | não verificado |
| Universidade da Vida | feito (código) | Integrada na main em 18/10 (#491–#494, #496): turmas, calendário de oito aulas + Encontro, responsáveis, matrícula explícita, chamada com reposição e correção com histórico, marcos Encontro/batismo, conclusão humana com aptidão à CD e WhatsApp do responsável **desligado** (`UV_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations `20261017_210500`, `_220000`, `_230000` validadas só em PostgreSQL local sintético. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Capacitação Destino | feito (código) | Base integrada em 18/10 (#495, #497–#501): currículo versionado, turmas, matrícula, frequência/reposição, conclusão, progressão, equivalência e certificado revogável. Integrada em 19/10 (#511): equivalência entre versões da mesma família sem matrícula nova, origem rastreada, pré-requisitos/certificado e matrícula concluída fora do índice de andamento. CD não promove liderança; WhatsApp **desligado** (`CD_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations CD `20261018_010000`–`_040000` e `_090000` só em PostgreSQL local sintético. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Enviar e multiplicação | feito (código) | Integrado em 19/10 (#502–#507, #510, #520): contrato de aptidão, avaliação humana com eventos imutáveis, nomeação de líder e abertura de célula por solicitação com aprovação web de pastor/admin distinto do autor/candidato, tela Enviar, evidências oficiais UV/CD/Reencontro (Reencontro validado/revogado/revalidado com histórico; revogação bloqueia novas operações, sem promoção/destituição automática) e WhatsApp **desligado** (`ENVIAR_WHATSAPP_APPROVED_RELEASE_ID=None`, lista por igreja vazia): consulta mínima de pendências/evidências e solicitações após SIM literal, com idempotência e recibo após commit; avaliação, validação e aprovação ficam no painel autenticado. Pré-requisito de release: usuários da coordenação vinculados a uma Pessoa ativa (`app_users.pessoa_id`). Ajustes P2 do WhatsApp integrados pela #521 (`c7166cd1`): roteamento restrito ao catálogo, confirmação objetiva e aviso de paginação. Migrations `20261018_050000`–`_080000` e `_100000` só em PostgreSQL sintético; aplicar UV/CD/Enviar antes do deploy do backend; `_080000` valida FK em `celula_solicitacao` e pode falhar com linha legada inconsistente. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Memória privada durável | em andamento | Exclusão antes de memória nova. Integradas: fila durável de exclusão (#509), exclusão por pessoa e igreja/reset (#518), resumo privado por conversa (#526), retomada privada pelo comando exato "retomar conversa" (#531), pedido de exclusão com decisão web do admin (#535) e reset privado por pessoa no painel (#541). Contagens privadas agregadas no Hoje do admin (#546) e reset privado por igreja com confirmação pelo nome, SLA dos pedidos e quitação atômica dos pedidos pendentes cobertos pelo recibo (#561, migration nova, não aplicada). Tudo DESLIGADO (release None, lista vazia, flag false, teto 0). Pré-requisitos de ativação abertos: reconciliação de upload ambíguo, identidade explícita do worker, expiração de tombstones, dono/BYPASSRLS das funções no release. Ver [operação/limites](docs/ops/RESUMOS-PRIVADOS.md). | não verificado |
| Conhecimento oficial | em andamento | Base versionada e API editorial (#513/#514), busca autorizada (#516), painel editorial (#517), exclusão definitiva admin com confirmação (#524) e consulta pelo WhatsApp com fontes autorizadas (#525), DESLIGADA (`CONHECIMENTO_WHATSAPP_APPROVED_RELEASE_ID=None`, lista vazia), sem ingestão de conversas. Falta aceite pastoral e decisão 21 definitiva. | não verificado |
| Ferramentas e especialistas por área | em andamento | Ampliar rotinas pelo WhatsApp usando os mesmos serviços do painel; comportamento global versionado, dados e execução por igreja, credencial OpenAI própria da igreja. | não verificado |
| Pessoas, responsabilidades, Minha Célula, Central e Hoje | em andamento | Integradas: pendências da Central em Hoje (#528), responsabilidade por setor com vigência (#530), pendências por responsabilidade vigente (#534) e gestão web de responsabilidades (#539). Faltam planejamento, alertas e sinalizar contas da coordenação sem Pessoa ativa. | Cobertura completa: não verificado. |
| Triagem semântica Jev | em andamento | S1 implementada/testada com simulações; falta avaliar qualidade real, crise/humano e falsos opt-outs, contrato de tratamento de dados e autorização específica. Jev B/C/D continuam condicionados. | não verificado; não autoriza ativação. |
| Comunicados, assinatura/Asaas e e-mail/Brevo | em andamento | Bases implementadas; faltam aceite por finalidade, domínio/remetente e canários separados. Não envolver a igreja em cortesia em cobrança real. | não verificado |
| Onboarding da igreja, equipe, permissões e console | em andamento | Integradas: autorização de telas isolada por igreja (#536), reenvio de convite isolado (#538) e vínculo Pessoa ↔ usuário pelo admin, com auditoria e índice único (#543); ativação trava a igreja antes de Pessoa/usuário, eliminando a espera mútua com a gestão de equipe, com teste da corrida com convite que já traz Pessoa (#556). A tela de equipe sinaliza contas sem Pessoa vinculada (#557). Antes do release da #543: reconciliar manualmente duplicidades legadas de (igreja, pessoa). | Cobertura completa: não verificado. |
| Exclusão da pessoa, exclusão da igreja e reset | em andamento | Fatias integradas: #509, #518, pedido da pessoa com decisão admin (#535) e reset privado por pessoa (#541). Reset privado preserva cadastros/opt-out/consentimento e não autoriza reset cadastral. A trilha de vínculo Pessoa (#543) guarda UUIDs após exclusão aprovada; documentar no runbook de exclusão. Novos derivados acompanham sua implementação. | não verificado |
| UX, acessibilidade e desempenho do painel | em andamento | Integradas: teclado nas abas da Central (#527) e foco/anúncios/reflow no atendimento (#532). Faltam leitor de tela e celular reais, zoom e métricas autenticadas de campo. | Frontend publicado conforme registros; backend/telemetria e operação completa: não verificado. |
| Agenda completa e importação Google | em andamento | Operações locais pelo WhatsApp com SIM e recibo integradas (#540), desligadas. Lembretes pela outbox com gate próprio fechado (#547) e janela configurável por evento (2h/24h/72h/168h, públicos existentes, invalidação de pendentes; #560). Faltam G2b e credencial Google isolada por igreja antes de usar Google. | não verificado |
| Observabilidade de IA e operação | em andamento | Há logs/custos/filas, consumo de IA por igreja (#537) e idade/contagem agregada de mensagens e tarefas pendentes por igreja (#544, só admin, sem conteúdo); outbox e webhooks entram na medição, com DLQ separada e função de métricas restrita a admin ativo da igreja (#562, migration nova, não aplicada); alerta `stuck_flow` preparado e DESLIGADO até existir credencial dedicada de leitura. Faltam métricas por rota, retenção e metas de serviço. | não verificado |

**Segurança e decisões que permanecem abertas:**

- **em andamento:** auditoria de 03/10: redação de segredo em logs e escopo
  de igreja nas rotinas automáticas integrados (#558). Faltam MFA no console
  (depende de ligar no Clerk). Logout no servidor é candidato em
  `feat/logout-servidor`, ainda pendente de integração. Acessibilidade
  automática (axe WCAG 2.1 A/AA) nas telas principais integrada (#559); leitor
  de tela e celular reais: **não verificado**.
- **em andamento:** dependências corrigidas e triadas (#463/#469/#470; Next 15.5.28 em #552);
  auditorias das dependências de produção registradas como limpas em 10/10, mas permaneciam cinco
  alertas altos nas ferramentas ligados a `braces`. Situação atual **não verificado**.
- **falta:** decidir a divergência de acesso customizado ao inbox, opt-out no
  envio humano e expectativa de visitante em reunião passada (backlog técnico
  B3/B4). Preservar opt-out global e regras por canal até decisão; refatoração
  não muda comportamento silenciosamente.
- **falta:** reconferir os bugs históricos de classificação CSIM, primeiro
  consentimento e interpretação de relatório (B5/B7/B15 do MVP); não declarar
  resolvidos pela presença em auditoria. B1/B2/B3/B4/B14/B16 têm correções
  registradas, com disponibilidade atual em produção **não verificado**.
- **falta, quando houver necessidade concreta:** diagnóstico de configuração
  sem segredos, registro de ações sem relaxar autorizações e retirada individual
  de código/testes com proteção equivalente (B1/B2/B5 do backlog técnico).
  Medir ganho real por fatia na PR, sem percentuais inventados (B6).

**Trabalhos a preservar fora da main, conforme inventário de 15/10:** medições,
ferramentas de avaliação da interpretação e demonstração V1a de 13/10 em
`integracao-incremental-20261013`; auditoria em
`arquitetura-performance-seguranca-20261003`. Integração desse material e estado
dos arquivos não salvos: **não verificado**. Nenhuma cópia ou descarte nesta entrega.

**Decisões pastorais aprovadas em 18/10 (Raniel):**

- CD: 6 módulos de 10 aulas; todas as aulas com reposição; sequência linear, exceção só pela coordenação (admin/pastor); certificado após módulos obrigatórios e confirmação da coordenação; CD não promove a líder.
- UV: conclusão confirmada pelo responsável da turma ou admin/pastor; `lider_consol` pode criar turma e ver elegíveis (risco aceito).
- CD entre versões: conclusões de versão anterior valem na nova mediante equivalência da coordenação (implementado nesta fatia; produção não verificada).
- Enviar: avaliação exige UV, CD certificado e Reencontro como critérios distintos, com decisão humana final; aprova pastor/admin distinto do autor e do candidato; líderes atuais preservados como legado e revisados caso a caso; aprovar executa na hora com confirmação; evidência revogada barra novas nomeações e abre revisão, sem destituição automática.
- Tela Enviar: o líder não vê a avaliação (decisão/motivo) dos discípulos; vê só aptidão e pendências (opção padrão adotada; reversível).

## 5. No final: banco, latência, infraestrutura e release

| Entrega | Estado | O que falta |
|---|---|---|
| Banco Supabase e histórico de migrations | em andamento | Registro de 14/10: 78 aplicadas, backup e quatro pendentes de propósito (`20260711_023515`, `20260711_152127`, `20260925_183811`, `20260926_120446`). Estado atual **não verificado**. Decidir destino das pendentes e eventual consolidação do histórico sem impedir recriação local; Neon cancelada. |
| Reconciliação da virada da agenda V2b | falta | Visibilidade/inventário de usuários, gates e entrega dos 11 eventos EVT-7: **não verificado**. Conciliar com provedor/logs antes de decidir qualquer reenvio, que pode duplicar. |
| Resposta rápida (B17), capacidade e estabilidade | falta | Meta abaixo de 10 s adiada para esta etapa; medir região de servidor/banco e decidir infraestrutura. Investigar incidentes e falhas de prontidão da API: monitor verde registrado não prova causa resolvida. |
| DEV online isolado | em andamento | Preparação integrada e ensaio sintético registrados (#468/#471); ambiente disponível **não verificado**, registrado como ainda inexistente. Faltam executor exclusivo, região, teto de custo, recursos e aceite de login/Storage/navegador com duas igrejas. Local continua opcional para depuração/testes. |
| Publicação coordenada de backend/frontend e recuperação | em andamento | Preparação e ensaio integrados (#472/#473; merge de #473 confirmado no Git). Checagens só leitura do lote (#563, candidata) e runbook do lote com ensaio de restauração sintético em preparação. Falta pacote validado, versão viva anterior, compatibilidade de banco, contenção dos consumidores, janela e autorização nominal. Não prometer rollback universal. |
| Publicação automática no DEV e explícita em PROD | falta | Operar o caminho preparado e acertar a publicação do frontend com a API (B9/B13). Não alterar agora a automação atual ou gates. |
| Backup diário e restauração | em andamento | PROD agora é a VPS `srv2031318.hstgr.cloud` (a `srv1728329` será desativada); runbooks atualizados (#545). Em 21/10, leitura somente: backup diário com manifesto recente e monitor de produção instalado e saudável na VPS nova. Faltam restaurar em alvo isolado, aceitar a chave do host novo no backup externo (Windows) e incluir novas tabelas privadas. |
| Revisão antes de ampliar o piloto ou lançar | falta | Conferir autenticação/Clerk Production, configurações, gates e privacidade; canários Asaas/Brevo/broadcast/agente independentes. Governança pausada não é reativada automaticamente. |

**Preservar para esta etapa:** pré-checagem de backup em
`vps07a-source-20261005`, guarda de rede em `vps04a-network-guard`,
`lock_timeout` em `elastic-kirch-0de4a3` e scripts de backup externo cifrado
(`deploy/offsite-encrypt-backup.sh` e `deploy/pull-offsite-backup.sh`). Os scripts,
a avaliação Jev de 26/09 e as evidências de 04/10 estão somente na referência
local `refs/archive/checkout-principal-20261016`, nos caminhos originais;
preservação conferida, integração e funcionamento **não verificados** nesta
entrega. Os demais candidatos continuam sem nova conferência de recuperação;
não são correções declaradas entregues.

Governança E4B/D3/D6/D2A, atestações, catálogos e F1/F2 de governança permanecem
pausados; reavaliação somente por necessidade e decisão próprias. Isso não
adianta banco/infra nem impede desenvolver UV/CD após a etapa 3.

## Evidências e manutenção

A consolidação usa os dois planos agora históricos
([MVP histórico](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/MVP-PLANO-SIMPLIFICACAO.md) e
[refatoração histórica](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/refatoracao-modular-plano.md)), os 22 itens do
[acompanhamento arquivado](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/a812b9a6ef68b8757fda9e776e4f149cc2913722/docs/ops/acompanhamento/tarefas.json), a [cobertura do PRD](docs/ai/PRD-COVERAGE.md) e o Git da base.
O [registro V2b](docs/sprints/2026-10-15-v2b-verificacao-pos-cutover.md) mantém
explícitos os limites da consulta anterior; ele não declara o banco consistente.
Não houve consulta à produção nesta entrega. Os documentos históricos são
evidência, não instruções para retomar suas sequências ou manter seu painel.

Daqui para frente, atualizar somente este roteiro quando o estado/escopo mudar
e registrar entrega, testes e limites na descrição da PR. Requisitos e runbooks
continuam sendo referências técnicas; sem novo sprint, painel ou plano paralelo.
Integração exige `backend-tests`, `frontend-ci`, `e2e-critical` e
`rls-integration`; produção e efeitos reais exigem autorização nominal própria.
