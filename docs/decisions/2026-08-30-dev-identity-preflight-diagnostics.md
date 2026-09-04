# Diagnóstico bloqueado do preflight de identidade de DEV

**Data:** 2026-08-30

**Estado:** `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO BLOQUEADA`

**SHA do `main` exercitado:** `64cc157d649256a4a9819741f4276c0420590fd1`

## Evidência observada

Duas invocações do preflight de identidade de DEV foram feitas sob autorizações
humanas nominais distintas e exclusivas. Cada autorização ficou limitada a uma
única invocação `PROCESS_INVOCATION_ONLY` e foi consumida pela própria tentativa.

As duas invocações terminaram de forma idêntica:

- exit `7`;
- `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`;
- `ROLLBACK_CONFIRMED=false`;
- `CONNECTION_CLOSED=true`;
- `OPERATIONAL_AUTHORIZATION=false`;
- `NEXT_STAGE_AUTHORIZED=false`;
- `CAPTURE_EXECUTED=false`;
- `MATERIALIZATION_EXECUTED=false`;
- `PROD_ACCESSED=false`.

O timestamp operacional preciso das duas invocações não foi preservado. O único
marco temporal registrável é a data `2026-08-30`; nenhum horário UTC foi
inferido ou reconstruído.

## Interpretação permitida

A evidência prova somente que as duas invocações terminaram fail-closed antes de
observar e atestar a identidade esperada. `ROLLBACK_CONFIRMED=false` registra o
campo emitido pelo runner e não prova que uma transação ficou aberta.
`CONNECTION_CLOSED=true` registra o estado final de limpeza e não prova que a
conexão foi estabelecida com sucesso.

Não é permitido inferir, a partir desses campos, se houve ou não conexão, se a
autenticação teve sucesso ou falhou, nem qual foi a causa raiz. Não houve
captura, materialização, DML, migration, reconciliação, backfill, deploy, flag
ou runtime. PROD não foi consultado.

## Diagnóstico offline posterior

O runner permaneceu byte a byte intacto, com SHA-256
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`.
O workflow também permaneceu intacto, com SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.

O caminho full-main passou em `2/2` sobre PostgreSQL 17 TLS descartável. O foco
offline passou em `97/97`. Essas provas mostram que o contrato exercitado
funciona no laboratório descartável; não reclassificam as duas invocações DEV,
não atestam o ambiente compartilhado e não identificam a causa do exit `7`.

## Decisão

As duas autorizações foram consumidas e não podem ser reutilizadas. O estado
permanece deny-by-default. Repetir o preflight de DEV não faz parte desta missão
e exigiria uma autorização humana futura, nominal, exclusiva e separada.

## Integração e evidência pós-merge

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnóstica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`:

- Canonical `33319560819`;
- Environment Attestation PG17 `33319560923`;
- E2E `33319560908`;
- RLS `33319560769`;
- Backend `33319560836`;
- Frontend `33319560781`;
- Tooling `33319560786`.

A Vercel registrou o deployment frontend Production `6168185324`, com status
`17531418022`, `state=success` e
`created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata prova somente o
frontend e não prova backend, banco ou runtime.

A integração não repetiu o preflight, não consultou logs, não fez novo acesso a
DEV ou PROD e não determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

## Proposta histórica não consumida

`SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION`.

Naquele recorte histórico, esse gate foi proposto, mas não foi consumido. Ele
exigiria uma autorização humana nova, nominal, exclusiva e separada
para uma única revisão read-only e sanitizada dos logs da falha DEV. A fonte,
os filtros e a janela temporal mínima ainda não foram delimitados e precisariam
constar da autorização antes de qualquer acesso. Como o timestamp
operacional preciso das tentativas não foi preservado, nenhum horário ou janela
é inferido. Nenhum log foi acessado nesta PR.

O gate proposto não autoriza retry, nova invocação DEV, consulta a PROD, banco ou SQL,
exportação ou persistência de logs, captura, materialização, DML, migration,
reconciliação, backfill, deploy, flag, runtime, `status`, `apply`,
`bootstrap-ledger` ou `harden-ledger`. Posteriormente, esse caminho foi
supersedido pelos diagnósticos de fase e pelo probe transport-only executados
sob autorizações humanas nominais próprias. O identificador permanece somente
como registro histórico e não é gate corrente nem próximo hoje.

Na worktree atual, a árvore de migrations foi normalizada localmente para
diretórios `0755` e arquivos `0644`; o snapshot privado descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](2026-09-03-trusted-repository-snapshot-policy.md)
comprova offline somente esse recorte. Isso não é uma correção universal ou
durável: os ancestrais do workspace e do repositório principal permanecem
`0775`, e o `chmod` local pode não sobreviver a um novo checkout. O P2 global
de permissões continua aberto.

O gate
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE` foi
consumido exclusivamente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](2026-09-03-migration-environment-attestation-executor-v2.md).
O candidato não repete nem reclassifica os preflights históricos: sua prova
unitária é offline e a prova PG17 descartável está implementada, mas ainda
depende de execução sem skips no CI do commit candidato. O bloqueio posterior
em `TLS_HANDSHAKE` continua sem causa determinada. A mesma conexão/PID abriga
duas transações e dois snapshots read-only separados.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto no recorte do executor v2, mas não foi consumido. Depois do Commit
A local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, ele foi substituído pela
consolidação
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, agora o
único estágio global corrente, fechado e não autorizado. Seu eventual consumo
fica restrito à consulta remota somente leitura de `refs/heads/main`, ao
preflight da base, ao push da branch candidata, à abertura da PR e à observação
do CI e do Vercel Preview automáticos. O commit local não afirma integração, CI
remoto ou estado de ambiente. O gate consolidado não autoriza merge, banco
compartilhado, DEV, PROD, migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

O estágio funcional
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`
continua futuro, não corrente e não autorizado; a consolidação atual não o
consome nem o antecipa.
