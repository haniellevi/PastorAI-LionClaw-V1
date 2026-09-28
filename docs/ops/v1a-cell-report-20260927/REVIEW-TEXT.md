# Revisão V1a, vertical de texto

**Veredito:** APTO técnico, delimitado à cadeia de texto V1a revisada. Não há P0, P1 ou P2 abertos neste recorte.

## Candidato conferido

Base declarada: `f2a532a9cadba44a31e3d3067125a9e2b624c233`.

| Arquivo | SHA-256 |
| --- | --- |
| `backend/app/agent/privileged_turn.py` | `710a23dc5f1faf3e573bd9634d0cb9b641607d059ab8a2184c803207755730e6` |
| `backend/app/services/cell_report_v1a_service.py` | `5957bf7bd2e09cd9f11872f73f921c27382383f01f788cde50be3a3fb1747740` |
| `backend/app/services/cell_report_finalizer.py` | `e222e204d92933e7d0078cfdb660ed8d03e2d5c23e39b060676dbbd4b5b9a537` |
| `backend/app/db/models.py` | `be2f6f7bfa01d2a7a7dc6a0c49be6e4ab2dd7ad751ae27e4f52a20a73a96ac53` |
| `backend/app/domain/cell_report_v1a.py` | `fbaf1f6b881cecdee7b97306ea60778f5fb26a85d9683f0d9b1b55f9f714f007` |
| `backend/app/services/cell_report_whatsapp.py` | `b5816383ebe4dbb50f40047fda8f2b84bf901d0cc1fd700cd340eb046abb2f6e` |
| `backend/app/services/agent_action_proposals.py` | `b742fe05473637e3342bf19609fee89fb6d4b03a522b23d8d8aba867bca64d28` |

## Cadeia revisada

A entrada é limitada ao texto agregado e não conserva observações nem texto livre no rascunho ou no resumo. O rascunho, a reunião, a célula, a liderança atual, o consentimento LGPD e o tenant são relidos sob locks antes da proposta e novamente antes de transporte e execução. A confirmação usa a proposta entregue, o hash do resumo e o recibo idempotente; a finalização usa apenas os quatro agregados e não abre transação durante transporte.

A correção anterior da integridade foi fechada em dois pontos. A correção parcial agora verifica `candidate_json` contra `candidate_sha256` antes de fazer merge. Se divergir, purga e terminaliza o rascunho. O novo `persist_before_handoff` faz commit desse terminal antes de encaminhar a conversa, evitando o rollback que restaurava o rascunho corrompido. O handoff posterior cerca a resposta reservada e as propostas ativas. Isso preserva falha fechada sem produzir novo resumo, proposta ou efeito.

O cenário tratado é P2 de integridade, não execução silenciosa de valor diferente do resumo já aceito: sem a correção, a revisão poderia recalcular e mostrar o valor adulterado antes do novo SIM. Ainda assim, aceitar um rascunho com digest divergente quebra a fronteira de integridade e a correção é necessária.

## Evidência recebida

O root informou 11/11 cenários PG E2E verdes após o delta, incluindo corrupção de JSON/hash, persistência em nova sessão após handoff, SIM posterior sem efeito, TTL, concorrência e flag inerte. A suíte RLS do snapshot anterior foi informada como 415/415 sem skips. Não executei banco nem provedores nesta revisão.

## Limites

Este parecer não aprova lembretes, orçamento, extração por LLM, áudio, purga agendada ou o finalizador comum humano, que permanecem fora do recorte. Também não prova deploy, ativação de flag, egress real ou operação em ambiente compartilhado.
