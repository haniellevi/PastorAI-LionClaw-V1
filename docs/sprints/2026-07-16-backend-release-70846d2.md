# Release de backend — 70846d2 — 2026-07-16

**Commit:** `70846d2` (`origin/main`)  ·  **Deploy:** sim, produção

> Escopo deste registro: só o fato do release e as confirmações abaixo. Não
> inclui hostname, IP, caminho local/remoto, nome de container, comando de
> implantação, URL interna ou qualquer outro detalhe operacional.

## Escopo funcional

Release de backend em produção no commit `70846d2`, que inclui as seguintes
correções (já mergeadas em `origin/main`, ancestrais do commit do release —
confirmado via `git log 82e1c6f..70846d2`, ambos os merges listados):

- **SEC-ALTO-003** — fonte única para `CENTRAL_ROLES` (PR#181, merge `6baf893`).
  `backend/app/routers/cells.py` e `backend/app/routers/cell_meetings.py`
  removem a definição local duplicada e passam a importar a constante de
  `backend/app/deps.py`, único ponto de definição. Sem mudança de valor, rota,
  permissão ou migration.
- **SEC-ALTO-004** — hardening do OAuth state do Google Calendar (PR#182,
  merge `cd2f918`). `GoogleOAuthClient.verify_state`
  (`backend/app/services/google_oauth.py`) delega a verificação de
  assinatura/algoritmo/issuer/claims obrigatórias a
  `ClerkClient.verify_purpose_token` — a mesma política endurecida já usada
  para os tokens de sessão/reset/invite — com issuer dedicado
  `pastorai-gcal-oauth`, pinando o state ao seu propósito e impedindo troca
  por outro tipo de token mesmo compartilhando o mesmo segredo de assinatura.

## Verificação

- Health check público: **200**, confirmado pelo responsável após o release.
- Runtime das duas correções acima verificado no container em produção pelo
  responsável.
- Smoke autenticado: login e carregamento do Painel de Hoje confirmados em
  produção, sem escrita.
- Confirmado neste registro (leitura de código, não apenas relato): o código
  de `CENTRAL_ROLES` fonte única e do `verify_purpose_token`/issuer
  `pastorai-gcal-oauth` está presente no working tree de `70846d2` (ver
  `backend/app/deps.py`, `backend/app/routers/cells.py`,
  `backend/app/services/google_oauth.py`); cobertura de teste do state OAuth
  em `backend/tests/test_calendar_oauth.py` (assinatura adulterada, segredo
  errado, expirado, issuer errado, claim obrigatória ausente, purpose errado,
  token de sessão não reutilizável como state).
- Nenhuma migration nova entre `82e1c6f` e `70846d2` — **MSG-IDEMP-1** e
  **CONSOL-1** não fazem parte deste deploy e não foram reaplicadas.
- Nenhuma exposição de segredo identificada neste release (sem credencial,
  token ou chave em diff, log ou documento).

## Nota de escopo da verificação

Este registro comprova que o commit `70846d2` foi publicado em produção. As
checagens de runtime acima cobrem especificamente **SEC-ALTO-003** e
**SEC-ALTO-004** — não constitui verificação runtime separada para nenhuma
outra correção de código que também esteja contida neste mesmo commit (por
exemplo, o restante do trabalho de migração de diálogos admin/W4A/W4B
incluído no mesmo release, que é frontend e fora do escopo de segurança
deste registro).

## Pendente / próximo passo

Nenhum item de código pendente vinculado a este release. Backlog de segurança
restante (ALTO-003/ALTO-004 já concluídos com este release; demais itens) em
`docs/security/2026-07-08-seg-igreja12-remediation-plan.md`.
