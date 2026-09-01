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

O commit técnico local `4988de11566f8f0675256b9958ca242e5a009fa3`
integra ao lote o snapshot agregado `cell-report/v2`. Ele preserva apenas os
totais de presentes, visitantes e decisões; `presencas`, `visitantes` e
`records` individuais precisam permanecer arrays vazios, portanto o snapshot
não inventa pessoas nem transforma totais em fatos individuais. Os pins são
`backend/app/domain/cell_report_snapshot.py`, SHA-256
`19adb057c9f002776e3ad99d87de636de4975f5cf602a8fb06d2d8401a7d2aaa`, e
`backend/tests/test_cell_report_snapshot.py`, SHA-256
`08464997fa55cb9319d095f672fe0d78693280104d8b4247390e3e75d80ad7f9`.

O commit técnico local `452aa6ff591b80dcbd3da90f1e5c18367cffd72b`
integra o workflow puro de coleta, revisão e confirmação do relatório. A
confirmação literal apenas correlaciona a revisão corrente; o workflow não
autentica o ator, não concede autoridade e não executa efeito. O estado
`COMMITTED` projeta uma comprovação externa futura, sem gravar ou enviar nada.
Os pins são `backend/app/domain/cell_report_workflow.py`, SHA-256
`87ec5691774eab1b2711fea0f07f9f311ddacf7f321fe36646730742b02569b5`, e
`backend/tests/test_cell_report_workflow.py`, SHA-256
`a5a542f6b0192964a0bdd238b8306a1b8ca162be4ec6e2f824773020300508c6`.

O hardening posterior foi composto pelos commits
`f40d39efeb847b84b30e495ba78f6d218437e8ad`,
`a84bb7d5f00bae6bb472d02c4a33d14442a294a2`,
`ef4aa00797e11bbbaa0189faa2c299bf9ace8a5b`,
`9ea14000065117bda4aa8e7627e78c07dd5d1b2a` e
`45323a64b17cd9f1fa4d4a86f3a32d769f525660`, sem reescrever os freezes
anteriores. Os pins finais são adaptador SHA-256
`2d2adde74dd2bea21aa7a1a3a0e3551ebc62ab269885531162ffc0681e3c7629`,
teste do adaptador SHA-256
`380bf43ea70020ad30134ac56b1ff42823c3219c1950ee3c46c508acdd3290b8`,
snapshot SHA-256
`95a9c4f5ea68b3027b42416d858c5cfc3eed858198bf38f8bab638c1b293a53f`,
teste do snapshot SHA-256
`21c9799aed4d79003c5b3d3018fa5c6c61ff11c6452409056309e5b74d3b76ee`,
workflow SHA-256
`3213bcc9949661bd3db56717492babfc7b9a9c0d79c20b8da9ddc039ab1b129d`
e teste do workflow SHA-256
`7887a930b8d2fbf7f508acae0d6b256927ab52534a726b2a54fec7224c897dd6`.

O hardening de paridade local centraliza `MAX_REPORT_COUNT=1_000_000` e o
limite E2 de oferta em `R$ 999.999,99`; builder e revalidação do snapshot
persistido usam os mesmos limites. O writer humano e o snapshot recusam zero
negativo; o writer também recusa `NaN`, infinito, booleano, string e mais de
duas casas decimais. Isso ainda é constante compartilhada mais validação
humana endurecida, não um serviço de aplicação compartilhado. Os pins
adicionais são
`backend/app/domain/cell_report_limits.py`, SHA-256
`cb0acd562ebd4e91f2f3170d59ff67cea3ac45f9b4a73f370b1c78522b330412`, e
`backend/tests/test_cell_report_limits.py`, SHA-256
`7f11003b18b0159815f54306002e87624045282d775de08d1ba47da1b6822e86`;
`backend/app/routers/cell_meetings.py`, SHA-256
`e72c1e8366a45ab487b38e1d04b110583b4825645daadaccf1957a04b913ddf5`; e
`backend/tests/test_cell_lider.py`, SHA-256
`07ffabd0260b573bad0fbd8ba572064d0acaaa3b361524dea06a35d8ac781b4d`.

Na revisão integrada final do HEAD
45323a64b17cd9f1fa4d4a86f3a32d769f525660, passaram 512 passed, 5 warnings;
633 passed, 7 skipped, 2 warnings; 398 passed, 18 warnings; e 34 passed
documentais. Links locais 89/89, matriz de pins e gates 13/13, py_compile,
secret scan e git diff --check ficaram verdes. O parecer foi GO, com P0, P1 e
P2 iguais a zero. A evidência é exclusivamente local e pré-PR; não prova
runtime, DEV, PROD, banco, deploy ou efeito vivo.

Ainda não existe bridge ou wiring entre `turn_plan_adapter`, workflow e
snapshot. `REPLAY_TERMINAL` não prova relatório persistido: o plano atual de
`report_capture` contém somente intake, auditorias e resposta, sem efeito de
gravação do relatório. Um adapter futuro, em código confiável, deverá derivar o
escopo vinculado ao tenant, mapear centavos e string sob o mesmo limite de
produto E2 do painel e marcar `COMMITTED` somente depois de um commit externo
atômico comprovado.

As duas fatias permanecem restritas ao lote local. Nenhum runtime ou worker foi
acionado; não houve acesso a banco, migration, rede, persistência, mensagem ou
qualquer efeito vivo. Estado: `FUNDAÇÃO OFFLINE DO RELATÓRIO DE CÉLULA
AMPLIADA LOCALMENTE / SNAPSHOT V2 AGREGADO / WORKFLOW PURO / CANDIDATO NÃO
INTEGRADO NO MAIN / EFEITOS VIVOS BLOQUEADOS`.

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

O gate anterior `REVIEW_AND_CI_D3_TURN_FOUNDATION_REPLAY_ONLY_OFFLINE_PR` foi
substituído localmente, sem consumo, pela fundação offline do relatório de
célula. Não houve push, PR, CI ou Preview sob esse gate, portanto ele não é
evidência histórica de uma ação externa.

A fatia offline posterior foi congelada no commit tecnico original
`c24b910bcd4bf4015eda14847e9695497b5b8ef6` e consolidada, sem alteracao da
arvore tecnica, no HEAD local
`bcabbae0cf96a9b6e2cd47e8ff041b5aeaffbc84`, sobre a reconciliacao
documental `e0cb280`. Ela acrescenta o envelope fechado
`cell-report-pending-proposal/v1` e o servico
`cell_report_application`. A proposta usa `relatorio_snapshot` apenas
enquanto o relatorio esta pendente, com bindings opacos de tenant, reuniao,
conversa e ator, expiracao maxima de 24 horas, no maximo 32 operacoes
estruturais e digest do estado-base. O JSONB nao guarda UUIDs brutos, mas os
hashes nao sao autenticadores e o conteudo privado nao pode ser logado.

O servico exige transacao tenant-scoped ja ativa e pertencente ao caller,
adquire locks em ordem canonica e revalida conversa oficial sem handoff,
reuniao passada e nao cancelada; novas propostas e materializacoes exigem
relatorio pendente, enquanto replay final exato e permitido para enviado;
celula, lider e Pessoa ativos, opt-out,
`sem_interesse`, exatamente um `AppUser` utilizavel e ao menos um papel
ministerial. Proposta e confirmacao exigem `AgentTurnIdentity` e
`AgentEffectIntent` com payload exato. A confirmacao literal corrente troca o
envelope por `cell-report/v2`, atualiza `celula_reuniao` e faz somente
`flush`. O caller continua responsavel por commit ou rollback.

O hardening final persiste o `submission_effect_id` original e o
`submission_payload_digest` separado. A dupla nao prova proveniencia,
autorizacao, primeira execucao nem unicidade global, e o historico limitado da
proposta nao substitui plano, receipt duravel autenticado ou outbox. Os limites
compartilhados fixam `MAX_CELL_REPORT_OBSERVATIONS_LENGTH=2_000` caracteres e
`MAX_CELL_REPORT_OBSERVATIONS_BYTES=8_000` bytes UTF-8. Fetch de rows, fetch
de scalars e `flush` sanitizam `SQLAlchemyError` sem encadear a excecao
privada.

Nao existe caller no grafo, worker, webhook, router humano ou
`turn_plan_adapter`; a primeira execucao do agente e `tool_calls` continuam
bloqueados. O router humano ainda nao compartilha o servico nem o lock. Papel,
lideranca e opt-out nao substituem o consentimento `tarefas_operacionais`: a
fonte juridica e do controlador segue nao aprovada, o ledger D2B2a permanece
sem caller e sem aplicacao, e esta fatia nao le nem grava consentimento. Nao
houve migration, banco compartilhado, DEV, PROD, rede, mensagem ou efeito vivo.

Pins integrais do HEAD: `backend/app/domain/cell_report_limits.py`
`8c7a81ee9a8f0a14125c5918aba6f149582e6392d129c9b37744ac3a1d12bf42`;
`backend/app/domain/cell_report_pending_proposal.py`
`53769d79835803dc8c294928047d2d8766de491e17aecc9d57edb239f06c4056`;
`backend/app/domain/cell_report_snapshot.py`
`24e93a2b6e8cbe92a849ba3ccc081ff6fbd092a347a605494464fddc6aa3bc51`;
`backend/app/domain/cell_report_workflow.py`
`da16186dc28f18261967e10800c5f300dae2b11552ed6dff389cbe9d7a3bf877`;
`backend/app/routers/cell_meetings.py`
`59de2e7b9d12a4c9d36e16edf28c8a74ea590244b778dae8da44ac8f47f49067`;
`backend/app/services/cell_report_application.py`
`7dc9d0d9cc7bf09c3d8963e956bd60500038004c5e8d882c7d37dd30c3a3389b`;
`backend/tests/test_cell_health_service.py`
`19fbe602a4943fa76a3583e1e9e61a3e7979169caba5de15e157072262c8be69`;
`backend/tests/test_cell_lider.py`
`a0265297ec29895399bf4ea0bfac37f554ec935ae5fd6e157c4f348bd69cc6a5`;
`backend/tests/test_cell_report_application.py`
`30139bffee6be9c00f7068255c6150ee8507506a14ccb9649bebadbf39dc136e`;
`backend/tests/test_cell_report_limits.py`
`c1d4c2b89e3863e10fed7a3e84eb27b2cece6447c8a63e05237d24fff26196aa`;
`backend/tests/test_cell_report_pending_proposal.py`
`299b23c0795d9a1e70ac0e6ed46b4124c64a94e567f2e8a6d03732fde6165a3c`;
`backend/tests/test_cell_report_snapshot.py`
`7cbd65505095c7821bbb8328da9b6d22760fce0544ab80861ca765c82bbd87fb`;
`backend/tests/test_cell_report_workflow.py`
`704f036d1fd5632c7c33dd5c446e80e6f303fa712adacee892dde822b83f53a9`;
e `backend/tests/test_reports.py`
`fb511601265dfa374a7d9fbec35f913a7e4bdbde615ce82c1c7996e2d51177d2`.

A focal passou em `292 passed`; `tests/test_agent*.py` terminou em
`633 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`730 passed, 18 skipped, 35 warnings`. A suite ampla do backend, com
`migration_history` e Redis fora da selecao, chegou a
`4601 passed, 325 skipped, 499 deselected, 66 warnings`, sem classificacao
verde por uma assercao documental do pin anterior e duas falhas baseline de
modo group-writable `0664` no checkout `/tmp`. Apos esta reconciliacao, a
matriz documental passou em `34 passed`. A revisao independente repetiu
`729 passed` e `1363 passed, 25 skipped` e concluiu `GO`, com P0,
P1 e P2 iguais a zero. A evidencia e local e pre-PR.

Estado: `FRONTEIRA TRANSACIONAL OFFLINE DO RELATORIO AMPLIADA LOCALMENTE /
PROPOSTA PENDENTE FECHADA / FLUSH SEM COMMIT / CANDIDATO NAO INTEGRADO NO MAIN
/ RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior `REVIEW_AND_CI_D3_CELL_REPORT_OFFLINE_FOUNDATION_PR` foi
substituido localmente, sem consumo, pela fatia offline do servico de aplicacao
do relatorio. Nao houve push, PR, CI ou Preview sob esse gate, portanto ele nao
e evidencia historica de uma acao externa.

A composicao transacional posterior esta no HEAD local
`dac3a14cdd2bf857f84609518dd96050e203b4b3`. A reserva V2 foi criada no
commit tecnico original `4d08e783c2de1bb20dfeb29ffb8ee6a43c7a444f` e
integrada como `d6ee2323d658a91bb92724aaa13adea7222538b4`; a UoW veio de
`58b77a84e38ba7be4d3968d32834ef1b415b3a89` e foi integrada como
`17305af54e52aea74948e275ad68fae50427ae67`; os locks dos writers vieram
de `83b4810008f37250b9a9d00f9c9a83f04a3d0399` e foram integrados como
`b6a763cbcab41a78815a7777f2c9b682a6af1ddb`. O commit
`dac3a14cdd2bf857f84609518dd96050e203b4b3` reconciliou nos testes o
`expected_replayed` explicito. A revisao tecnica consolidada posterior
concluiu `GO`; a evidencia exata esta registrada abaixo.

A reserva `AgentOutboundReplyReservationV2` e um contrato puro derivado
somente de `AgentTurnIdentity`, antes de payload ou plano. Ela fixa o slot
`OUTBOUND_REPLY` ordinal zero e produz a mesma chave de compatibilidade V2 do
efeito posterior, sem usar `claim_id`. O valor nao reserva linha, nao prova
outbox, autenticacao, idempotencia global, aceite do provedor ou envio.
Compatibilidade V1/V0 continua somente como drain: a UoW pode vincular a chave
exata observada numa linha legacy ja bloqueada, sem deriva-la nem promove-la.

Os seis writers humanos `edit_meeting`, `set_real_attendance`,
`register_visitor`, `add_record`, `save_report` e `submit_report`
passam pela mesma boundary sanitizada e serializam a reuniao, a celula e o
acesso do lider com locks tenant-bound. Um envelope pendente reconhecido pode
ser invalidado por takeover humano explicito; snapshot pendente desconhecido
falha fechado. O reconhecedor puro do snapshot humano legacy exige shape
completo, metadados coerentes e UUIDs canonicos nao nulos. Assim, um submit
humano concorrente vira `REPORT_CONFLICT` para o agente, enquanto shape
malformado continua `DATA_INTEGRITY`. Os writers web continuam separados do
servico de aplicacao do agente; compartilhar locks nao equivale a compartilhar
servico.

A `cell_report_turn_uow` exige uma transacao tenant-scoped externa, um plano
fechado com `TOOL_CALL`, `AUDIT_EVENT` e `OUTBOUND_REPLY`, e uma
`Message` de reply pre-reservada. Ela bloqueia a mensagem, valida a chave V2
antes do banco ou, para V1/V0, a evidencia exata depois do lock; exige
`expected_replayed` booleano no servico de confirmacao; e requer concordancia
entre relatorio, audit sem conteudo e reply em replay. No caminho novo, agrupa o
snapshot, um `AgentConversationLog` sem texto pastoral e a `Message` com
estado `ia_pendente` na transacao do caller. Todo sucesso da UoW retorna
`requires_caller_commit=true`, inclusive replay observado na transacao atual.
A boundary faz somente `flush`: nao inicia, confirma ou reverte transacao, nao
envia mensagem e nao chama runtime, worker, grafo ou rede.

Esta fatia especifica fecha parte do staging atomico, mas nao cria outbox
generica, receipt global autenticado ou comprovante pos-commit. Nao existe
caller; consentimento `tarefas_operacionais`, `AgentConfig`, proveniencia
operacional, commit, send, primeira execucao generica pelo
`turn_plan_adapter`, migration, drain V1/V0 e efeitos vivos continuam
bloqueados. Nao houve banco compartilhado, DEV, PROD, rede, mensagem ou
deployment.

Pins SHA-256 integrais do HEAD:
`backend/app/agent/turn_execution.py`
`b729c3b25024cff41aa42b39aecd9d30712bf229c8f635c40fbd306cf52ac351`;
`backend/app/agent/turn_identity.py`
`59848ebee37c9be0c9488420c4634e1b323f611c22627328c8c4dd73d5e69998`;
`backend/app/domain/cell_report_legacy_snapshot.py`
`22dc8e5992f5661a5c110d6a4cc1ebedf7babfabfd45a56490b484de4695f869`;
`backend/app/routers/cell_meetings.py`
`9a04c1589f64179e7b60a8b18755a40ee21035a8e955f8ff5238c4c5eba3a18e`;
`backend/app/services/cell_report_application.py`
`0c8ddd4040b83e09fd496eeea3594c68309f0446b97b2466d5f32204babcc347`;
`backend/app/services/cell_report_turn_uow.py`
`1bdebab8fb70b081781fa0ace6152b1d83cdeb9161a125172b16ca5929795399`;
`backend/tests/test_agent_turn_execution.py`
`911cc7743b073c78b6d5eaffc29eee1171bdf25d1526bd94a32542302c92420e`;
`backend/tests/test_agent_turn_identity.py`
`6d60a2668810bf8c62e23658d95c54b886079e4e7ecf120f349e989de710e1cf`;
`backend/tests/test_cell_lider.py`
`0732667504127fb4bcdc163187b9b137e77f645e81a743413d8a7c4332f1ee0e`;
`backend/tests/test_cell_report_application.py`
`278e3d506ca5c0853b957529013991bb676320381727f33183afcadc7768f430`;
`backend/tests/test_cell_report_legacy_snapshot.py`
`57586f81accd27145d5877ce91fa9d98f82f29b1ee4f73828768cfe93134c354`;
e `backend/tests/test_cell_report_turn_uow.py`
`5ce3d8b37f672adfeaf04839183d43f7f67b51f5cf6d81b37b663bf9c2128db9`.

A revisao tecnica integrada no HEAD
`dac3a14cdd2bf857f84609518dd96050e203b4b3` concluiu `GO`, com P0, P1 e
P2 iguais a zero. A focal integrada terminou em `682 passed, 5 warnings`;
`tests/test_agent*.py` terminou em `649 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`960 passed, 18 skipped, 35 warnings`. Tambem passaram 200 vetores da reserva
V2 e 8 casos de corrupcao legacy. As validacoes de AST e `git diff --check`
para `d37d528..dac3a14` ficaram verdes. A evidencia e local e pre-PR. Ela
confirma ainda a ausencia de caller em runtime, worker ou webhook, de migration,
rede ou send e de `begin`, `commit` ou `rollback` na UoW.

Estado: `STAGING TRANSACIONAL OFFLINE COMPOSTO E REVISADO LOCALMENTE / RESERVA
V2 CLAIM-INDEPENDENT / WRITERS SERIALIZADOS / FLUSH SEM COMMIT / GO TECNICO
P0=P1=P2=0 / SEM CALLER / RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior
`REVIEW_AND_CI_CELL_REPORT_APPLICATION_SERVICE_OFFLINE_PR` foi substituido
localmente, sem consumo, pelo lote de staging transacional. Nao houve push, PR,
CI ou Preview sob esse gate, portanto ele nao e evidencia historica de uma acao
externa.

**Próximo gate único:**
`REVIEW_AND_CI_CELL_REPORT_TRANSACTIONAL_STAGING_OFFLINE_PR`. O nome nao
constitui autorizacao ja concedida. Seu consumo exige autorizacao humana
posterior e separada que nomeie push, abertura da PR e GitHub CI e aceite o
Vercel Preview automatico. O gate cobre somente revisao e CI do lote offline de
staging transacional. Nao autoriza merge, Vercel Production, flag-on, caller,
`AgentConfig`, primeira execucao do agente, runtime, worker, consentimento,
commit, send, drain V1/V0, receipt global, saver, probe vivo, acesso a DEV ou
PROD, banco, logs, SQL, DML, migration, outra rede, deploy, mensagem, tool call
ou qualquer efeito vivo.
