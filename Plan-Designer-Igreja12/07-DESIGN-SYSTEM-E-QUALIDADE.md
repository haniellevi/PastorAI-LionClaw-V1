# Design system e qualidade

## 1. Direção preservada

Atualizado em 01/10/2026 com a direção expressiva v3 aprovada e aplicada às 42 unidades existentes. [DESIGN.md](../DESIGN.md) é o contrato visual canônico; este capítulo descreve sua aplicação e as metas de qualidade. A identidade Diamante Lapidado permanece como base.

Nome da direção: **Farol de Hoje sobre Diamante Lapidado**.

Princípio: cada tela destaca o que precisa de atenção agora, mantendo a identidade mineral da Igreja 12 e um caminho G12 compreensível.

Sensação:

- serena;
- clara;
- acolhedora;
- premium sem ostentação;
- pastoral sem infantilização;
- eficiente sem parecer um ERP hostil.

A imagem em `assets/concepts/conceito-farol-de-hoje.png` explora essa direção. Seu texto é conceitual.

## 2. O que já é canônico

A referência vigente é a [execução v3](../docs/sprints/2026-10-01-ux-expressiva-v3.md), com [tokens](../frontend/src/app/design-tokens.css), [estilos de base](../frontend/src/app/globals.css) e [composição v3](../frontend/src/app/expressive-ux-v3.css). A tabela abaixo resume a paleta canônica. Os valores tipográficos legados dos tokens permanecem por compatibilidade; as famílias de telas aplicam a hierarquia v3.

### Cor

| Token | Valor atual | Função |
|---|---|---|
| `--diamond-950` | `oklch(24% 0.055 252)` | marinho mineral, sidebar e fundo de marca |
| `--diamond-900` | `oklch(32% 0.08 252)` | hover forte |
| `--diamond-700` | `oklch(48% 0.13 252)` | ação primária |
| `--diamond-600` | `oklch(58% 0.16 248)` | foco, seleção forte e borda ativa |
| `--diamond-500` | `oklch(67% 0.15 238)` | acento de marca, sem uso como foco canônico |
| `--diamond-300` | `oklch(82% 0.09 230)` | acento leve |
| `--diamond-100` | `oklch(95% 0.025 230)` | seleção suave |
| `--ice-50` | `oklch(98.5% 0.008 230)` | canvas |
| `--ink-950` | `oklch(24% 0.035 245)` | texto principal |
| `--ink-600` | `oklch(46% 0.025 245)` | texto secundário |
| `--line-200` | `oklch(88% 0.018 235)` | divisória sutil |
| `--border-emphasis` | `oklch(63% 0.024 238)` | borda de controle |

Texto operacional secundário não recebe transparência adicional. O foco de 2 px usa `--focus-ring`, associado a `diamond-600`; a seleção não substitui esse indicador.

Estados semânticos atuais, verde, âmbar, coral e azul, permanecem independentes da marca.

### Tipografia

- títulos: Sora;
- corpo: Plus Jakarta Sans;
- dados técnicos raros: JetBrains Mono;
- corpo, identidade de linha e campos: 16 pixels; apoio e metadado de linha: 14 pixels;
- rótulo: 14 pixels; título de tela: 32 pixels no desktop e 28 no mobile;
- acesso: headline de marca de 48 a 56 pixels no desktop, título do formulário de 28 pixels;
- títulos, pesos e entrelinhas seguem a tabela de [DESIGN.md](../DESIGN.md);
- nenhum texto operacional abaixo de 12 pixels.

### Espaçamento

Escala atual: 4, 8, 12, 16, 24, 32, 48 e 64 pixels.

### Forma

- controle: 10 pixels;
- painel: 14 pixels;
- diálogo: 18 pixels;
- pill: raio total;
- sombras baixas e raras, somente para elevação real.

### Movimento

- rápido: 140 ms;
- padrão: 200 ms;
- expressivo: 220 ms na entrada de facetas do acesso; hover 140 ms e apoio/diálogo 200 ms;
- mouse fino: facetas decorativas separadas, deslocamento máximo de 6 pixels e um frame pendente; foco de campo interrompe o efeito;
- conteúdo de apoio: revelação única com scroll nativo, sem esconder ações ou campos;
- `prefers-reduced-motion` já deve neutralizar animações e transições.

## 3. Teal e reconhecimento de marca

Exploração histórica, sem adoção no refinamento v3 aprovado. Os tokens candidatos abaixo permanecem fora do contrato canônico.

O código atual consolidou azul mineral como ação canônica. Reintroduzir teal como segundo primário criaria duas identidades e deve ser evitado.

O teal pode ser testado, após aprovação, como acento pastoral de baixa frequência:

- progresso calmo;
- presença humana;
- conexão ativa;
- destaques do caminho vivo que não sejam botões primários;
- superfícies informativas suaves.

Tokens candidatos, ainda não aprovados:

```css
--pastoral-calm: oklch(53% 0.09 185);
--pastoral-calm-soft: oklch(96% 0.025 185);
```

Antes de adoção, medir contraste e comparar com `state-ok` e WhatsApp para evitar colisão semântica.

## 4. Assinaturas visuais

### Farol de Hoje

Na composição v3, a faixa mineral compacta e a fila de cuidados priorizam:

- saudação curta;
- pessoa e motivo antes dos totais;
- uma ação principal por cuidado, com ênfase no primeiro e secundárias rotuladas conforme a capacidade disponível;
- agenda imediata visível;
- Jornada e responsáveis sob demanda;
- totais do escopo em "Visão geral do seu cuidado", recolhidos por padrão;
- estado de tranquilidade quando não há pendências.

A faixa de Hoje, Gestão e Console permanece compacta (até 160 pixels no desktop), com contexto e ações visíveis. Listas e formulários usam superfícies claras. Acesso usa composição dividida 48/52 a partir de 1024 pixels e formulário de largura máxima 440 pixels; no mobile, marca compacta e formulário único.

### Caminho vivo G12

Ganhar, Consolidar, Discipular e Enviar aparecem como continuidade:

- posição;
- progresso;
- pendência;
- próximo passo;
- navegação.

O caminho não pode depender apenas de cor e não deve aparecer em toda tela.

### Diamante

- marca no shell e momentos de identidade;
- recorte geométrico sutil em divisores ou seleção;
- nunca repetir diamantes decorativos em todos os cards;
- não usar brilho, neon ou gradiente sem função.

## 5. Layout

### Breakpoints de validação

- 360 pixels;
- 390 a 414 pixels;
- 768 pixels;
- 1024 pixels;
- 1440 pixels ou mais.

### Margens e largura

| Faixa | Padding recomendado | Comportamento |
|---|---|---|
| 360 a 414 | 16 px | uma coluna, ações em largura total quando necessário |
| 768 | 20 a 24 px | uma ou duas colunas, conforme tarefa |
| 1024 | 24 a 32 px | sidebar e conteúdo operacional |
| 1440+ | 32 px | largura de leitura controlada, sem esticar formulários |

### Densidade

- filas e listas podem ser compactas;
- formulários e conteúdo pastoral precisam respirar;
- cards só quando existe agrupamento semântico;
- linha divisória é preferível a um novo card quando os itens pertencem ao mesmo fluxo;
- no mobile, detalhes secundários podem recolher, mas ações essenciais permanecem visíveis.

## 6. Componentes

### Botões

- um rótulo curto e uma linha;
- `white-space: nowrap` somente quando houver estratégia de largura;
- altura alvo de 44 pixels em mobile;
- ícone não substitui nome acessível;
- uma ação primária por região;
- destrutivo separado e confirmado conforme impacto;
- loading preserva largura e informa estado.

### Campos

- label sempre visível;
- ajuda antes do erro quando necessário;
- erro junto ao campo e resumo em formulário longo;
- não apagar valor após falha;
- autocomplete apropriado;
- teclado mobile coerente com telefone, data e número;
- dados já conhecidos não são pedidos novamente sem motivo.

### Listas e tabelas

- tabela para comparação repetida e várias colunas;
- lista para fila e ação;
- cabeçalho fixo somente se não ocultar foco;
- em mobile, converter linha em bloco sem perder rótulo de cada valor;
- seleção em lote exige confirmação, contagem e possibilidade de recuperação.

### Tabs

- `tablist`, `tab`, `tabpanel` e roving tabindex;
- setas navegam entre abas;
- aba ativa possui texto e estado, não apenas cor;
- abas mobile rolam sem deslocar a página inteira;
- preservar a aba ao abrir e fechar detalhe quando possível.

### Dialogs e drawers

- foco inicial previsível;
- foco preso durante abertura;
- Escape fecha quando seguro;
- foco retorna ao acionador;
- título e descrição acessíveis;
- confirmação de impacto antes de aprovação sensível;
- formular longo em mobile pode virar tela, não modal apertado.

### Conteúdo sob demanda

- `details` e `summary` nativos para expansão inline;
- título visível, foco de teclado e contexto acessível por item;
- pessoa, estado e ação principal continuam visíveis;
- abrir detalhe e voltar preserva o contexto compatível com o contrato da tela;
- expansão nativa imediata, sem exigir animação de altura.

### Feedback

- toast não é o único lugar de um erro importante;
- sucesso curto e específico;
- erro persistente até ação;
- offline e módulo desativado têm estados próprios;
- `aceito pelo provedor` não é `entregue`.

## 7. Acessibilidade, WCAG 2.2 AA

Requisitos mínimos:

- contraste de texto e componentes medido;
- navegação integral por teclado;
- foco visível e nunca totalmente oculto por elementos fixos;
- touch target mínimo da norma e meta interna de 44 por 44 pixels;
- alternativa a arrastar;
- autenticação sem teste cognitivo desnecessário;
- evitar entrada redundante;
- nomes, descrições e mensagens acessíveis;
- headings e landmarks coerentes;
- zoom a 200 por cento sem perda de conteúdo ou ação;
- leitor de tela anuncia loading, erro, sucesso, contagens e mudanças relevantes;
- `prefers-reduced-motion` respeitado;
- informação nunca depende somente de cor, posição ou ícone.

Padrões complexos devem seguir o WAI-ARIA APG, mas HTML nativo vem primeiro.

## 8. Linguagem

Tom:

- humano;
- direto;
- respeitoso;
- pastoral quando apropriado;
- sem jargão técnico;
- sem culpa ou ameaça.

### Exemplos

| Situação | Evitar | Preferir |
|---|---|---|
| vazio | Nenhum registro | Ainda não há registros desta reunião. |
| erro | Erro 422 | Revise o líder escolhido. Essa pessoa ainda não está apta. |
| sem acesso | Acesso negado | Esta ação pertence à Central de Células. |
| sucesso | Operação realizada | Relatório enviado para a Central. |
| envio | Notificação enviada | 84 mensagens foram aceitas pelo provedor, 3 falharam. |
| revisão | Cadastro atualizado | Respostas enviadas para revisão. |

Datas usam português do Brasil, fuso da igreja e formatos claros. Valores financeiros exibem moeda. Telefones são apresentados de forma legível e armazenados canonicamente.

## 9. Orçamento de desempenho percebido

Metas de campo, percentil 75 em mobile e desktop:

- LCP até 2,5 s;
- INP até 200 ms;
- CLS até 0,1.

Metas de interação do produto:

- feedback visual de clique em até 100 ms;
- skeleton ou progresso em até 200 ms quando a resposta não for imediata;
- shell permanece utilizável durante troca de área;
- evitar spinner de página inteira em navegação interna;
- preservar layout para impedir saltos;
- carregar módulos pesados sob demanda;
- cancelar ou ignorar respostas obsoletas de busca e filtro;
- paginação ou virtualização quando a lista real exigir;
- medir em dados reais, não apenas Lighthouse local.

Aplicação cuidadosa no stack atual:

- `next/font` para fontes otimizadas e sem layout shift;
- `next/image` com dimensões e `sizes` corretos;
- prefetch, streaming e loading states quando compatíveis com a arquitetura atual;
- não migrar hash routing ou shell apenas para seguir uma recomendação genérica.

## 10. Qualidade visual e regressão

Para cada fatia:

1. screenshot antes;
2. screenshot depois nos cinco breakpoints;
3. estado vazio, carregando, erro e preenchido;
4. teclado e foco;
5. zoom a 200 por cento;
6. reduced motion;
7. contraste automatizado e manual;
8. Playwright visual com tolerância definida;
9. smoke autenticado com papéis reais;
10. verificação de conteúdo e autorização por API.

Uma aprovação visual não aprova a regra de negócio. Uma autorização correta também não prova que a tela é utilizável.

No [recorte v2](../docs/sprints/2026-09-30-ux-contraste-fluxo-v2.md), a evidência local cobre 390/768/1024/1440 px, contraste renderizado, teclado, foco, reduced motion e continuidade mobile com dados sintéticos. A largura de 360 px, zoom real de 200%, leitor de tela e smoke com papéis/backend reais permanecem sem evidência nesta entrega. Os critérios acima continuam sendo metas, sem declarar esses itens concluídos.

## 11. Fontes oficiais

- [WCAG 2.2, visão geral do W3C](https://www.w3.org/WAI/standards-guidelines/wcag/)
- [Novidades da WCAG 2.2](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/)
- [WAI-ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/)
- [Core Web Vitals no web.dev](https://web.dev/articles/vitals)
- [Curso de acessibilidade do web.dev](https://web.dev/learn/accessibility)
- [Next.js, fontes](https://nextjs.org/docs/app/api-reference/components/font)
- [Next.js, imagens](https://nextjs.org/docs/app/api-reference/components/image)
- [Next.js, navegação](https://nextjs.org/docs/app/getting-started/linking-and-navigating)

## 12. Gate de direção

Em 01/10/2026, Raniel aprovou o conjunto concreto v3 e autorizou a aplicação global e a publicação frontend. A [execução e evidência](../docs/sprints/2026-10-01-ux-expressiva-v3.md) controla o candidato, QA e recibo; a [referência do programa](README.md) mantém os limites de produto e das operações externas.

A exploração histórica de teal e as composições ainda não implementadas não passam a ser capacidades aprovadas por essa atualização.
