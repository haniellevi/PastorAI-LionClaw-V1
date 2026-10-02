# Igreja12: execução da UX expressiva v3

## Autorização e candidato

Em 01/10/2026, Raniel aprovou o [conjunto concreto de referência, copy, composição e motion](../design/UX-EXPRESSIVA-V3-APROVADA.md) e autorizou sua aplicação em todo o sistema e a publicação do frontend. A proposta pré-implementação tem SHA256 `be616f40fa6263f34109d8b4ead4e41872576a272c9a67ca71384e9b91501b19`.

Execução no worktree `/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0`, branch `codex/ux-global-v2-final`, sobre `d46d765c0e2853a38b3f484140e281da643f73de`. O checkout original do usuário permanece preservado. Base comparada: main `342b255e309f49b03177d31259d92bb87cc3c1f9`. A implementação e suas correções dirigidas foram validadas localmente; a regressão integrada e a publicação são registradas pelo SHA exato na [PR consolidada #450](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/450) e no recibo de deployment. O registro da PR recebe os resultados finais, o commit de merge, o deployment e a verificação dos aliases somente após a execução real.

## Cobertura e preservação

As 42 unidades da [matriz v2](2026-10-01-ux-global-v2.md) recebem a fundação v3 e os estilos de suas famílias. A nova composição usa Sora/Plus Jakarta Sans, azul mineral, marca Diamante Lapidado nativa e formulários claros. Nenhuma dependência nova.

| Unidades | Aplicação executada | Conteúdo e efeitos preservados |
|---|---|---|
| U01/U25 | Navegação com seleção por superfície e rótulos15 | Grupos, hashes, papéis, logout, links entre superfícies e drawer |
| U02–U05/U35 | Acesso split48/52, mobile compacto, headline48–56/form28, copy do passo | Campos, tokens, recuperação neutra, convite e sessões distintas |
| U06–U08 | Hoje com faixa mineral, primeira tarefa enfatizada; lista/thread16/14 e compositor16 | Fila inteira, callbacks por capacidade, responsável, mídia, rascunho e retorno |
| U09–U13 | Pessoas, Ganhar e Consolidação com linhas16/14 e detalhe em pares; Contato e percurso | Todas as colunas, telefone/dados, filtros/página, CSIM, vínculos e critérios de avanço |
| U14–U20 | Células/G12/Central/Minha célula/Enviar com superfície clara e contexto selecionado | Papéis, saúde, foco do atalho, reunião escolhida, presença/relatório e solicitações |
| U21–U24 | Agenda, comunicados, relatórios e perfil com seção18/label14/campo16 | Modos/fuso/períodos, confirmação, etapas, identidade/senha e gates |
| U26–U34 | Gestão com faixa mineral; demais formulários claros; Minha célula na matriz | Seis itens checklist, logo original, permissões/rascunho, canais/cron/credencial e owner-only |
| U36–U39 | Console standalone mineral, tabela16/14, revisão repete taxa personalizada | Igreja alvo, moedas/métricas, links de ferramentas, convite separado e controles sensíveis |
| U40–U42 | Indisponibilidade real, documentos legíveis e estados semânticos | Textos jurídicos integrais, índice/links, erros, retry e módulos bloqueados |

A [paridade operacional](../design/UX-V3-PARIDADE-OPERACAO.md) e a [paridade administrativa](../design/UX-V3-PARIDADE-ADMINISTRACAO.md) registram fontes, hashes e condicionais. Componentes sem rota, como PublicAgentProfile, não se tornam novas telas por esta missão. Formação indisponível não recebe cursos/certificados fictícios. Não foi identificado outro site público antigo além das superfícies existentes.

## Correções verificáveis

Além da apresentação, a base corrige navegação cancelada, Back e Forward na matriz sem perder rascunho ou destinos, disclosure Ver saúde com destino/foco, erros de Pessoas e agente sem falso vazio/inativo, e carregamento de Células/Central sem falso zero. A confirmação de descarte em Pessoas bloqueia o submit por Enter e o fechamento durante busy. Payloads, APIs e RBAC existentes permanecem. Negativos dirigidos demonstram as falhas anteriores; testes sintéticos não comprovam dados ou provedores vivos.

Motion usa CSS, IntersectionObserver e rAF nativos. Facetas separadas respondem no máximo6px com um frame pendente, cancelam durante foco, em mudança de preferência e desmontagem. Pointer coarse/reduced são estáticos. Apoio revela uma vez com scroll nativo e fica visível sem JS. Diálogo mantém foco/Esc imediatos; polling não reinicia decoração.

A revisão independente identificou folga insuficiente potencial no compositor1024 e entrada decorativa durante foco. Padding intermediário e regra de foco foram corrigidos. As antigas asserções de fonte sobre aparência v2 foram retiradas quando não representavam a cascata v3; medidas renderizadas assumem essa validação.

## Verificação e release

A primeira rodada v3 registrou 59 PASS e 5 FAIL em 4 min: um header com 201px em 1024 e quatro ocorrências do mesmo seletor ambíguo de heading. Foram corrigidos o layout do header, o seletor, o badge Tipo quebrado e os chips mensais da Agenda em 768 (44px/14px). A rodada inicial está preservada em `ux-expressiva-v3/qa-v3-rodada1`.

A segunda rodada passou 65/65 cenários em 4,1 min, com 1.080 testes unitários em 116 arquivos, build, lint e typecheck aprovados. Medidas renderizadas nas quatro larguras registraram contraste 6,91 no apoio, 6,36 na ação, 4,16 no foco, 13,57 no texto da faixa mineral e 9,61 na seleção do menu. O header desktop mediu 133px em 1024 e 141px em 1440. Estes números descrevem somente os elementos e estados exercitados, sem declarar certificação geral de acessibilidade.

A revisão independente posterior encontrou três P2 que exigiram nova correção: envio por Enter durante a confirmação de descarte em Pessoas, substituição do destino anterior ao cancelar Back em Permissões e fragmentação de palavras no evento mensal em 768. As evidências da segunda rodada estão preservadas em `ux-expressiva-v3/qa-v3-rodada2`; Os 1.093 testes unitários em 117 arquivos passaram após os patches; resultado final de navegador e SHA serão registrados após a regressão destas correções.

A terceira rodada passou 62 cenários e falhou em três: os dois casos de Permissões detectaram remount pelo wrapper do Next ao anotar uma entrada de histórico com state vazio; o caso mensal de 768 encontrou uma palavra longa fragmentada. O hook foi corrigido para preservar o state inteiro do mesmo documento e anotar metadado sem argumento URL. A Agenda reutiliza sua seleção de dia e lista completa de eventos quando a largura útil é estreita, inclusive com sidebar, mantendo a grade desktop quando há espaço. As três larguras de 768, 1024 e 1440 entram na verificação mensal. Evidência anterior preservada em `ux-expressiva-v3/qa-v3-rodada3`.

A quarta rodada dirigida fechou a Agenda em 768/1024/1440 (3 PASS), também revisada visualmente sem novo corte. Os dois casos de Permissões ainda falharam no primeiro cancelamento. Instrumentação do navegador demonstrou que o assinante nativo de hash publicava a rota antes do guard registrado no Window, desmontando o formulário, sem novo documento ou delta zero. O veto passa a ocorrer no assinante antes de publicar o snapshot de rota. Registros e capturas anteriores estão em `ux-expressiva-v3/qa-v3-dirigida-rodada4`.

A execução final compilada de Permissões passou os dois cenários em 390/1440 (11,2 s), preservando rascunho, Back, Forward e os destinos anteriores/futuros com Navigation API ausente. A fonte final passou 1.096 testes unitários em 117 arquivos, build com lint/types e a revisão de escopo. A Agenda passou três cenários renderizados em 768/1024/1440. Artefatos preservados em `ux-expressiva-v3/qa-v3-dirigida-final`; o head antes do commit era `d46d765c0e2853a38b3f484140e281da643f73de`, portanto esses testes locais são vinculados aos hashes de arquivo do candidato, sem atribuí-los a um commit ainda inexistente. A suíte integrada de 67 cenários e os cinco checks obrigatórios serão vinculados ao commit final na PR.

Frontend será publicado somente a partir do SHA exato revisado em main, conforme [runbook](../ops/PRODUCTION-RUNBOOK.md#7-deploy-do-frontend). Aliases app/admin/painel, bundle sem localhost e deployment READY do mesmo SHA precisam ser conferidos. Baseline/rollback confirmado em 02/10/2026 às 00:00:51 UTC: deployment `dpl_EyiD4Y7ZM4vSQer478fPQMVjvgda`, READY, main `342b255e309f49b03177d31259d92bb87cc3c1f9`, com os três aliases. Esse estado será reconsultado no momento da publicação. O recibo final será preservado no pacote `ux-expressiva-v3/recibo-producao-v3.json` e no registro da PR consolidada.

A missão não inclui backend, schema, banco compartilhado, envio real, cobrança ou ativação do agente. A autorização atual cobre o release frontend; o próximo gate de produto, fora desta missão, continua sendo autorização nominal de qualquer operação com provedor/tenant real.
