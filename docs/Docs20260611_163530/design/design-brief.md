# Design Brief

## Direcao Visual

**Direcao:** Software web claro, modern-minimal + tech utilitario; base zinc/off-white quente, acento teal dessaturado unico, numeros tabulares, bordas hairline, sem serif e sem preto puro
**Densidade:** balanced

## Tokens

### Cores

| Token | Valor |
|-------|-------|
| bg | oklch(98.6% 0.003 95) |
| surface | oklch(100% 0 0) |
| sidebar | oklch(21% 0.012 200) |
| fg | oklch(24% 0.01 90) |
| muted | oklch(52% 0.012 90) |
| border | oklch(91% 0.005 95) |
| accent | oklch(52% 0.078 195) |
| ok | oklch(56% 0.09 155) |
| warn | oklch(64% 0.11 75) |
| danger | oklch(56% 0.13 25) |

### Tipografia

| Token | Valor |
|-------|-------|
| display | system-ui (-apple-system / Segoe UI) |
| body | system-ui (-apple-system / Segoe UI) |
| mono | ui-monospace / JetBrains Mono |

### Espacamento

| Token | Valor |
|-------|-------|
| xs | 4px |
| sm | 8px |
| md | 12px |
| lg | 16px |
| xl | 24px |
| 2xl | 32px |

### Radii

| Token | Valor |
|-------|-------|
| sm | 6px |
| md | 10px |
| lg | 14px |
| xl | 20px |

## Mapa de Telas

- **Login** (`login`) — rota: `#login` — stories: US-01
- **Dashboard** (`dashboard`) — rota: `#dashboard` — stories: US-02, US-15, US-16, US-17, US-26, US-40
- **Inbox** (`inbox`) — rota: `#inbox` — stories: US-08, US-11, US-12, US-13, US-14
- **Contatos** (`contatos`) — rota: `#contatos` — stories: US-09, US-10, US-18, US-19, US-20, US-31, US-32
- **Celulas** (`celulas`) — rota: `#celulas` — stories: US-21, US-22, US-23, US-25
- **Relatorios de celula** (`relatorios`) — rota: `#relatorios` — stories: US-24, US-25, US-26
- **Comunicados** (`comunicados`) — rota: `#comunicados` — stories: US-31, US-32, US-33
- **Calendario** (`calendario`) — rota: `#calendario` — stories: US-30
- **Conexao WhatsApp** (`whatsapp`) — rota: `#whatsapp` — stories: US-05, US-06, US-07
- **Agente de IA** (`agente`) — rota: `#agente` — stories: US-27, US-28, US-29
- **Equipe e papeis** (`equipe`) — rota: `#equipe` — stories: US-03, US-04
- **Assinatura** (`assinatura`) — rota: `#assinatura` — stories: US-34, US-35, US-36
- **Permissoes** (`permissoes`) — rota: `#permissoes` — stories: US-04, US-03
- **Ganhar** (`ganhar`) — rota: `#ganhar` — stories: US-09, US-10, US-18, US-19, US-20
- **Consolidar** (`consolidar`) — rota: `#consolidar` — stories: US-18, US-19, US-20, US-37, US-38
- **Consolidacao Individual** (`consol-individual`) — rota: `#consol-individual` — stories: US-18, US-19, US-37, US-39
- **Universidade da Vida** (`universidade-vida`) — rota: `#universidade-vida` — stories: US-18, US-19
- **Capacitacao Destino** (`capacitacao`) — rota: `#capacitacao` — stories: US-18, US-19
- **G12 · Descendencias** (`g12`) — rota: `#g12` — stories: US-21, US-22, US-23
- **Central de Celula** (`central-celula`) — rota: `#central-celula` — stories: US-21, US-22, US-23, US-24, US-25, US-26
- **Enviar** (`enviar`) — rota: `#enviar` — stories: US-21, US-22, US-23
- **Gerentes de Sistema** (`gerentes`) — rota: `#gerentes` — stories: US-03, US-04
- **Super-Admin · Igrejas** (`super-admin-igrejas`) — rota: `#super-admin-igrejas` — stories: US-42
- **Super-Admin · Provisionar igreja** (`super-admin-provisionar`) — rota: `#super-admin-provisionar` — stories: US-43

## Navegacao Principal

- **Dashboard** (`nav-dashboard`) -> tela `dashboard` — stories: US-15, US-16, US-17, US-26
- **Chat (WhatsApp da Igreja)** (`nav-inbox`) -> tela `inbox` — stories: US-08, US-11, US-12, US-13, US-14
- **Ganhar** (`nav-ganhar`) -> tela `ganhar` — stories: US-09, US-10, US-18, US-19, US-20
- **Consolidar** (`nav-consolidar`) -> tela `consolidar` — stories: US-18, US-19, US-20
- **Consolidacao Individual** (`nav-consol-individual`) -> tela `consol-individual` — stories: US-18, US-19
- **Universidade da Vida** (`nav-universidade-vida`) -> tela `universidade-vida` — stories: US-18, US-19
- **Capacitacao Destino** (`nav-capacitacao`) -> tela `capacitacao` — stories: US-18, US-19
- **G12 · Descendencias** (`nav-g12`) -> tela `g12` — stories: US-21, US-22, US-23
- **Central de Celula** (`nav-central-celula`) -> tela `central-celula` — stories: US-21, US-22, US-23, US-24, US-25, US-26
- **Enviar** (`nav-enviar`) -> tela `enviar` — stories: US-21, US-22, US-23
- **Agenda da Igreja** (`nav-calendario`) -> tela `calendario` — stories: US-30
- **Comunicacao** (`nav-comunicados`) -> tela `comunicados` — stories: US-31, US-32, US-33
- **Equipe de Lideranca** (`nav-equipe`) -> tela `equipe` — stories: US-03, US-04
- **Conexao WhatsApp** (`nav-whatsapp`) -> tela `whatsapp` — stories: US-05, US-06, US-07
- **Agente IA** (`nav-agente`) -> tela `agente` — stories: US-27, US-28, US-29
- **Assinatura** (`nav-assinatura`) -> tela `assinatura` — stories: US-34, US-35, US-36
- **Gerentes de Sistema** (`nav-gerentes`) -> tela `gerentes` — stories: US-03, US-04
- **Permissoes** (`nav-permissoes`) -> tela `permissoes` — stories: US-04

## Componentes Principais

- **Botao primario** (`btn-primary`) — tipo: `form`
- **Campo de formulario** (`form-field`) — tipo: `form`
- **Navegacao lateral** (`sidebar-nav`) — tipo: `navigation`
- **Pilula de status** (`status-pill`) — tipo: `display`
- **Item da fila pastoral** (`work-queue-item`) — tipo: `display`
- **Cartao de indicador** (`stat-card`) — tipo: `display`
- **Lista de conversas** (`conversation-list`) — tipo: `display`
- **Thread de conversa** (`conversation-thread`) — tipo: `display`
- **Tabela de dados** (`data-table`) — tipo: `display`
- **Abas** (`tabs`) — tipo: `navigation`
- **Calendario mensal** (`calendar-month`) — tipo: `display`
- **QR code de conexao** (`qr-connect`) — tipo: `display`
- **Switch** (`toggle-switch`) — tipo: `form`
- **Estado vazio** (`empty-state`) — tipo: `display`
- **Selo de prazo** (`deadline-badge`) — tipo: `display`
- **Modal lancar decisao por Jesus** (`decision-modal`) — tipo: `overlay`
- **Painel do assistente do sistema** (`assistant-panel`) — tipo: `overlay`

## Deltas

- **scope** (`delta-001`) — impacto: low
  RECONCILIADO: as stories US-37 a US-43 (omitidas do mapa compacto) foram recebidas integralmente e tratadas uma a uma. US-38/US-39 anexadas as telas consolidar/consol-individual (rastreabilidade real); US-37 e US-40 construidas (ver delta-021/022); US-41 construida (delta-023); US-42/US-43 fora de escopo (delta-024). Cobertura US-01..US-43 completa.
- **assumption** (`delta-002`) — impacto: low
  Painel de Super-Admin (gestao de tenants/igrejas) citado nas notas de cobertura nao foi incluido por ser um painel separado do operacional da igreja; este artifact cobre apenas o painel da igreja (Pastor/Admin/Lider).
- **unclear** (`delta-003`) — impacto: low
  Dados exibidos (contatos, celulas, relatorios, conversas) sao amostras representativas do dominio para validar fluxo e estados; nao representam dados reais da igreja piloto.
- **assumption** (`delta-004`) — impacto: low
  Integracao Clerk, Google Calendar, gateway de pagamento e provedor LLM sao representados por estados de UI e contratos de API esperados; nenhuma credencial real e usada.
- **assumption** (`delta-005`) — impacto: high
  RBAC sem seletor manual: o seletor 'Ver como' foi removido. Cada pessoa acumula um conjunto de papeis no cadastro (ex.: pastor+admin+lider_g12; lider_celula+lider_consol; apenas membro) e o sistema monta menu e dashboard pela uniao dos acessos desses papeis. Itens de Configuracao (Equipe, Agente, WhatsApp, Assinatura, Permissoes) so aparecem para quem tem o papel admin. Os perfis de demonstracao no login simulam pessoas com papeis diferentes; em producao os papeis vem do cadastro autenticado (Clerk).
- **assumption** (`delta-006`) — impacto: high
  Itens da fila pastoral so aparecem para quem pode resolve-los. 'Resolver' = falar com o responsavel: abre um compositor que envia mensagem pelo WhatsApp oficial da igreja, prefixada com a identidade do remetente no formato 'Nome [papel]: mensagem'. Modelado em api-send-internal-message.
- **assumption** (`delta-007`) — impacto: medium
  Abrir/editar uma celula exige ser o lider daquela celula ou um superior na hierarquia ministerial. Cards bloqueados ficam com estado .locked e nao abrem o modal de detalhe/edicao.
- **assumption** (`delta-008`) — impacto: medium
  Contatos reorganizados em Todos, Sem acompanhamento, Visitantes, Discipulos, Lideres, Pastores. O antigo conceito 'sem consentimento' virou estado de Notificacoes (Liberadas/Bloqueadas) por contato, usado para excluir do envio de comunicados.
- **assumption** (`delta-009`) — impacto: medium
  Comunicados aceitam multiplos segmentos (multi-select) e agendamento tipo cron (enviar agora ou agendar com repeticao once/daily/weekly/biweekly/monthly). Agente passa a ter campo de Comportamento (prompt) e escopos de acesso selecionaveis ao sistema.
- **scope** (`delta-010`) — impacto: high
  Nova tela Permissoes (admin): matriz papel x tela onde o administrador da igreja define o que cada papel ministerial enxerga. Alteracoes refletem na hora no menu/dashboard. Dashboard tem visao de lideranca (fila pastoral, proximas acoes, status do WhatsApp) e visao de membro (trilha pessoal, celula, proximo evento), alternadas conforme a pessoa tenha ou nao papel de lideranca.
- **assumption** (`delta-011`) — impacto: high
  Tela Equipe agora edita o cadastro que alimenta o RBAC: cada pessoa recebe um ou mais papeis acumulados via checkboxes (convite com nome+email+papeis, e edicao de papeis por pessoa em modal). Salvar atualiza data-user-roles; se a pessoa editada for o usuario logado, menu e dashboard sao remontados na hora. Fecha o ciclo cadastro -> papeis -> acessos (api-team-roles, PUT /team/{usuarioId}/roles).
- **scope** (`delta-012`) — impacto: high
  Navegacao reorganizada em torno do ciclo ministerial G12. Grupo 'Gestao' (Dashboard + Chat/WhatsApp da Igreja); secao 'Visao G12 · Igreja' com os 4 estagios do pipeline: Ganhar (novos contatos + visitantes), Consolidar (dashboard + Consolidacao Individual + Universidade da Vida), Discipular (Capacitacao Destino + G12/Descendencias + Central de Celula) e Enviar (multiplicacoes agendadas/sem agendamento, aptos a liderar, aprovacao e historico); grupo 'Gestao' inferior (Agenda da Igreja, Comunicacao, Equipe de Lideranca); grupo 'Configuracao' (admin only). 9 telas novas adicionadas: ganhar, consolidar, consol-individual, universidade-vida, capacitacao, g12, central-celula, enviar, gerentes. Telas legadas contatos/celulas/relatorios permanecem validas para deep-link mas saem do menu (cobertas por ganhar/central-celula).
- **assumption** (`delta-013`) — impacto: medium
  Regra de promocao automatica de visitante: pessoa permanece 'visitante' ate (a) aceitar Jesus — informado pela consolidacao ou pelo lider de celula — OU (b) atingir 3 presencas em celula. Modelado em data-pipeline-stage (presencasCelula, aceitouJesus). Nenhuma edicao manual de etapa e necessaria; o sistema avanca a etapa pela trilha ministerial.
- **assumption** (`delta-014`) — impacto: high
  Trilha ministerial dirige o RBAC sem edicao manual de cadastro: visitar celula 2+ vezes -> membro; concluir Reencontro/Capacitacao -> apto a liderar; participar de multiplicacao + receber lideranca de celula -> lider de celula. Admins so editam papeis ministeriais como excecao; o fluxo normal e automatico (data-user-roles atualizado pela trilha).
- **scope** (`delta-015`) — impacto: medium
  Nova tela 'Gerentes de Sistema' (Configuracao, admin only): operador do sistema e um papel OPERACIONAL do SaaS, distinto dos papeis ministeriais (pastor, lider etc.). Definido no onboarding ou adicionado por admin. Modelado em data-system-managers / api-system-managers.
- **unclear** (`delta-016`) — impacto: low
  Agente IA foi mantido em Configuracao (admin only) embora nao tenha sido citado na lista explicita de Configuracao do usuario (Conexao WhatsApp, Assinatura, Gerentes de Sistema, Permissoes). Mantido por ser requerido por US-27/28/29 e por ja existir wiring. Confirmar se deve permanecer em Configuracao ou migrar para outro grupo.
- **scope** (`delta-017`) — impacto: high
  Painel do Consolidar: lista '100% consolidados' filtravel por celula, descendencia, genero e faixa etaria. Acao 'Atribuir lider' abre sugestao automatica de responsaveis ranqueada por genero igual (obrigatorio), proximidade de faixa etaria e mesma regiao/bairro; ao escolher, o orquestrador pergunta ao lider pelo WhatsApp se aceita assumir e, com o aceite, vincula a pessoa a celula, abre a consolidacao e avisa quem iniciou. Modelado em data-consolidation-queue / api-assign-consolidator (suggestLeaders + orchestrator flow).
- **assumption** (`delta-018`) — impacto: high
  Consolidacao Individual: cada pessoa abre uma trilha (aceitou Jesus -> conectou em celula -> fonovisita -> N visitas definidas pelas regras da igreja). Quem confirma cada encontro e exclusivamente o consolidador da pessoa; a central apenas supervisiona e o orquestrador lembra quem estiver em atraso. Confirmacao gateada por identidade (usuario logado == consolidador). Concluida a trilha, a pessoa entra no criterio da Universidade da Vida.
- **scope** (`delta-019`) — impacto: medium
  Universidade da Vida e Capacitacao Destino ficam bloqueadas no MVP (estado .locked com simbolo de relogio e cinza claro, rotulo 'em breve'). Conteudo detalhado das aulas/modulos existe e sera desenvolvido depois; o menu sinaliza disponibilidade futura sem navegar.
- **scope** (`delta-020`) — impacto: high
  Painel do Discipular (G12): organograma ministerial. O cadastro da igreja define o organograma inicial (so pastor, so pastora, ou familia pastoral -> descendencia masculina E feminina). A liderança principal aparece no topo com 12 slots; conforme os 12 sao marcados, os slots se preenchem e os vagos aparecem apagados. Cada pessoa marca no maximo 12; ao avancar ministerialmente, pode marcar seus proprios 12. Na arvore, a pessoa ve apenas sua linha ascendente/descendente; clicar num card que ja tem time abre o proximo nivel de 12 (drill-down por breadcrumb). Pastor visualiza homens, pastora visualiza mulheres. Modelado em data-g12-org / api-g12-tree.
- **scope** (`delta-021`) — impacto: high
  US-37 Lancar decisao por Jesus: acao disponivel no Dashboard de Consolidacao e na Consolidacao Individual (botao 'Lancar decisao'). Modal com dois fluxos. Fluxo A (pessoa ja em celula): o lider daquela celula assume a consolidacao. Fluxo B (visitante sem vinculo): a equipe de consolidacao lanca a decisao e abre um prazo de 24h para conectar a pessoa a uma celula. Em ambos os casos a pessoa entra na etapa inicial do pipeline de consolidacao. Modelado em data-decision / api-launch-decision.
- **scope** (`delta-022`) — impacto: high
  US-40 Pendencias com prazo na fila do Dashboard: 'Conectar a celula' carrega prazo de 24h com selo de tempo (deadline-badge) que muda de tom — dentro do prazo, alerta quando faltam poucas horas e destaque vermelho quando atrasado. Fonovisita tambem aparece como pendencia acionavel na fila, abrindo o acompanhamento da pessoa. Reforca a supervisao do orquestrador (lembretes por WhatsApp a quem estiver em atraso).
- **scope** (`delta-023`) — impacto: medium
  US-41 Assistente geral do sistema no painel: aside deslizante acionado por botao na topbar, ciente do papel do usuario logado (sauda citando os papeis e so sugere/explica telas que a pessoa pode ver, via allowedScreens) e restrito ao tenant/igreja. Implementado como prototipo de estados com respostas roteadas por palavra-chave e sugestoes de navegacao; NAO ha IA real nem chamada a LLM. Em producao seria api-assistant com contexto de papeis e tenant. Modelado em data-assistant.
- **scope** (`delta-024`) — impacto: medium
  US-42 e US-43 (Super-Admin do SaaS: gerir igrejas/tenants e provisionar nova igreja apos verificar pagamento) ficam FORA DO ESCOPO deste artifact, que cobre apenas o painel operacional de uma igreja (tenant). Sao uma superficie separada (console multitenant do provedor), a ser prototipada em artifact proprio. Registrado para rastreabilidade; nao implementado aqui.
- **assumption** (`delta-025`) — impacto: medium
  Atribuir na fila de trabalho pastoral (Dashboard): o botao 'Atribuir' de um item da fila abre o modal de atribuicao com ranking de lideres aptos (mesmo genero, area e faixa etaria do contato), em vez de apenas notificar. Reutiliza o fluxo de openAssign ja usado na consolidacao. Modelado em api-multiplicacoes/api-send-internal-message para o efeito colateral de notificar o lider escolhido.
- **assumption** (`delta-026`) — impacto: high
  Convite para celula (Ganhar): contatos novos disponiveis para convite so aparecem para lideres do MESMO genero do contato. Ao convidar, a pessoa fica em estado 'pendente' com selo 'Lider X demonstrou interesse' e e bloqueada para os demais lideres. So volta a ficar aberta para convite se a pessoa recusar o ultimo convite. Estado mantido em inviteState (open/pending/refused, by, prev). Em producao seria api-invite-to-cell.
- **assumption** (`delta-027`) — impacto: high
  Aprovacao de multiplicacao (Enviar): o botao 'Aprovar' nao aprova direto — abre um popup (approveModal) com os dados da solicitacao (celula origem, lider atual, novo lider, descendencia, area, data prevista, membros, criterio de aptidao e status de supervisao). So dentro do popup ha o botao 'Aprovar multiplicacao', e ele fica desabilitado enquanto a solicitacao tiver dados pendentes (sem novo lider ou sem data/supervisao). Modelado em api-multiplicacoes.
- **scope** (`delta-028`) — impacto: high
  CORRECAO CAPACITACAO DESTINO: os rotulos antigos da tela capacitacao (Encontro/Reencontro/Escola de Lideres) eram apenas placeholder visual e NAO representam o modelo real. Substituidos por placeholder honesto do modelo oficial da CD: 6 modulos, 1 livro por modulo, 10 aulas por livro (numeracao livro.aula 1.1-1.10..6.1-6.10), organizados em 3 niveis (1+2, 3+4, 5+6); maximo 2 modulos ativos por turma, varias turmas em paralelo; semaforo de assiduidade (>80% verde, 60-70% amarelo, <=50% vermelho); nivel concluido exige >70% assiduidade; 4 livros = selo Apto a Liderar (pode multiplicar), 6 livros = Certificado completo da CD. A Escola de Lideres sera detalhada a parte dentro desta trilha. Tela permanece BLOQUEADA no MVP. Feature completa fica para roadmap (ver delta-042 / Onda 5).
- **scope** (`delta-029`) — impacto: medium
  A4 Cobertura espiritual: o modal de cadastro/edicao de celula ganhou o campo obrigatorio 'cobertura espiritual' (toda celula esta sob uma cobertura no modelo G12). Deve ser persistido por celula no back. Modelado como extensao de data-cells/data-cell-detail.
- **scope** (`delta-030`) — impacto: high
  FUNDACAO F1 (multi-tenant desde a 1a linha) — NAO-UI, decisao de arquitetura para o pipeline: toda tabela nasce com igreja_id e isolamento por tenant (RLS no Postgres). A igreja piloto e apenas o primeiro registro de uma tabela de igrejas que ja existe. Nao construir mono-igreja para adaptar depois. Critico mesmo com Super-Admin (Onda 1) sendo roadmap.
- **scope** (`delta-031`) — impacto: high
  FUNDACAO F2 (trilha de maturidade como state machine unica) — NAO-UI: a posicao da pessoa (Conhecendo -> Visitante/Participante -> Em Consolidacao -> Discipulo -> Apto p/ UV -> Cursando UV -> Concluiu UV -> Cursando CD -> Apto a Liderar -> Lider/G12) e UM campo de estado governado por regras, nao flags espalhadas. Mudar de etapa edita o cadastro e reflete em menu, dashboard, permissoes e organograma. Modelar como maquina de estados central desde o MVP (ver data-pipeline-stage).
- **scope** (`delta-032`) — impacto: high
  FUNDACAO F3 (papeis acumulados dirigem o RBAC) — ja e regra do prototipo (delta-005/011/014): cada pessoa carrega um conjunto de papeis; menu e dashboard sao a uniao dos acessos. Nao modelar um papel por pessoa. A matriz papel x tela (tela Permissoes) e a fonte de verdade dos acessos; a trilha promove papeis automaticamente. O back precisa suportar promocao automatica desde o inicio.
- **scope** (`delta-033`) — impacto: high
  FUNDACAO F4 (autorizacao no back, nao so na UI) — NAO-UI: o prototipo trava na interface (so consolidador confirma encontro; so lider/superior abre celula; Config so admin), mas cada endpoint precisa revalidar igreja_id + papel do usuario no servidor. A UI e conveniencia; a autorizacao real e no back.
- **scope** (`delta-034`) — impacto: high
  FUNDACAO F5 (agente usa as mesmas regras de um humano) — NAO-UI: ao registrar decisao, marcar presenca, vincular a celula ou avancar a trilha, o agente usa as mesmas funcoes e validacoes de um usuario humano, com o mesmo escopo de tenant e permissao. O agente nunca tem atalho que ignore regras de negocio. Evita corromper a trilha ou misturar dados de igrejas.
- **scope** (`delta-035`) — impacto: medium
  FUNDACAO F6 (modelo de pessoa unificado) — NAO-UI: Conhecendo/Visitante/Discipulo/Lider/Pastor sao estados da MESMA pessoa, nao tabelas diferentes. Quem chega como contato no WhatsApp e vira lider anos depois e o mesmo registro evoluindo. Nao criar entidades separadas que depois precisam ser fundidas.
- **scope** (`delta-036`) — impacto: medium
  FUNDACAO F7 (organograma G12 com integridade hierarquica) — parcialmente no prototipo (delta-020): ninguem abaixo aparece acima de quem tem hierarquia maior; mover um card edita o cadastro indicando nova lideranca (com confirmacao). Modelar a relacao lider->liderado como campo de lideranca no cadastro da pessoa, nao estrutura paralela, para arvore e cadastro nunca divergirem. Familias pastorais geram descendencia masculina E feminina.
- **scope** (`delta-037`) — impacto: medium
  FUNDACAO F8 (auditoria e custos de IA desde o inicio) — NAO-UI: mesmo sem as telas do Super-Admin, registrar no back logs de conversacao (interacoes do agente, ferramentas usadas) e consumo de IA por igreja (modelo, tokens, custo). Sustenta o BYO-LLM, a futura precificacao e a depuracao. Logar desde o dia 1 e muito mais barato que reconstruir historico depois.
- **scope** (`delta-038`) — impacto: medium
  FUNDACAO F9 (crons com gatilhos por estado) — NAO-UI, conecta com A1: a infra de agendamento do Agente nao e so horario fixo; deve suportar gatilhos disparados por estado do banco (prazo vencendo, meta atingida). Mesma fundacao do motor de SLAs (A1) e do Numero de Sonho da UV (Onda 4). Construir generico desde ja.
- **scope** (`delta-039`) — impacto: high
  MVP-BACKEND A1 (motor de SLAs proativo) — diferencial, NAO-UI rica: alem de mostrar pendencias, detectar SLA estourando e disparar cobranca automatica pelo WhatsApp. Prazos: relatorio de pessoas salvas ate 2h; conexao do novo ganho a uma lideranca ate 12h; fonovisita + marcar 1a visita ate 24h. Numero de Sonho da UV: meta configuravel (ex.: 50) -> alerta automatico a pastores/coordenacao. Escalonamento: lider sem resposta -> sobe para a coordenacao. Reaproveita a infra de crons (F9).
- **scope** (`delta-040`) — impacto: high
  MVP-BACKEND A2 (registro formal de consentimento LGPD) — dado sensivel, pode ser back sem tela rica: gravar versao do termo + data/hora do aceite por pessoa; nova versao publicada exige re-aceite no proximo contato/acesso; o agente apresenta o termo (mensagem curta + link) ANTES de coletar dados alem de nome+telefone; mascara de CPF e dados sensiveis nos logs. CPF + dados religiosos sao sensiveis sob a LGPD. Hoje o MVP tem apenas o flag Notificacoes (Liberadas/Bloqueadas) por contato (delta-008).
- **scope** (`delta-041`) — impacto: high
  MVP-BACKEND A3 (relatorio de celula capturado por conversa) — NAO-UI: o lider envia por texto OU audio (ex.: 'realizei a celula ontem, vieram 8, a visitante Maria aceitou Jesus'); o agente extrai e registra presentes, visitantes, quem aceitou Jesus e se houve oferta; visitante que aceitou Jesus abre automaticamente o fluxo de consolidacao. O escopo 'Relatorios via WhatsApp' ja existe nos toggles do Agente; falta especificar a extracao.
- **scope** (`delta-042`) — impacto: medium
  ROADMAP Ondas 1-5 (entregaveis independentes, fora do MVP): Onda 1 Multi-tenant de verdade (painel Super-Admin: cadastro/edicao de igrejas, aprovacoes globais, custos de IA por igreja, logs; onboarding de nova igreja por convite com link que expira em 7 dias + validacao de CPF/e-mail + 'Aguardando Aprovacao'; cadastro de pessoas em cascata; presets de metodologia G12). Onda 2 Operacao da celula (Planejar Celula: tema/musica/quebra-gelo/oferta/avisos com distribuicao de tarefas; Realizar Celula: confirmar data -> presentes -> visitantes/aceitou Jesus -> oferta -> relatorio; tudo por conversa com o agente, inclusive audio). Onda 3 Consolidacao completa (telas de consolidacoes individuais com guia, materiais PDF/online, scripts de fonovisita, ranking de consolidadores, supervisao). Onda 4 Universidade da Vida (destravar tela universidade-vida; 10 semanas: aulas 1-4 -> Encontro com Deus (semana 5) -> aulas 5-8 -> Batismo (semana 10); pre-requisito de matricula = consolidacao individual concluida + vinculo a celula, matricula feita pelo lider; turmas anteriores e turma atual; selo 'Apto para Encontro' apos aulas 1-4; Certificado da UV ao concluir -> habilita CD; Numero de Sonho como gatilho automatico via motor de SLAs; gestao do Encontro restrita a coordenacao/pastores com valor/local/data). Onda 5 Capacitacao Destino completa (modelo de 6 livros do delta-028).
