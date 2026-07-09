# Fechamento 7B — 2026-07-09

## Status

Ciclo 7B técnico fechado em main.

## Entrou em main

- #136 Pessoas/CSIM/paginação.
- #137 Pessoas/Comunicação admin-only.
- #139 CSIM pausa IA + AgentConfig.ativo + inbox order.
- #140 Billing: checkout e catálogo lendo tabela planos.
- #141 GRANT UPDATE(dono_id) em igrejas.
- #142 Setup checklist 7B-7.

## Encerrado sem PR

- 7B-4: zero diff. Investigação confirmou que não havia mudança necessária.

## Read-only

- 7B-8: organograma/árvore ministerial entregue como planejamento. Implementação futura separada.

## Decisões registradas

- Checkout Asaas permanece interno.
- Catálogo de planos agora vem da tabela `planos` para UI/checkout.
- Autoupgrade de billing ainda segue trigger SQL hardcoded.
- CSIM fica fora do funil pastoral e do atendimento IA recorrente.
- `AgentConfig.ativo` agora pausa o agente.
- Pessoas e Comunicação foram movidas para superfície admin.
- Setup checklist não bloqueia uso; apenas lista pendências reais.

## Pendências futuras

- Árvore ministerial/G12 profunda.
- QA visual autenticado completo.
- Limpeza dos worktrees antigos.
