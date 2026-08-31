# Registro sanitizado `CONNECT_TLS_AUTH` e plano offline do probe de transporte DEV

Data: `2026-08-31`

Estado: `PLANO OFFLINE INTEGRADO / RESULTADO SANITIZADO REGISTRADO / CAUSA
INDETERMINADA / PROBE NÃO IMPLEMENTADO E NÃO EXECUTADO / OPERAÇÃO BLOQUEADA`.

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

## Próximo gate único

`REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_POSTMERGE_RECONCILIATION_PR`.

Esse gate autoriza somente abrir e revisar a PR documental pós-merge e executar
o CI do mesmo SHA. Seu consumo exige autorização humana que nomeie o push e a
abertura da PR e aceite o Vercel Preview automático do frontend. Não autoriza
merge nem integração ou deployment Production.

O gate não autoriza implementar ou executar o probe, retry, nova invocação
DEV, DNS, TCP, TLS, senha, autenticação, consulta de logs, banco, SQL, captura,
materialização, DML, migration, reconciliação, backfill, deploy manual ou do
backend, flag, runtime ou acesso a PROD.
