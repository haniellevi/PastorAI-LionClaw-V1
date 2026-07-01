# Agenda de Eventos — EVT-7 PR2: fonte de telefone / destinatários de alerta

**Status:** auditoria read-only concluída · decisão de PR2 recomendada · **Data:** 2026-07-01
**Base analisada:** `origin/main` SHA `21bc8cf` (Merge PR #79 — EVT-7 PR1 aviso na confirmação).
**Origem:** auditoria read-only da fonte de telefone da equipe interna (models, roles, auth/ativação, SLA, Clerk, LGPD) com verificação por dado real no DEV e fan-out de leitura.
**Escopo deste documento:** **docs-only.** Não contém código, migration, env, worker nem deploy. É um contrato de decisão (regra de trabalho #2).
**Documento-pai:** [`AGENDA-EVENTOS-EVT0-decisao.md`](AGENDA-EVENTOS-EVT0-decisao.md) — fonte única do módulo Agenda.
**Documento-irmão:** [`AGENDA-EVENTOS-EVT7-auditoria-lembretes.md`](AGENDA-EVENTOS-EVT7-auditoria-lembretes.md) — auditoria que definiu o PR1 e deixou **aberto** o "Gate de destinatário" (§3). **Este documento resolve esse gate.**

> **Renumeração (para a história não virar ficção).** A auditoria-irmã chamou o lembrete semanal/cron de "PR2 futuro". Como a validação do PR1 em produção revelou `destinatarios=0` (aviso inerte), inserimos um **PR2 = destinatários** antes do cron. Logo, a partir daqui: **PR1** = aviso síncrono na confirmação (feito, em prod, flag off); **PR2** = configuração de destinatários de alerta (este documento); **PR3** = lembrete semanal/cron (o antigo "PR2 futuro").

---

## 1. Diagnóstico — verificado contra o código e por dado real (DEV)

### 1.1 Cadeia atual do destinatário

O aviso EVT-7 resolve **para quem enviar** e **por qual número** assim ([`event_notify.py`](../../backend/app/services/event_notify.py)):

```
UserRole.papel ∈ {pastor, lider_g12}        →  user_ids      (elo 1: PAPEL)
  → AppUser.pessoa_id      (nullable!)       →  pessoa        (elo 2: VÍNCULO)
    → Pessoa.telefone       (NOT NULL)                        (elo 3: telefone)
remetente: whatsapp_connections.instance     (nullable)       (elo 4: NÚMERO OFICIAL)
```

- Filtro de papel: `NOTIFY_ROLES = {pastor, lider_g12}` ([`event_notify.py:37`](../../backend/app/services/event_notify.py)).
- Telefone: `_team_phones` percorre `user_id → AppUser.pessoa_id → Pessoa.telefone`; se `pessoa_id is None`, **pula** ([`event_notify.py:42-63`](../../backend/app/services/event_notify.py)).
- Remetente: `_instance` lê `whatsapp_connections.instance` da igreja; sem número oficial → `None`.
- Sem instância **ou** sem telefones → `return False`, nada enviado ([`event_notify.py:113-117`](../../backend/app/services/event_notify.py)); `notificado_em` só é marcado após ≥1 envio.

### 1.2 Por que `destinatarios=0` (causa raiz = dupla exclusão)

`Pessoa.telefone` é **NOT NULL** ([`models.py:80`](../../backend/app/db/models.py)). Logo `destinatarios=0` **nunca** é "pessoa sem telefone" — é **falta de papel (elo 1)** ou **falta de vínculo `pessoa_id` (elo 2)**.

| # | Causa | Evidência |
|---|---|---|
| **C1 — papel** | `NOTIFY_ROLES` cobre só `pastor`/`lider_g12`. O **dono/1º admin** de uma igreja nasce **apenas** com papel `admin`, que **não está** no filtro. Se a igreja só tem `admin` (comum), 0 destinatários por definição. | dono criado com `papel="admin"` + `dono_id` em [`platform_admin.py:414-424`](../../backend/app/routers/platform_admin.py); enum de papéis de igreja = `{admin, pastor, lider_g12, lider_consol, lider_celula, lider_mult, membro}` (7) em [`0001_extensions_and_enums.sql:54`](../../backend/migrations/0001_extensions_and_enums.sql) — NOTIFY_ROLES cobre **2 de 7** |
| **C2 — vínculo `pessoa_id`** | Telefone só existe via `AppUser.pessoa_id`. O dono nasce `pessoa_id=NULL`. Convite de equipe nasce papel `membro` e `pessoa_id` só é preenchido se o convidado já era `Pessoa` (Parte A) ou se ativar com telefone (Parte B). **Não há endpoint** para ligar um usuário já ativo a uma `Pessoa` depois. | dono sem `pessoa_id` em [`platform_admin.py:414`](../../backend/app/routers/platform_admin.py); convite em [`team.py:431-455`](../../backend/app/routers/team.py) (Parte A seta `pessoa_id`; Parte B = `None` + papel `membro`); ativação Parte B em [`auth.py:313-357`](../../backend/app/routers/auth.py); `AppUser.pessoa_id` nullable, FK SET NULL em [`models.py:138-140`](../../backend/app/db/models.py) |
| **C3 — número oficial** | Sem `whatsapp_connections.instance` conectado, o aviso para antes de resolver destinatário (mesmo efeito prático). | gate em [`event_notify.py:113-117`](../../backend/app/services/event_notify.py) |

**Estado PROD observado (Estágio 1 risco-zero, 2026-07-01):** `destinatarios=0` nas duas igrejas — Filadélfia (reconectando/sem telefones da equipe = C1/C2), Fortaleza (sem instância = C3). Aviso **inerte** por falta de dado, não por bug.

### 1.3 DEV mascara o problema

O seed amarra **à mão** `app_user → pessoa → telefone` e concede `{admin, pastor}` ([`0005_seed.sql:60-83`](../../backend/migrations/0005_seed.sql)). Query read-only rodada no DEV (`Igreja12-dev`, SELECT-only): a igreja piloto tem `destinatarios_evt7 = 1`, mas `instance = null`. Ou seja, **o DEV só reproduz C3** — o gap real de onboarding (C1/C2) é invisível no seed. Não use o DEV como prova de que "há destinatário".

### 1.4 Fontes de telefone disponíveis (por que não há atalho)

| Fonte | Coluna | Natureza | Serve como destino? |
|---|---|---|---|
| Pessoa (staff) | `pessoas.telefone` (NOT NULL) | destino atual | Sim — mas depende de C1+C2 |
| Número oficial | `whatsapp_connections.numero`/`instance` ([`models.py:707-709`](../../backend/app/db/models.py)) | **remetente** | **Não** — é a linha de atendimento (enviar para si mesmo) |
| Conversa | `conversations.telefone` (NOT NULL) ([`models.py:277`](../../backend/app/db/models.py)) | telefone do **membro/contato** | **Não** — é o público, não a equipe |
| Clerk JWT | — | só `sub`/`email`/`nome` | **Não carrega telefone** ([`deps.py`](../../backend/app/deps.py) resolve só clerk_user_id/email/nome) |
| Igreja / agent_config / app_users | — | sem coluna de telefone | Não existe |
| Dono | `igrejas.dono_id → app_user → pessoa_id` | destino potencial | Só se `pessoa_id ≠ NULL` — **mesmo gap C2** (ver `_admin_phones` guardado em [`subscription.py:101-117`](../../backend/app/routers/subscription.py)) |

### 1.5 Paridade com o SLA

O motor de SLA usa a **mesma cadeia** (`UserRole → AppUser.pessoa_id → Pessoa.telefone`), **sem fallback** ([`sla_engine.py:167-197`](../../backend/app/services/sla_engine.py)). Herdaria o mesmo `destinatarios=0`. Nenhum envio interno funciona hoje em PROD por essa via — não é bug do EVT-7, é dado ausente compartilhado. **Uma config explícita de destinatários pode, no futuro, servir também o SLA.**

### 1.6 LGPD

- Membros/visitantes: `consentimento` + `optout` **são aplicados** no broadcast ([`broadcast.py:87`](../../backend/app/domain/broadcast.py)).
- `event_notify` **não** checa `optout`/`consentimento` ([`event_notify.py:42-63`](../../backend/app/services/event_notify.py)).
- O telefone da `Pessoa`-staff foi coletado tipicamente para **acompanhamento pastoral** — finalidade **divergente** de alerta operacional interno.
- Risco: com a flag ligada, um staff que também é `Pessoa` com `optout=true` receberia assim mesmo. Mitigação = destino cadastrado com **finalidade própria e opt-in** (ver §2).

---

## 2. Decisão recomendada — PR2 = configuração explícita de destinatários

**PR2 = "Quem recebe os avisos da Agenda", por igreja.** Uma configuração explícita de destinatário(s) de alerta, **independente de papel** (mata C1) e **independente de `pessoa_id`** (mata C2), **opt-in** com finalidade registrada (LGPD limpa). Serve o **PR1** (aviso síncrono) e o **PR3** (lembrete/cron) com a mesma fonte.

Por que é o menor caminho seguro:

- **Não depende de papel** — o dono/admin passa a poder receber sem entrar em `NOTIFY_ROLES`.
- **Não depende do vínculo `pessoa_id`** — não precisa mexer em onboarding nem em backfill.
- **Opt-in por construção** — o número é informado com finalidade "avisos operacionais da Agenda", resolvendo a divergência de finalidade da §1.6.
- **Fonte única** para PR1 e PR3 — o cron futuro lê a mesma tabela/coluna.

Mapa das alternativas de sequenciamento (pergunta do escopo): a escolha é **"criar config de equipe primeiro, cron depois"** — PR2 resolve os destinatários do PR1 **e** adia o cron para PR3.

---

## 3. Opções rejeitadas (e por quê)

- ❌ **Só incluir `admin` em `NOTIFY_ROLES`.** Resolve C1, deixa C2 (admin sem `pessoa_id` continua sem telefone) e amplia envio sem consentimento.
- ❌ **Backfill em massa de `pessoa_id`.** Mexe em dado real, arriscado, e vincula staff a `Pessoa`-membro (finalidade LGPD divergente). Fora de escopo.
- ❌ **Usar telefone de membros / `conversations.telefone`.** É o público, não a equipe; finalidade divergente + `optout` ignorado.
- ❌ **Usar o número oficial (`whatsapp_connections`) como destino.** É a linha de atendimento (remetente); mistura aviso interno ao inbox. A intenção é "origem apenas, não destino".
- ❌ **Buscar telefone no Clerk.** Não existe lá (JWT só traz `sub`/`email`).
- ❌ **Criar o cron/lembrete antes dos destinatários.** Sem "para quem", o cron só amplia envio inerte — ou pior, errado — em escala.

---

## 4. PR2 proposto (contrato — implementação em missão futura)

- **Dados/modelo (migration por timestamp):** destino(s) de alerta por igreja. Começar no menor honesto — **1 telefone de alerta por igreja** (coluna 1:1, opt-in + rótulo de finalidade) cobre o caso "avise o pastor/secretaria". Escalar para **N destinatários** (tabela dedicada, ex.: `agenda_notify_recipients(igreja_id, telefone, nome, ativo, created_at)`) se/quando o produto pedir. A migration entra no fluxo de nome por timestamp (helper `scripts/new_migration.py`), aplicada manualmente em ordem.
- **Endpoint admin-only:** CRUD/config do(s) destinatário(s), escopado por tenant (RLS por `igreja_id`), gate de papel `admin`.
- **UI simples:** em Configurações/Agenda **ou** no card de Planejamento — campo(s) de telefone com **texto de finalidade** (opt-in explícito).
- **`event_notify` lê essa configuração:** `_team_phones` passa a resolver os destinatários pela config. **Sem config → não envia** (não inventa destinatário; mantém a semântica atual de `return False`). Idempotência (`notificado_em`) e `outbound_guard` **inalterados**.
- **LGPD:** número cadastrado com finalidade "avisos operacionais da Agenda"; se o destino for uma `Pessoa`, respeitar `optout`.
- **Testes:** sem config → não envia; com 1 destino → envia 1×; idempotência (não reenvia); flag off → não envia; `outbound_guard` respeitado (fora de prod / sem `ALLOW_REAL_SENDS` → suprimido).
- **Flag continua off:** `AGENDA_NOTIFY_ENABLED` default `false` ([`config.py:46`](../../backend/app/config.py)). PR2 não liga nada.

---

## 5. Gates obrigatórios

1. **Migration aplicada no DEV antes do PROD** (ordem por nome; validar no `Igreja12-dev`).
2. **Sem envio real** durante a validação de código.
3. **Flag `AGENDA_NOTIFY_ENABLED` off por padrão** — PR2 não a liga.
4. **Validação com `external_sends` bloqueado** (guard suprime a rede em DEV/staging → `[SANDBOX]`; prova destinatário resolvido sem tocar rede). ⚠️ Em **produção** o guard fica **aberto** (`external_sends_enabled = is_production OR allow_real_sends`, ver auditoria-irmã §1.2) — em prod a única trava é **flag off + `destinatarios=0`**.
5. **Estágio 2 (envio real) só depois** de `destinatario ≥ 1` cadastrado **e** número oficial online (`instance ≠ NULL`), em **1 igreja piloto**, com decisão de negócio explícita.

---

## 6. Sequência segura

1. **Agora:** auditoria registrada (este doc + sprint + memória). Docs-only.
2. **PR2:** migration + endpoint admin-only + UI + `event_notify` lê config + testes. **Flag off.**
3. **Validar DEV:** aplicar migration DEV; cadastrar destino; flag on + `external_sends` off; confirmar evento descartável; log mostra destinatário resolvido sem rede; flag off.
4. **Deploy** backend+frontend (com migration). **Flag off.**
5. **Estágio 1 PROD** risco-zero repetido, agora com destino cadastrado (em prod o guard é aberto → manter **flag off**; provar `destinatarios≥1` por log/consulta, sem ligar a flag).
6. **Estágio 2** (decisão de negócio): 1 piloto, ligar a flag, 1 evento real, verificar entrega + idempotência, medir, então generalizar.
7. **PR3:** lembrete semanal/cron (timezone `America/Sao_Paulo`, dedup persistida por ocorrência, `set_tenant_context` por igreja, fonte = **mesma** config de destinatários).

---

## 7. Referências de código (base `21bc8cf`)

- [`backend/app/services/event_notify.py`](../../backend/app/services/event_notify.py) — `NOTIFY_ROLES:37`; `_team_phones:42-63`; flag `:104`; gate instância/telefones `:113-117`; marca `notificado_em:129-135`.
- [`backend/app/services/sla_engine.py`](../../backend/app/services/sla_engine.py) — cadeia idêntica sem fallback `:167-197`.
- [`backend/app/db/models.py`](../../backend/app/db/models.py) — `Pessoa.telefone` NOT NULL `:80`; `AppUser.pessoa_id` nullable FK SET NULL `:138-140`; `Conversation.telefone:277`; `WhatsappConnection.numero/instance:707-709`.
- [`backend/app/routers/platform_admin.py`](../../backend/app/routers/platform_admin.py) — dono nasce `papel="admin"` + `dono_id`, sem `pessoa_id` `:414-424`.
- [`backend/app/routers/team.py`](../../backend/app/routers/team.py) — convite cria `AppUser` (Parte A seta `pessoa_id` / Parte B `None`) + papel `membro` `:431-455`.
- [`backend/app/routers/auth.py`](../../backend/app/routers/auth.py) — `_complete_cadastro_pessoa` (Parte B, cria `Pessoa` tipo `membro`) `:313-357`.
- [`backend/app/routers/subscription.py`](../../backend/app/routers/subscription.py) — `_admin_phones` (mesma cadeia, guardada por `pessoa_id`) `:101-117`.
- [`backend/app/domain/broadcast.py`](../../backend/app/domain/broadcast.py) — `optout`/`consentimento` aplicados `:87`.
- [`backend/migrations/0001_extensions_and_enums.sql`](../../backend/migrations/0001_extensions_and_enums.sql) — `user_role_papel` (7 papéis de igreja) `:54`.
- [`backend/app/config.py`](../../backend/app/config.py) — `agenda_notify_enabled` default `false` `:46`; guard `external_sends_enabled`.
- [`backend/app/routers/events.py`](../../backend/app/routers/events.py) — `POST /events/{id}/confirm` chama `notify_event_confirmed` `:329`.

**Próxima missão (quando autorizada):** implementar o PR2 (config de destinatários, backend+frontend, atrás da flag off) conforme §4.
