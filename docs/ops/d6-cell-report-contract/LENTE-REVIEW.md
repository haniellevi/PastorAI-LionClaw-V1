# LENTE: parecer da única rodada independente

Missão: M-2026-09-13-d6-cell-report-operational-contract.
Revisora: LENTE, gpt-5.6-terra max, sessão distinta da FORJA.
Modo: somente leitura/offline, worktree própria
`.worktrees/d6-cell-report-contract-review-20260913`.
Referência temporal da inspeção: 2026-09-13T19:27:12-03:00.
Base: `7a7afa3d08927f3f5b2ed116638aed3131dde88b`.
Patch integral revisado: `ba11308867c7a418ea18e0e1ffc53ee3db8e30ef2524b171811b3f0b7a4f87e2`.
Fonte: parecer devolvido no terminal LENTE, capturado pelo Orquestrador.
Rodada 1 de no máximo 1; nenhuma segunda revisão autorizada nesta missão.

## Veredito sobre o candidato acima: NAO APTO

A1, A3, A4 e A5 aptos no recorte documental. PR362 adiado como áudio-only,
consentimento externo deny-all, C09/C10 BLOCKED_BY_E4B e backend preservado.
A2 apto como contrato comportamental; a sucessora precisa explicitar
`now=clock` e testar os vínculos do alvo.
A6 depende de resolver o bloqueador A7.

## P1 bloqueador, critério A7

Em `docs/ops/d6-cell-report-contract/FINAL-REPORT.md:97`, a descrição da
sucessora se limita a implementar e testar offline o adaptador.
Faltam arquivos de implementação, módulos de teste, dependências e casos
de aceite executáveis.

Correção exigida pela LENTE: acrescentar no mesmo relatório um recorte
executável, derivado do contrato existente em
`docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:64`,
sem alternativas pendentes, incluindo:

- arquivos exatos do adaptador e do mint do alvo opaco;
- arquivos de teste exatos;
- CurrentUser, AgentTurnIdentity, resolvedor, validação do inbound,
  alvo opaco, RLS e relógio injetado como dependências delimitadas;
- tenant divergente, inbound ausente/adulterado, ator divergente, none,
  ambiguidade, overflow, limite temporal com now=clock e alvo vinculado
  ao mesmo inbound, ator e reunião;
- proibições de writer, permit positivo, _mint_operational_consent_permit,
  bypass de purpose_consent, staging, UoW, commit, runtime, rede e C09/C10.

## Evidência confirmada pela LENTE

16 arquivos, incluindo 11 não rastreados, byte-idênticos ao inventário
`CANDIDATE-INDEX.json` do controle. Hash integral do patch confirmado.
Hash semântico `7e27d897eee3696d0a985fc5ee169857de69368d0fccaab267dfd4680d642059`
e normalizado `88ffb8fb186f1f7b81cd66d708f1812513aefd3ff4117006df4dbd90c7320ad8`
reproduzidos. `git diff --check` passou, sem diff em backend ou manifesto.
Recibos confirmam 17 testes, zero falhas/erros/skips e zero guard_denials.

LENTE não executou pytest, não importou produto, não escreveu arquivos,
não acessou banco, rede, hooks, runtime, credenciais ou PROD.
QA visual não se aplica: nenhum fluxo ou UI alterado.

## Tratamento do achado

Este parecer permanece referente ao candidato exato acima.
Correção pela FORJA e verificação objetiva pelo Orquestrador são a continuação
da mesma missão prevista na ficha; não serão rotuladas como novo parecer APTO
da LENTE. A worktree de revisão preserva o candidato original.

Gate humano único permanece: Raniel autorizar nominalmente
`M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION` após correção e aceite
do contrato; a implementação não está autorizada nesta missão.
