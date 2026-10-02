# Expressividade v 3: composição, copy e movimento

Proposta para revisão visual em 01/10/2026, pesquisa às 22:04UTC (19:04BRT).
Nenhum arquivo do produto foi alterado nesta etapa. A direção precisa aparecer
em prancha e prévia de movimento antes de sua implementação. Este documento
não substitui o QA nem publica o candidato v 2.

## Decisão de direção

Dar presença à marca e ritmo à leitura, mantendo a tarefa fácil de localizar.
A assinatura proposta combina Sora, azul Diamante, superfícies claras,
tipografia maior nos pontos de orientação e uma única peça gráfica da marca na
entrada. O controle principal continua reconhecível antes de qualquer efeito.

O salto visual deve ser percebido no cabeçalho, no acesso e na relação entre
lista e detalhe. A fila operacional permanece estável enquanto a pessoa lê,
digita, usa teclado ou recebe atualizações. Movimento entra para mostrar
origem, resposta e mudança de contexto; mouse e scroll têm uma expressão
específica, sem transferir o efeito para dados pastorais.

### Referência fornecida

[Vitalex](https://vitalex-ttm.webflow.io/) foi observado pelo executor no CUA.
A síntese recebida registra hero fotográfico amplo, h1 Geist 124px, CTA de alto
contraste, menu central em pill escura, fotos antes dos blocos e lista de
serviços com expansão. Métricas/ticker também foram observados. A inspeção
independente deste pesquisador não verificou os pixels nem o comportamento de
scroll da referência. O executor confirmou por PageDown painéis A e C no mesmo espaço visual, com
imagem/copy alternando e trilho A/B/C. Isso sustenta composição ancorada e
progressão narrativa observadas, sem afirmar biblioteca, algoritmo ou que
posições do DOM, isoladamente, provem o efeito.

| Sinal da referência | Adaptação ao Igreja 12 | Limite de aplicação |
|---|---|---|
| Grande gesto tipográfico de entrada | Frase de marca em Sora no acesso desktop; título operacional maior com subtítulo curto | Hero não ocupa a primeira dobra de tarefa no app; não importar Geist nem escala 124px para listas/formulários |
| Contraste forte entre CTA e superfície | `action-primary`/`text-on-action`, título em `text-primary` e borda legível | Preservar azul Diamante; verde permanece semântica de estado confirmado, sem lime de marca |
| Ritmo entre imagem e conteúdo | Peça gráfica autoral de facetas Diamante na entrada; áreas de conteúdo com respiro e uma prioridade | Fotografias somente se houver material autêntico autorizado; não inventar foto da igreja, membros ou atendimento |
| Serviços em linhas expansíveis | Linhas de pessoa com ação visível e detalhe em região própria; apoio em disclosure | Expandir continua separado de avançar, salvar ou abrir; sem mover dados no hover |
| Processo por etapas | Conservar etapas reais de relatório/comunicado e explicitar próxima ação | Não criar wizard para API sem estado nem afirmar passo concluído antes da resposta |
| Contadores e ticker | Valores reais estáticos, apoiando a fila | Não animar contagens de pessoas, pendências, progresso pastoral ou saúde; nenhum ticker no workspace |

## Pesquisa 21st: proveniência e alcance

Foram feitas 9 consultas livres com `mcp__21st__search`, `type=component`,
`limit=4`: login, sidebar, painel, lista/detalhe, formulários, agenda, console,
pointer e scroll. Retornaram 36 metadados. Não foram chamados `get_component`,
geração paga, instalação, bookmark ou publicação. Nenhuma chave ou comando com
credencial entra neste artefato.

Nome, descrição e URL são informações do catálogo. A seleção abaixo é uma
inferência de adequação a partir desses metadados; não afirma acessibilidade,
qualidade de código, licença de implementação, performance ou fidelidade visual
do componente. Previews/vídeos foram retornados pelo catálogo, mas não
inspecionados por este pesquisador. A proposta reutiliza os componentes locais,
sem adoção do código externo ou de outro design system.

### Sete famílias, decisão única por família

| Família e consulta | Referência 21st selecionada | O que vale transportar para a identidade Igreja 12 | Menor mudança local proposta | O que conservar |
|---|---|---|---|---|
| Login, `login sign in` | [Split Login, id 28369](https://21st.dev/@mohammadshehadeh/components/login-03); secundária [login, id 2428](https://21st.dev/@ephraimduncan/components/login-2) | Separação entre expressão da marca e tarefa de entrada, com assinatura ampla e formulário claro | `AuthLayout`: em≥1024px, área gráfica azul de até 42% e formulário 440px. A frase de marca fica na área gráfica; campos/error/links permanecem na área funcional. Em mobile, marca compacta e coluna única | Login por e-mail/senha, recuperação e links legais atuais; não importar botão social GitHub do exemplo nem citação/testemunho inventados |
| Sidebar, `sidebar navigation` | [Sidebar Nav Group, id 24865](https://21st.dev/@felipemenezes098/components/collapsible-05) | Grupos com expansão previsível, rótulo forte e caminho selecionado reconhecível | Elevar rótulos para 15px, destacar seleção com superfície azul compatível e manter contexto da igreja. Ícone/chevron recebe feedback 140ms no mouse | Sidebar/BottomNav/useDrawerA 11y, hashes reais, foco e grupos autorizados; sem switcher de tenant ou badges de novidade fictícios |
| Painel, `dashboard bento` | [Analytics Bento, id 9658](https://21st.dev/@jatin-yadav05/components/analytics-bento), como referência secundária de ritmo | Espaço desigual pode evidenciar uma prioridade | Manter fila v 2 como centro; cabeçalho editorial com título 32px e uma ação, reunião/agenda em região de apoio. Representar a tarefa por escala e alinhamento | Dados atuais e superfície estável. Não adotar dashboard bento de métricas, gráfico ou radar de saúde. Os resultados encontrados não demonstram opção superior à fila aprovada |
| Lista/detalhe, `list detail` | [List Group Custom Content, id 29346](https://21st.dev/@uiable/components/list-group-custom-content) + [Key Value List, id 25162](https://21st.dev/@corr/components/key-value-list) | Nome/tarefa primeiro; pares rótulo/valor para contexto sem pilha de cards | Nome 16px, contexto 14px, estado textual e uma ação por linha. Detalhe organiza dados em lista de definição, com primeira seção aberta; apoio sob demanda | Filtros/página/seleção/foco/retorno v 2 e campos autorizados. Sem follow social, score, timeline ou ações em massa novas |
| Formulários, `form field` | [Field, id 18215](https://21st.dev/@intentui/components/field); secundária [Field, id 11458](https://21st.dev/@coss.com/components/field) | Relação evidente entre rótulo, ajuda, entrada e erro | Padronizar seções com heading 18px, campo 16px/48px no acesso e≥44px nos fluxos, rótulo 14px e erro imediatamente associado. Uma ação principal por seção transacional | Controles nativos, validações e DS local. Metadados que dizem “accessible” não constituem prova; não trocar por BaseUI para obter o aspecto |
| Agenda, `calendar date picker` | [Calendar, id 483](https://21st.dev/@originui/components/calendar); secundária [Calendar Basic, id 30812](https://21st.dev/@uiable/components/calendar-basic) | Seleção de dia forte e toolbar simples | Ajustar presença do dia selecionado, título de período e lista de eventos com nome/horário/origem. Lista do dia continua logo abaixo no mobile | Calendário atual, Semana/Mês/Ano/A confirmar, fuso e teclado. Não instalar date picker que apague modos, confirmação ou permissões existentes |
| Console, `data table admin` | [Data Table, id 31861](https://21st.dev/@wensity/components/data-table); secundária [Data Table, id 28327](https://21st.dev/@ephraimduncan/components/table-05) | Ação de linha explícita, alvo legível e detalhe expandível onde o contrato comporta | Igreja alvo 32px no detalhe, coluna de identidade com estado textual e ação “Abrir igreja”; operações agrupadas com contrastes claros. Métricas reais em segunda hierarquia | DataTable local, página dedicada e RBAC. Não acrescentar pesquisa global, sorting de endpoint, seleção em massa, exportação ou last-login/2FA ausentes |

### Metadados de mouse e scroll

| Referência | Adequação e decisão |
|---|---|
| [Mouse-Responsive Background, id 2588](https://21st.dev/@minhxthanh/components/mouse-responsive-background) | Inspira movimento de um plano decorativo da marca na entrada. Limitar a≤6px, fora do formulário e apenas em pointer fino. Não transportar o efeito para tabela, mensagem, avatar de pessoa ou calendário |
| [Mouse Following Line, id 6272](https://21st.dev/@ravikatiyar162/components/mouse-following-line) | Campo reativo de linhas é expressivo, mas sua repetição aumenta atividade visual. Não selecionado para o app; uma única faceta autoral dá presença sem campo de linhas contínuo |
| [Scroll Reveal, id 18654](https://21st.dev/@cnippet-dev/components/scroll-reveal-2) | O modo once descrito é adequado a apoio não crítico. Proposta local sem biblioteca: uma revelação curta de bloco auxiliar, nunca aplicada a item de polling ou controle necessário |
| [Scroll Reveal Image, id 24466](https://21st.dev/@unlumen/components/scroll-reveal-image) | A descrição inclui animação de largura. Não selecionado: no workspace, reservar espaço e usar transform/opacity evita reflow durante uso |
| [Bento Dashboard, id 9758](https://21st.dev/@daiwiikharihar/components/bento-dashboard) | Sistema de métricas/radar animados e stack adicional não atende ao cuidado por tarefa. Mantida a composição v 2 |

## Delta visual mensurável

Os números abaixo são metas da proposta, sem afirmar ganho medido ou
implementação. Os tokens atuais têm display 28px, body 15px, label 14px e
meta 13px. Aumentar presença onde a pessoa se orienta, preservando o espaço das
ações, produz diferença verificável sem ampliar informação.

| Ponto | V 2 consultada | Proposta v 3 | Como verificar |
|---|---|---|---|
| Entrada desktop | Coluna central de formulário até 440px | Composição split a partir 1024px; área de marca até 42%, formulário 440px, frase de marca 48–56px/1.08 e título funcional 28px | Capturas 1024/1440; campos e botão sem scroll obrigatório em altura 900px; nenhuma imagem atravessa campo |
| Entrada mobile | Marca/formulário em uma coluna | Preservar coluna; frase de marca dispensada ou 24px em uma linha curta, heading 28px e campos 48px | Captura 390× 844 com erro e teclado simulado; login e recuperação permanecem encontráveis |
| Orientação do app | Títulos compactos e superfícies neutras | Título principal 32px desktop/28px mobile; subtítulo 16px; cabeçalho com um gesto azul da marca e uma ação | Em 390× 844 a tarefa/fila e sua primeira ação aparecem sem rolar um hero |
| Leitura por pessoa | Body 15/meta 13 | Identidade 16px, apoio 14px, entrelinha 1.45–1.55, rótulo 14px. Duas linhas úteis antes do detalhe | Nomes longos identificáveis, ações presentes em 390/768/1024/1440; sem truncar informação necessária |
| Marca | Logo e azul do sistema | Logo intacta mais facetas gráficas autorais, geometria aberta e≤2 planos decorativos no acesso | Comparar imagem estática inicial e foco. A marca reconhecível vem antes do movimento |
| Seleção | Estado textual e ação | Estado textual preservado; seleção em `selection-soft`, contorno/foco legíveis e indicador por forma | Contraste texto≥4.5:1, foco≥3:1, controle≥44× 44px; cor isolada não comunica seleção |
| Informação concorrente | V 2 usa apoio em disclosure | Reforçar ordem título→estado→próxima ação; manter detalhe adicional fechado por padrão | Contar ações primárias visíveis por região: exatamente 1 quando há tarefa transacional; nenhuma removida por decoração |

Não aplicar mudança tipográfica global antes de conferir densidade dos quatro
tamanhos. O aumento deve ser por papel semântico, com meta 13px limitado a
informação auxiliar; descrição necessária para decidir usa 14–16px.

## Copy amostra para a prancha

Copy identifica ação, efeito e estado. Não promete produto completo, envio,
aprovação, cobertura pastoral ou ganho não comprovados. Termos jurídicos,
mensagens do servidor, valores e nomes de papéis conservam sua fonte.

| Área | Texto proposto | Condição de uso |
|---|---|---|
| Expressão da marca no acesso | **Cuidado que continua.** / Pessoas, conversas e próximos passos no mesmo lugar. | Frase editorial, sem promessa de automação ou resultado. Logo original ao lado, sem redesenho |
| Formulário de login | **Entre na sua igreja** / Use o e-mail e a senha da sua conta. / **Entrar** / Esqueci minha senha | Mantém tarefa/entrada atual; rótulos dos campos permanentes |
| Recuperação | **Recuperar acesso** / Informe o e-mail que você usa para entrar. / **Pedir novo link** | Confirmação neutra existente permanece; não afirmar que conta existe ou que e-mail foi entregue |
| Hoje | **Hoje** / Veja os cuidados que precisam de atenção e escolha o próximo passo. | Texto estático; prazo/estado/responsável apenas quando a fonte os fornece |
| Conversa | **Atendimento com [nome validado]** / Sob responsabilidade de [responsável atual]. / **Assumir atendimento** ou **Enviar mensagem** | Ação depende do modo/capacidade/servidor; pessoa inexistente usa “Contato” sem identificação inventada |
| Pessoas | **Pessoas** / Encontre o registro e acompanhe o que acontece a seguir. / **Cadastrar pessoa** | Filtros/busca não prometem alcance global além do contrato |
| Ganhar | **Ganhar** / Acompanhe visitantes e ajude a construir o próximo vínculo. / **Avançar para Consolidar** | Domínio conserva regra de avanço e vínculo; sem pontuação ou linguagem de conversão quantitativa |
| Detalhe de cuidado | **Próximo passo** / [ação derivada do estado] / **Jornada e responsáveis** | Quando derivação não existe, mostrar estado disponível e ação autorizada; não fabricar recomendação |
| Gestão | **Gestão da igreja** / Configure pessoas com acesso, conexões e informações da igreja. | Pessoa, conta e responsabilidade continuam conceitos separados |
| Estado do assistente | **Assistente ativo**, **Assistente desativado** ou **Estado indisponível** / Salvar a credencial não ativa o assistente. | Somente afirmar ativo/desativado após configuração confirmada; erro nunca vira estado padrão |
| Plataforma | **Console da Plataforma** / Escolha a igreja antes de administrar seus dados. / **Abrir igreja: [nome validado]** | Identifica tenant e operação; nenhuma troca de igreja conserva rascunho de outro tenant |
| Falha de escrita | **Não foi possível salvar.** / Seus dados continuam nesta tela. / **Tentar novamente** | Segunda frase somente nos fluxos que realmente preservam preenchimento; sem retry automático |
| Bloqueio de formação | **Módulo indisponível** / Turmas, presença e certificação não podem ser registradas nesta área. / **Voltar ao Hoje** | Sem promessa de data, curso, certificado ou formação implementada |

## Protocolo de movimento

Aplicação das skills
[animate](/home/raniel-linux/.agents/skills/animate/SKILL.md),
[scroll-craft](/home/raniel-linux/.agents/skills/scroll-craft/SKILL.md) e
[motion-design](/home/raniel-linux/.agents/skills/motion-design/SKILL.md).
O escopo desta etapa é pesquisa/proposta. Não foram iniciados build de landing,
geração de assets, engine de scroll, instalação de biblioteca ou execução paga.

Decisões de autoria: intenção emocional de acolhimento e segurança; ritmo
contido no trabalho e expressão maior na entrada. O momento memorável é uma
faceta Diamante que responde levemente ao pointer e se estabiliza quando a
pessoa entra no formulário. Cada área recebe a mesma assinatura por forma,
contraste e tipografia, sem repetir uma animação ornamental em todos os dados.

Reutilizar os tokens atuais: `motion-fast=140ms`, `motion-standard=200ms`,
`motion-expressive=640ms`, `ease-out-productive` e `ease-out-expressive`.
Os 640ms se aplicam somente à peça editorial inicial, nunca a campo, botão,
navegação ou leitura. Ações frequentes e teclado têm estado imediato.

| Momento | Finalidade | Movimento proposto | Gatilho e cancelamento | Toque/reduced motion |
|---|---|---|---|---|
| Peça de marca do acesso | Expressão, baixa frequência | Uma única faceta decorativa chega de 8px/opacity 0 a posição final em 640ms, sem stagger de formulário | Uma vez por entrada; nunca espera rede nem altera posição do form. Navegar desmonta/cancela | Mobile usa peça estática menor; reduced motion mostra estado final imediatamente |
| Pointer na peça de marca | Resposta leve à presença | Plano decorativo desloca≤6px em cada eixo; placa textual/logo/form não seguem pointer | Somente `(hover:hover) and (pointer:fine)`; atualizar transform do elemento em no máximo 1rAF por frame; pointerleave estabiliza em 200ms; suspender ao focar o formulário | Touch e teclado usam composição estática. Reduced motion desativa listener/transform |
| Link/ação por mouse | Feedback | Cor/contorno 140ms; ícone pode deslocar 2px. Texto permanece fixo | Hover gated; pressionar não posterga o handler. Retarget com transição, sem keyframe reiniciado | Touch mostra feedback de estado sem hover persistente; teclado mantém foco imediato |
| Lista→detalhe ocasional | Origem e mudança de contexto | Detalhe entra com 4–8px/opacity em 200ms; lista e toolbar imóveis | Clique pointer. Selecionar novamente interrompe e mostra dado atual; não animar troca vinda de polling | Mobile pode usar a mesma curta orientação, se não atrasar Voltar; teclado/reduced motion mostram instantaneamente |
| Diálogo/drawer ocasional | Mudança de contexto | Painel translate 8px +opacity em 200ms; saída simétrica 140ms. Overlay sem blur animado | Clique; trava/foco ativos imediatamente. Esc, ação e troca de rota não esperam animação para cumprir contrato | Teclado/reduced motion eliminam deslocamento. Foco contido e retorno preservados; touch não depende de gesto |
| Apoio alcançado por scroll | Ritmo de leitura | Um bloco auxiliar revela de 4px/opacity em 200ms, once, sem cadeia de itens | Somente apoio sem controle essencial; IO dispara uma vez e desconecta. Texto já existe e permanece visível sem JS | Mesmo conteúdo sem pinning no mobile; reduced motion mostra tudo no primeiro frame |
| Rolagem da lista | Orientação | Header permanece legível; borda estática sinaliza separação após scroll | Scroll nativo. Eventual listener passivo/único comrAF; não interceptar wheel/touchmove | Mesma orientação em touch/reduced motion; nenhum smooth-scroll obrigatório |
| Sucesso/erro | Estado confirmado | Texto e ícone aparecem com estado real; opção de fade 140ms no pointer | Somente após resposta validada. Erro mantém campo/foco e permite ação; nada de shake ou celebração em fila | Mesmo estado imediatamente em teclado/reduced motion. ARIA anuncia resultado sem deslocar o formulário |

O bloco global existente de `prefers-reduced-motion` já reduz animação e
transição a estado imediato. Preservar esse contrato. Não criar exceção local
que reative faceta, parallax, smooth-scroll ou movimento de listas nessa
preferência. Opacidade pode ser direta, sem transição, e toda informação é
visível no primeiro frame.

Scroll nativo permanece livre: sem scroll hijack, scroll de oito telas para
uma tarefa, pinning sobre formulário, vídeo scrub obrigatório, autoplay ou
cursor substituído. O efeito decorativo não ocupa camada sobre controle, não
recebe foco e tem `pointer-events:none`/`aria-hidden` quando implementado.

## Performance, dados e testes de aceite

Metas de implementação, ainda não medidas:

| Controle | Aceite concreto |
|---|---|
| Custo técnico | Zero dependência nova para o delta; CSS/transições/IO/WAAPI local quando necessário. Não incluir Framer Motion/Tailwind/React Day Picker só para reproduzir aparência |
| Layout | Efeito não altera width/height/top/left/margins durante uso; posição e tamanho reservados desde o primeiro frame. Zero layout shift atribuível à decoração |
| Polling | Dez atualizações sintéticas preservam foco, posição, seleção e rascunho; não reiniciam entrada nem stagger de linhas |
| Mouse | Efeito local≤6px, uma atualização por frame, sem trabalho fora do componente/aba ativa e sem listener em coarse pointer/reduced motion |
| Interrupção | Trocar seleção, navegar ou pressionar Esc durante movimento mantém o estado/rota final corretos. Nenhum callback atrasado escreve em seleção/tenant anterior |
| Frame e input | Em captura de performance do mesmo dispositivo, decoração não introduz long task>50ms, nem bloqueia foco/handler. Comparar v 2/v 3 comCPU 4×, sem afirmar universalidade a partir do desktop |
| Tipografia/contraste | Texto normal≥4.5:1, foco≥3:1 contra adjacência; medir no frame decorativo mais claro/escuro. Fonte 16px em entrada; todos os controles móveis≥44× 44px |
| Mobile | 390/768/1024/1440px e touch coarse. Form/error/voltar acessíveis com viewport reduzido para teclado; nome/ação não cortados; sem overflow do documento |
| Acessibilidade | Tab/Shift+Tab, Enter/Space e Esc equivalentes ao pointer; leitura/ordem DOM estáveis; focus-visible estático. Validar também leitor de tela instalado e zoom nativo 200% antes de afirmar cobertura desses critérios |
| Estado real | Conteúdo/sucesso/contagem não dependem de animação. Sem progressos simulados, contador de 0 até valor, saúde fictícia ou celebração antes de commit |
| Dados | Pesquisa/prancha usa somente exemplos sintéticos e marca autorizada. Nenhuma captura de Pessoas, conversa pastoral, key, token ou tenant real para referência |

## Conjunto revisável e próximo gate

A prancha do executor deve mostrar: acesso split desktop e coluna mobile;
Hoje com cabeçalho novo e fila preservada; pessoa aberta com lista de definição;
gestão/console com alvo explícito. Cada quadro tem ação principal, variante com
erro, foco visível e legenda curta do gesto. A peça Diamante é autoria local,
sem transformar a logo original em objeto deformável.

A prévia de movimento precisa permitir observar estados inicial/meio/final,
interrupção, pointerleave, seleção repetida, scroll nativo e reduced motion.
Screenshots isolados não comprovam mouse/scroll, duração ou cancelamento.

O gate é a aprovação do delta concreto de referências + copy + design + motion
exigido pela
[revisar-ux-igreja12](/home/raniel-linux/.agents/skills/revisar-ux-igreja12/SKILL.md).
A skill registra: “delta visual relevante exige aprovação apenas do delta”.
A pesquisa não implementa esse conjunto. O executor apresentará a prancha e a
prévia para revisão; o candidato v 2 continua com sua evidência de QA separada.

## Revisão crítica do guard de hash

Leitura de `frontend/src/lib/use-hash-route.ts` e seu teste de hidratação no
worktree `ux-global-v 2-final` em 01/10. O cache novo mantém snapshot estável até
`hashchange` aceito, de modo que renderização disparada antes do evento não
desmonte o rascunho. O guard de Permissões em captura restaura URL e interrompe
evento cancelado; como o subscriber não executa, o cache permanece na rota
original. A última unsubscribe limpa o snapshot; navegar novamente para hash
igual força ressincronização após `replaceState`.

Nenhum achado concreto novo por código. O achado original do E 2E permanece
pendente de fechamento no build final. A suíte unitária consultada cobre
SSR/hidratação, eventos, mesma rota e remoção da assinatura; não reproduz
explicitamente render entre mudança de URL e evento cancelado nem múltiplos
assinantes. O E 2E de Permissões deve provar cancelar/aceitar saída preservando
rascunho e número de writes no candidato final. Não se infere fechamento pelo
build ou pela presença do cache.
