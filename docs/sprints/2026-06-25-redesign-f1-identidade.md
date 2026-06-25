# Redesign #8 — F1: identidade Igreja 12 — 2026-06-25

**Branch:** `feat/redesign-f1-identidade`  ·  **PR:** [#37](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/37) (MERGED)  ·  **Commit:** `0e42310`  ·  **Merge commit:** `85bc1ea`  ·  **Deploy:** não

## O que foi feito
Aplicação da identidade visual **Igreja 12** sobre a fundação de tokens da [F0](2026-06-25-redesign-f0-fundacao-tokens.md): carrega as webfontes, aplica os gradientes de marca, o estado ativo *mint* na navegação, anel de foco/sombra do CTA e **corrige o contraste** dos pares `--accent`/`--warn` (dívida AA herdada da F0). **Estritamente apresentação** — sem mudança de API, lógica, auth, RBAC, RLS ou navegação. É a F1 do redesign #8 (fases F0→F4).

Arquivos alterados (5):
- `frontend/src/app/layout.tsx` *(+13)* — 9 imports `@fontsource` (self-hosted) **antes** do `globals.css`: Plus Jakarta Sans 400/500/600/700, Sora 600/700/800, JetBrains Mono 400/500. O build empacota os `woff2` do `node_modules` — **sem chamada externa** (não usa `next/font/google`).
- `frontend/src/app/globals.css` *(+55/-19)* — contraste, fontes e gradientes (detalhe abaixo).
- `frontend/src/components/shell/Sidebar.tsx` *(+8/-1)* — selo `.owner-seal` ("Dono") no bloco `.side-church`, condicional a `user.isOwner` (feature #4 — só o dono/admin principal).
- `frontend/package.json` *(+3)* — deps `@fontsource/plus-jakarta-sans`, `@fontsource/sora`, `@fontsource/jetbrains-mono` (`^5.2.8`).
- `frontend/package-lock.json` *(+30)* — lockfile correspondente.

Detalhe do `globals.css`:
- **Contraste (AA) — tokens escurecidos + dependentes re-derivados:**
  - `--accent` `60% → 53.5%` (matiz 185→186); `--accent-dark` `51.1% → 46%`; `--warn` `66.6% → 55%`.
  - Re-derivados ao novo accent: `--shadow-primary`, `--ring`, `--grad-brand`, `--grad-brand-mint` (1ª parada).
  - O `--warn` em 55% **desfaz a colisão byte-idêntica** com o estágio *Consolidar* (`--st`, que segue 66.6%) — dívida registrada na reconciliação da F0.
- **Webfontes aplicadas:** `--font-display` (Sora) em `h1–h4`, `.brand`, `.btn`, `.panel-title`, `.stat .val`, `.owner-seal`. O corpo (`--font` = Plus Jakarta Sans), antes em fallback `system-ui`, passa a renderizar de fato com o carregamento — alcança toda a UI por cascata.
- **Gradientes de marca:** `.login-aside` e `.sidebar` → `var(--grad-sidebar)`; `.brand-mark` → `var(--grad-brand-mint)`.
- **Estado ativo *mint* na nav:** `.nav-item.active` = fundo `color-mix(accent 22%)` + texto branco + barra `inset 3px var(--accent-bright)`; ícone e badge do ativo em mint.
- **Mint sobre fundo escuro (legibilidade):** `.aside-kicker` e `.aside-item svg` `--accent` → `--accent-bright` (~10:1 no dark).
- **Foco / CTA:** `input/select/textarea:focus` e `.btn:focus-visible` → `box-shadow: var(--ring)`; `.btn-primary` ganha `box-shadow: var(--shadow-primary)` e hover → `var(--accent-dark)` (antes um `oklch()` hardcoded).
- **Selo do dono:** `.owner-seal` (novo) — pill dourado (`--gold-plan`) na sidebar dark.

## Decisões
- **Webfontes self-hosted via `@fontsource`** (não `next/font/google`): o build não depende de internet — requisito do prompt da F1. Famílias batem com os tokens `--font` / `--font-display` / `--mono` da F0.
- **Correção de contraste entrou na F1** (estava prevista para "F1/F4" na reconciliação): como a F1 é quem **aplica** accent/warn em superfícies visíveis, escurecer agora evita publicar um CTA abaixo de AA. F4 (polish) segue para ajustes finos.
- **`--warn` divergiu do estágio Consolidar de propósito** — separar o token de estado do token de estágio resolve a colisão latente sem afetar a escada G12.
- **Merge via merge commit** (padrão do repo). **Branch não deletada** — o worktree `jolly-curran-4d0c74` ainda está nela.
- **Contexto de concorrência:** durante o ciclo da F1, a `main` recebeu também o **PR #38** (outra conversa — botão mostrar/ocultar senha no login, `abc98f9`). A F1 mesclou **limpa por cima** (`MERGEABLE/CLEAN`, sem conflito); as duas mudanças coexistem na `main`.
- **Correções de fidelidade ao código** (o registro não pode virar ficção): o corpo é **Plus Jakarta Sans**, não "Inter"; e a F1 **não** adicionou regras específicas de *Topbar*, *tabelas* ou *pills* — esses elementos mudam apenas por herdarem a fonte de corpo agora carregada, não por regra própria.

## Pendente / próximo passo
- **⚠️ Bloqueadores antes da F2/F3 — B1 + B2.** A F2 (navegação) e a F3 (mobile-first) exigem interação autenticada nas telas internas; hoje o ambiente local/dev aponta para **dados e serviços de produção**.
  - **B1 — staging isolado:** projeto Supabase separado + instância Clerk de dev + contas de teste, para validar fluxos sem tocar produção.
  - **B2 — guarda de envios não-prod:** *gating* por `is_production` + URLs de sandbox, impedindo WhatsApp (Evolution), cobrança (Asaas) e e-mail (Brevo) reais fora de produção.
- **F4 (polish)** segue para refinos de contraste/densidade e ajustes finos de tokens.
- **Densidade de tabela em mobile (scroll horizontal) — F3** (herdado da F0).
- **F2/F3/F4 NÃO foram iniciadas** nesta sessão — nenhuma branch dessas fases criada.

## Verificação
- **Gates técnicos (HEAD `0e42310`):** `typecheck` ✅ · `lint` ✅ · `build` ✅ (compila empacotando os `woff2`).
- **Contraste (medido oklch→WCAG):** CTA texto branco sobre `--accent` `3.65 → ~4.67:1`; `--accent` como texto sobre branco `3.75 → ~4.79:1`; `--warn` como texto sobre branco `3.18 → ~5.07:1`; mint sobre dark `~10:1`. Todos ≥ AA.
- **Fontes offline:** `@font-face` do `@fontsource` sem `src` externo; `woff2` vêm do `node_modules`. As referências a `fonts.googleapis.com`/`gstatic` no `.next` são *boilerplate* inerte do framework Next.js (preconnect em `main-*.js`/`_error.js`), **não** do código da F1 — diff e CSS da app com 0 referências externas.
- **CodeGraph:** `detect_changes` no diff da F1 = arquivos de apresentação + deps; nenhum nó de lógica/fluxo de backend afetado (mudança visual).
- **Smoke autenticado read-only:** usuário logou manualmente no Chrome controlado; navegação das telas internas sem mutar dados (sem enviar WhatsApp/e-mail/cobrança, sem assumir atendimento, sem salvar formulário). Identidade aplicada conforme protótipo.
- **PR #37:** OPEN → ready → **MERGED** (mergeCommit `85bc1ea`); `origin/main` contém `0e42310` (ancestral); `layout.tsx` na `main` com 9 imports `@fontsource`.

### Limitações aceitas (baixo risco para a F1)
- **Modal ao vivo não aberto** no smoke — a F1 não altera comportamento de modais; risco baixo.
- **Mobile autenticado não capturado** — o resize do Chrome controlado não reflowou a viewport. A identidade da F1 é independente de viewport e o login mobile já foi validado a 375px (Claude Preview). A densidade mobile é escopo da F3.

---
*Coordenação:* registro criado no worktree temporário `docs-f1` (branch `docs/sprint-f1-identidade`, a partir de `origin/main` `85bc1ea`). Docs-only — nenhum código de produto, config, env, banco, auth ou serviço externo tocado.
