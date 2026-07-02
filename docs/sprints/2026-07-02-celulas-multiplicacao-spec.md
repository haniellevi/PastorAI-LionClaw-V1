# Células — Multiplicação: registro da especificação — 2026-07-02

**Branch:** docs/celulas-multiplicacao-spec  ·  **Commits:** (ver PR)  ·  **Deploy:** não (docs-only)

## O que foi feito
- Auditoria do módulo `multiplicacoes` existente e registro da especificação de
  **Multiplicação de Célula** (solicitação → aprovação da Central de Células).
- Doc de design: `docs/design/CELULAS-MULTIPLICACAO-solicitacao-aprovacao.md`
  (fluxo, permissões, status, entidades, endpoints, validações, riscos, PRs,
  decisões abertas).
- **Nada de código.** Sem backend/frontend/migration/env/worker.

## Decisões (fixadas pelo dono do produto)
- **Evoluir** `multiplicacoes` (tabela/router/domain); **não** criar
  `cell_multiplication_requests` paralela.
- Solicitação **nasce `pendente`**; novo enum `pendente/em_analise/aprovada/
  rejeitada/cancelada`.
- **Aprovação = 1 transação**: cria célula, define líder, move membros, grava
  dia/hora/endereço/anfitrião, atualiza organograma/cobertura, concede gestão.
- Rejeição/cancelamento não cria célula nem move membros (rejeição grava motivo).
- **Aptidão** vira regra explícita (não esconder em `etapa='enviar'`).
- **Central de Células** precisa de papel real (`lider_central`); `pastor/lider_g12`
  é fallback temporário.

## Achado que condicionou tudo
- `multiplicacoes` **já existe mas é stub**: `aprovar` só troca status; não cria
  célula, não move membros, não mexe no organograma. O enum atual
  (`agendada/sem_agendamento/aprovada/concluida`) difere do fluxo pedido → migração
  de enum necessária (custo baixo: `0007_remove_demo_data` zerou os dados e o módulo
  não foi a produção com dados reais).

## Pendente / próximo passo
- Fechar **Decisões Abertas** antes de PR4/PR5:
  - **A.** como modelar aptidão (recomendado: flag explícita em `pessoas`);
  - **B.** papel da Central de Células (`lider_central` real vs fallback);
  - **C.** cobertura espiritual/organograma da nova célula (herda da origem ou do
    novo líder).
- Implementação em 6 PRs pequenos (PR1 schema → PR6 frontend), ver o doc de design.

## Verificação
- Docs-only: sem testes/build. Doc ancorado por leitura direta do código
  (`routers/multiplicacoes.py`, `domain/multiplication.py`, `db/models.py`,
  `migrations/0004_triggers.sql`, `db/rls.py`).
