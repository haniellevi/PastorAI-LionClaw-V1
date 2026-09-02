# Catálogo evolutivo de migrations e consumidores históricos

**Estado:** `M1A/M1B/M1C CANDIDATAS OFFLINE / NÃO COMMITIDAS / CATÁLOGO
CORRENTE COM 75 MIGRATIONS / CI REMOTO NÃO EXECUTADO / OPERAÇÃO BLOQUEADA`

**Base:** `e5d07e60c2eb9dafae671323bde60d1fa1be5749`

## Decisão

O catálogo deixa de usar a contagem corrente como sinônimo do snapshot
histórico. O artefato `migration-catalog-head-v1.json` mantém os 75 arquivos
anteriores, seu digest e seu último basename como prefixo imutável. O head
corrente é reconstruído por lotes append-only de exatamente uma migration e
continua com `operational_authorization=false` e
`next_stage_authorized=false`.

O verificador estrito exige o conteúdo completo do head anteriormente
aprovado quando existe um lote novo. A âncora é recebida por descritor de
arquivo e serve somente para provar a evolução longitudinal. Um hash válido
não autoriza criar, aplicar ou executar uma migration.

## Compatibilidade histórica

Consumidores históricos podem validar um snapshot local do head apenas para
recuperar o prefixo imutável. Essa leitura valida a cadeia completa e a
correspondência exata com o diretório corrente, mas não substitui a prova
longitudinal do verificador estrito.

O manifesto de expectativa de schema e a derivação canônica continuam
vinculados somente aos 75 arquivos históricos. O verificador da proposta v3
compara o template histórico com esse mesmo prefixo. Uma migration posterior,
quando representada por um lote válido no head, não altera capability counts,
fingerprint ou evidência histórica.

O materializador de captura v1 e
`verify_migration_history_reconciliation.py` permanecem artefatos históricos
de hash fixado. Eles não são gates do catálogo corrente e não foram alterados.
Os pacotes v1, v2 e v3, seus schemas, o fingerprint e os recibos existentes
também permanecem byte-idênticos.

O SHA-256 `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`
repetido nos registros anteriores identifica a versão histórica do verificador
v3 antes desta adaptação. Ele continua sendo evidência daquele artefato e não
deve ser substituído retroativamente nem interpretado como hash dos bytes
candidatos da M1B.

## Integração CI candidata

O workflow dedicado `migration-catalog-head.yml` executa em `pull_request` e
em push para `main`, com `contents: read`, histórico completo no checkout e sem
credencial persistida. O histórico completo garante que o `before` continue
disponível após um push com múltiplos commits. O contexto do evento fornece o
SHA corrente e exatamente um ancestral: base do pull request ou `before` do
push. O orquestrador valida o checkout e a ancestralidade usando somente
objetos Git locais.

Sem lotes append-only, o head inicial é verificado sem abrir o blob anterior.
Quando existe um lote, o orquestrador exige que o head anterior exista no
ancestral do evento, limita seu tamanho antes da leitura e o entrega ao
verificador estrito como prova longitudinal. Ausência, ambiguidade, SHA zero,
objeto não blob, ancestral inválido, mais de um lote novo ou reescrita do
prefixo bloqueiam o job.

Depois do head estrito, o mesmo job valida o manifesto histórico source-only e
a estrutura bloqueada da proposta v3. Ele não chama `apply_migrations.py`, não
recebe DSN ou segredo, não acessa banco e não transforma CI verde em
autorização operacional. O workflow não foi executado nesta missão, pois
commit, push, PR e rede continuam fora do escopo.

## Provas e limites

A matriz focal cobre o catálogo real de 75 arquivos e um catálogo sintético de
76 arquivos em diretório temporário. No cenário futuro, o caminho estrito
recusa ausência do head anterior, aceita a âncora correta e os consumidores
históricos continuam lendo exatamente 75 entradas. Tail não representado,
reescrita do prefixo, digest divergente e gates verdadeiros falham fechado.

Esta decisão não cria migration SQL, não altera o runner, não acessa banco,
DEV, PROD ou rede e não autoriza commit, PR, merge, deploy, flag ou runtime.

## Próximo gate único

`OWNER_AUTHORIZE_COMMIT_M1_MIGRATION_CATALOG_EVOLUTION_FOUNDATION`. O gate
ainda está fechado. Seu consumo futuro poderá autorizar somente um commit local
dos arquivos e hashes congelados de M1A/M1B/M1C; não autoriza push, PR, CI
remoto, migration SQL, banco, DEV, PROD, rede, merge ou deploy.
