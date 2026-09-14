# Matriz C01-C10 do contrato D6-CELL-REPORT

Ambiente: `local/offline`. Base: `7a7afa3d08927f3f5b2ed116638aed3131dde88b`.
Execução focal: `2026-09-13T18:57:15-03:00` a
`2026-09-13T18:57:16-03:00`, 17 aprovados, sem recusas do runner. O recibo
gerado é `pytest-resolver.json` e o JUnit é `pytest-resolver.xml`.

Estados usados:

- `VERIFICADO_OFFLINE`: o comportamento indicado foi exercitado no teste
  identificado, com dados sintéticos e sem banco/rede. Não demonstra ambiente
  vivo, RLS viva, caller, consentimento ou persistência.
- `EXPECTATIVA_DOCUMENTADA`: a regra é exigência do contrato e possui fonte
  source-only, mas a totalidade do cenário não foi exercitada nesta missão.
- `BLOCKED_BY_E4B`: o caso depende de concessão externa aprovada de
  `tarefas_operacionais`. Não foi executado, simulado ou marcado como skip.

| ID | Cenário | Expectativa fechada | Evidência e fonte | Estado | Limite |
|---|---|---|---|---|---|
| C01 | Reunião fora da igreja confiável | Nenhum candidato é retornado quando os tenants de reunião e célula divergem do tenant server-bound. | Consulta e checagem em `backend/app/services/cell_report_meeting_resolver.py:249-305` e `backend/app/services/cell_report_meeting_resolver.py:340-362`; caso em `backend/tests/test_cell_report_meeting_resolver.py:152-175`; execução em `docs/ops/d6-cell-report-contract/pytest-resolver.json:4-26`. | `VERIFICADO_OFFLINE` | Fake session e monkeypatch de escopo no teste não provam RLS PostgreSQL nem emissão de alvo. |
| C02 | Ator sem responsabilidade válida | Acesso inativo, duplicado, ausente ou sem papel ministerial não deve escolher ator nem produzir candidato. | Revalidação em `backend/app/services/cell_report_meeting_resolver.py:153-246`; subconjunto inativo/duplicado em `backend/tests/test_cell_report_meeting_resolver.py:371-390`; execução em `docs/ops/d6-cell-report-contract/pytest-resolver.json:4-26`. | `EXPECTATIVA_DOCUMENTADA` | A execução não possui caso dedicado de ausência de papel ministerial; não declara o cenário inteiro verificado. |
| C03 | Reunião ausente | Resultado é `none`, sem alvo, quando não houver candidato elegível. | Resultado fechado em `backend/app/services/cell_report_meeting_resolver.py:145-150` e `backend/app/services/cell_report_meeting_resolver.py:401-427`. | `EXPECTATIVA_DOCUMENTADA` | A execução focal não possui caso dedicado de conjunto vazio após todas as revalidações. |
| C04 | Duas reuniões elegíveis | Resultado é `ambiguous`, com ordem determinística e sem seleção silenciosa. | Ordenação em `backend/app/services/cell_report_meeting_resolver.py:401-427`; caso em `backend/tests/test_cell_report_meeting_resolver.py:178-198`; execução em `docs/ops/d6-cell-report-contract/pytest-resolver.json:4-26`. | `VERIFICADO_OFFLINE` | Não emite `CellReportMeetingTarget` nem inicia staging. |
| C05 | Alvo de outro inbound/ator ou janela inválida | Divergência de inbound, ator, tenant ou tempo deve impedir emissão/uso do alvo antes de operação. | Janela e vínculos em `backend/app/services/cell_report_meeting_resolver.py:308-398`; inbound/ator em `backend/app/services/cell_report_whatsapp_coordinator.py:568-648`; alvo revalidado em `backend/app/services/cell_report_whatsapp_coordinator.py:403-432`; subconjunto no teste `backend/tests/test_cell_report_meeting_resolver.py:152-175`. | `EXPECTATIVA_DOCUMENTADA` | Não há adaptador entre resolvedor e alvo neste SHA; o teste focal não executa a ligação inbound para alvo. |
| C06 | Consentimento ausente ou gate indisponível | Negar antes de proposta ou confirmação, sem writer, gravação ou concessão. | Gate em `backend/app/services/cell_report_whatsapp_coordinator.py:282-295`; fail-closed em `backend/app/services/cell_report_whatsapp_coordinator.py:669-692`; pré-staging em `backend/app/services/cell_report_whatsapp_coordinator.py:740-772` e `backend/app/services/cell_report_whatsapp_coordinator.py:820-858`; teste não executado em `backend/tests/test_cell_report_whatsapp_coordinator.py:310-337`. | `EXPECTATIVA_DOCUMENTADA` | A suíte do coordenador contém gates permissivos de teste e foi deliberadamente excluída desta missão. |
| C07 | Consentimento retirado ou finalidade divergente | Negar. Papel, liderança, opt-out ou outro propósito não substituem `tarefas_operacionais`. | Finalidade em `backend/app/services/cell_report_whatsapp_coordinator.py:231-245` e `backend/app/services/cell_report_whatsapp_coordinator.py:651-666`; revalidação em `backend/app/services/cell_report_whatsapp_coordinator.py:669-727`; fonte externa em `docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:25-28`. | `EXPECTATIVA_DOCUMENTADA` | Não existe fonte E4B nem writer de teste autorizado. |
| C08 | Validade ou proveniência não comprovada | Negar. Não presumir expiração, prova ou proveniência que o domínio externo não forneça. | Permit não durável em `backend/app/services/cell_report_whatsapp_coordinator.py:248-268`; validade em `backend/app/services/cell_report_whatsapp_coordinator.py:457-485`; E4B ausente em `docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:25-28`. | `EXPECTATIVA_DOCUMENTADA` | A validação de permit local não satisfaz catálogo, ledger ou recibo externo. |
| C09 | Proposta que exige consentimento concedido | Não executar proposta positiva. | Gate em `backend/app/services/cell_report_whatsapp_coordinator.py:282-295`; proposta após permit em `backend/app/services/cell_report_whatsapp_coordinator.py:740-772`; bloqueio em `docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:88-92`. | `BLOCKED_BY_E4B` | E4B é fonte externa ausente. Nenhum permit, writer ou monkeypatch positivo foi criado. |
| C10 | Confirmação/persistência que exige consentimento concedido | Não executar confirmação, UoW, persistência ou resposta positiva. | Gate em `backend/app/services/cell_report_whatsapp_coordinator.py:282-295`; confirmação após permit em `backend/app/services/cell_report_whatsapp_coordinator.py:820-858`; bloqueio em `docs/decisions/2026-09-13-d6-cell-report-operational-contract.md:88-92`. | `BLOCKED_BY_E4B` | E4B é fonte externa ausente. Nenhuma confirmação positiva foi simulada. |

Esta matriz é evidência de aceite do contrato, não um segundo contrato e não
altera comportamento do produto.
