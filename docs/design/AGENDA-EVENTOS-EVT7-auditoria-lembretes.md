# Agenda de Eventos — Auditoria EVT-7 (lembretes/planejamento) e decisão de PR mínimo

**Status:** auditoria concluída · decisão de PR1 recomendada · **Data:** 2026-07-01
**Base analisada:** `origin/main` SHA `25f1a97` (Merge PR #77 — EVT-6 import UI).
**Origem:** auditoria read-only EVT-7 (workers, senders, guard, config, models, frontend, docs) com verificação adversarial.
**Escopo deste documento:** **docs-only.** Não contém código, migration, env, worker nem deploy. É um contrato de decisão (regra de trabalho #2).
**Documento-pai:** [`AGENDA-EVENTOS-EVT0-decisao.md`](AGENDA-EVENTOS-EVT0-decisao.md) — fonte única do módulo Agenda (§4 e §9 delimitam o EVT-7).

> **Nota sobre a spec de produto.** A "Especificação UX/UI e Regras de Negócio v1.0" do Módulo Agenda é **referenciada** pelo ADR EVT-0, pelos deltas do PRD e pela migration EVT-1, mas **não está versionada no repositório**. Logo, os detalhes finos de destinatário, horário e canal do lembrete eram **doc silencioso**. Este documento **resolve esses pontos com decisão recomendada** (§3), a ser confirmada com o usuário antes de implementar.

---

## 1. Estado atual — verificado contra o código

Todos os itens abaixo foram verificados lendo o código na base `25f1a97` (não por memória).

### 1.1 Workers

- **`queue_worker.py` é inbound/reativo — não serve para lembrete agendado.** Drena webhooks de WhatsApp do Redis (`BRPOP` em `pastorai:webhooks`) → Postgres → agente. É acionado por evento externo, não por horário. É a única referência boa de dois padrões que o EVT-7 vai precisar: ativação de RLS por igreja (`set_tenant_context_for_igreja`, [queue_worker.py:128](../../backend/app/workers/queue_worker.py)) e envio real via `EvolutionClient().send_text` ([queue_worker.py:445](../../backend/app/workers/queue_worker.py)).
- **`cron_worker.py` existe, mas só executa SLA — ações novas são "skipped".** É o único motor de agendamento (tick a cada `cron_tick_seconds`, **default 300s**). Faz sweep de SLA + varre a tabela `crons`. Porém `run_due_crons` só despacha ação de SLA (`_is_sla_action`, [cron_worker.py:81](../../backend/app/workers/cron_worker.py)); **qualquer outra `acao` cai em `"has no executable action handler; skipped"`** ([cron_worker.py:116](../../backend/app/workers/cron_worker.py)). A infra de scheduling existe, mas está vazia de handlers de negócio além do SLA.
- **Não há agendador por data/hora absoluta.** `frequencia` só entende intervalos relativos ("a cada 5m/2h/1d/weekly"). O throttle de recorrência (`_last_run`) é **in-process, não persistido**: reiniciar o worker zera o mapa e re-dispara no 1º tick.

### 1.2 Guard de envio externo

- **`outbound_guard` existe (`external_sends_allowed`, [outbound_guard.py:24](../../backend/app/services/outbound_guard.py)), central na camada de serviço.** Cada método de envio (Evolution/Brevo/Asaas/LLM/Google) chama o guard no topo; se bloqueado, loga `[SANDBOX]` e retorna **sucesso simulado** sem tocar a rede.
- **⚠️ Em produção o guard fica ABERTO por `is_production=true`.** A regra é `external_sends_enabled = is_production OR allow_real_sends` ([config.py:160-169](../../backend/app/config.py)). Ele protege local/staging, **não** protege produção. **Não existe segunda trava por-feature.**

### 1.3 Config / flags / timezone

- **Não existe flag própria para reminders/notificações da Agenda.** Só há a `allow_real_sends` genérica (`ALLOW_REAL_SENDS`, default `False`, [config.py:39](../../backend/app/config.py)). Nada de `AGENDA_NOTIFY_ENABLED`/`AGENDA_REMINDERS_ENABLED`.
- **Não existe timezone configurado para `America/Sao_Paulo`.** O backend opera em UTC de ponta a ponta (`_now()` = UTC). O único `America/Sao_Paulo` do código está **hardcoded no `GoogleCalendarClient` legado/inativo** (não ligado ao `POST /events` desde EVT-6 PR6.0).

### 1.4 Modelos / tabelas

- **As colunas `publico_alvo`, `antecedencia_horas`, `mensagem_confirmacao` existem em `events`, mas estão dormentes** ([models.py:638-640](../../backend/app/db/models.py)). Criadas na migration EVT-1 ("só persistem, sem envio"). **Verificado por grep: nenhum código de backend as escreve e nenhuma UI as coleta** — o `EventFormModal` tem só 4 campos (título/data/hora/descrição) e a confirmação (`POST /events/{id}/confirm`) só troca o status, sem body. São campos órfãos aguardando o EVT-7.
- **Não existe idempotência persistida de envio.** Não há tabela de reminders/dispatch nem coluna "lembrete enviado". A dedup existente é toda de inbound/evento (Redis por `provider_message_id`; SLA por evento) — nenhuma garante que uma **mensagem outbound** não seja reenviada.
- **A tabela `crons` é genérica e não está ligada a `events`** (`nome/frequencia/gatilho_estado/acao/ativo`, [models.py:498-520](../../backend/app/db/models.py)); não tem `event_id` nem estado por ocorrência.

### 1.5 Multi-tenant / RLS no caminho do cron

- **O cron roda como role `postgres` (BYPASSRLS) e NÃO chama `set_tenant_context`** — isola tenant só por filtro manual `WHERE igreja_id`. Um handler futuro de lembrete **precisa** ativar `set_tenant_context_for_igreja` por igreja (padrão do `queue_worker`), senão vaza eventos entre igrejas.

### 1.6 Frontend

- **A aba "Planejamento" ainda não existe no frontend.** `CalendarioScreen.tsx` tem 4 abas (Semana/Mês/Ano/**A confirmar**); `type AgendaTab = EventView | "confirmar"`. Zero ocorrências de "Planejamento" em `frontend/src`. Nenhuma chamada de API de lembrete/planejamento.

---

## 2. Lacunas (resumo)

1. Nenhum código de lembrete/EVT-7 (grep = zero).
2. Nenhum agendador por data/hora absoluta.
3. Nenhuma idempotência persistida de envio.
4. Nenhum handler de ação "lembrete" no cron.
5. Nenhuma flag por-feature (guard aberto em prod).
6. Nenhum timezone `America/Sao_Paulo` configurado.
7. Dados de config do lembrete não são coletados (colunas dormentes + sem UI).
8. Aba "Planejamento" + contrato de API inexistentes.
9. RLS não ativada no caminho do cron.
10. Consentimento/opt-out (LGPD S10 do PRD) não amarrado ao envio.

---

## 3. Decisão recomendada — PR1 mínimo

**PR1 = notificação síncrona no `POST /events/{id}/confirm`.** Quando um evento é confirmado, envia **uma** notificação, sem worker/cron novo.

Por que é o menor PR seguro:

- **Síncrono no request** que já existe → herda RLS/tenant do usuário logado; sem BYPASSRLS do cron.
- **Sem scheduler, sem timezone, sem cron** (dispara no ato da confirmação).
- **Reusa o `EvolutionClient`** (já protegido pelo `outbound_guard`) — nenhum cliente novo.
- **Idempotência mínima:** uma marca "já notificado" por evento (a confirmação é one-shot). Só vira tabela de dispatch se o destinatário for multi-pessoa (aí vira PR2).
- **Atrás de flag `AGENDA_NOTIFY_ENABLED` (default `false`)** — a trava por-feature que o guard de prod não oferece.

Parâmetros recomendados (resolvendo o doc silencioso):

| Parâmetro | Decisão recomendada para o PR1 |
|---|---|
| **Destinatário** | **Equipe interna da igreja: admin / pastor / dono.** **Não** enviar a membros/visitantes nesta fase. |
| **Canal** | **WhatsApp via Evolution.** |
| **Momento** | **Imediatamente ao confirmar o evento.** |

> **Gate de destinatário (aberto):** admin/pastor/dono são usuários (Clerk), não contatos (`pessoas`). É preciso **identificar uma fonte de telefone confiável** para a equipe interna antes do envio — não assumir. Se não houver telefone confiável para admin/pastor/dono, o PR1 fica bloqueado nesse ponto até a fonte ser definida (regra: "não assumir destinatários sem fonte de telefone confiável").

---

## 4. PR2 futuro — lembrete semanal / com antecedência

Fica para depois do PR1 (é o caminho caro):

- Handler novo no `cron_worker` para varrer eventos com janela de lembrete devida.
- **Tabela de dedup persistida** (ex.: `event_reminder_sent`, unique parcial por `(igreja_id, event_id, ocorrencia_date)` — molde do índice EVT-6 [`20260701_014654`](../../backend/migrations/20260701_014654_evt6_google_event_dedup_index.sql)).
- **Timezone `America/Sao_Paulo`** explícito na conversão (data,hora)→instante UTC.
- **`set_tenant_context` por igreja** no worker.
- **Opt-out / consentimento (LGPD S10)** ao montar destinatários.
- **Restart explícito do container `cron-worker`** no deploy (o runbook de prod reinicia só o backend; sem reiniciar o cron, o handler novo não roda ou roda código antigo).

---

## 5. O que NÃO fazer agora

- ❌ **Não criar worker novo agora** (PR1 não precisa).
- ❌ **Não usar `_last_run` como idempotência** (in-process; some no restart → duplica).
- ❌ **Não enviar evento `a_confirmar`** (só `confirmado`; "só comunicado após confirmação").
- ❌ **Não ativar envio em prod sem flag própria** (guard de prod fica aberto).
- ❌ **Não implementar o lembrete semanal antes do PR1.**
- ❌ **Não assumir destinatários sem fonte de telefone confiável.**
- ❌ Não reusar o `GoogleCalendarClient` legado (token global, conta errada).
- ❌ Não bypassar o `outbound_guard`.

---

## 6. Gates obrigatórios para o PR1

Requisitos de código para o PR1 ser aceito:

1. **Flag `AGENDA_NOTIFY_ENABLED` default-off.**
2. **Teste: flag off → NÃO envia** (nenhuma chamada ao serviço de envio).
3. **Teste: flag on → chama o serviço mockado** (sem tocar rede real).
4. **Teste de idempotência** (marca "já notificado" gravada).
5. **Teste: NÃO reenvia se o evento já foi notificado.**
6. **Teste: NÃO envia evento `a_confirmar`.**
7. **Teste: respeita o `outbound_guard`** (fora de prod / sem `ALLOW_REAL_SENDS` → suprimido).
8. **Zero worker / env de produção / deploy no PR** (a flag é config declarada; nenhum worker novo).
9. **Backend-only**, salvo docs.

Gate de produto pendente (bloqueia o envio, não o código do gate): confirmar a **fonte de telefone** da equipe interna (§3).

---

## 7. Sequência segura dev → prod (para o PR1, quando implementado)

1. **DEV**: implementar atrás de flag off; `pytest` verde (todos os gates da §6). Migration da marca de idempotência aplicada em `Igreja12-dev`.
2. **DEV com envio simulado**: guard suprime (`[SANDBOX]`) → valida gate/idempotência sem rede.
3. **PROD shadow**: deploy backend com flag **off**; migration aplicada em prod; **zero envio**.
4. **PROD go-live**: ligar `AGENDA_NOTIFY_ENABLED=true` com um evento de teste real (número da própria igreja); verificar 1 envio + idempotência (confirmar de novo → não reenvia).
5. Só então planejar o PR2 (aí sim com **redeploy do `cron-worker`**).

---

## 8. Referências de código (base `25f1a97`)

- [`backend/app/workers/queue_worker.py`](../../backend/app/workers/queue_worker.py) — inbound WhatsApp; `set_tenant_context_for_igreja:128`; `send_text:445`.
- [`backend/app/workers/cron_worker.py`](../../backend/app/workers/cron_worker.py) — scheduler; `run_due_crons:88`; `_is_sla_action:81`; skip `:116`; `_last_run` in-process.
- [`backend/app/services/outbound_guard.py`](../../backend/app/services/outbound_guard.py) — guard B2 (`external_sends_allowed:24`).
- [`backend/app/config.py`](../../backend/app/config.py) — `allow_real_sends:39`; `external_sends_enabled:160`; `cron_tick_seconds:131`; sem timezone.
- [`backend/app/db/models.py`](../../backend/app/db/models.py) — `Event` colunas dormentes `:638-640`; `Cron` `:498-520`.
- [`backend/app/routers/events.py`](../../backend/app/routers/events.py) — CRUD + `POST /events/{id}/confirm` (ponto de gatilho do PR1).
- [`backend/migrations/20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql`](../../backend/migrations/20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql) — colunas de confirmação (dormentes).
- [`backend/migrations/20260701_014654_evt6_google_event_dedup_index.sql`](../../backend/migrations/20260701_014654_evt6_google_event_dedup_index.sql) — molde de índice único parcial (para a dedup do PR2).
- [`frontend/src/components/calendario/CalendarioScreen.tsx`](../../frontend/src/components/calendario/CalendarioScreen.tsx) — 4 abas, sem "Planejamento".

**Próxima missão (quando autorizada):** implementar o PR1 (notificação na confirmação, atrás de flag, backend-only) após confirmar a fonte de telefone da equipe interna.
