# Prompt para Claude Code + Fable

> **Estado atual: continuar na MESMA CONVERSA do Claude Code que concluiu os Gates 1–3.**
> Não abrir nova conversa, não repetir o inventário e não recriar as três direções. Executar somente o Gate 4 consolidado.

```text
Você será o executor principal da refatoração visual do sistema Igreja 12.

MISSÃO

Transformar a interface existente em um produto pastoral minimalista, fluido, intuitivo e visualmente marcante, sem criar nenhuma funcionalidade nova e sem alterar regras, rotas, APIs, permissões ou domínio.

O trabalho usa o próprio modelo Claude Fable 5 para explorar e aprovar a direção antes de qualquer código. "Fable" neste documento não significa uma ferramenta ou servidor MCP externo. Você não pode pular a etapa visual.

DECISÃO CRIATIVA POSTERIOR AO GATE 3

O Gate 3 foi aprovado com a estrutura `Quiet Pastoral Operations`, formada por Quiet Operations como base, calor humano seletivo de Pastoral Editorial e tabelas semânticas seletivas de Precision Workspace.

Depois dessa aprovação, o dono adicionou uma camada de identidade obrigatória chamada `Diamante Lapidado`. Leia também:

- `docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md`
- `DESIGN.md`

A metáfora da lapidação não autoriza decoração indiscriminada. A pessoa já possui valor; o discipulado revela, fortalece e forma em direção à semelhança de Cristo. Azul mineral, geometria lapidada e motion de encaixe devem orientar marca, foco, progresso e feedback, sem efeitos de luz e sem transformar o produto em joalheria, fintech, crypto, landing page religiosa ou dashboard de IA.

DECISÃO DE LOGO V2

- A proposta com abertura vertical central foi rejeitada por lembrar pinças, captura e anatomia feminina.
- Não tente corrigir essa forma. Elimine-a.
- A direção escolhida é a rota A, `Diamante Lapidado`.
- Use um diamante fechado, reconhecível e graficamente simplificado.
- As linhas internas representam planos visuais, não a quantidade total de facetas de um diamante real.
- O número `12` permanece no wordmark `Igreja 12`; não o codifique como contagem de facetas.
- Não use núcleo luminoso, estrela, brilho, clarão, feixe ou percurso de luz.
- Não explore novamente `Coroa Lapidada`, `Doze Cortes` ou outras rotas.
- Faça teste de silhueta, rotação, espelhamento e desfoque para eliminar associações involuntárias.
- Em toda ilustração de discipulado individual, homem discipula homem e mulher discipula mulher.
- Imposição de mãos segue a mesma regra, nunca par misto.

Antes de qualquer implementação, crie um Gate 4 visual consolidado mostrando `Quiet Pastoral Operations + Diamante Lapidado`. Inclua o símbolo escolhido, wordmark, paleta, motion frames e as 12 pranchas já exigidas. Exporte Artifact, HTML autocontido e PNGs portáteis. Pare para aprovação externa do Codex.

MODO DE TRABALHO

- Trabalhe como product designer sênior + frontend engineer.
- Seja cético com o briefing visual antigo. Preserve o que funciona, não a aparência por obrigação.
- Beleza deve reduzir esforço e aumentar confiança.
- Não transforme o produto em landing page, dashboard genérico de IA ou galeria de cards.
- Faça mudanças pequenas, revisáveis e comprovadas.
- Não invente dados, rotas, telas ou comportamentos.

FONTES DE VERDADE, EM ORDEM

1. PRODUCT.md
2. docs/design/AUDITORIA-UX-UI-IGREJA12-2026-07-11.md
3. docs/design/PLANO-MESTRE-REFATORACAO-VISUAL-IGREJA12.md
4. pontos-melhoria.md, somente para saber o que NÃO entra no ciclo visual
5. docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md
6. DESIGN.md
7. SPEC.md
8. docs/Docs20260611_163530/PRD20260611_163530.md
9. docs/Docs20260611_163530/design/design-brief.md
10. docs/design/RECONCILIACAO-igreja12.md
11. docs/design/REDESIGN-UX-AJUSTES-POS-F4.md
12. docs/design/CONTRATO-UX-CELULAS-CENTRAL.md
13. PRDs de Minha Célula e Central de Célula
14. Código atual

Em conflito, o código confirma o comportamento atual; PRODUCT.md e o Plano Mestre governam a nova direção visual; regras ministeriais travadas continuam imutáveis.

PRIMEIRO GATE: AMBIENTE

1. Confirme que os arquivos acima existem. Se estiver em um worktree limpo criado antes desses documentos serem commitados, leia as fontes read-only pelo caminho absoluto do checkout principal: `C:\Users\hanie\Searches\OneDrive\Documentos\workspace\PastorAi-1.0`. A ausência no seu worktree não é bloqueio quando a fonte existe nesse checkout principal.
2. Rode `git status --short --branch`, `git remote -v` e compare HEAD com `origin/main`.
3. Se o checkout estiver sujo com alterações que não são desta missão, não as toque.
4. Para implementar, use worktree e branch limpos a partir do `origin/main` atualizado.
5. Branch sugerida: `claude/redesign-visual-fable-f0`.
6. Confirme que a sessão está executando o modelo Claude Fable 5. Use a capacidade nativa do modelo e Artifacts/pranchas do Claude para a exploração visual.
7. Não procure nem exija MCP, comando ou ferramenta externa chamada Fable. Só responda `BLOCKED` se o próprio modelo não puder produzir as pranchas/Artifacts solicitadas.

SEGUNDO GATE: INVENTÁRIO READ-ONLY

Antes de desenhar:

- Mapeie app., admin. e painel.
- Liste telas, papéis, ações principais, estados e breakpoints.
- Identifique onde Sidebar, BottomNav, JourneyStepper e ModuleTabs coexistem.
- Conte e catalogue dialogs, formulários, tabelas, cards, banners, toasts e empty states.
- Confirme os dois anti-padrões determinísticos apontados na auditoria.
- Confirme que nenhuma proposta exigirá endpoint ou estado novo.
- Se encontrar melhoria funcional, registre como candidata em pontos-melhoria.md, mas não implemente.

SAÍDA DO GATE

- inventário curto;
- riscos;
- telas escolhidas como amostra;
- status `PASS`, `FAIL`, `BLOCKED` ou `SKIP`.

TERCEIRO GATE: CLAUDE FABLE 5 + ARTIFACTS, SEM CÓDIGO

Crie três direções no Fable:

A. QUIET OPERATIONS
- filas e listas dominantes;
- quase nenhum card;
- máxima calma e foco;
- teal reservado a ação e seleção.

B. PASTORAL EDITORIAL
- tipografia e whitespace mais expressivos;
- presença humana sem ornamento religioso;
- composição assimétrica controlada;
- familiaridade de produto preservada.

C. PRECISION WORKSPACE
- densidade eficiente;
- divisão clara entre ação e contexto;
- atalhos visuais para usuário recorrente;
- alta legibilidade de dados.

Cada direção deve mostrar:

1. Painel de Hoje desktop 1440.
2. Painel de Hoje mobile 390.
3. Conversas desktop 1440.
4. Conversas mobile: lista e thread em 390.
5. Minha Célula líder em 390.
6. Minha Célula discípulo em 390.
7. Central de Célula desktop com Dashboard.
8. Central de Célula mobile com Gerenciar Células.
9. Um formulário administrativo desktop.
10. O mesmo formulário como sheet ou página mobile.
11. Loading, empty, error, success e access denied.
12. Dialog desktop e sheet mobile.

REGRAS VISUAIS DURAS

- Produto, não marketing.
- Nada de gradient text.
- Nada de glassmorphism decorativo.
- Nada de hero metric SaaS.
- Nada de grid repetitivo de cards iguais.
- Nada de faixa lateral grossa em callout.
- Nada de preto ou branco puro.
- Nada de animação decorativa.
- Nada de ícone sem rótulo quando a ação não for universal.
- Cards apenas quando representam objetos independentes.
- Um h1 por tela e hierarquia semântica coerente.
- Touch target mínimo 44 x 44.
- WCAG AA.
- Mobile é composição própria, não desktop empilhado.

NORTE DA EXPERIÊNCIA

Cada frame precisa responder em 5 segundos:

1. Onde estou?
2. O que exige atenção agora?
3. Qual é a ação principal?
4. O que mudou depois da ação?

ENTREGA FABLE

- Link ou identificador de cada proposta.
- Pranchas lado a lado.
- Racional de no máximo 8 bullets por direção.
- Matriz comparativa: clareza, velocidade, calor humano, densidade, risco técnico e aderência à Igreja 12.
- Sua recomendação, com argumentos concretos.
- Lista do que foi preservado da identidade atual.
- Lista do que foi removido por gerar ruído.

PARE AQUI.

Este bloco registra o Gate 3 histórico, que já foi concluído. Não o execute novamente. A combinação aprovada foi `Quiet Pastoral Operations`. Não edite código e não sobrescreva o `DESIGN.md` existente. Siga para o Gate 4 descrito na decisão criativa do início deste documento.

APÓS A APROVAÇÃO DO DONO, CONTINUE NA MESMA CONVERSA

FASE DE CONSOLIDAÇÃO

1. Depois que o Gate 4 for aprovado, reconcilie a direção final com o `DESIGN.md` existente. Não o recrie do zero.
2. Defina tokens semânticos de cor, tipografia, spacing, radius, elevation, z-index e motion.
3. Defina anatomia e estados dos primitives mínimos.
4. Gere uma página/harness de referência usando CSS real do projeto.
5. Compare o harness com os frames Fable.

GATE

- Screenshot desktop e mobile.
- Contraste medido.
- Touch targets medidos.
- Zero código de tela migrado antes da aprovação do sistema.

FASE DE IMPLEMENTAÇÃO

Execute na ordem abaixo, um PR por onda:

PR 1: FUNDAÇÃO
- tokens semânticos;
- Button, IconButton, Field, Dialog, Toast, Banner, EmptyState, Tabs, PageHeader;
- remover transição de width e side-stripe;
- não alterar telas além do necessário para validar primitives.

PR 2: SHELL E NAVEGAÇÃO
- Sidebar, Topbar, BottomNav, drawer, JourneyStepper e ModuleTabs;
- no máximo uma navegação contextual por decisão;
- preservar NAV_SECTIONS, canSee, screenId, hash e deep-links.

PR 3: PAINEL DE HOJE
- fila na primeira dobra;
- métricas secundárias;
- hierarquia de urgência e ações;
- sem mudar chamadas ou dados.

PR 4: CONVERSAS
- preservar master-detail;
- lista, thread, composer, banners e drawer;
- hierarquia por risco das ações.

PR 5: MINHA CÉLULA
- discípulo: próxima reunião e presença primeiro;
- líder: relatório e planejamento primeiro;
- dados sensíveis progressivos;
- Central continua separada.

PR 6: CENTRAL DE CÉLULA
- exceções e tarefas antes de métricas;
- reduzir seis cards equivalentes;
- preservar cinco tabs e endpoints.

PR 7+: JORNADA E ADMIN
- Ganhar, Consolidar, G12, Enviar;
- Agenda, Pessoas, Comunicação, Relatórios;
- Configuração Inicial, Usuários, Permissões, Integrações, WhatsApp, Agente, Identidade, Assinatura;
- painel master por último.

REGRAS DE IMPLEMENTAÇÃO

- Não tocar backend, banco, migration, auth, RLS, RBAC, integrações ou env.
- Não adicionar dependência sem justificar e obter autorização.
- Não reescrever o frontend.
- Não mover tudo para componentes genéricos.
- Remover estilo inline apenas nas áreas migradas.
- Toda mudança visual deve preservar estados loading, empty, error e populated.
- Toda mudança de copy deve preservar significado e regra.
- Se o design exigir comportamento novo, pare e registre fora do escopo.

VALIDAÇÃO OBRIGATÓRIA POR PR

- 360, 390, 414, 768, 1024 e 1440 px quando relevante.
- Sem overflow horizontal.
- Zoom 200%.
- Teclado completo nos fluxos críticos.
- Esc e focus trap em dialogs.
- prefers-reduced-motion.
- contraste WCAG AA.
- npm run typecheck.
- npm run lint.
- npm run build.
- testes existentes relacionados.
- screenshots antes/depois.

RELATÓRIO DE CADA PR

1. Objetivo.
2. Arquivos alterados.
3. Antes/depois.
4. Invariantes funcionais confirmados.
5. Testes e medições.
6. Riscos e limitações.
7. Veredito por gate: PASS / FAIL / BLOCKED / SKIP.

DEFINIÇÃO DE PRONTO FINAL

- Ação primária identificável em 5 segundos.
- Fluxo recorrente concluível em menos de 60 segundos.
- No máximo duas camadas de navegação simultâneas.
- Nenhum card aninhado.
- Nenhum dialog sem foco correto.
- Nenhum controle móvel abaixo de 44 x 44.
- Nenhuma mudança funcional.
- Screenshots e testes comprovam desktop e mobile.

ESTADO ATUAL DA MISSÃO

- Gates 1, 2 e 3: concluídos e aprovados.
- Direção estrutural: `Quiet Pastoral Operations`.
- Nova camada de identidade: `Diamante Lapidado`.
- Próxima execução: somente Gate 4, símbolo + identidade + 12 pranchas consolidadas + evidência portátil.

AGORA EXECUTE SOMENTE O GATE 4. Não implemente, não altere código de produto e não modifique o worktree. Depois pare para aprovação externa do Codex.
```
