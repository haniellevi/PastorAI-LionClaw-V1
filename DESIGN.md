# Igreja 12 Design System, Diamante Lapidado

**Register:** product  
**Status:** direção aprovada nos Gates 4/4.1; fundação visual aprovada no Gate 5.2.  
**Fonte conceitual:** `docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md`.

## 1. Norte

O sistema deve parecer calmo antes de parecer sofisticado. A beleza vem de hierarquia, precisão e cuidado humano. A metáfora da lapidação entra em estrutura, cor, motion e progressão, não em efeitos de luz ou formas decorativas espalhadas pela interface.

Cena física orientadora: um pastor ou líder consulta o sistema entre conversas, em uma sala clara ou no celular, precisando reconhecer em segundos quem precisa de cuidado e qual ação é segura.

## 2. Princípios

1. Ação antes de informação.
2. Pessoas antes de números.
3. Valor inerente, formação progressiva.
4. Facetas apenas quando comunicam marca, formação ou organização.
5. Familiaridade nas interações, personalidade na composição.
6. Densidade progressiva, nunca universal.
7. Mobile é uma tarefa por vez.
8. Estado e urgência usam texto, ícone e cor.

## 3. Cor

```css
:root {
  --diamond-950: oklch(24% 0.055 252);
  --diamond-900: oklch(32% 0.080 252);
  --diamond-700: oklch(48% 0.130 252);
  --diamond-600: oklch(58% 0.160 248);
  --diamond-500: oklch(67% 0.150 238);
  --diamond-300: oklch(82% 0.090 230);
  --diamond-100: oklch(95% 0.025 230);
  --ice-50: oklch(98.5% 0.008 230);
  --ink-950: oklch(24% 0.035 245);
  --ink-700: oklch(39% 0.030 245);
  --ink-600: oklch(52% 0.025 245);
  --line-200: oklch(88% 0.018 235);

  --surface-canvas: var(--ice-50);
  --surface-panel: oklch(97% 0.012 232);
  --surface-raised: oklch(99% 0.006 232);
  --text-primary: var(--ink-950);
  --text-secondary: var(--ink-600);
  --border-subtle: var(--line-200);
  --action-primary: var(--diamond-700);
  --action-primary-hover: var(--diamond-900);
  --selection-soft: var(--diamond-100);
  --focus-ring: var(--diamond-500);
}
```

### Uso

- Azul saturado ocupa no máximo 10% da superfície operacional.
- Sidebar pode usar `diamond-950`.
- Ação principal usa `diamond-700` com texto claro. `diamond-600` fica reservado a borda ativa, foco e seleção forte, nunca como fill com texto branco pequeno.
- Métricas neutras não recebem cor de marca.
- Sem gradiente em texto.
- A marca principal não usa gradiente, brilho ou clarão.
- Contraste mínimo WCAG AA.

## 4. Tipografia

| Papel | Família | Tamanho | Peso | Linha |
|---|---|---:|---:|---:|
| Display institucional | Sora | 32 | 700 | 1.15 |
| H1 produto | Sora | 26 | 700 | 1.2 |
| H2 | Sora | 20 | 650 | 1.25 |
| H3 | Plus Jakarta Sans | 16 | 700 | 1.35 |
| Corpo | Plus Jakarta Sans | 14–16 | 450–550 | 1.5 |
| Label | Plus Jakarta Sans | 13 | 650 | 1.35 |
| Metadado | Plus Jakarta Sans | 12 | 500 | 1.4 |

Nenhum texto operacional abaixo de 12 px. Eyebrows em caixa alta são reservados a orientação excepcional, não aparecem em todas as seções.

## 5. Espaçamento e layout

Escala base: `4, 8, 12, 16, 24, 32, 48, 64`.

- Densidade confortável é o padrão.
- Densidade compacta é permitida em tabelas e listas administrativas desktop.
- Blocos relacionados usam proximidade antes de cards.
- Não usar cards aninhados.
- Linha de texto longa: máximo 72ch.
- Painel de Hoje mantém a fila na primeira dobra.
- No máximo duas camadas de navegação simultâneas.

## 6. Forma, radius e elevação

```css
:root {
  --radius-control: 10px;
  --radius-panel: 14px;
  --radius-dialog: 18px;
  --radius-pill: 999px;
  --shadow-raised: 0 12px 36px oklch(24% 0.055 252 / 0.10);
  --shadow-floating: 0 20px 56px oklch(24% 0.055 252 / 0.16);
}
```

- Controles permanecem familiares e retangulares.
- Facetas angulares ficam restritas ao símbolo, ilustrações e momentos de progresso.
- Pílula é usada apenas para status compacto, não para cada rótulo.
- Elevação é reservada a dialog, popover e toast.

## 7. Iconografia e imagem

- Ícones de produto: traço 1.75–2 px, cantos moderadamente arredondados.
- Símbolo da marca: diamante fechado e graficamente simplificado. As divisões internas comunicam lapidação, não uma contagem gemológica. Sem fenda, estrela ou núcleo luminoso.
- Ícones nunca carregam significado crítico sem texto ou nome acessível.
- Ilustrações humanas seguem as cenas e regras éticas do documento de identidade.
- Discipulado individual sempre mostra homem com homem ou mulher com mulher.
- Imposição de mãos segue a mesma regra, sem par misto.
- Não usar diamante como ícone de cada etapa, pessoa ou tarefa.

## 8. Componentes

### Button

- Primário sólido azul, um por região.
- Secundário com borda.
- Terciário textual.
- Destrutivo coral, nunca azul.
- Altura 40 px desktop, 44–48 px mobile.
- Estados: default, hover, focus-visible, active, disabled e loading.

### Field

- Label sempre visível.
- Ajuda e erro próximos do campo.
- Focus ring azul de 2 px com offset.
- Não depender de placeholder como label.

### Row e Table

- Linha é a unidade padrão para fila, conversa, célula e usuário.
- Seleção usa `selection-soft`, indicador textual e foco.
- Tabelas usam números tabulares quando comparáveis.
- Densidade compacta somente em desktop e sem texto abaixo de 12 px.

### Dialog e Sheet

- Mesmo primitive e mesma semântica.
- Dialog central no desktop, sheet ancorada embaixo no mobile.
- Esc fecha, foco fica contido e retorna ao gatilho.
- Ação principal próxima do final do fluxo.

### Toast e Banner

- Toast confirma ação sem roubar foco.
- Banner explica problema e próxima ação.
- Ícone, texto e cor sempre combinados.
- Um reflexo curto pode atravessar o ícone de sucesso, nunca o texto.

### EmptyState

- Nomeia o estado.
- Explica o que acontece depois.
- Oferece ação apenas quando existe uma ação real.
- Ilustração humana é opcional e reservada a primeiro acesso ou contexto pastoral.

## 9. Motion

```css
:root {
  --motion-fast: 140ms;
  --motion-standard: 200ms;
  --motion-expressive: 640ms;
  --ease-out-productive: cubic-bezier(0.16, 1, 0.3, 1);
  --ease-out-expressive: cubic-bezier(0.19, 1, 0.22, 1);
}
```

### Produtivo

- Hover, seleção, disclosure, dialog e feedback: 140–220 ms.
- Animar opacity e transform.
- Não animar width, height, top, left ou propriedades de layout.

### Expressivo

- Apenas marco significativo: 480–760 ms.
- Os planos do símbolo se encaixam e estabilizam uma única vez.
- Sem loop automático, partículas, confete, bounce ou parallax operacional.

### Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

## 10. Aplicação por superfície

### Painel de Hoje

- Estrutura Quiet Operations.
- Saudação e pessoas recebem calor de Pastoral Editorial.
- Sem rail persistente de Precision Workspace.
- Resumo semanal vem depois da fila e pode ser recolhido.

### Conversas

- Master-detail no desktop.
- Lista e thread separadas no mobile.
- Avatares, nome e estado da IA são explícitos.
- Contexto adicional aparece sob demanda ou depois da seleção.

### Minha Célula

- Discípulo: próxima reunião, presença e comunidade.
- Líder: relatório semanal primeiro.
- Dados estruturais e solicitações usam progressive disclosure.

### Central de Célula

- Exceções antes de métricas.
- Tabela semântica no desktop.
- Linha única de contexto da Jornada, seguida das cinco tabs existentes.

### Administração

- Formulários em página dedicada no mobile.
- Densidade seletiva em tabelas de usuários e permissões.
- Marca da igreja local permanece separada da marca do produto.

## 11. Acessibilidade

- Texto normal: contraste mínimo 4.5:1.
- Texto grande: mínimo 3:1.
- Controles mobile: mínimo 44 × 44 px.
- Zoom 200% sem perda de conteúdo.
- Foco visível em todo controle.
- Estado nunca depende apenas de cor ou movimento.
- `prefers-reduced-motion` obrigatório.
- Ilustrações decorativas têm alt vazio; imagens informativas recebem descrição curta.

## 12. Proibições

- Glassmorphism decorativo.
- Gradient text.
- Hero metrics.
- Grade repetitiva de cards iguais.
- Faixa lateral grossa em callout.
- Glow permanente.
- Estrela, clarão ou percurso de luz no símbolo.
- Diamantes decorativos espalhados.
- Texto de 10 ou 11 px.
- Movimento em loop.
- Pastor representado como fonte de poder ou valor.
- Fenda central, duas pinças, cavidade anatômica ou forma que pareça agarrar algo.
- Cena de discipulado individual entre homem e mulher.
- Símbolos religiosos genéricos usados para preencher espaço.

## 13. Gate antes da implementação

1. Escolher e aprovar o símbolo.
2. Criar protótipo consolidado com a identidade aplicada.
3. Medir contraste e touch targets.
4. Validar 390, 768, 1024 e 1440.
5. Comparar visualmente com Quiet Pastoral Operations.
6. Confirmar zero funcionalidade nova.
7. Só então migrar tokens e primitives em PR próprio.
