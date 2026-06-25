# Redesign #8 — F2: navegação (abas-por-hash + glifo lock) — 2026-06-25

**Branch:** `feat/redesign-f2-navegacao`  ·  **PR:** [#44](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/44) (MERGED)  ·  **Commit:** `6d70471`  ·  **Merge commit:** `5c94896`  ·  **Deploy:** não

## O que foi feito
Terceira fase do redesign #8 (F0→F4): **navegação/shell desktop**. Mantém a sidebar nested+reskin entregue por [F0](2026-06-25-redesign-f0-fundacao-tokens.md)/[F1](2026-06-25-redesign-f1-identidade.md) e adota **abas-por-hash** nos módulos Consolidar e Discipular. **Estritamente apresentação** — sem mudança de API, lógica, auth, RBAC, RLS, permissões ou rota. Liberada após o gate B1+B2 (staging isolado + guard `[SANDBOX]`).

Arquivos alterados (4):
- `frontend/src/components/shell/ModuleTabs.tsx` *(novo, ~90 linhas)* — barra de abas no topo do módulo. A lista é **derivada de `NAV_SECTIONS`** (`lib/navigation.ts`): `head` + `subs` do estágio, sem `target` repetido — **fonte única com a Sidebar**, nenhuma rota hardcoded. Usa `useHashRoute` (navega por `#hash`), `usePermissions` + `canSee` e `useAuth`. Se o grupo não for derivável de `NAV_SECTIONS`, retorna `null` (sem fallback de rota nova).
- `frontend/src/components/shell/ScreenView.tsx` *(+24)* — monta `<ModuleTabs>` acima das telas alcançáveis de cada grupo: `consolidar`/`consol-individual` (grupo Consolidar) e `g12`/`central-celula` (grupo Discipular). Telas individuais intocadas.
- `frontend/src/components/shell/Sidebar.tsx` *(±1)* — glifo locked padronizado: `⌛` → `<Icon name="lock" />` (ícone já existente em `lib/icons.tsx`).
- `frontend/src/app/globals.css` *(+19)* — regra `.module-tabs` (posição acima da `.screen` rolável, alinhada ao padding `--s5`; estilo da aba locked), **reusa** `.tabs`/`.tab`/`.tab.active` já existentes.

Comportamento das abas (delta-010 preservado):
- **Aba ativa** = rota vigente (`route === target`).
- **Tela em `LOCKED`/futuro** (`NavItem.locked` — `universidade-vida`, `capacitacao`): aba **desabilitada com cadeado**, não navega.
- **Tela sem `canSee`**: **não renderiza** (some).
- Grupo Consolidar = `consolidar` · `consol-individual` · `universidade-vida`(locked); grupo Discipular = `g12` · `capacitacao`(locked) · `central-celula` (o `g12`, que é head **e** sub, é deduplicado).

## Decisões
- **Manter sidebar nested + reskin (não achatar).** F0/F1 já reskinaram a sidebar aninhada; achatar seria reestruturação com risco a permissão/deep-link. Decisão de produto do usuário no início da F2.
- **Adotar abas-por-hash** (opção (a) da [reconciliação](../design/RECONCILIACAO-igreja12.md)): as sub-views viram abas que **navegam por `#hash` para os screenIds existentes** — preserva `canSee`/`LOCKED_SCREENS`/`role_permissions`/deep-link. **Não** migrou para o modelo de abas-como-estado-interno (opção (b), mais cara/arriscada).
- **Abas derivadas de `NAV_SECTIONS`**, não hardcoded — single source of truth com a Sidebar; se um grupo não derivar, o componente para (não inventa rota).
- **Montagem em `ScreenView`** (acima da tela), não dentro de cada screen — menor diff, telas intocadas. Posicionamento fino fica para a F4 (polish).
- **Glifo locked = ícone `lock`** (substitui a ampulhêta `⌛`), padronizando o estado bloqueado conforme a reconciliação #5.
- **Merge via merge commit** (padrão do repo). **Branch não deletada** — o worktree `strange-torvalds-ff8485` ainda está nela.

## Pendente / próximo passo
- **F3 — mobile-first** é a próxima fase: bottom-nav (Hoje/Conversas/Jornada/Mais) + drawer; densidade de data-table/grids (tabela→cards). **Não iniciada** nesta sessão.
- **F4 — polish + PWA:** posicionamento fino das abas de módulo, micro-raios/transições, contraste AA dos novos pares, ícones/tema PWA.
- **Gate `canSee` oculta** não foi *positivamente* observado no smoke (o usuário de teste é admin → vê tudo); o filtro está verificado em código e a mesma função `canSee` gateia observavelmente o grupo Configuração. Reverificar com login não-admin de staging quando houver conta.

## Verificação
- **Gates técnicos (HEAD `6d70471`):** `typecheck` ✅ · `lint` ✅ (0 warnings) · `build` ✅ (Next 14). Reexecutados verdes antes do merge.
- **CodeGraph `detect_changes`:** apenas nós de shell/nav (ModuleTabs/deriveTabs/ScreenView/Sidebar); **0 fluxos backend afetados**.
- **Invariância (git diff vs base `e32fdd1`):** `permissions.ts`, `canSee`, `LOCKED_SCREENS`, `OWNER_ONLY`, `navigation.ts` **intactos**; nenhum `target`/`screenId` removido; só 4 arquivos shell/nav/apresentação.
- **Smoke autenticado em STAGING REAL = APTO.** Ambiente B1 isolado (env do worktree `adoring-morse`): backend `:8001` `env=staging` + `ALLOW_REAL_SENDS=false` (guard armado), frontend F2 `:3000`, Supabase ref de staging `cndmgbnzbbzlhxmotxks` (≠ prod), usuário seed `pastor@igrejapiloto.com` (admin/owner, igreja piloto). Resultados por gate:
  - abas aparecem em Consolidar e Discipular (derivadas corretas, locked com cadeado);
  - clicar aba muda `#hash` **sem reload** (sentinela `window` sobreviveu à navegação);
  - deep-link direto `#consol-individual` (reload completo) **resolve** na tela certa, não cai para dashboard;
  - aba locked (`universidade-vida`/`capacitacao`) mostra cadeado e **não navega** (hash inalterado);
  - sidebar segue **nested** (3 seções colapsáveis + 4 estágios + grupo Configuração);
  - **nenhum envio real:** log do backend com **0 `[SANDBOX]` e 0 chamadas outbound** (Evolution/Asaas/Brevo/OpenAI/Calendar); só GETs + `POST /auth/login 200`;
  - **produção intocada:** instância prod-pointed (`:8000`) nunca foi alvo; sem worker iniciado.
- **PR #44:** OPEN → ready → **MERGED** (mergeCommit `5c94896`); `origin/main` avançou `e32fdd1`→`5c94896`; `6d70471` ancestral de `origin/main`.

### Limitações aceitas (baixo risco para a F2)
- **Posicionamento das abas** acima da `.screen` (não embutido no header de cada módulo) — escolha de menor diff; refino visual é escopo da F4.
- **Gate `canSee` oculta** não positivamente observável com usuário admin (ver Pendente).

---
*Coordenação:* registro criado no worktree `strange-torvalds-ff8485` (branch `docs/sprint-f2-navegacao`, a partir de `origin/main` `5c94896`). Docs-only — nenhum código de produto, config, env, banco, auth ou serviço externo tocado.
