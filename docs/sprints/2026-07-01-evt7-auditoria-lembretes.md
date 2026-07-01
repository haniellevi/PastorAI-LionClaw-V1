# EVT-7 — Auditoria de lembretes/planejamento da Agenda — 2026-07-01

**Branch:** `docs/evt7-auditoria-lembretes` · **Commits:** (ver PR) · **Deploy:** não (docs-only)

## O que foi feito
- Auditoria **read-only** do EVT-7 (lembrete/planejamento da Agenda) sobre `origin/main` `25f1a97`, cobrindo workers, senders, guard, config, models, frontend e docs, com verificação adversarial.
- Registrado o ADR de auditoria + decisão de PR mínimo em [`docs/design/AGENDA-EVENTOS-EVT7-auditoria-lembretes.md`](../design/AGENDA-EVENTOS-EVT7-auditoria-lembretes.md) (fonte única do EVT-7).

## Estado atual verificado (contra o código, não por memória)
- **`queue_worker` é inbound/reativo** — não serve para lembrete agendado (acionado por webhook, não por horário).
- **`cron_worker` existe, mas só executa SLA** — ações novas caem em `"no executable action handler; skipped"` ([cron_worker.py:116](../../backend/app/workers/cron_worker.py)). Não há agendador por data/hora absoluta; `_last_run` é in-process.
- **`outbound_guard` existe, mas em produção fica ABERTO** por `is_production=true` (`external_sends_enabled = is_production OR allow_real_sends`, [config.py:160](../../backend/app/config.py)). Protege staging, não prod.
- **Não existe flag própria** para reminders/notificações da Agenda (só a `ALLOW_REAL_SENDS` genérica).
- **Não existe timezone `America/Sao_Paulo`** configurado (backend é UTC; o único `America/Sao_Paulo` está no `GoogleCalendarClient` legado/inativo).
- **Colunas `publico_alvo`, `antecedencia_horas`, `mensagem_confirmacao` existem mas estão dormentes** — nenhum backend as escreve, nenhuma UI as coleta (verificado por grep; `EventFormModal` tem só 4 campos).
- **Aba "Planejamento" ainda não existe** no frontend (`CalendarioScreen.tsx`: 4 abas, sem "Planejamento").
- **Não existe idempotência persistida de envio** (dedup atual é só inbound/evento, no Redis/SLA).
- **O cron roda como `postgres`/BYPASSRLS** — handler futuro precisa setar `set_tenant_context` por igreja, senão vaza entre tenants.

## Decisões
- **PR1 mínimo = notificação síncrona no `POST /events/{id}/confirm`**, atrás de flag `AGENDA_NOTIFY_ENABLED=false`, **sem cron/worker novo**. Reusa `EvolutionClient` (já guardado) e o request (herda RLS/tenant).
  - **Destinatário inicial** = equipe interna da igreja (admin/pastor/dono). **Não** enviar a membros/visitantes nesta fase.
  - **Canal inicial** = WhatsApp via Evolution.
  - **Momento inicial** = imediatamente ao confirmar o evento.
  - **Gate aberto:** identificar fonte de telefone confiável da equipe interna (admin/pastor/dono são usuários Clerk, não `pessoas`) antes do envio.
- **PR2 futuro** = lembrete semanal/antecedência via `cron_worker`, com **tabela de dedup persistida**, **timezone `America/Sao_Paulo`**, **tenant context por igreja**, **opt-out/consentimento** e **restart explícito do `cron-worker`** no deploy.
- **O que NÃO fazer agora:** não criar worker novo; não usar `_last_run` como idempotência; não enviar evento `a_confirmar`; não ativar envio em prod sem flag própria; não implementar lembrete semanal antes do PR1; não assumir destinatários sem fonte de telefone confiável.

## Gates obrigatórios para o PR1 (registrados no ADR §6)
- Flag default-off; teste flag off não envia; teste flag on chama serviço mockado; teste de idempotência; teste não reenvia se já notificado; teste não envia evento `a_confirmar`; teste respeita `outbound_guard`; zero worker/env/deploy no PR; backend-only salvo docs.

## Pendente / próximo passo
- Confirmar com o usuário a **fonte de telefone** da equipe interna (bloqueia o envio do PR1, não o código do gate).
- Implementar o **PR1** (backend-only, atrás de flag) quando autorizado.
- **PR2** (cron/worker + dedup persistida + timezone) só depois do PR1 validado em prod.

## Verificação
- **Docs-only:** zero alteração em frontend, backend, migrations, env e scripts de deploy. `git diff --check` limpo.
- Sem deploy, sem migration, sem env, sem worker, sem envio de mensagem — nada tocado em produção (não aplicável a docs).
