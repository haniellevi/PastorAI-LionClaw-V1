# Células — Multiplicação de Célula (solicitação → aprovação)

> Especificação funcional e técnica. **Modelagem/auditoria — nada implementado.**
> Ancorada no código real: `backend/app/routers/multiplicacoes.py`,
> `backend/app/domain/multiplication.py`, models `Celula`/`Pessoa`/`Multiplicacao`
> (`backend/app/db/models.py`), triggers `backend/migrations/0004_triggers.sql`,
> RLS `backend/app/db/rls.py`.

## 0. Ponto de partida (o que já existe)

Já existe o módulo `multiplicacoes` (US-21/22/23, delta-027): tabela + router +
domain + RLS + testes. Hoje é **leve/stub**:

- `POST /multiplicacoes` cria a linha como `agendada` (com data) ou
  `sem_agendamento`;
- `POST /multiplicacoes/{id}/aprovar` **só troca o status** para `aprovada` e grava
  `aprovada_por`, bloqueado enquanto `supervisao_ok=false`;
- **não cria célula, não move membros, não atualiza organograma, não transfere
  gestão**;
- enum de status atual: `agendada, sem_agendamento, aprovada, concluida`.

### Decisão de produto/arquitetura (fixada)

1. **Evoluir** o módulo/tabela/router `multiplicacoes` existente. **Não** criar
   `cell_multiplication_requests` paralela (evita dois conceitos "multiplicação"
   competindo).
2. A solicitação **nasce `pendente`** (não `agendada`).
3. A **aprovação executa tudo em uma transação**: cria célula → define novo líder
   → move membros selecionados → grava dia/hora/endereço/anfitrião → atualiza
   organograma/cobertura → concede gestão ao novo líder.
4. **Rejeição/cancelamento** não cria célula nem move membros (rejeição grava
   motivo).
5. **"Apto"** (a liderar / multiplicar / consolidar) vira **regra explícita** —
   não fica escondido em `etapa='enviar'` sem decisão formal.
6. **Central de Células** precisa de **papel real** (`lider_central` ou
   equivalente). Até existir, `pastor`/`lider_g12` é **fallback temporário**, não
   a regra final.

## 1. Fluxo de usuário

1. **Líder apto** abre "Solicitar Multiplicação" na célula de origem.
2. Seleciona: **novo líder** (apto a liderar), **membros** que vão para a nova
   célula, **dia + hora**, **endereço**, **anfitrião**.
3. "Solicitar Multiplicação" → cria **solicitação `pendente`**. Nenhuma célula real
   é criada agora.
4. **Central de Células** vê a fila, abre a solicitação (pode marcar
   `em_analise`).
5. **Aprovar** → 1 transação (§3.item 3). Status → `aprovada`; a nova célula passa
   a existir e os membros já estão nela.
6. **Rejeitar** → grava **motivo**; nada é criado/movido. Status → `rejeitada`.
7. **Cancelar** (pelo solicitante) enquanto `pendente`/`em_analise` → `cancelada`.

Estados de tela: fila (lista por status) · detalhe da solicitação (com membros e
dados) · form de solicitação · ação da Central (aprovar/rejeitar/cancelar +
motivo).

## 2. Permissões

| Ação | Regra de negócio | Situação no código atual |
|---|---|---|
| Solicitar multiplicação | só **líder apto** | hoje `MULTIPLICATION_ROLES = [lider_g12, pastor]` (+admin implícito). "apto" **não é campo** — ver Decisão Aberta A |
| Analisar / Aprovar / Rejeitar | **Central de Células** | papel `lider_central` **não existe no DB** (migration de papéis desenhada, não aplicada). Fallback: `pastor`/`lider_g12` — ver Decisão Aberta B |
| Cancelar solicitação | **solicitante** (enquanto pendente/em_análise) | não existe hoje |
| Ser **novo líder** | pessoa **apta a liderar** | sem flag dedicada; sinal existente mais próximo: `pessoa.etapa='enviar'` — ver Decisão Aberta A |
| Dar aula na **CD** e na **UV** | só **líderes** | UV modelada (`consolidacao_tipo='universidade_vida'`); CD via `pessoa.apto_proxima_cd`. Gate de "quem **ministra**" **não modelado** |
| **Consolidar** pessoas | só **líderes aptos "para frente"** | consolidação existe (`consolidacoes.responsavel_id` faz o gate de confirmação de etapa); "apto para frente" **não modelado** — ver Decisão Aberta A |

## 3. Status (novo enum `multiplicacao_status`)

`pendente` · `em_analise` · `aprovada` · `rejeitada` · `cancelada`

Transições válidas:

- `pendente → em_analise → aprovada|rejeitada`
- `pendente → aprovada|rejeitada` (análise direta, sem passo intermediário)
- `pendente|em_analise → cancelada` (pelo solicitante)
- `aprovada|rejeitada|cancelada` = **terminais** (nova ação → **409**).

> **Migração de enum:** os valores atuais (`agendada, sem_agendamento, concluida`)
> saem/são remapeados. Como `0007_remove_demo_data` zerou as `multiplicacoes` e o
> módulo não entrou em produção com dados reais, o custo é baixo — mas a migration
> precisa recriar/alterar o tipo `multiplicacao_status` e ajustar `VALID_STATUS`,
> testes e RLS.

## 4. Entidades / tabelas prováveis

Evoluindo `multiplicacoes` (colunas em `snake_case`, seguindo o modelo atual):

- **`multiplicacoes`** (estender):
  - `status` → novo enum (§3);
  - `celula_origem_id` (= `celula_id` atual, renomear/aliar);
  - `solicitante_id` → `app_users` (quem pediu);
  - `novo_lider_id` → `pessoas` (já existe);
  - `dia_semana` + `hora` (HH:MM, espelhar `events_hora_formato_chk`);
  - `endereco` (texto);
  - `anfitriao_id` → `pessoas` **ou** `anfitriao` (texto) — decidir;
  - `motivo_rejeicao` (texto, preenchido em `rejeitada`);
  - `celula_criada_id` → `celulas` (NULL até a aprovação criar a célula);
  - `decidida_por` / `decidida_em` (auditoria; reusar `aprovada_por`);
  - manter `data_prevista`/`descendencia`/`supervisao_ok` só se seguirem úteis.
- **`multiplicacao_membros`** (nova, child): `(multiplicacao_id, pessoa_id)` — os
  membros selecionados. `UNIQUE(multiplicacao_id, pessoa_id)`, FK `ON DELETE
  CASCADE`, `igreja_id` para RLS.
- **Reuso na aprovação:**
  - `celulas` (cria a nova: `nome, lider_id, dia_reuniao, cobertura_espiritual,
    ativo`);
  - `pessoas` (mover membros = setar `celula_id` e `lider_id`);
  - vínculo de gestão do novo líder = `user_roles`/associação líder→célula
    (depende do modelo de papéis — Decisão Aberta B).
- **Organograma = derivado, não há tabela:** é a árvore
  `celulas.cobertura_espiritual` + `celulas.lider_id` + cadeia `pessoas.lider_id`.
  "Atualizar organograma" = definir a cobertura da nova célula e religar
  `pessoas.lider_id`/`celula_id` dos membros movidos — ver Decisão Aberta C.
- **Aptidão:** provável nova coluna em `pessoas` (ex.: `apto_lider boolean`) **ou**
  regra derivada — Decisão Aberta A.

## 5. Endpoints prováveis (namespace `/multiplicacoes` existente)

- `POST /multiplicacoes` — cria solicitação **`pendente`**. Body estende o atual:
  `+ membros[]`, `dia_semana`, `hora`, `endereco`, `anfitriao`, `novo_lider_id`.
  ⚠️ muda o default de status (hoje nasce `agendada`).
- `GET /multiplicacoes?status=` — fila (já existe; validar novo enum).
- `GET /multiplicacoes/{id}` — detalhe + membros selecionados (novo).
- `POST /multiplicacoes/{id}/analisar` — `pendente → em_analise` (opcional).
- `POST /multiplicacoes/{id}/aprovar` — **transação** (reescreve o handler atual,
  que só flipa status).
- `POST /multiplicacoes/{id}/rejeitar` — body `{ motivo }` → `rejeitada`.
- `POST /multiplicacoes/{id}/cancelar` — solicitante, enquanto
  `pendente`/`em_analise`.

## 6. Validações

- **Tenant:** toda leitura/escrita filtra `igreja_id` (RLS + predicado explícito,
  padrão do projeto).
- **Solicitante** é apto (Decisão Aberta A) e tem relação com a célula de origem.
- **Célula de origem** existe, é do tenant e está `ativo`.
- **Novo líder:** existe, do tenant, **apto a liderar**; coerência com a lista de
  membros (definir se o novo líder também é "movido").
- **Membros:** cada um pertence à célula de origem (`pessoa.celula_id ==
  celula_origem`); sem duplicatas; lista **não vazia**.
- **Dados da nova célula:** `dia_semana` + `hora` (HH:MM), `endereco`, `anfitrião`
  obrigatórios na solicitação.
- **Transições de status** guardadas (§3); decidir de novo em estado terminal →
  **409** (espelha o padrão do projeto, ex.: confirm de evento / aprovação por
  supervisão).
- **Aprovação atômica e idempotente:** `SELECT ... FOR UPDATE` (já usado hoje em
  `aprovar`) + transação única; erro parcial faz rollback total.

## 7. Riscos

- **R1 — evolução do enum/tabela:** mudar `multiplicacao_status` e o default de
  criação afeta `VALID_STATUS`, testes e RLS existentes. Migração precisa cuidar do
  tipo enum no Postgres.
- **R2 — aprovação transacional (núcleo):** criar célula + mover N membros +
  religar líder + organograma numa transação **RLS-safe** — precisa do
  `set_tenant_context` com `SET LOCAL ROLE authenticated` (`app/db/rls.py`; o role
  `postgres` tem BYPASSRLS). Falha parcial não pode deixar meia-célula.
- **R3 — triggers colaterais:** mover `pessoa.celula_id` dispara
  `fn` de `0004_triggers.sql` que seta `acompanhamento='consolidado'` (e mexe em
  subetapa). A aprovação precisa considerar/absorver esses efeitos.
- **R4 — aptidão indefinida (bloqueia permissões):** não há flag "apto a liderar" /
  "apto para frente"; só `apto_proxima_cd` (CD) e `etapa='enviar'`. Sem decisão,
  metade das regras de §2 fica ambígua.
- **R5 — papel da Central de Células ausente:** `lider_central` não existe no DB.
  Fallback `pastor`/`lider_g12` é temporário; a regra final depende de aplicar a
  migration de papéis. Ver `[[pastorai-papeis-lider-modelo]]`.
- **R6 — cobertura/organograma da nova célula:** a descrição não diz de onde a nova
  célula herda a cobertura espiritual (da origem? do novo líder?). Regra ausente —
  Decisão Aberta C.
- **R7 — concurrency / duplo-aprovar:** lock já existe; manter e cobrir com teste.
- **R8 — "conceder gestão ao novo líder":** criar `UserRole`/vínculo depende do
  modelo de papéis (R5) — pode exigir criar `AppUser` para o líder se ele ainda não
  tiver acesso ao painel.
- **R9 — integridade dos membros:** membro movido some da célula de origem
  (contagens, alertas `cell_alerts` ligados por `celula_id ON DELETE CASCADE`); a
  transação precisa manter consistência.

## 8. Divisão sugerida em PRs pequenos

- **PR1 — schema** (migration + models): novo enum de status; colunas novas em
  `multiplicacoes`; tabela `multiplicacao_membros`; RLS das novas linhas. **Sem
  comportamento novo.** Materializa a Decisão de evoluir (§0).
- **PR2 — criar solicitação `pendente`** + validações (apto, membros pertencem à
  origem, campos obrigatórios) + `GET` detalhe/lista com membros. **Sem efeitos de
  aprovação.**
- **PR3 — rejeitar + cancelar** (transições de status + `motivo`). Barato,
  independente do PR4.
- **PR4 — aprovar (transação)**: cria célula, define líder, move membros, grava
  dia/hora/endereço/anfitrião, cobertura/organograma, concede gestão. **Núcleo
  pesado** — testes de atomicidade, RLS e idempotência.
- **PR5 — permissões "apto"** (materializa Decisão Aberta A) + gate CD/UV + gate
  consolidar. Cross-cutting; pode correr em paralelo a PR2–PR4.
- **PR6 — frontend**: form de solicitação (novo líder, membros, dia/hora, endereço,
  anfitrião) + tela da Central (aprovar/rejeitar/cancelar + motivo).

> Pré-requisito de PR4/PR5: fechar as Decisões Abertas A, B e C.

## 9. Decisões abertas (precisam do dono do produto)

- **A. Como modelar aptidão** ("apto a liderar / multiplicar / consolidar"):
  - opção 1 — **coluna(s) explícita(s)** em `pessoas` (ex.: `apto_lider`,
    `apto_consolidar`), setadas por processo formal;
  - opção 2 — **regra derivada** (ex.: `etapa='enviar'` + concluiu CD/UV) — mas a
    decisão fixa (§0.5) pede que **não** fique implícita sem formalizar.
  - Recomendo opção 1 (flag explícita, auditável) e a regra fica no domain.
- **B. Qual papel representa a Central de Células:**
  - opção 1 — aplicar a migration de `lider_central` e usá-lo como aprovador
    (regra final);
  - opção 2 — `pastor`/`lider_g12` como **fallback temporário** até (1).
  - Recomendo planejar (1); começar em (2) só se preciso desbloquear.
- **C. Cobertura espiritual/organograma da nova célula:**
  - de onde herda: **da célula de origem** (mesma cobertura) ou **do novo líder**
    (o líder de origem passa a cobrir a nova)?
  - Definir também o novo `lider_id`/`cobertura_espiritual` e como os
    `pessoas.lider_id` dos membros movidos passam a apontar para o novo líder.

## Referências de código

- Router atual: `backend/app/routers/multiplicacoes.py`
- Regras/domain: `backend/app/domain/multiplication.py`
  (`MULTIPLICATION_ROLES`, `can_approve`, `schedule_status`)
- Models: `backend/app/db/models.py` (`Celula`, `Pessoa`, `Multiplicacao`,
  `UserRole`, `CellAlert`)
- Triggers de vínculo à célula: `backend/migrations/0004_triggers.sql`
- RLS / tenant: `backend/app/db/rls.py` (`set_tenant_context`, BYPASSRLS)
