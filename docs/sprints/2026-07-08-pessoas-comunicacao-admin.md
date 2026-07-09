# Missão 7B-2 — Pessoas/Comunicação para admin-only — 2026-07-08

**Branch:** `claude/pessoas-comunicacao-admin-6ea1d6`  ·  **Commits:** `42562ff`  ·  **Deploy:** não (PR draft, sem migration, sem deploy)

## O que foi feito
- `Pessoas` (`contatos`) e `Comunicação` (`comunicados`) saem do menu operacional (`app.<domínio>`) e viram telas exclusivas do admin (`admin.<domínio>` → `/gestao`), reaproveitando o padrão já existente de `identidade`/`equipe`/`permissoes`/`integracoes` (`ADMIN_ONLY` + gate `isAdmin` no topo de `/gestao`).
  - [frontend/src/lib/permissions.ts](frontend/src/lib/permissions.ts) — `contatos`/`comunicados` saem de `MENU_SCREENS`, entram em `ADMIN_ONLY`; removidos das listas por papel em `DEFAULT_PERMISSIONS`.
  - [frontend/src/lib/navigation.ts](frontend/src/lib/navigation.ts) — seção "Gestão" operacional (só tinha essas 2 entradas) removida; entradas movidas para `ADMIN_NAV_SECTIONS`.
- Backend: `can_access_screen()` recusa telas `ADMIN_ONLY` para qualquer papel não-admin **antes** de consultar a matriz do tenant — fecha o caso de uma linha legada em `role_permissions` ainda conceder `comunicados`/`contatos` a um papel comum ([backend/app/domain/permissions.py](backend/app/domain/permissions.py)). `require_screen("comunicados")` (já existente em `broadcasts.py`) é o gate real de `POST/GET /broadcasts`.
- `GET/POST /contacts` **não** foi restringido: é infraestrutura compartilhada por Ganhar, Consolidar, Células, G12 e Multiplicação — não exclusiva da tela Pessoas. A edição (`PATCH /contacts/{id}`) já era `admin`-only via `require_role(["admin"])` e segue assim, sem mudança.
- Testes: [backend/tests/test_rbac_routers.py](backend/tests/test_rbac_routers.py) atualizado pro novo default (pastor deixa de passar por padrão; matriz do tenant não consegue mais conceder tela ADMIN_ONLY a papel comum); [backend/tests/test_permissions_domain.py](backend/tests/test_permissions_domain.py) novo, testa `can_access_screen` direto.
- PR draft aberto: [#137](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/137). **Não mergeado.**

## Decisões
- Não existe papel "pastor principal/admin" separado no modelo (`Role` = admin/pastor/lider_g12/lider_consol/lider_celula/lider_mult/operador/membro). `admin` já cobre o requisito — como papéis são acumulados (`user_roles`), um pastor com privilégio administrativo explícito basta ter também o papel `admin` para ver as duas telas. Não criei papel novo.
- `GET/POST /contacts` ficou de fora do gate porque é dado compartilhado com múltiplos fluxos operacionais legítimos de papéis não-admin (líder de célula pedindo multiplicação, líder de consolidação buscando contato, etc.) — restringir quebraria esses fluxos e violaria a instrução explícita de não mexer em regra de célula/liderança.
- O gate `ADMIN_ONLY` no backend foi colocado em `can_access_screen()` (a função raiz consultada por `require_screen`), não em cada router — fecha a lacuna pra qualquer tela futura marcada `ADMIN_ONLY`, não só as duas desta missão.

## Pendente / próximo passo
- **Validação visual autenticada por papel** (browser, com usuários reais admin / pastor comum / líder de célula) — não feita nesta sessão: worktree novo sem `.env`/Clerk configurado e sem usuário de teste não-admin seedado no DEV. Documentado como BLOCKED no PR.
- Se aprovado, mergear #137 (sem deploy imediato necessário — é frontend+lógica de permissão, sem migration).
- Dívida pré-existente identificada mas fora de escopo: nenhuma nova — nenhuma migration de dado precisa ser feita; linhas antigas em `role_permissions` que porventura já concedessem `comunicados`/`contatos` a papel não-admin ficam inertes (bloqueadas em código), sem necessidade de limpar o banco.

## Verificação
- `pytest` completo (backend): **PASS**, exit 0 (suíte cheia, sem regressão).
- `pytest tests/test_rbac_routers.py tests/test_permissions_domain.py` (alvo): **PASS**, 16/16.
- `next build` (compile + typecheck + lint embutidos): **PASS**.
- `tsc --noEmit`: **PASS**.
- `next lint`: **PASS**, 0 warnings/errors.
- Navegação visual autenticada por papel: **BLOCKED** (ver Pendente).
