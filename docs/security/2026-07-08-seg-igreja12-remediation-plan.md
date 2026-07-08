# Plano de Remediação de Segurança — Seg-Igreja12

- **Data:** 2026-07-08
- **Projeto pipeline:** Seg-Igreja12 (LionCloud Security Audit Pipeline)
- **Base de código:** PastorAI (`main` @ `b188358`, C1/RLS já fechado)
- **Tipo deste documento:** fonte de verdade versionada do resultado do pipeline. **Docs-only — não implementa correção.**
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

Pontos de partida já resolvidos:

- **ALTO-001 (Secrets)** foi tratado pela **Missão 7A** como **contenção/higiene local**. O snapshot do pipeline (2026-07-07 18:04) registrou credencial real (e-mail, nome completo e duas senhas em texto claro) nas linhas `:42`/`:50` dos `settings.local.json`. Na execução da 7A esses arquivos **já estavam com regra curinga** (`clerk users create *`), **sem `--password`**; restavam apenas IDs locais, que foram redigidos. **Nenhum arquivo estava rastreado pelo git nem foi ao remoto.** Conclusão: **sem evidência atual de credencial ativa versionada** — mas a credencial esteve exposta localmente (repositório sob OneDrive, sincronizado), então **a rotação da senha no Clerk permanece obrigatória** (ver SEC-0 e §7). Valores omitidos deste documento por política.
- **Missão 6/C1** (seam profundo de RLS/tenant-context) está **fechada e em produção** e é a **base para os itens de RLS** deste plano — especificamente o gate do SEC-5 (`FORCE ROW LEVEL SECURITY`), que só deve ser executado **depois** do C1 validado.

Este plano **não** implementa correções. Ele fixa: estado por severidade, ordem recomendada (SEC-0..7), riscos, gates por PR, dependências e decisões. A execução será feita depois, **um SEC por PR** (ou sub-PR pequeno), via Cloud Code com gates reais — **não** pelo LionCloud Coder.

---

## 2. Estado por severidade

Legenda de **status**: `CONCLUÍDO` (7A) · `PENDENTE` (a executar). Arquivos citados como referência do finding — **não** editados aqui.

### 2.1 ALTO (5)

| ID | Título | Arquivos-chave | SEC | Status |
|----|--------|----------------|-----|--------|
| ALTO-001 | Credencial de usuário Clerk exposta em `settings.local.json` (e cópias em worktrees) | `.claude/settings.local.json` + 4 cópias em worktrees | SEC-0 | **CONCLUÍDO** (7A) · rotação pendente do dono |
| ALTO-002 | Ausência de rate limiting nos endpoints de autenticação | `backend/app/routers/auth.py` (login/forgot/reset/activate/change) · `backend/app/main.py` | SEC-2 | PENDENTE |
| ALTO-003 | Constante `CENTRAL_ROLES` redefinida em dois módulos (risco de drift de autorização) | `backend/app/deps.py`, `backend/app/routers/cells.py` | SEC-7 | PENDENTE |
| ALTO-004 | Métodos de verificação de JWT quase idênticos em `ClerkClient` | `backend/app/services/clerk.py` (verify session/reset/invite) | SEC-7 | PENDENTE |
| ALTO-005 | Dispatch de SLA envia WhatsApp **antes** de persistir log de dedupe | `backend/app/services/sla_engine.py` | SEC-4 | PENDENTE |

### 2.2 MÉDIO (6)

| ID | Título | Arquivos-chave | SEC | Status |
|----|--------|----------------|-----|--------|
| MEDIO-001 | Fallback de CORS para `["*"]` com `allow_credentials=True` | `backend/app/main.py`, `backend/app/config.py` | SEC-1 | PENDENTE |
| MEDIO-002 | Sessão JWT stateless não invalidada após troca/reset de senha | `backend/app/services/clerk.py`, `backend/app/routers/auth.py`, `deps.py` | SEC-3 | PENDENTE |
| MEDIO-003 | Token de reset de senha reutilizável (sem uso único) | `backend/app/services/clerk.py`, `backend/app/routers/auth.py` | SEC-3 | PENDENTE |
| MEDIO-004 | Dedup canônica de telefone repetida em 4 locais (uma sem filtro de `igreja_id`) | `contacts.py`, `auth.py`, `queue_worker.py` → novo `domain/phone.py` | SEC-7 | PENDENTE |
| MEDIO-005 | Métodos de emissão de JWT quase idênticos em `ClerkClient` | `backend/app/services/clerk.py` (mint session/reset/invite) | SEC-7 | PENDENTE |
| MEDIO-006 | Approve de solicitação de célula sem lock → TOCTOU | `cell_requests.py`, `cell_requests_service.py` | SEC-4 | PENDENTE |

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

## 3. Ordem recomendada de execução (SEC-0..7)

Cada SEC é **um PR separado** (ou sub-PR pequeno). A ordem prioriza: contenção → fundação de config → superfície de auth → concorrência → RLS → frontend → dívida. Correlações do pipeline anotadas onde importam.

### SEC-0 — Secrets / contenção · **CONCLUÍDO (Missão 7A)**
- **Findings:** ALTO-001.
- **O que já foi feito:** arquivos atuais sem `--password`; IDs locais redigidos; confirmado não-rastreado/não-remoto; `.gitignore` cobre `**/.claude/settings.local.json` + `.claude/worktrees/`.
- **Pendente (fora de código):** **rotação da senha no painel Clerk** pelo dono — ver §7.

### SEC-1 — Config segura (fundação)
- **Findings:** BAIXO-001 (`SESSION_JWT_SECRET` dedicado + validado) e MEDIO-001 (CORS estrito, sem fallback `["*"]` com credenciais). *(pipeline: sprint-002)*
- **O que muda:** `assert_production_ready()` passa a exigir `SESSION_JWT_SECRET` (>=32 bytes) e origens CORS explícitas (`FRONTEND_URL`/`APP_BASE_URL`); em produção o secret de sessão nunca cai em `clerk_secret_key`. Atualizar `.env.example` (sem valores).
- **Por que primeiro:** é fundação para SEC-3 (invalidação de sessão/reset dependem de secret de sessão dedicado e estável).

### SEC-2 — Rate limiting de auth
- **Findings:** ALTO-002. *(pipeline: sprint-003)*
- **O que muda:** limiter por IP + por conta/e-mail em `login`/`forgot`/`reset`/`activate`/`change-password`; resposta `429` + `Retry-After` sem vazar existência de conta. Reutiliza Redis já disponível.

### SEC-3 — Invalidação de sessão + reset token de uso único
- **Findings:** MEDIO-002 (invalidar sessão em troca/reset de senha) e MEDIO-003 (reset token `jti` uso único).
- **O que muda:** migration adiciona `password_changed_at`/`token_version` em `app_user`; `get_current_user` rejeita token anterior ao evento; reset/change-password atualizam o carimbo; reset token vira uso único.
- **Correlação:** toca `clerk.py` (mint/verify de JWT). **Se ALTO-004 e MEDIO-005 (helpers únicos de verify/mint) forem feitos antes, o diff do SEC-3 encolhe e o endurecimento fica num só ponto** — resequenciamento opcional (ver §6).

### SEC-4 — Idempotência / locks / TOCTOU
- **Findings:** ALTO-005 (SLA: log de dedupe antes do envio), MEDIO-006 (lock em approve de solicitação), BAIXO-004 (`confirm_event` com lock + unicidade), BAIXO-005 (`notify_autoupgrade` idempotente).
- **O que muda:** reservar/commitar marcador de idempotência **antes** de qualquer efeito externo (WhatsApp); `with_for_update()` nas transições de estado; constraint/dedupe de alvos.
- **Correlação:** ALTO-005 × BAIXO-004 × BAIXO-005 (idempotência antes de envio); MEDIO-006 × BAIXO-004 (lock de linha). Endurecer em conjunto.

### SEC-5 — `FORCE ROW LEVEL SECURITY` · **somente depois do C1 validado**
- **Findings:** BAIXO-002.
- **O que muda:** migration `ALTER TABLE ... FORCE ROW LEVEL SECURITY` nas tabelas de tenant, tornando a RLS fail-closed também para o papel owner/de conexão.
- **Gate rígido:** só executar com o **C1/RLS seam fechado e validado** (feito) e após confirmar que fluxos legítimos cross-tenant (worker, platform_admin) usam `mark_cross_tenant`/service role. **DEV antes de PROD.** Ver riscos (§4) e rollback (§5).

### SEC-6 — Frontend token hardening
- **Findings:** BAIXO-010.
- **O que muda:** preferir cookie `HttpOnly`+`Secure`+`SameSite` como fonte primária da sessão; Bearer só em memória; CSP restritiva. Se manter `localStorage`, reduzir TTL + invalidação server-side (alinha com SEC-3).

### SEC-7 — Dívida técnica / dedups / refactors grandes
- **Findings:** ALTO-003, ALTO-004, MEDIO-004, MEDIO-005, BAIXO-003, BAIXO-006, BAIXO-007, BAIXO-008, BAIXO-009.
- **Nota de altitude (surfacing explícito):** ALTO-003 e ALTO-004 têm severidade **ALTA** por risco de *drift* (autorização divergente; endurecimento de JWT aplicado inconsistentemente), mas a correção é **dedup/refactor** — daí caírem no bucket SEC-7. Não são "baixa prioridade": recomenda-se **puxá-los para PRs pequenos e cedo**, especialmente ALTO-004/MEDIO-005 antes do SEC-3.
- **Sub-divisão sugerida (cada um PR pequeno e isolado):**
  - **SEC-7a — dedups de segurança (pequenas):** ALTO-003 (fonte única `CENTRAL_ROLES`), ALTO-004 (helper único verify JWT), MEDIO-004 (`find_pessoa_by_phone` com `igreja_id` explícito), MEDIO-005 (helper único mint JWT), BAIXO-003 (helper único do HTTP client Clerk).
  - **SEC-7b — performance/qualidade pontual:** BAIXO-006 (`count(*)` no banco).
  - **SEC-7c — refactors estruturais grandes:** BAIXO-007 (dividir `platform_admin.py`), BAIXO-008 (telas/módulos >500 linhas), BAIXO-009 (dividir `models.py` — **opcional**).

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
7. **DEV antes de PROD quando houver migration** (SEC-3, SEC-5) — aplicar e validar no Supabase DEV `cxmjojnocigekgcxhubi` antes do PROD `pffafnchtxbimpwyaczq`.
8. **Rollback documentado** para itens que alteram **auth ou RLS** (SEC-1 fail-fast, SEC-2, SEC-3, SEC-5): passo de reversão explícito no PR (migration reversa / flag / revert), testado ou descrito.

---

## 6. Dependências

- **SEC-5 (FORCE RLS) depende do C1/RLS seam fechado** — pré-condição satisfeita (Missão 6/C1 em produção). Ainda assim, validar policies + cross-tenant em DEV antes de aplicar.
- **SEC-1 é fundação de SEC-3** — `SESSION_JWT_SECRET` dedicado e CORS estrito antes da invalidação de sessão/reset.
- **Resequenciamento opcional:** ALTO-004 + MEDIO-005 (helpers únicos verify/mint em `clerk.py`) **antes** do SEC-3, para reduzir o diff e centralizar o endurecimento de JWT num só ponto.
- **Refactors baixos não bloqueiam ALTO/MÉDIO** — SEC-7b/7c (BAIXO-006/007/008/009) podem esperar; não são gate de nada.
- **Não misturar SEC-1/2/3/4 com SEC-7** no mesmo PR — mudança de comportamento de segurança separada de refactor estrutural, para preservar rastreabilidade.

---

## 7. Decisões explícitas

1. **Não implementar os 21 findings em um PR único.** Cada SEC = um PR separado (ou sub-PR pequeno).
2. **Não misturar segurança com a Missão 6.** A base RLS do C1 é pré-requisito de SEC-5, mas a execução de segurança é trilha própria.
3. **Não usar o LionCloud Coder para executar a correção.** A execução será via **Cloud Code com gates reais** (§5).
4. **Cada SEC vira PR separado ou sub-PR pequeno**, com os gates obrigatórios aplicados.
5. **Rotação de credencial (SEC-0) é ação do dono no Clerk** — não pode ser feita por código. As senhas registradas no snapshot do pipeline devem ser tratadas como **comprometidas**:
   > **Ação recomendada ao dono:** no painel Clerk → usuário afetado → redefinir/rotacionar a senha (e revisar sessões ativas). Considerar as credenciais do snapshot inválidas. Como o repositório está sob OneDrive (sincronizado), revisar também backups/versões na nuvem. Valores omitidos deste documento por política de contenção.

---

## 8. Próximo passo recomendado

Após o merge deste PR **docs-only**, **iniciar SEC-1** (Config segura: `SESSION_JWT_SECRET` dedicado + CORS estrito) em branch nova a partir de `origin/main`, seguindo os gates da §5.

---

## Apêndice A — Rastreabilidade finding → SEC

| Finding | Severidade | SEC | PR sugerido |
|---------|-----------|-----|-------------|
| ALTO-001 | ALTO | SEC-0 | concluído (7A) + rotação do dono |
| ALTO-002 | ALTO | SEC-2 | PR SEC-2 |
| ALTO-003 | ALTO | SEC-7a | PR pequeno (dedup) |
| ALTO-004 | ALTO | SEC-7a | PR pequeno (dedup) — antes de SEC-3 |
| ALTO-005 | ALTO | SEC-4 | PR SEC-4 |
| MEDIO-001 | MÉDIO | SEC-1 | PR SEC-1 |
| MEDIO-002 | MÉDIO | SEC-3 | PR SEC-3 |
| MEDIO-003 | MÉDIO | SEC-3 | PR SEC-3 |
| MEDIO-004 | MÉDIO | SEC-7a | PR pequeno (dedup) |
| MEDIO-005 | MÉDIO | SEC-7a | PR pequeno (dedup) — antes de SEC-3 |
| MEDIO-006 | MÉDIO | SEC-4 | PR SEC-4 |
| BAIXO-001 | BAIXO | SEC-1 | PR SEC-1 |
| BAIXO-002 | BAIXO | SEC-5 | PR SEC-5 (dep. C1) |
| BAIXO-003 | BAIXO | SEC-7a | PR pequeno (dedup) |
| BAIXO-004 | BAIXO | SEC-4 | PR SEC-4 |
| BAIXO-005 | BAIXO | SEC-4 | PR SEC-4 |
| BAIXO-006 | BAIXO | SEC-7b | PR pequeno (perf) |
| BAIXO-007 | BAIXO | SEC-7c | refactor estrutural |
| BAIXO-008 | BAIXO | SEC-7c | refactor estrutural |
| BAIXO-009 | BAIXO | SEC-7c | refactor estrutural (opcional) |
| BAIXO-010 | BAIXO | SEC-6 | PR SEC-6 |

## Apêndice B — Nota de reconciliação ALTO-001 (pipeline × Missão 7A)

- **Snapshot do pipeline (2026-07-07 18:04):** `settings.local.json` (raiz + 4 worktrees), linhas `:42`/`:50`, continham regra de permissão com e-mail real, nome completo e **duas senhas** em texto claro. Repositório sob OneDrive amplia a exposição. Severidade ALTO.
- **Missão 7A (2026-07-08):** os arquivos **atuais** já estavam com regra curinga (`clerk users create *`), **sem `--password`**. Restavam apenas IDs de usuário Clerk locais, que foram **redigidos** para placeholder. Confirmado: **nenhum arquivo rastreado pelo git, nunca enviado ao remoto**; `.gitignore` cobre os padrões.
- **Conclusão:** **sem credencial ativa versionada no estado atual.** A parte de código/higiene do finding está contida. **Pendência remanescente = rotação da senha no Clerk** (fora de código, ação do dono), porque a credencial esteve exposta localmente antes da limpeza. Este é o único item aberto do SEC-0.
