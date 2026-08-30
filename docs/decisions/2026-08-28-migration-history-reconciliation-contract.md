# Contrato offline de reconciliação do histórico de migrations

**Estado:** `INTEGRADO / INVENTÁRIOS CAPTURADOS / REVISÃO INDEPENDENTE
BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / NÃO APLICADO`

**Base auditada:** `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`

## Objetivo e limite

Este contrato define um pacote deny-state versionado e um verificador local
somente leitura para preparar uma reconciliação histórica humana futura. O
artefato organiza fatos sanitizados sobre o catálogo versionado e exige que
toda decisão sobre aplicação permaneça explícita, humana e acompanhada por
evidência verificável.

O pacote e o verificador foram integrados pela PR #325, mas isso não significa
que o histórico foi reconciliado. Nenhuma decisão humana foi materializada ou
aprovada, e nenhum resultado estrutural autoriza operação em ambiente.

## Históricos independentes

Existem dois históricos diferentes:

- `supabase_migrations.schema_migrations`, ledger nativo do Supabase;
- `public.schema_migrations`, ledger de controle do runner local de arquivo
  único.

Eles não são equivalentes. Nome, ordem, timestamp, hash, conteúdo SQL, forma do
schema ou presença em um deles não prova aplicação nem autoriza copiar,
preencher, alterar, reaplicar ou registrar uma entrada no outro. O snapshot
histórico de 66 migrations locais e 31 entradas permanece uma evidência datada,
sem ser convertido em decisão atual.

## Pacote deny-state

O pacote é versionado, sanitizado e nasce bloqueado. Ele deve:

1. identificar a base auditada e vincular cada item ao basename e ao SHA-256
   exatos do catálogo versionado;
2. representar ausência de decisão, divergência ou evidência incompleta como
   bloqueio, nunca como aprovação implícita;
3. rejeitar item ausente, extra, duplicado, fora de ordem ou com hash
   divergente;
4. não conter DSN, senha, token, host, referência de projeto, conteúdo pessoal
   ou inventário obtido de ambiente sem gate nominal posterior;
5. não ser consumido pelo runtime, pelo backend, pelo runner ou por migrations.

O pacote integrado é um contrato de preparação. Ele não declara
migrations aplicadas, não constitui backfill e não satisfaz a revisão humana.

## Verificador offline

O verificador usa somente a biblioteca padrão e é separado de
`backend/scripts/apply_migrations.py`. Ele lê apenas arquivos locais
versionados, valida forma, cobertura, ordem e hashes e produz saída
determinística e sanitizada.

São proibidos acesso a banco, rede ou variáveis de ambiente, conexão, SQL,
DML, subprocesso operacional, escrita de arquivo e qualquer inferência sobre
aplicação. Também é proibido adicionar um comando de reconciliação ao runner.
Ausência, ambiguidade ou divergência falha fechado.

Mesmo quando a validação estrutural termina com sucesso, o resultado deve
conservar explicitamente:

```text
OPERATIONAL_AUTHORIZATION=BLOCKED
```

Esse resultado prova somente que o pacote obedece ao contrato
offline. Ele não prova banco, ledger, backend, runtime, DEV ou PROD e não
autoriza `bootstrap-ledger`, `harden-ledger`, `status`, `apply`, SQL Editor,
`apply_migration`, `db push` ou MCP.

## Artefatos e interface

O contrato está materializado em quatro arquivos versionados:

- `backend/scripts/verify_migration_history_reconciliation.py`, verificador
  stdlib sem integração com o runner;
- `backend/tests/test_verify_migration_history_reconciliation.py`, matriz
  adversarial do contrato;
- `docs/governance/migrations/migration-history-reconciliation.schema.json`,
  schema fechado da versão `1.0`;
- `docs/governance/migrations/packets/migration-history-reconciliation-template-v1.json`,
  template deny-state vinculado aos 75 arquivos do catálogo desta base.

A única interface aceita é executada a partir de `backend`:

```text
python scripts/verify_migration_history_reconciliation.py --packet migration-history-reconciliation-template-v1.json
```

`--packet` recebe somente um basename JSON minúsculo no diretório versionado.
O verificador recusa caminho absoluto, travessia, symlink, hardlink, tipo de
arquivo incompatível, permissões de escrita de grupo ou mundo, mutação durante
a leitura, JSON ambíguo, catálogo divergente e evidência humana incompleta.

Um pacote humano completo precisa manter inventários público e nativo
independentes na mesma transação `REPEATABLE READ READ ONLY`. O contrato
público ordena por `applied_at ASC, name ASC` e projeta somente posição e nome;
o nativo ordena por `version ASC` e projeta posição, versão e nome sanitizado.
Os dois inventários carregam o mesmo `snapshot_record_sha256`, mantêm
`capture_record_sha256` distintos e registram o mesmo instante. Igualdade de
timestamp sem vínculo de snapshot não satisfaz o contrato.

Cada item do catálogo e cada linha nativa precisa de uma decisão explícita com
`evidence_record_sha256` próprio. Essa evidência não pode reutilizar autorização,
capturas, snapshot, registro de decisão ou os três registros globais de
atestação, inclusive quando o registro pertence a outra decisão. Autorizações
podem coincidir somente entre os dois inventários; os demais papéis de
provenance são únicos e disjuntos, exceto pelo snapshot deliberadamente comum.
O digest usa framing binário com domínio e tamanho, sem depender de serialização
JSON. Os registros externos finais são distintos e vinculados ao mesmo payload
declarado. O verificador prova somente consistência estrutural dessas
referências, sem autenticar pessoas ou o estado atual de um ambiente.

Quando um pacote completo passa, a saída permanece limitada a:

```text
OPERATIONAL_AUTHORIZATION=BLOCKED
VALID_FOR_HUMAN_REVIEW_ONLY
```

O template versionado não passa: ele termina com
`HUMAN_EVIDENCE_BLOCKED`, como exige o estado deny-state.

## Evidência de integração e prova offline

O código foi integrado pela PR #325, HEAD
`d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`. Os workflows da PR concluíram com `SUCCESS`: Backend
`33207468055`, E2E `33207468044`, Frontend `33207468014`, RLS `33207468132` e
Tooling `33207468082`. Os pós-merge também concluíram com `SUCCESS`: Backend
`33207645381`, E2E `33207645348`, Frontend `33207645362`, RLS `33207645399` e
Tooling `33207645340`.

A Vercel registrou o Preview automático frontend `6147914118`, com `SUCCESS`,
em `2026-08-28T20:16:00Z` no HEAD, e o Production automático frontend
`6147952424`, com `SUCCESS`, em `2026-08-28T20:18:55Z` no merge. Essas metadatas
provam somente o frontend, sem provar backend, banco ou runtime. Não houve
deploy manual ou do backend, migration, bootstrap, hardening, restart, flag ou
runtime nesta missão.

A prova local preservada é `98/98` testes focais do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.
Nenhum desses
resultados prova ambiente ou decisão humana.

## Capturador, materializador e evidência viva bloqueada

O capturador e o materializador foram integrados pela PR #327, HEAD
`c4f7a25b81a8091a0d74783c816a168bb7adf44d`, no merge
`f9201a06495fad138e313e4149ad9275ff896900`. A PR #328 integrou o hotfix, HEAD
`2cbdfaf39ae11d984f0aa27dfcf0910c25984840`, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catálogo usado na captura é a
base `656d1d9eebe90ad4b2cbb35c21939a6796c46bfe`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.

A superfície técnica integrada está limitada a
`backend/scripts/capture_migration_history_evidence.py`,
`backend/tests/test_capture_migration_history_evidence.py`, ao SQL allowlisted
abaixo e às alterações no verificador, no teste do verificador, no schema e no
template já listados. Nenhum desses artefatos integra o runner ou o runtime.

O SQL allowlisted
`docs/governance/migrations/migration-history-inventory-capture-v1.sql`, com
SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`,
é apenas o canal nominal de consulta. Somente o valor final de
`sanitized_capture` foi extraído, sem copiar saída auxiliar do comando. O
materializador offline recebe a captura e a chave HMAC por descritores de
arquivo independentes. O digest esperado do target binding entra somente pelo
argumento sanitizado `--expected-target-binding-sha256`; a fonte permanece
independente. `native.name` fica em `null`. Na materialização local, as saídas
são originalmente criadas com modo `0600` e `O_EXCL`; depois do versionamento,
a proteção depende da sanitização e da ACL do repositório, não do modo do
checkout.

Todo pacote permanece bloqueado. O verificador só termina em
`HUMAN_EVIDENCE_BLOCKED` depois de validar a integridade e confirmar o ledger
nativo `PRESENT_COMPLETE` não vazio. Casos anteriores podem terminar em
`INVENTORY_BLOCKED` ou no motivo fail-closed correspondente.

Foram materializados localmente seis artefatos sanitizados. Na origem, o
materializador usou modo `0600` e `O_EXCL`; depois do versionamento, a proteção
depende da sanitização e da ACL do repositório, não do modo do checkout:

- `migration-history-reconciliation-dev-evidence-v1.json`;
- `migration-history-reconciliation-dev-evidence-v1-public-capture-receipt-v1.json`;
- `migration-history-reconciliation-dev-evidence-v1-native-capture-receipt-v1.json`;
- `migration-history-reconciliation-prod-evidence-v1.json`;
- `migration-history-reconciliation-prod-evidence-v1-public-capture-receipt-v1.json`;
- `migration-history-reconciliation-prod-evidence-v1-native-capture-receipt-v1.json`.

Todo pacote permanece bloqueado. O estado atual é `INVENTÁRIOS DEV E PROD
CAPTURADOS / REVISÃO INDEPENDENTE BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01
REGISTRADA / NÃO APLICADO`. Em PostgreSQL 17, DEV registrou o ledger público
`PRESENT_COMPLETE`, com 33 linhas, e o nativo `PRESENT_COMPLETE`, com 6 linhas,
no snapshot `2026-08-28T22:43:11.454382Z`. PROD registrou o ledger público
`ABSENT_CONFIRMED`, com 0 linhas, e o nativo `PRESENT_COMPLETE`, com 32 linhas,
no snapshot `2026-08-28T22:47:43.965243Z`. Todo `native.name` permanece `null`.

Os dois pacotes estão em `EVIDENCE_CAPTURED_UNREVIEWED`. A verificação offline
de cada pacote terminou com exit `8` e
`RECONCILIATION_CONTRACT_BLOCKED:HUMAN_EVIDENCE_BLOCKED`; a checagem conjunta
terminou `CROSS_PACKAGE_OK`. A matriz focal offline pós-captura passou com
`163 passed, 2 skipped` em `1.40s`. Essa matriz não é suíte integral nem
reexecução PostgreSQL e não converte evidência em decisão.

A captura ocorreu somente em leitura e não executou DML, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, deploy, flag ou runtime.
Nenhuma linha capturada, ausência de ledger, contagem ou igualdade aparente
prova aplicação, autoriza backfill ou reconcilia os históricos.

A PR #329, HEAD `c5ae430aa865dbd6371953d43e4a4447ca8e6618`, integrou e
versionou os seis artefatos no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
workflows da PR concluíram com `SUCCESS`: Backend `33222301288`, E2E
`33222301419`, Frontend `33222301331`, RLS `33222301296` e Tooling
`33222301367`. Os pós-merge também concluíram com `SUCCESS`: Backend
`33222447467`, E2E `33222447447`, Frontend `33222447518`, RLS `33222447506` e
Tooling `33222447495`.

O merge gerou o deployment automático Vercel frontend Production `6150482852`,
com `SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o
frontend, sem provar deploy manual ou do backend, banco ou runtime. A integração
versiona a evidência sanitizada já capturada, mas não revisa os inventários,
não altera `EVIDENCE_CAPTURED_UNREVIEWED` ou `HUMAN_EVIDENCE_BLOCKED`, não
aplica migration e não libera o runner nem qualquer autorização operacional.

A revisão externa de `REVIEWER-01`, registrada pelo SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`,
classificou DEV como `BLOCKED_LEDGER_DIVERGENCE` e PROD como
`BLOCKED_EVIDENCE_INSUFFICIENT`. `OWNER-01` aceitou o bloqueio no registro
externo de SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve `operational_authorization=false` e autorizou somente a preparação
offline da correção. Nenhum registro bruto, nome, contato ou assinatura foi
versionado. Os pacotes continuam imutáveis e bloqueados.

## Estado operacional preservado

O `bootstrap-ledger` integrado pela PR #323 continua não aplicado. O preflight
PROD na base histórica `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`
confirmou `public.schema_migrations` ausente e
`M06_MIGRATION_DATABASE_URL` não provisionada. A missão histórica de
implementação e integração da PR #325 não acessou DEV ou PROD, não capturou
inventários e não executou deploy manual ou do backend, migration, bootstrap,
hardening, restart,
credencial, flag, runtime, agente ou canário. `status` e `apply` permanecem
bloqueados.

## Próximo gate único

O manifesto estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
Ele é `SOURCE_LEVEL_EXPECTATION_ONLY`, não prova o schema final de DEV ou PROD
e permanece com `OPERATIONAL_AUTHORIZATION=BLOCKED`. A revisão técnica foi
feita pelo mesmo executor e não é independente.

A derivação canônica prevista pela
[`proposta de remediação da divergência`](2026-08-29-migration-history-divergence-remediation.md)
foi reproduzida e verificada somente offline, em PostgreSQL 17 descartável.
As execuções A e B, a evidência e as limitações estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](2026-08-29-offline-canonical-schema-derivation.md).
Isso não atesta DEV, PROD, Data API ou Realtime e não altera os pacotes,
ledgers ou o runner. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisão de derivação offline`](2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

O tooling posterior de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. O tooling está documentado em
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
O JSON Schema valida somente o envelope e exige o verificador Python; o HMAC é
apenas correlação e anti-swap, sem autorização humana nem observação direta do
project ref. Data API e Realtime permanecem
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

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnóstica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e não prova backend, banco ou runtime.

A integração não repetiu o preflight, não consultou logs, não fez novo acesso a
DEV ou PROD e não determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

O único gate seguinte é
`SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION`. Ele exige
uma autorização humana nova, nominal, exclusiva e separada para uma única
revisão read-only e sanitizada dos logs da falha DEV. A fonte, os filtros e a
janela temporal mínima ainda não foram delimitados e precisam constar da nova
autorização antes de qualquer acesso; nenhum horário é inferido. Nenhum log foi
acessado nesta PR. Este gate não autoriza retry, nova invocação DEV, consulta a
PROD, banco ou SQL, exportação ou persistência de logs, captura,
materialização, DML,
reconciliação de ledger, corte de época, `bootstrap-ledger`, `harden-ledger`,
`status`, `apply`, migration, backfill, deploy, flag ou runtime. PROD continua
fora. Universidade da Vida e Capacitação Destino permanecem fora desta missão.

O procedimento reproduzível e a separação entre proprietário e pessoa revisora
estão em
[`migration-history-human-review-guide-v1.md`](../governance/migrations/migration-history-human-review-guide-v1.md).
