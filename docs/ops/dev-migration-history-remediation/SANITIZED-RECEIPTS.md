# Recibos sanitizados F1

## Fonte local

| Campo | Valor |
| --- | --- |
| Recibo | `F1_SOURCE_RECEIPT_V1` |
| Ambiente | `LOCAL_SOURCE_ONLY` |
| Base Git | `e1da65d0a6fa5286674f425f855600eb3e4982bb` |
| Branch | `docs/dev-migration-history-remediation-f1-20260915` |
| Catálogo ausente do ledger público registrado | `44` |
| Posições divergentes registradas | `8` |
| SHA-256 da ficha preservada | `1f4528d9bb80962e7366b897bb435ed17d7c604a4f7e8feffc91ce411c4a5725` |
| Ambiente remoto acessado por agente | `nenhum` |
| Ledgers alterados | `nenhum` |

Este recibo registra somente leitura de fonte versionada. Não é recibo de DEV,
VPS ou PROD e não afirma que qualquer migration foi aplicada.

## PostgreSQL 17 descartável

| Campo | Valor |
| --- | --- |
| Recibo | `F1_PG17_E2E_RECEIPT_V1` |
| Ambiente | `LOCAL_DISPOSABLE_POSTGRES_17` |
| Imagem exigida | `postgres:17.6-trixie`, existente localmente, sem pull |
| Rede do container | `none` |
| Porta publicada | `nenhuma` |
| Fixture | dois ledgers sintéticos com 33/6 entradas, roles customizada, `anon` e de plataforma, ACLs de schema/relação/função/default em `public`, `agent_private`, `recovery` e global, e uma relação mascarada com constraint/index/policy/trigger sintéticos |
| Executado em | `2026-09-15T03:05:08-03:00` |
| PostgreSQL reportado pela fixture | `17.6` |
| Resultado | `RESULT=PASS_PG17_E2E_F1_B1_B2_AND_REGRESSION` |
| Verificações concluídas | `row_security=off`, 33/6, `nspacl`, `relacl`, `proacl`, default ACL dos três schemas e global, `grantee_ref=anon`, referências permitidas de `PUBLIC` e `PLATFORM_ROLE`, opacidade de role customizada, `TARGET_DIGEST` Unix de 64 hex estável no mesmo binding/database e diferente ao trocar binding ou database, `ROLLBACK_COMPLETED_F1`, máscara de constraint/index/policy/trigger e ausência de nome ou OID de role customizada, objeto mascarado e statement sintético na saída |

O teste prova separadamente as fixtures novas de grantee customizado em
`agent_private.nspacl`, `relacl` de uma relação `agent_private`, `proacl` de
função e default ACL de `agent_private`; também prova `grantee_ref=anon` nessa
ACL de schema, referência `PUBLIC`, referência de role de plataforma, e que a
role customizada continua sem nome ou OID. A mesma execução confirma os demais
escopos, a enumeração de `relacl/aclexplode`, `proacl` e `pg_default_acl`, o
`TARGET_DIGEST` por socket Unix, sua estabilidade ao repetir o SQL exato no
mesmo database com o mesmo binding e sua mudança ao trocar binding ou database
clonado. O regex DDL após comentário inicial, a ausência de statement e os
nomes brutos de constraint/index/policy/trigger da relação mascarada também são
verificados. Ele não prova DEV, RLS real por principal DEV, dados, target
binding real ou história de migration. O runner não possui caminho de skip:
erro de inicialização, falha de asserção ou ausência de qualquer sinal esperado
encerra com falha.

## Guarda local de privacidade

| Campo | Valor |
| --- | --- |
| Comando | `python3 -I -B -m unittest discover -s backend/tests -p test_source_contact_privacy.py` |
| Resultado | `13` testes, `OK` |
| Limite exercitado | guarda offline do tree atual; a própria implementação exclui caminhos protegidos, rede, banco e configuração runtime |

O binário `pytest` não estava instalado neste worktree. O comando acima é o
modo sem dependência indicado no próprio guarda e concluiu sem skip. Nenhuma
LENTE foi executada.

## Entregáveis DEV futuros, emitidos somente por Raniel

O candidato SQL `09eaa414ea222d4bb3c1675d799eba9124f81791c460e2fa5c4c7195b319d306`
foi julgado conjuntamente como `NAO_APTO` e qualquer `APTO` anterior foi
revogado. OpenCode e CLAUDE precisam primeiro declarar `APTO` para o novo
candidato congelado, manifesto e SHA-256 exatos, em revisão limitada a B1, B2
e regressão. Nenhum agente preenche, infere ou combina os dois entregáveis
abaixo. Em falha ou saída inesperada, Raniel executa somente `ROLLBACK;`,
encerra e envia o erro sanitizado, sem nova tentativa até nova conferência dos
dois conselheiros.

### Transcrição sanitizada

```text
RECEIPT=F1_DEV_READONLY_OPERATOR_RECEIPT_V1
ENVIRONMENT=DEV
BASE_GIT_SHA=e1da65d0a6fa5286674f425f855600eb3e4982bb
CANDIDATE_MANIFEST_SHA256=<HASH_CONFERIDO_DO_MANIFESTO>
TRANSCRIPT_SHA256=<HASH_DA_TRANSCRICAO_SANITIZADA>
TARGET_BINDING_STATE=PRESENT_FORMAT_VALID_NOT_PRINTED
TARGET_DIGEST=<SHA256_DE_64_HEX_SEM_COMPONENTES_DO_ALVO>
TRANSACTION=REPEATABLE_READ_READ_ONLY
ROLLBACK=COMPLETED
DOMAIN_ROWS_SELECTED=NO
LEDGER_STATEMENT_TEXT_PRINTED=NO
UNEXPECTED_CUSTOM_GRANTEE_NAME_PRINTED=NO
```

Preencher somente depois de uma execução humana normal do arquivo de hash
conferido. Não incluir target binding, host, usuário, database, porta,
transporte, role inesperada, PID, snapshot, statement, dado de domínio, PII ou
segredo. O recibo não aprova aplicação.

### Declaração DEV_DATA_DISPOSITION separada

```text
DEV_DATA_DISPOSITION=<EXATAMENTE_UM_DE_NO_VALUE_NO_PII__VALUE_OR_PII_PRESENT__UNKNOWN>
```

Raniel emite essa declaração em artefato separado da transcrição e escolhe
exatamente um valor da ficha, sem preencher mais de uma linha:

- `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`;
- `DEV_DATA_DISPOSITION=VALUE_OR_PII_PRESENT`;
- `DEV_DATA_DISPOSITION=UNKNOWN`.

Ela não deve ser preenchida, inferida ou combinada por agente algum, não deriva
de schema ou ledger e não autoriza recriação.
