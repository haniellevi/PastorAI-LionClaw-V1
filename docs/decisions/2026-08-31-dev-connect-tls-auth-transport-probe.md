# Registro sanitizado `CONNECT_TLS_AUTH` e plano offline do probe de transporte DEV

Data: `2026-08-31`

Estado: `PLANO OFFLINE INTEGRADO / RESULTADO SANITIZADO REGISTRADO / CAUSA
INDETERMINADA / PROBE IMPLEMENTADO, INTEGRADO E COMPROVADO OFFLINE / CATEGORIA
TLS INTEGRADA E COMPROVADA OFFLINE / PROBE NÃO EXECUTADO / OPERAÇÃO
BLOQUEADA`.

Base versionada: `bab031a7e0067a257eedb4a24c786cc925801463`.

## Princípio de diagnóstico

Uma fase agregada delimita onde o runner iniciou uma fronteira operacional. Ela
não identifica a causa da falha. Portanto, `CONNECT_TLS_AUTH` não comprova nem
separa resolução DNS, abertura TCP, negociação TLS, validação do certificado ou
autenticação PostgreSQL.

O plano desta missão reduz a incerteza futura por fronteiras observáveis, mas
permanece `execution_disabled=true`. Preparar e revisar o contrato offline não
autoriza executá-lo em DEV.

## Evidência offline versionada

O pacote exclusivamente offline é composto por quatro artefatos:

- plano JSON, SHA-256
  `5d0b1e4d8f3609b5409b9007a7ffb94e4dbebc17bc3bf4a342d5a281dbfa7f36`;
- schema fechado, SHA-256
  `431b413ff8c14ea331269116b13e7ebf1f1f9cdb80ddf7b23c8182c2437648bb`;
- verificador sem capacidade de rede, SHA-256
  `f5146b4df6238c31ac6af7cec01e6e7a747218e0a2fd9b32d43409409f25e961`;
- testes adversariais, SHA-256
  `03561d503c586fc34314bfb70cf02ceace48463cda46c76dfba56665ea79e896`.

Os testes técnicos passaram em `22/22`. O foco documental e de runbooks passou
em `54/54`; o agregado exato terminou em `76 passed`. O verificador standalone,
o parse dos JSONs, a compilação em memória, a varredura AST sem capacidade
externa, os links locais e `git diff --check` também ficaram verdes. Essas
provas cobrem somente os bytes versionados e não equivalem a DNS, TCP, TLS,
consulta de ambiente ou execução do probe.

## Terceira invocação DEV, evidência preservada

Uma única invocação `PROCESS_INVOCATION_ONLY` foi executada no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`, com runner SHA-256
`8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`.
A autorização nominal ficou válida entre `2026-08-31T11:03:30Z` e
`2026-08-31T11:18:30Z`. Essa janela limita a autorização e não é o timestamp da
invocação. O horário operacional preciso não foi preservado e não será
inferido.

A invocação terminou com exit `7` e produziu somente o seguinte resultado
sanitizado:

```text
ENVIRONMENT=DEV
OPERATIONAL_AUTHORIZATION=false
NEXT_STAGE_AUTHORIZED=false
CAPTURE_EXECUTED=false
MATERIALIZATION_EXECUTED=false
PROD_ACCESSED=false
SINGLE_USE_SCOPE=PROCESS_INVOCATION_ONLY
ROLLBACK_CONFIRMED=false
CONNECTION_CLOSED=true
PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH
RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED
```

A autorização foi consumida pela tentativa. Não existe retry implícito.

## Interpretação permitida

| Hipótese | Classificação após a invocação |
|---|---|
| DNS | `UNKNOWN` |
| TCP | `UNKNOWN` |
| TLS e CA | `UNKNOWN` |
| Credencial e autenticação | `UNKNOWN` |
| Conexão estabelecida | `UNKNOWN` |
| Transação iniciada | `UNKNOWN` |
| Identidade do projeto | `UNKNOWN` |

`ROLLBACK_CONFIRMED=false` não prova falha de rollback, pois a transação pode
não ter sido iniciada. `CONNECTION_CLOSED=true` é compatível tanto com nenhuma
conexão aberta quanto com uma conexão posteriormente fechada. A fase não pode
ser convertida em diagnóstico de senha, endpoint, disponibilidade, rede, TLS,
CA ou autenticação.

Não houve captura, materialização, DML, migration, reconciliação, backfill,
deploy, flag ou runtime. Nenhum log foi consultado e PROD não foi acessado.

## Limpeza e contenção

Após a tentativa, o diretório temporário de autorização, o launcher temporário
e a worktree operacional temporária foram removidos. O checkout usado para a
missão ficou limpo, sem `__pycache__` ou `.pyc`, e o registro Git obsoleto da
worktree foi limpo. Esse registro de limpeza não altera a classificação da
causa e não autoriza uma nova conexão.

## Probe de transporte preparado somente offline

O contrato versionado está em
[`dev-connect-tls-auth-transport-probe-plan-v1.json`](../governance/migrations/dev-connect-tls-auth-transport-probe-plan-v1.json).
Ele permanece `execution_disabled=true`. Nesta missão, o probe não resolve DNS,
não abre socket, não inicia TCP ou TLS, não consulta ambiente, não lê senha,
não envia credencial e não produz tráfego de rede.

Uma implementação e uma execução futuras, cada uma sujeita a gate próprio,
deverão respeitar cumulativamente estas fronteiras:

1. validar offline uma autorização nominal curta e vinculada ao SHA do
   launcher, ao digest da CA, ao destino DEV sanitizado, ao nonce e à tentativa
   única;
2. resolver DNS uma única vez, aplicar política fail-closed aos endereços e não
   usar fallback;
3. abrir no máximo uma conexão TCP, com deadline total e sem retry;
4. enviar somente o `SSLRequest` de oito bytes do protocolo PostgreSQL e exigir
   a resposta estática que admite TLS;
5. executar TLS com CA explícita, validação obrigatória e verificação do
   hostname original;
6. fechar o socket antes de qualquer `StartupMessage`, usuário, banco, senha,
   autenticação ou SQL.

As fases futuras ficam limitadas a `PRECONNECT_GUARDS`, `DNS_RESOLUTION`,
`ADDRESS_POLICY`, `TCP_CONNECT`, `PG_SSL_NEGOTIATION`, `TLS_HANDSHAKE`,
`TLS_HOSTNAME_VERIFICATION` e `SOCKET_CLOSE`. A saída deverá usar somente a
categoria estática da última fronteira iniciada, sem host, project ref, IP,
porta, certificado, emissor, serial, cipher, exceção ou mensagem de provedor.

Mesmo um resultado futuro positivo provaria somente que a fronteira de
transporte foi exercitada naquele instante. Ele não provaria identidade do
projeto, acesso ao banco, validade de credencial, disponibilidade contínua ou a
causa histórica desta tentativa. Uma futura execução poderá criar telemetria
de DNS e rede no provedor, ainda que o probe não consulte nem persista logs;
por isso ela exige autorização humana específica.

## Limites desta missão

Esta missão foi exclusivamente offline e versionada. Ela não criou um runner
de rede executável, não acessou DEV ou PROD, não usou senha, SQL, banco ou logs
e não abriu a próxima etapa viva. `OPERATIONAL_AUTHORIZATION=false` e
`NEXT_STAGE_AUTHORIZED=false` permanecem invariantes.

## Integração do plano offline

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`.

A Vercel registrou o deployment frontend Production `6181597461`, status
`17569033825`, `state=success`, em `2026-08-31T13:02:53Z`. Essa metadata prova
somente o frontend e não prova saúde funcional, backend, banco, DEV, PROD,
probe ou migration. A integração incorporou o pacote técnico offline de quatro
artefatos, além da documentação e dos testes de governança, sem runner de rede.
O contrato permanece `execution_disabled=true`, com
`implementation_present=false`, `network_capability_present=false`,
`operational_authorization=false` e `next_stage_authorized=false`. Nenhum probe
foi implementado ou executado e nenhuma nova consulta de ambiente ocorreu.

O campo `next_gate` embutido no plano JSON registra
`REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_OFFLINE_DIAGNOSTICS_PR`, gate consumido pela
abertura, revisão, CI e integração da PR #346. Ele é evidência histórica dos
bytes integrados e não é um segundo gate corrente. Alterar esse campo agora
mudaria o artefato técnico já revisado; o gate corrente é somente o definido
abaixo e validado pelo teste documental.

## Reconciliação da PR #347 e candidato de implementação

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33402611962`, Environment Attestation PG17 `33402611967`,
Canonical `33402611953`, Backend `33402611993`, E2E `33402611920`, Frontend
`33402612121` e RLS `33402611951`. A Vercel registrou o deployment frontend
Production `6183047421`, status `17572803614`, `state=success`, em
`2026-08-31T14:26:57Z`. Essa metadata prova somente o frontend e não prova
backend, banco, DEV, PROD ou o probe.

Sobre esse `main`, o candidato adiciona somente o runner
`backend/scripts/probe_dev_connect_tls_auth_transport.py` e sua matriz
`backend/tests/test_dev_connect_tls_auth_transport_probe.py`. Os SHA-256
congelados são, respectivamente,
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e
`b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
A prova focal passou em `90/90` usando fixtures e loopback TLS sintético
descartável. A única rede desta rodada foi o `git fetch` nominalmente
autorizado para obter o commit-base; nenhum probe vivo, DEV, PROD, banco ou log
foi acessado.

O runner recebe seis descritores privados, fixa no código somente o hash do
project-ref DEV e exige o SHA esperado do registro de autorização em descritor
independente. O caminho de transporte resolve uma vez, exige todos os endereços
globais, escolhe um endereço deterministicamente, envia somente o SSLRequest
PostgreSQL de oito bytes, exige `S`, valida a cadeia TLS com CA explícita e o
hostname e fecha antes de StartupMessage. Não recebe senha, usuário, banco ou
DSN e não tenta autenticação nem SQL. A saída é
sanitizada, mantém `ROOT_CAUSE=UNDETERMINED`,
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false`.

O plano JSON permanece histórico e byte-idêntico. Seus campos
`implementation_present=false` e `network_capability_present=false` descrevem
somente a etapa anterior já consumida, integrada pela PR #346; eles não descrevem
o runner integrado pela PR #348. Nenhum registro nominal de execução foi
emitido e nenhum resultado local autoriza uma execução viva.

## Integração da implementação na PR #348

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, foi integrada no
merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33408103314`, Environment Attestation PG17 `33408103217`,
Canonical `33408103386`, Frontend `33408103193`, E2E `33408103279`, Backend
`33408103254` e RLS `33408103282`.

A Vercel registrou o deployment automático frontend Production `6184050276`,
status `17575418445`, `state=success`, em `2026-08-31T15:23:35Z`. Essa metadata
prova somente o deployment do frontend, não sua saúde funcional, e não prova
backend, banco, DEV, PROD ou o probe. O estado da implementação é
`IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NÃO EXECUTADO /
OPERAÇÃO BLOQUEADA`.

O conteúdo do merge foi validado offline: a árvore calculada dos pais conhecidos
`36f8d13284a8f4964d0258a2a3b845323a80fe7e` e
`af91e5218f9317a730aa29ad8d8c645312b30f19` é
`11d282f20f81a0b6b0885929be19852e34d15f70`, idêntica à árvore do HEAD da PR.
O objeto remoto `1e727cd2` não foi baixado nesta missão porque rede permaneceu
bloqueada. Isso limita somente a proveniência local da reconciliação, não muda
os bytes técnicos já revisados.

## Integração documental e primeira execução transport-only

A PR #349, HEAD `9f2e1573efbbd0e9dc86bdee177a03399c4a118c`, foi integrada no
merge `20d995c2cae643697fa86807bb478b546d61ac0c` em
`2026-08-31T15:50:50Z`. Os sete workflows pós-merge terminaram com `SUCCESS`:
Tooling `33410776855`, RLS `33410776858`, Backend `33410776869`, Environment
Attestation PG17 `33410776921`, E2E `33410776885`, Frontend `33410776816` e
Canonical `33410776874`. O deployment automático Vercel frontend Production
`6184537013`, status `17576683669`, terminou com `state=success` em
`2026-08-31T15:51:36Z`. Essa metadata prova somente o deployment do frontend,
não sua saúde funcional, e não prova backend, banco, DEV, PROD ou o probe.

O gate `SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`
foi consumido por exatamente uma invocação `PROCESS_INVOCATION_ONLY` no
checkout `1e727cd2ea90ccfb68961174b802d595c71f355b`, usando o runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e o
plano SHA-256
`5d0b1e4d8f3609b5409b9007a7ffb94e4dbebc17bc3bf4a342d5a281dbfa7f36`.
O registro preservou
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e`.
O timestamp preciso não foi preservado; nenhuma hora foi inferida. O registro
efêmero teve SHA-256
`6c3af99ad3608f8de03098e47c2dc25bc1db1c16d4e78e96dd1ece44615526c7`,
a CA explícita SHA-256
`6602a85a36afc2e51c66a0df5ae3d383c5b7c2fed93339ccef7d37e01faf09e8`
e o nonce SHA-256
`fe6dfc97738fa193ca727e7ac7411cc1d3525ccb266cb5ef2dcfadcdcccfe2ad`.

Uma única invocação terminou com exit `7`,
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED` e
`TRANSPORT_PROBE_FAILURE_PHASE=TLS_HANDSHAKE`. A saída confirmou
`DNS_RESOLVED=true`, `ADDRESS_POLICY_PASSED=true`, `TCP_CONNECTED=true`,
`PG_SSL_NEGOTIATED=true`, `TLS_HANDSHAKE_COMPLETED=false`,
`TLS_HOSTNAME_VERIFIED=false` e `SOCKET_CLOSED=true`. Também preservou
`AUTHENTICATION_ATTEMPTED=false`, `DATABASE_SESSION_ESTABLISHED=false`,
`SQL_EXECUTED=false`, `LOGS_QUERIED=false`, `PROD_ACCESSED=false`,
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false`. O launcher,
a worktree e os arquivos temporários foram removidos; `LOCAL_CLEANUP=true`.
Não houve retry.

Essa evidência comprova somente que, naquela invocação, DNS, política de
endereço, TCP e a resposta `S` ao SSLRequest foram confirmados. Handshake e
hostname não foram confirmados. A causa permanece indeterminada. Ela não
identifica se a causa foi
verificação de certificado, protocolo TLS, I/O, validação local ou prazo, não
prova autenticação e não autoriza outra tentativa. O resultado histórico não
pode receber categoria retroativa; o resultado não recebe categoria
retroativa.

Uma evolução exclusivamente offline adicionou a categoria estática de falha
TLS `TLS_HANDSHAKE_FAILURE_CATEGORY`, limitada a `NOT_APPLICABLE`,
`CERTIFICATE_VERIFICATION_ERROR`, `TLS_PROTOCOL_ERROR`, `TRANSPORT_IO_ERROR`,
`LOCAL_VALIDATION_ERROR` ou `DEADLINE_EXCEEDED`. Nenhuma mensagem, SQLSTATE,
host, endereço, certificado ou exceção dinâmica entra na saída. O candidato
tem runner SHA-256
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191` e
teste SHA-256
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489`;
`95/95` testes passaram, incluindo loopback TLS sintético.

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
não autoriza evidência viva, cutover, migration ou runtime.

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

O gate histórico `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` foi consumido
pelo push, abertura, CI e Preview da PR #351. Ele não autorizou o merge
posterior, permanece somente como evidência histórica e não é um segundo gate
corrente.

O gate histórico `REVIEW_AND_CI_D3_EPHEMERAL_EFFECT_STATE_PR` foi consumido
pelo push, abertura, CI e Preview da PR #352. O merge e o deployment automático
do frontend Production foram autorizados separadamente; esse gate não os
autorizou. Após o consumo, ele permanece somente como evidência histórica e
não é um segundo gate corrente.

## Próximo gate único

`REVIEW_AND_CI_D3_TURN_IDENTITY_OFFLINE_PR`. O nome não constitui autorização
já concedida. Seu consumo exige autorização humana posterior e separada que
nomeie push, abertura da PR e GitHub CI e aceite o Vercel Preview automático.
A próxima fatia permanece exclusivamente offline e limita-se à identidade
estável de mensagem e turno e ao contrato de idempotência. Este gate não
autoriza merge, Vercel Production, saver, probe vivo, nova execução, retry,
senha, autenticação, sessão de banco, acesso a DEV ou PROD, logs, SQL, captura,
materialização, DML, migration, reconciliação, backfill, deploy, flag, runtime
ou execução externa.
