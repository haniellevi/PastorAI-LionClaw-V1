# Prompt para o Claude Designer — Protótipo do módulo Células (Igreja 12)

> Rascunho preparado em 2026-07-02. Copiar o bloco abaixo (a partir de "## O que você vai construir")
> para o Claude Designer. Não commitado — arquivo de trabalho.

---

## O que você vai construir

Um **protótipo HTML navegável do módulo Células** do **Igreja 12** — SaaS de gestão pastoral para igrejas do modelo G12 (jornada ganhar → consolidar → discipular → enviar). O app já existe em produção (Next.js, SPA com sidebar escura, mobile-first, PWA); este protótipo precisa parecer uma **extensão nativa** dele, seguindo à risca o design system da seção 3 — os tokens abaixo foram extraídos do CSS real do produto.

O protótipo cobre **três recortes**, que no produto vivem em lugares diferentes da navegação:

1. **Líder de Célula** — gestão da própria célula (menu **Células**)
2. **Discípulo** — membro da célula, visão minimalista (menu **Células**)
3. **Central de Células** — supervisão da rede (fica em **Jornada G12 → Discipular → Central de Célula**, para admin / líder da central — **não** é uma aba do menu Células)

> A Árvore Ministerial (organograma de quem lidera quem) é um módulo à parte da célula e **não** faz parte deste protótipo — só é citada como destino da multiplicação aprovada.

## 1. Formato do entregável

- **Um único arquivo HTML autocontido**: todo CSS e JS inline. Sem CDN de scripts/CSS. Fontes: pode incluir `<link>` do Google Fonts para **Plus Jakarta Sans** (400/500/600/700), **Sora** (600/700/800) e **JetBrains Mono** (400/500), mas sempre com fallback de sistema (`-apple-system, "Segoe UI", system-ui, sans-serif`) — o arquivo precisa continuar apresentável sem internet.
- **SPA por hash**: uma tela visível por vez (ex.: `#central-dashboard`, `#lider-discipulos`, `#discipulo`). Proibido "telas empilhadas" uma embaixo da outra.
- **Switcher de contexto** fixo e discreto (barra própria acima do app ou botão flutuante), rótulo "Protótipo — visão:": `Líder · Discípulo · Central`. É apenas um **atalho de navegação do protótipo** para pular entre os três recortes — **não** é um seletor de papel do produto e **não** implica que a Central seja uma terceira aba do menu Células. Deixe isso visualmente claro (fundo escuro, o rótulo "Protótipo"). Estrutura real que o menu deve refletir (ver 2.x): **menu Células = só Líder + Discípulo**; a **Central de Células vive dentro de "A Jornada G12 → Discipular → Central de Célula"**.
- **Dados mock realistas em pt-BR** (seção 8), datas em 2026. Interações simuladas em JS: trocar abas, abrir/fechar modais, marcar checkboxes, avançar wizard, toasts. Nada persiste.
- **Responsivo de verdade**: desktop (≥1280px) e mobile 390px. Breakpoint principal **≤860px**: sidebar vira drawer, aparece bottom-nav fixa. Sem scroll horizontal em nenhuma largura ≥360px.
- Todos os textos em Português do Brasil, com acentuação correta.

## 2. Shell do app (replicar o produto real)

- **Grid desktop**: `sidebar 248px | main 1fr`, altura `100dvh`, `overflow hidden` no grid; só a área de conteúdo (`.screen`) rola.
- **Sidebar escura**: fundo `radial-gradient(120% 120% at 30% 0%, oklch(31.8% 0.047 186), oklch(26.8% 0.038 187) 55%, oklch(23.1% 0.032 188))`. Marca: quadrado 24px arredondado com "12" (Sora 800) em fundo `--accent`, ao lado do nome "Igreja 12". Abaixo, card da igreja ativa (fundo `oklch(26% 0.012 187)`). Títulos de grupo: 10px, 700, uppercase, `letter-spacing .16em`, cor `oklch(62% 0.015 187)`. Item de nav: 13.5px/500, cor `oklch(86% 0.025 187)`, raio 10px, com bloco de ícone 27px; hover fundo `oklch(26% 0.012 187)`; **ativo**: fundo `color-mix(in oklch, var(--accent) 18%, transparent)`, texto mint `--accent-bright`, peso 640.
- **Topbar sticky**: fundo `color-mix(in oklch, var(--bg) 82%, transparent)` + `backdrop-filter: blur(10px)`, borda inferior; eyebrow do grupo (10px uppercase; some ≤860px), título h1 17px, chips de papel do usuário à direita (pílulas 10.5px).
- **Conteúdo**: `.screen` com `padding: 24px` e cabeçalho `screen-head` (h2 + ações à direita).
- **Mobile ≤860px**: 1 coluna; sidebar como drawer (translateX); **bottom-nav** fixa (borda superior, fundo branco, `padding-bottom: env(safe-area-inset-bottom)`, itens de 52px com ícone 22px e rótulo 11px, ativo em `--accent`). Itens da bottom-nav por visão: Líder → Painel / Discípulos / Planejar / Mais; Discípulo → só a tela única (bottom-nav opcional); Central → Painel / Células / Solicitações / Mais.

### Menu lateral por papel

A sidebar do app tem a estrutura fixa de grupos (replicar sempre, mesmo itens inertes): grupo **"Igreja"** (Painel de Hoje · Agenda · Conversas), grupo **"A Jornada G12"** (Ganhar · Consolidar · Discipular · Enviar) e grupo **"Gestão"** (Pessoas · Comunicação). O que muda por visão:

- **Líder** (menu **Células**, dentro de "Gestão" ou como grupo próprio "Minha Célula"): Painel da Célula · Discípulos · Planejar Célula · Relatório · Multiplicação · Avisos · Editar Célula. **A Central NÃO aparece aqui.**
- **Discípulo** (menu **Células**): item único "Minha Célula". Menu enxuto, sem os grupos administrativos.
- **Central de Células**: **NÃO é um grupo à parte** — é o sub-item **"Central de Célula"** dentro de **A Jornada G12 → Discipular** (ao lado de "G12 · Descendências"/Árvore Ministerial). Ao entrar nela, o conteúdo abre com suas próprias abas/telas internas: Painel da Central · Gerenciar Células · Solicitações (badge com nº pendentes) · Avisos · Materiais de Apoio · Líderes. No protótipo, expanda "Discipular" e destaque "Central de Célula" como ativo quando estiver nessas telas.

## 3. Design system — tokens obrigatórios (extraídos do produto)

Use exatamente estas variáveis. Não invente cores fora delas.

```css
:root {
  /* superfícies & neutros */
  --bg: oklch(94% 0.005 183);
  --surface: oklch(100% 0 0);
  --surface-2: oklch(96.5% 0.003 174);
  --surface-3: oklch(95% 0.004 180);

  /* tinta (verde-petróleo) */
  --fg: oklch(31.8% 0.047 186);
  --muted: oklch(41.1% 0.024 184);
  --faint: oklch(72% 0.016 182); /* NUNCA em texto informativo — reprova contraste AA */

  /* bordas */
  --border: oklch(91.5% 0.008 177);
  --border-strong: oklch(87.5% 0.014 181);

  /* acento teal + mint */
  --accent: oklch(53.5% 0.108 186);
  --accent-fg: oklch(99% 0.01 185);
  --accent-soft: oklch(95.8% 0.016 187);
  --accent-dark: oklch(46% 0.092 186);
  --accent-bright: oklch(85.5% 0.125 181); /* mint — só estados ativos/decoração */

  /* estados */
  --ok: oklch(62.7% 0.17 149);     --ok-soft: oklch(96.2% 0.043 157);
  --warn: oklch(55% 0.146 58);     --warn-soft: oklch(96.2% 0.058 96);
  --danger: oklch(57.7% 0.215 27); --danger-soft: oklch(97.1% 0.013 17);
  --info: oklch(58.8% 0.139 242);  --info-soft: oklch(95.1% 0.025 237);
  --whatsapp: oklch(76.1% 0.201 150);

  /* raios & espaços */
  --r-sm: 10px; --r-md: 12px; --r-lg: 16px;
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px; --s5: 24px; --s6: 32px; --s7: 48px;

  /* tipografia */
  --font: "Plus Jakarta Sans", -apple-system, "Segoe UI", system-ui, sans-serif;
  --font-display: "Sora", var(--font);
  --mono: "JetBrains Mono", ui-monospace, Menlo, monospace;

  /* sombras & foco */
  --shadow: 0 1px 2px oklch(31.8% 0.047 186 / 0.05), 0 8px 24px oklch(31.8% 0.047 186 / 0.09);
  --shadow-primary: 0 8px 20px oklch(53.5% 0.108 186 / 0.32);
  --ring: 0 0 0 3px oklch(53.5% 0.108 186 / 0.16);
  --grad-brand: linear-gradient(135deg, oklch(53.5% 0.108 186), oklch(46% 0.092 186));
}
body { font-family: var(--font); font-size: 14px; line-height: 1.5; color: var(--fg); background: var(--bg); }
h1,h2,h3,h4,.btn,.val { font-family: var(--font-display); }
```

### Componentes (replicar o estilo do produto)

- **Botão** `.btn`: Sora, `padding 9px 14px`, raio 10px, 13.5px/560, fundo `--surface-2`, borda `--border-strong`. Primário: fundo `--accent`, texto `--accent-fg`, `--shadow-primary`. Variantes ghost, danger (texto `--danger`, hover `--danger-soft`) e `sm` (`5px 9px`, 12.5px). Focus sempre com `--ring`. Loading com spinner 15px.
- **Card**: fundo `--surface`, borda `--border-strong`, raio 16px, `--shadow`. Cabeçalho `.panel-title`: 13.5px Sora 600, padding 16px, borda inferior, contador em `--muted`.
- **Stat-card** (KPIs): grid de 4 colunas (2 em ≤980px); rótulo 12.5px `--muted` com ícone 15px em `--accent`; valor Sora 30px/640; variação `.alert` com valor em `--warn`.
- **Pill de status**: pílula 11.5px/560, `padding 2px 8px`, dot de 6px em `currentColor`. Tons: `ok` (fundo `--ok-soft`, texto verde escuro), `warn`, `danger`, `accent`, `muted`, `info`.
- **Tabs**: trilho com fundo `--surface-2`, `padding 3px`, raio 10px; aba 12.5px/540 em `--muted`; ativa com fundo `--surface`, texto `--fg` e sombra leve. Contador na aba (` · N`).
- **Modal**: overlay `oklch(20% 0.02 186 / 0.32)`, caixa max-width 420px (ou 560px para wizard), raio 16px, animação sutil de subida (0.18s); cabeçalho com título 14px + botão "Fechar" ghost; rodapé com ações à direita. Em ≤600px, selects e botões com `min-height 44px`.
- **Toast**: fixo embaixo centralizado, fundo `--surface`, borda, sombra, 13px; ícone verde (`ok`) ou vermelho (`err`); some sozinho (~3.2s).
- **Empty state**: centrado, `padding 48px`, ícone 40px em `--border-strong`, texto `--muted` ("**Frase forte.** complemento").
- **Formulários**: label 12.5px/560; inputs `padding 9px 11px`, raio 10px, borda `--border-strong`; focus com borda `--accent` + `--ring`; helper 12px `--muted`.
- **Linhas de lista** `.list-row`: `padding 12px 16px`, borda inferior `--border`, hover `--surface-2`; nome 13.5px/560, subtítulo 12px `--muted`.
- **Tabela → cards no mobile** (≤600px): cada `td` empilha com rótulo via `data-label`.
- **Acessibilidade**: contraste AA em todo texto; `--faint` proibido em informação útil; alvos de toque ≥44px no mobile; `prefers-reduced-motion` neutraliza animações; foco visível sempre.

## 4. Convenções específicas do módulo Células

- **Avisos da igreja/central** → tom **vermelho** (`--danger` / `--danger-soft`). **Avisos da célula** → tom **azul** (`--info` / `--info-soft`). Aplicar como borda esquerda de 3px + fundo soft no card do aviso.
- **Presença/saúde**: bolinha **verde** (`--ok`) = presente / relatório enviado; bolinha **vermelha** (`--danger`) = ausente / relatório não enviado. Bolinhas de 8–10px em fileira, com `title` acessível.
- **Pendência cadastral do discípulo**: triângulo/dot **amarelo** (`--warn`) ao lado do nome.
- **Solicitações**: pill `warn` "Aguardando aprovação" → `ok` "Aprovada" → `danger` "Rejeitada".
- **Selo "Apto a liderar"**: pill `accent`. Aptidão = a pessoa **realizou o Reencontro** (não é a CD). Todo **líder de célula já é apto implicitamente** — não exibir o selo redundante em quem já lidera; o selo destaca membros aptos que ainda **não** lideram (candidatos a novo líder / a consolidar).
- **Programação padrão da célula** (8 etapas, sempre nesta ordem e com estes tempos):
  1. Boas-vindas — 2 min
  2. Louvor — 5 a 10 min
  3. Quebra-gelo — 5 min
  4. Mensagem — 20 min
  5. Oração por Necessidades — 5 min
  6. Oração de Salvação — 5 min
  7. Oferta — 5 min
  8. Comunhão — 10 min

## 5. Visão CENTRAL DE CÉLULAS

### 5.1 `#central-dashboard` — Painel da Central
- Fileira de stat-cards: **Total de células** · **Relatórios da semana** (ex.: "6 de 8" + pill com % recebidos; não recebidos em `--warn`) · **Visitantes no mês** · **Participantes no mês** · **% da igreja em células** (percentual de membros da igreja que participam de célula).
- Card **"Saúde das células"**: uma linha por célula — nome + líder à esquerda, fileira de **10 bolinhas** à direita (últimas 10 semanas: verde = relatório enviado, vermelha = não houve/relatório não enviado). Clicar na linha abre o painel da célula (5.2).
- Card lateral **"Solicitações pendentes"** (atalho para 5.3) com contador.

### 5.2 `#central-celulas` — Gerenciar Células
- Cabeçalho com **busca por nome do líder** e **filtro por descendência** (select: "Todas · Desc. Pr. Rafael · Desc. Pra. Ana…" — descendência = ramo do G12 pastoral).
- Botão primário **"Nova célula"** → modal de cadastro: **cobertura espiritual*** (select de líderes G12), **líder*** (select, só pessoas com selo "Apto a liderar"), **nome***, **local/endereço**, **link da localização (mapa)**, **dia da semana***, **horário*** (HH:MM). A cobertura é obrigatória — toda célula está debaixo de uma cobertura espiritual.
- Lista/grade de células (card por célula): nome, líder, dia · hora, nº membros, nº visitantes, mini-fileira de saúde (últimas 5 bolinhas), pill Ativa/Inativa.
- Clicar numa célula → **painel de detalhe** (coluna lateral no desktop, tela cheia no mobile): dados completos, solicitações daquela célula, saúde (10 bolinhas), e um bloco **"Trilha da visão"** com os mesmos contadores que o líder vê (ver 6.1, versão compacta).

### 5.3 `#central-solicitacoes` — Solicitações
- Tabs: **Multiplicações · Alterações sensíveis · Histórico**.
- **Multiplicação pendente** (linha expandível ou modal): célula de origem, líder atual, **novo líder** (com selo Apto), membros que irão (lista com contagem), dia/hora, endereço, anfitrião, data prevista. Ações: **Aprovar** (primário) e **Rejeitar** (danger, pede motivo em textarea). Texto de apoio: "Ao aprovar, a nova célula é criada, os membros são transferidos e a Árvore Ministerial é atualizada."
- **Alteração sensível** pendente: a Central aprova qualquer mudança de dado sensível da célula — **dia, horário, endereço, anfitrião, auxiliar, entrada/saída de membros**. Mostrar tipo da alteração, célula, líder, valor atual → valor proposto (ex.: "Dia: Quinta 20:00 → Terça 19:30"; ou "Anfitrião: Roberto Lima → Marcos Paulo"; ou "Saída de membro: Larissa Almeida"), motivo do líder. Aprovar / Rejeitar (com motivo).
- Aba Histórico: linhas com pill do desfecho. Incluir um estado em que a lista está **vazia** (empty state: "Nenhuma solicitação pendente.").

### 5.4 `#central-avisos` — Avisos
- Botão "Novo aviso" → modal: **título***, **mensagem***, **para quem*** (chips selecionáveis: Todos · Homens · Mulheres · Jovens · Casais · Líderes específicos — este último abre um campo de busca com multi-seleção de líderes), **quando** (Agora · Agendar → date+time).
- Lista de avisos enviados/agendados (título, público, quando, pill Enviado/Agendado). Avisos da central aparecem para líderes e discípulos **em vermelho** (convenção da seção 4).

### 5.5 `#central-materiais` — Materiais de Apoio
- Tabs: **Sermões · Quebra-gelos · Músicas**.
- Busca por tema + chips de tags (ex.: "família", "fé", "comunhão", "jovens").
- Sermões: cards com título, resumo curto, tags, botão "Ver". Quebra-gelos: título + descrição curta + tags. Músicas: **nome + link** (ícone de link externo) + tags.
- Botão "Adicionar material" → modal simples (tipo, título, conteúdo/link, tags).
- Nota visível: estes materiais alimentam o "Material disponível" do líder (6.3).

## 6. Visão LÍDER DE CÉLULA

### 6.1 `#lider-dashboard` — Painel da Célula
- Cabeçalho: nome da célula + pill Ativa + "Quinta · 20:00 · Casa do Roberto".
- **Se passou do horário da última reunião prevista e o relatório não foi enviado** (simule este estado): banner GRANDE no topo, tom `--warn`/`--danger-soft`, ícone de alerta: "**Relatório pendente!** A célula de quinta (10/09) ainda não teve o relatório enviado." + botão primário "Enviar relatório agora" (vai para 6.4). Este banner aparece 2h após o horário previsto — deixe isso escrito num microtexto.
- KPIs da trilha da visão (stat-cards compactos, pode ser strip de 2 fileiras): **Reuniões realizadas** · **Visitantes (histórico)** · **Membros** · **Precisam aceitar Jesus (Ganhar)** · **Em consolidação** · **Na UV atual** · **Concluíram a UV** · **Batizados** · **Fazendo a CD** · **Fizeram Reencontro** · **Formados na CD**.
- Card "Próxima célula": data/hora, status (Planejada/Confirmada), atalho para Planejar (6.3).
- Card "Avisos ativos" (mistos: igreja em vermelho, célula em azul).

### 6.2 `#lider-discipulos` — Discípulos
- Lista **numerada em ordem alfabética**, com o **Auxiliar sempre em 1º lugar** (destaque: pill `accent` "Auxiliar"). Anfitrião marcado com pill `muted` "Anfitrião".
- Cada linha: nº, avatar de iniciais, nome, **5 bolinhas das últimas 5 reuniões** (verde presença, vermelha ausência), e **alerta amarelo** quando há dado cadastral pendente.
- Botão "Adicionar participante" → modal com dados básicos (nome*, WhatsApp*, nascimento, endereço).
- Clicar no discípulo → **ficha completa** (modal wide ou tela):
  - Cabeçalho: nome, idade, pills (etapa da trilha, Auxiliar/Anfitrião se for o caso).
  - **Próxima meta na trilha** (ganhar → consolidar → discipular → enviar), ex.: "Concluir a Universidade da Vida".
  - **Atividades na célula**: participações na programação, ex.: "Quebra-gelo — 12/06/2026 · Oferta — 28/05/2026".
  - **Presenças**: as 5 bolinhas + taxa (ex.: "4 de 5").
  - **Dados pessoais**: aniversário; **família** (parentes que moram com ele, cada um com marcador "da igreja"/"não é da igreja"); **atividade principal** (Estudante/Empresário/Funcionário + horário de ocupação); **maior sonho**; **maior dificuldade**; **como gostaria de servir na igreja**.
  - Campos vazios ganham o alerta amarelo + botão "Atualizar cadastro" (a atualização cadastral é responsabilidade do líder).
  - Ações no rodapé: "Definir como auxiliar" / "Definir como anfitrião".

### 6.3 `#lider-planejar` — Planejar Célula
- Bloco de status no topo: "Próxima célula: **quinta, 17/09 · 20:00**" + pill (Não confirmada / Confirmada) + botão primário **"Confirmar e planejar"**.
- Sub-aba/card **"Material disponível"**: os materiais da central (5.5) com busca por tema e tabs Sermões/Quebra-gelos/Músicas — inspiração para o planejamento.
- Ao confirmar → **wizard da programação** (modal wide ou tela em passos): para **cada uma das 8 etapas** (seção 4): nome da etapa + tempo, **Responsável** (select com os membros da célula, opcional) e **Observação** (texto curto opcional, ex.: "levar violão"). Barra de progresso "Etapa 3 de 8". Campos adicionais no passo inicial: **Tema da célula** e **Música** sugerida.
- Último passo: **"Revisar programação"** — lista das 8 etapas com responsável e observação; botão primário **"Confirmar programação"** → toast: "Programação confirmada. Os responsáveis serão avisados no WhatsApp." (quem envia é o agente de IA do sistema).

### 6.4 `#lider-relatorio` — Relatório da Célula
- Card **simples e minimalista** (o líder preenche em 1 minuto no celular):
  - **Tema** (texto);
  - **Deu os avisos?** (toggle sim/não);
  - **Teve oferta?** (toggle sim/não; se sim, campo opcional de valor);
  - **Presentes**: lista de membros com checkbox (auxiliar primeiro, demais em ordem alfabética);
  - **Visitantes**: lista dinâmica "+ Adicionar visitante" → nome*, WhatsApp*, **Aceitou Jesus?** (sim/não — se sim, dot verde e microtexto "vai iniciar consolidação");
  - Botão primário **"Enviar relatório"** → toast "Relatório enviado para a Central de Células."
- Abaixo, card "Relatórios anteriores": linhas "nº · data · tema · presentes/visitantes" com pill Enviado.

### 6.5 `#lider-multiplicacao` — Multiplicação
- Card de status: se existe solicitação, mostrar com pill (Aguardando aprovação / Aprovada / Rejeitada + motivo).
- Botão primário **"Criar multiplicação"** → modal/wizard: **Novo líder*** (select mostrando só membros aptos = **que realizaram o Reencontro**; os não aptos aparecem desabilitados com o motivo "ainda não fez o Reencontro"), **Membros que irão** (multi-seleção com checkbox), **Dia e hora** da nova célula, **Endereço**, **Anfitrião** (select), **Data prevista**. Botão **"Solicitar multiplicação"** → pill warn "Aguardando aprovação da Central".
- Microtexto de regra: "Apto a liderar = quem realizou o Reencontro. Aprovada a multiplicação, a nova célula entra na Árvore Ministerial e o novo líder recebe a gestão dela."

### 6.6 `#lider-avisos` — Avisos
- Duas seções: **"Da igreja"** (recebidos da central/liderança — cards vermelhos, somente leitura) e **"Da minha célula"** (cards azuis, com "Novo aviso" → modal título+mensagem, editar/excluir).

### 6.7 `#lider-editar` — Editar Célula
- **Dados leves** (o líder salva direto): **nome**, **link do grupo de WhatsApp**, **mensagem de convite** (textarea com botão "Restaurar padrão do sistema"; esta é a mensagem que o discípulo usa no "Convidar amigo"). Rodapé: "Salvar" → toast de sucesso.
- **Dados sensíveis** (bloco separado e visualmente distinto, cada campo travado com ícone de cadeado + botão **"Solicitar alteração"**): **dia**, **horário**, **endereço**, **link da localização (mapa)**, **anfitrião**, **auxiliar**, **entrada/saída de membros**. Cada "Solicitar alteração" abre modal (novo valor + motivo) → envia para aprovação da Central e mostra pill warn "Alteração pendente" junto ao campo. Microtexto no topo do bloco: "Estes dados só mudam com aprovação da Central de Células."

## 7. Visão DISCÍPULO — `#discipulo` (tela única, minimalista)

Ordem vertical (mobile-first; no desktop pode virar 2 colunas):

1. **Hero da próxima célula** (card destacado, gradiente `--grad-brand`, texto claro): "Próxima célula: **quinta, 17/09 · 20:00** · Casa do Roberto" + botão claro **"Confirmar presença"** → ao confirmar, expande: toggle **"Vou levar visitante"** e campo **"Nome para oração"** ("coloque um nome para todos orarmos"). Abaixo, a linha de expectativa dinâmica: "🔥 **Expectativa: 14 participantes e 3 convidados**" (atualiza ao confirmar — simule).
2. **Fileira de 3 ações**: **Convidar amigo** (abre modal com a mensagem de convite configurada pelo líder — tom de amizade, contando como a célula está ajudando quem convida a vencer dificuldades — já com dia, endereço e link da localização; botão "Copiar" e botão verde WhatsApp "Enviar") · **Grupo da célula** (botão WhatsApp, só aparece se o líder cadastrou o link) · **Localização** (link do mapa).
3. **Contador**: card pequeno "Nossa célula já realizou **47 encontros**" (número em Sora 30px).
4. **Mural de avisos** (minimalista e discreto): cards compactos — **igreja em vermelho, célula em azul** (borda esquerda + fundo soft), título 13px + texto 12px.
5. **Participantes**: lista começando pelo **Líder** (pill accent "Líder"), depois **Auxiliar**, depois os demais **numerados**.
6. **Últimas células realizadas**: card com **rolagem interna** (max-height ~280px): linhas "**nº** · data · tema".

O discípulo NÃO vê: relatórios, dados de outros membros, gestão. Tom geral: leve, acolhedor, zero jargão administrativo.

## 8. Dados mock (usar estes, pode enriquecer)

- Igreja: **Igreja Filadélfia** (Corrente-PI). Descendências: "Pr. Rafael (masculina)" e "Pra. Ana (feminina)".
- 8 células na central; foco na **Célula Vida Nova** — líder **Carlos Mendes**, auxiliar **Juliana Souza**, anfitrião **Roberto Lima**, quinta 20:00, Rua das Palmeiras 142, cobertura espiritual "Pr. Rafael". 9 membros + 2 visitantes recentes. 47 reuniões realizadas.
- Membros (exemplos): Ana Beatriz (estudante, sonho: fazer medicina), Marcos Paulo (funcionário, dado pendente: família), Pedro Henrique (apto a liderar ✓), Fernanda Costa, João Vitor, Larissa Almeida, Rafael Nunes, Camila Rocha, Tiago Martins.
- Solicitações pendentes na central: 1 multiplicação (Célula Vida Nova → novo líder Pedro Henrique, 5 membros, terça 19:30) e 2 alterações sensíveis (Célula Ebenézer: dia quinta 20:00 → terça 19:30, motivo "líder mudou turno de trabalho"; Célula Vida Nova: anfitrião Roberto Lima → Marcos Paulo).
- Aptidão: Pedro Henrique e Juliana Souza já **fizeram o Reencontro** (aptos a liderar); os demais membros ainda não.
- Materiais: sermão "O poder da comunhão" (tags: comunhão, família), quebra-gelo "Duas verdades e uma mentira" (tags: integração), música "Grande é o Senhor" + link (tags: adoração).
- Avisos: igreja — "Vigília geral sexta às 22h" (vermelho); célula — "Traga um lanche para a comunhão 🙂" (azul).
- Relatórios: 6 de 8 células enviaram na semana; Célula Vida Nova com 1 relatório atrasado (para acionar o banner do líder).

## 9. Regras de negócio que o design precisa deixar visíveis

1. Toda célula pertence a uma **cobertura espiritual** (campo obrigatório no cadastro).
2. **Central cadastra células**; o líder edita só dados leves (nome, link do grupo, mensagem de convite). **Dados sensíveis — dia, horário, endereço, anfitrião, auxiliar, entrada/saída de membros — só mudam com aprovação da Central.**
3. **Apto a liderar = realizou o Reencontro.** Todo líder de célula já é apto implicitamente. Só membros aptos podem ser novo líder numa multiplicação (não aptos desabilitados com o motivo).
4. Multiplicação e alterações sensíveis **nascem como solicitação pendente** — a Central aprova ou rejeita (rejeição tem motivo).
5. Relatório não enviado **2h após o horário previsto** gera a grande notificação no painel do líder; o botão de enviar fica disponível a qualquer momento depois do horário.
6. Avisos: **igreja = vermelho, célula = azul**, em todas as visões.
7. Visitante do relatório que **aceitou Jesus** inicia consolidação (microtexto no form).
8. A **Central de Células** fica em **Jornada G12 → Discipular → Central de Célula** (não é aba do menu Células) e só existe para admin e líder(es) da central. A **Árvore Ministerial** (quem lidera quem) é coisa separada da célula — a multiplicação, ao ser aprovada, atualiza essa árvore.

## 10. O que NÃO fazer

- Não inventar telas além das listadas (nada de configurações, billing, chat etc. — são de outros módulos).
- Não usar bibliotecas externas de JS/CSS (sem Tailwind, Bootstrap, React etc.).
- Não usar cores fora dos tokens da seção 3; não usar `--faint` em texto informativo.
- Não empilhar telas: SPA de verdade, uma tela por hash.
- Não esquecer os estados: pelo menos 1 empty state, o banner de relatório atrasado, pills de todos os desfechos de solicitação.
- Não escrever textos em inglês nem placeholder "lorem ipsum" — todo conteúdo em pt-BR realista.
