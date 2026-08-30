# Derivação canônica offline do schema de migrations

**Estado:** `DERIVADOR E FINGERPRINT INTEGRADOS / CI VERDE / DERIVAÇÃO
CANÔNICA REPRODUZIDA E VERIFICADA SOMENTE OFFLINE EM PG17 DESCARTÁVEL /
AMBIENTES NÃO ATESTADOS / OPERATIONAL_AUTHORIZATION=BLOCKED`

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

## Integração versionada

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR concluíram com `SUCCESS`:
Backend `33266660793`, Canonical Schema `33266660831`, E2E `33266660798`,
Frontend `33266660804`, RLS `33266660852` e Tooling `33266660794`. Os seis
checks pós-merge do SHA integrado também concluíram com `SUCCESS`: RLS
`33275857135`, Backend `33275857158`, Canonical Schema `33275857195`, E2E
`33275857144`, Tooling `33275857174` e Frontend `33275857154`.

A superfície sanitizada da API `deployments/{deployment_id}` registrou o
deployment automático Vercel frontend Production `6160229001` com
`created_at=2026-08-29T21:22:00Z`; a superfície sanitizada
`deployments/{deployment_id}/statuses` registrou `state=success`,
`created_at=2026-08-29T21:22:01Z`. O intervalo entre esses registros não prova
duração de build nem reuso de artefato. Os checks provam apenas o comportamento
exercitado naquele SHA; a metadata do deployment prova somente o frontend e não
prova backend, banco, migration, runtime ou atestação de ambiente.

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

O tooling posterior de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A decisão e seus limites estão em
[`2026-08-30-read-only-environment-attestation-tooling.md`](2026-08-30-read-only-environment-attestation-tooling.md).
As provas terminaram em `81 passed` de `81` no foco offline,
`367 passed, 47 skipped` na seleção relacionada e `82 passed` de `82` no foco
PostgreSQL 17 TLS descartável. Sarah/Terra concluiu `GO`; o healthcheck de
Claude Opus passou, mas a revisão completa travou com `Execution error` e não
conta como revisão concluída.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluíram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e não
prova backend, banco ou runtime. O estado corrente é
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O JSON Schema valida somente o envelope e o verificador Python é obrigatório.
O HMAC serve para correlação e anti-swap, sem conceder autorização humana ou
provar observação direta do project ref. Data API e Realtime permanecem
`PLATFORM_SURFACES_UNATTESTED`, `OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false`.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integração.
Os SHA-256
congelados são: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitários `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestação existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitários passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestação existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e não prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado à autorização. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorização nominal para cada invocação.
O HMAC serve somente correlação e anti-swap e não substitui autorização humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materialização. Os buffers de chave e nonce são zerados, os descritores são
fechados e os certificados TLS temporários são removidos após a prova. DEV e
PROD não foram consultados. PROD está explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

Em 2026-08-30, já no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocações DEV foram feitas
sob autorizações humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso não foi preservado;
nenhum horário UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos não
provam se houve conexão, não provam sucesso ou falha de autenticação e não
identificam a causa raiz.

O diagnóstico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartável e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local não reclassifica DEV nem determina a causa do bloqueio. A
evidência detalhada está em
[`diagnóstico do preflight de identidade de DEV`](2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

`REVIEW_AND_INTEGRATE_DEV_IDENTITY_PREFLIGHT_DIAGNOSTICS_PR` é o gate
seguinte. Ele autoriza somente revisar e integrar a prova diagnóstica offline e
sua documentação. Não autoriza retry, nova invocação DEV, consulta a PROD,
captura, materialização, DML, migration, reconciliação, backfill, deploy, flag
ou runtime. Uma eventual nova tentativa exige outra autorização humana
nominal, exclusiva e separada, que este gate não concede. PROD continua fora.
