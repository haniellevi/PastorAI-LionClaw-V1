# AGENDA / EVT-8 — Notificação por evento na confirmação

**Status:** spec (PR0, docs-only) · **Data:** 2026-07-06 · **Escopo:** captura + persistência da intenção + modal + resolver read-only. **Envio real fica fora (EVT-9).**

## 1. Objetivo

Ao **confirmar** um evento da Agenda, permitir configurar a **notificação daquele evento**:

1. **Quando** notificar — X horas/dias antes, ou data/hora específica anterior ao evento.
2. **Quem (individual)** — contatos/pessoas que já conversaram com o WhatsApp da igreja (sem digitar telefone livre).
3. **Quem (coletivo)** — igreja inteira, pastores, G12 pastoral, líderes de célula.
4. **Canal** — WhatsApp (padrão). **Nada é enviado nesta missão.**

## 2. Estado atual (verificado)

EVT-8a (PR #87, `71f23a2`) já está em `main`:

- Colunas em `events`: `publico_alvo text[]`, `antecedencia_horas integer`, `mensagem_confirmacao text` — criadas na migration EVT-1 `20260629_222635` (`backend/migrations/…evt1…sql:65-67`), model em `backend/app/db/models.py:1107-1109`.
- `ConfirmEventRequest` (`backend/app/routers/events.py:182-219`) valida e `confirm_event` (`events.py:372-424`) **persiste** os 3 campos quando vem body. Gate `require_role(["pastor"])`, 409 se não `a_confirmar`.

**Achado crítico:** essas 3 colunas são **gravadas mas nunca lidas**. O único caminho de notificação hoje é `notify_event_confirmed()` (`backend/app/services/event_notify.py`), que é o **aviso interno EVT-7** (§3) — não usa `publico_alvo`, `antecedencia_horas` nem `mensagem_confirmacao`. E a taxonomia atual do `publico_alvo` (`toda_igreja, lideres, discipulos, visitantes, casais, jovens, criancas`) **não corresponde** aos grupos desta missão.

Infra reutilizável: `backend/app/workers/cron_worker.py` já tem loop + tabela `crons`; hoje só executa ação de SLA (outras ações são ignoradas). Serve de base para o cron de envio do EVT-9.

PR #88 (EVT-8b, `ConfirmEventModal` frontend) foi **fechado sem merge**; o modal não está em `main`. Aproveita-se o layout, não a taxonomia (que muda aqui).

## 3. EVT-7 `agenda_alert_recipients` ≠ EVT-8 público do evento

São **dois fluxos distintos que nunca se cruzam**:

| | EVT-7 PR2 — `agenda_alert_recipients` | EVT-8 — público do evento |
|---|---|---|
| Granularidade | **Global da igreja** (uma lista para toda a Agenda) | **Por evento** |
| Propósito | Aviso **interno da equipe**: "evento X foi confirmado" | Comunicação ao **público participante** |
| Origem dos telefones | Lista fixa opt-in (`calendar.py:422-622`, admin-only) | Grupos derivados + seleção individual dinâmica |
| Cobre grupos/individual? | Não | Sim (toda_igreja / pastores / g12_pastoral / lideres_celula + individual) |
| Model/migration | `models.py:1159`, `20260701_193000` | evolui `events` (§5) |

**Não reutilizar** `agenda_alert_recipients` como público do EVT-8. Faz sentido apenas como **fallback interno futuro** (meta-aviso à equipe de que a comunicação ao público saiu) — nunca como destino principal.

## 4. Decisões (D1–D7, fechadas pelo dono)

- **D1 — Taxonomia (reestruturar).** Contrato coletivo do MVP EVT-8: `toda_igreja`, `pastores`, `g12_pastoral`, `lideres_celula`. Mais uma **seleção individual separada**. Os valores antigos (`discipulos`, `visitantes`, `casais`, `jovens`, `criancas`) **saem do MVP** — podem voltar depois como segmentações.
- **D2 — G12 pastoral.** No MVP, `g12_pastoral` = pessoas/usuários com papel `lider_g12` na igreja. Refinamento futuro vira regra/schema próprio.
- **D3 — Individual.** Baseado em quem já conversou no WhatsApp da igreja. Fonte: `Conversation` por `igreja_id`. Persistir de forma estável: **preferir `pessoa_id`** quando existir; **`telefone` de `Conversation` como fallback** quando não há pessoa vinculada. **Sem digitação livre de telefone.**
- **D4 — Quando.** UI suporta os dois modelos (X horas/dias antes **e** data/hora específica). Backend **normaliza para `notificar_em` (`timestamptz`)** no evento. `antecedencia_horas` permanece por compatibilidade/entrada relativa, mas o cron (EVT-9) usa `notificar_em`.
- **D5 — Líder de célula canônico.** Fonte = `Celula.lider_id` de **célula ativa**. **Não** usar `CelulaMembro.papel='lider'` (identificado como conceito errado/bug).
- **D6 — Canal.** MVP assume `canal='whatsapp'` como padrão. Prever na spec, sem implementar múltiplos canais. **Não enviar WhatsApp real.**
- **D7 — Escopo.** EVT-8 = captura + persistência da intenção + modal/frontend + resolver read-only. Envio real, cron/worker de envio e qualquer flag de envio ficam em **EVT-9** (nova autorização). Nesta missão: nenhuma flag de envio ligada, nenhum WhatsApp, nenhum `.env` alterado, nenhum deploy sem autorização.

## 5. Modelo de dados / migrations previstas

Objetivo do schema: guardar a **intenção** (quem/quando/mensagem/canal) de forma que o cron do EVT-9 consiga resolver e disparar depois. Persistência transacional no `confirm`.

Alterações previstas em `events` (migration SQL manual, nome por timestamp — ver `backend/migrations/README.md`):

- `notificar_em timestamptz NULL` — instante normalizado do disparo (D4). Fonte única para o cron.
- `notificacao_enviada_em timestamptz NULL` — idempotência do envio agendado (distinto de `notificado_em`, que é do aviso EVT-7).
- `canal text NULL` (default lógico `whatsapp`) — D6.
- **Público coletivo:** manter `publico_alvo text[]`, porém com a **nova allowlist** (`toda_igreja | pastores | g12_pastoral | lideres_celula`). Validação continua no Pydantic; avaliar CHECK no banco.

**Seleção individual (D3)** — decisão de forma na PR1, duas opções a detalhar:
- (a) tabela filha `event_notify_targets (id, event_id, igreja_id, pessoa_id NULL, telefone NULL, created_at)` com RLS por tenant — normalizado, fácil de resolver/deduplicar; **recomendado**.
- (b) coluna JSONB em `events` com `[{pessoa_id?, telefone?}]` — menos peças, porém sem FK/índice.

`antecedencia_horas` e `mensagem_confirmacao` permanecem (já existem). Nada é removido.

> Migrations criadas mas **não aplicadas** nesta missão sem autorização (aplicação manual no Supabase DEV→PROD, em ordem de nome).

## 6. Plano de PRs

| PR | Escopo | Migration | Worker | Front |
|---|---|:---:|:---:|:---:|
| **PR0** (este) | Spec docs-only: decisões D1–D7, delimitação EVT-7×EVT-8, plano, riscos | — | — | — |
| **PR1 — schema + confirm** | Nova taxonomia; storage individual (§5); `notificar_em` + `notificacao_enviada_em` + `canal`; `ConfirmEventRequest`/persist acompanham; testes backend | **SIM** (SQL manual) | — | — |
| **PR2 — resolver (read-only)** | Serviço `público/individual → telefones`, tenant-scoped, opt-out, dedup. **Não envia.** Unit tests com fixtures | — | — | — |
| **PR3 — modal** | `ConfirmEventModal`: quando (relativo + específico) + coletivo + picker individual (contatos WhatsApp) + mensagem; `confirmEvent(body)`; `events-api.ts` tipos | — | — | **SIM** |
| **PR4 — cron + envio (EVT-9, fora desta missão)** | Handler `agenda_notify` no `cron_worker` varre `notificar_em`, resolve (PR2) e envia via Evolution, **gated por flag** | — | **SIM** | — |

Ordem: PR1 → PR2 → PR3 fecham a captura da intenção ponta-a-ponta (sem enviar). PR4/EVT-9 é fase separada com autorização própria.

## 7. Riscos

- **RLS / multi-tenant.** Toda query do resolver (pastores, G12, líderes, individual) **precisa** `WHERE igreja_id` e `SET LOCAL ROLE authenticated` — o role de conexão do Supabase tem **BYPASSRLS** (ver `backend/app/db/rls.py` e CLAUDE.md). Query de público sem tenant vaza destinatários entre igrejas.
- **LGPD / opt-out.** `Pessoa.optout` existe, mas nenhuma query filtra hoje. O resolver (PR2) **deve** excluir opt-out antes de compor a lista. Sem isso, comunicação a quem pediu para não receber.
- **Ilusão de "pronto".** Os campos EVT-8a já existem e serão gravados, mas **só o EVT-9 envia**. Documentar na UI que o disparo automático ainda não está ativo (evitar promessa do rótulo "e agendar").
- **`publico_alvo` sem CHECK.** `text[]` aceita array malformado em POST direto (sem modal). Manter validação Pydantic; avaliar CHECK no banco.
- **Individual sem pessoa.** `Conversation.pessoa_id` é nullable — o storage individual (D3) precisa aceitar telefone puro como fallback, e o resolver deduplicar pessoa↔telefone.
- **`Conversation.telefone`** já é normalizado no ingest; o resolver deve reusar a mesma normalização para deduplicar contra pessoas.

## 8. Fora de escopo (EVT-8)

- Envio real (WhatsApp/Evolution), cron de disparo, qualquer flag de envio ligada → **EVT-9**.
- "Sugerir mensagem com IA" (§5.4 do protótipo antigo) → EVT-8c (futuro).
- Segmentações antigas (`discipulos/visitantes/casais/jovens/criancas`) → futuro.
- Múltiplos canais (SMS/e-mail) → futuro.
