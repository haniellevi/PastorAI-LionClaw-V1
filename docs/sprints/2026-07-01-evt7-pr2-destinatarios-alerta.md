# EVT-7 PR2 — Auditoria da fonte de telefone / destinatários de alerta — 2026-07-01

**Branch:** `docs/evt7-pr2-destinatarios-alerta` · **Commits:** (ver PR) · **Deploy:** não (docs-only)

## O que foi feito
- Auditoria **read-only** da fonte de telefone da equipe interna do EVT-7, sobre `origin/main` `21bc8cf` (PR1 já em prod, flag off), cobrindo models/roles/auth-ativação/SLA/Clerk/LGPD, com fan-out de leitura e verificação por dado real no DEV (SELECT-only).
- Registrado o ADR de decisão em [`docs/design/AGENDA-EVENTOS-EVT7-destinatarios-alerta.md`](../design/AGENDA-EVENTOS-EVT7-destinatarios-alerta.md), que **resolve o "Gate de destinatário" deixado aberto** pela auditoria-irmã ([`AGENDA-EVENTOS-EVT7-auditoria-lembretes.md`](../design/AGENDA-EVENTOS-EVT7-auditoria-lembretes.md) §3).
- **Renumeração registrada:** PR1 = aviso síncrono (feito, prod, flag off); **PR2 = destinatários (esta auditoria)**; **PR3 = lembrete semanal/cron** (o antigo "PR2 futuro").

## Diagnóstico (verificado contra o código, não por memória)
- **Cadeia atual do destinatário:** `UserRole(pastor/lider_g12) → AppUser.pessoa_id → Pessoa.telefone`; remetente = `whatsapp_connections.instance`.
- **`Pessoa.telefone` é NOT NULL** ([models.py:80](../../backend/app/db/models.py)) → `destinatarios=0` **nunca** é "pessoa sem telefone"; vem de **falta de papel** ou **falta de vínculo `pessoa_id`**.
- **Causa raiz = dupla exclusão:**
  - **C1 (papel):** dono/1º admin nasce **só** como `admin` ([platform_admin.py:414-424](../../backend/app/routers/platform_admin.py)); `NOTIFY_ROLES = {pastor, lider_g12}` ([event_notify.py:37](../../backend/app/services/event_notify.py)) **exclui** admin (cobre 2 dos 7 papéis de igreja).
  - **C2 (vínculo):** `AppUser.pessoa_id` pode ser NULL; convite de equipe nasce papel `membro` e só ganharia papel/telefone depois ([team.py:431-455](../../backend/app/routers/team.py), [auth.py:313-357](../../backend/app/routers/auth.py)); **não há endpoint** para ligar usuário ativo a `Pessoa`.
  - **C3 (número oficial):** sem `whatsapp_connections.instance` o aviso para antes do destinatário.
- **DEV seed mascara o problema** — amarra `app_user → pessoa → telefone` à mão ([0005_seed.sql:60-83](../../backend/migrations/0005_seed.sql)); query DEV mostrou `destinatarios=1` mas `instance=null` (só reproduz C3).
- **Fontes alternativas não servem como destino:** `whatsapp_connections.numero/instance` é **remetente**; `conversations.telefone` é **membro/contato**; **Clerk não fornece telefone**; caminho `dono_id` esbarra no mesmo `pessoa_id` NULL.
- **Paridade SLA:** `sla_engine.py` usa a mesma cadeia sem fallback ([sla_engine.py:167-197](../../backend/app/services/sla_engine.py)) — herdaria o mesmo problema.
- **LGPD:** `event_notify` não checa `optout`/`consentimento`; telefone de `Pessoa`-staff foi coletado para acompanhamento pastoral (finalidade divergente de alerta operacional).

## Decisões
- **PR2 = configuração explícita de destinatários de alerta por igreja**, **independente de papel e de `pessoa_id`**, **opt-in** com finalidade clara. Serve **tanto o PR1 quanto o PR3**.
- **Cron/lembrete semanal vira PR3** (não PR2).
- **Opções rejeitadas:** só incluir `admin` em `NOTIFY_ROLES`; backfill em massa de `pessoa_id`; usar telefone de membros/`conversations`; usar número oficial como destino; buscar telefone no Clerk; criar cron antes de destinatários.
- **PR2 proposto:** migration para destino(s) por igreja (começar 1 telefone 1:1; escalar para N se pedir); endpoint admin-only; UI simples em Configurações/Agenda ou card de Planejamento; `event_notify` lê a config; **sem config → não envia**; testes (sem config / 1 destino / idempotência / flag off / guard); **flag continua off**.

## Gates obrigatórios (registrados no ADR §5)
- Migration no DEV antes do PROD; sem envio real na validação; `AGENDA_NOTIFY_ENABLED` off por padrão; validação com `external_sends` bloqueado (⚠️ em prod o guard é aberto — trava é flag off + `destinatarios=0`); Estágio 2 real só depois de `destinatario ≥ 1` **e** número oficial online, em 1 piloto.

## Pendente / próximo passo
- Implementar o **PR2** (backend + frontend, atrás da flag off) quando autorizado — ver ADR §4/§6.
- **PR3** (cron/lembrete: timezone `America/Sao_Paulo`, dedup persistida por ocorrência, `set_tenant_context` por igreja) só depois do PR2 validado.

## Verificação
- **Docs-only:** zero alteração em frontend, backend, migrations, env e scripts de deploy. `git diff --check` limpo.
- Sem deploy, sem migration, sem env, sem worker, sem envio de mensagem — nada tocado em PROD/DEV (a auditoria só fez SELECT read-only no DEV).
