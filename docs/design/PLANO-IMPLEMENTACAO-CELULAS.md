# Plano de Implementação — Módulo Células (Igreja 12)

> **Status:** Rascunho para revisão. Consolida a série de PRDs já em `main` numa sequência implementável de PRs. **Não escreve código.**
> **Data:** 2026-07-03.
> **Natureza:** docs-only. Nenhum código, migration, env, worker, Supabase ou deploy nesta entrega.

## Fontes de verdade (todas já em `main`)

1. [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — contrato UX/UI (invariantes).
2. [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md).
3. [`docs/design/PRD-MINHA-CELULA-LIDER.md`](PRD-MINHA-CELULA-LIDER.md).
4. [`docs/design/PRD-CELULAS-SOLICITACOES-APROVACAO.md`](PRD-CELULAS-SOLICITACOES-APROVACAO.md).
5. [`docs/design/PRD-CENTRAL-DE-CELULAS.md`](PRD-CENTRAL-DE-CELULAS.md).

Contexto de stack (de `CLAUDE.md`, sem inventar): FastAPI + SQLAlchemy + PostgreSQL (Supabase), **RLS por tenant `igreja_id`** com `set_tenant_context` (`app/db/rls.py`, faz `SET LOCAL ROLE authenticated` — não remover). Migrations SQL em `backend/migrations/`, **novas por timestamp** `AAAAMMDD_HHMMSS_slug.sql` (`scripts/new_migration.py`), aplicadas **manualmente** no Supabase em ordem de nome. Frontend Next.js 14 (App Router) em `frontend/`, Clerk, mobile-first. Módulo `multiplicacoes` já existe como **stub** (evoluir, não recriar). Testes: `pytest` em `backend/`. DEV e PROD são projetos Supabase **separados**.

---

## 1. Objetivo do plano

Transformar a série de contrato + 4 PRDs em uma **fila de PRs pequena, ordenada e verificável**, deixando explícito (a) o que **bloqueia** o início do código, (b) o **modelo de domínio** alvo, (c) a **sequência** de entrega, (d) os **riscos** e o **rollout**. O plano é o "mapa"; cada PR futuro é uma entrega isolada com testes e gates.

Princípio: **backend antes de frontend** por camada; **schema antes de fluxo**; **nada de WhatsApp real** até o fluxo estar validado; **cada PR mergeável sozinho** sem quebrar produção.

## 2. Estado atual

- **Documentos mergeados** (docs-only): contrato UX/UI + PRD Discípulo + PRD Líder + PRD Solicitações & Aprovação + PRD Central. Cinco arquivos em `docs/design/`.
- **Zero implementação nova** do módulo Células a partir desses PRDs. O que existe hoje é o **stub** de `multiplicacoes` e telas parciais herdadas do MVP; presença por reunião, relatório com escrita real, entidade Solicitação e campos de célula **não existem**.
- **Onde estamos**: o módulo precisa **sair de contrato/PRD para implementação**. Este plano é a ponte. **Ainda não** é hora de código — há decisões que mudam o schema (seção 3).

## 3. Decisões abertas que bloqueiam a implementação

Seis decisões que **mudam o modelo** ou a **fronteira de permissão**. Detalhadas na seção 4.

1. **Papel definitivo da Central** (quem decide solicitações por igreja).
2. **Sensível vs. edição direta** para **anfitrião / auxiliar / endereço** (discrepância 14.1: protótipo salva direto, contrato classifica sensível).
3. **Critérios oficiais de saúde** (janela, pesos, limiar).
4. **Relação célula comum ↔ Árvore Ministerial** (cobertura/descendência sem misturar conceitos).
5. **Entidade ocorrência/reunião da célula** (hoje inexistente; destrava presença/expectativa/relatório/saúde).
6. **Entidade Solicitação + auditoria + payloads tipados** (núcleo do fluxo de aprovação).

> #5 e #6 são **estruturais** (não dá para adiar — são o alicerce). #1 e #2 são de **fronteira/regra** e têm default provisório seguro. #3 e #4 podem começar com heurística/stub e evoluir.

## 4. Decisões abertas — análise

### 4.1 Papel definitivo da Central
- **Contexto:** os PRDs falam de "líder da Central" com pastor/admin como fallback. Hoje não há esse papel formal por igreja.
- **Impacto técnico:** define a **autorização** de aprovar/rejeitar/cadastrar célula. Precisa de uma checagem de permissão (papel por `igreja_id`) e do princípio de **segregação** (quem origina não aprova).
- **Recomendação pragmática:** começar com **pastor/admin = Central** (papel já existente) e deixar um ponto de extensão para um papel dedicado `lider_central` depois. Não bloquear o schema.
- **Decisão do dono:** existe papel dedicado agora ou fica só pastor/admin no MVP do módulo?
- **Risco se não decidir:** autorização frouxa (qualquer admin aprova) ou retrabalho de permissão. Baixo se adotarmos o default e isolarmos a checagem numa função única.

### 4.2 Sensível vs. edição direta (anfitrião / auxiliar / endereço)
- **Contexto:** discrepância 14.1 — protótipo (Editar célula do líder) salva esses campos direto; contrato + PRDs Líder/Solicitações os classificam como **sensíveis** (viram solicitação).
- **Impacto técnico:** define **quais tipos de solicitação existem** e o que o endpoint de edição do líder aceita direto. Muda a lista de `tipo` da entidade Solicitação e a UI do líder.
- **Recomendação pragmática:** **seguir o contrato** (sensível → solicitação), como já fixado no PRD Solicitações (regra provisória). É o mais conservador (governança). Se o dono quiser reduzir, é só **remover tipos** — mais fácil que adicionar depois.
- **Decisão do dono:** confirmar sensível, ou liberar algum desses como edição direta do líder?
- **Risco se não decidir:** implementar edição direta e depois ter que "trancar" (migrar dados + reescrever UI + criar solicitação retroativa). Implementar como sensível e liberar depois é trivial.

### 4.3 Critérios oficiais de saúde
- **Contexto:** a UI fixa a **anatomia** (10 bolinhas verde/vermelho por reunião + ordenação Menos/Mais saudáveis), mas a **fórmula** (janela, pesos, o que conta como "saudável") está aberta.
- **Impacto técnico:** a saúde é **derivada** de relatórios/ocorrências. Enquanto a métrica agregada não estiver definida, dá para exibir o **sinal cru** (enviado/não enviado por reunião) sem uma nota composta.
- **Recomendação pragmática:** MVP = **saúde = série de "relatório enviado?" das últimas 10 ocorrências** (verde/vermelho) + contadores; ordenação por nº de verdes. Frequência/visitantes entram como **sinais adicionais** numa v2.
- **Decisão do dono:** a nota de saúde composta (pesos) é necessária no MVP ou basta o histórico de envio?
- **Risco se não decidir:** overengineering de uma "nota de saúde" antes de ter dados. Baixo — o MVP cru já entrega valor e é base para a fórmula.

### 4.4 Célula comum ↔ Árvore Ministerial
- **Contexto:** Árvore = quem lidera quem (organograma pastoral); célula = reunião. São **conceitos separados**. A **cobertura/descendência** liga os dois sem fundi-los.
- **Impacto técnico:** a célula referencia uma **cobertura** (líder pastoral). A multiplicação aprovada precisa **atualizar a árvore**. Se a Árvore ainda não é uma entidade robusta, a célula guarda a cobertura como **referência simples** e a integração fica num PR final (PR10), opcional.
- **Recomendação pragmática:** MVP = campo `cobertura` na célula (FK para pessoa/líder), **sem** acoplar à Árvore Ministerial. Integração real vira PR10 só se necessário.
- **Decisão do dono:** a Árvore Ministerial precisa ser atualizada automaticamente na multiplicação já no MVP, ou basta registrar a cobertura na célula?
- **Risco se não decidir:** acoplar cedo dois módulos e travar ambos. Baixo se mantivermos a cobertura como referência e adiarmos a sincronização.

### 4.5 Entidade ocorrência/reunião da célula
- **Contexto:** hoje **não existe** uma instância datada de reunião. Presença, expectativa, relatório e saúde **dependem** dela.
- **Impacto técnico:** é a **entidade central** do módulo. Sem ela, nada do fluxo Discípulo/Líder funciona. Define como se gera a "próxima reunião" (regra a partir de dia/hora da célula) e como se fecha o relatório por ocorrência.
- **Recomendação pragmática:** criar `celula_reuniao` (ocorrência) com data/hora/tema/status; **geração** da próxima ocorrência derivada do padrão da célula (job/consulta, não worker no MVP). É o **PR2** e destrava tudo.
- **Decisão do dono:** ocorrências são **materializadas** (uma linha por reunião) ou **virtuais** (calculadas)? Recomendo materializar ao confirmar/planejar.
- **Risco se não decidir:** é bloqueante duro — sem essa decisão, PR2 em diante não sai. **Precisa fechar antes do código.**

### 4.6 Entidade Solicitação + auditoria + payloads tipados
- **Contexto:** o PRD Solicitações define status, ciclo de vida, validações, aprovação transacional/idempotente/auditada.
- **Impacto técnico:** entidade genérica `solicitacao` (`tipo`, `status`, `payload_proposto`, `payload_atual`, motivo/observação, decisor, timestamps) + tabela de **auditoria** (transições append-only). Aprovação = aplicar payload por tipo numa **transação**.
- **Recomendação pragmática:** payload como **JSONB tipado por `tipo`** (validação na aplicação, não no banco), + tabela de transições. Multiplicação é um `tipo` especial com aplicação transacional (PR6).
- **Decisão do dono:** a Central pode **editar o payload** antes de aprovar (afeta auditoria e segregação)? Recomendo **não** no MVP (só aprovar/rejeitar/pedir ajuste).
- **Risco se não decidir:** modelar auditoria fraca e ter que refazer para conformidade. Médio — decidir a forma do payload e do log agora evita retrabalho.

## 5. Modelo de domínio proposto (sem código)

Entidades e relações (nomes ilustrativos; multi-tenant: **toda** tabela carrega `igreja_id` + RLS):

| Entidade | Campos-chave | Relações / notas |
|---|---|---|
| **Célula** | nome, cobertura (FK líder), líder (FK), auxiliar (FK, opcional), anfitrião (FK), dia, horário, endereço, link_grupo, link_localizacao, mensagem_convite, status (ativa/inativa) | 1 célula → N membros; leves (nome/link/msg) editáveis pelo líder; sensíveis via Solicitação |
| **Vínculo de célula (membro)** | pessoa_id, celula_id, papel (membro/auxiliar/anfitrião), ativo | 1 pessoa → 1 célula ativa (regra); entrada direta, saída via Solicitação |
| **Reunião / ocorrência** | celula_id, data, hora, tema, status (planejada/confirmada/realizada) | núcleo; gera presença/expectativa/relatório |
| **Presença** | reuniao_id, pessoa_id, estado (confirmada/compareceu/ausente) | base dos contadores e da saúde |
| **Expectativa de visitante** | reuniao_id, pessoa_id (membro), nome_visitante, observacao/oracao | **não** cria pessoa cadastrada |
| **Relatório da célula** | reuniao_id, tema, deu_avisos, teve_oferta(+valor?), observacoes, pedidos_oracao, enviado_em | presença via tabela Presença; visitantes reais via lista |
| **Visitante do relatório** | relatorio_id, nome, whatsapp, aceitou_jesus | aceitou → entra em consolidação (leitura de outro módulo); **não** vira membro auto |
| **Solicitação** | celula_id, solicitante, tipo, status, payload_proposto (JSONB), payload_atual (snapshot), motivo/observacao, aprovado_por/rejeitado_por, timestamps | genérica, extensível por `tipo` |
| **Solicitação de multiplicação** | (tipo especial de Solicitação) novo_lider, membros[], dia/hora, endereço, anfitrião, data_prevista | aplicação transacional (cria célula + move membros + árvore) |
| **Auditoria de solicitação** | solicitacao_id, de_status, para_status, autor, texto, criado_em | append-only |
| **Material para líderes** | tipo (sermão/quebra-gelo/música), titulo, tema, tags[], conteudo/arquivo/link, status (rascunho/publicado) | link só para música |
| **Aviso da Central** | titulo, mensagem, publico_alvo, quando/prioridade, status (enviado/agendado/rascunho) | igreja/central = vermelho; célula = azul (aviso da célula é outra origem, do líder) |

Derivados (não são tabela nova, são consulta/agregação): **indicadores do dashboard**, **saúde por célula**, **frequência média**.

## 6. Sequência recomendada de PRs

Ordem por dependência (cada um mergeável sozinho; back antes de front por camada):

1. **PR1 — Schema/base de Célula** (campos completos + vínculo de membro + RLS).
2. **PR2 — Ocorrência/reunião + Presença + Expectativa** (a entidade que destrava tudo).
3. **PR3 — Minha Célula / Discípulo** (tela + endpoints de presença/expectativa).
4. **PR4 — Relatório da célula / visão Líder** (escrita real + visitantes acumulando).
5. **PR5 — Entidade Solicitação + aprovação** (genérica: dia/hora/endereço/anfitrião/auxiliar/transferir/remover).
6. **PR6 — Multiplicação transacional** (tipo especial de Solicitação; evolui o stub `multiplicacoes`).
7. **PR7 — Central: dashboard + listas** (indicadores, gerenciar células, fila de solicitações UI).
8. **PR8 — Materiais e Avisos** (CRUD + publicar; avisos por público).
9. **PR9 — Saúde das células** (agregação + ordenação; MVP = série de envio).
10. **PR10 — Integração com Árvore Ministerial** (só se o dono exigir sincronização automática).

## 7. Detalhe por PR

> Convenções comuns a **todos**: multi-tenant (`igreja_id` + RLS via `set_tenant_context`); migration nova por **timestamp** (`scripts/new_migration.py`), aplicada manual no **DEV primeiro**; `pytest` verde antes de commitar; branch própria + PR; sem tocar env/worker/deploy fora do previsto; sem WhatsApp real.

### PR1 — Schema/base de Célula
- **Objetivo:** modelar a célula completa e o vínculo de membro.
- **Escopo:** tabelas `celula` (campos da seção 5) e `celula_membro`; endpoints CRUD de célula (Central) + edição de **dados leves** (líder); entrada direta de membro.
- **Camadas prováveis:** `backend/app/models/celula.py`, `schemas/`, `routers/celulas.py`, `db/rls` (políticas), `frontend/` (só leitura inicial).
- **Migrations:** criar `celula`, `celula_membro` + políticas RLS por `igreja_id`.
- **Testes mínimos:** CRUD respeita tenant; líder edita leve, não sensível; RLS isola igrejas.
- **Gates:** pytest; RLS testada com 2 tenants; sem regressão no `multiplicacoes` stub.
- **Fora de escopo:** ocorrência, relatório, solicitação.
- **Dependências:** nenhuma (base). **Requer decisão 4.2** (quais campos são sensíveis) e 4.1 (quem é Central) — aceitáveis por default provisório.

### PR2 — Ocorrência/reunião + Presença + Expectativa
- **Objetivo:** criar a entidade que datam as reuniões e capturam presença/expectativa.
- **Escopo:** `celula_reuniao`, `presenca`, `expectativa_visitante`; geração da "próxima ocorrência" a partir do padrão da célula; endpoints de confirmar presença / registrar expectativa.
- **Camadas:** models/schemas/routers correspondentes; regra de geração de ocorrência.
- **Migrations:** 3 tabelas + índices (por `celula_id`, `data`).
- **Testes:** presença é idempotente por (reunião, pessoa); expectativa aceita N por membro; contadores batem.
- **Gates:** pytest; RLS; sem worker.
- **Fora de escopo:** relatório, envio.
- **Dependências:** PR1. **Requer decisão 4.5** (materializada vs virtual) — **bloqueante**.

### PR3 — Minha Célula / Discípulo
- **Objetivo:** entregar a tela do membro (PRD Discípulo).
- **Escopo:** frontend da visão Discípulo (hero, próxima reunião, fluxos ① presença / ② expectativa, participantes, mural, histórico) ligada aos endpoints do PR2.
- **Camadas:** `frontend/` (rotas/componentes), consumo dos endpoints.
- **Migrations:** nenhuma.
- **Testes:** e2e/unit dos fluxos de presença e expectativa; estados vazios.
- **Gates:** typecheck/lint/build; smoke sem overflow ≥360px.
- **Fora de escopo:** visão Líder, Central.
- **Dependências:** PR2.

### PR4 — Relatório da célula / visão Líder
- **Objetivo:** relatório com escrita real + o resto da visão Líder que não depende de Solicitação.
- **Escopo:** `relatorio_celula` + `visitante_relatorio`; endpoints de salvar/enviar relatório; frontend das abas Painel/Discípulos/Planejar/Relatório/Avisos-da-célula.
- **Camadas:** models/schemas/routers + `frontend/`.
- **Migrations:** `relatorio_celula`, `visitante_relatorio`.
- **Testes:** enviar relatório marca ocorrência; visitantes acumulam e não viram membro; presença consolidada.
- **Gates:** pytest + front build; banner de relatório pendente (2h).
- **Fora de escopo:** solicitações sensíveis, multiplicação.
- **Dependências:** PR2 (ocorrência), PR1.

### PR5 — Entidade Solicitação + aprovação
- **Objetivo:** o fluxo genérico Líder→Central (PRD Solicitações).
- **Escopo:** `solicitacao` + `solicitacao_auditoria`; tipos dia/horário/endereço/anfitrião/auxiliar/transferir-membro/remover-membro; criar (líder), decidir (Central: aprovar/rejeitar/pedir-ajuste); aplicação por tipo; segregação + tenant + idempotência.
- **Camadas:** models/schemas/routers; serviço de aplicação por tipo; políticas RLS; `frontend/` (Editar célula do líder com "Solicitar alteração" + fila da Central).
- **Migrations:** `solicitacao`, `solicitacao_auditoria` (payload JSONB).
- **Testes:** rejeição exige motivo; ajuste exige observação; aprovação aplica e audita; imutabilidade até aprovar; idempotência (duplo clique); quem origina não aprova; tenant.
- **Gates:** pytest cobrindo a máquina de estados; RLS 2 tenants.
- **Fora de escopo:** multiplicação (PR6).
- **Dependências:** PR1. **Requer decisões 4.2 e 4.6.**

### PR6 — Multiplicação transacional
- **Objetivo:** multiplicação como tipo especial de Solicitação, aplicada em transação.
- **Escopo:** payload de multiplicação (novo líder apto, membros, dia/hora, endereço, anfitrião); aprovação = **cria célula + move membros + atualiza vínculos** numa transação (rollback em falha); evolui o **stub `multiplicacoes`**.
- **Camadas:** serviço transacional; reuso da Solicitação (PR5); `frontend/` aba Multiplicação (líder) + item na fila (Central).
- **Migrations:** provavelmente nenhuma nova (reusa `solicitacao`) — talvez índice.
- **Testes:** aprovação cria célula e move membros atomicamente; falha parcial faz rollback e não marca aprovada; só novo líder **apto**; revalidação na aprovação.
- **Gates:** pytest de transação/rollback; idempotência.
- **Fora de escopo:** organograma automático (PR10).
- **Dependências:** PR5 (Solicitação), PR1. **Requer 4.4** (o quanto a árvore é tocada agora).

### PR7 — Central: dashboard + listas
- **Objetivo:** a tela da Central (PRD Central) — leitura + fila.
- **Escopo:** endpoints de indicadores agregados; frontend Dashboard (stat-cards + saúde-cru) + Gerenciar células (lista/busca/filtros) + Solicitações (UI da fila, ligada ao PR5/PR6).
- **Camadas:** routers de agregação (read-only), `frontend/` da Central.
- **Migrations:** nenhuma (agregação por consulta).
- **Testes:** indicadores batem com dados mock; ordenação; tenant.
- **Gates:** pytest read + front build; Central **fora** de Minha Célula (invariante).
- **Fora de escopo:** materiais/avisos (PR8), saúde composta (PR9).
- **Dependências:** PR1, PR2, PR4, PR5.

### PR8 — Materiais e Avisos
- **Objetivo:** abastecer líderes.
- **Escopo:** `material` (rascunho/publicado, tipo, tema/tags, texto/arquivo/link) + `aviso_central` (público-alvo, agora/agendar); frontend das abas Materiais e Avisos; "Material da Central" no Planejar do líder consumindo publicados.
- **Camadas:** models/schemas/routers + `frontend/`; upload de arquivo (storage — decisão de infra à parte).
- **Migrations:** `material`, `aviso_central`.
- **Testes:** link só para música; publicar libera ao líder; público-alvo; tenant.
- **Gates:** pytest + front build; sem WhatsApp real (avisos só persistem/agendam).
- **Fora de escopo:** disparo real de aviso (agente).
- **Dependências:** PR1; PR4 (Planejar consome material).

### PR9 — Saúde das células
- **Objetivo:** consolidar o indicador de saúde.
- **Escopo:** agregação da série de "relatório enviado?" das últimas N ocorrências por célula + ordenação Menos/Mais saudáveis; sinais adicionais (frequência, visitantes) se a decisão 4.3 pedir.
- **Camadas:** serviço/consulta de agregação; frontend da lista de saúde (já esboçada no PR7, aqui ganha a métrica real).
- **Migrations:** nenhuma (ou índice para performance).
- **Testes:** saúde reflete envio/ausência; ordenação correta; performance com N células.
- **Gates:** pytest de agregação.
- **Fora de escopo:** nota composta se o dono não pedir.
- **Dependências:** PR2, PR4, PR7. **Requer 4.3** (fórmula) — default provisório = série de envio.

### PR10 — Integração com Árvore Ministerial (condicional)
- **Objetivo:** sincronizar a multiplicação/cobertura com o organograma **se** exigido.
- **Escopo:** ao aprovar multiplicação/transferência de liderança, atualizar a Árvore; refletir cobertura.
- **Camadas:** serviço de integração entre módulos.
- **Migrations:** depende do modelo da Árvore.
- **Testes:** multiplicação aprovada atualiza a árvore; cobertura consistente.
- **Gates:** pytest de integração.
- **Fora de escopo:** redesenho da Árvore.
- **Dependências:** PR6. **Só se decisão 4.4 exigir** — senão fica cobertura como referência simples e este PR não é feito no MVP.

## 8. Riscos técnicos

1. **Multi-tenant / RLS** — **toda** tabela nova precisa de `igreja_id` + política RLS, e o acesso deve passar por `set_tenant_context` (`SET LOCAL ROLE authenticated`). ⚠️ Sabe-se que o **worker roda com RLS desligada** (risco herdado) — nada do módulo Células deve rodar em worker sem tenant explícito. Mitigação: teste de isolamento com 2 tenants em cada PR de schema.
2. **Transação na aprovação** — multiplicação (criar célula + mover membros + árvore) tem que ser **tudo-ou-nada**. Risco de estado parcial. Mitigação: transação única + teste de rollback + não marcar `aprovada` antes do commit.
3. **Duplicidade / idempotência** — duplo clique em aprovar não pode aplicar duas vezes. Mitigação: estado terminal = no-op no servidor; unicidade de solicitação pendente por (célula, tipo) a avaliar.
4. **Histórico / auditoria** — decisões precisam de trilha append-only. Risco de log fraco. Mitigação: tabela de transições desde o PR5.
5. **Migração de dados existentes** — há telas/stub herdados (`multiplicacoes`, dados de célula parciais do MVP). Risco de conflito. Mitigação: mapear o que já existe antes do PR1; migrations aditivas; não apagar dados legados sem plano.
6. **Divergência protótipo vs. contrato** — a discrepância 14.1 (anfitrião/aux/endereço) e a aba "Líderes" (contrato tem, protótipo não). Risco de implementar a versão errada. Mitigação: **seguir o contrato** como regra provisória e travar a decisão do dono antes do PR5.

## 9. Estratégia de rollout

- **DEV primeiro** — toda migration aplicada e validada no Supabase **DEV** (projeto separado) via SQL Editor, em ordem de timestamp, antes de qualquer PROD.
- **PROD depois** — só após smoke em DEV; aplicar a mesma migration em PROD e redeployar.
- **Deploy separado** — **backend** (VPS, recreate do container para pegar env; restart não pega) e **frontend** (Vercel) deployam **independentes**; um PR de schema exige migration + backend; um PR de UI exige só frontend.
- **Flags** — features de escrita sensível (Solicitação, multiplicação) atrás de **flag off** até o fluxo estar validado ponta-a-ponta; ligar por igreja/gradual.
- **Sem WhatsApp real** — nenhum disparo pelo agente (cobrar líder, avisar responsável/membro) até o fluxo estar validado; até lá, as ações **persistem a intenção** sem enviar.
- **Backups/reversão** — migrations aditivas e reversíveis sempre que possível; nada destrutivo sem backup.

## 10. Critérios para começar código

**Precisam estar fechadas antes do PR2+ (estruturais):**
- **4.5 Ocorrência/reunião** — materializada vs virtual. **Bloqueia PR2 em diante.**
- **4.6 Forma da Solicitação/auditoria/payload** — bloqueia PR5/PR6.

**Podem começar com default provisório (documentado):**
- **4.1 Papel da Central** → default: pastor/admin = Central; ponto de extensão para `lider_central`.
- **4.2 Sensível vs. direto** → default: **seguir o contrato** (sensível). Fácil relaxar depois.
- **4.3 Critérios de saúde** → default: série de "relatório enviado?" das últimas 10; fórmula composta depois.
- **4.4 Árvore Ministerial** → default: cobertura como referência simples; PR10 só se exigido.

**Primeiro PR:** **PR1 (Schema/base de Célula)** — não depende das decisões estruturais mais duras e prepara o terreno; pode iniciar assim que 4.1/4.2 tiverem default aceito. **PR2 só começa depois de fechar 4.5.**

## 11. Recomendação final

- **Sequência de implementação:** PR1 → PR2 → PR3 → PR4 → PR5 → PR6 → PR7 → PR8 → PR9 → (PR10 condicional). Back antes de front por camada; schema antes de fluxo.
- **Decisão que eu, como engenheiro, recomendo tomar agora:** adotar os **defaults provisórios** de 4.1 (pastor/admin = Central), 4.2 (**seguir o contrato** — sensível), 4.3 (saúde = série de envio) e 4.4 (cobertura como referência, sem acoplar a Árvore). Isso destrava PR1 imediatamente sem fechar o dono em nada irreversível.
- **O que ainda precisa ser confirmado pelo dono (antes do PR2/PR5):**
  1. **4.5** — ocorrências **materializadas** (recomendo) ou virtuais. **Bloqueante do PR2.**
  2. **4.6** — payload JSONB tipado + auditoria append-only, e **Central não edita payload** antes de aprovar (recomendo). **Bloqueante do PR5.**
  3. **4.2** — confirmar sensível para anfitrião/auxiliar/endereço (ou liberar algum como direto).
  4. **4.1** — papel `lider_central` dedicado agora ou depois.
  5. **4.3 / 4.4** — se saúde composta e sincronização com a Árvore entram no MVP ou ficam para v2.

**Próxima ação sugerida (docs-only):** o dono responde as 5 confirmações acima (idealmente num despacho curto), viram um adendo a este plano, e só então abre-se o **PR1** de implementação.

---

### Referências

- Série de PRDs Células (todos em `main`): [contrato](CONTRATO-UX-CELULAS-CENTRAL.md) · [Discípulo](PRD-MINHA-CELULA-DISCIPULO.md) · [Líder](PRD-MINHA-CELULA-LIDER.md) · [Solicitações](PRD-CELULAS-SOLICITACOES-APROVACAO.md) · [Central](PRD-CENTRAL-DE-CELULAS.md).
- `CLAUDE.md` — stack, RLS, migrations por timestamp, regras de trabalho.
