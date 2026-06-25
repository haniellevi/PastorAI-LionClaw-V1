# Redesign #8 — F0: fundação de tokens Igreja 12 — 2026-06-25

**Branch:** `feat/redesign-f0-tokens`  ·  **PR:** [#35](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/35) (MERGED)  ·  **Commits:** `4b95d75`, `94a3afe`  ·  **Merge commit:** `7b57d3e`  ·  **Deploy:** não

## O que foi feito
Fundação visual da identidade **Igreja 12** (paleta fria/teal substituindo a quente). **Estritamente apresentação** — sem mudança de API, lógica, auth, RBAC, RLS ou navegação. É a F0 do redesign #8 (fases F0→F4), base para os PRs seguintes.

Arquivos alterados (5):
- `docs/design/RECONCILIACAO-igreja12.md` *(novo, +121)* — contrato de reconciliação design × código atual; base congelada dos PRs F0–F4. Já registra as colisões estágio↔status como dívida da F1.
- `docs/design/Igreja12-Prototipo.standalone.html` *(novo, +181)* — protótipo standalone de referência (Claude Designer), congelado.
- `frontend/package.json` *(+1/-1)* — apenas `description` → "Igreja 12 — painel da igreja (Next.js App Router, PWA, mobile-first)". `name` segue `pastorai-frontend` (interno, intencional).
- `frontend/src/app/globals.css` *(+119/-72)* — reescrita do `:root`: swaps de `--accent`/`--bg`/`--fg`/`--surface`/`--border`/`--sidebar`, 4 `--st` invertidos (G12), tokens novos (`--accent-dark`/`-bright`, `--font-display`, `--grad-*`, `--shadow-primary`, `--ring`, `--urgent`, `--info`, `--whatsapp`, `--gold-plan`, `--surface-3`, `--border-2`/`-teal`, `--st-*-soft`, `--r-xs`/`--r-container`) e re-derivação dos oklch hardcoded da sidebar (matiz 200→~187). Rebrand textual no CSS.
- `frontend/src/components/config/AgenteScreen.tsx` *(+1/-1)* — rebrand textual "plataforma Igreja 12", **preservando o fluxo "requisição ao master"** da `main` (resolução do conflito de rebase).

## Decisões
- **F0 = só fundação de tokens.** Webfonts (Sora / Plus Jakarta Sans / JetBrains Mono) e gradientes ficam **declarados mas NÃO aplicados** nos componentes — aplicação visual fica para a F1. No estado atual o app usa fallback `system-ui`.
- **Estágios G12 invertidos** (frio→quente por etapa): ganhar = rose, consolidar = âmbar, discipular = emerald, enviar = indigo.
- **Merge via merge commit** (padrão do repo, igual aos PRs #30–#34), preservando rastreabilidade. **Branch não deletada** — o worktree `hardcore-sammet-e68aa1` ainda está nela.
- **Revisão independente:** APTO PARA SAIR DE DRAFT (zero bloqueadores). PR saiu de draft → ready → mesclado.

## Pendente / próximo passo
Dívidas previstas e documentadas (no `RECONCILIACAO-igreja12.md`), a tratar nas próximas fases:
- **⚠️ Contraste `--accent` / `--accent-fg` (CTA primário) — F1/F4.** Com `--accent` em OKLCH L=60 e `--accent-fg` quase-branco, o `.btn-primary` cai para ~**3,65:1** em texto de 13,5px (antes da F0 era ~5,17:1), abaixo do alvo **AA 4,5:1**. Escurecer o par accent quando a F1 estilizar os componentes. *(Codex P2 no PR #35, `frontend/src/app/globals.css:37` — não-bloqueante.)*
- **⚠️ Contraste `--warn` como texto — F1/F4.** L 66.6%, limítrofe AA sobre branco. Medir e escurecer junto do par accent.
- **Colisões byte-idênticas estágio↔status — F1.** `consolidar --st` == `--warn`; `ganhar --st-soft` == `--urgent-soft`. Tokens já separados (risco latente); validar antes de aplicar `--st` em superfície clara.
- **Webfonts — F1.** Declaradas; carregar e validar com o protótipo.
- **Gradientes (`--grad-*`, `--shadow-primary`, `--ring`) — F1.** Declarados, ainda não aplicados em componentes.
- **Densidade de tabela em mobile (scroll horizontal) — F3.**
- **Próximo passo:** **F1 em branch nova a partir de `origin/main` (`7b57d3e`)** — não misturar com este registro de docs.

## Verificação
- **Gates técnicos (HEAD `94a3afe`):** `typecheck` ✅ 0 erros · `lint` ✅ sem warnings · `build` ✅ compiled successfully · `git diff --check` ✅ limpo.
- **CodeGraph (conteúdo `main` @ `7b57d3e`):** full build = 242 arquivos / 2253 nós / 17859 arestas; `detect_changes` do merge (`95553d2`→`7b57d3e`) = **5 arquivos, 1 função (`AgenteScreen`), 1 flow, risco 0.60** — impacto só de apresentação.
- **PR #35:** OPEN → ready → **MERGED** (mergeCommit `7b57d3e`); `origin/main` contém `94a3afe` (ancestral); `globals.css` na main com 21× matiz 187.
- **Coordenação:** registro criado em worktree limpo (`jolly-curran-4d0c74`, branch `docs/sprint-f0-fundacao-tokens`). O worktree da `main` **não foi tocado** — tinha mudanças não commitadas de outra conversa.
