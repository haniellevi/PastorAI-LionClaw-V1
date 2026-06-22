# User Stories e Requisitos — PastorAI

> Documento gerado a partir do discovery. Fonte de verdade para a fase Open Design.
> Cada user story foi escrita para virar tela, fluxo, componente ou estado de UI.
> Onde aplicavel, indica-se o padrao de interface esperado (tela, lista, formulario,
> dashboard, detalhe, chat, calendario, menu, modal, estado vazio etc.).

---

## Personas de referencia

- **Pastor / Admin da Igreja** — responsavel maximo pela igreja no sistema. Enxerga pendencias pastorais, toma decisoes sensiveis, acompanha celulas, lideres e relatorios, e configura o sistema.
- **Lider de Celula** — opera a rotina semanal: envia relatorio pelo WhatsApp, acompanha membros e visitantes da sua celula, recebe alertas sobre seus liderados.
- **Usuario final via WhatsApp** (visitante, membro, lider) — interage 100% pelo WhatsApp; nao acessa o painel.
- **Equipe de Consolidacao** — ministerio responsavel por acompanhar quem decide por Jesus e conectar visitantes sem celula; acessa o Dashboard de Consolidacao (acesso restrito).
- **Admin do Sistema (Super-Admin / operador do SaaS)** — controla todo o negocio do SaaS: gerencia as igrejas cadastradas (cada igreja isolada, com IA e dados proprios), verifica pagamentos e provisiona novas igrejas. Atua no painel de Super-Admin, separado do painel operacional das igrejas.

---

# 1. User Stories

## Dominio: Autenticacao e Multi-tenant

### US-01 — Login no painel
Como **Pastor/Admin**, quero **fazer login com minhas credenciais via Clerk**, para **acessar o painel da minha igreja com seguranca**.
- **Interface:** tela de login.
- **Criterios de aceite:**
  - O usuario autentica via Clerk (e-mail/senha e demais metodos habilitados pelo Clerk).
  - Apos autenticacao bem-sucedida, o usuario e redirecionado ao dashboard da sua igreja.
  - Credenciais invalidas exibem mensagem de erro sem revelar se o e-mail existe.
  - Sessao invalida ou expirada redireciona para a tela de login.

### US-02 — Isolamento de dados por igreja (multi-tenant)
Como **Pastor/Admin**, quero **ver e operar somente os dados da minha igreja**, para **garantir que nenhuma outra igreja acesse meus dados**.
- **Interface:** transversal (sem tela propria; afeta todas as telas).
- **Criterios de aceite:**
  - Toda consulta de dados retorna apenas registros pertencentes a igreja (tenant) do usuario autenticado.
  - Uma tentativa de acessar um recurso (por ID) de outra igreja retorna erro de acesso negado.
  - O isolamento e aplicado em nivel de banco via RLS do Supabase.

### US-03 — Gestao de usuarios da igreja
Como **Pastor/Admin**, quero **convidar e gerenciar usuarios (lideres) da minha igreja**, para **dar acesso ao painel a quem precisa**.
- **Interface:** tela de listagem de usuarios + formulario/modal de convite.
- **Criterios de aceite:**
  - O Admin pode convidar um novo usuario informando e-mail e papel (Pastor/Admin ou Lider).
  - O convite gera envio de e-mail (via Brevo) com link de ativacao.
  - O Admin pode listar usuarios ativos e pendentes com seu papel.
  - O Admin pode revogar o acesso de um usuario.

### US-04 — Controle de acesso por papel
Como **Pastor/Admin**, quero **que cada papel veja apenas o que lhe compete**, para **manter decisoes sensiveis restritas**.
- **Interface:** transversal (visibilidade condicional de menus e acoes).
- **Criterios de aceite:**
  - O Lider de Celula visualiza apenas os dados da(s) celula(s) sob sua responsabilidade.
  - O Pastor/Admin visualiza todas as celulas, lideres e configuracoes da igreja.
  - Acoes restritas a Admin (configuracao, assinatura, gestao de usuarios) nao aparecem para Lider.
  - O modelo de acesso segue o principio hierarquico "quem esta acima ve o que esta abaixo; quem esta abaixo nao ve o que esta acima". No MVP os papeis ativos sao Pastor/Admin, Lider de Celula e usuario autorizado ao atendimento humano (ex.: secretaria); a hierarquia completa de papeis (membro, lider de ministerio, niveis G12) esta prevista no Roadmap pos-MVP.

---

## Dominio: Conexao WhatsApp

### US-05 — Conectar o numero oficial da igreja
Como **Pastor/Admin**, quero **conectar o WhatsApp oficial da igreja lendo um QR code**, para **que o sistema receba e envie mensagens por esse numero**.
- **Interface:** tela/modal de conexao com exibicao de QR code e estado da conexao.
- **Criterios de aceite:**
  - A tela exibe um QR code gerado via Evolution API para parear o numero da igreja.
  - O estado da conexao e exibido (Desconectado, Aguardando leitura, Conectado).
  - Apos pareamento, o estado muda para "Conectado" sem recarregar manualmente a pagina.
  - Apenas um numero oficial por igreja pode estar conectado por vez.

### US-06 — Monitorar e reconectar o WhatsApp
Como **Pastor/Admin**, quero **ver se o WhatsApp da igreja esta online e reconectar quando cair**, para **nao perder mensagens de visitantes e lideres**.
- **Interface:** indicador de status (badge/estado) + acao de reconectar.
- **Criterios de aceite:**
  - O painel exibe o status atual da conexao do WhatsApp da igreja.
  - Quando a conexao cai, o Admin pode acionar a reconexao (novo QR quando necessario).
  - Mensagens recebidas enquanto desconectado nao geram contatos duplicados ao reconectar.

### US-07 — Nao registrar conversas pessoais do pastor
Como **Pastor/Admin**, quero **que apenas conversas com o numero oficial sejam registradas**, para **preservar a privacidade pastoral das conversas pessoais**.
- **Interface:** transversal (regra de captura; sem tela propria).
- **Criterios de aceite:**
  - O sistema registra e atua somente sobre mensagens trocadas com o numero oficial da igreja.
  - Conversas no WhatsApp pessoal do pastor (outro numero) nunca sao capturadas nem exibidas no painel.

---

## Dominio: Atendimento por IA (Agente Orquestrador)

### US-08 — Atendimento automatico de quem chama a igreja
Como **Usuario final via WhatsApp**, quero **ser atendido automaticamente ao chamar o numero da igreja**, para **receber resposta sem esperar um humano**.
- **Interface:** WhatsApp (conversa); reflexo no painel como conversa registrada.
- **Criterios de aceite:**
  - Toda mensagem recebida no numero oficial e roteada pelo agente orquestrador.
  - O agente responde via WhatsApp usando o provedor LLM configurado pela igreja.
  - Cada conversa nova cria/atualiza um contato vinculado a igreja.

### US-09 — Coleta de dados e criacao de contato pelo agente
Como **Pastor/Admin**, quero **que o agente colete dados basicos do interlocutor e crie o contato**, para **que ninguem que fala com a igreja fique sem registro**.
- **Interface:** reflexo em tela de detalhe do contato (dados coletados).
- **Criterios de aceite:**
  - O agente coleta, no minimo, nome e numero de telefone do interlocutor.
  - Um contato e criado/atualizado automaticamente com os dados coletados.
  - O contato registra a origem (ex.: chegou pelo WhatsApp) e a data do primeiro contato.

### US-10 — Onboarding de contato/visitante pelo agente
Como **Usuario final via WhatsApp**, quero **ser recebido e cadastrado pelo agente de onboarding**, para **iniciar meu vinculo com a igreja**.
- **Interface:** WhatsApp (fluxo conversacional conduzido pelo orquestrador da igreja); reflexo no painel/consolidacao.
- **Criterios de aceite:**
  - O agente de onboarding (orquestrador do WhatsApp da igreja) conduz a conversa coletando, no minimo: nome, endereco, interesse em ser acompanhado por alguem da igreja, necessidade de oracao e se a pessoa ja veio a igreja ou a uma celula.
  - O conteudo e as etapas do fluxo de boas-vindas sao configuraveis e podem ser editados a qualquer momento (nao apenas no setup da igreja), ver US-28; nao e um roteiro fixo.
  - As informacoes coletadas sao notificadas ao sistema de consolidacao.
  - A pessoa e cadastrada como "contato (precisa de acompanhamento)" caso ainda nao tenha ido a igreja, ou como "visitante" caso ja tenha ido a igreja ou a alguma celula.
  - O contato/visitante recem-cadastrado entra na fila de acompanhamento da consolidacao (ver US-18 e US-38).

### US-11 — Lista de conversas (inbox)
Como **Pastor/Admin** ou **usuario autorizado ao atendimento humano** (ex.: secretaria), quero **ver a lista de conversas do WhatsApp da igreja**, para **acompanhar o que esta acontecendo nos atendimentos**.
- **Interface:** lista (inbox) + tela de chat por conversa.
- **Criterios de aceite:**
  - As conversas sao listadas com identificacao do contato, ultima mensagem e horario.
  - Ao abrir uma conversa, o historico de mensagens e exibido em ordem cronologica.
  - Conversas com atendimento humano pendente sao visualmente sinalizadas.
  - Apenas Pastor/Admin e usuarios explicitamente liberados ao atendimento humano (ex.: secretaria) acessam o inbox; Lideres de celula NAO tem acesso as conversas do WhatsApp da igreja.

---

## Dominio: Atendimento Humano (Handoff)

### US-12 — Assumir atendimento (pausar IA)
Como **Pastor/Admin** ou **usuario autorizado ao atendimento humano** (ex.: secretaria), quero **assumir uma conversa e pausar a IA**, para **atender pessoalmente quando o caso exige sensibilidade humana**.
- **Interface:** tela de chat com acao "Assumir" + estado "Em atendimento humano".
- **Criterios de aceite:**
  - Ao assumir, a IA para de responder automaticamente naquela conversa.
  - O sistema registra quem assumiu e o horario.
  - Enquanto em atendimento humano, mensagens enviadas pelo operador saem pelo numero oficial.

### US-13 — Devolver atendimento para a IA
Como **Pastor/Admin** ou **Lider**, quero **devolver a conversa para a IA depois de atender**, para **que o agente retome o fluxo automatico**.
- **Interface:** tela de chat com acao "Devolver para IA" + retorno ao estado "Atendimento por IA".
- **Criterios de aceite:**
  - Ao devolver, a IA volta a responder automaticamente naquela conversa.
  - O sistema registra o encerramento do atendimento humano e o horario.

### US-14 — Fila de atendimentos humanos aguardando
Como **Pastor/Admin**, quero **ver os atendimentos humanos que estao aguardando**, para **priorizar quem precisa de resposta agora**.
- **Interface:** lista/fila priorizada dentro do dashboard.
- **Criterios de aceite:**
  - A fila exibe as conversas aguardando atendimento humano, com tempo de espera.
  - Cada item permite acao direta de assumir.
  - Ao ser assumido ou resolvido, o item sai da fila.

---

## Dominio: Painel / Fila de Trabalho Pastoral

### US-15 — Dashboard de pendencias pastorais
Como **Pastor/Admin**, quero **ver em segundos o que exige acao hoje**, para **reduzir a carga operacional e nao perder pessoas**.
- **Interface:** painel unico de tarefas pendentes (dashboard) com blocos/cartoes priorizados (o urgente primeiro); US-16 e US-17 sao visoes do mesmo painel.
- **Criterios de aceite:**
  - O painel mostra apenas tarefas/pendencias a fazer (nao e um historico de acoes ja realizadas).
  - O painel e visivel somente a usuarios com privilegio (Pastor/Admin e usuarios autorizados); papeis sem privilegio nao o acessam.
  - O dashboard exibe, no minimo: visitantes sem acompanhamento, atendimentos humanos aguardando e relatorios de celula pendentes.
  - Cada bloco mostra a contagem e permite navegar para a lista detalhada correspondente.
  - A informacao e ordenada por prioridade/urgencia (mais urgente no topo).

### US-16 — Acoes diretas na fila de trabalho
Como **Pastor/Admin**, quero **assumir, resolver, atribuir e devolver itens direto da fila**, para **agir sem trocar de tela**.
- **Interface:** lista de itens acionaveis com acoes inline (assumir, resolver, atribuir, devolver).
- **Criterios de aceite:**
  - As acoes sao executadas dentro do sistema (nao abrem nem dependem de uma conversa no WhatsApp).
  - Cada item da fila oferece as acoes: assumir, resolver, atribuir a um responsavel e devolver para IA (quando aplicavel ao tipo do item).
  - Atribuir um item exige selecionar um responsavel valido da igreja e dispara uma notificacao ao responsavel pelo WhatsApp oficial da igreja.
  - Um item pode ser baixado de duas formas: (a) o orquestrador pergunta ao responsavel, pelo WhatsApp, se a acao foi concluida e atualiza o sistema; ou (b) um usuario com privilegio atualiza/resolve o item manualmente no sistema.
  - Ao resolver um item, ele sai da fila de pendencias.

### US-17 — Proximas acoes por responsavel
Como **Pastor/Admin**, quero **ver as proximas acoes agrupadas por responsavel**, para **saber quem esta com o que**.
- **Interface:** lista/agrupamento por responsavel.
- **Criterios de aceite:**
  - As acoes pendentes sao agrupadas pelo responsavel atribuido.
  - Itens sem responsavel aparecem em um grupo "Nao atribuido".

---

## Dominio: Gestao de Visitantes e Contatos

### US-18 — Lista de visitantes sem acompanhamento
Como **Pastor/Admin** ou **Lider**, quero **listar visitantes que ainda nao foram acompanhados**, para **conecta-los a uma celula no tempo certo**.
- **Interface:** lista filtravel + estado vazio.
- **Criterios de aceite:**
  - A lista exibe os visitantes em status "em acompanhamento" (visitantes da igreja ainda sem celula), com data do primeiro contato.
  - A lista pode ser ordenada pelo tempo desde o primeiro contato.
  - Todo visitante sem celula e responsabilidade da equipe de consolidacao ate ser conectado a uma celula.
  - Ao vincular o visitante a uma celula (US-20), ele passa a "membro" e sai desta lista.

### US-19 — Detalhe do contato
Como **Pastor/Admin** ou **Lider**, quero **abrir o perfil de um contato**, para **ver seus dados, historico e situacao**.
- **Interface:** tela de detalhe (perfil) do contato.
- **Criterios de aceite:**
  - O detalhe exibe dados coletados (nome, telefone, tipo, origem, data de entrada).
  - O detalhe mostra a celula vinculada (quando houver) e o status de acompanhamento.
  - A partir do detalhe e possivel abrir a conversa de WhatsApp do contato.

### US-20 — Conectar visitante a uma celula
Como **Pastor/Admin** ou **Lider**, quero **vincular um visitante a uma celula**, para **iniciar a consolidacao rapidamente**.
- **Interface:** acao/modal de vinculo a partir do detalhe ou da lista.
- **Criterios de aceite:**
  - E possivel selecionar uma celula valida da igreja e vincular o contato.
  - Apos o vinculo, o contato deixa o status "em acompanhamento" e passa a "membro" da celula.
  - O contato vinculado aparece na celula correspondente.

---

## Dominio: Celulas e Lideres

### US-21 — Cadastro de celulas
Como **Pastor/Admin**, quero **cadastrar e editar celulas da igreja**, para **organizar a estrutura G12**.
- **Interface:** lista de celulas + formulario de cadastro/edicao.
- **Criterios de aceite:**
  - O Admin pode criar uma celula informando, no minimo, nome e lider responsavel.
  - O Admin pode editar e inativar uma celula.
  - A lista exibe as celulas com seu lider e quantidade de membros.

### US-22 — Membros e visitantes de uma celula
Como **Lider de Celula**, quero **ver os membros e visitantes da minha celula**, para **acompanhar meus liderados**.
- **Interface:** tela de detalhe da celula com lista de membros/visitantes.
- **Criterios de aceite:**
  - O detalhe da celula lista os membros e visitantes vinculados.
  - O Lider visualiza apenas a(s) celula(s) sob sua responsabilidade.
  - Cada pessoa da lista abre seu detalhe de contato (US-19).

### US-23 — Alertas sobre liderados
Como **Lider de Celula**, quero **receber alertas sobre meus liderados**, para **agir quando alguem precisa de atencao**.
- **Interface:** area de alertas/notificacoes no painel.
- **Criterios de aceite:**
  - Os alertas sao gerados por gatilhos configuraveis e editaveis a qualquer momento (regras que definem quais eventos geram alerta), e nao por uma lista fixa.
  - O Lider recebe alertas relacionados aos contatos da sua celula (ex.: visitante novo a acompanhar, liderado em consolidacao, relatorio de celula pendente).
  - Cada alerta indica o contato e a acao esperada.
  - Um alerta e considerado "tratado" quando o responsavel realiza/baixa a acao, deixando de ser exibido como pendente.
  - *(Refinamento futuro)* Inteligencia para priorizar e sugerir alertas automaticamente.

---

## Dominio: Relatorio de Celula via WhatsApp

### US-24 — Enviar relatorio de celula pelo WhatsApp
Como **Lider de Celula**, quero **enviar o relatorio semanal por mensagem no WhatsApp**, para **nao precisar acessar planilha ou painel**.
- **Interface:** WhatsApp (fluxo conversacional); reflexo no painel.
- **Criterios de aceite:**
  - O agente coleta os dados minimos: celula, data, presentes, visitantes, decisoes por Jesus e observacoes.
  - O agente confirma os dados coletados antes de registrar o relatorio.
  - O relatorio registrado fica vinculado a celula e a data informadas.
  - Cada decisao por Jesus registrada no relatorio pode iniciar a consolidacao da pessoa (ver US-37).

### US-25 — Visualizar relatorios de celula no painel
Como **Pastor/Admin**, quero **ver os relatorios de celula no painel**, para **acompanhar a vida das celulas**.
- **Interface:** lista de relatorios + tela de detalhe do relatorio.
- **Criterios de aceite:**
  - Os relatorios sao listados por celula e data, com indicadores principais (presentes, visitantes, decisoes).
  - O detalhe exibe todos os dados coletados, incluindo observacoes.

### US-26 — Relatorio pendente vira acao na fila
Como **Pastor/Admin**, quero **ver quais celulas nao enviaram o relatorio da semana**, para **cobrar os lideres pendentes**.
- **Interface:** bloco/lista de pendencias no dashboard.
- **Criterios de aceite:**
  - O sistema identifica celulas sem relatorio no periodo esperado e gera item de pendencia.
  - O item de pendencia indica a celula e o lider responsavel.
  - Quando o relatorio e recebido, a pendencia e baixada automaticamente.

---

## Dominio: Configuracao de Agentes IA e Credencial LLM

### US-27 — Cadastrar credencial do provedor LLM (BYO)
Como **Pastor/Admin**, quero **cadastrar a chave de API do meu provedor de IA**, para **que a igreja use sua propria credencial e arque com o custo de LLM**.
- **Interface:** tela/formulario de configuracao de credencial LLM.
- **Criterios de aceite:**
  - O Admin cadastra uma credencial de provedor informando o provedor e a chave de API.
  - A chave e armazenada de forma protegida e nunca exibida em texto claro apos salva.
  - O sistema valida que a credencial e funcional antes de marca-la como ativa.
  - No MVP, o provedor disponivel e OpenAI; a modelagem permite adicionar outros provedores no futuro.

### US-28 — Configurar comportamento do agente
Como **Pastor/Admin**, quero **configurar com quem o agente fala e o que fala**, para **adaptar o atendimento ao tom da minha igreja**.
- **Interface:** tela/formulario de configuracao de agente.
- **Criterios de aceite:**
  - O Admin pode definir o conteudo/instrucoes que orientam as respostas do agente.
  - As alteracoes passam a valer nas conversas seguintes apos salvar.

### US-29 — Configurar crons e agendamentos do agente
Como **Pastor/Admin**, quero **configurar agendamentos (crons) para acoes do agente**, para **automatizar lembretes e rotinas**.
- **Interface:** tela de configuracao de agendamentos (lista + formulario).
- **Criterios de aceite:**
  - O Admin pode criar, editar e desativar agendamentos de acoes do agente.
  - Cada agendamento define periodicidade e a acao a ser executada.
  - Agendamentos desativados nao disparam.

---

## Dominio: Calendario e Eventos

### US-30 — Gerir eventos no calendario
Como **Pastor/Admin**, quero **cadastrar e visualizar eventos da igreja em um calendario**, para **organizar a agenda integrada ao Google Calendar**.
- **Interface:** calendario + formulario de evento.
- **Criterios de aceite:**
  - O Admin pode criar um evento informando titulo, data/hora e descricao.
  - Os eventos sao sincronizados com o Google Calendar da igreja.
  - O calendario exibe os eventos no periodo selecionado (visao por mes/semana/dia).

---

## Dominio: Comunicados, Consentimento e Opt-out

### US-31 — Registrar consentimento de comunicacao
Como **Pastor/Admin**, quero **que o consentimento de cada contato seja registrado**, para **enviar comunicados apenas a quem aceitou**.
- **Interface:** indicador de consentimento no detalhe do contato.
- **Criterios de aceite:**
  - O consentimento e concedido automaticamente quando a pessoa inicia a conversa com o numero oficial da igreja (a igreja nunca inicia comunicacao espontanea / nao envia spam).
  - A pessoa pode pedir opt-out a qualquer momento, deixando de receber comunicados em massa, mas seguindo apta a conversas normais de atendimento (ver US-32).
  - Para a base existente (membros atuais), a igreja faz um contato inicial informando o novo atendimento e perguntando se a pessoa concorda em receber comunicados pelo WhatsApp; a resposta atualiza o status de consentimento.
  - O detalhe do contato exibe o status atual de consentimento.

### US-32 — Opt-out de comunicacao
Como **Usuario final via WhatsApp**, quero **poder cancelar o recebimento de comunicados**, para **deixar de receber mensagens quando nao quiser mais**.
- **Interface:** WhatsApp (comando/fluxo de opt-out); reflexo no detalhe do contato.
- **Criterios de aceite:**
  - O usuario pode solicitar opt-out pelo WhatsApp.
  - Apos o opt-out, o contato deixa de receber comunicados em massa.
  - O status de opt-out e refletido no detalhe do contato.

### US-33 — Envio segmentado de comunicados
Como **Pastor/Admin**, quero **enviar comunicados a um segmento de contatos**, para **comunicar com controle e sem violar opt-out**.
- **Interface:** tela de criacao de comunicado com selecao de segmento.
- **Criterios de aceite:**
  - O Admin seleciona um segmento (ex.: por celula ou tipo de contato) para o envio.
  - Contatos com opt-out ou sem consentimento sao excluidos automaticamente do envio.
  - O envio e disparado pelo numero oficial da igreja no WhatsApp.

---

## Dominio: Monetizacao e Assinatura

### US-34 — Contratar assinatura com setup fee
Como **Pastor/Admin**, quero **contratar a assinatura da minha igreja pagando a mensalidade e o setup**, para **ativar o uso do PastorAI**.
- **Interface:** tela de planos/checkout (integracao Asaas).
- **Criterios de aceite:**
  - Os tres planos sao exibidos com porte e mensalidade (ate 100 = R$199; 101-200 = R$299; acima de 201 = R$399).
  - A contratacao cobra o setup unico de R$ 1.000,00 alem da mensalidade.
  - O pagamento e processado via Asaas com PIX, boleto ou cartao.
  - Apos confirmacao do pagamento, a igreja fica com a assinatura ativa.

### US-35 — Acompanhar status da assinatura
Como **Pastor/Admin**, quero **ver o status e os dados da minha assinatura**, para **saber se esta em dia**.
- **Interface:** tela de assinatura/faturamento.
- **Criterios de aceite:**
  - A tela exibe o plano atual, valor da mensalidade e status (ativa, pendente, inadimplente).
  - A tela exibe a proxima data de cobranca.

### US-36 — Upgrade automatico de plano por porte
Como **Pastor/Admin**, quero **que o plano suba automaticamente quando ultrapassar o limite de pessoas**, para **nao precisar trocar de plano manualmente**.
- **Interface:** reflexo na tela de assinatura + notificacao.
- **Criterios de aceite:**
  - O porte e contado pelo numero de pessoas cadastradas na igreja.
  - Ao ultrapassar o limite do plano atual, a igreja passa automaticamente ao plano seguinte.
  - A mudanca de plano e refletida na assinatura e comunicada ao Admin.

---

## Dominio: Consolidacao

### US-37 — Lancar decisao por Jesus e iniciar consolidacao
Como **Lider de Celula** ou **equipe de Consolidacao**, quero **registrar quando alguem decide por Jesus e iniciar a consolidacao**, para **que ninguem que aceitou Jesus fique sem acompanhamento**.
- **Interface:** acao/formulario "Lancar decisao" (a partir do detalhe do contato, da celula ou do relatorio de celula US-24) + reflexo no Dashboard de Consolidacao.
- **Criterios de aceite:**
  - E possivel lancar uma decisao por Jesus informando a pessoa (contato) e a origem (culto, celula, etc.).
  - Caso a pessoa ja participe/visite uma celula: o lider lanca e assume a consolidacao, e o sistema alerta o ministerio de consolidacao.
  - Caso seja visitante sem vinculo: a equipe de consolidacao lanca e e aberto o prazo de 24h para conecta-la a uma celula (ver US-40).
  - Ao lancar, a pessoa entra no Dashboard de Consolidacao na etapa inicial.

### US-38 — Dashboard de Consolidacao (acesso restrito)
Como **equipe de Consolidacao** (ou usuario com privilegio), quero **ver as pessoas em consolidacao**, para **acompanhar e agir no tempo certo**.
- **Interface:** dashboard/lista restrita de consolidacao.
- **Criterios de aceite:**
  - O acesso e restrito a equipe de consolidacao e usuarios com privilegio; demais papeis nao acessam.
  - Cada pessoa exibe seus dados, a celula que participa (quando houver) e a etapa atual da consolidacao.
  - A lista permite filtrar por etapa e destacar prazos estourados (ex.: 24h sem celula).

### US-39 — Acompanhar etapas e concluir a consolidacao
Como **equipe de Consolidacao**, quero **registrar o avanco das etapas e concluir a consolidacao (Universidade da Vida)**, para **saber quem ja foi consolidado**.
- **Interface:** detalhe da pessoa em consolidacao com etapas.
- **Criterios de aceite:**
  - A consolidacao (Universidade da Vida) possui etapas que podem ser marcadas como concluidas.
  - A conclusao da consolidacao e registrada manualmente pela equipe quando as etapas sao cumpridas.
  - Concluir a consolidacao NAO matricula a pessoa automaticamente na CD (Capacitacao Destino): a matricula aguarda a abertura da proxima turma. Ao concluir, a pessoa entra na "lista de aptos para a proxima turma da CD", refletida no cadastro da pessoa.
  - Ao concluir, a pessoa sai do Dashboard de Consolidacao.
  - *(Roadmap pos-MVP)* Lista de pessoas consolidadas com estatisticas/numeros de consolidacoes concluidas.

### US-40 — Pendencias de consolidacao (conexao a celula e fonovisita)
Como **Pastor/Admin** ou **equipe de Consolidacao**, quero **que as acoes de consolidacao virem pendencias com prazo**, para **garantir acompanhamento rapido**.
- **Interface:** itens de pendencia na fila de trabalho (US-16) + sinalizacao de prazo.
- **Criterios de aceite:**
  - Visitante sem vinculo gera pendencia "Conectar a celula" com prazo de 24h.
  - A fonovisita (contato/visita telefonica de acompanhamento) tambem gera pendencia de consolidacao.
  - O sistema alerta a equipe de consolidacao pelo WhatsApp oficial da igreja.
  - Ao concluir a acao (conexao a celula ou fonovisita realizada), a respectiva pendencia e baixada.
  - Pendencia de "Conectar a celula" nao baixada em 24h e destacada como atrasada.

---

## Dominio: Assistente do Sistema (no painel)

### US-41 — Assistente geral do sistema no painel
Como **usuario do painel** (Pastor/Admin, Lider ou demais papeis), quero **um assistente de IA no painel que conhece quem sou e o que posso acessar**, para **tirar duvidas do sistema e ser orientado nas tarefas**.
- **Interface:** chat/assistente acessivel dentro do painel.
- **Criterios de aceite:**
  - O assistente conhece o usuario logado e respeita seu papel/permissoes; nao expoe dados fora do escopo do usuario nem de outra igreja.
  - O assistente responde duvidas sobre o uso do sistema e explica as regras/logica do produto.
  - O assistente orienta o usuario em tarefas de preenchimento de dados.
  - As respostas ficam restritas ao contexto da igreja (tenant) do usuario.

---

## Dominio: Administracao da Plataforma (Super-Admin)

### US-42 — Gerir igrejas (tenants) do SaaS
Como **Admin do Sistema (Super-Admin)**, quero **ver e gerir as igrejas cadastradas na plataforma**, para **controlar todo o negocio do SaaS**.
- **Interface:** painel administrativo do SaaS com lista de igrejas (tenants).
- **Criterios de aceite:**
  - O Super-Admin visualiza todas as igrejas cadastradas, com status (ativa, pendente, inadimplente) e plano.
  - Cada igreja e um tenant isolado, com seus proprios dados e sua propria credencial de IA.
  - O painel do Super-Admin e separado e nao se mistura com o painel operacional das igrejas.

### US-43 — Provisionar nova igreja
Como **Admin do Sistema (Super-Admin)**, quero **criar uma nova igreja apos verificar o pagamento**, para **liberar o uso somente para quem contratou**.
- **Interface:** formulario de criacao de igreja no painel do Super-Admin.
- **Criterios de aceite:**
  - O Super-Admin verifica se o pagamento (mensalidade + setup) foi realizado antes de criar a igreja.
  - O Super-Admin decide criar ou nao a igreja.
  - Ao criar, preenche os dados necessarios para a igreja comecar a operar (ex.: nome da igreja, dados do Pastor/Admin inicial, plano).
  - A nova igreja nasce como tenant isolado, com seus proprios dados e configuracao de IA.

---

# 2. Requisitos Funcionais

## Autenticacao e Multi-tenant
- **RF-01** — O sistema deve autenticar usuarios via Clerk e estabelecer sessao. *(US-01)*
- **RF-02** — O sistema deve isolar todos os dados por igreja (tenant) usando RLS do Supabase, retornando apenas registros do tenant do usuario autenticado. *(US-02)*
- **RF-03** — O sistema deve permitir ao Admin convidar usuarios informando e-mail e papel, com envio de e-mail de ativacao via Brevo. *(US-03)*
- **RF-04** — O sistema deve permitir ao Admin listar e revogar acesso de usuarios da igreja. *(US-03)*
- **RF-05** — O sistema deve aplicar controle de acesso por papel (Pastor/Admin x Lider), restringindo telas, dados e acoes conforme o papel. *(US-04, US-22)*

## Conexao WhatsApp
- **RF-06** — O sistema deve gerar QR code via Evolution API para conectar o numero oficial da igreja e exibir o estado da conexao. *(US-05)*
- **RF-07** — O sistema deve permitir apenas um numero oficial conectado por igreja por vez. *(US-05)*
- **RF-08** — O sistema deve monitorar o status da conexao do WhatsApp e permitir reconexao. *(US-06)*
- **RF-09** — O sistema deve registrar e atuar exclusivamente sobre mensagens trocadas com o numero oficial, ignorando conversas de outros numeros. *(US-07)*

## Atendimento por IA
- **RF-10** — O sistema deve rotear toda mensagem recebida no numero oficial pelo agente orquestrador. *(US-08)*
- **RF-11** — O sistema deve gerar respostas automaticas via provedor LLM configurado pela igreja. *(US-08, US-27)*
- **RF-12** — O sistema deve criar/atualizar contato a partir das conversas, coletando no minimo nome e telefone e registrando origem e data do primeiro contato. *(US-09)*
- **RF-13** — O sistema deve executar um fluxo de onboarding para novos visitantes e registra-los como contato do tipo visitante. *(US-10)*
- **RF-14** — O sistema deve disponibilizar uma lista de conversas (inbox) e o historico cronologico de cada conversa. *(US-11)*

## Atendimento Humano
- **RF-15** — O sistema deve permitir assumir uma conversa, pausando a resposta automatica da IA, registrando responsavel e horario. *(US-12)*
- **RF-16** — O sistema deve permitir devolver a conversa para a IA, registrando o encerramento do atendimento humano. *(US-13)*
- **RF-17** — O sistema deve manter uma fila de atendimentos humanos aguardando, com tempo de espera e acao de assumir. *(US-14)*

## Painel / Fila de Trabalho Pastoral
- **RF-18** — O sistema deve exibir um dashboard com, no minimo, visitantes sem acompanhamento, atendimentos humanos aguardando e relatorios de celula pendentes, ordenados por prioridade. *(US-15)*
- **RF-19** — O sistema deve permitir acoes diretas nos itens da fila: assumir, resolver, atribuir a responsavel e devolver para IA. *(US-16)*
- **RF-20** — O sistema deve agrupar as proximas acoes por responsavel, incluindo grupo "Nao atribuido". *(US-17)*

## Visitantes e Contatos
- **RF-21** — O sistema deve listar visitantes sem acompanhamento, ordenaveis pelo tempo desde o primeiro contato. *(US-18)*
- **RF-22** — O sistema deve exibir o detalhe do contato com dados coletados, celula vinculada, status de acompanhamento e acesso a conversa. *(US-19)*
- **RF-23** — O sistema deve permitir vincular um contato a uma celula valida da igreja, encerrando o status "em acompanhamento" e marcando-o como "membro" da celula. *(US-20)*

## Celulas e Lideres
- **RF-24** — O sistema deve permitir criar, editar e inativar celulas, informando no minimo nome e lider responsavel. *(US-21)*
- **RF-25** — O sistema deve exibir o detalhe da celula com seus membros e visitantes vinculados. *(US-22)*
- **RF-26** — O sistema deve gerar alertas ao Lider, com base em gatilhos configuraveis e editaveis a qualquer momento, sobre contatos da sua celula que exigem acao, marcando o alerta como "tratado" ao baixar a acao. *(US-23)*

## Relatorio de Celula
- **RF-27** — O sistema deve coletar via WhatsApp os dados minimos do relatorio: celula, data, presentes, visitantes, decisoes por Jesus e observacoes, com confirmacao antes de registrar. *(US-24)*
- **RF-28** — O sistema deve listar relatorios por celula e data e exibir o detalhe completo de cada relatorio. *(US-25)*
- **RF-29** — O sistema deve identificar celulas sem relatorio no periodo esperado e gerar item de pendencia, baixado automaticamente ao receber o relatorio. *(US-26)*

## Configuracao de Agentes IA e Credencial LLM
- **RF-30** — O sistema deve permitir cadastrar credencial de provedor LLM (chave de API), armazenando-a protegida e validando-a antes de ativar. *(US-27)*
- **RF-31** — O sistema deve modelar a camada de provedor LLM como credencial configuravel, suportando OpenAI no MVP e extensivel a outros provedores. *(US-27)*
- **RF-32** — O sistema deve permitir configurar instrucoes/comportamento do agente, com efeito nas conversas seguintes. *(US-28)*
- **RF-33** — O sistema deve permitir criar, editar e desativar agendamentos (crons) de acoes do agente. *(US-29)*

## Calendario e Eventos
- **RF-34** — O sistema deve permitir criar eventos (titulo, data/hora, descricao) e sincroniza-los com o Google Calendar. *(US-30)*
- **RF-35** — O sistema deve exibir os eventos em um calendario com visoes por mes, semana e dia. *(US-30)*

## Comunicados, Consentimento e Opt-out
- **RF-36** — O sistema deve conceder consentimento automaticamente quando a pessoa inicia a conversa com o numero oficial (a igreja nunca inicia comunicacao espontanea) e registrar/exibir o status de consentimento de cada contato. *(US-31)*
- **RF-37** — O sistema deve permitir opt-out de comunicacao pelo WhatsApp e refletir o status no contato. *(US-32)*
- **RF-38** — O sistema deve permitir envio segmentado de comunicados pelo numero oficial, excluindo automaticamente contatos com opt-out ou sem consentimento. *(US-33)*

## Monetizacao e Assinatura
- **RF-39** — O sistema deve exibir os tres planos por porte com suas mensalidades e processar a contratacao via Asaas (PIX, boleto, cartao), cobrando o setup unico de R$ 1.000,00. *(US-34)*
- **RF-40** — O sistema deve ativar a assinatura da igreja apos confirmacao do pagamento. *(US-34)*
- **RF-41** — O sistema deve exibir status da assinatura (plano, valor, situacao e proxima cobranca). *(US-35)*
- **RF-42** — O sistema deve contar o porte pelo numero de pessoas cadastradas e promover automaticamente ao plano seguinte ao ultrapassar o limite, comunicando o Admin. *(US-36)*

## Consolidacao
- **RF-43** — O sistema deve permitir lancar uma decisao por Jesus e iniciar a consolidacao, tratando dois casos: (a) pessoa ja em celula — o lider assume e o ministerio de consolidacao e alertado; (b) visitante sem vinculo — a equipe de consolidacao assume com prazo de 24h para conexao a uma celula. *(US-37)*
- **RF-44** — O sistema deve oferecer um Dashboard de Consolidacao restrito a equipe/privilegiados, exibindo dados da pessoa, celula e etapa atual, com filtro por etapa e destaque de prazos estourados. *(US-38)*
- **RF-45** — O sistema deve permitir registrar etapas e concluir a consolidacao manualmente; ao concluir, marcar a pessoa como apta a proxima turma da CD no cadastro e remove-la do dashboard, sem matricula automatica. *(US-39)*
- **RF-46** — O sistema deve gerar pendencias de consolidacao na fila de trabalho — "Conectar a celula" (prazo 24h, destacada como atrasada se estourar) e "fonovisita" — alertar a equipe pelo WhatsApp e baixar a pendencia ao concluir a acao. *(US-40)*

## Assistente do Sistema
- **RF-47** — O sistema deve oferecer um assistente de IA no painel, ciente do usuario logado e de suas permissoes, capaz de responder duvidas de uso, explicar regras do sistema e orientar no preenchimento de dados, respeitando o isolamento por tenant. *(US-41)*

## Administracao da Plataforma (Super-Admin)
- **RF-48** — O sistema deve oferecer um painel de Super-Admin para gerir todas as igrejas (tenants), exibindo status e plano, separado do painel operacional das igrejas. *(US-42)*
- **RF-49** — O sistema deve permitir ao Super-Admin verificar o pagamento e provisionar uma nova igreja como tenant isolado, preenchendo os dados iniciais e o Pastor/Admin da igreja. *(US-43)*

---

# 3. Requisitos Nao-Funcionais

## Seguranca
- **RNF-01** — Toda autenticacao deve ser feita via Clerk; o sistema nao deve armazenar senhas proprias. *(Seguranca/Autenticacao)*
- **RNF-02** — O isolamento multi-tenant deve ser garantido em nivel de banco por RLS do Supabase, de forma que nenhuma consulta retorne dados de outra igreja. *(Seguranca/Autorizacao)*
- **RNF-03** — As credenciais de provedor LLM e chaves de integracao devem ser armazenadas cifradas e nunca exibidas em texto claro apos o cadastro. *(Seguranca)*
- **RNF-04** — Todo o trafego entre cliente e servidor deve ocorrer sobre HTTPS (TLS), com certificado automatico (Let's Encrypt via Coolify/Dokploy). *(Seguranca)*
- **RNF-05** — O acesso a funcionalidades deve respeitar o papel do usuario (Admin x Lider) em todas as requisicoes, inclusive no backend. *(Seguranca/Autorizacao)*
- **RNF-06** — O sistema deve registrar consentimento e suportar opt-out de comunicacao por contato, como boa pratica para dados pessoais e sensiveis (religiosos), facilitando formalizacao LGPD futura. *(Seguranca/Privacidade)*

## Performance
- **RNF-07** — O dashboard de pendencias deve carregar sua visao inicial em ate 3 segundos em conexao 4G tipica. *(Performance)*
- **RNF-08** — Mensagens recebidas no numero oficial devem ser processadas e roteadas pelo orquestrador em ate 5 segundos da chegada do webhook (excluindo tempo de resposta do provedor LLM). *(Performance)*
- **RNF-09** — As listas (inbox, contatos, relatorios) devem usar paginacao para responder em ate 2 segundos com ate 1.000 registros. *(Performance)*

## Usabilidade
- **RNF-10** — O painel deve ser web responsivo mobile-first e funcionar bem em navegador de celular e desktop. *(Usabilidade)*
- **RNF-11** — O painel deve ser instalavel como PWA (tela inicial, sem loja de apps). *(Usabilidade)*
- **RNF-12** — A interface deve priorizar a informacao de forma hierarquica (o urgente primeiro, o detalhe depois), coerente com o conceito de fila de trabalho pastoral. *(Usabilidade)*
- **RNF-13** — O usuario final (visitante, membro, lider enviando relatorio) deve interagir 100% pelo WhatsApp, sem instalar nada nem acessar o painel. *(Usabilidade)*
- **RNF-14** — Toda a interface do painel deve estar em portugues brasileiro. *(Usabilidade)*

## Confiabilidade
- **RNF-15** — Os processos sempre-ligados (LangGraph e Evolution API) devem rodar em modo persistente/stateful e reiniciar automaticamente apos falha (gestao de containers via Coolify/Dokploy). *(Confiabilidade)*
- **RNF-16** — Mensagens recebidas durante indisponibilidade ou desconexao do WhatsApp nao devem gerar contatos duplicados apos a reconexao. *(Confiabilidade)*
- **RNF-17** — O processamento de webhooks de mensagens deve ocorrer por meio de worker de filas, com reprocessamento em caso de falha temporaria. *(Confiabilidade)*

## Restricoes de plataforma e custo (MVP)
- **RNF-18** — Todo o stack do MVP (frontend Next.js, backend FastAPI + LangGraph, worker e Evolution API) deve rodar em uma unica VPS com no minimo 4GB de RAM. *(Restricao tecnica)*
- **RNF-19** — Nao deve haver app nativo (iOS/Android) no MVP; a experiencia mobile e atendida por web responsivo + PWA. *(Restricao de escopo)*
- **RNF-20** — O custo de LLM deve ficar fora do preco do PastorAI, usando a credencial BYO da propria igreja. *(Restricao de negocio)*

---

## Roadmap pos-MVP (fora do escopo do MVP)
> Funcionalidades validadas com o usuario, porem deliberadamente adiadas para depois do MVP enxuto.

- **Portal do Membro** — dashboard da propria celula na visao de membro: avisos da igreja, proxima celula, ultimas celulas, membros da celula, bate-papo da celula, solicitar conversa com pastor/lider.
- **Trilhas de formacao** — Universidade da Vida e Capacitacao Destino (acompanhamento das etapas onde a pessoa participa).
- **Aba de Gestao de Celula (Lider)** — materiais da central de celula, comunicados da liderança, planner de celula (planejamento das proximas celulas), metas recebidas da liderança e planejamento de multiplicacao.
- **Agente de IA de gestao da celula** — agente dedicado que conversa com o lider sobre a celula, lembra prazos e avisa de notificacoes da central/liderança (distinto do agente do WhatsApp de atendimento).
- **Ministerios e lideres de ministerio** — gestao por ministerio e visao do lider de ministerio.
- **RBAC hierarquico completo (G12)** — modelo "quem esta acima ve o que esta abaixo; quem esta abaixo nao ve o que esta acima" abrangendo membro, lider, lider de ministerio e niveis G12.

---

## Notas de cobertura (UI)
Padroes de interface identificados para a fase de Open Design: **tela de login**, **dashboard** (fila de trabalho), **Dashboard de Consolidacao** (acesso restrito), **listas** (inbox, contatos, visitantes, celulas, relatorios, usuarios, comunicados), **chat** (conversa WhatsApp), **telas de detalhe** (contato, celula, relatorio), **formularios/modais** (convite, celula, evento, comunicado, credencial LLM, agente, agendamentos), **calendario** (eventos), **tela de QR code** (conexao WhatsApp), **tela de planos/checkout**, **tela de assinatura/faturamento** e **painel de Super-Admin** (gestao de igrejas/tenants), alem de **assistente (chat) no painel**, **indicadores de status** e **estados vazios**.
