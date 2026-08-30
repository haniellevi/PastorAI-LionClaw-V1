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

## Próximo gate único

`REVIEW_AND_INTEGRATE_DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_PR`.

Esse gate autoriza somente revisar e integrar a prova diagnóstica offline e
esta documentação. Ele não autoriza retry, nova invocação DEV, consulta a PROD,
captura, materialização, DML, migration, reconciliação, backfill, deploy, flag,
runtime, `status`, `apply`, `bootstrap-ledger` ou `harden-ledger`.
