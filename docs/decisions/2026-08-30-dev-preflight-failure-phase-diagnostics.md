# Diagnóstico sanitizado de fase do preflight DEV

Data: `2026-08-30`

Estado: `IMPLEMENTADO E COMPROVADO OFFLINE / REVISÃO INDEPENDENTE GO / NÃO
INTEGRADO / DEV E PROD NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

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

## Autorização e próximo gate

O novo SHA-256 do runner invalida qualquer autorização vinculada ao hash
anterior. Uma eventual invocação futura exige autorização humana nominal nova,
exclusiva, separada e vinculada ao novo SHA; integração, teste verde ou revisão
não a concedem.

`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatórios.

## Próximo gate único

`REVIEW_AND_CI_DEV_PREFLIGHT_PHASE_DIAGNOSTICS_PR`.

O gate autoriza somente abrir e revisar uma PR própria e executar o CI do mesmo
SHA. Não autoriza merge nem integração. O merge em `main` e o deployment
automático frontend Vercel Production exigem autorização humana posterior
específica que nomeie e aceite ambos. O gate também não autoriza retry, nova
invocação DEV, consulta de logs, acesso a DEV ou PROD, banco, SQL, captura,
materialização, DML, migration, reconciliação, backfill, deploy manual ou do
backend, flag, runtime, `status`, `apply`, `bootstrap-ledger` ou
`harden-ledger`.
