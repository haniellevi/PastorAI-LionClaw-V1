# M7B-W1.3 + W1.4 — Fechamento consolidado (Minha Célula do líder) — 2026-07-11

**Branch:** `docs/m7b-w1-3-w1-4-fechamento` (docs-only)  ·  **Base:** `origin/main` `93e3228`
**Deploy:** sim, ambos em produção (backend VPS + frontend Vercel) · smoke manual PASS

## Objetivo do bloco

Deixar a tela **Minha Célula / visão do líder** **segura** e **fiel ao protótipo**:

- **Segura:** o líder não gerencia entrada/transferência/saída de discípulos — isso é
  atribuição da **Central de Célula**. A lista de discípulos é **somente leitura**.
- **Fiel ao protótipo:** cabeçalho de contexto (hero) e composição visual alinhados ao
  protótipo aprovado (`docs/design/Igreja12-Prototipo.standalone.html`), preservando o
  comportamento correto (relatório, avisos, planejamento, solicitações permitidas).

Dois PRs, ambos já mesclados e em produção.

## PR #152 — M7B-W1.3 (remoção de Transferir/Remover + guard backend)

- **Merge:** `99479f8` (commit de trabalho `c269d19`).
- **Backend (`cell_requests.py`):** guard `_reject_member_tipo` retorna **403** na
  **criação** (`POST /cell-requests`) e no **reenvio** (`resubmit`) de
  `transferir_membro` e `remover_membro`. Fecha o bypass direto por API. Aplicado
  **após** a checagem de ownership (não-líder segue 404). NÃO toca
  approve/reject/request-adjustment (a Central ainda decide solicitações legadas) nem
  os tipos permitidos.
- **Frontend (`minha-celula/`):** `DisciplesList.tsx` vira leitura pura (sem botões de
  ação); `SensitiveFieldRequestModal.tsx` perde os ramos transferir/remover, ficando
  com os 5 campos sensíveis permitidos (alterar dia/horário/endereço/anfitrião/
  auxiliar). O **líder não vê** essas ações em nenhum ponto da tela.
- **Deploy validado:** backend na VPS (rebuild só do container backend — mudança
  route-only, health `api.igreja12.com.br/health` = 200) e frontend na Vercel
  (alias `app.igreja12.com.br` = 200). Sem migration/banco/RLS.

## PR #153 — M7B-W1.4 (alinhamento visual da Minha Célula)

- **Merge:** `93e3228` (commit de trabalho `5755634`).
- **Hero de contexto:** nome da célula + agenda (dia · horário) + cobertura + contador
  de membros. Nome via `getMyLedCells`; dia/horário/cobertura via `fetchCellDetail`
  (GET `/cells/{id}`, RLS por tenant) com fallback gracioso — se a leitura falhar, o
  painel segue com nome + contador, sem quebrar.
- **Lista de discípulos:** avatar de iniciais + nome + pill Ativo/Inativo, **somente
  leitura** (nenhuma ação administrativa reintroduzida — mantém a decisão da W1.3).
- **CSS escopado a `.mc-stack`:** o bloco novo (`.mc-hero`, e as regras de
  `.chip-actions`/`.section-foot`) fica restrito à tela do líder. A **Central foi
  preservada** — ela reusa `.chip-actions`, então o escopo evita restilizar seus
  botões de decisão.
- **Deploy Vercel:** deployment `dpl_HXQsun9W5WYUr9BWGWce1KUgta16` (frontend-only), alias
  `app.igreja12.com.br` = 200. Sem tarball/VPS/container/banco/migration.

## Evidências de produção (smoke manual PASS, atestado pelo dono)

- **Líder → Minha Célula:** Célula 1 com agenda/cobertura e **um discípulo ativo**
  (Raniel Levi); **sem Transferir/Remover**; ações permitidas presentes (Planejar,
  Relatório, Avisos, Dados da célula: alterar dia/horário/endereço/anfitrião/auxiliar +
  multiplicação); **mobile sem overflow horizontal**.
- **Admin/pastor → Central de Célula:** tela intacta — Célula 1 seleciona normalmente,
  **`Editar célula`** e **`Convidar membro`** continuam disponíveis; **nenhum efeito
  visual da W1.4 vazou** para a Central.

## Pendências reais (não são bug deste bloco)

Fidelidade total ao protótipo depende de **dados que ainda não existem** na API do líder.
Ficam para missão posterior, não são regressão nem defeito deste bloco:

- **Endereço** da célula e **nº de visitantes** no hero.
- **Papéis/curso por discípulo** (Auxiliar/Anfitrião, "cursando CD").
- **Presença** (bolinhas das últimas reuniões) na lista.
- **Árvore Ministerial / "Minha equipe de 12"** (superfície G12 separada).

## O que ficou resolvido (não reabrir)

- **Transferir/Remover na tela do líder:** **RESOLVIDO** na W1.3 (front + guard backend
  403) e confirmado em produção. Não é pendência.
