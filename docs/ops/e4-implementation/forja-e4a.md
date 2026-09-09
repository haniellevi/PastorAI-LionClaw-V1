# E4a, limite fail-closed para identidade idempotente

Data e hora: 2026-09-09T09:15:21-03:00
Ambiente: worktree local isolada, sem rede, banco, credenciais ou efeitos externos
Branch: `feat/e4-consent-ledger-receipt-v1`
SHA base: `9487eac5c1e39df9262c34b0d3ee12d6f7c4e89d`

## Decisão

E4a foi reduzida a uma identidade idempotente durável e reidratável, escopada
por `(igreja_id, chave_idempotencia)`. A chave não contém segredo, HMAC,
entropia de processo, prova de emissão ou capacidade. Ela é somente um valor
que um futuro adaptador persistente, sob RLS e transação revisadas, poderá ler
e comparar.

`ConsentLedgerReceiptOperation` carrega apenas `operation_id`, essa identidade
tenant-scoped e a ação declarada. A comparação pura classifica duas operações
rehidratadas da mesma chave como `EXACT_RETRY` ou `CONFLICT`; portanto a mesma
chave com `operation_id` diferente é conflito. Essa comparação não consulta
banco, não autentica caller e não prova ownership do tenant.

O coordenador não aceita fonte, autoridade, delegado, sessão ou transação por
construtor ou método. Para qualquer operação fechada, ele falha com
`AUTHORITY_ADAPTER_UNAVAILABLE`. Não existe fábrica de autoridade, HMAC de
processo, protocolo duck-typed ou caminho que promova dados em memória a uma
capacidade server-owned.

Foram removidos da API E4a a associação de evidência, recibo e ledger, qualquer
resultado `CONFIRMED`, a reconciliação e a ordem declarada de locks. A ordem
futura só poderá nascer no adaptador de UoW revisado, por chaves concretas e
começando na identidade idempotente tenant-scoped exigida pelo contrato E1.
E4a não declara lock de Pessoa, decisão de ACL ou serialização de stream.

## Limites explícitos

Esta entrega não escreve tabela, não abre transação, não chama runtime, nem
cria rota, tool, worker, webhook, flag, migration ou envio. A busca source-only
limitada a `backend/app` não encontrou caller atual, além da importação interna
do próprio serviço; isso não prova ausência universal de caller. A garantia
efetiva nesta etapa é `stage_write`: toda operação fechada falha com
`AUTHORITY_ADAPTER_UNAVAILABLE` antes de qualquer efeito, pois não existe
adapter revisado.

Ela também não prova tenant ownership, RLS, estado prévio de consentimento,
evidência, recibo, ledger ou reconciliação. Um adapter server-owned real só
poderá ser introduzido numa mudança posterior, com revisão humana própria,
contrato de UoW, persistência tenant-scoped, RLS, locks concretos e testes PG17.
Nada em E4a autoriza essa etapa.

## Arquivos não rastreados do patch

- `backend/app/domain/consent_ledger_receipt.py`
- `backend/app/services/consent_ledger_receipt.py`
- `backend/tests/test_consent_ledger_receipt_domain.py`
- `backend/tests/test_consent_ledger_receipt_coordinator.py`
- `docs/ops/e4-implementation/forja-e4a.md`

## Verificação focal

Foram executados somente os dois arquivos focais, sem banco compartilhado:

```text
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  /tmp/pastorai-pr390-full-gNlSYEGL/venv/bin/python -B -m pytest \
  -p no:cacheprovider -v \
  backend/tests/test_consent_ledger_receipt_domain.py \
  backend/tests/test_consent_ledger_receipt_coordinator.py
```

Resultado esperado e registrado: `14 passed`.

Os testes cobrem reidratação após reinício lógico, escopo tenant, chave igual
com `operation_id` diferente, ação divergente, fonte duck-typed falsificada,
argumento de autoridade falsificado, ausência de reconciliação e locks, ausência
de fábrica ou HMAC de processo e dependências proibidas. O guard de caller é
uma regressão source-only para formas estáticas conhecidas e carregadores
reconhecidos: import direto, relativo resolvido, namespace indireto por
`app.services` e `app`, wildcard, composição estática, f-string, `getattr`,
acesso estático a `importlib.__dict__` e `__import__`. Ele não afirma bloquear
toda forma dinâmica, não substitui autorização nem runtime e não é prova de
segurança efetiva fora da fronteira fail-closed de `stage_write`.

## Identidade canônica do conjunto

O conjunto é formado por todas as linhas `??` de
`git status --porcelain=v1 --untracked-files=all`, ordenadas byte a byte com
`LC_ALL=C`. Para cada caminho relativo, calcula-se `SHA-256` dos bytes do
arquivo e concatena-se `UTF-8(caminho)`, byte NUL, hash hexadecimal ASCII em
minúsculas e LF. A identidade é o `SHA-256` desse fluxo concatenado.

O hash final é relatado no terminal após a última edição deste documento. Ele
não é gravado dentro do próprio conjunto, pois isso criaria uma auto-referência
que alteraria os bytes submetidos ao algoritmo. O método, a lista e o hash do
relato tornam a verificação reproduzível.

Rollback: remover somente estes cinco arquivos não rastreados. Não há schema,
dados persistidos, fila ou efeito externo a compensar.
