# Estado atual e gaps

## 1. Como ler este documento

Esta matriz compara os textos fornecidos e documentos históricos com o SHA atual. Ela não presume que a produção esteja idêntica ao código.

Classes:

- `IMPLEMENTADO`: encontrado no código atual;
- `PARCIAL`: base útil, com lacuna concreta;
- `DIVERGENTE`: comportamento atual conflita com a intenção mais recente;
- `AUSENTE`: não encontrado;
- `NÃO COMPROVADO`: exige runtime, dado ou ambiente que não foi medido;
- `RELATADO`: problema informado pelo usuário, ainda sem medição autenticada.

## 2. Evoluções que não podem regredir

| Evolução atual | Evidência principal |
|---|---|
| rótulo `Fora da igreja`, ordenado no fim | `ContatosScreen.tsx`, `contacts.py` |
| agente pausado para CSIM | `agent/runtime.py` |
| CSIM no fim das conversas | `conversations.py` e teste dedicado |
| detalhe da pessoa antes de editar | `ContatosScreen.tsx` |
| Pessoas e configuração fora do app operacional | `navigation.ts`, `/gestao/page.tsx` |
| checklist de configuração inicial | `SetupChecklistScreen.tsx`, `setup.py` |
| app, admin e painel master separados | middleware, shells e navegação |
| matriz papel por tela | `permissions.ts`, `roles.py`, tela Permissões |
| conversa total para pastor/admin e atribuída para responsáveis | `conversations.py` |
| Agenda com Semana, Mês, Ano e A confirmar | `CalendarioScreen.tsx` |
| importação Google e confirmação manual | `calendar.py`, `CalendarConnectCard.tsx` |
| audiência e intenção de notificação por evento | `ConfirmEventModal.tsx`, `events.py` |
| Minha Célula para discípulo e líder | `components/minha-celula/` |
| Central com dashboard, gestão, solicitações, avisos e materiais | `components/central-celula/` |
| planejamento e relatório real de reunião | `PlanMeetingModal.tsx`, `MeetingReportForm.tsx` |
| solicitações com aprovar, rejeitar e pedir ajuste | `cell_requests.py`, `RequestDecisionPanel.tsx` |
| multiplicação transacional no domínio | `cell_multiplication_service.py` |
| design system Diamante Lapidado | `design-tokens.css`, `globals.css`, `ds.css` |
| reduced motion e padrões de tabs/dialog | CSS global e primitives `ds` |
| primeiro contato WhatsApp idempotente | `queue_worker.py` |
| orquestrador LangGraph por igreja | `agent/graph.py`, `AgentConfig` |
| opt-out e broadcast com ledger | `consent.py`, `broadcast.py`, migrations |

## 3. Matriz global

### 3.1 Shell, navegação e configuração

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| três superfícies | `IMPLEMENTADO` | smoke por host em produção não medido | P1 de validação |
| navegação operacional e administrativa | `IMPLEMENTADO` | nomenclaturas ainda podem confundir acesso e discipulado | P2 |
| configuração inicial | `IMPLEMENTADO` | validar primeiro dia completo com igreja vazia | P1 |
| identidade por igreja | `IMPLEMENTADO/PARCIAL` | limites de personalização e contraste precisam permanecer controlados | P2 |
| assinatura somente dono | `IMPLEMENTADO no gate atual` | papel owner não governa todos os outros controles sensíveis | P0 de decisão |

### 3.2 Pessoas, acesso e permissões

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| CSIM / Fora da igreja | `IMPLEMENTADO` | classificação automática ainda é frágil | P1 |
| lista e detalhe administrativos | `IMPLEMENTADO na UI` | endpoints gerais aceitam qualquer autenticado em trechos críticos | P0 |
| criação de contato | `IMPLEMENTADO` | autorização ampla e dados pastorais ainda incompletos | P0/P1 |
| vínculo com célula | `DIVERGENTE` | primeira vinculação pode ser feita por qualquer autenticado | P0 |
| papéis base | `IMPLEMENTADO` | enum fixo não atende responsabilidades customizadas | P1 |
| matriz papel por tela | `IMPLEMENTADO` | não substitui capacidade e escopo no backend | P0 |
| CRUD de cargos ministeriais | `AUSENTE` | papéis de segurança e responsabilidades estão misturados | P1 |
| convite e revogação | `IMPLEMENTADO` | convite exige célula e bloqueia Pessoa já vinculada | P0 |
| liderança e acesso sincronizados | `DIVERGENTE` | é possível criar líder sem AppUser e atribuir papel sem liderança real | P0 |
| pastor principal e organograma | `AUSENTE` | `dono_id` não representa liderança ministerial | P1 |

### 3.3 Dashboard

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| overview do líder escopado à célula | `IMPLEMENTADO` | mecanismo não foi reaproveitado em toda a experiência | P0 |
| Painel de Hoje por responsabilidade | `PARCIAL` | frontend distingue principalmente líder e não líder | P1 |
| fila pastoral | `DIVERGENTE` | filtra tipo, não pessoa, célula ou atribuição | P0 |
| estatísticas de contatos e CSIM | `PARCIAL` | backend possui dados, UI e escopos por persona estão incompletos | P1 |
| membro com agenda e avisos | `PARCIAL` | visão ainda é genérica e pouco composta | P1 |
| múltiplas responsabilidades | `AUSENTE como composição` | união de menu não produz dashboard contextual | P1 |

### 3.4 Conversas

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| pastor/admin vê tudo | `IMPLEMENTADO` | runtime autenticado por papel não medido | P1 de validação |
| responsável vê atribuídas | `IMPLEMENTADO` | matriz efetiva do destinatário não é usada na transferência | P0/P1 |
| assumir, devolver à IA e transferir | `IMPLEMENTADO no núcleo` | política final e estados por papel precisam smoke | P1 |
| CSIM sem autoengajamento | `IMPLEMENTADO` | manter reversão humana auditada | P1 |
| SLA e fila humana | `PARCIAL` | precisa composição com responsabilidade no dashboard | P1 |

### 3.5 Agenda

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| Semana, Mês, Ano | `IMPLEMENTADO` | abre em Mês; escolha de abertura exige validação | P2 |
| A confirmar | `IMPLEMENTADO` | estado pendente deve usar ícone e texto em todas as visões | P1 |
| criar e editar evento | `PARCIAL` | faltam local, público operacional e recorrência completa no formulário | P1 |
| Google Calendar | `PARCIAL forte` | importação é unidirecional; push e conflito não existem | P2 |
| audiência e mensagem | `IMPLEMENTADO como intenção` | nada é enviado agora | P0 de expectativa |
| dispatcher real | `AUSENTE` | sem envio futuro comprovado | P0 antes de prometer |
| Planejamento | `AUSENTE` | validar se o onboarding semanal ainda é requisito | P1 de produto |
| alinhamento visual | `RELATADO` | sem smoke autenticado, não foi medido | P1 de validação |

### 3.6 Minha Célula

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| visão do discípulo | `IMPLEMENTADO` | falta hero com líder, grupo, localização e participantes | P1 |
| presença e visitante | `IMPLEMENTADO/PARCIAL` | visitante não conclui telefone e decisão até Pessoas/Ganhar | P0/P1 |
| visão do líder | `IMPLEMENTADO/PARCIAL` | pilha longa, poucos KPIs e contexto resolvido por várias chamadas | P1 |
| planejar reunião | `PARCIAL` | somente data, hora e tema | P1 |
| relatar reunião | `IMPLEMENTADO forte` | falta progresso, recuperação e alerta claro de atraso | P1 |
| avisos | `PARCIAL` | sem vigência, agendamento, edição ou visto | P2 |
| materiais | `PARCIAL` | URL e inativação, sem versão, busca, tags ou upload seguro | P2 |
| adicionar participante | `PARCIAL` | domínio permite com guards, visão do líder é leitura | P1 |
| transferência e saída | `PARCIAL` | tipos existem, origem completa na UI não foi encontrada | P1 |
| alinhamento visual | `RELATADO` | sem smoke autenticado, não foi medido | P1 de validação |

### 3.7 Central de Células

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| dashboard e filas | `IMPLEMENTADO/PARCIAL` | faltam KPIs agregados validados | P1 |
| criar e editar célula | `PARCIAL forte` | frontend não usa todos os campos já aceitos pelo backend | P1 rápido |
| saúde de dez reuniões | `IMPLEMENTADO` | faltam busca e ordenação escolhida | P2 |
| solicitações | `IMPLEMENTADO` | aprovação sensível não tem confirmação de impacto | P0/P1 |
| multiplicação | `PARCIAL forte` | UI não coleta todo o payload aceito pelo backend | P1 |
| nova liderança | `AUSENTE` | precisa sincronizar Pessoa, AppUser, papel e célula | P0/P1 |
| aviso no WhatsApp | `AUSENTE` | serviço atual é no-op, intenção não é entrega | P0 de linguagem |

### 3.8 Jornada G12

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| Ganhar | `IMPLEMENTADO/PARCIAL` | dados e ações não são escopados por responsabilidade | P0 |
| Consolidar | `IMPLEMENTADO/PARCIAL` | acompanhamento de discípulos e responsáveis precisa escopo explícito | P0/P1 |
| Discipular | `PARCIAL` | árvore básica existe, privacidade e experiência ainda precisam projeto | P1 |
| Universidade da Vida | `AUSENTE como módulo completo` | visão de aluno, líder e direção não implementada | P2 |
| Capacitação Destino | `AUSENTE como módulo completo` | mesmas lacunas da formação | P2 |
| Enviar | `PARCIAL/AUSENTE` | conteúdo educativo e visão operacional ainda não fechados | P2 |
| caminho vivo | `PARCIAL visual` | stepper existe, falta integração consistente ao progresso real | P1 |

### 3.9 Agente e WhatsApp

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| Evolution por igreja | `IMPLEMENTADO no código` | conexão e entrega em produção não comprovadas | P0 de smoke |
| primeiro contato | `IMPLEMENTADO` | dedupe físico ainda não usa telefone canônico | P1 |
| boas-vindas | `PARCIAL` | sem fluxo de atualização cadastral |
| cadastro progressivo | `AUSENTE` | sem estado, retomada, confirmação ou revisão | P1 |
| revisão semestral | `AUSENTE` | sem campos e handler | P1 |
| consentimento adicional | `PARCIAL` | base existe, finalidades não estão separadas | P0 |
| opt-out | `IMPLEMENTADO` | preservar | manutenção |
| CSIM automático | `PARCIAL` | heurística por palavra-chave | P1 |
| LangGraph | `IMPLEMENTADO stateless` | sem memória conversacional | P1 |
| RAG | `AUSENTE` | usar primeiro para documentos com ACL | P2 |
| dados vivos da igreja | `PARCIAL` | quatro ferramentas, sem diretório amplo autorizado | P1 |
| configuração pelo master | `IMPLEMENTADO` | credencial/modelo/WhatsApp continuam liberados a qualquer admin | P0 de decisão |
| multiprovedor | `AUSENTE` | somente OpenAI | P3 |
| comunicação editorial | `AUSENTE` | broadcast manual não equivale a integração de fontes | P2 |
| criar célula pelo agente | `AUSENTE` | não deve entrar antes dos gates de autorização | P3 |

### 3.10 Design e qualidade

| Capacidade | Estado | Gap atual | Prioridade |
|---|---|---|---|
| tokens e primitives | `IMPLEMENTADO forte` | migração de telas legadas pode estar incompleta | P1 contínuo |
| marca e ativos | `IMPLEMENTADO` | preservar fonte canônica | manutenção |
| reduced motion | `IMPLEMENTADO` | validar componentes novos | contínuo |
| acessibilidade estática | `PARCIAL forte` | runtime, leitor de tela e zoom não medidos em todo produto | P1 |
| responsividade estática | `PARCIAL forte` | 360 a 1440 autenticado não medido | P1 |
| performance percebida | `PARCIAL/NÃO COMPROVADO` | sem métricas reais nesta auditoria | P1 |
| consistência de paddings e botões | `RELATADO` | precisa captura autenticada das telas problemáticas | P1 |

## 4. Gaps críticos, ordem de tratamento

### P0. Autorização e escopo

- bloquear enumeração tenant-wide por papéis limitados;
- proteger vínculo de célula por capacidade;
- filtrar fila por responsabilidade;
- validar transferência de conversa pela matriz efetiva;
- provar que ocultar menu e negar API produzem o mesmo resultado.

### P0. Liderança e acesso

- desacoplar convite e célula;
- impedir líder sem AppUser ativo;
- impedir papel de líder sem liderança real;
- criar aprovação atômica e auditada.

### P0. Comunicação real

- separar consentimentos por finalidade;
- definir owner/admin principal;
- comprovar Evolution, worker, flags e outbox;
- não chamar intenção de entrega.

### P1. Experiência por responsabilidade

- dashboard composto;
- Ganhar, Consolidar, Pessoas e Células escopados;
- áreas educativas seguras;
- visual autenticado de Agenda e Minha Célula.

### P1. Completar contratos já existentes

- frontend de célula com campos já suportados no backend;
- payload completo de multiplicação;
- visitante com telefone e decisão;
- alerta de relatório atrasado;
- confirmação antes de aprovações sensíveis.

### P1. Cadastro WhatsApp

- workflow retomável;
- campos e proveniência;
- revisão semestral;
- CSIM com revisão segura;
- dados vivos por ferramentas autorizadas.

## 5. Medido, inferido e hipótese

### Medido nesta auditoria

- SHA, branch e estado do worktree;
- presença e contratos de arquivos no frontend, backend e migrations;
- navegação, papéis, gates e escopos implementados;
- componentes e textos estáticos;
- ativos de marca e design tokens.

### Inferido

- impacto provável dos gaps de autorização;
- carga cognitiva de telas longas;
- utilidade dos blocos por responsabilidade;
- risco de expectativa quando intenção é exibida como envio.

### Hipótese a validar

- Agenda deve abrir em Semana;
- teal deve voltar como acento pastoral;
- quais KPIs da Central ajudam decisões reais;
- qual conteúdo educativo de Enviar será público;
- papel exato de pastor na administração;
- frequência e aceitação do recadastro semestral.

### Não comprovado

- estado atual de produção;
- migrations aplicadas em produção;
- flags e workers ativos;
- conexão Evolution e Google em uma igreja real;
- performance de campo;
- acessibilidade com leitores de tela;
- qualidade visual das telas autenticadas por breakpoint;
- dados legados e possíveis inconsistências.
