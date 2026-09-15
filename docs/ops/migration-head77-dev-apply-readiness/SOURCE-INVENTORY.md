# Inventário de fonte: catálogo público 77 para DEV

Status: `SOURCE_ONLY / OPERATIONAL_AUTHORIZATION=BLOCKED`.

Preparado em `2026-09-14T21:46:18-03:00`, no SHA
`5e2082e94db2b6af6b34cfe351d81cf54b85aa76`, branch
`docs/migration-head77-dev-apply-readiness-readonly-20260915`. A base imediata
é `615408514103be1d67bcafa182b5b3b05f1c3e73`.

## Limite deste inventário

Este documento descreve somente bytes versionados e resultados locais
source-only. Não comprova o estado de DEV, a imagem em execução, a aplicação de
migration, credenciais, autorização humana, replay durável ou cutover.

O estado inicial do worktree continha, sem alteração desta missão, a ficha em
`docs/missions/` e o diretório operacional desta missão, ambos não rastreados.

## Vínculo autenticado do catálogo público

O verificador canônico foi executado no SHA exato contra seu parent Git:

```text
RESULT=MIGRATION_CATALOG_CI_VERIFIED_OFFLINE
EVENT_NAME=push
CATALOG_MIGRATION_COUNT=77
CATALOG_DIGEST_SHA256=162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801
PRIOR_HEAD_REQUIRED=true
OPERATIONAL_AUTHORIZATION=BLOCKED
NEXT_STAGE_AUTHORIZED=false
```

O helper canônico `validated_local_catalog_snapshot()` confirmou:

| Evidência | Valor |
| --- | --- |
| SHA-256 dos bytes do head atual | `88e588660f995f774fe298d2bd4e5ea80d399006379661156b7eff28a6940a57` |
| Quantidade pública atual | `77` |
| Digest público atual | `162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801` |
| Head aprovado imediatamente anterior, 76 | `38aac6b4349c168f38d24a1f1cfc81843139dce938f596cd92d30b261dbe3dd3` |
| Prefixo histórico | `75`, digest `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f` |
| Primeiro append público | posição `75`, `20260909_004005_consent_evidence_store_lab.sql`, digest resultante `9942997137c34f807dbc9d0800add85ae3c74940df20f27e42361d0ce43c3fdc` |
| Último append público | posição `76`, `20260910_142830_add_e4b_consent_persistence.sql` |
| SHA-256 do último SQL | `64c031beea4d74feed83337ea623173d0f8d848c685ffcf5365b279a6ea7d1fd` |
| Tamanho do último SQL | `49631` bytes |

Os valores de digest acima vêm do verificador e do helper canônicos. Nenhum foi
recalculado por procedimento ad hoc neste pacote.

## C3 E4b dentro da entrada 77

A intent V1 do SQL de posição 76 é `TENANT`, preserva
`operational_authorization=false` e declara recuperação
`FORWARD_COMPENSATION`. Ela abrange somente estas seis relações, em ordem
lexicográfica na intent:

1. `public.e4b_consent_hold_events`
2. `public.e4b_consent_holds`
3. `public.e4b_consent_operations`
4. `public.e4b_consent_receipts`
5. `public.e4b_consent_retentions`
6. `public.e4b_consent_streams`

O DDL cria fisicamente operations, streams, receipts, retentions, holds e
hold_events. Todas devem ter `igreja_id`, RLS habilitada e forçada, uma policy
permissiva e uma restritiva `FOR ALL TO PUBLIC`, ambas vinculadas a
`app.tenant_igreja_id`. A migration revoga ACLs e não concede acesso
operacional. O preflight de DEV captura somente metadados desses objetos, nunca
suas linhas.

## Catálogo privado, mantido separado

O catálogo privado do runtime não é a entrada pública 76 ou 77. Ele continua
com um único SQL privado, digest
`1644f51e4538700418ed3c9a507ed999ae61cbbc6295c5681873b32908bde080`, ancorado
ao prefixo público histórico 75. Esta missão não combina, aplica ou rebatiza o
stream privado.

## Superfícies de execução encontradas

| Superfície | Estado no SHA desta missão | Consequência |
| --- | --- | --- |
| `verify_migration_catalog_ci.py` | verificador source-only autenticado | pode comprovar a cadeia de fonte, não aplica SQL |
| `validated_migration_catalog_snapshot.py` | snapshot local autenticado | expõe evidência de bytes, não cria trust anchor de ambiente |
| `apply_migrations_catalog_bound_v2.py` | somente `list`; demais comandos bloqueiam antes da conexão | não é executor de aplicação |
| `catalog_bound_execution_v3.py` | somente `describe` e `validate`; sem I/O de aplicação | não é executor de aplicação |
| `apply_migrations.py` | legado | é explicitamente proibido como entrypoint operacional |

A implementação V3 no SHA desta missão fixa a ligação integrada em
`repository_sha1=36999c2f9bfca8035afb886509440fc3760d9154`, com o SQL, o head
e o digest atuais. Esse commit é ancestral alcançável de `5e2082e`. O documento
histórico `docs/decisions/2026-09-10-catalog-bound-execution-v3-foundation.md`
ainda descreve a ligação original anterior à integração, em `02a4f1a`, com os
hashes substituídos pelo rebind do commit `6ab2413`; portanto, não serve como
referência dos literais V3 correntes. A fonte vigente para a ligação é
`backend/scripts/catalog_bound_execution_v3.py`. A V3 continua source-only,
não autentica ambiente e não oferece caminho de apply. Isso é bloqueio
técnico, não uma autorização pendente que possa ser inferida localmente.

## Saídas humanas

O pacote admite somente duas saídas sanitizadas produzidas pelo Raniel:

1. a observação de release na VPS foi completada em
   `2026-09-15T01:56:43+00:00`: o symlink aponta para `c525d6a`, ancestral do
   SHA da missão; quatro containers aparecem saudáveis; e a imagem local tem
   ID `sha256:833d51b5ff40b6bcb576d90449054da342cdfda24d5b93046033c466cda2b1f7`,
   criada em `2026-08-26T04:53:43Z`; e
2. a transcrição da transação DEV de
   `DEV-READONLY-PREFLIGHT.sql`, limitada a versão, identidade sanitizada,
   ledgers e metadados de catálogo, foi executada com sucesso e rollback em
   `2026-09-14T23:18:03-03:00`. O resumo registra PostgreSQL 17.6, ledger
   público com 33 entradas, ledger nativo com seis entradas e as seis relações
   E4b ausentes. As linhas sanitizadas foram recebidas e reconciliadas: zero
   nomes públicos desconhecidos, prefixo coincidente até a posição 24, oito
   posições divergentes e 44 arquivos do catálogo ausentes do ledger público.

Nenhuma saída ausente, abreviada, divergente ou proveniente de outro SHA pode
ser tratada como aprovação de aplicação.
