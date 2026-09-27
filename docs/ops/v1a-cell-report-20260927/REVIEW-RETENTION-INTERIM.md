# Revisão V1a, retenção de proposta e rascunho

**Estado:** NÃO APTO neste recorte. A limpeza exigida para término de proposta ainda não está ligada aos caminhos terminais.

## Escopo conferido

| Arquivo | SHA-256 |
| --- | --- |
| `backend/app/services/cell_report_reminders.py` | `83eaef93a21bc2a7b11050b5f99516f939b198c59567c2c4b0d4268ff04ae2a5` |
| `backend/app/services/cell_report_v1a_service.py` | `5957bf7bd2e09cd9f11872f73f921c27382383f01f788cde50be3a3fb1747740` |
| `backend/app/services/agent_action_proposals.py` | `b742fe05473637e3342bf19609fee89fb6d4b03a522b23d8d8aba867bca64d28` |
| `backend/app/services/conversation_handoff.py` | `bad994b80cdc6e54f43290a6dc1c7975007562ff448e097045f435ebfbc5bfc4` |
| `backend/app/agent/privileged_turn.py` | `710a23dc5f1faf3e573bd9634d0cb9b641607d059ab8a2184c803207755730e6` |
| `backend/app/db/models.py` | `be2f6f7bfa01d2a7a7dc6a0c49be6e4ab2dd7ad751ae27e4f52a20a73a96ac53` |

O contrato aplicável está nas linhas 20, 21 e 26 do plano: prazo de proposta de dez minutos, limpeza do conteúdo de rascunho e resumo pendente em até uma hora do término, e exclusão de revisões privadas no cancelamento ou em no máximo 24 horas. O histórico de resumo efetivamente entregue e o relatório oficial têm retenção distinta.

## P1, término não limpa o rascunho nem o resumo pendente

`resolve_and_execute_action_proposal()` transforma NÃO, outro inbound e expiração em estado terminal, mas `_set_terminal()` só grava estado, motivo, confirmação e `expires_at` nulo. A mudança de termo segue o mesmo caminho. `fence_agent_replies_for_handoff()` também só cancela a proposta ativa e muda o estado do outbound; não toca no `CellReportDraft`.

O único sweep de conteúdo seleciona apenas drafts ainda ativos cujo próprio `expires_at` de 24 horas venceu. Ele não seleciona `AgentActionProposal`, não deriva o rascunho a partir da proposta terminal e não atualiza `Message`. Portanto, após uma proposta V1a entregue receber NÃO, ou após SAIR, humano, revogação, termo alterado, expiração ou invalidação antes do transporte, o `candidate_json` e o `candidate_sha256` do draft podem ficar em estado `pronto` até 24 horas. Isso excede o limite de uma hora.

O resumo que nunca foi entregue permanece em `Message.texto`: a fence muda apenas `agent_reply_state`, e `invalidate_action_proposal_for_delivery()` apenas terminaliza a proposta. A exclusão desse tipo de mensagem do histórico enviado ao LLM está correta, porém ela não remove o conteúdo persistido.

Reprodução fonte: crie relatório completo, entregue o resumo e responda NÃO. A proposta fica `rejeitada` em `agent_action_proposals.py:1039-1050`, enquanto o draft só é elegível ao sweep em `cell_report_reminders.py:881-899` quando o TTL de 24 horas vencer. A mesma separação existe para cancelamento por termo, handoff ou invalidação antes de transporte.

Correção mínima recomendada: um helper V1a chamado dentro da transação que já possui o lock de `Conversation`, apenas para `enviar_relatorio_celula`. Ele deve terminalizar o draft correspondente, apagar `candidate_json` e `candidate_sha256`, e preencher `terminal_at` e `content_purged_at`. A expiração sem novo inbound exige que o sweep também selecione propostas V1a pendentes vencidas, as terminalize e invoque a mesma limpeza. Não convém tornar o terminalizador S3 genérico responsável por apagar todo tipo de dado de outras ações.

Para resumo não entregue, o helper deve apagar `Message.texto` quando o ledger prova que o envio não foi confirmado, preservando `agent_privilege_context`, IDs, hashes, estado e motivo como tombstone mínimo. Resumo confirmado, `AgentActionReceipt` e `CelulaReuniao` não devem ser apagados neste fluxo. O estado ambíguo requer uma regra explícita, pois não prova ausência de entrega e não deve ser tratado como resumo nunca enviado por suposição.

## P2, limite de manutenção pode postergar indefinidamente a limpeza

`_purge_tenant_state()` contabiliza primeiro todos os claims expirados, sem limite, e somente depois consulta drafts com `limit - changed`. Em seguida, o laço global encerra quando `changed >= limit`. Uma fila grande de claims ou reminders em uma igreja pode consumir o orçamento inteiro e impedir a seleção de drafts expirados daquela igreja e das seguintes, mesmo que o job seja executado no prazo.

Reserve capacidade para limpeza de conteúdo, priorize drafts vencidos antes de manutenção de reminder, ou use cursor independente por tipo de registro. A prova precisa conter mais itens de outbox que o limite e ao menos um draft expirado em cada um de dois tenants.

## P2, a prova nova não mede o prazo exigido nem o resumo pendente

`test_terminal_proposal_content_is_purged_within_one_hour()` usa `proposal.expires_at + 61 minutos`. Nos casos NÃO e SAIR, essa referência pode ocorrer mais de uma hora após o término que deveria iniciar a retenção. A prova também conserva deliberadamente a mensagem entregue, correto para o histórico privado, mas não cria um resumo suprimido ou não entregue para verificar a remoção de `Message.texto`.

O teste deve medir a partir de cada evento terminal, com limpeza imediata ou no máximo sessenta minutos depois. Cobrir: NÃO, SAIR, humano, revogação, termo alterado, expiração sem inbound e entrega inválida antes do transporte; cada caso deve verificar draft limpo, proposta tombstoned, mensagem pendente limpa quando aplicável, e resumo confirmado preservado. Acrescentar um caso tenant A versus B e o cenário de saturação do limite fecha o contrato de isolamento e SLA.

## Pontos preservados e limites

O histórico comum já filtra mensagens privilegiadas, portanto o resumo de ação não entra posteriormente no prompt não privilegiado. `agent_privilege_context` contém somente identificadores opacos, fingerprint, tipo e IDs de proposta/prova, apropriados para o tombstone. Os FKs de proposta, recibo e draft usam cascata para conversa, mensagem, pessoa e reunião, mas esta leitura não substitui uma prova PG de reset ou exclusão de tenant.

Não executei banco, cron, transporte ou provedor. Este parecer não autoriza deploy, envio ou retenção operacional até que o delta de limpeza e suas provas sejam revistos no candidato congelado.
