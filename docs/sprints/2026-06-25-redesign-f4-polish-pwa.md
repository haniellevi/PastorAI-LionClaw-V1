# Redesign #8 — F4: polish + PWA Igreja 12 — 2026-06-25

**Branch:** `feat/redesign-f4-polish-pwa`  ·  **PR:** [#48](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/48) (MERGED)  ·  **Commit:** `1cf3b29`  ·  **Merge commit:** `36db492`  ·  **Deploy:** não

## O que foi feito
Quinta e **última** fase do redesign #8 (F0→F4): **polish + PWA**. Reusa o shell/reskin de [F0](2026-06-25-redesign-f0-fundacao-tokens.md)/[F1](2026-06-25-redesign-f1-identidade.md), as abas-por-hash da [F2](2026-06-25-redesign-f2-navegacao.md) e o mobile-first da [F3](2026-06-25-redesign-f3-mobile.md). **Estritamente apresentação** — sem mudança de API, lógica, auth, RBAC, RLS, permissões ou rota. **Sem service worker / sem offline.**

Arquivos alterados (9), todos em `frontend/`:
- `frontend/public/manifest.webmanifest` — `theme_color` `#1b2526`→**`#0b2c29`**; `background_color` `#fbfbf9`→`#eef3f2` (paleta fria); array de `icons` ampliado com **PNG fallbacks** (`/icon-192.png` 192², `/icon-512.png` 512² em `purpose:any`; `/icon-maskable-512.png` 512² em `purpose:maskable`) ao lado dos SVGs `any`/`maskable` já existentes.
- `frontend/src/app/layout.tsx` — `viewport.themeColor` `#1b2526`→**`#0b2c29`** (alinha ao manifest); `icons.apple` `/icon.svg`→**`/apple-touch-icon.png`** (PNG 180², formato que iOS exige). `manifest:"/manifest.webmanifest"` e `appleWebApp` já estavam wired.
- `frontend/public/icon.svg` — recolorido p/ teal Igreja 12: `fill` `#2f6d72`→`#0d9488`, `stroke` `#eefbf9`→`#f0fdfa`.
- `frontend/public/icon-maskable.svg` — recolorido: `fill` `#1b2526`→`#0d9488`, `stroke` `#3a8e94`→`#f0fdfa`. **Paleta antiga eliminada dos SVGs.**
- `frontend/public/apple-touch-icon.png` *(novo, 180×180)*, `icon-192.png` *(192×192)*, `icon-512.png` *(512×512)*, `icon-maskable-512.png` *(512×512)* — PNGs gerados; dimensões conferem com o `sizes` declarado no manifest/head (medido no IHDR).
- `frontend/src/app/globals.css` *(+~25 / -5)*:
  - **D1 — hambúrguer oculto ≤860:** `.menu-toggle` em `@media (max-width:860px)` vai de `display:grid!important`→**`display:none!important`**. O botão era redundante com o atalho **"Mais"** do bottom-nav (F3) — ambos abrem o **mesmo drawer**. Desktop já ocultava o hambúrguer (base `.menu-toggle{display:none}`, sidebar sempre visível). "Mais" vira a **entrada única** do drawer no mobile.
  - **a11y — `prefers-reduced-motion`:** novo `@media (prefers-reduced-motion: reduce)` neutraliza `animation`/`transition` globais (e `scroll-behavior`) **sem remover o estado final** (anti motion-sickness, preserva o fade `.screen`).
  - **Contraste AA em texto real:** `--faint` (medido **2.46:1** sobre branco, reprova AA) trocado por `--muted` (**~8.7:1**) em 5 seletores de **texto essencial**: `.field .helper`, `.topbar .crumb`, `table.data-table th`, `.filter-bar label`, `.panel-section` (título de seção). `--sidebar-muted` subiu `64%`→`70%` (oklch) p/ passar AA como texto no stop claro do gradiente da sidebar (`3.77`→`4.75:1`, auto-medido).

## Decisões
- **theme_color `#0b2c29`** (petróleo escuro) no manifest **e** no `viewport` — cor da chrome do browser/PWA. **Distinta** do teal do ícone (`#0d9488`): chrome escura + marca teal viva, por design (não é divergência).
- **Recolorir o ícone atual** (não trocar a forma) — SVGs recoloridos p/ teal; PNGs gerados a partir da mesma identidade. `#0d9488` é hex literal (SVG estático não usa CSS var); aceito.
- **Hambúrguer oculto ≤860, "Mais" mantém o drawer** — resolve a redundância **reportada na F3**. Decisão de produto do usuário no início da F4.
- **Sem service worker / sem offline** — fora do escopo; PWA = manifest + ícones + theme, instalável sem cache offline. Decisão explícita.
- **Contraste só em texto real que reprova AA** — corrigidos os 5 pares de texto essencial; `--faint` remanescente fica em itens **isentos/suplementares** (ícones, `::placeholder`, `:disabled`, `.tab.locked`) e alguns rótulos secundários (`.stat .delta`, `.panel-title .count`, `.ov-scope`, `.qbody .resp`) — ver Pendente.
- **Merge via merge commit** (padrão do repo). **Branch não deletada** — o worktree `friendly-bartik-67b235` ainda está nela.

## Pendente / próximo passo
- **Redesign #8 ENCERRADO** com este registro. **F0–F4 todas mescladas** em `origin/main` (`36db492`). Não há F5.
- **Rótulos suplementares ainda em `--faint` (2.46:1):** `.stat .delta`, `.panel-title .count`, `.ov-scope`, `.qbody .meta-line .resp`. São secundários (cabem na decisão "só texto essencial"), mas um auditor estrito pode marcá-los. Candidato a polish futuro — `.stat .delta` é o mais defensável de subir p/ `--muted`.
- **Smoke em browser ao vivo (375/desktop) não executado** — a rota `/` é `force-dynamic` + auth-gated (Clerk), exigiria env/auth p/ `next start`. Validação foi estática + build verde (ver Verificação). Reverificável em staging quando útil.

## Verificação
- **Gates técnicos (HEAD `1cf3b29`):** `typecheck` (`tsc --noEmit`) ✅ exit 0 · `lint` (`next lint`) ✅ 0 warnings · `build` (`next build`, Next 14.2.15) ✅ "Compiled successfully", 5/5 páginas. Reexecutados verdes antes do merge.
- **CodeGraph `detect_changes` (head vs main):** risco **0.00** — 0 funções/classes, 0 fluxos, 0 test-gaps afetados (mudanças são CSS/estáticos/strings, não tocam código executável).
- **PWA validado:** `theme_color`/`themeColor` = `#0b2c29` (manifest + head); manifest aponta p/ 5 ícones **existentes**; `apple-touch-icon.png` existe (180²); PNGs com dimensões corretas (192/512/512, medidas no IHDR); SVGs **sem paleta antiga**; head wired (`manifest`, `icons.apple`, `appleWebApp`).
- **CSS validado:** hambúrguer some ≤860 (dentro de `@media max-width:860`); desktop preservado (base `.menu-toggle{display:none}`); `prefers-reduced-motion` presente; bottom-nav/drawer intactos — `BottomNav` mantém "Mais" (`onClick={onMore}`) como entrada única do drawer.
- **Contraste recalculado de forma independente** (oklch→linear sRGB→WCAG): `--faint`=**2.46:1** (bate com o comentário do código), `--muted`=**8.7:1** vs branco (8.3 vs surface-2, 7.9 vs bg) — os 5 swaps de texto essencial passam AA com folga.
- **Invariância (`git diff` vs base):** **só os 9 arquivos** frontend/public + layout/head + globals.css; **sem** backend, auth, banco, migrations, `permissions/navigation/canSee/LOCKED/OWNER_ONLY`, service worker/offline.
- **Revisão independente read-only = APTO PARA SAIR DE DRAFT.** Zero bloqueadores; riscos remanescentes (rótulos `--faint` suplementares) não-bloqueantes.
- **PR #48:** draft → ready → **MERGED** (mergeCommit `36db492`, **merge commit** — 2 pais: `86c06dc` + `1cf3b29`); `origin/main` avançou `86c06dc`→`36db492`; `1cf3b29` ancestral de `origin/main`.
- **Produção/banco/workers intocados:** nenhuma mudança de runtime; `:8000` (prod) nunca alvo; sem worker iniciado; nenhum envio externo.

## Fechamento do redesign #8 (F0→F4)
| Fase | Tema | PR | Merge commit |
| ---- | ---- | -- | ------------ |
| F0 | Fundação / tokens (flip de paleta lado-claro) | — | mesclada |
| F1 | Identidade (gradientes/sombras/mint/fontes) | — | mesclada |
| F2 | Navegação (abas-por-hash) | [#45](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/45) | `7907760` |
| F3 | Mobile-first (bottom-nav + cards) | [#46](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/46) | `8019c85` |
| F4 | Polish + PWA | [#48](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/48) | `36db492` |

**Redesign #8 concluído.** Todas as 5 fases em `origin/main`. Próximas frentes do roadmap (ex.: Eventos F2, agente/RAG) seguem fora deste bloco.

---
*Coordenação:* registro criado no worktree `unruffled-leavitt-e8377c` (branch `docs/sprint-f4-polish-pwa`, a partir de `origin/main` `36db492`). Docs-only — nenhum código de produto, config, env, banco, auth ou serviço externo tocado.
