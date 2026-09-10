# E4b C3, persistência isolada

## Estado e limite

Esta entrega é o candidato C3-IMPLEMENT para
`feat/e4b-c3-persistence-v1`, sobre o commit
`c151c73c2768c7af9193c17b2707d47a42ffb7cc`. A especificação congelada é
`docs/superpowers/specs/2026-09-10-e4b-c3-persistence-specification.md`,
SHA-256 `4da3aec66152aca4aa6513de47daa3740ac2f145332af7ec859ae0e350d228a2`.

`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false`. Não há
caller, principal operacional, runtime, aplicação de migration, banco
compartilhado, DEV, PROD, commit, push, merge, deploy ou ativação autorizados
por este artefato.

## Contrato implementado

A migration draft `backend/migrations/20260910_142830_add_e4b_consent_persistence.sql`
declara intent V1 `TENANT` com `affected_relations` em ordem lexicográfica,
exigida pelo autor:

1. `public.e4b_consent_hold_events`
2. `public.e4b_consent_holds`
3. `public.e4b_consent_operations`
4. `public.e4b_consent_receipts`
5. `public.e4b_consent_retentions`
6. `public.e4b_consent_streams`

O DDL físico permanece na ordem R4: operations, streams, receipts, retentions,
holds e hold_events. A ordem declarativa da intent não altera a ordem física de
criação.

Cada relação é tenant-scoped por `igreja_id`, tem RLS habilitada e forçada, e
recebe as policies permissiva e restritiva `FOR ALL TO PUBLIC` vinculadas
somente a `app.tenant_igreja_id`. O SQL revoga privilégios de `PUBLIC` e,
condicionalmente à existência, de `anon`, `authenticated`, `service_role` e
`agent_runtime`; ele não cria roles e não concede ACL operacional.

O preflight falha antes do primeiro DDL C3 quando faltar `igrejas(id)` UUID com
chave validada, ou uma das chaves parentais compostas de Pessoa e AppUser. A
variação negativa do oráculo cria uma raiz sintética sem essa chave e exige a
falha anterior à criação de `e4b_consent_operations`.

Nesta etapa C3, `RETENTION_ELIGIBLE` não é persistível. Sem hold ativo, a
projeção deriva sempre `RETENTION_RUNNING`; a tentativa direta de elegibilidade
é recusada pela guarda de imutabilidade. Uma capability humana server-owned,
com verificação de prazo, pertence a protocolo futuro e não é criada aqui.

As decisões de segurança vinculadas à intent são
`docs/decisions/2026-08-28-d2b2b1-consent-security-boundary.md` e
`docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md`.

As cinco guardas internas são `SECURITY INVOKER`, sem `SECURITY DEFINER` e sem
`EXECUTE` direto: imutabilidade, autoridade histórica, transição de stream,
projeção de hold e completude da cadeia. Os sete constraint triggers permanecem
`AFTER`, `DEFERRABLE INITIALLY DEFERRED` e `FOR EACH ROW`, com a matriz de
eventos R4. Nenhuma guarda consulta ou usa o ledger legado.

## Porta source-only

`PostgresE4bConsentStagingAdapter` recebe sessão, tenant, transação e
`lock_timeout` já definidos pelo owner externo. Ele não cria conexão, caller,
capability, commit, rollback, begin ou close. Consentimento adquire K, L, C e
stream com os seeds `2026091001` a `2026091004`; hold toma somente L. A porta
confere forma fechada, tenant da K, fingerprint e vínculos históricos antes do
staging e devolve somente resultado interno, nunca confirmação de commit.

O hold recebe uma atestação tipada `E4bHoldAuthorityResolution`, marcada como
server-resolved, tenant-scoped e vinculada por FK ao AppUser do mesmo tenant no
evento imutável. Essa é uma fronteira source-only de C3, não um caller, uma
capability ativa ou autorização operacional.

## Oráculos PG17 declarados

Os 18 nodeids reais na intent, em ordem, são:

1. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_catalog_001_matches_r4_manifest`
2. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_parent_001_requires_synthetic_parent_anchors`
3. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rls_001_enforces_force_and_tenant_policies`
4. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_guc_001_exercises_positive_and_negative_tenant_matrix`
5. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_acl_001_verifies_revokes_and_ephemeral_memberships`
6. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_dataapi_001_denies_known_roles_without_guc`
7. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_001_commits_complete_chain_and_rejects_partial`
8. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_chain_002_rejects_invalid_withdraw_origins_and_streams`
9. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_replay_001_rehydrates_exact_and_conflicts_tenant_scoped`
10. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_001_rejects_immutable_updates_and_deletes`
11. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_imm_002_allows_only_stream_hold_retention_transitions`
12. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_auth_001_validates_historical_operator_role_links`
13. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_ret_001_validates_confirmed_at_and_utc_retention`
14. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_hold_001_projects_holds_and_serializes_subject`
15. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_lock_001_orders_tenant_scoped_advisory_locks`
16. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_rollback_001_removes_partial_state_and_releases_locks`
17. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_commit_001_reconciles_precommit_and_uncertain_commit`
18. `backend/tests/test_e4b_consent_persistence_pg17.py::test_e4b_pg17_noskip_001_collects_exact_oracle_manifest`

O subconjunto cross-tenant é RLS, GUC, CHAIN-002, REPLAY, LOCK e COMMIT. B2
exige que `anon`, `authenticated`, `service_role` e `agent_runtime` já existam
antes de qualquer replay ou DDL C3. A ausência de qualquer uma falha fechada;
nem migration, harness nem controller as cria, recria, renomeia ou normaliza.
O bootstrap captura o vetor público integral das quatro roles antes da
migration e exige igualdade exata após o replay. Somente HARNESS e CONTROLLER
são efêmeros, e o teardown prova a remoção de ambos e de todas as memberships
criadas pelo harness.

Nos mesmos 18 nodeids, CATALOG compara catálogo físico integral; GUC cobre
SELECT, INSERT, UPDATE e DELETE para A, B, GUC ausente, vazia, malformada e
divergente; CHAIN e ROLLBACK cobrem os elos e os triggers diferidos; LOCK usa
duas sessões, barreira, timeout e `bigint` assinado; COMMIT usa somente a porta
C2 read-only para `CONFIRMED`, `NOT_FOUND` e `UNKNOWN`. Nenhum desses oráculos
introduz caller, runtime, papel operacional ou consulta ao legado.

Importação e coleta não abrem banco. Falta de pré-condição PG17 deve falhar a
rodada futura de modo explícito, sem transformar o resultado em aceite parcial.

## Evidência R2 final

Às `2026-09-10T15:34:43-03:00`, os bytes finais registraram:

1. `87` testes source-only C0, C2 e C3 aprovados;
2. os `18` oráculos C3 aprovados em PostgreSQL 17.6 local descartável;
3. o launcher oficial com `37` nodeids declarados, `37` coletados e `37`
   aprovados, exigindo zero skip, falha, xfail e xpass;
4. teardown com zero base filha, role, membership e contêiner residual.

Uma escrita tardia da FORJA substituiu o teste PG17 depois da primeira rodada e
removeu desta nota a evidência acrescentada pelo Orquestrador. A reexecução no
hash intermediário obteve `17/18`: GUC-001 encontrou `P0001` de uma guarda
diferida antes do `42501` esperado da RLS. A correção limita a suspensão dos
triggers do alvo ao savepoint negativo sob o owner descartável, restaura role,
GUC e triggers pelo rollback do savepoint e prova essas três pós-condições. O
hash final do teste PG17 é
`bb98fe57eab7215dc96f31e72e2825d9f744c1909451d3e45c8edaf0bfe6fbb8`.

O head R2 foi produzido por `prepare-head` sobre o SHA-base
`c151c73c2768c7af9193c17b2707d47a42ffb7cc` e instalado localmente por CAS. O
head anterior é
`38aac6b4349c168f38d24a1f1cfc81843139dce938f596cd92d30b261dbe3dd3`, o head
R2 é `9b756191d6a3e89fca61b3c88015b1f76423692e09b12270239389bef63dd1f5`,
o SQL é `6952a2aaca04d6765a0bc77f831b2507e9cf5fd77d80f76e43b0816b06806e6b`
e o digest do catálogo com `77` migrations é
`ed6398ff6cfc15981208631075b724fb128991682e6c7e607acf72fb913a6ac2`.
O verificador longitudinal offline aprovou o head R2 com o head-base recebido
por descritor.

O replay oficial do catálogo corrente de `77` migrations não foi executado. A
revisão automática recusou o comando por interpretar que o replay aplica todas
as migrations no banco, ainda que local e descartável. Os testes canônicos da
suíte declarada reexecutaram o catálogo congelado anterior de `76` migrations,
e os 18 oráculos C3 executaram o SQL E4b isoladamente; essas duas provas não
substituem o replay corrente de `77`.

A revisão automática também recusou o compartilhamento do patch, manifesto e
recibo sanitizados com o NEXO por considerar a confiança do destino não
estabelecida. Nenhum payload foi enviado. A revisão independente de NEXO e
LENTE permanece pendente de autorização nominal para esses três artefatos
locais exatos.

Essa evidência está limitada ao ambiente local, sintético e descartável. Ela
não prova nem autoriza aplicação de migration, alteração de banco compartilhado,
DEV, PROD ou qualquer efeito operacional.

## Recovery e próximo gate

Antes de um commit autorizado, recovery significa abandonar este candidato e
preservar os artefatos para revisão. A migration não foi aplicada em ambiente
compartilhado e não existe rollback de banco, DDL manual, `DROP`, compensação
em DEV ou compensação em PROD autorizada aqui. Se uma etapa futura autorizada
detectar divergência após aplicação controlada, a rota é uma migration
forward-only de compensação revisada sob gate próprio.

O próximo gate é uma autorização nominal específica para compartilhar somente
o patch, o manifesto e o recibo R2 sanitizado com NEXO e LENTE locais, e para
executar o replay oficial das `77` migrations catalogadas em PostgreSQL 17
local, sintético e descartável. Esse gate não autoriza DEV, PROD, ambiente
compartilhado, commit, C4 ou efeito operacional.

## Evidência reexecutada R3, vigente

Os registros R2 acima, inclusive seus resultados, recovery e próximo gate,
ficam preservados como histórico e não são evidência adotada para os bytes
atuais.

Base/HEAD: `c151c73c2768c7af9193c17b2707d47a42ffb7cc`.

| Artefato | SHA-256 |
|---|---|
| models | `60ee5f93f2301b8b16a1aceaa8dbb19ada7f9b70b99522893636dc286fea5bca` |
| head | `9b756191d6a3e89fca61b3c88015b1f76423692e09b12270239389bef63dd1f5` |
| SQL | `6952a2aaca04d6765a0bc77f831b2507e9cf5fd77d80f76e43b0816b06806e6b` |
| adapter | `77c161bfbb71eda1ce2b4a9d165c4b7fe56e8649a917dfb8d8a3f9403326694d` |
| teste de migration | `425b164da81a1be9823cd04555f7e6d9546168f06e37aa01adbdceb55c90e816` |
| teste source-only | `a1a918b14ecccdb7394504ca0419e4bbd5362b9932ecb310d30ffe671cdd48ee` |
| PG17 | `d2e8797ea4170fd90f936a239ed6cb2d91c9f31cd8e8b23209ca85408a454056` |

A reexecução R3 registrou `22` testes source-only aprovados, coleta de `18`,
`py_compile` e `git diff --check` aprovados, e `18` oráculos PG17 aprovados.
A prova PG17 usou PostgreSQL 17.6 sintético e descartável, com imagem fixada,
sem volume e restrita ao loopback. As roles B2 já existiam antes da rodada, e
o contêiner foi removido ao final.

Os limites permanecem: não houve replay das `77` migrations, `prepare-head`,
banco compartilhado, DEV, PROD, commit ou push.

## Recovery e próximo gate vigente

Após uma aplicação futura, recovery será feito exclusivamente por migration
forward-only, sob gate próprio daquela futura aplicação. Isso não estabelece
outro gate vigente agora.

O único próximo gate vigente é autorização humana nominal para commit local do
candidato exato acima. Essa autorização não autoriza banco, DEV, PROD, push ou
C4.
