# Igreja 12 — roteiro único

Atualizado em 18/10/2026 sobre a `main` `5460af62`. Esta é a única fonte ativa
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

## 1. Simplificação documental

| Entrega | Estado | O que falta |
|---|---|---|
| Roteiro único e regras de agentes coerentes | feito | [PR #480](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/480), merge `a812b9a6`; quatro checks pós-merge aprovados. Isso não conclui o produto. |
| Registrar entregas na descrição da PR | feito | Regra definida aqui; sem novos sprints ou atualização obrigatória do painel paralelo. |
| Arquivar documentação antiga sem perder histórico | em andamento | Lote 1 feito: [PR #481](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/481), merge `79dfa534`. Lote 2 em andamento: 87 documentos/registros de governança, missões e planos temáticos preservados em `archive/docs-2026-10-lote2` (`79dfa534`), com referências históricas em SHA fixo. Faltam revisão, quatro checks e integração do lote 2. Insumos de verificadores, runbooks duvidosos e demais conjuntos ficam preservados para decisão. |

## 2. Organização do checkout

| Entrega | Estado | O que falta |
|---|---|---|
| Limpeza recuperável de worktrees e branches locais | em andamento | Recuperação dos 37 worktrees conferida em 15/10, com 0 divergências; referências `refs/archive/worktrees-20261015/`. Isso é evidência registrada daquela conferência, não uma nova validação nesta entrega. Resta preservar trabalhos úteis e tratar os remanescentes. |
| Voltar o checkout principal à main | feito | Checkout em `main` `63a1b798` em 16/10. Estado anterior preservado na referência **local** `refs/archive/checkout-principal-20261016` (`6d75e085788fc9d0612217830010433b7fa45ce6`): 23 alterações/arquivos soltos conferidos, 0 divergências, e os dois commits locais preservados por ancestralidade. `chore/neon-dev-setup` mantida. Configuração local e `output/` permanecem no disco para decisão; `output/` não foi lido nem arquivado. Outros worktrees intactos. |
| Decidir o destino dos arquivos locais restantes | falta | Revisão do proprietário: dois exemplos de ambiente alterados somente na referência local acima; `.claude/settings.json` arquivado e mantido no disco; 18 arquivos em `output/` fora do arquivo Git e sem leitura. Artefatos locais de ferramentas também permanecem no disco, sem limpeza autorizada. |

Nenhum trabalho não salvo pode ser preservado apenas criando uma referência ao
HEAD: é preciso guardar também as alterações e arquivos novos, conferir a
recuperação e excluir segredos/dados reais de qualquer snapshot Git. Worktrees
Codex são arquivadas pela ferramenta responsável. Nada de limpeza global ou de
branches remotas sem ordem própria. Não apagar migrations para organizar pastas.

## 3. Próximas funcionalidades

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Pedido de oração pelo WhatsApp (V4) | feito | Primeira versão de texto e pedido próprio integrada na main pela [PR #484](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/484), merge `2d408d92`; implementação e testes registrados. DESLIGADO por igreja e por trava de release; sem produção. Sigilo da coleta/histórico no inbox em revisão (fatia 1: backend/RLS, marcador, prévia e mídia; integração com exclusão privada #509 e fila durável, decisões pastorais provisórias). Áudio e aceite pastoral pendentes. | não verificado em produção |
| Indicar células próximas | feito | Indicação guiada somente por bairro integrada na main pela [PR #486](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/486), merge `1caf4a36`; implementação e testes registrados. Só células ativas com divulgação autorizada, sem endereço ou dados do líder; sem cálculo de distância ou vínculo automático. DESLIGADO por igreja e por trava de release; sem produção. | não verificado em produção |
| Fluxo G12: ganhar, consolidar e célula | em andamento | Implementado na main, desligado e sem produção: evento real de visita de célula ligado à Pessoa ([PR #487](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/487), merge `05eb07b9`); aceite explícito da fonovisita com convite de 24h, troca após aceite e autoatribuição ([PR #488](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/488), merge `8d3d13f2`); primeira visita sugere vínculo com a célula, confirmado por pastor/admin ([PR #489](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/489), merge `b3fdd6fc`). G12 PR 5 em andamento na [PR #490](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/490): percurso reunião → atraso → lembrete → baixa comprovado pelo agente e painel com provedor simulado; supressão terminal registrada só para igrejas da release/lista V1a; handoff e conexão indisponível são transitórios; nenhum gate aberto. Falta aceitar com o piloto o caminho completo. | Fluxo completo: não verificado |
| Aceite pastoral do atendimento | falta | Aprovar 20 conversas reais, incluindo visitante, oração, horário, opt-out e crise; corrigir os problemas encontrados. | não verificado |

## 4. Demais funcionalidades e qualidade

Modularizar a área quando ela for tocada, preservando os serviços existentes.
Sem reescrita geral, renomeio em massa ou refatoração como pré-requisito de tudo.

| Entrega | Estado | Implementação / teste | Produção |
|---|---|---|---|
| Atendimento básico, consentimento, opt-out, passagem para humano e informações públicas | feito | Resposta de IA ao texto atual, contexto curto da conversa e consultas determinísticas registrados; isolamento e controles mantidos. | Piloto registrado; estado atual não verificado. |
| Ações por papel (S3) | feito | Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por texto (V1a) | feito | Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Relatório por áudio (V1b) | feito | Versão base na main, com testes sintéticos registrados. Decisão pastoral 15 (18/10, Raniel), integrada pela #512: mídia, transcrição e hashes sob consentimento v2 sem purga automática de 24h; saída por exclusão admin/aprovação de pedido da pessoa. Capturas v1/sem versão v2 preservam purga de até 24h. Via conversa preserva #509; pessoa/igreja seguem pendentes. Risco: maior volume retido; sem migration/backfill. Ver [política](docs/ops/EXCLUSAO-PRIVADA.md). Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Agenda V2 | feito | Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Consolidação V3 | feito | Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Presença própria (V4) | feito | Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Expectativa de visitante (V4) | feito | Falta definir o canal para a pessoa pedir exclusão (o aviso v2 promete esse caminho) e a exclusão por pessoa/igreja antes de qualquer ativação. A fatia não conclui o módulo; ativação não comprovada. | não verificado |
| Simulador e prova integrada de visitante | feito | Transporte falso, fila Redis, worker, catálogo, autorização, banco com isolamento entre igrejas e acesso autenticado; testes locais/CI registrados (#462/#466). Não prova aceite online pelo navegador nem lembretes com gates fechados. | Simulador não se destina a PROD. |
| Ferramentas de desenvolvimento e testes | feito | Versões alinhadas ao CI; `test-local.sh` recusa alvo desconhecido (#464), com teste registrado. Corrige o falso sucesso sem executar testes. | Ferramenta de desenvolvimento. |
| Refatorações de visitante e leitura da resposta | feito | Validação de nome no domínio e leitura fora do worker, com regressão registrada (#465/#467). | não verificado |
| Universidade da Vida | feito (código) | Integrada na main em 18/10 (#491–#494, #496): turmas, calendário de oito aulas + Encontro, responsáveis, matrícula explícita, chamada com reposição e correção com histórico, marcos Encontro/batismo, conclusão humana com aptidão à CD e WhatsApp do responsável **desligado** (`UV_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations `20261017_210500`, `_220000`, `_230000` validadas só em PostgreSQL local sintético. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Capacitação Destino | feito (código) | Base integrada em 18/10 (#495, #497–#501): currículo versionado, turmas, matrícula, frequência/reposição, conclusão, progressão, equivalência e certificado revogável. Candidata desta fatia: equivalência entre versões da mesma família sem matrícula nova, origem rastreada, pré-requisitos/certificado e matrícula concluída fora do índice de andamento. CD não promove liderança; WhatsApp **desligado** (`CD_WHATSAPP_APPROVED_RELEASE_ID=None`). Migrations CD `20261018_010000`–`_040000` e `_090000` só em PostgreSQL local sintético. | Aplicação das migrations: **não verificado**; ativação não autorizada. |
| Enviar e multiplicação | em andamento | Contrato, avaliação, operações e tela integrados (#502–#507). Fatia 3 candidata: evidências oficiais UV/CD/Reencontro, referências na avaliação, Reencontro validado/revogado/revalidado por pastor/admin distinto da Pessoa, com histórico preservado e pendências reais; revogação bloqueia novas operações, sem promoção/destituição automática. Migration `20261018_100000` só em PostgreSQL sintético; aplicar UV/CD/Enviar antes do deploy do backend. Fatia 8: WhatsApp integrado ao fluxo existente e **desligado** (`ENVIAR_WHATSAPP_APPROVED_RELEASE_ID=None`, lista por igreja vazia); catálogo/roteador determinísticos, consulta mínima de pendências/evidências e solicitações de nomeação/abertura após SIM literal, com idempotência e recibo após commit. Avaliação, validação de evidências e aprovação continuam no painel autenticado, por pastor/admin distinto do autor/candidato. Sem migration nova ou ativação; integração desta fatia à main depende da PR. | Aplicação das migrations: **não verificado**. |
| Memória privada durável | falta | Exclusão completa antecede memória nova: fatia 1 integrada na main em 19/10 (#509), com fila durável, remoção de logs derivados e barreiras de geração/replay/upload/envio (recibo pendente durante transporte). Resumos e retomada privados ainda faltam. | não verificado |
| Conhecimento oficial | em andamento | Base versionada e API editorial (#513/#514); busca lexical autenticada e trechos transacionais (#516). Painel web candidato (#517), reposicionado sobre a main: lista/histórico paginados, retomada do envio de rascunho sem expor seu texto, revisão opcional, aprovação/publicação admin, substituição, revogação, públicos, vigência, histórico e busca com trecho; capacidades revalidadas no servidor e leitura isolada por igreja. Testes sintéticos de frontend e PG; decisões pastorais continuam provisórias. Sem WhatsApp ou ingestão de conversas; falta integração e aceite pastoral. | não verificado |
| Ferramentas e especialistas por área | em andamento | Ampliar rotinas pelo WhatsApp usando os mesmos serviços do painel; comportamento global versionado, dados e execução por igreja, credencial OpenAI própria da igreja. | não verificado |
| Pessoas, responsabilidades, Minha Célula, Central e Hoje | em andamento | Base existente; faltam responsabilidades temporais/por setor, planejamento, alertas e composição das pendências. | Cobertura completa: não verificado. |
| Triagem semântica Jev | em andamento | S1 implementada/testada com simulações; falta avaliar qualidade real, crise/humano e falsos opt-outs, contrato de tratamento de dados e autorização específica. Jev B/C/D continuam condicionados. | não verificado; não autoriza ativação. |
| Comunicados, assinatura/Asaas e e-mail/Brevo | em andamento | Bases implementadas; faltam aceite por finalidade, domínio/remetente e canários separados. Não envolver a igreja em cortesia em cobrança real. | não verificado |
| Onboarding da igreja, equipe, permissões e console | em andamento | Há telas/serviços; faltam fechamento do fluxo de responsáveis/aprovações e validação das lacunas de acesso. Assistente no painel respeita igreja/papel. | Cobertura completa: não verificado. |
| Exclusão da pessoa, exclusão da igreja e reset | em andamento | Fatia 1 em revisão: conversa, mensagens, mídias e V1b com exclusão transacional, limpeza externa durável e recibo por camada (camadas ausentes = zero). Pessoa, igreja/reset e inclusão de novos derivados ficam para as fatias seguintes. | não verificado |
| UX, acessibilidade e desempenho do painel | em andamento | Hoje/atendimento e UX v3 implementados; proteção do microfone ao trocar de conversa em candidato. Faltam teclado, leitor de tela, zoom, mobile e métricas autenticadas de campo; integração atual desse candidato: não verificado. | Frontend publicado conforme registros; backend/telemetria e operação completa: não verificado. |
| Agenda completa e importação Google | em andamento | Base de cadastro/consulta existe; falta fechar o especialista, entrega de avisos e integração com credencial isolada por igreja antes de usar Google. | não verificado |
| Observabilidade de IA e operação | em andamento | Há logs/custos/filas; faltam métricas por igreja/rota, retenção, metas de serviço e alertas de fluxos presos. | não verificado |

**Segurança e decisões que permanecem abertas:**

- **falta:** tratar os achados da auditoria de 03/10: segredo em URL de log,
  escopo de igreja em cron/SLA, MFA no console e logout no servidor. A auditoria
  está fora da main; correções e reprodução atual: **não verificado**.
- **em andamento:** dependências corrigidas e triadas (#463/#469/#470);
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
| Publicação coordenada de backend/frontend e recuperação | em andamento | Preparação e ensaio integrados (#472/#473; merge de #473 confirmado no Git). Falta pacote validado, versão viva anterior, compatibilidade de banco, contenção dos consumidores, janela e autorização nominal. Não prometer rollback universal. |
| Publicação automática no DEV e explícita em PROD | falta | Operar o caminho preparado e acertar a publicação do frontend com a API (B9/B13). Não alterar agora a automação atual ou gates. |
| Backup diário e restauração | falta | Verificar rotina, restaurar em alvo isolado e incluir novas tabelas privadas. Pré-checagens de rede/backup, Compose e recuperação ainda exigem aceite no alvo. |
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
