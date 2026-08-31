# Diagnóstico sanitizado de fase do preflight DEV

Data: `2026-08-30`

Estado: `INTEGRADO / TERCEIRA INVOCACAO DEV BLOQUEADA EM CONNECT_TLS_AUTH /
CAUSA INDETERMINADA / PROBE DE TRANSPORTE PLANEJADO OFFLINE E DESABILITADO /
PROD NÃO CONSULTADO / OPERAÇÃO BLOQUEADA`.

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

## Próximo gate único

`REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_IMPLEMENTATION_PR`.

O gate exige autorização humana separada que nomeie o push, a abertura da PR,
o CI do mesmo SHA e o Vercel Preview automático do frontend. Não autoriza
merge nem integração. O gate também não autoriza executar o probe, retry, nova
invocação DEV, DNS, TCP, TLS,
senha, autenticação, consulta de logs, acesso a DEV ou PROD, banco, SQL,
captura, materialização, DML, migration, reconciliação, backfill, deploy manual
ou do backend, flag, runtime, `status`, `apply`, `bootstrap-ledger` ou
`harden-ledger`.
