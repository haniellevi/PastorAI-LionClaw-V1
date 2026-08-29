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

Antes do merge, a exigência é revisão e CI dedicado verde desta PR.
Depois da integração, o único gate será
`SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION`, em missão e autorização próprias.
Ele não autoriza DML, reconciliação de ledger, corte de época, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, migration, backfill,
deploy, flag ou runtime. Universidade da Vida e Capacitação Destino permanecem
fora desta missão.

O procedimento reproduzível e a separação entre proprietário e pessoa revisora
estão em
[`migration-history-human-review-guide-v1.md`](../governance/migrations/migration-history-human-review-guide-v1.md).
