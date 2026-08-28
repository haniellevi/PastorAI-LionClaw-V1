# Wiki do projeto Igreja 12

Snapshot documental desta candidata sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`. O `bootstrap-ledger` permanece
integrado pelo merge `3a5789c784017ab15a43e28c4270d25af8618359`. O preflight PROD histórico
permanece fixado na baseline auditada
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; a implementação D2B2b3A veio do
merge #320 `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`.

## Leitura de 30 segundos

A V1 do Igreja 12 está encerrada como piloto controlado. Autenticação, tenant,
Pessoas, Células, conversas, painéis, filas, integrações protegidas e a fundação
do agente formam uma base funcional.

O produto amplo ainda não está concluído. O objetivo aprovado é operar a rotina
da igreja principalmente pelo WhatsApp, com o painel reservado para
configuração, governança, exceções e ações sensíveis. Para chegar a esse marco,
faltam memória privada durável, conhecimento oficial por igreja, especialistas
de domínio, ações confirmadas, notificações unificadas, formação e validação
operacional ampla.

O canário ativo do agente passou tecnicamente e terminou com os gates fechados,
mas não passou como validação de qualidade: as respostas ficaram robóticas e
repetitivas. Por isso, o próximo trabalho é fortalecer a arquitetura antes de
qualquer expansão do canário.

## Princípios aprovados

- WhatsApp é a interface operacional principal.
- Web é apoio administrativo, de segurança e governança.
- Uma definição global e versionada de LangGraph atende todas as igrejas.
- Dados, memória, conhecimento, credenciais e execução são isolados por tenant.
- Conversas permanecem memória privada até exclusão solicitada e aprovada.
- Registros do sistema e documentos aprovados são as fontes oficiais.
- Conversa privada nunca vira conhecimento institucional automaticamente.
- O agente diz quando não sabe e encaminha a lacuna ao responsável do setor.
- Ações comuns podem terminar no WhatsApp após resumo e confirmação.
- Ações sensíveis terminam no painel autenticado.
- A primeira vertical é o relatório de célula completo pelo WhatsApp.
- OpenAI BYO é o provedor do PastorAI. OpenRouter não faz parte do produto.

## Estado geral

| Área | Estado | Próximo resultado necessário |
|---|---|---|
| V1 | `IMPLEMENTADO` | Preservar o encerramento e tratar a visão ampla como nova fase |
| Agente e Evolution | `PARCIAL / GATE OPERACIONAL` | Corrigir memória, conhecimento e qualidade antes de novo canário |
| Canário ativo | `PASS TÉCNICO / QUALIDADE INSUFICIENTE` | Avaliação conversacional humana após a nova fundação |
| LangGraph | `IMPLEMENTADO STATELESS / D2B1 INTEGRADA` | Persistência, memória e subgrafos permanecem posteriores |
| Consentimento | `PARCIAL / LEDGER-BOOTSTRAP INTEGRADO E COMPROVADO OFFLINE / PACOTE E VERIFICADOR CANDIDATOS SOMENTE OFFLINE / DECISÕES HUMANAS PENDENTES / NÃO APLICADO / D2B2B3A DRAFT-ONLY INTEGRADA E INATIVA` | Concluir testes e revisões da candidata e revisar sua integração; aprovações, catálogo, writers, Supabase e D2C permanecem bloqueados |
| Conhecimento por igreja | `AUSENTE` | Ingestão aprovada, ACL, busca e ferramentas de dados vivos |
| Relatório por WhatsApp | `PARCIAL` | Confirmar e gravar no relatório canônico |
| Central de Células | `PARCIAL FORTE` | Operação e notificações principais pelo WhatsApp |
| Agenda | `PARCIAL` | Consultas, confirmações e avisos pela plataforma unificada |
| Consolidação | `PARCIAL` | Máquina de estados e progresso durável |
| Universidade da Vida | `AUSENTE COMO MÓDULO` | PRD e implementação após Consolidação |
| Capacitação Destino | `AUSENTE COMO MÓDULO` | PRD e implementação após UV |
| Comercial | `GATES OPERACIONAIS` | Canários separados de broadcast, Brevo e Asaas |
| RNFs de campo | `NÃO VERIFICADO INTEGRALMENTE` | Acessibilidade, performance, retenção e recuperação contínua |

## O que está implementado

### Plataforma

- Superfícies separadas para operação, administração da igreja e console SaaS.
- Clerk, RBAC no backend e RLS PostgreSQL por igreja.
- Pessoas, papéis, Jornada G12 básica, Células, reuniões e relatórios web.
- Minha Célula, Central, solicitações, transferência e remoção de membros.
- Conversas, histórico, handoff, transferência humana e mídia privada.
- Painel de Hoje e fila central por responsabilidades existentes.
- Agenda, broadcast, billing e integrações com contenção e auditoria próprias.

### Fundação do agente

- instância Evolution identifica a igreja;
- telefone canônico identifica uma Pessoa ativa dentro do tenant;
- identidade duplicada, ferramenta desconhecida ou papel inconsistente falham
  fechados;
- papéis e capacidades são resolvidos no servidor;
- consentimento, opt-out, handoff e estado IA/humano são respeitados;
- credencial BYO válida não ativa o agente;
- `AgentConfig.ativo=false` impede resposta automática;
- `marcar_presenca` permanece desabilitada no runtime;
- falhas novas da fila possuem metadados seguros para investigação.

## O que está parcial

### Conversa e inteligência

O grafo atual é stateless. Ele não carrega histórico, não mantém campos já
respondidos e não consulta uma base oficial da igreja. O LLM é usado apenas
para refinar parte de uma resposta determinística. Esse desenho é um fator
tecnicamente compatível com a repetição vista no canário, mas a execução não
prova que ele seja a causa única.

Mensagens ficam registradas e áudio pode ser armazenado, mas não foi encontrada
transcrição operacional. O parser de relatório produz um evento de auditoria e
uma resposta, porém não grava o relatório oficial da reunião.

### Operação pastoral

Central, Minha Célula, Agenda e Consolidação possuem bases web úteis. Ainda não
formam uma experiência principal pelo WhatsApp. Notificações estão divididas
entre SLA, cron, serviços de evento, no-op de célula e broadcast, sem um ledger
geral de finalidade, consentimento, retry e escalonamento.

### Privacidade

A exclusão atual da conversa cobre conversa, mensagens e mídia. A nova memória
precisará incluir transcrição, resumo, checkpoint e vetores na mesma exclusão
aprovada. Consentimento também precisa ser separado por atendimento, cuidado
pastoral, tarefas operacionais e comunicados.

A D2B2a integrada adiciona somente o ledger append-only dessas quatro
finalidades, ORM, domínio e serviço interno sem caller. O runtime ainda não lê
ou escreve esse contrato, a migration não foi aplicada em Supabase, o
consentimento legado não é convertido por backfill e o opt-out global continua
prevalecendo.

A D2B2b1 integrada é código puro, sem migration ou caller. Ela exige chave
idempotente opaca gerada no servidor, aplica RBAC deny-first e recusa toda
tentativa de `concedido`. Essa contenção não escolhe texto, hipótese jurídica,
prova, retenção, política de menores ou semântica de eliminação e opt-out. Cada
finalidade depende de pacote aprovado pelo responsável humano e por validação
jurídica ou do encarregado antes de catálogo ou writer.

A D2B2b3A integra somente o preparo de rascunhos por igreja no Console
Master. O Master autenticado organiza fatos e campos permitidos, enquanto
tenant e ator são derivados no servidor. Seu e-mail não vira regra de acesso ou
configuração da igreja. A superfície não permite escolher hipótese jurídica,
decidir aplicação a menores, atestar, aprovar, assumir outro papel ou preencher
registros nominais. O status permanece `DRAFT_NOT_APPROVED` e nada chega ao
runtime.

## O que está ausente

- checkpointer durável conectado ao LangGraph;
- resumos privados e recuperação seletiva do histórico;
- base institucional com documentos aprovados, versão e audiência;
- busca híbrida e vetorial com RLS por igreja;
- propostas duráveis para confirmar ações no WhatsApp;
- outbox unificada para notificações proativas;
- onboarding guiado completo da igreja e de seus responsáveis;
- especialistas completos de Agenda, Consolidação, UV e CD;
- módulos operacionais de Universidade da Vida e Capacitação Destino;
- política completa de retenção e eliminação dos derivados de IA.

## Canário ativo do agente

O canário ativo é evidência operacional reconciliada nesta missão. Ele ainda
não constava como concluído no snapshot anterior `ad4a272`.

Foram enviadas somente as mensagens sintéticas `Olá`, `Aceito` e
`Quero conhecer a igreja`. O resultado técnico foi:

- três mensagens de entrada e três de saída;
- autoria da IA preservada;
- filas e dead-letter canônicas vazias;
- `AgentConfig.ativo=false` e `ALLOW_REAL_SENDS=false` restaurados ao final;
- Asaas, Brevo e broadcast permaneceram fechados.

Esses itens são relato do operador. A janela não deixou artefato versionado
capaz de provar de forma independente isolamento cross-tenant, ausência de tool
call ou ausência de mutação de domínio.

Esse `PASS` não é aprovação de qualidade. A avaliação humana identificou
linguagem robótica, pergunta repetida e falta de memória e conhecimento. O
registro operacional detalhado está em
[`POST-V1-MISSION-REGISTER.md`](ops/POST-V1-MISSION-REGISTER.md), atualizado na
mesma missão documental.

## Arquitetura de destino

```text
WhatsApp
  -> Evolution
  -> webhook e fila idempotente
  -> contexto confiável da igreja e da Pessoa
  -> política de identidade, capacidade e consentimento
  -> LangGraph global
       -> Atendimento
       -> Central de Células
       -> Agenda
       -> Consolidação
       -> Universidade da Vida (visão futura, fora da missão atual)
       -> Capacitação Destino (visão futura, fora da missão atual)
  -> política de resposta e proposta de ação
  -> outbox
  -> Evolution

Dados vivos -> ferramentas tipadas -> serviços de domínio
Documentos aprovados -> busca com tenant e audiência
Conversas -> memória privada, nunca publicação automática
```

O desenho detalhado está em
[`2026-08-27-whatsapp-first-tenant-agent-architecture.md`](decisions/2026-08-27-whatsapp-first-tenant-agent-architecture.md).
O contrato inativo do ledger está em
[`2026-08-28-d2b2-purpose-consent-ledger.md`](decisions/2026-08-28-d2b2-purpose-consent-ledger.md).
A fronteira deny-first D2B2b1 e as decisões humanas pendentes estão em
[`2026-08-28-d2b2b1-consent-security-boundary.md`](decisions/2026-08-28-d2b2b1-consent-security-boundary.md).
O contrato do template e a abertura draft-only do Console Master estão em
[`2026-08-28-d2b2b2-consent-decision-packet-contract.md`](decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md)
e
[`2026-08-28-d2b2b3-master-governance-drafts.md`](decisions/2026-08-28-d2b2b3-master-governance-drafts.md).

## Roteiro de conclusão

### D0, fonte de verdade

Reconciliar PRD, PRODUCT, SPEC, progresso, Wiki, memória de agentes, decisão de
arquitetura e registro do canário. Fase concluída na PR #310.

### D1, segurança

Revalidar capacidades, papéis, responsabilidades e endpoints sensíveis no SHA
atual. A auditoria confirmou quatro gaps de tenant, integridade e cobertura do
CI. A correção D1A foi integrada pela PR #311 e a migration foi aplicada em
DEV depois de preflight próprio. Produção não foi alterada.

### D2 a D5, fundação

Construir contexto confiável, consentimentos por finalidade, propostas de
ação, memória durável, exclusão integral, conhecimento oficial, onboarding e
outbox unificada. A PR #313 integrou a D2A como fronteira privada inativa: role
sem login, schema privado, helper de tenant e factory exclusiva ainda
desconectada do worker e do LangGraph. O candidato incorporado passou em 278
testes RLS no PostgreSQL 17 descartável e em 2.688 testes offline; isso não
prova execução em ambiente compartilhado. A integração não aplicou migration
compartilhada, não provisionou credencial, não conectou o runtime, não fez
deploy manual ou do backend, não promoveu a produção e não ativou o agente. O
único deploy associado foi o preview automático da PR, que não prova execução
do backend nem ambiente compartilhado.

A PR #315 integrou a D2B1 no `origin/main`
`84c5b71b415340868c1b0664e892b8b0350d91f4`. O contexto confiável v1 é
imutável e separado do estado mutável do grafo. A fronteira é montada pelo
servidor, revalidada antes do caminho compilado, do caminho direto e em cada
node, e preserva a mesma instância de `PrivilegeContext` até o executor de
tools. A entrada e o snapshot de Pessoa recusam chaves de autoridade, IDs,
telefone e campos não necessários ao turno.

O merge passou em 2.770 testes offline, com 278 desselecionados, e 278 testes
RLS, com zero skips. Cinco workflows da PR e cinco pós-merge ficaram verdes. O
LangGraph continua stateless, sem checkpointer persistente.

A continuação está na D2B2a integrada e inativa, ledger independente por
finalidade ainda sem caller. A D2B2b1 integrada acrescenta somente a fronteira
pura que gera chave opaca no servidor, aplica RBAC deny-first e nega toda
concessão. Não há reidratação por valor; retry entre processos exige futuro
recibo durável autenticado que prove a origem da chave. Antes de catálogo,
prova correlacionada, retenção ou writers, um
responsável humano e a função jurídica ou encarregado precisam aprovar o pacote
por finalidade. D2C continua bloqueada e reservada a propostas duráveis; D3
permanece a fatia de memória privada durável. A D2B1 não
adicionou migration, não acessou Supabase, não provisionou credencial, não
conectou a fronteira privada D2A, worker, fila ou checkpointer, não fez deploy
manual ou do backend, não promoveu a produção, não ativou o agente e não
executou canário. O preview automático da PR não prova execução do backend.

No histórico do `origin/main`, a PR #317 integrou a D2B2a no merge
`bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`, a partir do HEAD
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`. Ela cria
`public.consentimento_finalidade_evento`, ORM, domínio e serviço interno sem
caller. As quatro finalidades possuem estados `concedido|retirado`, fontes
`whatsapp_inbound|painel_autenticado`, `versao_termo`, idempotência por tenant
e sequência por stream protegida no banco. A tabela usa RLS forçada,
barreira restritiva GUC-only e ACL mínima.

Essa fundação não faz backfill, não expõe API, não conecta painel, WhatsApp,
worker, tool ou LangGraph e não foi aplicada em Supabase. Os cinco workflows da
PR #317 e os cinco pós-merge ficaram verdes. A PR gerou Preview e o merge gerou
deployment frontend Vercel automático classificado como Production; não houve
deploy manual ou do backend, ativação ou canário. Essa metadata prova o
deployment do frontend no ambiente Production da Vercel; não prova backend,
banco ou Supabase.

Textos e versões, hipótese jurídica, prova, tratamento de menores, retenção,
eliminação, transferência internacional, relação com opt-out e responsáveis
por direitos e incidentes continuam decisões humanas e jurídicas abertas. A
fronteira D2B2b1 não preenche essas decisões e nega concessões enquanto o
pacote não existir.

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, integrou a
D2B2b1 no merge `74951828f48994622a112d8e59eb978e5fb4f406`. O recorte focal
passou em 1.114 de 1.114, a suíte RLS em 288 de 288 e os cinco workflows da PR
e os cinco pós-merge ficaram verdes. A PR gerou Preview e o merge gerou
deployment frontend Vercel automático classificado como Production; não houve
deploy manual ou do backend, migration, Supabase, ativação ou canário. O
PostgreSQL descartável foi removido.

O template vazio D2B2b2 organiza um gate humano posterior e permanece
`TEMPLATE_ONLY / NOT_APPROVED`. Sua existência, teste ou merge não constituem
aprovação. O contrato está em
[`2026-08-28-d2b2b2-consent-decision-packet-contract.md`](decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md).

A PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, integrou a
D2B2b3A no merge `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`: migration
versionada, persistência, API e aba de governança no Console Master, todas
limitadas a rascunhos vinculados a uma igreja. A implementação usa revisão
otimista, auditoria sem payload e aviso permanente de conteúdo não aprovado. Os
cinco workflows da PR e os cinco pós-merge ficaram verdes. O merge gerou o
deployment automático Vercel frontend Production `6140373952`, com `SUCCESS`;
essa metadata prova apenas o frontend nesse ambiente. Esta missão não aplicou a
migration D2B2b3A; DEV e PROD confirmaram a ausência. A flag permanece `false`,
e não houve deploy manual ou do backend, wiring, ativação ou canário. Painel do
tenant, fluxo nominal de aprovação, catálogo, evidence store, writer, WhatsApp
e runtime continuam fechados.

No baseline `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD
somente leitura confirmou `DATABASE_URL` presente e
`M06_MIGRATION_DATABASE_URL` ausente. `current_user` e `session_user`
convergiram para a mesma identidade sanitizada; a role runtime possui
`NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, é owner de `public.igrejas` e
`public.app_users` e possui `SELECT` e `REFERENCES` efetivos nessas tabelas-pai.
A tabela alvo D2B2b3A, o validator e a própria `public.schema_migrations`
estavam ausentes. A flag `PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permaneceu
`false`. Esta missão não aplicou a migration D2B2b3A; DEV e PROD confirmaram a
ausência. A PR #321 integrou a reconciliação documental anterior no merge
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o deployment
automático Vercel frontend Production `6141449639`, com `SUCCESS`, em
2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar backend,
banco ou Supabase. O preflight VPS em si não executou deploy manual ou do
backend, migration, restart ou alteração da flag. A leitura comprova identidade,
ownership e ACL do caminho runtime atual, mas não o comportamento da tabela
futura sob `FORCE RLS`; o caminho de migration permanece bloqueado pela ausência
de `M06_MIGRATION_DATABASE_URL` e do ledger público.

### D6, primeira vertical

Entregar relatório de célula pelo WhatsApp com lembrete, texto ou áudio,
resumo corrigível, confirmação, gravação idempotente em `celula_reuniao` e
comprovante após commit.

### D7 e D8, produto pastoral amplo

Levar Central, Agenda, Consolidação e os fluxos de Enviar com contrato aprovado
ao WhatsApp. Universidade da Vida e Capacitação Destino estão excluídas da
missão atual; dependências que exijam esses módulos não serão improvisadas.

### D9, operação comercial

Executar canários independentes das integrações selecionadas, com consentimento,
observabilidade, responsáveis e rollback. A evolução do agente não abre Asaas,
Brevo ou broadcast.

## Dívidas que continuam visíveis

- política e execução de retenção dos logs do agente;
- revisão da quarentena de dead-letter na data registrada no runbook;
- restore periódico incluindo os novos schemas privados;
- avaliação manual com teclado, leitor de tela e zoom;
- métricas de performance em condições reais;
- owner operacional, substitutos e escalonamento por setor;
- o preflight runtime comprovou identidade, owner e ACL; o caminho
  `M06_MIGRATION_DATABASE_URL` e `public.schema_migrations` continuam ausentes
  em PROD, e o `FORCE RLS` da tabela futura não foi comprovado. O
  `bootstrap-ledger` foi integrado e comprovado somente offline, sem aplicação;
  o pacote e o verificador de reconciliação são candidatos somente offline,
  com decisões humanas pendentes e sem autorização operacional;
- completar depois o pacote humano e jurídico por finalidade: controlador e
  operadores reais, texto e versão, hipótese jurídica, prova, menores,
  retenção, eliminação, transferência internacional, opt-out, direitos,
  incidentes e aprovadores;
- depois do pacote, catálogo imutável, prova correlacionada, política
  versionada, RBAC e callers seguros;
- PRDs próprios para Formação e máquina de estados da Jornada.

## Fontes de verdade

Em divergência, use esta ordem:

1. ambiente vivo consultado e identificado no momento da ação;
2. Git, CI, código, migrations e testes do SHA exato;
3. PRD canônico e decisões aprovadas;
4. `docs/audits/2026-08-27-d1-security-scope-audit.md`,
   `docs/audits/2026-08-27-project-source-of-truth.md`, registro pós-V1 e
   runbooks;
5. Bootstrap, cobertura do PRD, esta Wiki, PRODUCT, SPEC e Plan Designer;
6. planos, sprints e auditorias substituídas ou históricas.

Nenhum item desta Wiki autoriza migration, deploy, flag, mensagem, cobrança ou
canário.

## Próximo gate único

A implementação foi desenvolvida e comprovada offline sobre a base versionada
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`. O código integrado pela PR #323
adiciona `bootstrap-ledger`, separado de
`harden-ledger`, com confirmação literal `BOOTSTRAP_LEDGER` e destino somente
em `M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17 ele cria, numa transação
`SERIALIZABLE`, apenas o ledger vazio `public.schema_migrations`, com colunas,
chave primária e defaults exatos, owner estável, RLS, policy deny e ACL
owner-only. Homônimo, default privilege ou grant de schema perigoso,
membership, ownership ou forma física divergente aborta com rollback; a
reaplicação exata e vazia termina sem mutação.

A implementação offline passou em 42/42 testes unitários, 87/87 em PostgreSQL 17-alpine
descartável em duas execuções independentes e 87/87 em Supabase PG17
17.6.1.159 descartável em duas execuções independentes. A revisão de segurança
resultou em `GO`. A suíte RLS completa, em execução serial limpa no PostgreSQL
17 descartável, passou em 326/326, com 3803 deselecionados e 2 warnings
preexistentes, em 162.77s. A suíte offline integral foi interrompida após 5
min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem falha
e não foi reclassificado. Os workflows Backend Tests da PR #323 e do pós-merge
concluíram com `SUCCESS`. O comando não descobre catálogo, não consulta ou altera
`supabase_migrations`, não reconcilia, não faz backfill e não aplica ou registra
migration. O ledger vazio mantém `status` e `apply` bloqueados até existir um
prefixo íntegro do catálogo, humanamente reconciliado, com no máximo uma migration pendente.

O `bootstrap-ledger` está integrado em `main`, mas continua não aplicado. A PR
#323, HEAD `74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada pelo
merge `3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`; seus cinco workflows e os cinco pós-merge concluíram
com `SUCCESS`. A Vercel registrou o Preview automático frontend `6143773477`,
com `SUCCESS`, em `2026-08-28T15:22:43Z`, e o Production automático frontend
`6143819601`, com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam
somente o frontend, sem provar backend, banco ou runtime. Não houve deploy
manual ou do backend, acesso aos bancos DEV ou PROD, bootstrap ou migration
compartilhada, restart ou alteração de credencial, flag, runtime, agente ou
canário. O preflight PROD e o deployment automático frontend da PR #321
permanecem evidências históricas separadas.

Sobre a base auditada `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, esta
candidata adiciona somente offline um pacote deny-state versionado e um
verificador stdlib separado do runner, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](decisions/2026-08-28-migration-history-reconciliation-contract.md).
O estado é `PACOTE E VERIFICADOR CANDIDATOS / SOMENTE OFFLINE / DECISÕES
HUMANAS PENDENTES / NÃO APLICADO`. O verificador não acessa banco, rede,
ambiente ou variáveis de ambiente, não executa SQL, DML ou escrita e não
infere migration aplicada. Os ledgers nativo e público permanecem independentes
e todo sucesso estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

A candidata passou `98/98` testes do verificador e `26/26` testes documentais.
O runner preservado passou `42/42` testes offline; `45` integrações foram
puladas por ausência deliberada de banco descartável.

Revisar as evidências focais e os pareceres independentes desta candidata e,
se todos permanecerem verdes, integrar a PR. Esse gate é exclusivamente
offline e não autoriza ambiente, comando do runner,
`bootstrap-ledger`, `harden-ledger`, `status` ou `apply`. Painel do tenant,
aprovações, catálogo, writer, migration D2B2b3A, flag, D2C, credencial, wiring,
deploy, restart, runtime, ativação e canário continuam bloqueados.
