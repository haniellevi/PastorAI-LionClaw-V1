# PRD — Central de Células (Igreja 12)

> **Status:** Rascunho para revisão. Fecha a série de PRDs do módulo Células. Deriva do contrato de UX/UI e dos PRDs Discípulo/Líder/Solicitações, todos já em `main`.
> **Data:** 2026-07-03.
> **Natureza:** docs-only. Nenhum código, migration, env ou deploy nesta entrega.
> **Escopo deste PRD:** a **tela Central de Células** — supervisão da rede de células. Detalha a **seção 8 do contrato**.

## Fontes de verdade

1. **Contrato UX/UI** — [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) (vinculante; seção 8 = Central).
2. **PRD Solicitações & Aprovação** — [`docs/design/PRD-CELULAS-SOLICITACOES-APROVACAO.md`](PRD-CELULAS-SOLICITACOES-APROVACAO.md) (o lado "decisão" da Central).
3. **PRD Líder** — [`docs/design/PRD-MINHA-CELULA-LIDER.md`](PRD-MINHA-CELULA-LIDER.md) (origem das solicitações e dos relatórios).
4. **PRD Discípulo** — [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md).
5. **Protótipo refinado aprovado** — `Igreja12 Prototipo (standalone) refinado.html` (base visual da Central).
6. **Regras decididas** (abaixo), que prevalecem em qualquer ambiguidade.

### Regras decididas (travadas)

- A **Central de Células NÃO fica no menu Minha Célula**; fica em **Jornada G12 → Discipular → Central de Célula**.
- O menu **Minha Célula** tem apenas **visão Discípulo** e **visão Líder**.
- A Central **acompanha** células, líderes, relatórios, saúde, solicitações, avisos e materiais.
- A Central pode **cadastrar célula** (definindo cobertura/liderança, líder, membros, dia/hora, endereço e anfitrião).
- A Central **aprova/rejeita/pede ajuste** em solicitações; **rejeição exige motivo**; **pedir ajuste exige observação**; **aprovação aplica a mudança real**.
- **Aprovação de multiplicação** cria a nova célula, move membros, atualiza dados/organograma e entrega a gestão ao **novo líder**.
- A Central pode **enviar materiais** aos líderes.
- A Central acompanha **relatórios recebidos, pendentes e frequência média**.
- A Central pode **ordenar/filtrar células por saúde**.
- A **Árvore Ministerial** é **separada** da célula comum.

---

## 1. Objetivo da Central de Células

Dar à liderança da rede uma **torre de controle** das células da igreja: enxergar a **saúde** de todas, **cobrar** relatórios, **decidir** solicitações sensíveis, **cadastrar/editar** células, e **abastecer** os líderes com avisos e materiais — mantendo consistência e governança sem entrar na gestão do dia a dia de cada célula (isso é da visão Líder).

Metas:
- **Visibilidade**: saúde e pendências da rede num relance.
- **Governança**: toda mudança sensível decidida aqui, com auditoria (via PRD Solicitações).
- **Suporte ao líder**: materiais e avisos que chegam à célula.

Não-objetivo: substituir a **visão Líder** (a Central não opera o dia a dia da célula do líder), nem ser a **Árvore Ministerial** (organograma é módulo à parte).

## 2. Persona / papéis que acessam

| Papel | Acesso |
|---|---|
| **Líder da Central** | Papel de supervisão da rede: dashboard, gerenciar células, decidir solicitações, avisos, materiais, relatórios. Papel formal a definir (perguntas abertas). |
| **Pastor / Admin (fallback)** | Onde não houver "líder da Central" designado, exerce o papel. **Fallback**, não segundo nível de aprovação. |
| **Líder comum de célula** | **NÃO acessa a Central.** Ele origina solicitações e envia relatórios pela **visão Líder**; a decisão acontece aqui, fora do alcance dele. |

Segregação: quem **origina** (líder comum) não **decide** (Central) — herdado do PRD Solicitações.

## 3. Navegação

- Caminho: **A Jornada G12 → Discipular → aba "Central de Célula"**. Ao entrar, o conteúdo abre com **abas internas próprias**: **Dashboard · Gerenciar células · Solicitações · Avisos · Materiais** (o contrato prevê também "Líderes"; ver limitação/perguntas).
- No protótipo, ao estar nessas telas, "Discipular" fica expandido e "Central de Célula" destacado como ativo.
- **Invariante explícito:** a Central **não aparece** dentro de **Minha Célula**. Minha Célula = só Discípulo + Líder. A Central é destino de navegação **separado**, só para líder da Central / admin.

## 4. Estados da tela

| # | Estado | Comportamento |
|---|--------|---------------|
| 4.1 | **Nenhuma célula cadastrada** | Rede vazia (igreja nova). Empty state: "**Nenhuma célula cadastrada ainda.**" + CTA "Nova célula". Dashboard zerado. |
| 4.2 | **Células ativas** | Estado base: dashboard com indicadores + "Saúde das células". |
| 4.3 | **Relatórios pendentes** | Há células sem relatório da última semana. Indicador "Relatórios pendentes" em `warn`; linhas marcadas na saúde (bolinha vermelha da semana). Ação "Cobrar" por líder. |
| 4.4 | **Solicitações pendentes** | Há solicitações aguardando decisão. Badge com nº na aba Solicitações; fila populada. |
| 4.5 | **Solicitações vazias** | Fila sem itens. Empty state: "Nenhuma solicitação pendente." |
| 4.6 | **Materiais vazios** | Sem materiais. Empty state: "**Nenhum material ainda.**" + CTA "Novo material". |
| 4.7 | **Avisos vazios** | Sem avisos. Empty state: "Nenhum aviso enviado." |
| 4.8 | **Erro / carregando** | Skeleton nos cards/listas ao carregar; estado de erro com retry ("Não foi possível carregar. Tentar de novo."). |

## 5. Dashboard / indicadores

- **Stat-cards** (contrato 8.1): **Total de células (ativas)** · **Relatórios recebidos na semana** · **Relatórios pendentes** (`warn`/`danger`) · **Frequência média** · **Visitantes no mês** · **Participantes no mês** · **% de membros em célula**.
- **Saúde das células** — uma linha por célula, com **posição/número como primeira informação**, avatar, nome, líder · dia, e **10 bolinhas** (últimas 10 reuniões: verde = relatório enviado / vermelho = não). Clicar → detalhe da célula.
- **Líderes com atraso** — recorte/lista dos líderes com relatório pendente (deriva de "Relatórios pendentes"); ação "Cobrar".
- **Ordenação por saúde** — abas Ordem padrão · Menos saudáveis · Mais saudáveis (contrato 8.1 / seção 12).

## 6. Gerenciamento de células

Aba **Gerenciar células**:

- Busca (célula ou líder) + filtros (Descendência · Cobertura · Status).
- **Cadastrar célula** ("Nova célula") → modal com: **cobertura espiritual*** (obrigatória), **líder** (só pessoas **aptas** = Reencontro), **nome**, **membros** (opcional na criação), **dia/hora***, **endereço**, **anfitrião**.
- **Editar célula** → atualiza **cobertura/liderança · líder · auxiliar · membros · dia/hora · endereço · anfitrião**. Bloco **"Transferir liderança (cobertura)"**: ao trocar a cobertura, a célula passa a ficar **abaixo** da nova liderança (e o líder aparece sob o novo líder no organograma — Árvore separada).
- **Ativar / inativar célula** (se previsto): pill Ativa/Inativa; inativar não apaga histórico. (Confirmar no design — ver perguntas.)

> **Nota — quem edita o quê:** a Central edita **direto** os dados da célula aqui (é a autoridade). O **líder comum** só muda dados sensíveis **via solicitação** (PRD Solicitações). A discrepância 14.1 (anfitrião/auxiliar/endereço serem sensíveis para o líder) **não** limita a Central: a Central sempre pode editar direto.

## 7. Solicitações

Aba **Solicitações** — o lado "decisão" do fluxo (detalhes no [PRD Solicitações & Aprovação](PRD-CELULAS-SOLICITACOES-APROVACAO.md)):

- **Fila** de solicitações: tipo, célula, líder, resumo "de → para", data; badge com nº pendentes.
- **Aprovar** → **confirmação de segurança** listando **todas as mudanças** que serão aplicadas → "Confirmar e aprovar". A aprovação **aplica a mudança real** (transacional).
- **Rejeitar** → modal exige **motivo** (obrigatório; o líder recebe).
- **Pedir ajuste** → modal exige **observação** (obrigatória; devolve ao líder).
- **Histórico de decisão** — aba/registro com o desfecho (aprovada/rejeitada/ajuste) e a auditoria (quem, quando, texto).
- **Vínculo:** estados, validações e transações seguem o PRD Solicitações; esta tela é a **UI da decisão**.

## 8. Multiplicação

A multiplicação chega como **solicitação vinda do líder** e é decidida aqui:

- Exibe: célula de origem, líder atual, **novo líder** (com selo Apto), **membros que irão** (lista + contagem), **dia/hora**, **endereço**, **anfitrião**, data prevista.
- **Novo líder deve ser apto** (Reencontro) — revalidado na aprovação.
- **Aprovar** (transacional): **cria a nova célula** → **move os membros** selecionados → **atualiza dados/organograma** (Árvore Ministerial) → **entrega a gestão ao novo líder**. Falha parcial = rollback (nada aplicado).
- **Rejeitar** com motivo. Texto de apoio: "Ao aprovar, a nova célula é criada, os membros são transferidos e a Árvore Ministerial é atualizada."

## 9. Relatórios da célula

- **Ver relatórios recebidos** — por célula/semana; conteúdo do relatório (do PRD Líder): **presença/faltas**, **visitantes**, **observações**, **pedidos de oração**, **decisões**, **planejamento**, data da reunião.
- **Ver pendentes** — células sem relatório da última reunião (alimenta o indicador e a saúde).
- **Cobrar líderes** — ação "Cobrar" que aciona o líder (via agente; envio fora do escopo).
- **Frequência média** — indicador agregado (presença/planejadas) da rede e por célula.
- A Central **lê** os relatórios; **não** os edita (o relatório é do líder). Correções/reabertura seguem regra a definir (perguntas do PRD Líder).

## 10. Materiais para líderes

Aba **Materiais**:

- **Criar rascunho** · **publicar** · **editar**. Status **Rascunho** (só a Central) / **Publicado** (visível aos líderes).
- **Tipo**: Sermão · Quebra-gelo · Música. **Tema/tags** para busca; **sugestão de tema por IA**.
- **Conteúdo**: texto; **upload** (.docx/.pdf/.txt); **link somente para música** (YouTube/Spotify, com preenchimento automático simulado de nome/artista).
- **Enviar material aos líderes** = publicar (aparece no "Material da Central" do líder ao planejar — PRD Líder 7.5). Se "enviar" dispara notificação ativa (WhatsApp) ou só fica disponível no sistema fica **em aberto** (perguntas).
- **Histórico/estado**: lista com pill Publicado/Rascunho; editar mantém histórico.

## 11. Avisos da Central

Aba **Avisos**:

- **Criar aviso** → modal: **título**, **mensagem**, **público-alvo** (chips: Todas as células · Líderes · Célula específica · Descendência/cobertura), **prioridade/quando** (Enviar agora · Agendar).
- **Histórico** — lista com pill Enviado/Agendado/Rascunho.
- **Diferença de origem/cor** (invariante do contrato, seção 4): **avisos da igreja/Central = vermelho**; **avisos da célula = azul**. Avisos da Central chegam **em vermelho** no mural do líder/discípulo.
- Nota: avisos gerais da igreja (homens, mulheres, jovens…) ficam em **Comunicação**, não aqui.

## 12. Saúde das células

- **Critérios de saúde** (base = últimas ~10 reuniões): **relatório enviado** (verde) vs **não enviado/não realizada** (vermelho). Sinais que compõem a saúde: **atraso de relatório**, **queda de frequência**, e — se aplicável — **falta de visitantes** (indicador de estagnação evangelística).
- **Ordenação**: **Ordem padrão · Menos saudáveis · Mais saudáveis** (as duas últimas destacam o topo).
- **Pendências** visíveis: bolinha vermelha na semana sem relatório; contagem de pendentes no dashboard.
- **Critérios oficiais** (pesos, janela, o que conta como "saudável") ficam **em aberto** (perguntas) — este PRD fixa a **anatomia visual** (10 bolinhas + ordenação), não a fórmula final.

## 13. Regras de permissão

1. **Tenant** — a Central só atua **dentro da própria igreja** (`igreja_id`, RLS); nunca vê/decide célula de outra igreja.
2. **Líder comum não acessa a Central** — nem a fila de solicitações, nem o cadastro de células.
3. **Central não substitui Minha Célula do líder** — são superfícies distintas; a Central supervisiona, o líder opera.
4. **Auditoria** — mudanças administrativas (cadastro/edição de célula, decisões de solicitação, multiplicação) **registram auditoria** (quem, quando, de→para) — herdado do PRD Solicitações.
5. **Segregação** — quem originou uma solicitação não a aprova.

## 14. Fora de escopo

- **Implementação backend** / contratos de API / máquina de estados em código.
- **Migrations** / modelo de dados implementado.
- **Envio de WhatsApp real** (agente; aqui só a intenção de avisar/cobrar).
- **Organograma / Árvore Ministerial visual completo** (módulo separado; a multiplicação só sinaliza a atualização).
- **PRD Discípulo** e **PRD Líder** (documentos próprios já em `main`).
- **PRD detalhado de relatórios**, se virar documento separado (aqui só o consumo pela Central).
- Dados leves da célula editados pelo líder (aplicam direto na visão Líder).

## 15. Dados necessários no futuro

Modelo que a implementação precisará (nomes ilustrativos; fora desta entrega):

1. **Célula** — nome, cobertura, líder, auxiliar, anfitrião, dia, horário, endereço, status (ativa/inativa), vínculos de membros.
2. **Reunião / ocorrência** e **Relatório por ocorrência** — presença, visitantes, decisões, observações, oração (do PRD Líder) — fonte da saúde e da frequência.
3. **Solicitação + auditoria + payloads tipados** — do PRD Solicitações (fila e decisões da Central).
4. **Indicadores agregados** — total ativas, relatórios recebidos/pendentes na semana, frequência média, % em célula, visitantes/participantes no mês.
5. **Saúde por célula** — série das últimas N reuniões (enviado/não) + sinais (frequência, visitantes).
6. **Material** — tipo, título, tema/tags, conteúdo/arquivo/link, status (rascunho/publicado).
7. **Aviso** — título, mensagem, público-alvo, quando/prioridade, status.
8. **Permissões** — papel "líder da Central" por igreja + fallback pastor/admin.
9. **Cobertura / descendência** — a estrutura pastoral que dá o filtro por cobertura (ligação com a Árvore Ministerial, sem misturar conceitos).

## 16. Critérios de aceite

1. **CA-1 (localização)** — a Central é acessível só por Jornada G12 → Discipular → Central de Célula; **não** aparece em Minha Célula.
2. **CA-2 (abas)** — expõe Dashboard · Gerenciar células · Solicitações · Avisos · Materiais (Líderes em aberto).
3. **CA-3 (dashboard)** — mostra células ativas, relatórios recebidos/pendentes na semana, frequência média e a lista "Saúde das células" (posição + 10 bolinhas).
4. **CA-4 (cadastrar)** — "Nova célula" coleta cobertura* (obrigatória), líder (apto), nome, dia/hora, endereço, anfitrião (e membros opcional).
5. **CA-5 (editar)** — edita cobertura/liderança, líder, auxiliar, membros, dia/hora, endereço, anfitrião; transferir liderança deixa claro que a célula fica abaixo da nova cobertura.
6. **CA-6 (solicitações)** — fila permite aprovar (com **confirmação** listando o que muda), rejeitar (**motivo** obrigatório), pedir ajuste (**observação** obrigatória); há histórico de decisão.
7. **CA-7 (aprovação aplica)** — aprovar aplica a mudança real (transacional) e grava auditoria.
8. **CA-8 (multiplicação)** — aprovar multiplicação cria a nova célula, move os membros, atualiza organograma/dados e entrega a gestão ao novo líder apto; falha parcial faz rollback.
9. **CA-9 (relatórios)** — vê recebidos e pendentes; permite "Cobrar" líder em atraso; expõe presença/faltas, visitantes, observações, oração, decisões, planejamento e frequência média.
10. **CA-10 (materiais)** — criar rascunho, publicar, editar; publicar disponibiliza ao líder; link só para música.
11. **CA-11 (avisos)** — criar com público-alvo e agendamento; avisos da Central em **vermelho**; histórico com estado.
12. **CA-12 (saúde/ordenação)** — ordenar por Menos/Mais saudáveis; pendências e atraso visíveis.
13. **CA-13 (permissão/tenant)** — Central só atua na própria igreja; líder comum não acessa; mudanças administrativas auditadas.
14. **CA-14 (estados)** — cobre nenhuma célula, células ativas, relatórios/solicitações pendentes, vazios (solicitações/materiais/avisos) e erro/carregando.

## 17. Perguntas abertas

1. **Papel definitivo da Central** — existe papel formal "líder da Central" por igreja? Como se atribui e quantos por igreja?
2. **Fallback pastor/admin sempre?** — pastor/admin sempre pode agir como Central, mesmo com líder da Central designado, ou vira co-decisor?
3. **Critérios oficiais de saúde** — janela (10 reuniões?), pesos (relatório vs frequência vs visitantes), limiar de "saudável".
4. **Central edita payload antes de aprovar?** — pode corrigir o valor proposto e aprovar já ajustado, ou só aprovar/rejeitar/pedir-ajuste? (herdada do PRD Solicitações).
5. **Materiais disparam WhatsApp ou só ficam no sistema?** — "enviar material" = notificação ativa aos líderes ou só publicação disponível?
6. **Avisos da Central exigem confirmação de leitura?** — precisa de "lido/visto" rastreável, ou basta chegar ao mural?
7. **Célula comum ↔ Árvore Ministerial** — como a cobertura/descendência conecta com o organograma **sem misturar** os conceitos (célula = reunião; árvore = quem lidera quem)?
8. **Anfitrião/auxiliar/endereço — sensível vs direto** — decisão herdada (PRD Líder 14.1 / Solicitações 16.2) **ainda pendente**; afeta o que o líder pode mudar direto, **não** a Central (que edita direto sempre).
9. **Ativar/inativar célula** — está previsto no produto? O que acontece com membros e histórico ao inativar?
10. **Aba "Líderes"** — o contrato previa; o protótipo não a tem. Entra como aba própria (gestão de líderes/aptos) ou fica coberta por Gerenciar células?

---

### Referências

- [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — contrato vinculante (seção 8 = Central).
- [`docs/design/PRD-CELULAS-SOLICITACOES-APROVACAO.md`](PRD-CELULAS-SOLICITACOES-APROVACAO.md) — fluxo de decisão.
- [`docs/design/PRD-MINHA-CELULA-LIDER.md`](PRD-MINHA-CELULA-LIDER.md) — origem de solicitações e relatórios.
- [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md) — a visão do membro.
- Protótipo aprovado: `Igreja12 Prototipo (standalone) refinado.html`.
