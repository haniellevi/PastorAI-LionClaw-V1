# Catálogo evolutivo de migrations e consumidores históricos

**Estado:** `M1A/M1B/M1C INTEGRADAS LOCALMENTE (commit 1150fe92) /
M1D-M1E CANDIDATAS NÃO COMMITADAS / COMPROVADAS OFFLINE /
CATÁLOGO CORRENTE COM 75 MIGRATIONS / CI REMOTO NÃO EXECUTADO / OPERAÇÃO
BLOQUEADA`

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

## Atualização pós-commit (2026-09-02)

O gate `OWNER_AUTHORIZE_COMMIT_M1_MIGRATION_CATALOG_EVOLUTION_FOUNDATION` foi
consumido por autorização humana nominal, exclusivamente no escopo declarado:
um commit local dos 14 arquivos e hashes congelados de M1A/M1B/M1C. O commit
técnico é `1150fe92ba67dbcb82b230b9a044472a1e1d9d8d`, na branch
`feat/migration-catalog-head-v1`, sobre a base `e5d07e60c2eb9dafae671323bde60d1fa1be5749`.

Esse consumo não autorizou e não executou push, PR, CI remoto, migration SQL,
banco, DEV, PROD, rede, merge ou deploy. `operational_authorization` e
`next_stage_authorized` permanecem `false` em todos os artefatos.

## Candidatas M1D-M1E não commitadas

M1A-M1C estão commitadas localmente no commit `1150fe92`. M1D e M1E são candidatas
offline posteriores ao commit, revisadas offline e ainda não commitadas. O
catálogo mantém o contrato append-only, o prefixo histórico das 75 migrations, o
digest histórico, o runner intacto, nenhuma migration SQL,
`operational_authorization=false` e `next_stage_authorized=false`.

A M1D reconcilia exclusivamente a documentação pós-commit de M1A-M1C.

A M1E aperfeiçoa o verificador estrito e acrescenta os testes adversariais.
Ela introduziu `_directory_identity`, `_stable_file_unchanged`, ajustes de call
sites e quatro testes adversariais para separar a identidade de segurança de um
diretório ancestral dos metadados voláteis.

A M1E corrige falsos positivos causados por mudanças legítimas em metadados
voláteis de diretórios ancestrais ou pais:

- `links` — pode mudar especialmente com criação ou remoção de subdiretórios;
- `size`, `mtime_ns` e `ctime_ns` — podem mudar com alterações legítimas nas entradas do diretório.

A M1E continua exigindo invariavelmente os cinco campos de identidade:

- `device` — prova que o objeto está no mesmo filesystem;
- `inode` — prova que é o mesmo objeto no filesystem;
- `mode` — prova que tipo e permissões não mudaram;
- `uid` — prova que o owner não mudou;
- `gid` — prova que o grupo não mudou.

Bytes e metadados completos dos arquivos (`FileSnapshot` com todos os nove
campos) continuam estritos. O diretório do catálogo e cada migration
continuam sob comparação integral durante o scan. A troca de ancestral,
chmod, mudança de ownership e cadeia divergente continuam falhando fechado.

## Evidência da revisão independente M1D-M1E

A revisão independente da M1D-M1E produziu veredito técnico GO com as
seguintes evidências offline:

- matriz focal: 89 passed;
- repetição: 20/20 rodadas aprovadas (89 passed cada);
- bateria ampliada: 383 passed, 45 skipped, 1 deselected;
- teste isolado desselecionado: falha fechada por modo 0775 preexistente
  no diretório `docs/governance/migrations/` — condição preexistente não
  introduzida pela M1E e não bloqueante para esta correção;
- veredito técnico: GO;
- nenhum banco, rede, migration ou ambiente consultado.

A limitação preexistente do modo 0775 não é regressão da M1E. Ela permanece
registrada como P2 conhecido, exigindo decisão humana separada sobre
permissões de diretório antes de qualquer attestation operacional.

## Próximo gate único

`OWNER_AUTHORIZE_COMMIT_M1D_M1E_MIGRATION_CATALOG_HARDENING`. O gate está
fechado e depende de revisão final do Codex.

Se futuramente autorizado, permitirá somente um commit local dos seis
arquivos congelados (quatro documentos e dois arquivos Python com hashes
SHA-256 fixados). Não autorizará rede, push, PR, merge, migration SQL,
runner, banco, DEV, PROD, deploy, flags, mensagens nem qualquer outro efeito
operacional.

## Gate remoto diferido

O gate anteriormente proposto
`OWNER_AUTHORIZE_REMOTE_READ_PREFLIGHT_M1_MIGRATION_CATALOG` não foi
consumido, fica diferido e não é o gate corrente. Seu escopo permanece
registrado para autorização humana posterior e separada:

1. consultar por rede o SHA atual de `origin/main` sem modificar referências
   locais;
2. confirmar no upstream os SHA fixados de `actions/checkout` e
   `actions/setup-python`;
3. registrar resultados sanitizados e horários da consulta.

Esse gate não autoriza fetch, pull, push, PR, merge, execução do workflow
remoto, migration SQL, runner, banco, DEV, PROD, deploy, flags, mensagens
nem qualquer outro efeito operacional.
