# Roadmap priorizado

## 1. Gates antes de qualquer PR

1. aprovar a direção visual;
2. definir owner/admin principal;
3. definir liderança de Ganhar e escopos por responsabilidade;
4. decidir consentimentos para comunicação ativa;
5. executar baseline autenticado em staging;
6. congelar screenshots nos cinco breakpoints;
7. verificar migrations, flags e workers sem modificar produção.

Cada PR abaixo é uma fatia vertical. Nenhum depende de reescrever o produto inteiro.

## 2. Fatias

### PR-01, capacidades e escopos de domínio

**Tipo:** correção necessária, P0.

**Objetivo:** impedir que papéis limitados enumerem ou alterem dados fora de sua responsabilidade.

**Arquivos prováveis:**

- `backend/app/deps.py`
- `backend/app/routers/contacts.py`
- `backend/app/routers/pipeline.py`
- `backend/app/routers/cells.py`
- `backend/app/routers/work_queue.py`
- `backend/app/domain/work_queue.py`
- `backend/app/routers/conversations.py`
- `frontend/src/lib/permissions.ts`
- telas de Ganhar e Pessoas.

**Dependências:** decisão de capacidade e escopo; dados de atribuição existentes.

**Risco:** alto, pode retirar acessos usados informalmente.

**Testes:** API direta por papel, tenant cruzado, célula cruzada, atribuição, URL manual, matriz efetiva.

**Screenshots:** Ganhar e fila para admin, pastor, líder e membro.

**Gate de aceite:** nenhum papel limitado lista ou altera objeto fora do escopo, mesmo chamando a API diretamente.

### PR-02, acesso e liderança de célula

**Tipo:** correção necessária, P0.

**Objetivo:** separar dar acesso, vincular célula e aprovar liderança.

**Arquivos prováveis:**

- `backend/app/routers/team.py`
- `backend/app/routers/cells.py`
- `backend/app/routers/cell_requests.py`
- `backend/app/services/cell_requests_service.py`
- `backend/app/services/cell_multiplication_service.py`
- `frontend/src/components/team/EquipeScreen.tsx`
- `frontend/src/components/central-celula/`
- migrations somente se o modelo aprovado realmente exigir.

**Dependências:** PR-01 e decisão sobre responsabilidade de líder.

**Risco:** alto, envolve dados legados e transação multiobjeto.

**Testes:** Pessoa existente com célula, convite sem mover, líder sem AppUser, papel sem célula, rollback e auditoria.

**Screenshots:** Dar acesso, solicitação de liderança e confirmação da Central.

**Gate de aceite:** liderança, acesso e papel nunca divergem após a transação.

### PR-03, fundação visual e quick wins

**Tipo:** quick win, depois da aprovação visual.

**Objetivo:** aplicar consistência sem mudar arquitetura funcional.

**Arquivos prováveis:**

- `frontend/src/app/design-tokens.css`
- `frontend/src/app/globals.css`
- `frontend/src/app/ds.css`
- primitives de Button, Field, Tabs, Dialog, Banner e EmptyState.

**Conteúdo:**

- padding consistente;
- botões sem quebra;
- largura e ações responsivas;
- estados de módulo desativado;
- teal candidato somente se aprovado e contrastado;
- documentação no harness.

**Dependências:** gate de direção.

**Risco:** médio, CSS global pode produzir regressão ampla.

**Testes:** harness, contraste, focus, reduced motion, visual regression.

**Screenshots:** biblioteca de componentes nos cinco breakpoints.

**Gate de aceite:** zero regressão de layout nas superfícies principais e nenhuma cor sem função semântica.

### PR-04, shell e dashboard por responsabilidade

**Tipo:** melhoria necessária, P1.

**Objetivo:** compor o Painel de Hoje por capacidades acumuladas.

**Arquivos prováveis:**

- `frontend/src/components/dashboard/`
- `frontend/src/components/shell/`
- `frontend/src/lib/navigation.ts`
- `backend/app/routers/dashboard.py`
- `backend/app/routers/work_queue.py`

**Dependências:** PR-01.

**Risco:** médio/alto, uma composição ruim duplica ou omite pendências.

**Testes:** combinações de papéis, uma e várias responsabilidades, fila vazia, dados parciais, offline.

**Screenshots:** membro, líder de célula, líder especializado, pastor e admin em mobile/desktop.

**Gate de aceite:** cada usuário entende em menos de cinco segundos o que exige ação e não vê uma fila global indevida.

### PR-05, Pessoas e Jornada escopadas

**Tipo:** correção e melhoria, P0/P1.

**Objetivo:** oferecer visões operacionais pequenas sem reabrir o diretório administrativo completo.

**Arquivos prováveis:**

- `frontend/src/components/contacts/`
- `frontend/src/components/pipeline/`
- telas de Consolidar e Discipular;
- `backend/app/routers/contacts.py`
- `backend/app/routers/pipeline.py`
- modelos de atribuição aprovados.

**Dependências:** PR-01 e decisões de liderança de Ganhar.

**Risco:** alto, impacto pastoral e de privacidade.

**Testes:** escopo célula, descendência, atribuído, self, CSIM, URL direta e paginação.

**Screenshots:** Ganhar e Consolidar em quatro papéis.

**Gate de aceite:** nenhum rótulo ou CTA promete ação que a API negará; nenhum papel vê dados além do escopo.

### PR-06, completar Minha Célula e Central

**Tipo:** melhoria necessária, P1.

**Objetivo:** completar contratos existentes antes de criar novos módulos.

**Arquivos prováveis:**

- `frontend/src/components/minha-celula/`
- `frontend/src/components/central-celula/`
- `frontend/src/components/cells/CellFormModal.tsx`
- APIs de células no frontend;
- routers e services de células, apenas para gaps comprovados.

**Conteúdo:**

- hero e contexto do membro;
- campos ricos já suportados;
- planejamento de reunião retomável;
- participante, transferência e saída;
- visitante integrado a Pessoas/Ganhar;
- confirmação antes de aprovar;
- payload completo de multiplicação;
- aviso honesto sobre entrega.

**Dependências:** PR-01 e PR-02.

**Risco:** alto em movimentação de pessoas, médio no visual.

**Testes:** membro, líder, Central, flag off, rollback, idempotência, mobile e teclado.

**Screenshots:** Minha Célula membro/líder e cinco abas da Central.

**Gate de aceite:** fluxos atuais permanecem, lacunas de contrato fecham e nenhuma transferência duplica membresia.

### PR-07, Agenda operacional e alinhamento visual

**Tipo:** melhoria necessária, P1.

**Objetivo:** completar evento, estados e Planejamento sem alterar o bom mobile atual.

**Arquivos prováveis:**

- `frontend/src/components/calendario/`
- `frontend/src/lib/events-api.ts`
- `backend/app/routers/events.py`
- `backend/app/routers/calendar.py`
- migration somente para novos campos aprovados.

**Conteúdo:**

- local, responsável e recorrência completa;
- pendente com ícone e texto;
- decisão Mês versus Semana;
- aba Planejamento, se validada;
- nome claro do aviso interno;
- conexão e conflito Google.

**Dependências:** PR-03 e decisão de governança Google.

**Risco:** médio.

**Testes:** fuso, recorrência, importação, conflito, papéis, teclado e breakpoints.

**Screenshots:** cinco abas, vazio, preenchido, erro e conexão expirada.

**Gate de aceite:** calendário permanece legível e honesto em todos os breakpoints; importação nunca é vendida como bidirecional.

### PR-08, workflow cadastral do WhatsApp

**Tipo:** nova capacidade necessária, P1.

**Objetivo:** transformar o questionário em workflow resumível e auditável.

**Arquivos prováveis:**

- novo domínio de workflow no backend;
- `backend/app/agent/nodes.py`
- `backend/app/agent/runtime.py`
- `backend/app/agent/tools.py`
- models/migration do workflow;
- tela administrativa de revisão;
- testes de queue worker e consentimento.

**Dependências:** decisão de dados, consentimentos e retenção.

**Risco:** alto, dados pessoais e estado conversacional.

**Testes:** pausa, retomada, recusa, lembrete, concorrência, opt-out, campo conflitante, revisão humana.

**Screenshots:** revisão administrativa, sem dados reais.

**Gate de aceite:** nenhuma resposta se perde, nenhum campo sensível muda sem finalidade e proveniência, e o fluxo não prende a pessoa.

### PR-09, governança e comunicação real

**Tipo:** correção e infraestrutura de produto, P0 antes de disparo.

**Objetivo:** separar owner, consentimentos e entrega real.

**Arquivos prováveis:**

- auth/deps de owner;
- agent, whatsapp, broadcast e events routers;
- services de outbox;
- migrations de consentimento e ledger, se aprovadas;
- telas de prévia, aprovação e relatório.

**Dependências:** decisão jurídica/produto, smoke Evolution e PR-08 quando o cadastro for um caso de uso.

**Risco:** muito alto.

**Testes:** payload exato, quantidade, destino, opt-out, retry, idempotência, cancelamento, falha parcial, recibos.

**Screenshots:** prévia, gate de aprovação, progresso e relatório.

**Gate de aceite:** nenhum envio acontece sem autorização, prévia e registro; estados distinguem aceito, entregue e falhou.

### PR-10, responsabilidades customizadas e organograma

**Tipo:** melhoria estrutural, P1/P2.

**Objetivo:** permitir cargos configuráveis sem inflar o enum de segurança.

**Dependências:** PR-01 e modelo aprovado de pastor principal.

**Risco:** alto, afeta autorização e árvore.

**Testes:** vigência, superior, substituto, escopo, revogação, loops e auditoria.

**Gate de aceite:** cargo ministerial não concede poder fora das capacidades explícitas.

### PR-11, conhecimento documental e áreas educativas

**Tipo:** opcional, P2.

**Objetivo:** Enviar, políticas, materiais e FAQ com fonte e ACL.

**Dependências:** governança de conteúdo e autorização.

**Risco:** médio/alto por conteúdo desatualizado e acesso.

**Testes:** tenant, audiência, versão, citação, ausência de fonte e revogação.

**Gate de aceite:** o agente não responde como fato sem fonte aprovada e vigente.

### PR-12, formação e Jornada profunda

**Tipo:** nova ideia fora do V1 atual, P2/P3.

**Objetivo:** Universidade da Vida, Capacitação Destino, árvore completa e Enviar operacional.

**Dependências:** modelo acadêmico e ministerial próprio.

**Risco:** muito alto, escopo amplo.

**Gate de aceite:** discovery e PRD separados, sem ocupar os wireframes atuais antes da aprovação.

## 3. Classificação executiva

### Quick wins

- título `Editar dados de {nome}`;
- renomear aviso interno da Agenda;
- paddings e botões sem quebra;
- estado claro para módulo desativado;
- ícone e texto para evento pendente;
- copy que diferencia intenção e entrega;
- usar no frontend campos de célula já suportados, quando não houver risco de autorização.

### Correções necessárias

- autorização por capacidade e escopo;
- convite separado de célula;
- liderança e acesso consistentes;
- consentimento por finalidade;
- fluxo real de entrega;
- visitante integrado a Pessoas/Ganhar;
- transferência de conversa com matriz efetiva.

### Melhorias opcionais

- teal pastoral;
- Planejamento da Agenda;
- busca global;
- timeline de atividade;
- rascunho automático;
- KPIs adicionais da Central.

### Fora do V1 atual

- agentes pessoais de pastor e pastora;
- banco em grafo para RAG sem necessidade provada;
- múltiplos provedores de IA;
- criação autônoma de células;
- publicação automática em redes sociais;
- formação acadêmica completa;
- sincronização profunda e automática do organograma.

## 4. Suite de aceite transversal

- 360, 390, 414, 768, 1024 e 1440 pixels;
- teclado e ordem de foco;
- axe e contraste manual;
- zoom a 200 por cento;
- reduced motion;
- Playwright visual;
- loading, vazio, erro, sucesso, offline, permissão e flag desligada;
- APIs chamadas diretamente por papel;
- multi-tenant e dados fora do escopo;
- smoke autenticado real;
- screenshots sanitizados;
- nenhuma credencial em log, vídeo ou captura.
