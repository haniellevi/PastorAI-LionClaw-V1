# Paridade semântica de operação, U01 a U24

Snapshot histórico de auditoria. Correções posteriores, QA e evidência de publicação estão no [registro de execução v3](../sprints/2026-10-01-ux-expressiva-v3.md). Os achados abaixo descrevem a árvore e o horário registrados nesta captura.

Registro anterior à correção do achado F1. Escopo: informações, campos, indicadores, ações, estados e destinos da versão antiga versus a árvore atual, incluindo conteúdo recolhido. Auditoria de código, sem backend, dados privados ou produção. Nenhuma mudança visual foi aplicada nesta auditoria.

## Proveniência

- Worktree: `/home/raniel-linux/.codex/worktrees/ux-global-v2-final/PastorAi-1.0`.
- Branch: `codex/ux-global-v2-final`.
- Base antiga `origin/main`: `342b255e309f49b03177d31259d92bb87cc3c1f9`.
- HEAD atual: `d46d765c0e2853a38b3f484140e281da643f73de`, acrescido do diff local compartilhado.
- Captura UTC: `2026-10-01T22:09:08.797294+00:00`.
- Critério: todo conteúdo operacional real da base permanece disponível no mesmo contexto de autorização, com valores derivados da mesma fonte e ações que alcançam o destino anunciado. Conteúdo ilustrativo, promessas de módulos indisponíveis e progressos fictícios não são requisito de restauração.

## Resultado

Não identifiquei remoção de campo transacional, endpoint ou ação autorizada nas 24 unidades. Há perda concreta de encontrabilidade na Central: o atalho “Ver saúde” passa a abrir uma aba que mantém a saúde fechada. Outros conteúdos reais foram recolhidos, mas continuam acessíveis por um acionamento de `summary`. Duas recomendações de encontrabilidade estão registradas sem tratar a abertura de um painel como perda de dados.

“Preservado” nesta matriz significa paridade identificada no código e nas condições de renderização. Não substitui validação em navegador, nem prova que o ambiente de produção contém os dados esperados.

## Inventário das 24 unidades

| Unidade e fonte principal | Conteúdo real da versão antiga | Disponibilidade atual, ações e destinos | Conclusão |
| --- | --- | --- | --- |
| U01 Navegação, `shell/Sidebar.tsx`, `lib/navigation.ts`, `shell/Topbar.tsx` | Grupos de navegação, rotas por capacidade, contexto da igreja, usuário/perfil, sair, módulos bloqueados, títulos e breadcrumbs. | Mesma definição de rotas/permissões. Itens autorizados agora são links de hash com navegação normal e modificadores; perfil vai a `#perfil`. Módulos indisponíveis continuam bloqueados. Menu responsivo conserva os mesmos destinos. | Preservado. |
| U02 Login da igreja, `login/LoginScreen.tsx`, `auth/AuthLayout.tsx` | E-mail, senha, mostrar senha, erro de credencial/sessão/igreja/cobrança, carregamento, entrar, recuperação, termos e privacidade. | E-mail/senha e revelação permanecem. Falha conserva entrada e destino de retorno; sucesso usa o destino autorizado. Links legais estão no layout comum (`/termos`, `/privacidade`). Título “Entre na sua igreja”. | Preservado. Removida informação institucional sem função transacional. |
| U03 Recuperação, `login/LoginScreen.tsx` | E-mail, pedido de link, resposta neutra, retry e retorno ao login. | “Recuperar acesso” e depois “Confira seu e-mail”; CTA “Pedir novo link”. Confirmação neutra não revela existência da conta. Retorno `#login`. | Preservado. |
| U04 Redefinição, `login/LoginScreen.tsx` | Token do link, nova senha, confirmação, mínimo de senha, divergência, expiração, erro, envio e confirmação de sucesso. | Mesmos campos/validação. “Criar nova senha” e depois “Senha atualizada”. Link inválido permite pedir outro link em `#esqueci-senha`; retorno ao login permanece. Estado assíncrono isolado por rota/token. | Preservado. |
| U05 Convite, `login/LoginScreen.tsx` | Nome/igreja/e-mail validados do convite, telefone condicionado ao cadastro necessário, senha/confirmar, link inválido, erro e ativação. | Contexto validado continua visível; telefone/WhatsApp só quando `precisaCadastro`. Mesmas entradas e ativação; “Ativar acesso” e “Acesso ativado”. Retorno `#login`. | Preservado. |
| U06 Hoje, `dashboard/DashboardScreen.tsx`, `WorkQueueItem.tsx`, `NextActions.tsx` | Fila e quantidade de cuidados, pessoa/contexto, prazos, responsável, assumir/conectar/fonovisita/atribuir/mensagem, agenda/próxima reunião, panorama real por escopo, jornada Ganhar/Consolidar/Discipular/Enviar e carga por responsável. | Fila e próxima ação permanecem visíveis; “Abrir conversas” aponta a `#inbox`. Contagem de cuidados continua no hero e fila. Panorama mantém o disclosure já existente “Visão geral do seu cuidado”. Jornada, valores por etapa e links autorizados, além das pendências por responsável, passaram a “Jornada e responsáveis”. Atribuir/Mensagem e Assumir secundário estão em “Mais ações”. | Dados preservados; F3 recomenda tornar ações de cuidado mais explícitas. |
| U07 Lista de conversas, `inbox/ConversationList.tsx`, `InboxScreen.tsx` | Busca por pessoa/telefone/mensagem, filtros, seleção, lista, contexto de estado e responsável, atualização e estados vazios/erro. | Mesma busca/filtros/seleção e fonte; mudança de título e placeholder. Nenhum item real da lista removido. | Preservado. |
| U08 Conversa e contexto, `inbox/ConversationThread.tsx` | Histórico de mensagens/mídias, autoria/tempo/estado, assumir/transferir, pessoa/contexto, rascunho, texto/áudio/anexo, erro/bloqueio, exclusão autorizada. | Estado junto ao nome e responsável explicitado. Transferir e Ver pessoa agora têm texto. Histórico/compositor, condições de posse e callbacks mantidos. Exclusão de admin passou a “Mais ações”, com a confirmação existente. | Preservado; recolhimento da exclusão é coerente com ação destrutiva. |
| U09 Ganhar, `contacts/GanharScreen.tsx`, `LinkCellModal.tsx` | Novos contatos/visitantes, nome/tipo/situação/vínculo/presenças, detalhe, vincular célula, promoção por critério, quatro indicadores reais. | Mesmas linhas e critérios; “Avançar para Consolidar” explicita a promoção. Critério de três presenças ou decisão por Jesus e ações por capacidade permanecem. Quatro indicadores estão em “Resumo dos contatos carregados”; tabs conservam contagens após carga confirmada. | Preservado, indicadores recolhidos. Falha inicial não exibe falso vazio. |
| U10 Pessoas, `contacts/ContatosScreen.tsx` | Busca, filtros de tipo/estado, total global do filtro, paginação 50, linhas, seleção, nova pessoa, arquivadas/reativação. | Mesmos filtros em select; total e paginação preservados. Mobile alterna lista/detalhe, com retorno explícito que conserva filtro/página/scroll e restaura foco. Dados antigos permanecem no refresh da mesma página; troca de filtro não mostra página antiga como atual. | Preservado. |
| U11 Detalhe e formulários, `ContatosScreen.tsx`, `NewContactModal.tsx`, `EditContactModal.tsx`, `ArchiveContactModal.tsx` | Nome, telefone, tipo, acompanhamento, liderança/apto, célula, presenças, decisão por Jesus, e-mail, motivo Fora da igreja; criar/editar, vincular, arquivar e reativar. Campos de nome/telefone/e-mail/gênero/tipo e condições Fora da igreja. | Nome/telefone/tipo, acompanhamento/célula/etapa e ação principal visíveis. Liderança/apto, presenças, decisão, e-mail e motivo estão em “Dados e percurso”. Editar secundário e arquivar estão em “Mais ações”. Campos de criação/edição, erro, preflight de arquivo e confirmação permanecem; adicionado aviso de descarte do dirty. | Preservado; F2 recomenda nomear os dados recolhidos. |
| U12 Consolidar, `consolidacao/ConsolidarScreen.tsx` | Fila de acompanhamento, pessoa/célula/prazo, progresso, decisão, base consolidada por célula/gênero, contagens e lista dos primeiros cinco consolidados junto à UV indisponível. | Fila mantém os dados e acrescenta consolidador/próxima etapa real; Ver progresso abre a mesma trilha. Base e filtros preservados. Contagens ficam em “Resumo do acompanhamento”; lista UV em “Universidade da Vida: disponibilidade”. Todos os consolidados continuam na tabela principal. | Preservado. Removidos apenas rótulo de aptidão UV e contador duplicado do mesmo `consolidated.length`. |
| U13 Consolidação individual, `ConsolIndividualScreen.tsx`, `TrackModal.tsx`, `DecisionModal.tsx` | Pessoa, consolidador, total de etapas obrigatórias cumpridas, abertura da trilha, etapas/notas/gates reais e registro de decisão; sequência explicativa. | “Etapas registradas” conserva `done`/`total` e acrescenta próxima etapa. Botão “Abrir trilha” explicita o destino. Trilha real e campos da decisão permanecem. Sequência didática em “Como funciona a trilha”, sem simular etapas já concluídas. | Preservado. Progresso decorativo fictício removido. |
| U14 Células, `cells/CelulasScreen.tsx`, `CellFormModal.tsx`, `InviteMemberModal.tsx` | Lista/detalhe, nome/líder/agenda/situação, membros/visitantes/alertas, edição autorizada e vínculo; quatro indicadores. Dados da célula: nome, cobertura, líder no contexto permitido, dia/hora, ativa, bairro/publicidade conforme capacidade. | Lista/detalhe e ações preservados; busca adicionada, foco/voltar no mobile. Criação continua exclusivamente na Central. Indicadores de ativas/sem líder/pessoas/Cobertura G12 ficam em “Visão geral das células”. Formulários retêm campos e condições de autorização/publicação. | Preservado, indicadores recolhidos. Limite L1 de estado inicial registrado abaixo. |
| U15 Rede G12, `g12/G12Screen.tsx` | Descendências, breadcrumbs, pessoa/tipo, quantidade de liderados, abertura de ramo, indicadores somente leitura e estado sem descendência. | Mesmas abas/fonte/valores e navegação por árvore. Folha explicita “Sem liderados”; breadcrumb/foco e rótulos melhorados. | Preservado. |
| U16 Central, `central-celula/*` | Hoje com pendências reais, gestão/detalhe/líder/membros, transferir/remover, saúde histórica por reunião, multiplicações/pedidos e decisões, relatórios pendentes, avisos e materiais com seus formulários. | Cinco abas e RBAC pastor/admin permanecem. Transferir visível; Remover em “Mais ações”. Saúde e panorama de multiplicações em “Saúde e multiplicações”; solicitações mantêm decisões. Relatórios pendentes seguem visíveis. Avisos/materiais e campos não mudaram. | F1: “Ver saúde” não revela seu destino. Dados e ações restantes preservados. |
| U17 Minha Célula líder, `minha-celula/MinhaCelulaLider.tsx` e modais | Célula liderada real, nome/contexto/cobertura/agenda/membros; seis áreas (Relatório/Pessoas/Avisos/Materiais/Solicitações/Dados); reunião correta e pedidos de reunião/multiplicação/dados sensíveis. | Mesmas seis áreas e campos. Escolha de reunião ganhou label “Reunião do relatório” e instrução para conferir data. Fonte da célula liderada e chave/ID da reunião preservados; modais só receberam classes de apresentação. | Preservado. |
| U18 Minha Célula discípulo, `DiscipuloScreen.tsx`, feeds | Próxima reunião/data/tema, confirmar presença, indicar visitante, avisos, materiais e links, histórico de suas reuniões/presença. | Próxima reunião e avisos visíveis; mesmas ações. Materiais em “Materiais da célula” e histórico em “Meu histórico de reuniões”, ambos por um acionamento. Conteúdo dos feeds idêntico à base. | Preservado, materiais/histórico recolhidos. |
| U19 Relatório de reunião, `MeetingReportForm.tsx` e seções | ID/data/status real, Presença, Visitantes/expectativas, Registros, Fechamento, oferta/observações, resumo, salvamento e envio; bloqueio após enviado, presenças e deduplicação existentes. | `MeetingReportForm.tsx` e serviços idênticos à base. Quatro etapas mantidas com valores da reunião escolhida, sem adicionar formulário paralelo. Seções e controles de envio persistem. | Preservado; não reabre envio concluído nem inventa sucesso. |
| U20 Enviar, `enviar/EnviarScreen.tsx` | Panorama somente leitura de multiplicações pendentes/registradas, datas/estado/origem, instrução do fluxo de solicitação. | Mesmo conteúdo e caráter somente leitura; Atualizar reutiliza carga existente. Não havia botão de envio de mensagem nesta tela. | Preservado; não transformar panorama em envio. |
| U21 Agenda, `calendario/*` | Semana/Mês/Ano/A confirmar, períodos/dias, eventos/estado/origem Google ou manual, detalhe/categoria/data/hora/descrição, criar/editar/remover/confirmar, notificações condicionadas. | Mesmos períodos, modelos e campos. Modais só receberam classes. Confirmar mantém opt-in de notificação, quando/data/hora/públicos/contatos/mensagem e validações; nenhuma ação nova de disparo. | Preservado. |
| U22 Comunicação, `comunicados/ComunicadosScreen.tsx` | Título interno/mensagem; segmentos e contagens/destinatários estimados; agendamento/data/hora/repetição; revisão/alcance final/opt-out/consentimento; envio, bloqueio/resultados e histórico. | Mesmo fluxo compose/segment/review e campos. Passo atual marcado semanticamente; mensagem de revisão ganhou classe de contraste. Gates, estimativa versus resultado real, zero de alcance e histórico conservados. | Preservado. Preview não comprova envio. |
| U23 Relatórios, `reports/*` | Reuniões da semana atual/anterior, célula/líder/data, presentes/visitantes/decisões, recebido/pendente/atrasado, detalhe/oferta/observações; SLA do backend e atualização do modal. | Pendentes primeiro, recebidos depois; mesmas colunas e detalhe. Rótulo por reunião, contexto do botão Ver e período de São Paulo explícitos. Valores ausentes continuam ausentes, sem substituir por zeros fictícios. | Preservado. |
| U24 Meu perfil, `profile/PerfilScreen.tsx` | E-mail da conta somente leitura, nome, nome no WhatsApp, senha atual/nova/confirmar; salvar, validação, erro/sucesso e carregamento independentes. | Três formulários empilhados, mesmas entradas e handlers. Renomeados apenas os títulos de exibição e segurança. Não acrescentado ajuste de igreja/papel ou edição de conta alheia. | Preservado. |

## Achados de encontrabilidade

### F1, P2, U16: atalho “Ver saúde” abre um destino recolhido

Origem: `today-queue.ts:111` cria a pendência com nome da célula, estado, ação “Ver saúde” e `goTo: "cells"`. `DashboardPanel.tsx:270` chama apenas `onGoTo(item.goTo)`. A Central passa `setTab` em `CentralCelulaScreen.tsx:116` e monta `ManageCellsPanel` sem intenção adicional em `:121`. Destino: `ManageCellsPanel.tsx:476` contém `CellHealthList` sob `details` sem `open`, summary “Saúde e multiplicações”.

Na versão antiga, saúde estava renderizada diretamente na aba. Agora, clicar numa pendência de saúde muda de aba, mas exige descobrir e abrir um segundo controle para ver a informação anunciada. Não há seleção, foco ou abertura desse conteúdo pelo atalho. Correção mínima indicada: transmitir a intenção de saúde e revelar/focar a seção existente, sem criar nova informação ou mudar a estética. Aceite: com célula em atenção/crítica, acionar “Ver saúde” apresenta a lista de saúde e mantém outras rotas da Central independentes; navegar manualmente a Células pode manter o panorama recolhido. Parent autorizou correção após este registro.

### F2, P3, U11: rótulo genérico oculta informação relevante da pessoa

`ContatosScreen.tsx:1078` recolhe liderança/apto, presenças, decisão por Jesus, e-mail e motivo Fora da igreja em “Dados e percurso”. Campos não foram removidos, porém o rótulo não informa quais dados podem ser encontrados. Avaliação de encontrabilidade, sem falha funcional demonstrada. Recomendação para V3: nomear o resumo com conteúdo explícito ou mostrar um resumo curto de presença/decisão quando ajuda a próxima ação; manter dados adicionais disponíveis por teclado.

### F3, P3, U06: atribuição e mensagem estão sob “Mais ações”

`WorkQueueItem.tsx:153` recolhe Atribuir (`:166`) e Mensagem (`:177`) quando permitidos, junto a Assumir secundário. As condições de capacidade e handlers permanecem. A operação ainda existe, mas a pessoa precisa abrir um menu genérico para encontrá-la. Recomendação para V3: o rótulo do menu ou um atalho visível deve indicar as ações disponíveis, respeitando capacidade. Validar encontrabilidade com usuários antes de aumentar a quantidade de controles em cada linha.

## Conteúdo recolhido, com caminhos preservados

| Unidade | Controle atual | Conteúdo real ao abrir | Avaliação |
| --- | --- | --- | --- |
| U06 | Jornada e responsáveis | Contagens por Ganhar/Consolidar/Discipular/Enviar, links por capacidade, escopo, nome/papel/pendências por responsável. | Um acionamento; summary explicita o assunto. |
| U06 | Mais ações por pendência | Assumir secundário, Atribuir, Mensagem conforme capacidade. | F3; rótulo pode indicar ações. |
| U08 | Mais ações | Excluir conversa para admin, mesma confirmação. | Apropriado para ação destrutiva. |
| U09 | Resumo dos contatos carregados | Quatro indicadores com os mesmos cálculos e âmbito da lista carregada. | Um acionamento, sem agregado global inventado. |
| U11 | Dados e percurso | Liderança/apto, presenças, decisão, e-mail, motivo Fora da igreja. | F2; campos presentes, menor encontrabilidade. |
| U11 | Mais ações | Editar quando secundário, arquivar com preflight/confirmar. | Preservado. Primário depende do vínculo existente. |
| U12 | Resumo do acompanhamento | Pendentes, consolidação concluída, atrasos e os respectivos valores reais. | Um acionamento. Contador duplicado UV não restaurado. |
| U12 | Universidade da Vida: disponibilidade | Primeiros cinco consolidados com nome/célula; módulo e CTA de turma continuam indisponíveis. | Pessoas também estão na tabela completa. |
| U13 | Como funciona a trilha | Mesma sequência/descrição das etapas e instrução sobre conclusão. | Informativo; progresso fictício removido. |
| U14 | Visão geral das células | Ativas, sem líder, pessoas em células e Cobertura G12. | Um acionamento; L1 de falha inicial. |
| U16 | Saúde e multiplicações | Saúde por reuniões e panorama das multiplicações. | F1 para entrada pelo alerta. Aprovação segue em Solicitações. |
| U16 | Mais ações por membro | Remover com confirmação; Transferir continua visível. | Apropriado para ação destrutiva. |
| U18 | Materiais da célula | Título/tipo/links do feed autorizado. | Um acionamento, sem perda de links. |
| U18 | Meu histórico de reuniões | Datas/presença das reuniões da própria pessoa. | Um acionamento, mantendo privacidade. |

## Estados reais: lacunas mantidas, não perda de conteúdo causada pelo novo layout

L1: `CelulasScreen.tsx:329` ainda renderiza estatísticas quando `showSkeleton` é falso, sem exigir `loaded`. Na primeira carga que falha, arrays iniciais vazios podem aparecer como quatro zeros se o usuário abrir o panorama, junto ao alerta de erro. Esse comportamento dos cálculos existia na base; a lista principal atual já evita falso vazio. Para paridade com estado verdadeiro, exigir carga confirmada também no panorama.

L2: `DashboardPanel.tsx:200` usa contagem derivada de dashboard ausente e pode dizer “Nenhuma exceção aberta”; `:255` pode dizer “Fila da Central zerada” após erro inicial da fila. Arquivo idêntico à base, portanto achado herdado, não regressão visual. Erro de API não deve ser interpretado como zero operacional. Não modificar ou restaurar esses textos como parte da simples preservação do conteúdo antigo.

## Remoções que não exigem restauração

- Aside de login com promessas institucionais sobre toda jornada e texto técnico sobre provedor de autenticação. Marca/termos/privacidade, recuperação e contexto de entrada permanecem.
- Selo repetido do hero Hoje: a quantidade de cuidados permanece no hero e na fila. O novo acesso às conversas não remove a métrica.
- Estatística “Prontos para a próxima UV”: repetia `consolidated.length`, já mostrado como consolidação concluída, e não era resultado de uma avaliação real de aptidão.
- Selo “Apto” da lista de consolidados para UV: agora “Consolidado”, mantendo pessoa/célula; gestão de turmas continua indisponível.
- Progresso ilustrativo “done/now” da sequência informativa da consolidação individual: a contagem real de cada pessoa permanece.
- Estruturas ilustrativas, livros/certificações e percentuais não implementados das telas bloqueadas UV/CD (`LockedScreen.tsx`). Retorno ao Hoje e estado indisponível são explícitos; não criar módulo funcional a partir dessas ilustrações. Essas telas ficam além das 24 unidades operacionais, mas a remoção afeta os caminhos bloqueados da navegação U01.
- Avatares decorativos de linhas mobile e cabeçalhos de tabela: nomes/conteúdo das células permanecem com rótulos; não eram dado exclusivo.

## Evidência de contratos e integridade

Identidade de bytes verificada entre a base antiga e a árvore auditada, sem inferir comportamento de serviços externos:

| Arquivo | Bytes versus base | SHA256 atual |
| --- | --- | --- |
| `frontend/src/lib/admin-api.ts` | Idênticos | `1daea6f62d4123dc1ffbc0904992c1b54a3e615d3a93c9f1cceb77b7af238648` |
| `frontend/src/lib/agent-api.ts` | Idênticos | `c0338b117b546526d9c59c7cef72c909612d27e9978a8018d09d64cd9cee2f20` |
| `frontend/src/lib/api.ts` | Idênticos | `f684af486055f7aca2cdbe5699ac744436e1720301ebc0fe2810ca276f02128c` |
| `frontend/src/lib/branding-api.ts` | Idênticos | `9c5cd478d1be7c90a84c21a07ef10e1b825e938b27c94e3cf47341ceb20408f4` |
| `frontend/src/lib/broadcasts-api.ts` | Idênticos | `65032672887df2760c1b4cad1af9924b47282efd71117dfc4fa2736d41926b21` |
| `frontend/src/lib/calendar-api.ts` | Idênticos | `049b446ee188aa17fcc39650d8712b66a125809ceda0db4462cbdaf413443f42` |
| `frontend/src/lib/cell-central-api.ts` | Idênticos | `3775f8c933495436e0ee8415e673ae6cf8626b5a04f9a98abe9511f0f687f188` |
| `frontend/src/lib/cell-materials-api.ts` | Idênticos | `673f8a490f2be9ad797df816e81a605153957c75451ada20ee452afcecbd08e6` |
| `frontend/src/lib/cell-meetings-api.ts` | Idênticos | `c6c3db11cf416fda485c334d0afccff36e7aae9c58ab5f479f1bc2989e7586b2` |
| `frontend/src/lib/cell-notices-api.ts` | Idênticos | `70eabe760cb5d37cdc431467562f9b97411b4276d86843b58cd799cee80fc6ef` |
| `frontend/src/lib/cell-requests-api.ts` | Idênticos | `d305046c2c38d4b188ca5606be78f9b75b91fa9ef86519a21241289794bc9345` |
| `frontend/src/lib/cells-api.ts` | Idênticos | `9c481ba9c3b8a139aca6496d906b154265038364515b574dd940ddea42076ca9` |
| `frontend/src/lib/church-cadastro-api.ts` | Idênticos | `988585cf771edc44046ed0978b296e60947f4863bc091a22e696f3e366e1ef7b` |
| `frontend/src/lib/consolidacao-api.ts` | Idênticos | `353ead511e7b60ffab2864b02e482461e61e7767d0123f5e4a3fae309294e623` |
| `frontend/src/lib/contacts-api.ts` | Idênticos | `c01e87a887644ce6ded961b865c07ca939e660c6ac354a34be8b984d47644436` |
| `frontend/src/lib/conversations-api.ts` | Idênticos | `e7e953942d138d9d0296987fc71bcdadf6e140057a6e2f76fc724f08cfa3daf4` |
| `frontend/src/lib/dashboard-api.ts` | Idênticos | `33d56c79d443569cd38579427e8b31f28c19fd12c79e326116ae65ea80cea249` |
| `frontend/src/lib/events-api.ts` | Idênticos | `e29c85d04132b76a670ec453be341ca2fe254318a42bd6fbabe62d5caafd2b51` |
| `frontend/src/lib/g12-api.ts` | Idênticos | `2533af81dbd4f3abb1a893fcd8d4d28e50c93b12f56d3a6f495dd686e40b3c57` |
| `frontend/src/lib/multiplicacoes-api.ts` | Idênticos | `0554722a8f36a87b438bb42441c98475abe63dd6fd532766a480f18aa10eb403` |
| `frontend/src/lib/reports-api.ts` | Idênticos | `275c9609ad1769480b5ae46ba548630f1fd3b3eb15626dc28e1a242f59c1267a` |
| `frontend/src/lib/roles-api.ts` | Idênticos | `72d0a22453f5d38f8b9e55aa592897286ce27dc1bd6081afd4b0d394fb884035` |
| `frontend/src/lib/setup-api.ts` | Idênticos | `e11f7bf9622021b126817c5fa4913456f7f9a567d459796a0920c207a832b4ac` |
| `frontend/src/lib/subscription-api.ts` | Idênticos | `1d38954cd962c774ad47ad0ad3d8ea1686ae3e81558af3311c666f6a0e4a9b09` |
| `frontend/src/lib/team-api.ts` | Idênticos | `69aa87ff19caf46294ec742c4e3e6650983a9bfd877b0200693f083b7623423c` |
| `frontend/src/lib/whatsapp-api.ts` | Idênticos | `941f3d33de9c0358d66a9d0ead13a5e8110917c91aaea793fefecc7ec0f506be` |
| `frontend/src/lib/permissions.ts` | Idênticos | `1e69a6bba26c0771b21c281fe5fcd8275191b9fc4860f813fbd85269ab803599` |
| `frontend/src/lib/navigation.ts` | Idênticos | `24511276118fcbc3a331ccaa66a8e3d9a6d41534f70c4347e8a85d2106f34c15` |
| `frontend/src/components/shell/Topbar.tsx` | Idênticos | `abc276d68328605f02aefaa9fe05d067b62655e07f9f98ccb12b2d25575594b7` |
| `frontend/src/components/minha-celula/MeetingReportForm.tsx` | Idênticos | `efd72ec5398eafd86df96d4da651d2afe88f45e6bccd0ff34b6d404b659c35f3` |
| `frontend/src/components/central-celula/DashboardPanel.tsx` | Idênticos | `cd5ef0bfbac9ab1616c416ce63c1c2ec70fa62d658eda8e4d8bcce32d723d132` |
| `frontend/src/components/central-celula/today-queue.ts` | Idênticos | `dfd9f318f6a6dd28ee51f26030b988f0f12d86aef17e97db6e353f452f05fddb` |
| `frontend/src/components/central-celula/CellHealthList.tsx` | Idênticos | `af56164d20fc847595b06d930b6412e027afb0e3a1f083d7b274ad048ae43716` |
| `frontend/src/components/central-celula/RequestsPanel.tsx` | Idênticos | `0d5ad28c31e155903465fbabafeec6d2c87dd8590e585b32a0fa10bebc224b07` |
| `frontend/src/components/minha-celula/NextMeetingCard.tsx` | Idênticos | `8ce41f4ca2ec264685d9ed34012586d30227f5f894cd4fd48b460a72d6f6f911` |
| `frontend/src/components/minha-celula/MaterialsFeed.tsx` | Idênticos | `45717e52107c67aa1fd918faf354e4796058090f11c27e14b6ee9a5f89ca2e7e` |
| `frontend/src/components/minha-celula/MeetingHistoryList.tsx` | Idênticos | `6fb7d9ab941e1887c7cb508c2591710dd0c80bcf196d4414d4957357cfb8c9e4` |

Fontes de apresentação alteradas da fatia auditada, SHA256 da captura (não são um commit):

| Arquivo | SHA256 atual |
| --- | --- |
| `frontend/src/components/auth/AuthLayout.tsx` | `8ee915262738e7b64a1132d152bf5f4bf678e2640e221b825f7bc2a91b9217e7` |
| `frontend/src/components/auth/SessionUnavailable.tsx` | `ef15b1245ecdbca0b05da3418cf6370c43a969496d9e5d1030e6b6450141c666` |
| `frontend/src/components/login/LoginScreen.tsx` | `d5ffdd02bfc713b7a735651d13f7dde9ccaab4b9c3a193eb579abf41ae7cbedc` |
| `frontend/src/components/dashboard/DashboardScreen.tsx` | `8d3372ae516eeaae69c053546ec13d1703eba992fbbc6010e8bf3a2135cb978a` |
| `frontend/src/components/dashboard/WorkQueueItem.tsx` | `b2a0aaa79daf447c171da8baf62219d5f97f28d76bc4ea1b57c92bea19d5f0cc` |
| `frontend/src/components/inbox/ConversationList.tsx` | `d6e2ba5edcdda7ccf7c6d2edd80f8c486e302ae19e576bc3c3151503bb09eeb5` |
| `frontend/src/components/inbox/ConversationThread.tsx` | `f8001595341479f4c8916a514e7d6d64c1172ca4ee2ab9a31897a1dfddeff6dc` |
| `frontend/src/components/inbox/InboxScreen.tsx` | `7f1f45e631bef966fca4b4053f4c71d13dbc10bee3fcd51ece712ade78123167` |
| `frontend/src/components/contacts/ArchiveContactModal.tsx` | `20b8391db2c5e34c7da0a39ef7832b31f3ef7de0aed177e584a9d46609eaece3` |
| `frontend/src/components/contacts/ContatosScreen.tsx` | `ec5463daf43c54bdb02c7982bce11a182227f66dc68ace06e6f0777fc0f583c7` |
| `frontend/src/components/contacts/EditContactModal.tsx` | `c1fecd6aa0973a7e4aac08fc18e1e34b979e7b86c955d9fc38d54bbda7194257` |
| `frontend/src/components/contacts/GanharScreen.tsx` | `28985dc44ec530727c31d69702460c98849785e6bf08e0ac19159663dd01b1fb` |
| `frontend/src/components/contacts/LinkCellModal.tsx` | `5765c806a358095a8ca7c38e34dd0c5df23eb0690e0092b98450bab9fe3c70ff` |
| `frontend/src/components/contacts/NewContactModal.tsx` | `e468b3a91cd2312c032a4fe137f3afab02726b9e9624f88766be39a5237616c6` |
| `frontend/src/components/contacts/people-ux-v2.css` | `b829225d41e3e4518f1bbf2210647295705888b3fe8f3c29961faa4b6ed566db` |
| `frontend/src/components/consolidacao/ConsolIndividualScreen.tsx` | `6b993b69f323e4b9c2bb882a85f3ce0a3915c4e0be354b01a436e7f8b1cacc1e` |
| `frontend/src/components/consolidacao/ConsolidarScreen.tsx` | `6afb71f10d3a782e745deeaa57afe72d0f3724613cfe7c00b166c53327633867` |
| `frontend/src/components/consolidacao/DecisionModal.tsx` | `3649b550bd3d86bc73e275c14f01027f2635a15719c490e83693f907198e0a8a` |
| `frontend/src/components/consolidacao/LockedScreen.tsx` | `463947c79af37c6a7ea3ac4248c5b3f0a677529aad9e547e673bfbb44065b9b7` |
| `frontend/src/components/consolidacao/TrackModal.tsx` | `0230cdddf87b9ed1788e5e707734d3f9b28653d3ebc130950c5e8d68c69f8781` |
| `frontend/src/components/cells/CellFormModal.tsx` | `790763108757565aac46e7efdc13a868de6714d0cc2fc651c1f1042a20080952` |
| `frontend/src/components/cells/CelulasScreen.tsx` | `3770938ee8d0e3ee663f7f6b2a177ca559f6965fded2175adbe6c5d868a8e7b0` |
| `frontend/src/components/cells/InviteMemberModal.tsx` | `82cad61abf7e800fe300bdf1ca1fb8577b419c773844df5b351d8eecaba84727` |
| `frontend/src/components/cells/operations-ux-v2.css` | `f6bbc575539a84ba13cddb614cbe857e2b2fdd78694bbb313640920711ec0e29` |
| `frontend/src/components/g12/G12Screen.tsx` | `783d83a0cb7f7393af2caea1ee66d79a29515f6d01735eba86729afa56344fa6` |
| `frontend/src/components/central-celula/CentralCelulaScreen.tsx` | `8169873456af6bc6b448b90084e6775115d0e4d02ccc336420f0407903323318` |
| `frontend/src/components/central-celula/ManageCellsPanel.tsx` | `a229e9932f4d81ed47886043fb7e82d05f6c1edefacc8dd386ed751c4c04af37` |
| `frontend/src/components/central-celula/TransferRemoveMemberModal.tsx` | `c1c710eee4bb799df05799cb96b2b97f5869e1d03b7784931ce4eb9c2748808b` |
| `frontend/src/components/minha-celula/DiscipuloScreen.tsx` | `9a00f2254ba6f9df8b6e26682228004472ff697d64cf535042837f7ea105712b` |
| `frontend/src/components/minha-celula/IndicateVisitorModal.tsx` | `6dfe8388957e360b8afd2ca5ab88acdefc866bf92b23d30d230bcf81643bd37b` |
| `frontend/src/components/minha-celula/MinhaCelulaLider.tsx` | `d7c1c5ec898096381c1e8b3dc158285cf52cc3eb8e863aadea7d063d4e1f8547` |
| `frontend/src/components/minha-celula/MultiplicationRequestModal.tsx` | `e491b5b707d0bdc7550df0b117747f0895bd91533cefd0fce3632fa5b9bae205` |
| `frontend/src/components/minha-celula/PlanMeetingModal.tsx` | `450e047a9ecce02d3610773c19d33abe668ea6463b760d017a0e3c033e91d39f` |
| `frontend/src/components/minha-celula/SensitiveFieldRequestModal.tsx` | `2d66f5ddd8e64b022e463324b35c7980a7f7457f55db43875e274d19a6fb7724` |
| `frontend/src/components/enviar/EnviarScreen.tsx` | `c17fbe352d3571cdf2713740ea1962ff3b4ac647210f034b45d5d88618395be5` |
| `frontend/src/components/calendario/CalendarioScreen.tsx` | `4d0cdc332533795feb5019b22ebf68ee781a500dbd57e1bbe8150535c58bba57` |
| `frontend/src/components/calendario/ConfirmEventModal.tsx` | `e16257000240f18ee5cb6f16d6b9c028c67106db76f66d7568569fe873cc8656` |
| `frontend/src/components/calendario/EventDetailModal.tsx` | `782ed3958228450441f3f6a6104a8369559ec8738f8e332a83e8962382be5b9c` |
| `frontend/src/components/calendario/EventFormModal.tsx` | `9ce3e9e21096bb3e1831db6c8a34bc12980958c9853fb7dd8a3e5b6fdad2a9b7` |
| `frontend/src/components/comunicados/ComunicadosScreen.tsx` | `0cf2e952e01d38aeec8164b3dba3eebfb7ca3aaa06ac19769cf66029d3fc7c63` |
| `frontend/src/components/reports/RelatoriosScreen.tsx` | `50951e0b0abd61108654ec6744c53682f037500414fbf05ab5e289c2b467fbe8` |
| `frontend/src/components/reports/ReportDetailModal.tsx` | `842fda2d5c6c5e9bfd4efd0957916865de38b960bcd42b05c5bf549d8839662c` |
| `frontend/src/components/profile/PerfilScreen.tsx` | `8adfac072dcd71ff8e444c31a9fc7e0fb739259f0fe985927216e3006b36763a` |
| `frontend/src/components/shell/Sidebar.tsx` | `df968ed7790589b512cab77fac1f45d82437dc13054d742d4a2fdd2c98d063a2` |
| `frontend/src/components/ui/DataTable.tsx` | `becb4e2cd34b2a8e708c396d6d5075bfe46ade675973bb6976aba34e167aa58a` |

## Limites e aceite da próxima etapa

Não houve build, execução de browser, leitura de PII/segredos, consulta de backend nem validação de produção nesta auditoria. Typecheck e ESLint da correção anterior de estados de Pessoas passaram segundo execução local concluída nesta sessão; não são prova de paridade das 24 unidades. Colapsar conteúdo não muda os bytes dos contratos, mas pode mudar a facilidade de localizar informação. Contraste, animações, mouse, scroll e layout renderizado dependem da etapa V3 e de QA em mobile/desktop.

Para concluir a preservação do conteúdo na próxima versão: corrigir F1, manter todos os campos/ações desta matriz em seus contextos de capacidade, dar pistas explícitas dos dados recolhidos, exercitar retorno/dirty/seleção/reunião correta/erros com fixtures sintéticas, e verificar que nenhuma animação esconde dados nem bloqueia teclado/reduced motion. Não restaurar os placeholders listados acima como se fossem execução real.

## Adendo: F1 corrigido e fixtures corrigidas

Registro UTC: 2026-10-01T22:13:39.942786+00:00. Após autorização do parent, o atalho de saúde passou a enviar uma intenção de abertura à aba Células. A seção existente abre e seu summary recebe foco; navegação manual e por relatório mantêm o panorama recolhido. Usuário pode fechar normalmente e voltar ao atalho. Mudança restrita a três TSX, sem CSS, dados novos, API ou RBAC.

Negativo dirigido: teste real da Central com DashboardPanel, ManageCellsPanel e CellHealthList reproduziu a falha antes (1 FAIL, 2 PASS). Depois da correção: **19/19 PASS**, cinco arquivos dirigidos da Central, incluindo o novo teste de navegação. Typecheck, ESLint dos cinco arquivos alterados e git diff --check: **PASS**. Não executei build nem E2E.

E2E ux-operations: traces locais mostraram /contacts com 501 e matriz do harness sem permissão Minha Célula para líder/membro; esses estados impediam os conteúdos buscados. Correção exclusivamente das fixtures: páginas tipadas de contatos/equipe, matriz específica com acessos coerentes e notices do membro no contrato array. Seletores Abrir célula, meeting-tema e Reunião do relatório eram compatíveis com o produto e foram preservados. O caso adversarial de resposta atrasada A para B foi mantido. Rerun E2E integrado permanece a cargo do parent.

| Arquivo após correção | SHA256 |
| --- | --- |
| `frontend/src/components/central-celula/CentralCelulaScreen.tsx` | `c0c160dc8b44d576c44512b2a1804fdce6c142b11c653b379c7af0da8bc63fe4` |
| `frontend/src/components/central-celula/DashboardPanel.tsx` | `02ddcb22e81acc509e90f567a3b8fcd135999d0b8d414ab1102507408dd4f2fe` |
| `frontend/src/components/central-celula/ManageCellsPanel.tsx` | `db1fcd00157bedb7b82f9d0b4f59f54e267794cc2ab9b29e95bf6c947319f981` |
| `frontend/src/components/central-celula/CentralCelulaScreen.health-navigation.test.tsx` | `48a42449304c0345771d392e85b439bd1042ebdc2038b2c010e539c0be384034` |
| `frontend/e2e/ux-operations.spec.ts` | `48786c18b94bec381da9e24ce782fa08758887c94f707f0d85baafdd9ef055da` |
