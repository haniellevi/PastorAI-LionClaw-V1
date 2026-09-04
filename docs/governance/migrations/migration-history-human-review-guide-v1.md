# Guia de revisão humana offline do histórico de migrations

**Estado:** `REVISÃO INDEPENDENTE BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01
REGISTRADA / OPERATIONAL_AUTHORIZATION=BLOCKED`

## Finalidade e separação de papéis

Este guia prepara a revisão humana independente prevista pelo
[`2026-08-28-migration-history-reconciliation-contract.md`](../../decisions/2026-08-28-migration-history-reconciliation-contract.md).
Ele não substitui a decisão da pessoa revisora e não altera os seis artefatos
capturados.

Os papéis públicos são somente referências opacas:

- `OWNER-01`: proprietário do sistema e responsável pela decisão de migration;
- `REVIEWER-01`: pessoa revisora técnica independente.

Os dois papéis precisam pertencer a pessoas distintas. Nome, e-mail,
assinatura, contato e prova de identidade permanecem em registro externo
controlado. O repositório público recebe somente SHA-256 do registro final.
Uma análise produzida por IA pode organizar evidência, mas não ocupa nenhum dos
dois papéis e não cria atestado humano.

## Entradas congeladas

| Ambiente | Artefato | SHA-256 |
|---|---|---|
| DEV | `migration-history-reconciliation-dev-evidence-v1.json` | `c2c9c29acaf469e1e560e9fb858c260b3fa8742c0b4b5fe692c6b763755db44c` |
| DEV | `migration-history-reconciliation-dev-evidence-v1-public-capture-receipt-v1.json` | `aa79b4f52a2c152f8a1451596f37d0479f3e336bba304a8e34f579f1f39a767f` |
| DEV | `migration-history-reconciliation-dev-evidence-v1-native-capture-receipt-v1.json` | `136b3938c62c80b0882dd084abc43bfdc58465f957a1040502b0e40aa11481fa` |
| PROD | `migration-history-reconciliation-prod-evidence-v1.json` | `a4ba967570985682bcff19ea5c0c9dc78f2ed96a07377cbdad3dcddf8f6dceda` |
| PROD | `migration-history-reconciliation-prod-evidence-v1-public-capture-receipt-v1.json` | `067377258893391c10a20da1e80c5b37154b2073d4060a8bda6c9628aa753524` |
| PROD | `migration-history-reconciliation-prod-evidence-v1-native-capture-receipt-v1.json` | `34123027ab1b64108a9fb8d6c97da327306acd5ca49a11de2208eb699debc135` |

Qualquer hash diferente encerra a revisão como `BLOCKED_ARTIFACT_DRIFT`.

## Verificação reproduzível

Executar somente em checkout local confiável, sem banco, rede, credencial ou
variável de ambiente:

```bash
cd backend
python scripts/verify_migration_history_reconciliation.py \
  --packet migration-history-reconciliation-dev-evidence-v1.json
python scripts/verify_migration_history_reconciliation.py \
  --packet migration-history-reconciliation-prod-evidence-v1.json
```

O resultado esperado para os dois pacotes ainda não revisados é exit `8`,
`HUMAN_EVIDENCE_BLOCKED` e `OPERATIONAL_AUTHORIZATION=BLOCKED`. Qualquer outro
resultado precisa ser investigado antes de continuar.

## Fatos objetivos que a pessoa revisora deve confirmar

1. O catálogo congelado contém 75 migrations e está vinculado ao digest
   `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
2. DEV registra 33 linhas no ledger público e 6 linhas no ledger nativo. O
   ledger público deixa de coincidir com o prefixo do catálogo na posição 25:
   a linha pública contém
   `20260808_011500_messages_outbound_provider_id_uidx.sql`, enquanto o catálogo
   contém `20260701_014654_evt6_google_event_dedup_index.sql`. Há oito posições
   divergentes entre as 33 capturadas.
3. PROD registra `ABSENT_CONFIRMED` para o ledger público e 32 linhas no ledger
   nativo.
4. Todos os nomes do ledger nativo permanecem `null`. Versão, posição,
   timestamp ou presença em um ledger não autorizam inferir associação com uma
   migration do catálogo.
5. Nenhum dos pacotes contém decisões humanas, atestado ou autorização
   operacional.

Esses fatos impedem uma aprovação imediata. A divergência de DEV não satisfaz
o prefixo íntegro exigido pelo verificador. Em PROD, a ausência do ledger
público e os nomes nativos sanitizados não fornecem, sozinhos, evidência para
mapear as 75 migrations. A conclusão continua bloqueada até existirem registros
humanos externos verificáveis para cada decisão.

## Decisão que `REVIEWER-01` deve produzir

A pessoa revisora deve criar, fora do repositório, um registro separado para
cada ambiente contendo:

- referência opaca da pessoa revisora;
- SHA-256 do pacote e dos dois recibos revisados;
- confirmação ou rejeição de cada fato objetivo acima;
- decisão `BLOCKED_LEDGER_DIVERGENCE`, `BLOCKED_EVIDENCE_INSUFFICIENT` ou,
  somente com evidência externa completa, a determinação individual de cada
  item;
- SHA-256 distinto da evidência e da decisão para cada entrada do catálogo e
  do ledger nativo;
- instante UTC da revisão;
- `operational_authorization=false`.

Uma decisão bloqueada é um resultado válido da revisão. Ela não deve ser
convertida em `HUMAN_REVIEW_COMPLETE`, `ATTESTED_REVIEW_ONLY` ou em uma
permissão para executar o runner.

## Resultado registrado

`REVIEWER-01` concluiu a revisão em `2026-08-29T02:49:00Z`. O registro externo
sanitizado possui SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133` e
classificou DEV como `BLOCKED_LEDGER_DIVERGENCE` e PROD como
`BLOCKED_EVIDENCE_INSUFFICIENT`. O registro não foi versionado.

`OWNER-01` aceitou essa revisão, manteve `operational_authorization=false` e
autorizou somente a preparação offline da correção histórica. O registro
externo dessa decisão possui SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240` e
também não foi versionado.

Essas decisões não modificam os pacotes capturados, não completam a
reconciliação e não autorizam nenhum comando do runner.

## Decisão posterior de `OWNER-01`

O registro separado de `OWNER-01` autorizou somente a proposta técnica em
[`migration-history-divergence-remediation-proposal-v1.json`](migration-history-divergence-remediation-proposal-v1.json).

O `v1` permanece preservado como o texto histórico efetivamente vinculado aos
registros anteriores. A emenda
[`migration-history-divergence-remediation-proposal-v2.json`](migration-history-divergence-remediation-proposal-v2.json)
também é histórica, não herdou aprovação e não constitui a proposta corrente.

A proposta técnica corrente é
[`migration-history-divergence-remediation-proposal-v3.json`](migration-history-divergence-remediation-proposal-v3.json),
congelada como `OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED` e
`RECOMMENDATION_ONLY_NOT_APPROVED`. Sua revisão independente está
`PENDING_INDEPENDENT_REVIEW_OF_V3`, a decisão humana de cutover é `NOT_MADE`,
as atestações separadas de DEV e PROD não estão completas e os gates de Data
API e Realtime permanecem pendentes. Registros humanos anteriores aplicam-se
somente ao `v1` e não podem ser reutilizados para aprovar `v3`.
`bootstrap-ledger`, `harden-ledger`, `status` e `apply` continuam bloqueados.
Qualquer manifesto, captura posterior, implementação ou execução exige gate e
autorização próprios, sem backfill ou reaplicação automática.

A política de permissões sucessora foi implementada e comprovada offline pelo
snapshot privado definido em
[`2026-09-03-trusted-repository-snapshot-policy.md`](../../decisions/2026-09-03-trusted-repository-snapshot-policy.md).

O gate `OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi consumido exclusivamente para o candidato local descrito em
[`2026-09-03-migration-environment-attestation-executor-v2.md`](../../decisions/2026-09-03-migration-environment-attestation-executor-v2.md).
Essa implementação não ocupa o papel de `REVIEWER-01`, não autentica por si só
o papel de `OWNER-01`, não aprova a proposta v3 e não muda as decisões
`BLOCKED_LEDGER_DIVERGENCE` e `BLOCKED_EVIDENCE_INSUFFICIENT`.

O único estágio corrente global é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`,
restrito à consulta remota somente leitura de `refs/heads/main`, ao preflight da
base, ao push da branch candidata, à abertura da PR e à observação do CI e do
Vercel Preview automáticos. Não autoriza merge, banco compartilhado, DEV, PROD,
migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem.

Somente após a integração posterior sob gate próprio e o CI verde, o estágio
funcional futuro poderá ser
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`;
ele não é o estágio corrente nem está autorizado.

Nenhuma etapa deste guia acessa DEV ou PROD, executa SQL, DML, migration,
deploy, flag ou runtime.
