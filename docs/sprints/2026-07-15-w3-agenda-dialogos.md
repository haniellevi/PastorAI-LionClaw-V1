# Wave Visual W3 — Agenda e diálogos — 2026-07-15

**Branch:** `worktree-w3-agenda-dialogos`  ·  **Commits:** `023d46a`  ·  **PR:** [#174](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/174) (DRAFT)  ·  **Deploy:** não

## O que foi feito

1. **Descoberta read-only** (conversa paralela, sem edição): inventário completo da Agenda e de
   todos os 24 diálogos/modais do frontend, contra `origin/main` `e9b38b1`. Achados: 2 blockers
   (modais da Agenda sem `ds/Dialog` — zero ESC/trap/scroll-lock/retorno de foco; criar evento
   clicando no dia era mouse-only) + 7 achados importantes/polish. Registrado em memória:
   `pastorai-w3-agenda-dialogos-descoberta.md`.
2. **Decisão de escopo do dono**: só os 3 diálogos da Agenda (não os outros 14 modais legados);
   teclado nas células de dia; labels/erros dos cards de Integrações; sem tocar `EquipeScreen`/
   papéis/W2; sem criar `Skeleton`.
3. **Implementação** (worktree novo a partir de `origin/main` `e9b38b1`):
   - `EventFormModal.tsx`, `EventDetailModal.tsx`, `ConfirmEventModal.tsx` migrados para o
     primitive `ds/Dialog`, seguindo o padrão mecânico já usado em 7 diálogos do produto.
   - `CalendarioScreen.tsx`: `dayCellActivation()` torna a célula do dia acionável por
     Enter/Espaço (mesmo padrão de `eventActivation()`), sem `role="button"` no container (evita
     aninhar com os chips de evento, que já são `role="button"`).
   - `AlertRecipientsCard.tsx`: `<label className="sr-only">` nos campos Nome/Telefone +
     `role="alert"` no erro. `CalendarConnectCard.tsx`: `role="alert"` no erro.
   - 4 arquivos de teste novos (`*.test.ts`), 15 casos: foco inicial/ESC/busy-guard de cada
     diálogo migrado + teclado da célula do dia + guarda contra `role="button"` aninhado.

## Decisões

- Manter `Cancelar`/`modal-foot` DENTRO do `<form>` (não usar a prop `footer` do primitive) nos
  dois diálogos com formulário (`EventFormModal`, `ConfirmEventModal`) — mesmo padrão de
  `PlanMeetingModal.tsx`, preserva submit por Enter no formulário.
- `EventDetailModal` (sem form) usa a prop `footer` — mesmo padrão de `DeleteConversationDialog`/
  `TransferConversationModal`.
- `autoFocus` nativo do campo Título → `data-autofocus=""` (contrato do primitive para foco
  inicial custom; sem isso o foco iria pro botão-X do cabeçalho).
- `onClose` de todos os 3 ganhou a guarda `if (!busy)` — muda o comportamento de fechar-por-ESC/
  clique-fora/botão-X durante salvamento (antes só o "Cancelar" tinha essa trava) — decisão
  deliberada de seguir o padrão já estabelecido nos 7 diálogos de referência, não um efeito
  colateral acidental.

## Pendente / próximo passo

- PR #174 ainda **DRAFT** — falta revisão humana, ready, merge, deploy e smoke autenticado.
- `AlertRecipientsCard`/`CalendarConnectCard` sem teste automatizado dedicado (mudança de 1 linha
  cada; verificado ao vivo no browser, não coberto por `vitest`).
- Não deployado — nada em produção mudou.
- Os outros 14 modais legados (Fase 6 do plano mestre) seguem intocados, fora desta wave.

## Verificação

- `vitest run`: 118/118 verde (15 novos).
- `tsc --noEmit`: 0 erros. `next lint`: sem warnings. `next build`: verde.
- `git diff --check`: sem erros de whitespace. Varredura manual de segredos: nada encontrado.
- Revisão adversarial (3 lentes, subagentes independentes): contrato PASS (2 divergências
  documentadas e inerentes ao padrão aprovado), acessibilidade — 1 achado real (`role="button"`
  aninhado nas células de dia) **corrigido** antes do commit, escopo PASS (zero vazamento).
- Prova visual desktop (1280px) + mobile (≤860px): via inspeção de DOM/CSS computado em browser
  real (dev server local sem backend, fetch interceptado no cliente) — screenshot por pixel
  indisponível nesta sessão (`computer screenshot`/`zoom` travaram; tooling, não código).
