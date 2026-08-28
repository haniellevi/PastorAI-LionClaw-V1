# Contrato offline de reconciliação do histórico de migrations

**Estado:** `PACOTE E VERIFICADOR CANDIDATOS / SOMENTE OFFLINE / DECISÕES
HUMANAS PENDENTES / NÃO APLICADO`

**Base auditada:** `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`

## Objetivo e limite

Esta candidata define um pacote deny-state versionado e um verificador local
somente leitura para preparar uma reconciliação histórica humana futura. O
artefato organiza fatos sanitizados sobre o catálogo versionado e exige que
toda decisão sobre aplicação permaneça explícita, humana e acompanhada por
evidência verificável.

Implementar o pacote e o verificador não significa que o histórico foi
reconciliado. Nenhuma decisão humana foi materializada ou aprovada nesta
missão, e nenhum resultado estrutural autoriza operação em ambiente.

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

O pacote desta candidata é um contrato de preparação. Ele não declara
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

Esse resultado prova somente que o pacote candidato obedece ao contrato
offline. Ele não prova banco, ledger, backend, runtime, DEV ou PROD e não
autoriza `bootstrap-ledger`, `harden-ledger`, `status`, `apply`, SQL Editor,
`apply_migration`, `db push` ou MCP.

## Artefatos e interface

O contrato é materializado em quatro arquivos versionados:

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

## Evidência offline da candidata

Passaram `98/98` testes focais do verificador e `26/26` testes documentais.
Como regressão de separação, o módulo preservado do runner passou `42/42`
testes offline; `45` integrações foram puladas por ausência deliberada de banco
descartável nesta missão. Nenhum desses resultados prova ambiente ou decisão
humana.

## Estado operacional preservado

O `bootstrap-ledger` integrado pela PR #323 continua não aplicado. O preflight
PROD na base histórica `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`
confirmou `public.schema_migrations` ausente e
`M06_MIGRATION_DATABASE_URL` não provisionada. Esta candidata não acessa DEV
ou PROD e não executa deploy, migration, bootstrap, hardening, restart,
credencial, flag, runtime, agente ou canário. `status` e `apply` permanecem
bloqueados.

## Próximo gate único

Revisar as evidências focais e os pareceres independentes desta candidata e,
se todos permanecerem verdes, integrar a PR. Esse gate é exclusivamente
offline e não autoriza acesso a ambiente nem comando do runner.
