# Briefing inicial — PastorAi-1.0

Voce esta iniciando uma sessao no Open Design embarcada no LionClaw (pipeline Development V2).

## Hierarquia de prioridade

Siga esta ordem quando houver conflito:

1. **Schema do `lionclaw-design-contract` e Design Lock** — campos obrigatorios, JSON valido e rastreabilidade vencem tudo.
2. **Cobertura das user stories aprovadas** — nenhuma tela, menu, entidade, permissao ou acao pode existir sem userStoryIds ou delta explicito.
3. **Briefing de produto e mapa de telas** — organize o produto em telas reais e estados funcionais.
4. **Skill de Frontend de Alto Nivel** — melhora a qualidade visual, mas nao pode ampliar escopo nem quebrar contrato.

## Exigencias obrigatorias

- Gerar design **high-fidelity**, nao wireframe.
- Nao inventar telas, fluxos, permissoes ou entidades fora das user stories listadas abaixo.
- Gerar artifact HTML standalone (single file ou exportavel por este OD), clicavel localmente.
- Embutir o bloco `<script type="application/json" id="lionclaw-design-contract">{...}</script>` no artifact final.
- Responda e nomeie artefatos em portugues brasileiro (locale=pt-BR), salvo se o projeto configurar outro idioma.
- **Use `save_artifact` APENAS para HTML.** Markdown, prose, racional de design, decisoes ou explicacoes vao no chat — nao tente salvar como artifact (sera rejeitado pelo validator do OD).
- **NAO abra questionario, formulario de briefing, question-form ou discovery form.** Voce ja tem material suficiente. Se algo visual faltar, assuma defaults coerentes e continue.

## Defaults quando o briefing visual estiver incompleto

- Superficie principal: desktop web responsivo.
- Avaliador do prototipo: fundador tecnico / dev solo que precisa validar se o produto e implementavel.
- Tom visual: modern minimal + tech utilitario, com acabamento refinado e sem cara de landing page.
- Contexto de marca: escolha uma direcao propria, coerente com o produto e com a skill; nao peça brand spec, referencia visual ou screenshot.
- Escopo desejado: cobrir as user stories aprovadas no menor conjunto de telas funcionais.
- Restricoes adicionais: se algo estiver incerto, registre em `deltas[]` no contract e siga. So pare para perguntar se for impossivel gerar HTML valido.

## Formato OBRIGATORIO do artifact: SPA multi-tela navegavel

**Este e o ponto mais importante do briefing. Leia duas vezes.**

O artifact entregue NAO eh uma "gallery de telas", showcase, landing page, case-study, pitch deck, scroll-narrative, "design portfolio" ou pagina unica com sections empilhadas mostrando como cada tela ficaria. Esses formatos sao **proibidos**.

O artifact eh uma **Single Page Application clicavel** onde:

1. **Cada tela do contract (`screens[]`) = uma `<section>` HTML separada** com `id` igual ao `screens[].id` e atributo `hidden` por padrao.
2. **Apenas uma tela fica visivel por vez.** A troca de tela acontece por mudanca de `location.hash` (router minimo em JS inline) ou toggling de `hidden` em resposta a eventos reais (submit de `<form>`, click em botao de nav, etc.).
3. **Login com `<form>` real** (`<input type="password">`, etc.) que ao submit muda pra tela principal. Nada de "mockup decorativo" de login na mesma viewport da tela principal.
4. **Estados visuais** (idle / escutando / processando / falando, ou equivalente) sao **estados da mesma tela** alternados por interacao real (click no botao do microfone, etc.) — NAO sao 5 cards lado-a-lado mostrando "como ficaria cada estado".
5. **`navigation.primary[]` do contract precisa estar funcional**: os items listados ali precisam existir como elementos clicaveis no DOM que mudam de tela quando clicados.
6. Copy editorial / parrafos descritivos / "pitch" do produto / explicacoes sobre o design **NAO entram no HTML** — vao na resposta do chat.

### Regra anti-tela-empilhada [CRITICO]

Um `index.html` unico esta correto. O que e proibido e renderizar as telas uma abaixo da outra como uma pagina longa.

- Inclua CSS obrigatorio: `[hidden] { display: none !important; }`.
- No DOM inicial, as `section` de telas podem existir, mas **somente uma** pode estar visivel.
- A tela de login nao pode ficar acima do app shell nem aparecer junto com telas internas ao rolar a pagina.
- Telas internas como dashboard, crons, integracoes, runs, logs, cobranca e auditoria devem iniciar com `hidden`.
- O submit do login deve esconder `#login` e mostrar a primeira tela interna via JS real.
- Cliques na navegacao devem alternar `hidden` entre as sections, nao apenas rolar para anchors empilhadas.
- Se uma pessoa conseguir rolar e ver login + outra tela sem submeter login ou clicar na navegacao, o artifact esta invalido. Corrija antes de usar `save_artifact`.

Teste mental antes de salvar: "Um usuario abre o HTML, ve a tela 1 sozinha (login). Submete o form. Some a tela 1, aparece a tela 2 (principal). Clica no botao do mic. A orb muda de estado. Para de aparecer a tela 1 mesmo se rolar a pagina." Se qualquer parte desse teste falha (ex: ver login e main ao mesmo tempo ao rolar), o artifact esta errado.

## Briefing de produto e cobertura

Use o mapa abaixo para planejar telas antes de desenhar. Ele existe para evitar que o HTML vire uma copia literal das user stories.

### Mapa compacto de user stories

- US-01: Login no painel | ComoPastor/Admin, quero fazer login com minhas credenciais via Clerk, para acessar o painel da minha igreja com seguranca.
- US-02: Isolamento de dados por igreja (multitenant) | ComoPastor/Admin, quero ver e operar somente os dados da minha igreja, para garantir que nenhuma outra igreja acesse meus dados.
- US-03: Gestao de usuarios da igreja | ComoPastor/Admin, quero convidar e gerenciar usuarios (lideres) da minha igreja, para dar acesso ao painel a quem precisa.
- US-04: Controle de acesso por papel | ComoPastor/Admin, quero que cada papel veja apenas o que lhe compete, para manter decisoes sensiveis restritas.
- US-05: Conectar o numero oficial da igreja | ComoPastor/Admin, quero conectar o WhatsApp oficial da igreja lendo um QR code, para que o sistema receba e envie mensagens por esse numero.
- US-06: Monitorar e reconectar o WhatsApp | ComoPastor/Admin, quero ver se o WhatsApp da igreja esta online e reconectar quando cair, para nao perder mensagens de visitantes e lideres.
- US-07: Nao registrar conversas pessoais do pastor | ComoPastor/Admin, quero que apenas conversas com o numero oficial sejam registradas, para preservar a privacidade pastoral das conversas pessoais.
- US-08: Atendimento automatico de quem chama a igreja | ComoUsuario final via WhatsApp, quero ser atendido automaticamente ao chamar o numero da igreja, para receber resposta sem esperar um humano.
- US-09: Coleta de dados e criacao de contato pelo agente | ComoPastor/Admin, quero que o agente colete dados basicos do interlocutor e crie o contato, para que ninguem que fala com a igreja fique sem registro.
- US-10: Onboarding de contato/visitante pelo agente | ComoUsuario final via WhatsApp, quero ser recebido e cadastrado pelo agente de onboarding, para iniciar meu vinculo com a igreja.
- US-11: Lista de conversas (inbox) | ComoPastor/Admin ou usuario autorizado ao atendimento humano (ex.: secretaria), quero ver a lista de conversas do WhatsApp da igreja, para acompanhar o que esta acontecendo nos atendimentos.
- US-12: Assumir atendimento (pausar IA) | ComoPastor/Admin ou usuario autorizado ao atendimento humano (ex.: secretaria), quero assumir uma conversa e pausar a IA, para atender pessoalmente quando o caso exige sensibilidade humana.
- US-13: Devolver atendimento para a IA | ComoPastor/Admin ou Lider, quero devolver a conversa para a IA depois de atender, para que o agente retome o fluxo automatico.
- US-14: Fila de atendimentos humanos aguardando | ComoPastor/Admin, quero ver os atendimentos humanos que estao aguardando, para priorizar quem precisa de resposta agora.
- US-15: Dashboard de pendencias pastorais | ComoPastor/Admin, quero ver em segundos o que exige acao hoje, para reduzir a carga operacional e nao perder pessoas.
- US-16: Acoes diretas na fila de trabalho | ComoPastor/Admin, quero assumir, resolver, atribuir e devolver itens direto da fila, para agir sem trocar de tela.
- US-17: Proximas acoes por responsavel | ComoPastor/Admin, quero ver as proximas acoes agrupadas por responsavel, para saber quem esta com o que.
- US-18: Lista de visitantes sem acompanhamento | ComoPastor/Admin ou Lider, quero listar visitantes que ainda nao foram acompanhados, para conectalos a uma celula no tempo certo.
- US-19: Detalhe do contato | ComoPastor/Admin ou Lider, quero abrir o perfil de um contato, para ver seus dados, historico e situacao.
- US-20: Conectar visitante a uma celula | ComoPastor/Admin ou Lider, quero vincular um visitante a uma celula, para iniciar a consolidacao rapidamente.
- US-21: Cadastro de celulas | ComoPastor/Admin, quero cadastrar e editar celulas da igreja, para organizar a estrutura G12.
- US-22: Membros e visitantes de uma celula | ComoLider de Celula, quero ver os membros e visitantes da minha celula, para acompanhar meus liderados.
- US-23: Alertas sobre liderados | ComoLider de Celula, quero receber alertas sobre meus liderados, para agir quando alguem precisa de atencao.
- US-24: Enviar relatorio de celula pelo WhatsApp | ComoLider de Celula, quero enviar o relatorio semanal por mensagem no WhatsApp, para nao precisar acessar planilha ou painel.
- US-25: Visualizar relatorios de celula no painel | ComoPastor/Admin, quero ver os relatorios de celula no painel, para acompanhar a vida das celulas.
- US-26: Relatorio pendente vira acao na fila | ComoPastor/Admin, quero ver quais celulas nao enviaram o relatorio da semana, para cobrar os lideres pendentes.
- US-27: Cadastrar credencial do provedor LLM (BYO) | ComoPastor/Admin, quero cadastrar a chave de API do meu provedor de IA, para que a igreja use sua propria credencial e arque com o custo de LLM.
- US-28: Configurar comportamento do agente | ComoPastor/Admin, quero configurar com quem o agente fala e o que fala, para adaptar o atendimento ao tom da minha igreja.
- US-29: Configurar crons e agendamentos do agente | ComoPastor/Admin, quero configurar agendamentos (crons) para acoes do agente, para automatizar lembretes e rotinas.
- US-30: Gerir eventos no calendario | ComoPastor/Admin, quero cadastrar e visualizar eventos da igreja em um calendario, para organizar a agenda integrada ao Google Calendar.
- US-31: Registrar consentimento de comunicacao | ComoPastor/Admin, quero que o consentimento de cada contato seja registrado, para enviar comunicados apenas a quem aceitou.
- US-32: Optout de comunicacao | ComoUsuario final via WhatsApp, quero poder cancelar o recebimento de comunicados, para deixar de receber mensagens quando nao quiser mais.
- US-33: Envio segmentado de comunicados | ComoPastor/Admin, quero enviar comunicados a um segmento de contatos, para comunicar com controle e sem violar optout.
- US-34: Contratar assinatura com setup fee | ComoPastor/Admin, quero contratar a assinatura da minha igreja pagando a mensalidade e o setup, para ativar o uso do PastorAI.
- US-35: Acompanhar status da assinatura | ComoPastor/Admin, quero ver o status e os dados da minha assinatura, para saber se esta em dia.
- US-36: Upgrade automatico de plano por porte | ComoPastor/Admin, quero que o plano suba automaticamente quando ultrapassar o limite de pessoas, para nao precisar trocar de plano manualmente.
- (7 stories adicionais omitidas do mapa compacto; ainda devem ser cobertas se aparecerem nas fontes.)

## Design Plan aprovado antes do Open Design

Este e o blueprint de produto para o artifact visual. O schema do design-contract e o Design Lock continuam tendo prioridade maxima.
Plano deterministico gerado pelo LionClaw; validacao deterministica: aprovada.


Telas planejadas:
- login (Login) — Autenticar usuario antes de acessar dados protegidos. — stories: US-01
- principal (Principal) — Executar as principais tarefas do produto usando dados das stories aprovadas. — stories: US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09, US-10, US-11, US-12, US-13, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31, US-32, US-33, US-34, US-35, US-36, US-37, US-38, US-39, US-40, US-41, US-42, US-43

Navegacao planejada:
- Principal -> principal — stories: US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09, US-10, US-11, US-12, US-13, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31, US-32, US-33, US-34, US-35, US-36, US-37, US-38, US-39, US-40, US-41, US-42, US-43

Vocabulario obrigatorio de dominio:
- dashboard
- registros
- configuracao

Copy proibida ou arriscada:
- acesse seu ambiente
- painel operacional
- eleve sua produtividade

Dados fake recomendados:
(nao declarado)

Instrucoes especificas para Open Design:
- Gere uma SPA operacional, nao uma landing page.
- Use entidades concretas das user stories e evite copy generica.
- Nao escreva regras de negocio na tela; mostre apenas dados, estados, formularios e acoes.
- Gere os fluxos de todas as telas necessarias com navegacao clicavel.
- Arquivo unico index.html e permitido, mas telas empilhadas no scroll sao proibidas. Use [hidden] e JS real para mostrar apenas uma section por vez.

Cobertura planejada:
- US-01: principal — Cobertura deterministica.
- US-02: principal — Cobertura deterministica.
- US-03: principal — Cobertura deterministica.
- US-04: principal — Cobertura deterministica.
- US-05: principal — Cobertura deterministica.
- US-06: principal — Cobertura deterministica.
- US-07: principal — Cobertura deterministica.
- US-08: principal — Cobertura deterministica.
- US-09: principal — Cobertura deterministica.
- US-10: principal — Cobertura deterministica.
- US-11: principal — Cobertura deterministica.
- US-12: principal — Cobertura deterministica.
- US-13: principal — Cobertura deterministica.
- US-14: principal — Cobertura deterministica.
- US-15: principal — Cobertura deterministica.
- US-16: principal — Cobertura deterministica.
- US-17: principal — Cobertura deterministica.
- US-18: principal — Cobertura deterministica.
- US-19: principal — Cobertura deterministica.
- US-20: principal — Cobertura deterministica.
- US-21: principal — Cobertura deterministica.
- US-22: principal — Cobertura deterministica.
- US-23: principal — Cobertura deterministica.
- US-24: principal — Cobertura deterministica.
- US-25: principal — Cobertura deterministica.
- US-26: principal — Cobertura deterministica.
- US-27: principal — Cobertura deterministica.
- US-28: principal — Cobertura deterministica.
- US-29: principal — Cobertura deterministica.
- US-30: principal — Cobertura deterministica.
- US-31: principal — Cobertura deterministica.
- US-32: principal — Cobertura deterministica.
- US-33: principal — Cobertura deterministica.
- US-34: principal — Cobertura deterministica.
- US-35: principal — Cobertura deterministica.
- US-36: principal — Cobertura deterministica.
- US-37: principal — Cobertura deterministica.
- US-38: principal — Cobertura deterministica.
- US-39: principal — Cobertura deterministica.
- US-40: principal — Cobertura deterministica.
- US-41: principal — Cobertura deterministica.
- US-42: principal — Cobertura deterministica.
- US-43: principal — Cobertura deterministica.

Regras para usar este plano:
- Use este plano como mapa operacional, nao como copy literal.
- Nao mostre este plano, JSON, criterios internos ou racional no HTML.
- O HTML final deve mostrar apenas a SPA funcional do produto.
- Nao gere landing page, hero, pitch comercial, galeria de telas ou secoes explicativas.
- Um index.html unico e permitido; telas empilhadas no scroll sao proibidas.
- Inclua CSS `[hidden] { display: none !important; }` e JS real para alternar qual `section` esta visivel.
- Login e app shell nunca podem coexistir visualmente. Ao submeter login, esconda login e mostre a primeira tela interna.
- Gere os fluxos de todas as telas necessarias com navegacao clicavel.
- Nao escreva regra de negocio, criterio de aceite ou contrato como texto visivel na UI.



### Como transformar stories em telas

- Agrupe stories por tarefa do usuario, entidade de dados e momento do fluxo.
- Crie o menor conjunto de telas necessario para cobrir as stories, mas inclua estados internos ricos dentro de cada tela.
- Para cada tela planejada, defina antes de codar: objetivo, stories cobertas, acoes primarias, estados, dados exibidos/editados e destino de navegacao.
- Telas comuns esperadas quando fizer sentido: autenticacao, dashboard/listagem principal, detalhe/edicao, criacao/configuracao, revisao/resultado, estado vazio/erro.
- Nao transforme cada user story em uma tela separada se elas pertencem ao mesmo fluxo.
- Nao esconda fluxos importantes em texto estatico. Use botoes, formularios, filtros, tabs ou navegacao real.
- Antes de salvar, faça uma autocritica severa: se a tela principal pudesse servir para qualquer SaaS trocando palavras, esta ruim. Reescreva para o dominio do projeto.

## Skill aplicada: Frontend de Alto Nivel (adaptada para Open Design)

Esta skill e uma camada de craft visual. Ela NUNCA substitui escopo, contrato ou rastreabilidade por user stories.

Baseline ativo:
- DESIGN_VARIANCE: 8 — layouts assimetricos e memoraveis em desktop; mobile sempre colapsa para coluna unica sem scroll horizontal.
- MOTION_INTENSITY: 6 — microinteracoes e movimento fluido, mas sem comprometer performance.
- VISUAL_DENSITY: 4 — app web claro, arejado e usavel no dia a dia.

Regras de hierarquia:
1. Contract + Design Lock vencem qualquer decisao estetica.
2. Cobertura de user stories vence qualquer ideia visual.
3. Cada tela, navegacao, acao, dado e API precisa declarar userStoryIds reais.
4. Elementos sem rastreio entram em deltas[]; nao viram escopo final escondido.

Direcao de frontend:
- Evite UI generica de IA: nada de roxo/azul neon, blobs decorativos, H1 central gigante, 3 cards iguais, nomes falsos tipo Joao da Silva/Maria Santos, numeros redondos tipo 99,99%.
- Para software/dashboard, use sans-serif premium e limpa; nao use serif; nao use preto puro; use off-black/zinc ou base clara refinada.
- Maximo 1 cor de acento, dessaturada e consistente.
- Priorize telas funcionais sobre landing page. O produto deve parecer utilizavel, nao uma peca de marketing.
- Formulario: label acima, helper text na marcacao, erro abaixo do input, estados loading/empty/error/success/disabled quando aplicavel.
- Use grid e agrupamento logico; cards so quando comunicam hierarquia real.
- Motion apenas com transform/opacity; nada de animar top/left/width/height; loops ou efeitos pesados devem ser isolados.

Adaptacao ao artifact HTML do Open Design:
- Gere HTML standalone clicavel. Nao importe React/Next/Tailwind/Framer a menos que o runtime do OD ja esteja explicitamente usando isso.
- Se precisar de icones, use SVG limpo inline. Emojis sao proibidos no HTML, labels e alt text.
- Aplique o espirito da skill no HTML/CSS/JS final: assimetria controlada, composicao premium, estados completos e interacoes reais.

## Fontes originais para conferencia

As fontes abaixo sao referencia de escopo. Nao copie blocos inteiros para a UI; extraia telas, estados, dados e acoes.

### Discovery

# Discovery Notes

## Visao

### Problema
Igrejas perdem processos humanos importantes porque tudo fica espalhado em WhatsApp, caderno, planilha, memoria da equipe e grupos informais. Na pratica:
- visitantes entram em contato e nao recebem acompanhamento no tempo certo;
- lideres deixam de enviar relatorios;
- pessoas aceitam Jesus mas nao sao conectadas rapidamente a uma celula;
- consolidacao depende de cobranca manual;
- pastores nao sabem com clareza quem precisa de acao urgente;
- comunicados saem sem controle de consentimento, opt-out ou segmentacao.

O PastorAI resolve isso criando uma ponte entre WhatsApp, agentes de IA, banco de dados e um painel operacional que funciona como fila de trabalho pastoral. O objetivo e reduzir a carga operacional do pastor e das equipes, transformando mensagens soltas em acoes pastorais organizadas (quem atender, qual visitante esta sem acompanhamento, qual lider nao enviou relatorio, o que precisa ser feito hoje).

### Usuario principal
Dois protagonistas:

1. **Pastor / Admin da Igreja** — responsavel maximo pela igreja no sistema. Abre o painel para enxergar pendencias pastorais (visitantes sem acompanhamento, atendimentos humanos aguardando, relatorios pendentes), tomar decisoes sensiveis, acompanhar celulas, lideres e relatorios. Precisa entender em poucos segundos o que exige acao hoje.

2. **Lider de Celula** — esta na linha de frente da operacao semanal. Envia relatorio da celula pelo WhatsApp, acompanha membros e visitantes da sua celula, planeja e realiza a celula, indica discipulos para trilhas e recebe alertas sobre seus liderados.

Esses dois perfis sao os que mais sentem a dor operacional e os que mais percebem o valor do produto no dia a dia.

### Referencia
- **BotConversa** — referencia para gestao de conversas de WhatsApp e tambem referencia de design system / identi

... (discovery compactado — 7523 chars omitidos; use como fonte de conferencia, nao como copy literal) ...

).
- **Principio de UX desejado:** interface **logica e organizada de forma hierarquica** — informacao priorizada (o urgente primeiro, o detalhe depois), coerente com o conceito de painel como "fila de trabalho pastoral".
- A identidade visual definitiva (logo, paleta de cores) ainda sera definida; o agente de geracao pode propor com base no design system inspirado no BotConversa.

### Notas adicionais
- **Igreja piloto:** Igreja Batista Filadelfia Internacional de Corrente (a propria igreja do fundador) — cenario ideal para validar rapido, com acesso direto aos usuarios e iteracao sem burocracia.
- **Equipe:** desenvolvimento **solo** (fundador desenvolve sozinho) — reforca a estrategia de MVP enxuto e stack economica/consolidada para reduzir esforco de manutencao.
- **LGPD:** nao e exigencia formal nesta fase. Observacao: o sistema lida com dados pessoais e religiosos (sensiveis); o plano ja preve consentimento e opt-out de comunicacao, o que e boa pratica e facilita formalizar LGPD no futuro, se desejado.

### User Stories e Requisitos aprovados

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
  - Credenciais invalidas exibem mensagem de er

... (stories-requisitos compactado — 39283 chars omitidos; use como fonte de conferencia, nao como copy literal) ...

*Ministerios e lideres de ministerio** — gestao por ministerio e visao do lider de ministerio.
- **RBAC hierarquico completo (G12)** — modelo "quem esta acima ve o que esta abaixo; quem esta abaixo nao ve o que esta acima" abrangendo membro, lider, lider de ministerio e niveis G12.

---

## Notas de cobertura (UI)
Padroes de interface identificados para a fase de Open Design: **tela de login**, **dashboard** (fila de trabalho), **Dashboard de Consolidacao** (acesso restrito), **listas** (inbox, contatos, visitantes, celulas, relatorios, usuarios, comunicados), **chat** (conversa WhatsApp), **telas de detalhe** (contato, celula, relatorio), **formularios/modais** (convite, celula, evento, comunicado, credencial LLM, agente, agendamentos), **calendario** (eventos), **tela de QR code** (conexao WhatsApp), **tela de planos/checkout**, **tela de assinatura/faturamento** e **painel de Super-Admin** (gestao de igrejas/tenants), alem de **assistente (chat) no painel**, **indicadores de status** e **estados vazios**.

## Notas adicionais do PRD Validator

(prd-validator ausente)

## Design System

- (nenhum design system selecionado — usar default coerente com o briefing)

## Configuracao da sessao (somente metadados — nao contem credenciais)

```json
{
  "agentId": "configured-in-open-design-studio",
  "model": "configured-in-open-design-studio",
  "reasoning": null,
  "designSystemId": null,
  "memoryEnabled": false,
  "mcpServerIds": [],
  "locale": "pt-BR"
}
```

## Entrega esperada

- **SPA multi-tela** seguindo o "Formato OBRIGATORIO" acima — um `<section>` por screen, um visivel por vez, transicoes por interacao real.
- `index.html` standalone unico e permitido; telas empilhadas no scroll sao proibidas.
- Bloco `lionclaw-design-contract` embutido no HTML EXATAMENTE no shape definido abaixo.
- Texto e copy em pt-BR **dentro das telas funcionais** — sem prose marketing, sem hero copy editorial, sem "## Sobre o produto", sem pitch.

Se uma user story exigir interpretacao, use o contexto disponivel, registre a decisao em `deltas[]` quando necessario e continue. Nao bloqueie a entrega com perguntas de briefing visual.

## Schema OBRIGATORIO do bloco `lionclaw-design-contract`

Este JSON eh consumido pelo validator do LionClaw. **Qualquer campo extra eh permitido, mas TODOS os campos abaixo sao obrigatorios** — sem isso o Design Lock rejeita.

```html
<script type="application/json" id="lionclaw-design-contract">
{
  "version": "1.0",
  "visual": {
    "direction": "string descritiva da direcao visual (ex: 'software dark utilitario com acento amber')",
    "density": "dense | balanced | editorial | mobile-first | unknown",
    "tokens": {
      "colors": { "bg": "#09090b", "accent": "#d97706", "...": "..." },
      "typography": { "display": "Geist", "body": "Satoshi", "...": "..." },
      "spacing": { "xs": "4px", "sm": "8px", "...": "..." },
      "radii": { "sm": "4px", "md": "8px", "...": "..." }
    }
  },
  "navigation": {
    "primary": [
      { "id": "nav-play", "label": "Jogar", "targetScreenId": "play", "userStoryIds": ["US-02"] }
    ],
    "secondary": []
  },
  "screens": [
    {
      "id": "login",
      "userStoryIds": ["US-01"],
      "title": "Login",
      "route": "#login",
      "purpose": "Autenticar usuario",
      "states": ["loading", "error", "success"],
      "actions": [
        { "id": "action-login", "label": "Entrar", "type": "submit", "userStoryIds": ["US-01"], "apiExpectationIds": ["api-login"] }
      ],
      "dataRequirementIds": ["data-user-login"]
    }
  ],
  "components": [
    { "id": "btn-primary", "name": "Botao primario", "type": "form", "usedInScreenIds": ["login"], "props": {}, "states": [] }
  ],
  "dataRequirements": [
    {
      "id": "data-user-login",
      "name": "Credenciais de login",
      "description": "Dados informados pelo usuario para autenticacao",
      "fields": [
        { "name": "email", "typeHint": "string", "required": true },
        { "name": "password", "typeHint": "string", "required": true }
      ],
      "sourceScreenIds": ["login"],
      "userStoryIds": ["US-01"]
    }
  ],
  "apiExpectations": [
    {
      "id": "api-login",
      "operation": "POST /auth/login",
      "screenIds": ["login"],
      "actionIds": ["action-login"],
      "methodHint": "POST",
      "requestShape": { "email": "string", "password": "string" },
      "responseShape": { "token": "string" },
      "userStoryIds": ["US-01"]
    }
  ],
  "deltas": [
    {
      "id": "delta-001",
      "type": "unclear",
      "description": "explicacao do delta",
      "impact": "low",
      "relatedUserStoryIds": [],
      "requiresRequirementsChange": false
    }
  ]
}
</script>
```

**Regras criticas:**
- `version` deve ser literalmente `"1.0"`.
- Cada `screens[]`, `navigation.primary[]` e `dataRequirements[]`/`apiExpectations[]` referencia user stories por `userStoryIds: string[]` (use os IDs reais do briefing, ex: `"US-01"`).
- Cada `apiExpectations[]` precisa declarar `screenIds: string[]`, `actionIds: string[]` e `userStoryIds: string[]`, mesmo que algum deles seja `[]`.
- Cada `dataRequirements[]` precisa declarar `fields[]`, `sourceScreenIds: string[]` e `userStoryIds: string[]`.
- Telas/componentes/dados/APIs SEM user story listada → registrar como `deltas[]` com `description` explicando por que existe.
- `components[]`, `apiExpectations[]`, `dataRequirements[]` e `deltas[]` exigem `id: string` unico.
- `deltas[]` exige `type`, `description`, `impact`, `relatedUserStoryIds` e `requiresRequirementsChange`.
- Use os 4 grupos de tokens (`colors`, `typography`, `spacing`, `radii`) mesmo que parcialmente vazios — eles sao obrigatorios na estrutura.

Campos adicionais ao schema (ex: `project`, `design_system`, `acceptance_criteria_visualized`) sao tolerados, mas os campos acima nao podem faltar.
