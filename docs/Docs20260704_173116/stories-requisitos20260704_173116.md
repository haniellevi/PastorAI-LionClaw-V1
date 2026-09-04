# User Stories e Requisitos — PR2 Células (Reuniões, Presença e Expectativa de Visitante)

> **Procedimento de migration substituído (2026-09-04):** requisitos de
> produto abaixo continuam como registro histórico; aplicação manual deixou de
> ser o procedimento vigente. Use
> [`backend/migrations/README.md`](../../backend/migrations/README.md); este
> documento não autoriza acesso ou mutação de banco.

> Feature: base backend-only de reuniões reais de célula (PastorAI / Igreja 12).
> Origem: `discovery20260704_173116.md` + SPEC canônica LIONCLAW-WORKFLOW-SPEC-PR2-CELULAS.
> Base commit: `7b31d4c` (PR1 em `origin/main`).
> Escopo: backend-only, aditivo sobre o PR1. NÃO altera `celulas` nem `pessoas`.

---

## 0. Contexto de arquitetura relevante (código existente)

Levantamento feito no repositório para ancorar as stories na arquitetura atual:

- **Router de referência:** `backend/app/routers/cells.py` — padrões a reusar: `ensure_tenant_context`, `_get_cell_or_404`, `_assert_pessoa_tenant` (valida tenant de Pessoa referenciada, pois a FK do Postgres não é RLS-scoped), `_actor_pessoa_id`, `_can_edit_cell`, `_lider_of_map`.
- **Helpers compartilhados:** `backend/app/routers/_common.py` — `Page[T]`, `PaginationParams` (page/pageSize, cap `MAX_PAGE_SIZE=200`) e `ensure_tenant_context` (reafirma a GUC de RLS por transação; não fazer leitura RLS-dependente após commit).
- **Hierarquia de liderança:** `backend/app/domain/hierarchy.py` — `is_leader_or_superior(actor_pessoa_id, cell_leader_id, lider_of)` (pura, com guard de ciclo). Base da autorização de "líder-da-célula-ou-superior".
- **Autenticação/tenant:** `backend/app/deps.py` — `CurrentUser` com `app_user_id`, `clerk_user_id`, `igreja_id` e `has_any_role(...)`. `get_current_user` já chama `set_tenant_context`.
- **RLS:** `backend/app/db/rls.py` — `set_tenant_context` faz `SET LOCAL ROLE authenticated` (não remover; o role `postgres` tem BYPASSRLS).
- **Modelos:** `backend/app/db/models.py` — `Celula` (com `dia_reuniao` texto livre, `horario` texto `HH:MM` validado por CHECK `celulas_horario_chk` NOT VALID, ambos nullable), `CelulaMembro` (vínculo canônico, índice único parcial `celula_membro_pessoa_ativa_uq` `where ativo`), `Pessoa`, `AppUser`, `Igreja`.
- **Migration PR1:** `backend/migrations/20260703_123803_celula_schema_base_pr1.sql` — padrão de migration aditiva/idempotente, RLS `enable` + policy `tenant_isolation` (`using (igreja_id = current_igreja_id())` + `with check`).
- **Padrão de status como constantes string:** `backend/app/routers/events.py` (ex.: `STATUS_A_CONFIRMAR`, `STATUS_CONFIRMADO`) — reusar o mesmo estilo para o status da reunião em vez de enum Python.
- **Registro de router:** `backend/app/main.py` (`app.include_router(cells.router)`); um novo router segue o mesmo `include_router`.
- **Padrão de teste:** `backend/tests/test_cells_crud.py` — fake session que espelha os predicados WHERE (`CellSession`), estilo `test_agent_crons_crud.py`; RLS real validada em DEV.
- **Regra fixa:** nunca alterar o código-fonte do LionClaw (`.lionclaw/...`).

### Personas

- **Líder de célula / Superior na cadeia** — lidera a célula ou está acima na cadeia `pessoas.lider_id`.
- **Pastor / Admin / Central de Células** — papéis `CENTRAL_ROLES` (`pastor`) + admin implícito via `has_any_role`.
  > **Nota (PR2):** "Central" NÃO é um papel dedicado no MVP. No código, `CENTRAL_ROLES = ["pastor"]` (cells.py) e o admin passa implicitamente por `has_any_role`. O papel `lider_central` dedicado está fora do MVP. Portanto, em todas as US/RF onde se lê "pastor/admin/Central", o conjunto autorizado é exatamente `has_any_role(["pastor"])` (que já inclui admin). Não implementar/procurar um papel "central" separado.
- **Membro (Discípulo)** — pessoa com vínculo ativo em `celula_membro` (`ativo = true`), representada por um `AppUser` ligado a `pessoa_id`.

---

## 1. User Stories

### Domínio A — Reunião / Ocorrência Materializada (`celula_reuniao`)

**US-01 — Materializar a próxima reunião**
Como líder da célula (ou superior/pastor/admin/Central), quero materializar a próxima reunião da minha célula, para registrar presença e expectativas sobre uma ocorrência real.
Critérios de aceite:
- `POST /cells/{cellId}/reunioes/next` cria uma linha em `celula_reuniao` quando ainda não existe reunião para a data calculada.
- A data é calculada a partir de `celulas.dia_reuniao` (texto PT-BR) e `celulas.horario` (`HH:MM`).
- Se já existe reunião para (célula, data calculada), o endpoint retorna a reunião existente (não cria duplicata) com HTTP 200.
- A reunião nasce com `status = 'planejada'`.
- A resposta inclui `id`, `celulaId`, `data`, `hora` (ou null), `tema` (ou null) e `status`.
- Célula inexistente no tenant retorna 404 (via `_get_cell_or_404`).

**US-02 — Rejeitar cálculo com dados insuficientes**
Como líder, quero receber um erro claro quando a célula não tem dados suficientes para calcular a reunião, para saber que preciso preencher dia/horário antes.
Critérios de aceite:
- `celulas.dia_reuniao` ausente/vazio ou não reconhecido pelo parser PT-BR retorna HTTP 422.
- `celulas.horario` NULL (célula legada) SEMPRE retorna HTTP 422: materializar exige `celulas.horario` preenchido (opção a). Sem horário na célula não há criação de reunião.
- A mensagem 422 indica o campo faltante/inválido (dia ou horário).
- Nenhuma linha em `celula_reuniao` é criada em caso de 422.

**US-03 — Listar reuniões da célula**
Como usuário autenticado do tenant, quero listar as reuniões de uma célula, para acompanhar as ocorrências planejadas/realizadas.
Critérios de aceite:
- `GET /cells/{cellId}/reunioes` retorna apenas reuniões da célula informada, escopadas ao tenant atual.
- Autorização segue o padrão de leitura de `cells.py` (ex.: `GET /cells/{id}`): qualquer usuário autenticado do tenant pode listar; NÃO há guard adicional de vínculo/liderança. A proteção é o escopo por `igreja_id` + 404 para célula fora do tenant.
- A resposta segue o mesmo estilo dos endpoints existentes de `cells.py` (lista de objetos de reunião).
- Reunião de outra igreja nunca aparece (RLS + filtro explícito por `igreja_id`).
- Célula inexistente no tenant retorna 404.

**US-04 — Bloquear criação por membro comum**
Como sistema, quero impedir que um membro comum materialize reuniões, para que só liderança/Central controle a agenda da célula.
Critérios de aceite:
- Um `AppUser` sem papel pastor/admin/Central e que não é líder-da-célula-ou-superior recebe 403 em `POST /cells/{cellId}/reunioes/next`.
- Pastor/admin (via `has_any_role`) e Central (`CENTRAL_ROLES`) sempre passam.
- Líder-da-célula-ou-superior (via `is_leader_or_superior` + `_lider_of_map`) passa.

### Domínio B — Presença (`celula_presenca`)

**US-05 — Confirmar a própria presença**
Como membro (Discípulo) com vínculo ativo na célula, quero confirmar minha presença numa reunião, para que a liderança tenha o registro da minha participação.
Critérios de aceite:
- `POST /cell-reunioes/{reuniaoId}/presenca` sem `pessoaId` usa a pessoa vinculada ao `app_user` atual (`AppUser.pessoa_id`).
- Requer vínculo ativo do membro na célula da reunião (`celula_membro.ativo = true`); sem vínculo ativo retorna 403.
- `app_user` sem `pessoa_id` vinculado retorna 403 (ou 422, definido na implementação) sem gravar presença.
- A presença fica escopada por `igreja_id` e associada a `(reuniao_id, pessoa_id)`.
- O registro grava `estado` (`confirmada|compareceu|ausente`, DEC-01/SPEC §8.2) e `origem`; ao confirmar a própria presença o `estado` default é `confirmada`.

**US-06 — Idempotência da presença**
Como membro, quero poder confirmar presença mais de uma vez sem gerar duplicatas, para que reenvios/toques repetidos não corrompam os dados.
Critérios de aceite:
- Marcar presença de novo para o mesmo `(igreja_id, reuniao_id, pessoa_id)` faz upsert (não insere segunda linha).
- A restrição `UNIQUE(igreja_id, reuniao_id, pessoa_id)` garante unicidade no banco.
- Uma corrida contra o índice único é mapeada para o mesmo resultado idempotente (recupera a linha existente e retorna 200, não vaza 500). ATENÇÃO: diferente do `add_cell_member`, que trata `IntegrityError` como 409 — a presença NUNCA retorna 409, o `IntegrityError` da corrida vira resultado idempotente (200).

**US-07 — Líder marca presença de terceiro**
Como líder da célula (ou superior/pastor/admin/Central), quero marcar a presença de outro participante da célula, para registrar quem compareceu durante a reunião.
Critérios de aceite:
- Com `pessoaId` informado, o líder-ou-superior/pastor/admin/Central marca a presença dessa pessoa.
- A pessoa alvo precisa existir no tenant (via `_assert_pessoa_tenant`) e ter vínculo ativo na célula da reunião.
- Um membro comum que envia `pessoaId` diferente do seu recebe 403 (só marca a própria).

**US-08 — Isolamento por tenant na presença**
Como sistema, quero rejeitar presença que referencie reunião ou pessoa de outra igreja, para nunca vazar dados entre tenants.
Critérios de aceite:
- Reunião de outro tenant retorna 404 (não encontrada sob RLS).
- `pessoaId` de outra igreja retorna 422 (via `_assert_pessoa_tenant`).
- Todas as queries passam por `ensure_tenant_context`.

### Domínio C — Expectativa de Visitante (`celula_expectativa_visitante`)

**US-09 — Registrar expectativa de visitante**
Como membro da célula, quero registrar que espero trazer visitante(s) para uma reunião, para ajudar a liderança a se preparar.
Critérios de aceite:
- `POST /cell-reunioes/{reuniaoId}/expectativas-visitantes` registra a expectativa sempre da própria pessoa do `app_user` atual (no PR2 não se registra por terceiro).
- Requer vínculo ativo do membro na célula da reunião (`celula_membro.ativo = true`); sem vínculo retorna 403.
- É permitido registrar múltiplas expectativas por membro na mesma reunião (N por membro/reunião).
- O endpoint NÃO cria `Pessoa` nem contato e NÃO envia WhatsApp.
- Reunião inexistente/de outro tenant retorna 404.

**US-10 — Validação do payload de expectativa**
Como sistema, quero validar o corpo da expectativa de visitante na borda, para não persistir registros incompletos.
Critérios de aceite:
- O payload obrigatório da expectativa é validado no schema Pydantic (campos ausentes/inválidos retornam 422).
- Nada é gravado quando a validação falha.
- Campos (DEC-02/SPEC §8.3): `nome_visitante` obrigatório (não-vazio); `observacao_oracao` opcional. Modelo nominal, não por contagem.

### Domínio D — Schema, RLS e Testes

**US-11 — Migration aditiva com RLS por tenant**
Como mantenedor, quero uma migration aditiva que crie as 3 tabelas com RLS própria, para preservar o PR1 e o isolamento multi-tenant.
Critérios de aceite:
- Migration nova por timestamp `AAAAMMDD_HHMMSS_slug.sql` em `backend/migrations/`, idempotente (`if not exists` / `do $$` / `drop policy if exists`), transacional.
- Cria `celula_reuniao`, `celula_presenca` e `celula_expectativa_visitante`.
- Cada tabela: `enable row level security` + policy `tenant_isolation` com `using (igreja_id = current_igreja_id())` e `with check (...)`.
- NÃO altera `celulas`, `pessoas` nem `multiplicacoes`; não toca `set_tenant_context`/BYPASSRLS.
- Aplicação manual no Supabase, DEV antes de PROD.

**US-12 — Cobertura de testes pytest**
Como mantenedor, quero testes cobrindo schema/autorização/idempotência/tenant, para garantir o comportamento sem depender de deploy.
Critérios de aceite:
- Arquivos `backend/tests/test_cell_meetings.py` e `backend/tests/test_celulas_pr2_models.py`.
- Testes rodam a partir da raiz do repo (sem `cd`), no padrão fake-session de `test_cells_crud.py` (espelham predicados WHERE).
- Cobrem: criação/idempotência/422/tenant da reunião; presença própria/idempotência/líder-marca-terceiro/membro-não-marca-outro/rejeita-outro-tenant; expectativa própria/obrigatoriedade/múltiplas/não-cria-Pessoa/tenant.
- A suíte pré-existente continua passando (não regride PR1).

---

## 2. Requisitos Funcionais (RF)

### Domínio A — Reunião

- **RF-01** (US-01, US-03) — Expor um router de reuniões registrado em `app/main.py` via `include_router`, seguindo o estilo de `cells.py`, com os endpoints: `GET /cells/{cellId}/reunioes`, `POST /cells/{cellId}/reunioes/next`, `POST /cell-reunioes/{reuniaoId}/presenca`, `POST /cell-reunioes/{reuniaoId}/expectativas-visitantes`.
- **RF-02** (US-01) — `POST /cells/{cellId}/reunioes/next` materializa a próxima reunião: cria linha em `celula_reuniao` com `status = 'planejada'` se não existir para (célula, data calculada); retorna a existente se já houver (sem duplicar), respeitando `UNIQUE(celula_id, data)`.
- **RF-03** (US-01, US-02) — Calcular a próxima reunião de forma determinística a partir de `celulas.dia_reuniao` e `celulas.horario`, sem dependência externa, sem config global nova e sem worker; usar data-base fixa/helper injetável para ser testável.
- **RF-04** (US-02) — Parser PT-BR de `dia_reuniao` reconhecendo `segunda|terca|quarta|quinta|sexta|sabado|domingo` com robustez a acentos e sufixo "-feira"; valor desconhecido/ausente retorna HTTP 422.
- **RF-05** (US-01) — Regra de próxima data: escolher a próxima ocorrência do dia igual ou posterior a hoje; se hoje é o dia mas o `horario` já passou, avançar para a próxima semana.
- **RF-06** (US-03) — `GET /cells/{cellId}/reunioes` lista reuniões da célula, escopadas ao tenant (RLS + filtro explícito por `igreja_id`), no envelope/estilo usado em `cells.py`.
- **RF-07** (US-01, US-03) — Resolver a célula por `_get_cell_or_404` (404 para UUID inválido ou célula fora do tenant) antes de operar reuniões.
- **RF-07b** (US-05, US-07, US-08, US-09) — Nos endpoints `/cell-reunioes/{reuniaoId}/...`, resolver a reunião por um helper análogo a `_get_cell_or_404` (ex.: `_get_reuniao_or_404`), escopado por tenant: `reuniaoId` malformado (não-UUID) → 404; reunião inexistente ou de outro tenant (sob RLS) → 404. NÃO se exige `cellId` no path; a reunião já carrega `celula_id`/`igreja_id` para os checks subsequentes de vínculo.
- **RF-08** (US-04) — Autorização de criação de reunião: liberar para papéis pastor/admin (via `has_any_role`) e Central (`CENTRAL_ROLES`) ou para líder-da-célula-ou-superior (via `is_leader_or_superior` com `_lider_of_map` + `_actor_pessoa_id`); caso contrário 403. Membro comum não cria.

### Domínio B — Presença

- **RF-09** (US-05) — `POST /cell-reunioes/{reuniaoId}/presenca` sem `pessoaId` resolve a pessoa via `AppUser.pessoa_id` do usuário atual; `app_user` sem `pessoa_id` é rejeitado sem gravar.
- **RF-10** (US-05, US-09) — Validar vínculo ativo em `celula_membro` (`ativo = true`) entre a pessoa e a célula da reunião antes de gravar presença/expectativa; sem vínculo ativo retorna 403.
- **RF-11** (US-06) — Persistir presença de forma idempotente por `(igreja_id, reuniao_id, pessoa_id)`, garantida por `UNIQUE(igreja_id, reuniao_id, pessoa_id)`; nova marcação faz upsert (não duplica).
- **RF-12** (US-06) — Tratar corrida contra o índice único (`IntegrityError`) mapeando para o resultado idempotente (recupera a linha existente, retorna 200), sem vazar 500. Distinto do `add_cell_member` (que mapeia `IntegrityError` para 409): a presença NÃO retorna 409 — a idempotência vence.
- **RF-13** (US-07) — Com `pessoaId` informado, permitir que líder-da-célula-ou-superior/pastor/admin/Central marque a presença de outro participante; membro comum que envia `pessoaId` diferente do próprio recebe 403.
- **RF-14** (US-07, US-08) — Validar tenant da pessoa alvo com `_assert_pessoa_tenant` (422 se de outra igreja) e resolver a reunião sob RLS (404 se de outro tenant).

### Domínio C — Expectativa de Visitante

- **RF-15** (US-09) — `POST /cell-reunioes/{reuniaoId}/expectativas-visitantes` registra expectativa sempre da própria pessoa do `app_user` no PR2; permite N registros por membro/reunião.
- **RF-16** (US-09) — A operação NÃO cria `Pessoa`/contato e NÃO dispara WhatsApp ou qualquer efeito externo.
- **RF-17** (US-10) — Validar o payload da expectativa no schema Pydantic (borda): `nome_visitante` é obrigatório (não-vazio → 422 se ausente/vazio, DEC-02/SPEC §8.3); `observacao_oracao` é opcional. Nada é persistido quando inválido.
- **RF-18** (US-09) — Resolver a reunião sob RLS e por `igreja_id` (404 se inexistente/de outro tenant) antes de gravar a expectativa.

### Domínio D — Schema, RLS e Registro

- **RF-19** (US-11) — Criar `celula_reuniao` com colunas `id, igreja_id, celula_id, data, hora (null), tema (null), status default 'planejada', created_at, updated_at`; `status` no conjunto `planejada|confirmada|realizada|cancelada`; `UNIQUE(celula_id, data)`. A coluna `hora` é nullable APENAS para dados legados/import; no fluxo `POST .../reunioes/next` o horário é obrigatório (célula sem `horario` → 422, ver US-02), então reuniões materializadas pelo endpoint sempre nascem com `hora` preenchida. A unicidade trata `hora` nula via `coalesce(hora, '')` no índice (já acordado). ESCOPO: os 4 valores de `status` (`planejada|confirmada|realizada|cancelada`) ficam no CHECK para evitar migration futura, mas a TRANSIÇÃO de status está FORA do PR2 — aqui só se implementa a materialização em `planejada`; nenhum endpoint do PR2 muda o status (confirmar/realizar/cancelar chegam em PRs seguintes).
- **RF-20** (US-11) — Índices de `celula_reuniao` por `igreja_id`, por `(igreja_id, celula_id)` e por `(igreja_id, celula_id, data)`.
- **RF-21** (US-11) — Criar `celula_presenca` escopada por `igreja_id`, com FKs para reunião e pessoa e `UNIQUE(igreja_id, reuniao_id, pessoa_id)`. Modelo de presença fechado por DEC-01 = SPEC §8.2: coluna `estado text` restrita ao conjunto `confirmada|compareceu|ausente` (CHECK, estilo constantes string de `events.py`) + coluna `origem text` (rastreia como/por quem foi registrada). NÃO é `presente boolean`.
- **RF-22** (US-11) — Criar `celula_expectativa_visitante` escopada por `igreja_id`, com `reuniao_id` + `pessoa_id` + dado do visitante, permitindo múltiplas linhas por membro/reunião. Modelo fechado por DEC-02 = SPEC §8.3 / US-PR2-05: visitante NOMINAL — coluna `nome_visitante text NOT NULL` + coluna `observacao_oracao text` (opcional). NÃO é por contagem (`quantidade`).
- **RF-23** (US-11) — Nas 3 tabelas: `enable row level security` + policy `tenant_isolation` (`using (igreja_id = current_igreja_id())` e `with check (...)`), no padrão da migration do PR1 e de `agenda_alert_recipients`.
- **RF-24** (US-11) — Migration aditiva idempotente e transacional por timestamp `AAAAMMDD_HHMMSS_slug.sql`; não altera `celulas`/`pessoas`/`multiplicacoes` nem remove `set_tenant_context`/BYPASSRLS.
- **RF-25** (US-11) — Modelos SQLAlchemy correspondentes em `app/db/models.py` seguindo o estilo de `Celula`/`CelulaMembro` (mapped_column, server_default, timestamps).
- **RF-26** (US-11) — Todo endpoint chama `ensure_tenant_context` no topo e evita leitura RLS-dependente após commit (preferir flush + refresh + commit único), conforme contrato de `_common.py`.
- **RF-27** (US-08) — Referências a Pessoa/Célula/Reunião são validadas explicitamente por tenant (a FK do Postgres não é RLS-scoped), reusando/estendendo o padrão `_assert_pessoa_tenant`.

### Domínio E — Testes

- **RF-28** (US-12) — Testes de modelo/schema em `backend/tests/test_celulas_pr2_models.py`: presença de colunas, unicidades, índices e policies das 3 tabelas.
- **RF-29** (US-12) — Testes de endpoint em `backend/tests/test_cell_meetings.py` no padrão fake-session que espelha predicados WHERE, cobrindo os cenários das US-01 a US-10.
- **RF-30** (US-12) — Os testes rodam da raiz do repositório sem `cd` e mantêm verde a suíte pré-existente do PR1.

---

## 3. Requisitos Não-Funcionais (RNF)

### Segurança / Multi-tenant

- **RNF-01** — Isolamento por tenant obrigatório: RLS ativa nas 3 tabelas com policy `tenant_isolation` (USING + WITH CHECK via `current_igreja_id()`), e nenhuma query retorna dados de `igreja_id` diferente do usuário autenticado. Verificável por teste de tenant cruzado (reunião/pessoa de outra igreja → 404/422).
- **RNF-02** — Não remover nem contornar `set_tenant_context` (`SET LOCAL ROLE authenticated`); nada do PR2 roda em worker (onde a RLS fica desligada). Toda operação passa por `ensure_tenant_context`.
- **RNF-03** — Autorização revalidada em cada endpoint por papel + vínculo (`has_any_role`, `is_leader_or_superior`, `celula_membro.ativo`), sem confiar em dados do cliente para elevar privilégio.
- **RNF-04** — Defesa em profundidade: além da RLS, filtrar explicitamente por `igreja_id` nas queries de listagem/lookup (como em `list_cell_members`), tornando o isolamento testável no harness fake.

### Confiabilidade / Integridade

- **RNF-05** — Idempotência garantida em banco por restrições UNIQUE (`celula_reuniao(celula_id, data)` e `celula_presenca(igreja_id, reuniao_id, pessoa_id)`); corridas resultam em `IntegrityError` tratado, nunca em duplicata ou HTTP 500.
- **RNF-06** — Migration idempotente e transacional (reaplicável sem erro), aditiva, sem efeito destrutivo sobre PR1; aplicada em DEV antes de PROD.
- **RNF-07** — Geração da próxima reunião determinística (helper de data injetável), sem dependência de relógio externo não controlado nos testes.

### Performance

- **RNF-08** — Consultas de reunião suportadas por índices `(igreja_id)`, `(igreja_id, celula_id)` e `(igreja_id, celula_id, data)`; lookups de vínculo usam os índices existentes de `celula_membro`.
- **RNF-09** — Endpoint de listagem responde em lote único coerente com o contrato de paginação de `_common.py` (cap `MAX_PAGE_SIZE = 200`) quando aplicável.

### Manutenibilidade / Consistência

- **RNF-10** — Código do PR2 segue os patterns de `cells.py`/`_common.py` (naming camelCase no contrato externo, `from_model`, helpers de tenant, status como constantes string no estilo de `events.py`), sem introduzir novas tecnologias além de FastAPI/SQLAlchemy/Pydantic já usadas.
- **RNF-11** — Nunca alterar o código-fonte do LionClaw (`.lionclaw/...`); PR2 é backend-only e não inclui frontend.
- **RNF-12** — Mudanças estruturais (3 tabelas novas) registradas na documentação do pipeline (`docs/Docs<id>/`) conforme regra 2 do CLAUDE.md.

### Usabilidade de API (contrato)

- **RNF-13** — Erros usam os códigos HTTP consistentes com o repositório: 404 (célula/reunião não encontrada no tenant), 422 (dados insuficientes/parser desconhecido/pessoa de outro tenant/payload inválido), 403 (sem permissão). A presença é idempotente e retorna 200 mesmo em remarcação/corrida (NÃO usa 409). O 409 permanece reservado a conflitos de estado de outros fluxos (ex.: `add_cell_member`), não à presença do PR2.

---

## 4. Decisões fechadas (antes em aberto)

Os dois pontos abaixo divergiam entre a SPEC canônica e o resumo do dono. Ambos foram FECHADOS na validação em favor da SPEC.

- **DEC-01 — Modelo de PRESENÇA. FECHADO = SPEC §8.2.**
  - Decisão: coluna `estado text` (`confirmada|compareceu|ausente`, via CHECK) + coluna `origem text`. NÃO é `presente boolean`.
  - Reflexo: RF-21 (schema), US-05 (grava estado/origem, default `confirmada`), payloads de presença (RF-09..RF-14) e testes.

- **DEC-02 — Modelo de EXPECTATIVA DE VISITANTE. FECHADO = SPEC §8.3 / US-PR2-05.**
  - Decisão: visitante NOMINAL — `nome_visitante text NOT NULL` + `observacao_oracao text` (opcional), N por membro/reunião. NÃO é por contagem (`quantidade`).
  - Reflexo: RF-22 (schema), RF-17 e US-10 (validação: nome obrigatório, observação opcional), `POST .../expectativas-visitantes` (RF-15) e testes.
