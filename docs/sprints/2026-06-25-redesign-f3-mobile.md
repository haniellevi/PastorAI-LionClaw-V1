# Redesign #8 — F3: mobile-first (bottom-nav + data-table em cards) — 2026-06-25

**Branch:** `feat/redesign-f3-mobile`  ·  **PR:** [#46](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/46) (MERGED)  ·  **Commit:** `732e8cf`  ·  **Merge commit:** `8019c85`  ·  **Deploy:** não

## O que foi feito
Quarta fase do redesign #8 (F0→F4): **mobile-first/responsivo**. Reusa o shell nested+reskin entregue por [F0](2026-06-25-redesign-f0-fundacao-tokens.md)/[F1](2026-06-25-redesign-f1-identidade.md) e as abas-por-hash da [F2](2026-06-25-redesign-f2-navegacao.md). **Estritamente apresentação** — sem mudança de API, lógica, auth, RBAC, RLS, permissões ou rota. Liberada sobre o gate B1+B2 (staging isolado + guard `[SANDBOX]`).

Arquivos alterados (4):
- `frontend/src/components/shell/BottomNav.tsx` *(novo, ~70 linhas)* — barra de navegação inferior, visível **só em mobile** (`@media max-width:860px`, via CSS). Atalhos **Hoje→`dashboard`**, **Conversas→`inbox`**, **Jornada→`ganhar`** navegam por **`#hash`** para screenIds **já existentes** (não cria rota nova); **Mais** chama `onMore()` → abre o **drawer da sidebar existente** (`mobileOpen`). Cada atalho de tela é filtrado por `canSee` (sem permissão, some); "Mais" é ação, sempre visível. Usa `useAuth`/`usePermissions`/`useHashRoute` — **espelha o padrão da `ModuleTabs`** (F2). Labels "Hoje"/"Jornada" são cosméticas do design; o `target`/screenId é preservado.
- `frontend/src/components/shell/AppShell.tsx` *(+2)* — monta `<BottomNav onMore={…}>` reusando `mobileOpen`/`navigate` existentes; **hambúrguer da Topbar mantido**.
- `frontend/src/components/ui/DataTable.tsx` *(+10)* — `data-label` em cada `<td>` (deriva de `Column.header` string, ou da nova `Column.label` opcional) para os cards mobile. Cobre as **7 telas** consumidoras do componente compartilhado (Relatórios, Ganhar, Contatos, Consolidar, Equipe, Comunicados, AdminConsole).
- `frontend/src/app/globals.css` *(+100)* — `.bottom-nav`/`.bn-item` (z-index **30**, fixo no rodapé, só ≤860); folga `padding-bottom: calc(56px + env(safe-area-inset-bottom))` em `.screen`; `.data-table` vira **cards empilhados** em `≤600px` (`thead:none`, `tr:block`, `td:flex` + `td::before{content:attr(data-label)}`); util `.table-scroll` (fallback de tabela inline).

## Decisões
- **Bottom-nav + drawer coexistem em mobile**; "Mais" abre o **drawer existente** (não foi criado drawer novo — a sidebar-drawer já existia desde antes da F3). Decisão de produto do usuário no início da F3.
- **Atalhos navegam por `#hash` para screenIds existentes** (não cria rota nova); filtrados por `canSee` — single source com a navegação, espelha a `ModuleTabs`.
- **Cards reais** para as consumidoras do `DataTable` (via `data-label`); para **tabelas inline** (não-DataTable), só o util `.table-scroll` — **aplicado apenas se o smoke detectar estouro real**, não em massa nas 22 telas.
- **Hambúrguer da Topbar mantido** nesta F3 (coexiste com "Mais"); redundância apenas **reportada**, não removida.
- **Breakpoints:** bottom-nav em ≤860 (mesmo limiar do sidebar→drawer); cards em ≤600 (telefone). Distintos de propósito.
- **Painel "Assistente" adiado** (é feature de chat, não responsivo) e **F4 não iniciada**.
- **Merge via merge commit** (padrão do repo). **Branch não deletada** — o worktree `sad-dewdney-712f21` ainda está nela.

## Pendente / próximo passo
- **F4 — polish + PWA:** micro-raios/transições, contraste AA dos novos pares (mint sobre dark), ícones/tema PWA Igreja12, **resolver a redundância hambúrguer × "Mais"** e o posicionamento fino. **Não iniciada.**
- **Gate `canSee` oculta atalho** não foi *positivamente* observado no smoke (o usuário seed é admin/DONO → vê tudo); o filtro está verificado em código e é o mesmo `canSee` da `ModuleTabs`. Reverificar com login **não-admin** quando houver conta no seed de staging.
- **`.table-scroll` criado mas não aplicado** em nenhuma tela — o smoke não detectou estouro horizontal inline (a matriz larga de `#permissoes` já é contida pelo `.perm-wrap`). Aplicar caso surja overflow real.

## Verificação
- **Gates técnicos (HEAD `732e8cf`):** `typecheck` ✅ · `lint` ✅ (0 warnings) · `build` ✅ (Next 14). Reexecutados verdes antes do merge.
- **CodeGraph `detect_changes`/`get_affected_flows`:** 3 nós front-end (AppShell/BottomNav/DataTable), **0 fluxos backend afetados**, risco 0.35.
- **Invariância (`git diff` vs base `7907760`):** `permissions.ts`, `canSee`, `LOCKED_SCREENS`, `OWNER_ONLY`, `navigation.ts` **intactos**; nenhum `target`/screenId removido; só 4 arquivos shell/ui/css.
- **Smoke autenticado em STAGING REAL = APTO.** Ambiente B1 isolado: backend `:8001` `env=staging` + `ALLOW_REAL_SENDS=false`, frontend F3 `:3000` apontando `:8001`, Supabase staging + Clerk test, tenant seed (Pastor Piloto/igreja piloto; Pessoas=1, volume=seed). Resultados por gate (viewports 375/390 e 917):
  - bottom-nav só em mobile (`display:flex`@375, `display:none`@917; `position:fixed`, `z-index:30`);
  - **Hoje→`#dashboard`**, **Conversas→`#inbox`**, **Jornada→`#ganhar`** — todos **sem reload** (sentinela `window` sobreviveu); aba ativa reflete a rota;
  - **Mais** abre o drawer (`.sidebar.open`, `z-index:40`) — sobre o bottom-nav;
  - **deep-link** `#consol-individual` (reload completo) **resolve** na tela certa, não cai p/ dashboard; abas F2 intactas;
  - **DataTable vira card** em `#contatos` (`thead:none`/`tr:block`/`td:flex` + `data-label`/`::before`), **sem estouro horizontal**;
  - **tabelas inline não estouram:** matriz `#permissoes` (1173px) contida pelo `.perm-wrap`; `#g12`/`#dashboard` sem overflow de documento;
  - conteúdo não fica sob o bottom-nav (`.screen` `padding-bottom:56px` @mobile);
  - **z-order:** conv-panel `z50` > drawer `z40` > bottom-nav `z30`;
  - **nenhum envio real:** log do `:8001` com **0 `[SANDBOX]` e 0** chamadas Evolution/Asaas/Brevo/OpenAI/Calendar (só GETs + auth; Clerk test é infra de login, sempre-on por design);
  - **produção intocada:** `:8000` (prod-pointed) nunca foi alvo; sem worker iniciado.
- **PR #46:** draft → ready → **MERGED** (mergeCommit `8019c85`); `origin/main` avançou `7907760`→`8019c85`; `732e8cf` ancestral de `origin/main`.

### Limitações aceitas (baixo risco para a F3)
- **Gate `canSee` oculta** não positivamente observável com usuário admin (ver Pendente) — limitação idêntica à F2 (já mesclada).
- **Redundância hambúrguer × "Mais"** em mobile — mantida nesta fase; candidata a decisão na F4.

---
*Coordenação:* registro criado no worktree `sad-dewdney-712f21` (branch `docs/sprint-f3-mobile`, a partir de `origin/main` `8019c85`). Docs-only — nenhum código de produto, config, env, banco, auth ou serviço externo tocado.
