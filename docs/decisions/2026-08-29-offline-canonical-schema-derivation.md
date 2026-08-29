# Derivação canônica offline do schema de migrations

**Estado:** `DERIVAÇÃO CANÔNICA REPRODUZIDA E VERIFICADA SOMENTE OFFLINE EM
PG17 DESCARTÁVEL / AMBIENTES NÃO ATESTADOS /
OPERATIONAL_AUTHORIZATION=BLOCKED`

**Base versionada:** `07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`

## Decisão e limite

Esta missão derivou duas vezes, em PostgreSQL 17 descartável, o schema esperado
pelo catálogo versionado. Ela sucede apenas o gate técnico de derivação previsto
na [proposta de remediação](2026-08-29-migration-history-divergence-remediation.md)
e no [contrato de reconciliação](2026-08-28-migration-history-reconciliation-contract.md).
Não reconcilia os ledgers, não atesta DEV ou PROD e não aprova corte de época.

O catálogo usado contém 75 migrations e permanece vinculado ao digest de fonte
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
O alvo descartável é a imagem fixada
`postgres:17.6-trixie@sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`.
Esses vínculos provam os bytes e o laboratório, não observam qualquer ambiente
compartilhado.

## Resultado reproduzível

As execuções independentes A e B produziram 388390 bytes idênticos, SHA-256
`7040a54d80c0ee4f37e1986ff0a579db275e45c129f4fdafcd66788e22a3eb3e` e
fingerprint estrutural
`8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370`.
Cada execução processou 75/75 migrations, encontrou 15 domínios estruturais usados na derivação e no fingerprint e
terminou com os dois ledgers ausentes. A ausência no alvo sintético é condição
do laboratório, nunca evidência sobre DEV ou PROD.

As provas focais terminaram em `21 passed, 1 skipped`; a seleção ampliada em
`286 passed, 48 skipped`; as provas PostgreSQL A e B tiveram uma aprovação cada.
`py_compile`, validação YAML e a comparação byte a byte também passaram. A
revisão independente Sarah Terra concluiu `GO`, sem achados P0 ou P1, sobre o
patch técnico SHA-256
`2238b97d27e766911f081c4ebceb95e40df32a071b103d17d6796fb127bdadd2`.
Esses resultados não equivalem a uma suíte completa e os skips não são
evidência positiva.

## Limites preservados

`OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório. Esta missão não
acessou DEV ou PROD, não executou DML, não abriu Data API ou Realtime, não
executou runner, `bootstrap-ledger`, `harden-ledger`, `status` ou `apply`, e não
alterou migration, pacote histórico, deploy, flag ou runtime. As observações de
`DERIVATION_OWNER` e versões de extensões pertencem apenas ao laboratório.

O serviço do GitHub Actions usa o mapeamento host:container próprio do runner;
o contrato local não expressa bind explícito de IP. Os DSNs de loopback, o
runner hospedado isolado e o alvo sintético descartável reduzem a superfície do
laboratório, mas não atestam qualquer ambiente. Data API e Realtime continuam
não atestados.

## Próximo gate único

Antes do merge, esta PR exige revisão e CI dedicado verde. Depois da integração,
o único gate é `SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION`. Ele exige missão e
autorização próprias para comparar, somente em leitura, cada ambiente contra a
derivação offline. Não autoriza DML, reconciliação de ledger, corte de época,
runner, migration, backfill, deploy, flag ou runtime.
