# Plano de Remediação de Segurança — Seg-Igreja12

- **Data:** 2026-07-08
- **Projeto pipeline:** Seg-Igreja12 (LionCloud Security Audit Pipeline)
- **Base de código:** PastorAI (`main` @ `b188358`, C1/RLS já fechado)
- **Tipo deste documento:** fonte de verdade versionada do resultado do pipeline. **Docs-only — não implementa correção.**
- **Última atualização:** 2026-07-17 (REL-5, docs-only) — ALTO-004 foi revalidado contra o código atual (`origin/main` @ `fd651f9`) e contra evidência versionada de deploy. As demais classificações preservam a reconciliação anterior, detalhada em §2.4.
- **Atualização REL-5 (2026-07-17):** ALTO-004 passou de **PARCIAL** para **CONCLUÍDO + deployado**. PR#186 (`9284038`, merge `fd651f9`) fez o retrofit dos três métodos originais de verificação JWT para `verify_purpose_token`, preservando os contratos públicos. O deploy e a verificação de runtime estão registrados em `docs/sprints/2026-07-17-backend-release-fd651f9.md`.
- **Fontes:**
  - `.lionclaw/Security/SPECsecurity-20260707_180329.md` (SPEC consolidada, 21 findings)
  - `.lionclaw/Security/Security-20260707-1804-*.md` (relatórios por categoria: secrets, auth, isolation, duplication, logic, standards, owasp)
  - `docs/Docs20260707_180329/sprints20260707_180329.json` (plano de sprints do pipeline)
  - Relatório da Missão 7A (contenção ALTO-001)
  - Estado final da Missão 6/C1 (seam RLS/tenant-context)

> As fontes em `.lionclaw/` **não** são versionadas (o diretório está no `.gitignore`) e permanecem como referência local. Este documento é a cópia versionada e estável dessas conclusões. Nenhum valor de segredo foi copiado para cá (política de contenção).

---

## 1. Resumo executivo

O pipeline de segurança confirmou **21 findings** na auditoria consolidada e deduplicada do PastorAI:

| Severidade | Qtd | Esforço estimado (pipeline) |
|-----------|-----|------------------------------|
| CRÍTICO | 0 | — |
| ALTO | 5 | ~12 h |
| MÉDIO | 6 | ~15 h |
| BAIXO | 10 | ~25 h |
| **Total** | **21** | **~50–65 h** |

Pontos de partida já resolvidos (na autoria original, 2026-07-08):

- **ALTO-001 (Secrets)** foi tratado pela **Missão 7A** como **contenção/higiene local**. O snapshot do pipeline (2026-07-07 18:04) registrou credencial real (e-mail, nome completo e duas senhas em texto claro) nas linhas `:42`/`:50` dos `settings.local.json`. Na execução da 7A esses arquivos **já estavam com regra curinga** (`clerk users create *`), **sem `--password`**; restavam apenas IDs locais, que foram redigidos. **Nenhum arquivo estava rastreado pelo git nem foi ao remoto.** Valores omitidos deste documento por política. **Atualização 2026-07-16: a rotação da senha, então pendente, foi confirmada concluída em 2026-07-09 — ver Apêndice B.**
- **Missão 6/C1** (seam profundo de RLS/tenant-context) está **fechada e em produção** e é a **base para os itens de RLS** deste plano — especificamente o gate do SEC-5 (`FORCE ROW LEVEL SECURITY`), que só deve ser executado **depois** do C1 validado.

**Atualização REL-5 (2026-07-17):** dos 5 ALTO + 6 MÉDIO, **9 estão concluídos e deployados em produção** (ALTO-001, ALTO-002, ALTO-003, ALTO-004, ALTO-005, MEDIO-001, MEDIO-002, MEDIO-003 e MEDIO-006), **1 parcial** (MEDIO-004) e **1 pendente de fato** (MEDIO-005). Ver §2.4 para evidência item a item e §8 para o backlog real restante.

Este plano **não** implementa correções. Ele fixa: estado por severidade, ordem recomendada (SEC-0..7), riscos, gates por PR, dependências e decisões. A execução será feita depois, **um SEC por PR** (ou sub-PR pequeno), via Cloud Code com gates reais — **não** pelo LionCloud Coder.

---

## 2. Estado por severidade

Legenda de **status** (revalidada em 2026-07-17, ver §2.4): `CONCLUÍDO` (corrigido no código atual, com teste cobrindo o comportamento) · `PARCIAL` (mitigado em parte, ou corrigido em alguns dos arquivos citados mas não em todos) · `PENDENTE` (problema ainda presente como descrito). Arquivos citados como referência do finding — **não** editados aqui.

### 2.1 ALTO (5)

| ID | Título | Arquivos-chave | SEC | Status |
|----|--------|----------------|-----|--------|
| ALTO-001 | Credencial de usuário Clerk exposta em `settings.local.json` (e cópias em worktrees) | `.claude/settings.local.json` + 4 cópias em worktrees | SEC-0 | **CONCLUÍDO** (7A + rotação confirmada 2026-07-09) — ver §2.4 |
| ALTO-002 | Ausência de rate limiting nos endpoints de autenticação | `backend/app/routers/auth.py` (login/forgot/reset/activate/change) · `backend/app/main.py` | SEC-2 | **CONCLUÍDO** (PR#131 + PR#148) — ver §2.4 |
| ALTO-003 | Constante `CENTRAL_ROLES` redefinida em dois módulos (risco de drift de autorização) | `backend/app/deps.py`, `backend/app/routers/cells.py` | SEC-7 | **CONCLUÍDO + deployado** (PR#181, `70846d2`) — ver §2.4 |
| ALTO-004 | Métodos de verificação de JWT quase idênticos em `ClerkClient` | `backend/app/services/clerk.py` (verify session/reset/invite) | SEC-7 | **CONCLUÍDO + deployado** (PR#186, `fd651f9`) — ver §2.4 |
| ALTO-005 | Dispatch de SLA envia WhatsApp **antes** de persistir log de dedupe | `backend/app/services/sla_engine.py` | SEC-4 | **CONCLUÍDO** (PR#144) — ver §2.4 |

### 2.2 MÉDIO (6)

| ID | Título | Arquivos-chave | SEC | Status |
|----|--------|----------------|-----|--------|
| MEDIO-001 | Fallback de CORS para `["*"]` com `allow_credentials=True` | `backend/app/main.py`, `backend/app/config.py` | SEC-1 | **CONCLUÍDO** (PR#129) — ver §2.4 |
| MEDIO-002 | Sessão JWT stateless não invalidada após troca/reset de senha | `backend/app/services/clerk.py`, `backend/app/routers/auth.py`, `deps.py` | SEC-3 | **CONCLUÍDO** (PR#133) — ver §2.4 |
| MEDIO-003 | Token de reset de senha reutilizável (sem uso único) | `backend/app/services/clerk.py`, `backend/app/routers/auth.py` | SEC-3 | **CONCLUÍDO** (PR#135) — ver §2.4 |
| MEDIO-004 | Dedup canônica de telefone repetida em 4 locais (uma sem filtro de `igreja_id`) | `contacts.py`, `auth.py`, `queue_worker.py` → novo `domain/phone.py` | SEC-7 | **PARCIAL** — ver §2.4 |
| MEDIO-005 | Métodos de emissão de JWT quase idênticos em `ClerkClient` | `backend/app/services/clerk.py` (mint session/reset/invite) | SEC-7 | PENDENTE — ver §2.4 |
| MEDIO-006 | Approve de solicitação de célula sem lock → TOCTOU | `cell_requests.py`, `cell_requests_service.py` | SEC-4 | **CONCLUÍDO + deployado** — ver §2.4 |

### 2.3 BAIXO (10)

| ID | Título | Arquivos-chave | SEC | Status |
|----|--------|----------------|-----|--------|
| BAIXO-001 | Segredo de sessão reutiliza Clerk secret key e não é validado | `backend/app/config.py` | SEC-1 | PENDENTE |
| BAIXO-002 | RLS com `ENABLE` mas sem `FORCE ROW LEVEL SECURITY` | `backend/migrations/` (tabelas de tenant) | SEC-5 | PENDENTE (dep. C1) |
| BAIXO-003 | Montagem repetida do cliente HTTP autenticado do Clerk | `backend/app/services/clerk.py` | SEC-7 | PENDENTE |
| BAIXO-004 | `confirm_event` transita estado sem lock | `backend/app/routers/events.py` | SEC-4 | PENDENTE |
| BAIXO-005 | `notify_autoupgrade` envia WhatsApp antes de commitar idempotência | `backend/app/routers/subscription.py` | SEC-4 | PENDENTE |
| BAIXO-006 | `list_events` conta total materializando todos os IDs | `backend/app/routers/events.py` | SEC-7 | PENDENTE |
| BAIXO-007 | Router `platform_admin.py` com ~1754 linhas | `backend/app/routers/platform_admin.py` | SEC-7 | PENDENTE |
| BAIXO-008 | Múltiplas telas/módulos acima de 500 linhas | frontend `*Screen.tsx` / backend routers | SEC-7 | PENDENTE |
| BAIXO-009 | Módulo `models.py` único com ~1562 linhas | `backend/app/db/models.py` | SEC-7 | PENDENTE (opcional) |
| BAIXO-010 | JWT de sessão persistido em `localStorage` | `frontend/src/lib/auth-context.tsx`, `admin-auth-context.tsx` | SEC-6 | PENDENTE |

---

## 2.4 Reconciliação 2026-07-16 (missão SEC-PLAN-RECON-1) — evidência item a item

Revalidação docs-only: cada finding ALTO/MÉDIO foi conferido contra o **working tree atual**
(`origin/main` @ `82e1c6f`) e contra `backend/tests/` — nunca contra comentário, nome de commit
ou memória de conversa isoladamente. Onde há evidência de deploy, ela vem de doc versionado
(`docs/sprints/`), não de relato de chat. BAIXO não foi revisado nesta rodada (fora do escopo
da missão).

**ALTO-001 — Credencial Clerk exposta.** `CONCLUÍDO`. Confirmado agora neste worktree:
`.claude/settings.local.json` usa regra curinga `Bash(CLERK_MODE=agent clerk users create *)`
sem `--password`, sem e-mail em claro; `git ls-files` confirma que o arquivo nunca foi
rastreado. **Correção de precisão ao plano original:** a proteção **não** vem do `.gitignore`
versionado do repositório (ele não contém nenhum padrão para `.claude/`) — vem de configuração
git **global do dono** e de uma configuração de exclusão **local deste clone, não versionada**.
Isso funciona nesta máquina, mas não protege automaticamente um clone novo ou outra máquina do
time sem a mesma configuração — risco residual pequeno, mitigável adicionando os padrões
equivalentes ao `.gitignore` do repo (poucas linhas, sem efeito funcional). **Rotação da
senha:** `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md`
(seção "SEC-0 — CONCLUÍDO") registra a rotação como feita pelo responsável em 2026-07-09 —
ação humana fora do Clerk, não verificável por código nesta missão, mas é evidência
versionada (não memória de chat) de que o único item aberto do SEC-0 foi fechado.

**ALTO-002 — Rate limiting de auth.** `CONCLUÍDO`. `backend/app/services/rate_limit.py`
(`RateLimiter.enforce_ip`/`enforce_account`, chave de conta via SHA-256, fail-open se Redis
cair) é chamado nos 5 endpoints do finding em `backend/app/routers/auth.py` (`login`,
`forgot_password`, `reset_password`, `activate`, `change_password`) e depois estendido ao
`/admin/login` (PR#148). `backend/app/main.py` registra handler de `RateLimitExceeded` → 429 +
`Retry-After`. Testes: `backend/tests/test_rate_limit.py` (unitário + HTTP 429 real em
login/forgot-password/admin-login). Deploy do backend concluído conforme registro versionado
de release em `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md` (commit `a7a04c8`, que contém
`f9c8629`/PR#131) e reforço do admin em `docs/sprints/2026-07-11-deploy-m7b-sec-prod.md`
(commit `8cbf78f`).
Gap não-bloqueante: reset-password/activate/change-password não têm teste HTTP de 429 literal
(só o rate limiter compartilhado é testado exaustivamente) — cobertura de teste, não brecha.

**ALTO-003 — `CENTRAL_ROLES` duplicada.** `CONCLUÍDO + deployado` (atualizado 2026-07-16,
REL-3B). Confirmado por leitura do código em `70846d2`: `backend/app/routers/cells.py` não
define mais `CENTRAL_ROLES` localmente — importa de `backend/app/deps.py`
(`from app.deps import CENTRAL_ROLES, ...`), único ponto de definição
(`app/deps.py:37`, `CENTRAL_ROLES = ["pastor"]`); `backend/app/routers/cell_meetings.py`
também passou a importar direto de `app.deps` em vez de reexportar via `cells.py`. Commit
`55abfd6` (PR#181) — diff conferido: `git show 55abfd6` mostra só remoção da duplicata e troca
de import, **zero mudança de valor, rota, permissão ou migration**, exatamente como descrito na
mensagem do commit. Risco de drift de autorização entre os módulos eliminado — não resta mais
que um único lugar para definir a lista. **Deploy confirmado:** `55abfd6` é ancestral de
`70846d2` (`git log 82e1c6f..70846d2`), publicado em produção — ver
`docs/sprints/2026-07-16-backend-release-70846d2.md`.

**ALTO-004 — Verify JWT triplicado em `ClerkClient`.** `CONCLUÍDO + deployado` (atualizado
2026-07-17, REL-5). PR#182 criou `ClerkClient.verify_purpose_token` e migrou o state OAuth para
a política compartilhada. PR#186 (commit `9284038`, merge `fd651f9`) completou o retrofit:
`verify_session_token`, `verify_reset_token` e `verify_invite_token` agora delegam a
decodificação e validação de algoritmo, segredo, issuer, expiração e claims obrigatórias ao
mesmo helper, preservando as assinaturas e mensagens públicas de erro de cada fluxo. A checagem
de valor específica de cada token permanece local ao método. O novo teste
`backend/tests/test_clerk_jwt_policy.py` cobre roundtrip, expiração, issuer incorreto, claim
ausente e isolamento entre session, reset, invite e state. **Deploy confirmado:** `fd651f9` foi
publicado e a presença da política compartilhada foi verificada no runtime; ver
`docs/sprints/2026-07-17-backend-release-fd651f9.md`.

**ALTO-005 — SLA envia antes de logar dedupe.** `CONCLUÍDO`. `SlaEngine._dispatch`
(`backend/app/services/sla_engine.py:340-382`) chama `reserve_agent_event(...)` — que faz
`INSERT`+`flush`+**`commit`** em `backend/app/agent/masking.py:113-149` — e só envia
`self._evolution.send_text(...)` depois, com `if marker is None: return False` cortando o envio
se a reserva não foi obtida; `release_agent_event` desfaz em falha total de envio. Corrigido no
commit `eb5d637` (PR#144). Testes: `backend/tests/test_sla_engine.py` (`test_dispatch_loses_
concurrent_reservation_race_never_sends`, `test_dispatch_releases_marker_on_total_send_failure`),
16/16 passando. **Deploy confirmado:** `eb5d637` é ancestral de `8cbf78f`
(`docs/sprints/2026-07-11-deploy-m7b-sec-prod.md`), que foi de fato colocado em produção — o
fix já está ativo em PROD, não apenas mergeado.

**MEDIO-001 — CORS fallback `["*"]`.** `CONCLUÍDO`. `Settings.cors_origins`
(`backend/app/config.py:204-221`) monta origens só a partir de `frontend_url`/`app_base_url`,
sem `or ["*"]`; `assert_production_ready()` falha o boot em produção se qualquer origem não
passar em `_is_valid_production_origin()` (rejeita wildcard/loopback/não-https).
`backend/app/main.py` chama `assert_production_ready()` no `lifespan()` (fail-fast) e monta o
`CORSMiddleware` direto da property, sem fallback. Testes: `test_config_sec1.py::
test_cors_origins_never_wildcard` e `test_app_cors_middleware_uses_explicit_origins` (extrai o
middleware real e confere `"*" not in allow_origins`), 16/16 passando. Corrigido no commit
`0006e15` (PR#129), endurecido em `699d328`. **Deploy confirmado:** PR#129 (`48526b8`)
ancestral de `a7a04c8` (deploy 2026-07-09).

**MEDIO-002 — Sessão não invalida após troca de senha.** `CONCLUÍDO`. Coluna
`app_users.password_changed_at` (migration `20260708_160128_sec3a_...sql`) +
`_reject_session_predating_password_change` (`backend/app/deps.py:107-138`, tolerância de
5s, fail-closed se faltar `iat`), chamado tanto em `get_current_user` (linha 191) quanto em
`get_platform_admin` (linha 454) — cobre as duas pipelines de auth. `auth.py::
_mark_password_changed` grava o carimbo em `reset_password` e `change_password`. Testes:
`test_session_password_invalidation.py`, 12/12 passando, incluindo caso end-to-end via
`TestClient` em `/auth/me`. Corrigido no commit `2537068` (PR#133). **Deploy confirmado por
query read-only em PROD** (não por relato): `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md` seção
"1/4" — coluna `password_changed_at` confirmada existente em `app_users` no projeto Supabase
de produção.

**MEDIO-003 — Reset token reutilizável.** `CONCLUÍDO`. Tabela `password_reset_tokens`
(`jti` único, `used_at` nullable) + `reset_password` (`backend/app/routers/auth.py:328-352`)
faz `SELECT ... FOR UPDATE` pelo `jti`, rejeita se já usado/expirado/inexistente, e só marca
`used_at`+commit **antes** de chamar `clerk.set_user_password(...)`. Corrigido no commit
`a8cf030` (PR#135). Testes: `test_password_reset_single_use.py`, 11/11 passando, incluindo
`test_second_use_of_same_token_is_rejected`. **Deploy confirmado por query read-only em PROD:**
`docs/sprints/DEPLOY-HANDOFF-2026-07-09.md` seção "2/4" — tabela, colunas, índices e a
constraint `password_reset_tokens_jti_key` conferidos existentes em produção.

**MEDIO-004 — Dedup de telefone sem `igreja_id`.** `PARCIAL`. A normalização canônica **já
existe** (`backend/app/domain/phone.py`, criado antes deste plano, reusado em 8 arquivos) — a
parte de "unificar normalização" está resolvida. Mas a busca por telefone continua duplicada
em vários pontos, e os 2 apontados pelo finding original (`create_contact`/`update_contact` em
`backend/app/routers/contacts.py`) seguem **sem filtro explícito de `igreja_id`** na query, ao
contrário dos demais arquivos citados no plano, que já filtram. A proteção hoje é só a RLS
(`set_tenant_context`), testada de forma genérica em `test_rls_invariant.py` mas não neste
caminho HTTP específico — falta defesa em profundidade nesses 2 pontos. **Próxima missão
isolada:** 1 PR pequeno, sem migration — replicar nesses 2 pontos de `contacts.py` o mesmo
filtro de `igreja_id` já usado nos demais arquivos.

**MEDIO-005 — Mint JWT triplicado em `ClerkClient`.** `PENDENTE`. Os três métodos de emissão de
JWT (`_mint_session_token`/`mint_reset_token`/`mint_invite_token`) em
`backend/app/services/clerk.py` continuam montando o payload de forma independente, sem helper
comum. Evidência de que a duplicação tende a divergir sob pressão: um dos três já mudou de
assinatura isoladamente (SEC-3B) sem que os outros dois acompanhassem. **Próxima missão
isolada:** 1 PR pequeno — extrair um helper privado único de emissão, preservando as
assinaturas públicas atuais; teste de roundtrip por tipo.

**MEDIO-006 — Approve de solicitação de célula.** `CONCLUÍDO + deployado`. Há uma correção
relacionada a este finding mergeada em `origin/main` (PR#157, commit de merge `40f705a`), com
teste automatizado cobrindo o cenário do finding. `40f705a` é ancestral de `82e1c6f` (verificado
via `git merge-base`) — a correção está contida no código desse commit. Evidência versionada de
deploy: `docs/sprints/2026-07-16-backend-release-82e1c6f.md` registra que `82e1c6f` foi
publicado em produção (não apenas mergeado em `origin/main`). **Ressalva de precisão:** o
registro de deploy documenta checagem de runtime específica só para MSG-IDEMP-1, PIPE-1,
CONSOL-1 e SLA-ALIGN-1 — não para este finding. A classificação de MEDIO-006 como deployado se
apoia em (a) o código da correção estar contido no commit publicado e (b) esse commit ter
registro versionado de deploy; ancestralidade Git isolada, sem esse registro, não seria prova
suficiente de deploy. Sem pendência de código para este item.

---

## 3. Ordem recomendada de execução (SEC-0..7)

Cada SEC é **um PR separado** (ou sub-PR pequeno). A ordem prioriza: contenção → fundação de config → superfície de auth → concorrência → RLS → frontend → dívida. Correlações do pipeline anotadas onde importam.

### SEC-0 — Secrets / contenção · **CONCLUÍDO (Missão 7A + rotação 2026-07-09)**
- **Findings:** ALTO-001.
- **O que já foi feito:** arquivos atuais sem `--password`; IDs locais redigidos; confirmado não-rastreado/não-remoto (proteção real via configuração git local/global do dono — **não** via `.gitignore` versionado, ver §2.4). Rotação da senha no Clerk confirmada em `docs/sprints/DEPLOY-HANDOFF-2026-07-09.md`.
- **Pendente:** nenhum item de código ou operacional. Sugestão de baixo custo (não bloqueante): versionar os 2 padrões de `.claude/` no `.gitignore` do repo, para não depender de config local/global de cada máquina.

### SEC-1 — Config segura (fundação) · **CONCLUÍDO — PR#129, deployado em PROD 2026-07-09**
- **Findings:** BAIXO-001 (`SESSION_JWT_SECRET` dedicado + validado) e MEDIO-001 (CORS estrito, sem fallback `["*"]` com credenciais). *(pipeline: sprint-002)*
- **O que foi feito:** `assert_production_ready()` exige `SESSION_JWT_SECRET` (>=32 bytes) e origens CORS explícitas (`FRONTEND_URL`/`APP_BASE_URL`), com boot fail-fast; CORS nunca cai em `["*"]`. Ver evidência em §2.4 (MEDIO-001).

### SEC-2 — Rate limiting de auth · **CONCLUÍDO — PR#131+#148, deployado em PROD 2026-07-09/11**
- **Findings:** ALTO-002. *(pipeline: sprint-003)*
- **O que foi feito:** limiter por IP + por conta/e-mail em `login`/`forgot`/`reset`/`activate`/`change-password` e, depois, `/admin/login`; `429` + `Retry-After`, fail-open se Redis cair. Ver evidência em §2.4 (ALTO-002).

### SEC-3 — Invalidação de sessão + reset token de uso único · **CONCLUÍDO — PR#133+#135, deployado em PROD 2026-07-09**
- **Findings:** MEDIO-002 (invalidar sessão em troca/reset de senha) e MEDIO-003 (reset token `jti` uso único).
- **O que foi feito:** `password_changed_at` em `app_users` + rejeição de token pré-evento em `get_current_user`/`get_platform_admin`; `password_reset_tokens` com `jti` único + `SELECT FOR UPDATE` antes do Clerk. Ver evidência em §2.4 (MEDIO-002/003).
- **Nota histórica:** o resequenciamento opcional (ALTO-004/MEDIO-005 antes do SEC-3, para encolher o diff) não foi seguido. **Atualização 2026-07-17 (REL-5):** ALTO-004 foi concluído no PR#186 e publicado em `fd651f9`; MEDIO-005 (mint) segue pendente, sem mudança.

### SEC-4 — Idempotência / locks / TOCTOU · **ALTO-005 e MEDIO-006 concluídos+deployados**
- **Findings:** ALTO-005 (SLA: log de dedupe antes do envio) — **concluído, PR#144, deployado**; MEDIO-006 (approve de solicitação de célula) — **concluído, PR#157, deployado** (ver §2.4); BAIXO-004 (`confirm_event` com lock + unicidade) e BAIXO-005 (`notify_autoupgrade` idempotente) — **não revisados nesta reconciliação** (fora do escopo ALTO/MÉDIO da missão SEC-PLAN-RECON-1).
- **Pendente real:** nenhum item ALTO/MÉDIO deste bucket em aberto. Revisar BAIXO-004/005 fica para uma missão futura dedicada a BAIXO.

### SEC-5 — `FORCE ROW LEVEL SECURITY` · **somente depois do C1 validado**
- **Findings:** BAIXO-002.
- **O que muda:** migration `ALTER TABLE ... FORCE ROW LEVEL SECURITY` nas tabelas de tenant, tornando a RLS fail-closed também para o papel owner/de conexão.
- **Gate rígido:** só executar com o **C1/RLS seam fechado e validado** (feito) e após confirmar que fluxos legítimos cross-tenant (worker, platform_admin) usam `mark_cross_tenant`/service role. **DEV antes de PROD.** Ver riscos (§4) e rollback (§5).

### SEC-6 — Frontend token hardening
- **Findings:** BAIXO-010.
- **O que muda:** preferir cookie `HttpOnly`+`Secure`+`SameSite` como fonte primária da sessão; Bearer só em memória; CSP restritiva. Se manter `localStorage`, reduzir TTL + invalidação server-side (alinha com SEC-3).

### SEC-7 — Dívida técnica / dedups / refactors grandes · **ALTO-003 e ALTO-004 concluídos+deployados; MEDIO-004 parcial (risco de segurança real remanescente); MEDIO-005 pendente**
- **Findings:** ALTO-003, ALTO-004, MEDIO-004, MEDIO-005, BAIXO-003, BAIXO-006, BAIXO-007, BAIXO-008, BAIXO-009.
- **Nota de altitude (surfacing explícito):** ALTO-003 e ALTO-004 têm severidade **ALTA** por risco de *drift* (autorização divergente; endurecimento de JWT aplicado inconsistentemente), mas a correção é **dedup/refactor** — daí caírem no bucket SEC-7. **Atualizado 2026-07-17 (REL-5, §2.4):** ALTO-003 foi corrigido e deployado (PR#181, `70846d2`) e ALTO-004 foi concluído e deployado (PR#186, `fd651f9`), com os três métodos originais de verificação delegando à política JWT compartilhada.
- **MEDIO-004 é o único item deste bucket com risco de segurança concreto remanescente** (não apenas dívida): `create_contact`/`update_contact` em `contacts.py` buscam por telefone sem filtro explícito de `igreja_id`, dependendo só da RLS. Recomenda-se puxar esse fix isoladamente (~4 linhas, sem migration) antes dos demais itens deste bucket — ver §2.4.
- **Sub-divisão sugerida (cada um PR pequeno e isolado):**
  - **SEC-7a — dedups de segurança (pequenas):** ~~ALTO-003 (fonte única `CENTRAL_ROLES`)~~ **concluído+deployado**, ~~ALTO-004 (retrofit dos 3 métodos verify de `clerk.py`)~~ **concluído+deployado**, MEDIO-004 (filtro `igreja_id` explícito em `contacts.py`, parcial — priorizar), MEDIO-005 (helper único mint JWT, pendente), BAIXO-003 (helper único do HTTP client Clerk, não revisado nesta rodada).
  - **SEC-7b — performance/qualidade pontual:** BAIXO-006 (`count(*)` no banco, não revisado nesta rodada).
  - **SEC-7c — refactors estruturais grandes:** BAIXO-007 (dividir `platform_admin.py`), BAIXO-008 (telas/módulos >500 linhas), BAIXO-009 (dividir `models.py` — **opcional**) — nenhum revisado nesta rodada (fora do escopo ALTO/MÉDIO).

---

## 4. Riscos por etapa

| SEC | Risco principal | Mitigação |
|-----|-----------------|-----------|
| SEC-0 | Credencial já exposta em backup/OneDrive continuar válida | **Rotação da senha no Clerk** (senhas do snapshot = comprometidas) |
| SEC-1 | **CORS bloquear `app`/`admin`/`painel`** por origem faltando; boot de produção falhar por var ausente | Compor origens com todas as superfícies antes; testar preflight das 3 superfícies; validar `assert_production_ready` em DEV |
| SEC-2 | **Rate limit travar usuários legítimos** (NAT/compartilhamento de IP, retries) | Limites por conta + por IP calibrados; `Retry-After`; smoke com fluxo real de login antes de PROD |
| SEC-3 | **Sessão invalidar usuários inesperadamente** (todos deslogados, ou reset não invalidar) | Testar token pré/pós-evento; frontend tratar `401` com re-login; rollout com observação; rollback documentado |
| SEC-4 | Regressão de entrega (mensagem não sair) ou deadlock por lock | Testes de reentrega/rollback (zero duplicados) e de concorrência; lock de escopo mínimo |
| SEC-5 | **`FORCE RLS` "zerar" dados** na prática se policies/cross-tenant estiverem errados (queries legítimas passam a retornar vazio) | **Só após C1 validado**; validar policies das tabelas de tenant em DEV; confirmar `mark_cross_tenant`/service role nos fluxos worker/platform_admin; **DEV antes de PROD**; rollback = migration reversa (`NO FORCE`) |
| SEC-6 | Quebra de login/refresh nas superfícies ao migrar armazenamento de token | Testar login/logout/refresh em `app` e `admin`; migração incremental (cookie primário, Bearer em memória) |
| SEC-7 | **Refactors grandes perderem rastreabilidade** / mudança de contrato silenciosa | Refactor puramente estrutural; paths/contratos inalterados; testes existentes verdes; PRs pequenos por sub-recurso; **não** misturar com SEC-1..4 |

---

## 5. Gates obrigatórios por PR

Todo PR de remediação (SEC-1 em diante) deve passar, **antes do merge**:

1. **`pytest` backend** (dentro de `backend/`, venv ativo) — suíte completa verde.
2. **Testes-alvo** do finding — cada critério de aceite vira teste (ex.: `429` após exceder limite; token pré-evento rejeitado; zero mensagens duplicadas; concorrência serializada).
3. **Lint / typecheck / build** quando o PR **tocar frontend** (Next build + typecheck).
4. **`git diff --check`** — sem whitespace/conflito residual.
5. **Secret scan** — nenhum segredo/credencial no diff (grep por `--password`, chaves, tokens, e-mails reais).
6. **Smoke local** — exercitar o fluxo afetado no runtime real (login, CORS preflight, envio idempotente, etc.), não só testes.
7. **DEV antes de PROD quando houver migration** (SEC-3, SEC-5) — aplicar e validar no projeto Supabase DEV antes do projeto Supabase PROD.
8. **Rollback documentado** para itens que alteram **auth ou RLS** (SEC-1 fail-fast, SEC-2, SEC-3, SEC-5): passo de reversão explícito no PR (migration reversa / flag / revert), testado ou descrito.

---

## 6. Dependências

- **SEC-5 (FORCE RLS) depende do C1/RLS seam fechado** — pré-condição satisfeita (Missão 6/C1 em produção). Ainda assim, validar policies + cross-tenant em DEV antes de aplicar.
- **SEC-1 é fundação de SEC-3** — `SESSION_JWT_SECRET` dedicado e CORS estrito antes da invalidação de sessão/reset.
- **Atualização REL-5:** ALTO-004 foi concluído; MEDIO-005 (helper único de mint) segue como a pendência de JWT dentro do SEC-7a.
- **Refactors baixos não bloqueiam ALTO/MÉDIO** — SEC-7b/7c (BAIXO-006/007/008/009) podem esperar; não são gate de nada.
- **Não misturar SEC-1/2/3/4 com SEC-7** no mesmo PR — mudança de comportamento de segurança separada de refactor estrutural, para preservar rastreabilidade.

---

## 7. Decisões explícitas

1. **Não implementar os 21 findings em um PR único.** Cada SEC = um PR separado (ou sub-PR pequeno).
2. **Não misturar segurança com a Missão 6.** A base RLS do C1 é pré-requisito de SEC-5, mas a execução de segurança é trilha própria.
3. **Não usar o LionCloud Coder para executar a correção.** A execução será via **Cloud Code com gates reais** (§5).
4. **Cada SEC vira PR separado ou sub-PR pequeno**, com os gates obrigatórios aplicados.
5. **Rotação de credencial (SEC-0) é ação do dono no Clerk** — não pode ser feita por código. As senhas registradas no snapshot do pipeline foram tratadas como **comprometidas** e a rotação foi **confirmada concluída em 2026-07-09** (`docs/sprints/DEPLOY-HANDOFF-2026-07-09.md`, seção "SEC-0"). Registro histórico da orientação original:
   > **Ação recomendada ao dono:** no painel Clerk → usuário afetado → redefinir/rotacionar a senha (e revisar sessões ativas). Considerar as credenciais do snapshot inválidas. Como o repositório está sob OneDrive (sincronizado), revisar também backups/versões na nuvem. Valores omitidos deste documento por política de contenção.

---

## 8. Próximo passo recomendado

**Atualizado em 2026-07-17 (REL-5) — o `iniciar SEC-1` original já foi executado e superado.** SEC-0/1/2/3/4 estão concluídos e deployados (incluindo ALTO-005 e MEDIO-006). ALTO-003 e ALTO-004 também estão concluídos e deployados (PR#181/PR#186). O backlog real de segurança ALTO/MÉDIO que resta é:

1. **MEDIO-004 (prioridade dentro do SEC-7a):** PR pequeno e isolado adicionando filtro explícito de `igreja_id` nas 2 queries de dedupe por telefone em `backend/app/routers/contacts.py` (`create_contact`/`update_contact`) — único item ALTO/MÉDIO remanescente com risco de segurança concreto (não apenas dívida). Sem migration.
2. **SEC-7a restante (dedup, sem urgência de segurança ativa, mas recomendado cedo por risco de drift):** MEDIO-005 (helper único de mint JWT) — 1 PR pequeno e isolado, com teste de roundtrip.
3. BAIXO-001..010 não foram revisados nesta reconciliação (fora do escopo da missão SEC-PLAN-RECON-1) — permanecem como registrados em §2.3/§3, precisam de revalidação própria antes de qualquer PR.

---

## Apêndice A — Rastreabilidade finding → SEC

| Finding | Severidade | SEC | Status (2026-07-17, REL-5) | PR real / sugerido |
|---------|-----------|-----|----------------------|---------------------|
| ALTO-001 | ALTO | SEC-0 | CONCLUÍDO | 7A + rotação do dono (2026-07-09) |
| ALTO-002 | ALTO | SEC-2 | CONCLUÍDO + deployado | PR#131, PR#148 |
| ALTO-003 | ALTO | SEC-7a | CONCLUÍDO + deployado | PR#181 (deploy: `docs/sprints/2026-07-16-backend-release-70846d2.md`) |
| ALTO-004 | ALTO | SEC-7a | CONCLUÍDO + deployado | PR#186 (deploy: `docs/sprints/2026-07-17-backend-release-fd651f9.md`) |
| ALTO-005 | ALTO | SEC-4 | CONCLUÍDO + deployado | PR#144 |
| MEDIO-001 | MÉDIO | SEC-1 | CONCLUÍDO + deployado | PR#129 |
| MEDIO-002 | MÉDIO | SEC-3 | CONCLUÍDO + deployado | PR#133 |
| MEDIO-003 | MÉDIO | SEC-3 | CONCLUÍDO + deployado | PR#135 |
| MEDIO-004 | MÉDIO | SEC-7a | PARCIAL — priorizar | PR pequeno (filtro `igreja_id` em `contacts.py`) a abrir |
| MEDIO-005 | MÉDIO | SEC-7a | PENDENTE | PR pequeno (dedup) a abrir |
| MEDIO-006 | MÉDIO | SEC-4 | CONCLUÍDO + deployado | PR#157 (deploy: `docs/sprints/2026-07-16-backend-release-82e1c6f.md`) |
| BAIXO-001 | BAIXO | SEC-1 | não revisado nesta rodada | PR SEC-1 |
| BAIXO-002 | BAIXO | SEC-5 | não revisado nesta rodada | PR SEC-5 (dep. C1) |
| BAIXO-003 | BAIXO | SEC-7a | não revisado nesta rodada | PR pequeno (dedup) |
| BAIXO-004 | BAIXO | SEC-4 | não revisado nesta rodada | PR SEC-4 |
| BAIXO-005 | BAIXO | SEC-4 | não revisado nesta rodada | PR SEC-4 |
| BAIXO-006 | BAIXO | SEC-7b | não revisado nesta rodada | PR pequeno (perf) |
| BAIXO-007 | BAIXO | SEC-7c | não revisado nesta rodada | refactor estrutural |
| BAIXO-008 | BAIXO | SEC-7c | não revisado nesta rodada | refactor estrutural |
| BAIXO-009 | BAIXO | SEC-7c | não revisado nesta rodada | refactor estrutural (opcional) |
| BAIXO-010 | BAIXO | SEC-6 | não revisado nesta rodada | PR SEC-6 |

## Apêndice B — Nota de reconciliação ALTO-001 (pipeline × Missão 7A)

- **Snapshot do pipeline (2026-07-07 18:04):** `settings.local.json` (raiz + 4 worktrees), linhas `:42`/`:50`, continham regra de permissão com e-mail real, nome completo e **duas senhas** em texto claro. Repositório sob OneDrive amplia a exposição. Severidade ALTO.
- **Missão 7A (2026-07-08):** os arquivos **atuais** já estavam com regra curinga (`clerk users create *`), **sem `--password`**. Restavam apenas IDs de usuário Clerk locais, que foram **redigidos** para placeholder. Confirmado: **nenhum arquivo rastreado pelo git, nunca enviado ao remoto**.
- **Correção de precisão (reconciliação 2026-07-16):** a afirmação original "`.gitignore` cobre os padrões" está **errada** — o `.gitignore` versionado do repositório não contém nenhuma entrada para `.claude/`. A proteção real vem de configuração git **global do dono** e de uma configuração de exclusão **local deste clone, não versionada**. Funciona nesta máquina, mas não protegeria automaticamente um clone novo sem a mesma configuração — ver §2.4 para o detalhe e a sugestão de mitigação (poucas linhas no `.gitignore` do repo).
- **Conclusão (revalidada em 2026-07-16):** sem credencial ativa versionada no estado atual (reconfirmado no código agora, não só em 2026-07-08). A parte de código/higiene do finding está contida. **A rotação da senha no Clerk — antes pendente — foi confirmada concluída em 2026-07-09** (`docs/sprints/DEPLOY-HANDOFF-2026-07-09.md`, seção "SEC-0"). ALTO-001/SEC-0 está **integralmente concluído**, sem pendência aberta.
