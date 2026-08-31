# Diagnóstico sanitizado de fase do preflight DEV

Data: `2026-08-30`

Estado: `INTEGRADO / TERCEIRA INVOCACAO DEV BLOQUEADA EM CONNECT_TLS_AUTH /
CAUSA INDETERMINADA / PROBE DE TRANSPORTE PLANEJADO OFFLINE E DESABILITADO /
CATEGORIA TLS INTEGRADA E COMPROVADA OFFLINE / PROD NÃO CONSULTADO / OPERAÇÃO
BLOQUEADA`.

## Objetivo e limite

Sobre a base versionada
`3685bbcaf11d5a20b3492953d897cb6a459701a8`, o candidato pré-merge adiciona
ao runner de identidade DEV um único diagnóstico sanitizado,
`PREFLIGHT_FAILURE_PHASE`. Esse campo registra somente a última fronteira
operacional iniciada antes do bloqueio. Ele não identifica a causa raiz e não
prova conexão, autenticação, identidade, transação ou estado de ambiente.

O valor `CONNECT_TLS_AUTH`, em particular, não separa nem comprova falha de
rede, TLS ou credencial. Investigar uma dessas hipóteses exige evidência
posterior, autorização própria e fonte adequada.

## Taxonomia e precedência

O enum é estático e fechado em dez valores:

1. `PRECONNECT_GUARDS`;
2. `CONNECT_TLS_AUTH`;
3. `SERVER_VERSION`;
4. `SESSION_GUARDS`;
5. `IDENTITY_VALIDATION`;
6. `ROLLBACK`;
7. `CURSOR_CLOSE`;
8. `CONNECTION_CLOSE`;
9. `POSTCONNECT_TLS_CA_REVALIDATION`;
10. `POST_IDENTITY_FINALIZATION`.

Cada saída `BLOCKED` contém exatamente uma linha
`PREFLIGHT_FAILURE_PHASE=<enum>`. Saídas de sucesso não contêm essa linha.
Quando mais de uma falha ocorre, a primeira falha vence; falhas posteriores de
revalidação ou limpeza não substituem a fase primária. O campo nunca contém
exceção, SQLSTATE, DSN, host, project ref, banco, usuário, IP ou outro valor
dinâmico.

## Evidência técnica congelada

Os SHA-256 do candidato são:

- runner:
  `8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`;
- testes unitários:
  `c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8`;
- prova PostgreSQL 17:
  `d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9`.

O foco offline passou em `109 passed, 2 skipped`. Duas provas sequenciais
passaram em `2/2` sobre PostgreSQL 17 TLS descartável. O agregado relevante
terminou em `222 passed, 2 skipped`; `pycompile` e `diff-check` ficaram verdes.
O contêiner e os certificados temporários foram removidos. Sarah concluiu
`GO`, com zero achado P0, P1 ou P2 após os reforços.

Essa evidência prova somente o comportamento exercitado no candidato sobre o
laboratório descartável. Nenhuma nova consulta, conexão ou invocação foi feita
em DEV ou PROD. Não houve DML, migration, captura, materialização, backfill,
deploy, flag ou runtime compartilhado.

## Integração

A PR #344 integrou o candidato no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. A integração não retroclassifica
as duas invocações históricas e não concede autorização operacional.

## História que permanece inalterada

As duas invocações DEV históricas no `main`
`64cc157d649256a4a9819741f4276c0420590fd1` terminaram com exit `7` antes da
existência deste campo. Elas não podem ser retroclassificadas com qualquer um
dos dez valores.

Uma única chamada `query_logs`, autorizada separadamente e limitada a
`postgres_logs`, ao marcador `pastorai_dev_identity_preflight_v1` e ao
intervalo `2026-08-30T14:10:48Z` a `2026-08-30T15:18:39Z`, retornou uma lista
vazia e nenhum erro. O resultado permanece `EVIDENCE_INSUFFICIENT`; ele não
determina a causa das duas tentativas. Esta missão não repetiu a consulta, não
usou fallback e não acessou linhas brutas, banco, tabelas, SQL da aplicação ou
PROD.

## Terceira invocação e diagnóstico preservado

Em `2026-08-31`, uma única invocação `PROCESS_INVOCATION_ONLY` foi executada
no `main` integrado. Sua autorização nominal era válida entre
`2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa é a janela de validade,
não o horário da execução. O timestamp operacional preciso não foi preservado
e não foi inferido.

A invocação terminou com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. Permaneceram
`OPERATIONAL_AUTHORIZATION=false`, `NEXT_STAGE_AUTHORIZED=false`,
`CAPTURE_EXECUTED=false`, `MATERIALIZATION_EXECUTED=false` e
`PROD_ACCESSED=false`. `ROLLBACK_CONFIRMED=false` não prova falha de rollback,
e `CONNECTION_CLOSED=true` não prova que uma conexão foi estabelecida.

DNS, TCP, TLS, CA, senha, autenticação, endpoint, disponibilidade, conexão,
transação e identidade permanecem `UNKNOWN`. A autorização foi consumida e não
pode ser reutilizada. Nenhum log foi consultado e não houve retry, captura,
materialização, DML, migration, backfill, deploy, flag ou runtime.

A causa histórica continua indeterminada. O plano para separar somente as
fronteiras DNS, TCP e TLS foi preparado offline, permanece
`execution_disabled=true` e não foi executado. Seu contrato e seus limites
estão na
[`decisão de 2026-08-31`](2026-08-31-dev-connect-tls-auth-transport-probe.md).
Após a tentativa, o diretório temporário de autorização, o launcher e a
worktree operacionais temporários foram removidos. O checkout ficou limpo, sem
`__pycache__` ou `.pyc`, e o registro Git obsoleto da worktree foi removido.

## Autorização e próximo gate

Qualquer invocação futura exige autorização humana nominal nova, exclusiva,
separada e vinculada ao artefato exato. Integração, teste verde ou revisão não
a concedem.

`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatórios.

## Integração do plano offline

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`. A Vercel registrou o deployment
frontend Production `6181597461`, status `17569033825`, `state=success`, em
`2026-08-31T13:02:53Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, DEV, PROD, probe ou migration. A integração
versionou apenas o plano offline: `execution_disabled=true`, implementação e
capacidade de rede ausentes, probe não executado e operação bloqueada.

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`, e o deployment automático Vercel frontend Production `6183047421`,
status `17572803614`, terminou com `state=success` em
`2026-08-31T14:26:57Z`. Essa metadata prova somente o frontend.

Sobre esse merge, o candidato de transporte tem runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e teste
SHA-256 `b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
Passaram `90/90` testes exclusivamente offline, incluindo loopback TLS
sintético descartável. Seis descritores privados vinculam alvo,
nonce e CA, fixam o hash do project-ref DEV e o registro de autorização; o
wire envia somente o SSLRequest PostgreSQL de oito bytes, exige `S` e fecha
antes de StartupMessage. O runner não recebe senha, usuário, banco ou DSN e
não tenta autenticação nem SQL. O plano JSON permanece histórico e
byte-idêntico; `execution_disabled=true` e `implementation_present=false`
descrevem a etapa anterior já consumida. A única rede desta rodada foi o `git fetch`
nominal autorizado; nenhum probe vivo, DEV, PROD, banco ou log foi acessado.
`operational_authorization=false` e `next_stage_authorized=false` permanecem.

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, integrou o probe no
merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33408103314`, Environment Attestation PG17 `33408103217`,
Canonical `33408103386`, Frontend `33408103193`, E2E `33408103279`, Backend
`33408103254` e RLS `33408103282`. A Vercel registrou o deployment automático frontend Production
`6184050276`, status `17575418445`, `state=success`, em
`2026-08-31T15:23:35Z`; essa metadata prova somente o deployment do frontend,
não sua saúde funcional, e não prova backend, banco, DEV, PROD ou o probe. O
estado é `IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NÃO EXECUTADO
/ OPERAÇÃO BLOQUEADA`.

## Gate transport-only consumido e diagnóstico seguinte

A PR #349 foi integrada no merge
`20d995c2cae643697fa86807bb478b546d61ac0c`. Seus sete workflows pós-merge e o
deployment automático Vercel frontend Production `6184537013` terminaram com
`SUCCESS`; essa metadata prova somente o frontend.

O gate `SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`
foi consumido uma única vez. Exatamente uma invocação usou o contrato interno
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e`. Uma única
invocação terminou com exit `7`,
`TRANSPORT_PROBE_FAILURE_PHASE=TLS_HANDSHAKE` e
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED`.
DNS, política de endereço, TCP e a resposta `S` ao SSLRequest foram
confirmados; handshake e hostname não foram confirmados. Não houve retry,
senha, autenticação, sessão de banco, SQL, logs ou PROD. A causa continua
indeterminada. A causa permanece indeterminada e o resultado não recebe
categoria retroativa. A evidência
completa e os hashes efêmeros sanitizados estão na
[`decisão de transporte`](2026-08-31-dev-connect-tls-auth-transport-probe.md).

A evolução offline adiciona somente a categoria estática de falha TLS do
handshake.
O candidato tem runner SHA-256
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191`,
testes SHA-256
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489` e
`95/95` testes verdes.

## Integração da categoria TLS na PR #350

A PR #350, HEAD `58af39b760b8b5be85723d3ea693abd20fe3f3cf`, foi integrada no
merge `0f8c6a77bf489f9080743ab3f7ce71097d361aea`, com
`mergedAt=2026-08-31T16:38:27Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Backend `33415223927`, Canonical `33415223885`, E2E `33415223922`,
Environment Attestation PG17 `33415223904`, Frontend `33415223881`, RLS
`33415223955` e Tooling `33415223892`.

A Vercel registrou o deployment automático frontend Production `6185328714`,
status `17578739446`, com `SUCCESS`. Essa metadata prova somente o deployment
do frontend, sem provar saúde funcional, backend, banco, DEV, PROD, probe,
migration ou runtime. O gate
`REVIEW_AND_CI_DEV_TLS_HANDSHAKE_FAILURE_CATEGORY_PR` foi consumido pela PR
#350. A categoria TLS está integrada e comprovada offline; o resultado
histórico não recebe categoria retroativa e a causa permanece indeterminada.
A árvore do merge é idêntica à do HEAD da PR.

O desenho `migration-epoch v3` deverá tratar como `KNOWN_UNVERIFIED_DRIFT`, sem nova
consulta nem inferência de migration aplicada, os sete índices observados por
evidência operacional anterior: `idx_pessoas_igreja_ativa_created`,
`idx_pessoas_igreja_ativa_tipo`, `idx_celulas_igreja_ativo_lider`,
`idx_work_queue_igreja_status_responsavel`,
`idx_conversations_igreja_assumido`, `idx_app_users_igreja_nome` e
`idx_user_roles_igreja_user`. Essa observação não foi revalidada nesta missão
e não prova o estado atual de DEV. A atestação v1 valida somente envelopes que
continuam bloqueados; ela não comprova conclusão e não pode ser reinterpretada
como `environment_attestation_complete=true`. Os artefatos históricos v1 e v2
permanecem byte-idênticos e fora do escopo.

O pacote candidato `migration-epoch v3` está congelado como
`OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED`. O verificador
`backend/scripts/verify_migration_history_divergence_remediation_proposal_v3.py`
tem SHA-256 `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`;
o teste `backend/tests/test_migration_history_divergence_remediation_v3.py`
tem SHA-256 `b34bd0677feb9d4453477d7503dc19beffcaf6cc8648acb85be56113b7578e24`;
a proposta
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.json`
tem SHA-256 `076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e`;
e seu schema
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.schema.json`
tem SHA-256 `88f7972780f07c7071bb4e4292e1f21c258fff47daf2ab207fc709ff34631b38`.
A matriz nova passou `87/87`, a focal estável passou `138/138`, e o verificador
terminou fail-closed com exit `8` e
`RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE`. O estado é
`RECOMMENDATION_ONLY_NOT_APPROVED`; isso comprova somente o desenho offline e
não autoriza evidência viva, cutover, migration ou runtime. O pacote permanece
exclusivamente offline.

No batch offline depois integrado pela PR #351, a correção de precedência classifica
`TimeoutError` e `socket.timeout` como `DEADLINE_EXCEEDED` antes de `OSError`
genérico em cada fronteira de rede. O batch integrado tem runner SHA-256
`2e2208bfbca1214c0cec024c58716eeac7c05789c33ce36d812c0265c3810809`, teste
SHA-256 `d7161cd7dd7c63935c07431193b0d916222e5341088edbdc6d4ef85ad3063689` e
`102/102` testes verdes. Nenhum probe vivo foi executado. Os hashes da PR #350
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191` e
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489`
permanecem evidência histórica e não são substituídos.

O contrato D3 fail-closed integrado usa
`backend/app/agent/private_checkpoint.py`, SHA-256
`098d7186d59b2be9c231e3ca41e328b69901d4bc3e3f9b09651b902c07768f33`,
`backend/app/agent/context.py`, SHA-256
`b8d9ccea0041a81021cb2b4cf8edcbd8af0457ebf4401b021bd974edd29eea7d`, e
`backend/tests/test_agent_private_checkpoint_contract.py`, SHA-256
`2f91523e6a5daacd7c3ac08b933c7d9f857c3eec2a72b9f962c09c98d39f3c8b`.
A seleção `tests/test_agent*.py` terminou em `292 passed, 7 skipped`, com duas
advertências preexistentes. A classificação é `CONTRATO OFFLINE INTEGRADO E INATIVO`: não
há saver, migration ou wiring, e o LangGraph continua stateless.

A PR #351 foi integrada no merge
`bc97dd4e6f2fc9024e85afe8d611708699c8983a`. Os `7/7` checks pós-merge
concluíram com `SUCCESS`. A Vercel registrou o deployment automático do frontend
Production `6187006353`, status `17583083885`, com `SUCCESS`. Essa metadata prova
somente o frontend e não prova backend, banco ou runtime. A preparação D3 de
estado efêmero desta branch permanece candidata offline, sem saver, migration
ou retomada, e não integra a evidência pós-merge da PR #351.

A PR #352, HEAD `c5b2b4c775592641b308de6b2ac3cd069f34dcb3`, integrou essa
preparação no merge `6c807717010a41edf3bfd3d1b2405c2f3527a696`, cuja árvore é
idêntica à do HEAD da PR. Os `7/7` workflows pós-merge concluíram com
`SUCCESS`: Backend Tests `33428905043`, Canonical Schema Derivation
`33428905057`, E2E Critical `33428905042`, Environment Attestation PG17
`33428905234`, Frontend CI `33428905212`, RLS Integration `33428905114` e
Tooling Static Checks `33428905041`. A Vercel registrou o deployment automático
do frontend Production `6187746800`, status `17584957483`, com `SUCCESS`, em
`2026-08-31T19:09:09Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, saver, migration, memória ativa, deploy do
backend, flag ou runtime. O estado permanece `PREPARAÇÃO D3 INTEGRADA E
INATIVA`.

No lote D3 local, antes da primeira consulta, o runtime rederiva a identidade
com quatro entradas confiáveis e separadas: `igreja_id`, `conversation_id`, o
UUID inbound persistido de `Message.id` e o `provider_message_id` exato. Ele
exige igualdade integral dos quatro vínculos com a identidade construída pelo
worker; qualquer divergência aborta. A flag permanece desligada por padrão e
nenhuma execução viva foi autorizada.

No mesmo lote local, o commit técnico
`abafdffdc8252fa6dff7c9d1975cb6c241141971` adiciona o adaptador puro e
replay-only `turn_plan_adapter`, sem status `EXECUTABLE`, callback injetável,
I/O ou consumer de runtime. Plano armazenado ausente ou qualquer receipt
terminal ausente produz `FIRST_EXECUTION_UNSUPPORTED`; somente plano
estruturalmente exato e um receipt terminal válido por efeito retorna
`REPLAY_TERMINAL`, sem conceder execução. `tool_calls` permanecem bloqueados e
a oferta fechada do relatório é vinculada como inteiro `oferta_centavos`.
Os pins são módulo SHA-256
`c81dafec100734ee9a219d8c99a636636b6317b94c93c87cb89ba0f9af581002`, teste
novo SHA-256
`328f3a2870fab8ea38f1901a02e640bec2f5bc9457c3d5261f350a45ef560d5e` e teste
de execução ajustado SHA-256
`7e22814f1715b7bdfc7f83431bf4e15cdf6d8f7d13d0d8d3afaa6811e95e0b2d`.
A revisão passou em `291/291`, a seleção `tests/test_agent*.py` terminou em
`625 passed, 7 skipped` e o parecer foi `GO`, com P0, P1 e P2 iguais a zero.
Não há plano ou receipt persistido, primeira execução, saver, migration,
flag-on ou runtime ativado.

O gate histórico `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` foi consumido
pelo push, abertura, CI e Preview da PR #351. Ele não autorizou o merge
posterior, permanece somente como evidência histórica e não é um segundo gate
corrente.

O gate histórico `REVIEW_AND_CI_D3_EPHEMERAL_EFFECT_STATE_PR` foi consumido
pelo push, abertura, CI e Preview da PR #352. O merge e o deployment automático
do frontend Production foram autorizados separadamente; esse gate não os
autorizou. Após o consumo, ele permanece somente como evidência histórica e
não é um segundo gate corrente.

O gate anterior `REVIEW_AND_CI_D3_TURN_IDENTITY_OFFLINE_PR` foi substituído
localmente, sem consumo, pelo lote combinado. Não houve push, PR, CI ou Preview
sob esse gate, portanto ele não é evidência histórica de uma ação externa.

O gate anterior
`REVIEW_AND_CI_D3_TURN_EXECUTION_AND_TRUSTED_INBOUND_WIRING_OFFLINE_PR` foi
substituído localmente, sem consumo, pelo lote ampliado replay-only. Não houve
push, PR, CI ou Preview sob esse gate, portanto ele não é evidência histórica
de uma ação externa.

## Próximo gate único

`REVIEW_AND_CI_D3_TURN_FOUNDATION_REPLAY_ONLY_OFFLINE_PR`. O nome não constitui autorização
já concedida. Seu consumo exige autorização humana posterior e separada que
nomeie push, abertura da PR e GitHub CI e aceite o Vercel Preview automático.
O gate cobre somente revisão e CI do lote offline ampliado replay-only. Não autoriza merge, Vercel
Production, flag-on, runtime, saver, probe vivo, nova execução, retry, senha,
autenticação, acesso a DEV ou PROD, banco, logs, SQL, captura, materialização,
DML, migration, reconciliação, backfill, deploy, mensagem, tool call, qualquer
efeito vivo, `status`, `apply`, `bootstrap-ledger` ou `harden-ledger`.
