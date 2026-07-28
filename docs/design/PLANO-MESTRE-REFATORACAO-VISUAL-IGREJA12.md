# Plano mestre de refatoração visual Igreja 12

## 1. Resultado desejado

Transformar o Igreja 12 em um produto pastoral de alta confiança: minimalista, expressivo, rápido de compreender e confortável no uso diário. A refatoração preserva integralmente funcionalidades, contratos de API, rotas, permissões e regras ministeriais.

O resultado não deve parecer uma nova skin. Deve parecer que a interface finalmente revela a lógica que o produto já possui.

## 2. Norte de design

**Conceito:** clareza pastoral contemporânea.

Uma interface calma, luminosa e precisa, com a densidade certa para supervisão. O teal deixa de ser decoração e passa a indicar ação e localização. O petróleo ancora navegação e confiança. A hierarquia usa espaço, tipografia e alinhamento antes de bordas e sombras.

### Cena de uso

Um pastor abre o sistema entre reuniões, em um notebook claro durante o dia, ou no celular enquanto se desloca. Ele precisa identificar uma pendência, compreender o contexto e agir em menos de um minuto, sem medo de enviar, excluir ou atribuir algo errado.

### Promessa de experiência

- A tarefa principal aparece na primeira dobra.
- O usuário nunca enfrenta mais de uma navegação contextual ao mesmo tempo.
- Uma mesma ação tem o mesmo componente, posição e feedback em todo o produto.
- Mobile mostra uma tarefa por vez; desktop favorece contexto sem virar BI.
- Beleza é percebida na precisão, não no excesso de efeitos.

## 3. Escopo estrito

### Incluído

- Hierarquia, composição, densidade, spacing e responsividade.
- Tipografia, cores, superfícies, iconografia e estados.
- Shell, navegação global e navegação contextual.
- Formulários, tabelas, listas, cards, modais, sheets, toasts, banners e vazios.
- Microinterações de estado com 150 a 220 ms.
- Copy de interface quando não altera regra ou significado.
- Refatoração de CSS e primitives para consistência visual.
- Acessibilidade visual e de interação.

### Proibido

- Nova funcionalidade, endpoint, rota, tela, papel, permissão ou dado.
- Mudança de RBAC, RLS, tenant, auth, integrações ou domínio.
- Desbloquear UV ou Capacitação Destino.
- Alterar o recorte Minha Célula versus Central de Célula.
- Adicionar dashboard, métrica ou conteúdo sem backing real.
- Trocar Next.js, React ou o modelo de CSS por outro framework.
- Instalar biblioteca antes de provar que a stack atual não resolve.

## 4. Arquitetura da experiência

### 4.1 Hierarquia de atenção por tela

1. Contexto mínimo: localização e título.
2. Situação atual: urgência, seleção ou estado.
3. Ação principal.
4. Conteúdo operacional.
5. Resumo e informação secundária.
6. Ajuda e detalhes sob demanda.

### 4.2 Navegação

- **Global:** sidebar no desktop; bottom navigation + drawer no mobile.
- **Contextual:** abas ou stepper, nunca ambos sem função diferente e evidente.
- **Jornada G12:** stepper indica posição e permite trocar de etapa. Abas aparecem somente quando existem vistas irmãs reais dentro da etapa.
- **Bottom navigation:** “Jornada” precisa refletir a etapa corrente ou abrir o último destino válido, sem criar estado ou rota nova. Se isso exigir nova persistência, manter o comportamento atual e apenas melhorar o rótulo/contexto.
- **Topbar:** título e contexto; ações raras não competem com a ação primária da tela.

### 4.3 Padrões por tipo de superfície

| Superfície | Padrão desktop | Padrão mobile |
|---|---|---|
| Fila de trabalho | lista dominante + resumo lateral | lista primeiro, resumo recolhido |
| Conversas | lista + thread + drawer sob demanda | lista ou thread, uma por vez |
| Minha Célula | sequência por frequência de uso | blocos contínuos, CTA no alcance do polegar |
| Central | lista operacional + filtros + detalhe | tabs roláveis, lista e detalhe progressivo |
| Jornada | posição + tarefa da etapa | stepper compacto + conteúdo |
| Configuração | seções estáveis, forms inline quando seguros | forms em página ou sheet, não modal estreito |
| Dados densos | tabela semântica | cards/lista rotulada somente quando necessário |

## 5. Sistema visual proposto

### 5.1 Cor

- Manter petróleo e teal como assinatura.
- Usar estratégia restrita: neutros tingidos + teal em menos de 10% da superfície.
- Remover gradientes de ações operacionais. Gradiente pode sobreviver no login e em pontos de marca.
- Cores da Jornada ficam suaves e subordinadas.
- Estado semântico usa ícone, texto e forma, nunca cor isolada.
- Definir pares de contraste AA documentados para texto, ícone e foco.

### 5.2 Tipografia

- Plus Jakarta Sans para interface; Sora apenas em marca e títulos de alta hierarquia.
- Escala compacta e consistente: 12, 13, 14, 16, 20, 28 px.
- Peso 500 para labels, 600 para títulos e ações importantes.
- Números com tabular figures.
- `text-wrap: balance` em títulos curtos e `text-wrap: pretty` em explicações.
- Um `h1` por tela; regiões principais com `h2` e subtítulos semânticos.

### 5.3 Espaçamento e layout

- Grid base de 4 px, com passos 4, 8, 12, 16, 24, 32 e 48.
- Largura útil por tipo de tarefa, não um container universal.
- Reduzir empilhamento de containers; um bloco não precisa de card apenas por existir.
- Espaço maior antes da ação dominante e entre regiões; espaço menor dentro de grupos relacionados.
- Desktop com largura máxima por superfície; telas de leitura não atravessam 75ch.

### 5.4 Superfícies

- Piso: `bg`.
- Conteúdo principal: `surface` sem sombra por padrão.
- Agrupamento secundário: `surface-2` ou divisor.
- Elevação apenas para drawer, popover, dialog e elemento flutuante.
- Raio externo 16 px, interno 10 a 12 px, controle 8 a 10 px.
- Eliminar cards aninhados.

### 5.5 Movimento

- 150 a 220 ms, ease-out-quart.
- Apenas `transform` e `opacity` para transições visuais.
- Animação comunica seleção, abertura, carregamento ou conclusão.
- Nada de cascata decorativa de entrada.
- Respeitar `prefers-reduced-motion`.

## 6. Biblioteca mínima de primitives

Criar ou consolidar apenas o necessário:

- `Button`: primary, secondary, ghost, danger; md/sm; loading e icon-only.
- `IconButton`: alvo 44 × 44, tooltip e aria-label obrigatórios.
- `Field`: input, select e textarea com label, helper, erro e descrição.
- `Dialog`: Esc, focus trap, retorno de foco, scroll lock; sheet em mobile.
- `Toast`: região live, duração, ação opcional e persistência para erro.
- `Banner`: info, warning, error e degraded.
- `EmptyState`: título, explicação e slot opcional de ação existente.
- `Skeleton`: formas por layout.
- `Tabs`: roving focus, overflow e estado ativo.
- `PageHeader`: título, contexto e ação principal.
- `SectionHeader`: título semântico, contagem e ação secundária.
- `DataList` e `DataTable`: seleção, ação de linha e variante mobile.
- `StatusBadge`: semântica consistente, sem pílula decorativa.

Não criar uma abstração para cada combinação. Receitas de composição podem ficar em CSS sem virar componente.

## 7. Fases de execução

### Fase 0. Baseline e contrato de não-regressão

**Objetivo:** congelar a verdade antes de mudar.

- Trabalhar em worktree limpo a partir do `origin/main` atualizado.
- Confirmar as três superfícies: app, admin e painel master.
- Capturar screenshots autenticados em 360, 390, 768, 1024 e 1440 px.
- Registrar rotas, estados e permissões representativas.
- Rodar typecheck, lint, build e testes atuais.
- Criar matriz visual: tela, papel, estado, ação principal, breakpoint.

**Gate:** baseline versionado e reproduzível. Nenhum código visual ainda.

### Fase 1. Exploração no Fable

**Objetivo:** decidir a direção antes de implementar.

Criar três propostas claramente diferentes, todas respeitando a identidade:

1. **Quiet Operations:** máxima calma, filas e listas, quase sem cards.
2. **Pastoral Editorial:** tipografia e espaços mais expressivos, mantendo familiaridade.
3. **Precision Workspace:** maior densidade e eficiência, com divisão clara entre ação e contexto.

Cada proposta deve conter, no mínimo:

- Painel de Hoje em desktop e mobile.
- Conversas em desktop e mobile.
- Minha Célula, visão líder e discípulo.
- Central de Célula com dashboard e Gerenciar Células.
- Uma tela de formulário administrativo.
- Estados loading, vazio, erro, sucesso e permissão negada.
- Um dialog desktop e um sheet mobile.

**Gate:** usuário escolhe uma direção ou combinação. Sem aprovação, não implementar.

### Fase 2. Fundação visual

**Objetivo:** transformar a direção aprovada em sistema.

- Consolidar tokens semânticos em CSS.
- Definir escala tipográfica, spacing, radius, elevation e z-index.
- Implementar primitives mínimas.
- Remover os dois anti-padrões determinísticos.
- Começar a substituir estilos inline somente nas áreas tocadas.
- Documentar `DESIGN.md` com decisões aprovadas no Fable.

**Gate:** página de referência ou harness com todos os componentes e estados, aprovada em desktop e mobile.

### Fase 3. Shell e navegação

**Objetivo:** reduzir orientação duplicada.

- Refinar sidebar, topbar, bottom navigation e drawer.
- Definir regra exata para stepper versus tabs.
- Preservar `NAV_SECTIONS`, `canSee`, `screenId` e hash routing.
- Melhorar estados ativo, foco, locked e permission-hidden.
- Garantir que navegação mobile tenha alvos de 44 px e safe area.

**Gate:** todos os deep-links funcionam; zero rota ou permissão alterada; usuário localiza qualquer tela permitida sem ambiguidade.

### Fase 4. Superfícies operacionais críticas

#### Onda 4A. Painel de Hoje

- Fila na primeira dobra.
- Resumo de métricas compacto e secundário.
- Urgência por linguagem, ícone e prazo.
- Ações de fila com hierarquia estável.

#### Onda 4B. Conversas

- Preservar master-detail.
- Refinar lista, thread, composer, banners e drawer.
- Ações de assumir, devolver, transferir e excluir com hierarquia por risco.

#### Onda 4C. Minha Célula

- Discípulo: reunião e confirmação primeiro; avisos, materiais e histórico depois.
- Líder: relatório atual e Planejar Reunião primeiro; administração sensível progressiva.
- Remover cards que apenas separam conteúdo contínuo.

#### Onda 4D. Central de Célula

- Trocar seis cards equivalentes por painel de exceções e saúde.
- Dar prioridade a solicitações, relatórios pendentes e células que exigem atenção.
- Preservar as cinco tabs e todos os endpoints.

**Gate por onda:** comparação antes/depois, testes, screenshots e validação do fluxo principal em menos de 60 segundos.

### Fase 5. Jornada e demais telas

- Ganhar, Consolidar, G12 e Enviar.
- Agenda, Pessoas, Comunicação e Relatórios.
- Configuração Inicial, Usuários, Permissões, Integrações, WhatsApp, Agente, Identidade e Assinatura.
- Console master somente depois do produto da igreja estar estabilizado.

**Gate:** vocabulário visual consistente sem apagar necessidades específicas de cada superfície.

### Fase 6. Formulários, diálogos e estados sistêmicos

- Migrar diálogos para o primitive compartilhado.
- Esc, foco inicial, trap, retorno de foco e scroll lock.
- Mobile sheet quando o fluxo couber; página inteira quando o formulário for longo.
- Padronizar erros inline, loading, disabled, sucesso e retry.
- Garantir autocomplete, inputmode, name e tipos de input adequados.

**Gate:** todos os fluxos críticos completos por teclado e em 390 px, sem perda de contexto.

### Fase 7. Polimento e hardening

- Remover estilos inline remanescentes nas áreas migradas.
- Auditar contraste, touch target, overflow, zoom 200% e reduced motion.
- Validar textos longos, nomes extensos, listas vazias e alto volume.
- Medir layout shift e responsividade.
- Reexecutar detector de anti-padrões.

**Gate final:** checklist abaixo completamente verde.

## 8. Ordem de prioridade

| Prioridade | Área | Motivo |
|---:|---|---|
| 1 | Fundação e dialogs | Afeta o produto inteiro e acessibilidade |
| 2 | Shell e Jornada | Reduz desorientação global |
| 3 | Painel de Hoje | Maior impacto na rotina pastoral |
| 4 | Conversas | Fluxo frequente e sensível no mobile |
| 5 | Minha Célula | Uso recorrente de líder e membro |
| 6 | Central de Célula | Maior densidade administrativa do recorte G12 |
| 7 | Ganhar, Consolidar, G12, Enviar | Coerência da Jornada |
| 8 | Admin e master | Configuração menos frequente |

## 9. Critérios objetivos de aceite

### Usabilidade

- Ação primária identificável em até 5 segundos.
- Fluxo principal de cada tela concluído em até 60 segundos por usuário recorrente.
- No máximo quatro escolhas de mesma hierarquia em um ponto de decisão.
- Nenhuma tela apresenta mais de duas camadas de navegação simultâneas.
- Todo vazio explica o estado e, quando já existe ação no escopo, oferece caminho claro.

### Visual

- Sem card aninhado.
- Sem grade de cards idênticos como resposta padrão.
- Teal reservado a ação, seleção e marca.
- Sombra apenas em elevação real.
- Tipografia e spacing aderem aos tokens aprovados.
- Nenhum gradiente em texto ou glassmorphism decorativo.

### Acessibilidade

- WCAG AA para texto e controles.
- Alvos de toque de pelo menos 44 × 44 px.
- Fluxos críticos completos por teclado.
- Foco sempre visível.
- Diálogos contêm e devolvem foco.
- Headings representam a hierarquia visual.
- Toasts e estados assíncronos usam regiões live adequadas.

### Responsividade

- Viewports: 360, 390, 414, 768, 1024 e 1440 px.
- `scrollWidth === innerWidth` nas superfícies principais.
- Nenhuma ação primária atrás da bottom navigation.
- Conteúdo funcional em zoom de 200%.
- Mobile não é apenas desktop empilhado.

### Engenharia

- Nenhuma mudança em API, banco, auth, RBAC, RLS ou regra G12.
- `screenId`, hash e deep-links preservados.
- Typecheck, lint, build e testes verdes.
- Diffs pequenos por onda.
- Screenshot antes/depois anexado a cada PR visual.

## 10. Provas exigidas por PR

1. Lista de arquivos alterados e justificativa.
2. Declaração explícita de invariantes funcionais.
3. Screenshots antes/depois nos breakpoints relevantes.
4. Medições de overflow e touch targets.
5. Resultado dos testes.
6. Riscos e limitações.
7. Veredito `PASS`, `FAIL`, `BLOCKED` ou `SKIP` por gate.

## 11. Estratégia de entrega

- Uma direção visual aprovada no Fable antes do código.
- Um PR de fundação.
- Um PR de shell/navegação.
- Um PR por superfície crítica ou grupo pequeno de telas relacionadas.
- Nunca misturar redesign global com correção funcional.
- Se uma melhoria exigir comportamento novo, registrar em `docs/design/pontos-melhoria.md` e retirar do diff.

