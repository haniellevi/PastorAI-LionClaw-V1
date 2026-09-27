# Revisão independente, V2a C05

**Candidato:** base `3e8306e9dfd5e3dec3097f3e8a701829b4d7aa36`; delta após `d4bf0f5ac6595ea914344a0b86d3c5f20691deda`; patch SHA-256 `6c27a42401f13bb44bb60d422c8814a9115a02be2bd580b11d891d1d1b84b953`.

**Integridade:** os 8 blobs de `V2A-CANDIDATE-05.json` conferem byte a byte. Hashes principais: catálogo `b647231e`, roteador `8f54b4d5`, turno `c49a5739`, teste de roteamento `40185bae` e teste PG `f4fe7c5b`.

## Resultado

**APTO técnico, delimitado ao candidato C05.** Não encontrei P0, P1 ou P2 reproduzível neste delta.

O catálogo cria a capacidade genérica somente após os gates servidor-side de Agenda e papel, com alvo sem argumentos e mapeamento exclusivo `("consultar_agenda", None)` ([agent_privilege_catalog.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/agent_privilege_catalog.py:203)). O roteador aceita candidatos vazios apenas para essa ferramenta fechada, faz B e C, retorna `selected` sem handle e não chama D ([agent_privilege_routing.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/agent_privilege_routing.py:174), [agent_privilege_routing.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/agent_privilege_routing.py:292)). Catálogos vazios e ações sem alvo continuam em handoff antes do modelo ([test_agent_privilege_routing.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/tests/test_agent_privilege_routing.py:116)).

Após B/C, o turno procura o par exato ferramenta/handle, reconstrói o catálogo sob a sessão atual e só então resolve a projeção de Agenda ([privileged_turn.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/agent/privileged_turn.py:1113), [privileged_turn.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/agent/privileged_turn.py:1159)). Assim, um mapeamento forjado, uma revogação de papel ou o fechamento do gate não se convertem em leitura. A revalidação pré-transporte recompõe a projeção ancorada e suprime resposta pendente se o evento mudar ([whatsapp_agenda.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/app/services/whatsapp_agenda.py:510)).

As E2E de membro e líder usam catálogo, roteador e turno reais. O fake restringe-se à escolha tipada e ao transporte; exige os dois estágios B/C, falha se D for chamado, compara o texto efetivamente entregue com a `Message`, e confirma ledger e estado `ia` ([test_whatsapp_agenda_pg.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/tests/test_whatsapp_agenda_pg.py:216), [test_whatsapp_agenda_pg.py](/tmp/igreja12-v2a-agenda-review-20260927/backend/tests/test_whatsapp_agenda_pg.py:270)).

## Evidência consultada

- RED de controle C04: 2 falhas esperadas, ambas por chamada indevida a `s3_handle`, em `/tmp/v2a-c05-e2e-red.xml`.
- C05 PG: 36 passed, 0 failures, 0 errors, 0 skips, em `/tmp/v2a-pg-c05.xml`.
- C05 offline: 5887 passed, 643 deselected, 0 skips, em `/tmp/v2a-offline-c05.xml`.

Não executei banco, rede ou provedor. A evidência valida o SHA congelado em ambiente sintético; não autoriza flag, deploy, envio externo ou produção. O controle legado com handle `h1` passou e não há base para concluir que toda Agenda anterior era inalcançável.
