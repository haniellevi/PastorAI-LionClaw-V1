# Auditoria UX/UI Igreja 12

**Data:** 2026-07-11  
**Escopo:** projeto completo, com foco no frontend e nos fluxos documentados  
**Objetivo:** identificar fricção, ambiguidade, carga cognitiva e oportunidades de elevar a qualidade visual sem criar funcionalidades

## 1. Evidências usadas

- `SPEC.md` e PRD principal.
- Design Brief, Design Lock, reconciliação e ciclos F0 a F4.
- Ajustes pós-F4 e documentação de onboarding.
- PRDs de Minha Célula, Central de Célula e solicitações.
- Mapa estrutural `graphify-out/graph.json`, com 6.960 nós e 18.169 relações.
- Código atual de 485 arquivos rastreados, com foco nos 100+ arquivos de frontend.
- Inspeção do sistema publicado em desktop e viewport móvel de 390 × 844.
- Análise determinística com Impeccable e regras atuais de interface web.

### Limitação conhecida

A inspeção visual ao vivo da área autenticada não foi executada porque não havia sessão autorizada no navegador. Não foram usadas credenciais encontradas no ambiente. As telas internas foram avaliadas por código, CSS, estrutura, estados, documentos e evidências de QA anteriores. O plano exige um novo baseline visual autenticado antes da implementação.

## 2. Veredito executivo

O Igreja 12 já tem identidade reconhecível, boa disciplina de estados e uma base responsiva superior à média. O problema não é falta de acabamento. O problema é que o acabamento foi aplicado sobre uma arquitetura visual que ainda distribui atenção demais.

Hoje a interface frequentemente pede ao usuário para interpretar a estrutura do sistema antes de realizar a tarefa. O redesign anterior corrigiu paleta, superfícies, responsividade e paridade com o protótipo, mas não reduziu suficientemente o número de camadas, contêineres e decisões simultâneas.

### Maior oportunidade

Transformar cada tela de “painel com blocos” em uma composição orientada à próxima ação. A beleza deve nascer de foco, ritmo e precisão, não da quantidade de cards.

### Diagnóstico resumido

| Dimensão | Nota | Leitura |
|---|---:|---|
| Heurísticas de usabilidade | 24/40 | Base aceitável, com fricção relevante |
| Qualidade técnica da interface | 13/20 | Boa fundação, inconsistência sistêmica |
| Carga cognitiva | Crítica, 5/8 falhas | Muitas camadas e opções concorrentes |
| Aparência genérica de IA | Parcial | Identidade própria, mas padrões genéricos persistem |

## 3. Pontuação por heurística

| # | Heurística | Nota | Evidência principal |
|---:|---|---:|---|
| 1 | Visibilidade do estado | 3/4 | Skeletons, banners e toasts existem; feedback não é padronizado por um primitive único |
| 2 | Correspondência com o mundo real | 3/4 | Vocabulário pastoral é forte; “Central de Célula”, “Células” e camadas da Jornada ainda se sobrepõem |
| 3 | Controle e liberdade | 2/4 | Há cancelar e voltar em vários fluxos; 25 diálogos não mostram tratamento sistêmico de Esc e focus trap |
| 4 | Consistência e padrões | 2/4 | Tokens existem, mas 423 estilos inline e um CSS global com mais de 5 mil linhas fragmentam o vocabulário |
| 5 | Prevenção de erros | 2/4 | Confirmações críticas existem; formulários e modais não compartilham uma arquitetura uniforme de validação |
| 6 | Reconhecimento em vez de memória | 3/4 | Rótulos e contexto são bons; subrotas e navegação em camadas exigem reconstrução mental |
| 7 | Flexibilidade e eficiência | 2/4 | Há deep-links e filtros; faltam atalhos consistentes e caminhos rápidos para usuários recorrentes |
| 8 | Estética e minimalismo | 2/4 | Visual limpo, porém muitos cards, métricas e barras de navegação competem pela atenção |
| 9 | Recuperação de erros | 3/4 | Mensagens e retry aparecem em muitas telas; padrão não está centralizado |
| 10 | Ajuda e documentação | 2/4 | `InfoTip` e Configuração Inicial ajudam, mas a orientação depende de ajuda dispersa |
| **Total** |  | **24/40** | **Melhorias significativas necessárias** |

## 4. Saúde técnica da interface

| Dimensão | Nota | Achado |
|---|---:|---|
| Acessibilidade | 2/4 | Boa intenção semântica, mas diálogos, foco e alvos de toque têm lacunas |
| Performance visual | 3/4 | Animações são contidas e reduced-motion existe; há uma transição de `width` sinalizada |
| Responsividade | 3/4 | Master-detail e cards mobile são bons; alvos do login medem 37 a 40 px, abaixo dos 44 px recomendados |
| Theming | 3/4 | Tokens em OKLCH e superfícies coerentes; muitos valores e estilos continuam locais |
| Anti-padrões | 2/4 | Grades de cards e hero metrics continuam presentes; detector encontrou side-stripe e animação de layout |
| **Total** | **13/20** | **Base boa, precisa de sistematização** |

## 5. O que já funciona bem

1. **Identidade própria:** petróleo, teal e tipografia Sora/Plus Jakarta formam uma assinatura reconhecível.
2. **Estados reais:** o frontend evita inventar métricas quando dados falham e usa skeleton, vazio, erro e retry em muitas superfícies.
3. **Mobile tratado como produto:** Conversas usa master-detail; Pessoas usa cards; bottom navigation respeita safe area.
4. **Regras de domínio preservadas:** navegação e telas são filtradas por permissões, sem seletor artificial de papel.
5. **Movimento responsável:** `prefers-reduced-motion` está implementado e as transições são curtas.

## 6. Problemas prioritários

### P1. A fila principal perde para métricas

**Onde:** `DashboardScreen.tsx`  
**Evidência:** saudação, quatro tiles e uma faixa de KPIs aparecem antes da fila de trabalho pastoral.  
**Estresse gerado:** o pastor precisa atravessar informação de contexto para chegar ao que exige ação. Em mobile, isso empurra a fila para baixo da primeira dobra.  
**Direção:** colocar a fila e sua urgência como protagonista. Métricas viram resumo compacto, progressivamente revelado ou coluna secundária no desktop.

### P1. Navegação concorrente na Jornada G12

**Onde:** Sidebar, `JourneyStepper`, `ModuleTabs` e BottomNav.  
**Evidência:** a mesma arquitetura pode aparecer como menu lateral, quatro etapas horizontais, abas de módulo e atalho “Jornada” que sempre abre Ganhar.  
**Estresse gerado:** o usuário não sabe qual camada representa localização, progresso ou troca de tela.  
**Direção:** uma camada global e uma contextual, no máximo. O stepper comunica posição; abas mostram vistas irmãs; não repetir os dois quando não agregam informação distinta.

### P1. Diálogos sem primitive compartilhado completo

**Onde:** pelo menos 25 implementações com `role="dialog"`.  
**Evidência:** apenas poucos `onKeyDown` aparecem no projeto e não há padrão sistêmico de Esc, foco inicial, retorno de foco, focus trap e scroll lock.  
**Estresse gerado:** usuário de teclado pode perder o contexto; em mobile os formulários parecem caixas desktop reduzidas.  
**Direção:** um único `Dialog` acessível, com variante sheet em mobile, cabeçalho, rodapé, foco e fechamento consistentes.

### P1. Controles móveis menores que o alvo recomendado

**Onde:** login publicado em 390 px.  
**Evidência medida:** inputs e CTA com 37 a 38 px; revelar senha com 40 × 38 px; “Esqueci minha senha” com 19,5 px de altura.  
**Estresse gerado:** erro de toque e sensação de interface comprimida.  
**Direção:** mínimo visual e interativo de 44 px, com área clicável ampliada para links compactos.

### P1. Sistema visual existe, mas não governa a implementação

**Onde:** `globals.css` e componentes de tela.  
**Evidência:** mais de 5 mil linhas de CSS global, 423 estilos inline e somente cinco primitives em `components/ui`.  
**Estresse gerado:** telas semelhantes têm pequenas diferenças de espaço, foco, densidade e estado. O usuário sente “produtos diferentes costurados”.  
**Direção:** tokens semânticos, primitives e receitas de tela; remover estilos inline gradualmente, sem reescrever o stack.

### P2. Excesso de cards e métricas equivalentes

**Onde:** Painel de Hoje, Central de Célula e telas de configuração.  
**Evidência:** 121 linhas de JSX usam classes com `card`; a Central abre com seis cartões equivalentes.  
**Estresse gerado:** tudo parece importante e nada domina.  
**Direção:** usar listas, faixas, agrupamentos por espaço e divisores. Card só quando a elevação comunica um objeto independente.

### P2. Hierarquia tipográfica é visualmente estreita

**Onde:** telas operacionais e cabeçalhos.  
**Evidência:** apenas 40 headings semânticos em mais de 24 mil linhas de componentes; muitos títulos usam `div` e `.panel-title`.  
**Estresse gerado:** leitura por varredura e acessibilidade perdem estrutura.  
**Direção:** escala tipográfica curta, porém inequívoca, com `h1` da tela, `h2` de região e labels compactos.

### P2. Ajuda importante fica escondida em “i”

**Onde:** Topbar e `InfoTip`.  
**Estresse gerado:** novatos precisam descobrir o ícone para entender a tela; usuários de toque não têm hover.  
**Direção:** manter ajuda contextual curta junto da decisão difícil; usar tooltip somente para informação suplementar.

### P2. Cores da Jornada competem com estados semânticos

**Onde:** ícones de Ganhar, Consolidar, Discipular e Enviar.  
**Estresse gerado:** rosa, âmbar, verde e índigo podem parecer status, prioridade ou sucesso.  
**Direção:** cores de etapa mais silenciosas, aplicadas a pequenos marcadores; urgência, erro e sucesso preservam exclusividade semântica.

### P3. Dois anti-padrões determinísticos

- `globals.css:4924`: `border-left: 3px solid var(--warn)` cria a faixa lateral típica de callout genérico.
- `globals.css:566`: transição de `width` causa trabalho de layout; usar `transform` ou mudança instantânea.

## 7. Personas e pontos de ruptura

### Pastor em rotina intensa

- Perde a fila principal abaixo de métricas.
- Alterna entre Painel, Conversas, Central e Jornada e encontra diferentes camadas de navegação.
- Precisa confiar que uma ação crítica foi concluída sem procurar toasts transitórios.

### Administrador de primeira viagem

- Vê muitas telas de configuração com densidade semelhante e prioridade pouco explícita.
- Depende de tooltips e documentação para entender sequência e consequências.
- Em formulário modal longo, não tem um padrão claro de progresso, foco e recuperação.

### Líder usando celular

- Tem boa base em Minha Célula e Conversas, mas enfrenta controles pequenos e cards longos.
- A ação mais frequente pode ficar no topo, distante da zona do polegar.
- Interrupção durante formulário modal pode causar insegurança sobre perda de dados.

### Usuário dependente de teclado ou leitor de tela

- Encontra semântica parcial e foco visível em vários componentes.
- Pode ficar sem contenção e retorno de foco em diálogos.
- A hierarquia de headings não representa completamente a hierarquia visual.

## 8. Princípio de solução

O novo sistema visual deve ser mais silencioso e mais útil, não apenas mais sofisticado. Cada superfície deve responder visualmente a quatro perguntas:

1. Onde estou?
2. O que exige minha atenção agora?
3. Qual é a ação principal?
4. O que mudou depois que eu agi?

Se uma tela não responder às quatro em cinco segundos, ela ainda não está pronta.

