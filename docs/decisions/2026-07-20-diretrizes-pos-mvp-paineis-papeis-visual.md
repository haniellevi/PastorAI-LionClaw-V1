# Diretrizes do dono — Pós-MVP 1: painéis por papel, visibilidade e visual — 2026-07-20

**Baseline:** `origin/main` = `9732abd` (pós PR#196 / veredito de fechamento do MVP M10)
**Processo:** o dono registrou 9 diretrizes de evolução após o fechamento do MVP.
Cada uma foi verificada contra o PRD consolidado
(`docs/Docs20260611_163530/PRD20260611_163530.md`) e classificada como
**contemplada**, **parcial** ou **nova**. Nenhuma reabre o veredito M10 — o MVP
permanece concluído; tudo aqui é evolução.

**Regra transversal decidida pelo dono (vale para todo o sistema):** área restrita
sem ensinamento possível → **esconder** do papel sem privilégio; área restrita com
conteúdo pedagógico disponível → **mostrar em modo educativo** (ver Diretriz 9).

---

## Diretriz 1 — Painel de Hoje por papel

- **Contexto no PRD:** o painel do MVP é a fila de pendências pastorais
  (US-15..17 / RF-18..20), e RF-D1 já monta menu/dashboard pela união dos papéis
  acumulados. Porém o PRD declara que o usuário final (visitante, membro, líder
  enviando relatório) "interage 100% pelo WhatsApp; não acessa o painel" (§ Personas).
- **Diretriz:** painéis **diferentes por papel**, montados pelas responsabilidades
  assumidas: pastor = fila pastoral completa (atual); líder de célula = estatísticas
  públicas da igreja, avisos, agenda da semana e ações da sua célula (sem fila
  pastoral); membro comum = avisos, agenda e avisos da própria célula; quem lidera
  ministério/outro cargo = painel derivado do que lidera.
- **Status no PRD:** **NOVA** (mudança estrutural — membro comum passa a ter painel;
  conteúdo por papel vai além da união de acessos do RF-D1).
- **Desdobramento:** módulo **PAPEL-1** (grande → pipeline novo, com design antes).

## Diretriz 2 — Minha Célula: alinhamento visual insatisfatório

- **Contexto:** alinhamentos anteriores (PR#153 e correlatos) mergeados, mas o dono
  considera o resultado atual ruim.
- **Diretriz:** refazer o refino visual da superfície Minha Célula.
- **Status no PRD:** não é requisito de PRD (qualidade visual).
- **Desdobramento:** **VIS-2A** (missão Claude Code direta, padrão W-series, com
  validação visual do dono antes do merge).

## Diretriz 3 — Agenda: alinhamento visual insatisfatório

- **Contexto:** W3 (PR#174) migrou diálogos; o layout geral segue ruim na visão do dono.
- **Diretriz:** refino visual da Agenda.
- **Status no PRD:** não é requisito de PRD (qualidade visual).
- **Desdobramento:** **VIS-2B** (missão direta; não confundir com AGENDA-ORD-1 do
  FECH-2, que é só ordenação da aba "A confirmar").

## Diretriz 4 — Espaçamentos e botões (global)

- **Contexto:** texto colado na margem esquerda em eventos locais e em vários pontos;
  botões com texto grande quebrando linha.
- **Diretriz:** nenhum botão pode quebrar linha do texto interno; textos com tamanho
  adaptável; revisar espaçamento lateral padrão nas listas/cards.
- **Status no PRD:** não é requisito de PRD (design system).
- **Desdobramento:** **VIS-2C** (auditoria visual global + fix nos tokens/ds
  components, missão direta).

## Diretriz 5 — Ganhar: visibilidade e ações por papel

- **Contexto no PRD:** RF-05/RF-D7 dão a base de RBAC; delta-046 já restringe
  `vincular_celula` no WhatsApp a líder/pastor/admin. No painel, porém, o líder de
  célula acessa Ganhar/Pessoas com visão ampla e consegue vincular célula.
- **Diretriz:** vincular célula passa a ser exclusivo da liderança do Ganhar (papel a
  definir); líder de célula enxerga **apenas pessoas vinculadas à sua célula** e as
  estatísticas; membro comum vê **apenas estatísticas**, sem nenhuma ação em
  Ganhar/Consolidar/Discipular/Enviar (só os próprios dados).
- **Status no PRD:** **PARCIAL** (RBAC existe; escopo de visibilidade por célula e o
  papel "liderança do Ganhar" são novos).
- **Desdobramento:** **PAPEL-1**. A definir com o dono: quem é a "liderança do
  Ganhar" (papel novo ou atribuição a papel existente).

## Diretriz 6 — Consolidar: líder acompanha só os próprios discípulos

- **Contexto no PRD:** RF-44 restringe o Dashboard de Consolidação à equipe de
  Consolidação. Líder de célula hoje não tem visão de consolidação.
- **Diretriz:** áreas restritas somem do papel sem acesso (ex.: Consolidar para
  membro); líder de célula com discípulos em consolidação acompanha **apenas os
  seus**; participação na Universidade da Vida dá acesso a detalhes (escopo a definir).
- **Status no PRD:** **PARCIAL** (restrição existe; a visão recortada por liderança
  é nova).
- **Desdobramento:** **PAPEL-1**. A definir: quais detalhes a participação na UV libera.

## Diretriz 7 — Discipular: árvore ascendente e descendente

- **Contexto no PRD:** a tela `g12` (organograma de descendências, US-21..23) e o
  auto-relacionamento `pessoa.lider_id` (RNF-25) já estão previstos; a árvore
  ministerial completa é escopo negativo (pós-MVP).
- **Diretriz:** pessoa visualiza a própria árvore nas duas direções — **ascendente**
  com dados mínimos por hover/clique (nome, tempo de igreja); **descendente**
  (discípulos diretos e indiretos) com dados completos.
- **Status no PRD:** **PARCIAL** (tela prevista; a regra de privacidade por direção
  da árvore é nova).
- **Desdobramento:** módulo **ARVORE-1** (roadmap; especificar junto do plano de
  organograma G12 já existente).

## Diretriz 8 — Capacitação Destino: visões por papel

- **Contexto no PRD:** telas `universidade-vida` e `capacitacao` **bloqueadas no MVP**
  (`locked-em-breve`, delta-019/028); módulo de roadmap.
- **Diretriz:** quando o módulo for construído — aluno vê a visão de aluno; líder vê
  apenas os dados dos seus discípulos; liderança do Discipular e pastores veem tudo.
- **Status no PRD:** contemplada como pós-MVP; as regras de visibilidade são novas e
  ficam registradas aqui para a spec do módulo.
- **Desdobramento:** **CAPDESTINO-1** (roadmap; sem missão agora).

## Diretriz 9 — Telas restritas em modo educativo

- **Contexto no PRD:** inexistente — o PRD só prevê `locked-em-breve` para módulos
  futuros; não há conceito de tela restrita pedagógica.
- **Diretriz:** área restrita (ex.: Enviar para líder de célula) exibe **conteúdo de
  ensino** em formato de blog com menus interativos: o que é (ex.: o que é o Enviar),
  materiais recomendados (livros e artigos), extraído da documentação G12. Prioridade
  é informar; sem ensinamento possível, esconder do papel.
- **Status no PRD:** **NOVA**.
- **Desdobramento:** **EDU-1** (médio; depende do mapa de acessos do PAPEL-1 para
  saber o que fica restrito por papel — executar depois ou junto do PAPEL-1).

---

## Consolidação — próximos pacotes

| Pacote | Itens | Tamanho / via |
|---|---|---|
| **FECH-2** (inalterado) | OPTIN-1, REATIVAR-1, ROTULO-1, AGENDA-ORD-1 | Pipeline já preparado em `wt-pipeline-fech2` — **nenhuma diretriz nova entra** (SPEC congelada) |
| **VIS-2** | Diretrizes 2, 3, 4 (Minha Célula, Agenda, espaçamentos/botões) | Missões Claude Code diretas (padrão W-series), validação visual do dono |
| **PAPEL-1** | Diretrizes 1, 5, 6 | Módulo grande → design + decisões pendentes → pipeline novo |
| **EDU-1** | Diretriz 9 | Médio; após/junto do PAPEL-1 |
| **ARVORE-1 / CAPDESTINO-1** | Diretrizes 7, 8 | Roadmap; especificar quando os módulos abrirem |

**Decisões em aberto para o dono (bloqueiam a spec do PAPEL-1):**
1. Quem é a "liderança do Ganhar" — papel novo ou atribuição a papel existente?
2. Membro comum passa a acessar o painel web (mudança de persona do PRD) — confirmar
   que o login de membro é desejado já no PAPEL-1 ou se começa por líderes.
3. Quais detalhes a participação na Universidade da Vida libera na consolidação?
