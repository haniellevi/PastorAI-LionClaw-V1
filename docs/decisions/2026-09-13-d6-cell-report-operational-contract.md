---
id: D6-CELL-REPORT
document_kind: operational-contract
mission: M-2026-09-13-d6-cell-report-operational-contract
status: CONTRATO_ENTREGUE_REVISAO_UNICA_P1_CORRIGIDO
base_sha: 7a7afa3d08927f3f5b2ed116638aed3131dde88b
environment: local_offline
created_at: 2026-09-13T18:57:21-03:00
---

# D6-CELL-REPORT: contrato operacional de alvo de reunião e consentimento externo

## Decisão

Este é o único contrato D6-CELL-REPORT ativo desta missão. Ele fecha a
interface verificável entre o resolvedor read-only de reunião e o futuro alvo
opaco do coordenador, sem implementar o adaptador, caller, runtime, worker,
webhook, banco, migration, escrita ou envio.

O PR #362 é uma proposta exclusiva de áudio. Seu destino local é ADIADO, a PR
remota permanece intacta, e ela não é requisito nem contrato concorrente deste
recorte. A referência histórica está em
`docs/ops/d6-cell-report-contract/PR362-DISPOSITION.md`.

`tarefas_operacionais` é uma precondição EXTERNA, não uma decisão inferível de
papel, liderança, opt-out, texto inbound ou estado local. Enquanto E4B não
existir como fonte aprovada, auditável e vinculada ao propósito, a única regra
válida é negar. `DenyAllOperationalConsentGate` continua o padrão.

## Princípio de segurança

Uma reunião elegível é um fato de domínio, e não uma autorização de operação.
O futuro adaptador só poderá transformar uma resolução unívoca em um alvo
opaco depois de revalidar os vínculos confiáveis de igreja, ator, inbound e
janela temporal. O alvo não é registro durável, prova de consentimento nem
permissão para gravar. A proposta e a confirmação continuam bloqueadas antes
de qualquer caminho positivo de consentimento.

## Fonte atual e fronteiras preservadas

O resolvedor existente recebe `CurrentUser` autenticado pelo servidor,
requer escopo RLS/tenant e reconfirma acesso ativo, papel ministerial,
liderança, pessoa, reunião e relatório antes de retornar `none`, `candidate`
ou `ambiguous`. Os detalhes verificáveis estão em
`backend/app/services/cell_report_meeting_resolver.py:153-246`,
`backend/app/services/cell_report_meeting_resolver.py:249-305` e
`backend/app/services/cell_report_meeting_resolver.py:430-512`.

O coordenador já aceita somente `CellReportMeetingTarget` opaco. Seu selo
process-local liga igreja, conversa, inbound, turno, ator e reunião, e o
revalida antes do staging. Isso detecta adulteração local, mas não é segredo,
prova durável, autorização ou substituto de fonte externa. Consulte
`backend/app/services/cell_report_whatsapp_coordinator.py:184-210` e
`backend/app/services/cell_report_whatsapp_coordinator.py:371-432`.

A fronteira de finalidade atual nega por padrão porque não há writer aprovado.
Ela exige um `OperationalConsentPermit` opaco e vinculado à solicitação, mas
esse objeto é explicitamente não durável e não serializável. As referências
são `backend/app/services/cell_report_whatsapp_coordinator.py:231-295`,
`backend/app/services/cell_report_whatsapp_coordinator.py:669-727`,
`backend/app/services/cell_report_whatsapp_coordinator.py:740-772` e
`backend/app/services/cell_report_whatsapp_coordinator.py:820-858`.

## Contrato do adaptador da missão sucessora

A missão `M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION`, se autorizada
nominalmente por Raniel, implementará somente um adaptador backend offline. A
entrada permitida será `db`, `CurrentUser`, `AgentTurnIdentity` confiável e
relógio injetado. Ela não aceitará igreja, ator, inbound, reunião, finalidade
ou consentimento do modelo, webhook, texto livre ou caller.

O adaptador deverá seguir esta ordem, toda dentro do mesmo escopo tenant
confiável:

1. validar os IDs canônicos de `CurrentUser` e exigir igualdade exata entre a
   igreja derivada e a igreja de `AgentTurnIdentity`, sem fallback;
2. obter e validar o inbound persistido para derivar ator e conversa, com uma
   fronteira ao menos tão restrita quanto a verificação atual do coordenador;
3. chamar o resolvedor existente com `CurrentUser` e aceitar somente
   `candidate`; `none`, `ambiguous`, erro de escopo, erro de dados ou overflow
   não produzem alvo;
4. conferir que o ator derivado do inbound corresponde ao líder revalidado que
   sustenta a resolução, e emitir apenas o alvo opaco vinculado ao mesmo
   inbound, turno, ator e `reuniao_id`;
5. retornar o alvo apenas ao caminho offline de teste. Não chamar staging,
   proposta, confirmação, UoW, commit, outbox, dispatch, runtime ou rede.

O adaptador não pode reutilizar `_mint_operational_consent_permit`, introduzir
um writer, aceitar `OperationalConsentPermit` de teste, conceder finalidade,
ler `Pessoa.consentimento` ou criar bypass de `purpose_consent`. A fonte E4B
continua externa e ausente. Mesmo com alvo emitido, C09 e C10 permanecem
`BLOCKED_BY_E4B`.

## Critérios de aceite do contrato

- A matriz C01-C10 em
  `docs/ops/d6-cell-report-contract/SCENARIO-MATRIX.md` possui uma única linha
  por cenário, fonte `arquivo:linha`, evidência executada quando disponível e
  limite explícito.
- O cenário positivo não é simulado. C09 e C10 ficam
  `BLOCKED_BY_E4B`, sem skip disfarçado.
- A evidência offline exercita apenas o resolvedor existente, em ambiente
  limpo e sem banco ou rede, e não é apresentada como prova de RLS viva,
  integração WhatsApp ou consentimento.
- A missão não muda `backend/app`, migrations, guardas, manifesto ou flags.
- O PR #362 continua delimitado como áudio adiado. Áudio, transcrição e mídia
  não entram no contrato nem na missão sucessora.

## Rollback

O rollback é exclusivamente documental: antes de qualquer remoção, o revisor
deve comparar o patch e os hashes registrados com o SHA base. Reverter apenas
os caminhos desta missão, preservando a ficha, o recibo de abertura, a
disposição do PR #362 e os recibos de teste. Não usar `reset --hard`, `clean`,
remoção de worktree, alteração de ref, banco ou ação remota.

## Único próximo gate

Raniel autoriza nominalmente
`M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION` depois da revisão independente
deste candidato. O gate permite somente a implementação offline do adaptador e
seus testes de recusa/resolução. Ele não abre E4B, runtime, caller, worker,
webhook, commit, envio, áudio, LLM, banco, migration, DEV, PROD, deploy ou
flags.
