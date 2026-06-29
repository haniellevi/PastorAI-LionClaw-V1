# Agenda de Eventos — Decisão técnica/produto (EVT-0)

**Status:** decidido · **Data:** 2026-06-29 · **Base analisada:** SHA `baeb26c`
**Origem:** auditoria E0 (read-only) + decisões com o usuário.
**Deltas no PRD:** delta-049, delta-050, delta-051 (`docs/Docs20260611_163530/PRD20260611_163530.md`).
**Spec de produto:** "Módulo Agenda de Eventos — Especificação UX/UI e Regras de Negócio" v1.0 (Igreja12, Área Igreja → Agenda).

Este documento é a **fonte única** da decisão do módulo Agenda de Eventos. Registra a divergência entre o
PRD/protótipo antigos e a spec nova, o escopo do MVP, o que fica fora, os riscos e o plano de PRs. Não contém
código; é um contrato de decisão (regra de trabalho #2 do projeto).

---

## 1. Contexto e divergência

A Agenda **não é greenfield**. A auditoria E0 (base `baeb26c`) encontrou um módulo "F1" já implementado e
funcionando:

- **Tabela `events`** (8 colunas: `id, igreja_id, titulo, data, hora(text), descricao, google_event_id, created_at`),
  com RLS por tenant (`0003_rls_policies.sql:48`).
- **Backend** `events.py`: `GET /events` (lista, sem gate de papel) e `POST /events`
  (`require_role(["pastor","lider_g12"])`, admin implícito). Sem PUT/DELETE/GET-by-id/confirm.
- **Sync Google = PUSH** (app→Google) na criação, best-effort (`events.py:114`).
- **Frontend** `CalendarioScreen.tsx`: tela real, **só visão mês**, **só criar+listar** (sem editar/excluir/detalhe,
  sem clicar-dia/clicar-evento).
- **OAuth Google por igreja** existe e é robusto (`calendar.py` + tabela `calendar_sync` 1:1, tokens cifrados),
  mas está **desconectado do push** (ver §5).

A **spec nova** define um módulo bem maior: 5 abas (Semana/Mês/Ano/A confirmar/Planejamento), status do evento,
recorrência por dia da semana, confirmação com público/antecedência/mensagem, import do Google como pendente,
"Células liberadas" e assistente de planejamento.

**Divergência com o PRD/protótipo:**

- PRD **RF-35** prevê visões **mês/semana/dia** — não as abas Semana/Mês/Ano + A confirmar + Planejamento.
- PRD entidade **`evento`** = `titulo/data/hora/descricao/google_event_id` — sem status/confirmação/recorrência/público.
- O **protótipo Igreja12** (`docs/design/Igreja12-Prototipo.standalone.html`, seção AGENDA) tem só um calendário
  **mensal simples** + "Próximos eventos" + badge "Google Calendar / Sincronizado". Não tem abas, "a confirmar",
  "Células liberadas" nem assistente.
- O contrato `RECONCILIACAO-igreja12.md` classifica o redesign como "reskin" e marca "planejar/realizar" como fora de escopo.

> **Paridade visual:** a spec nova **não tem protótipo** correspondente. A fidelidade visual das telas novas
> (abas, confirmação, planejamento) fica **pendente de design** — será resolvida tela a tela nas PRs de frontend
> (EVT-3/4/5), reusando os tokens de identidade Igreja12 já materializados no `globals.css` (teal `#0d9488`,
> petróleo `#0f3a36`, vermelho de alerta) e a paleta semântica da spec (Coral/Teal/Verde/Índigo/Âmbar; vermelho
> reservado a "a confirmar").

## 2. Decisão

**Honrar a spec nova das 5 abas.** O módulo Agenda passa a ser uma feature funcional (não reskin). Esta decisão é
uma mudança estrutural fora do PRD original → registrada via **delta-049/050/051** no PRD e neste documento
(regra #2: "o PRD não pode virar ficção").

Reuso: **estender a tabela `events` existente** (não criar tabela "eventos" paralela) e evoluir os endpoints/tela
atuais. Nada é regenerado do zero (regra #4).

## 3. Escopo do MVP — EVT-1..5

O MVP é **100% manual e local**, sem Google e sem envio real. Tudo testável sem tocar serviço externo.

Inclui:

- **CRUD manual** de eventos (criar, listar, editar, detalhe, excluir).
- **Visões Semana / Mês / Ano** lendo dados reais.
  - Semana = recorrência por **dia da semana** (evento "toda semana neste dia").
  - Mês / Ano = **data específica**.
- **Criar/editar/detalhe** via modal; clicar-dia → novo evento já contextualizado; clicar-evento → detalhe.
- **Status** `confirmado` / `a_confirmar` no modelo.
- **Aba "A confirmar"** (só Pastor/Admin) + marcação **⚠ vermelha** do evento pendente em todas as visões (informativa para todos).
- **Confirmação manual** pelo Pastor/Admin: define público + antecedência + mensagem e marca o evento como `confirmado`.
  No MVP isso **apenas persiste** esses campos e troca o status — **não dispara** WhatsApp/e-mail.

## 4. Fora do MVP (pós-EVT-5)

- **EVT-6 — Google import** (Google→app como `a_confirmar`). Depende do fix de token por igreja (§5).
- **EVT-7 — Planejamento/assistente + envios reais** (lembrete semanal automático, notificação na confirmação,
  envio com antecedência). Depende de worker novo + dedup persistido.
- **Envio real** de WhatsApp/e-mail (qualquer canal) — só a partir do EVT-7.
- **"Sugerir com IA"** da mensagem de confirmação — pode entrar no EVT-5 como geração local (guardada pelo outbound
  guard / sem envio) ou ficar para o EVT-7. Decisão fina na PR.
- **"Células liberadas"** em dia livre — acopla a Agenda ao domínio de células; decisão de produto adiada.
- **Assistente de onboarding** (agenda semanal base, "um dia de cada vez") — pós-MVP.

## 5. Risco Google: token global vs OAuth por igreja

**Achado (risco ALTO).** O cliente que escreve eventos (`GoogleCalendarClient`) usa **token/calendar GLOBAIS de
`settings`** (marcados "Legacy" em `config.py:111`) e **nunca** lê os tokens OAuth por igreja salvos em
`calendar_sync`. Consequência: conectar a agenda pelo card **não** faz os eventos irem para a agenda da igreja; ou
nada sincroniza (token global vazio) **ou tudo cai numa única conta global compartilhada entre tenants** — risco de
cruzamento de dados entre igrejas. A integração por igreja está **inerte** para escrita de eventos.

**Decisão.** **Não implementar nada de Google (push novo ou import) antes de corrigir o token por igreja.** O EVT-6
começa **obrigatoriamente** pelo fix: ligar a leitura/escrita de eventos ao `_valid_access_token` por igreja
(`calendar_sync`), nunca ao token global. O MVP (EVT-1..5) é totalmente manual e **não toca** Google, então não é
bloqueado por isso.

> O fix do token por igreja é um bug de multi-tenant independente da feature. Pode ser antecipado numa PR curta
> própria (fora do caminho do MVP) se houver risco operacional; caso contrário, é o primeiro passo do EVT-6.

## 6. Decisão: sem envio real no MVP

Nenhuma PR do MVP (EVT-1..5) dispara mensagem real (WhatsApp via Evolution, e-mail via Brevo). A confirmação só
persiste público/antecedência/mensagem e troca o status. O **outbound guard B2**
(`external_sends_allowed = is_production OR ALLOW_REAL_SENDS`, camada de serviço) **permanece** e deve cobrir
qualquer caminho novo que toque canal externo. Envio real só a partir do EVT-7, com dedup persistido (o cron usa
`last_run` em memória → reinício duplicaria envio).

## 7. Mapeamento de papéis

Papéis reais do sistema (enum `user_role_papel`): `admin, pastor, lider_g12, lider_consol, lider_celula,
lider_mult, operador, membro`. **Não existe "secretaria" nem "lider" genérico.** "DONO" é a coluna
`igrejas.dono_id` (não é papel; hoje só gateia Assinatura) — **não** se aplica à Agenda.

| Spec | Papel real | Pode |
|---|---|---|
| **Pastor / Admin** | `admin` (implícito) + `pastor` | Criar, editar, confirmar, configurar planejamento; ver abas "A confirmar" e "Planejamento". |
| **Líder e demais** | `lider_g12`, `lider_consol`, `lider_celula`, `lider_mult`, `operador`, `membro` | Apenas visualizar a agenda e ser notificado. Não confirmam nem configuram; não veem as abas administrativas. |

**Mudança de gate (EVT-2):** o `POST /events` hoje aceita `["pastor","lider_g12"]` — **líder cria**, o que diverge
da spec. No EVT-2, criar/editar/confirmar passa a `require_role(["pastor"])` (admin entra implícito); **`lider_g12`
sai** da criação/edição/confirmação. Visualização (GET) segue liberada ao tenant.

## 8. Regra de status do evento

- Evento **criado manualmente** nasce **`confirmado`**.
- Evento **importado do Google** nasce **`a_confirmar`** (a partir do EVT-6).
- **Antes do EVT-6**, eventos pendentes (`a_confirmar`) podem existir por **seed / teste / inserção técnica manual**
  para validar a UI da aba "A confirmar" e a marcação ⚠ — **nunca** por Google real. A confirmação manual
  (Pastor/Admin) os move para `confirmado`.

## 9. Plano de PRs

| PR | Escopo | Migration | Toca Google | Envia msg real |
|---|---|:---:|:---:|:---:|
| **EVT-0** | Esta decisão: ADR + anotação PRD/SPEC + sprint. Docs-only. | não | não | não |
| **EVT-1** | Schema: estende `events` (status/tipo/recorrência/origem + campos de confirmação) + enum + RLS + model + tests. | **sim** | não | não |
| **EVT-2** | API CRUD completo (GET-by-id, PUT, DELETE, POST confirm) + gate `["pastor"]` (remove `lider_g12`). | não | não | não |
| **EVT-3** | Frontend Semana/Mês/Ano read-only com dados reais + cor por tipo. | não | não | não |
| **EVT-4** | Criar/editar/detalhe (clicar-dia → novo, clicar-evento → detalhe, editar/excluir). | não | não | não |
| **EVT-5** | Aba "A confirmar" + ⚠ vermelho + confirmação manual (persiste público/antecedência/mensagem, **sem envio**). | só se faltar coluna | não | não |
| **EVT-6** ⚠ | Google import → entra `a_confirmar`. **Começa pelo fix do token por igreja.** | possível | **sim** | não |
| **EVT-7** ⚠ | Planejamento/assistente + envios reais (lembrete, notificação na confirmação, antecedência). | possível | possível | **sim** |

## 10. Gates de segurança

- **Nenhuma PR antes do EVT-6** pode tocar Google real (import ou push novo).
- **Nenhuma PR antes do EVT-7** pode disparar mensagem real (WhatsApp/e-mail).
- **Manter o outbound guard B2** ativo; qualquer caminho novo de canal externo passa por `external_sends_allowed`.
- **Migration só no EVT-1** (e, se necessário, EVT-5/6/7). Nome por timestamp (`scripts/new_migration.py`), aplicada
  manualmente no Supabase em ordem de nome.
- **Deploy de backend só depois da migration aplicada** no ambiente alvo.
- **Frontend e backend são deployáveis separadamente** quando a PR não cruza contrato de API (ex.: EVT-3/EVT-4 são
  front-only; EVT-1/EVT-2 são back-only).

## 11. Referências de código (estado atual, base `baeb26c`)

- `backend/app/routers/events.py` — GET/POST eventos, gate `["pastor","lider_g12"]`, push best-effort.
- `backend/app/services/google_calendar.py` — push-only; token global (Legacy).
- `backend/app/routers/calendar.py` + `backend/app/services/google_oauth.py` — OAuth por igreja (robusto).
- `backend/migrations/0002_schema_tables.sql:213` — DDL `events`.
- `backend/migrations/0003_rls_policies.sql:48` — RLS de `events` (tenant_isolation).
- `backend/app/services/outbound_guard.py` — guard B2.
- `backend/app/deps.py` — `require_role`/`require_owner`; enum de papéis.
- `frontend/src/components/calendario/CalendarioScreen.tsx` — tela mensal atual.
- `frontend/src/lib/events-api.ts` — `fetchEvents`/`createEvent`/`buildMonthGrid`.
- `frontend/src/lib/navigation.ts:50` — nav "Agenda" → `calendario`.

**Próxima missão:** EVT-1 (schema/migration/RLS/model/tests).
