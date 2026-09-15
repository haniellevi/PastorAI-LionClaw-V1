# F1: candidato de observação do histórico DEV

## Identificação congelada

| Campo | Valor |
| --- | --- |
| Missão | `M-2026-09-15-dev-migration-history-remediation-catalog-bound` |
| Ambiente executado por este candidato | local, source-only e PostgreSQL 17 descartável |
| Ambiente não acessado pelo agente | DEV, VPS e PROD |
| Worktree | `.worktrees/dev-migration-history-remediation-f1-20260915` |
| Branch | `docs/dev-migration-history-remediation-f1-20260915` |
| SHA base | `e1da65d0a6fa5286674f425f855600eb3e4982bb` |
| Ficha preservada | `docs/missions/M-2026-09-15-dev-migration-history-remediation-catalog-bound.md` |
| SHA-256 da ficha conferido | `1f4528d9bb80962e7366b897bb435ed17d7c604a4f7e8feffc91ce411c4a5725` |
| SHA-256 do SQL DEV read-only congelado | `8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` |
| Estado do candidato | `F1_CANDIDATE_FROZEN_B1_B2_REMEDIATED_PENDING_LIMITED_OPEN_CODE_AND_CLAUDE_APTO` |

## Critério de sucesso

O candidato só está completo se entregar 44 observações fonte-a-fonte, o anexo
das oito divergências, uma coleta psql read-only sanitizada, prova PG17 local
sem skip, recibos, rollback e manifesto reproduzível, sem concluir nada sobre
DEV antes da coleta humana. Raniel não executa a coleta até OpenCode e CLAUDE
conferirem o candidato, o manifesto e o arquivo SQL exatos como `APTO`. A
conferência conjunta que julgou o candidato SQL
`09eaa414ea222d4bb3c1675d799eba9124f81791c460e2fa5c4c7195b319d306` como
`NAO_APTO` revogou qualquer `APTO` anterior. Este congelamento substitui
somente os bloqueantes B1, B2 e a regressão correlata e ainda exige nova
conferência conjunta.

## Resultado

O inventário em [INVENTORY-44.md](INVENTORY-44.md) contém exatamente 44
migrations que estão no catálogo público e faltam no ledger público DEV
registrado no pacote anterior. Cada linha permanece
`PENDING_DEV_OBSERVATION`. O documento separa essa pendência do teto de prova
por schema: backfills, seeds, reconciliações e hardenings condicionais que
dependem de linhas históricas terminam obrigatoriamente como
`NOT_SCHEMA_DECIDABLE`, mesmo que alguma assinatura estrutural exista.

[DIVERGENT-POSITIONS-ANNEX.md](DIVERGENT-POSITIONS-ANNEX.md) preserva as oito
posições que não coincidem com a ordem canônica. Elas não formam uma fila de
aplicação e não autorizam reordenação, backfill ou alteração de nenhum ledger.

[DEV-READONLY-F1.sql](DEV-READONLY-F1.sql) é o único artefato destinado à
execução humana futura, depois do gate dos dois conselheiros. Raniel não o
executa enquanto OpenCode e CLAUDE não tiverem conferido como `APTO` o candidato
exato, seu manifesto e o SHA-256 congelado do SQL. Quando esse gate existir, o
arquivo começa uma transação `REPEATABLE READ READ ONLY`, fixa timeouts, exige
um binding opaco entregue fora da transcrição, lê somente `pg_catalog` e os dois
ledgers autorizados, exige exatamente 33 entradas no ledger público e 6 no
nativo, e termina pelo caminho normal com `ROLLBACK`. Qualquer forma ou
contagem divergente é saída inesperada, dispara `ROLLBACK` e encerra a coleta.
Nenhuma consulta lê tabela de domínio. Definições, policies, triggers e
statements do ledger nativo são expostos somente por hash ou classificação de
padrão não sensível; não há SQL armazenado na saída. Antes da observação, a
saída emite somente `TARGET_DIGEST`, calculado da tupla opaca binding, database,
porta ou `UNIX_SOCKET` e versão do servidor, sem imprimir nenhum desses
componentes isoladamente.

## Evidência local produzida

| Artefato | Limite comprovado |
| --- | --- |
| [PG17-E2E.sql](PG17-E2E.sql) e [run-pg17-e2e.sh](run-pg17-e2e.sh) | fixture sintética local prova, separadamente, grants customizados de schema, relação, função e default ACL em `public`, `agent_private`, `recovery` e global; prova `grantee_ref=anon` em `agent_private`, referências permitidas de `PUBLIC` e `PLATFORM_ROLE`, opacidade da role customizada, `TARGET_DIGEST` em socket Unix estável para o mesmo binding/database e distinto ao mudar binding ou database, além de `row_security=off`, 33/6, `proacl`, máscara de constraint/index/policy/trigger e ausência de objeto mascarado ou statement sintético |
| Guarda de privacidade local | `python3 -I -B -m unittest discover -s backend/tests -p test_source_contact_privacy.py`: 13 testes passaram; o próprio guarda exclui caminhos protegidos, rede, banco e configuração runtime |
| [SANITIZED-RECEIPTS.md](SANITIZED-RECEIPTS.md) | registra somente evidência source-only e o resultado condensado do teste local; não inventa recibo DEV |
| [ROLLBACK.md](ROLLBACK.md) | descreve o descarte documental e a reversão read-only; não prevê mutação em ledger ou schema compartilhado |
| [F1-CANDIDATE-MANIFEST.md](F1-CANDIDATE-MANIFEST.md) | prende a base, os bytes de todos os arquivos F1 e o hash canônico do patch |

Na reexecução local sem rede registrada em
[SANITIZED-RECEIPTS.md](SANITIZED-RECEIPTS.md), o runner concluiu com
`RESULT=PASS_PG17_E2E_F1_B1_B2_AND_REGRESSION`. A execução verificou, sem
skip, as fixtures independentes de `agent_private.nspacl`, `relacl` de relação
em `agent_private`, `proacl` de função, default ACL de `agent_private`, grants
equivalentes nos demais escopos e global, `grantee_ref=anon`, referências
permitidas para `PUBLIC` e a role de plataforma, opacidade da role customizada,
`TARGET_DIGEST` em transporte Unix, contagens 33/6, recibo de rollback e a
ausência de statement sintético e constraint/index/policy/trigger mascarados.

Teste verde local prova apenas o comportamento da fixture PostgreSQL 17 e dos
bytes deste candidato. Não prova a forma física de DEV, a identidade do alvo,
o conteúdo dos ledgers além da futura transcrição, nem aplicação de migration.

## Segurança e tenant

A coleta não chama serviço de domínio, não seleciona linhas de domínio e não
aceita tenant, papel ou autorização como entrada do modelo. A observação de RLS,
policies, funções, ACLs e default ACLs vem de metadados do catálogo. Para
`public`, `agent_private`, `recovery` mascarado e o namespace global,
`aclexplode` enumera `nspacl`, `relacl`, `proacl` e `pg_default_acl` antes da
classificação. Qualquer grantee direto fora da allowlist conservadora gera
somente `UNEXPECTED_CUSTOM_GRANTEE`, sem nome, OID ou identificador reutilizável.
Cada saída ACL preserva `grantee_class` e emite `grantee_ref` somente como
`PUBLIC`, como o nome de uma role cuja classe é `ALLOWLIST_ROLE` ou
`PLATFORM_ROLE`, ou como o mesmo marcador opaco para grantee customizado. As
cinco roles de plataforma previstas são classificadas como `PLATFORM_ROLE`, sem
ampliar a allowlist para roles customizadas.

`TARGET_DIGEST` usa a fórmula congelada de SHA-256 sobre binding opaco,
database, porta ou `UNIX_SOCKET` e `server_version_num`, separados por byte
`0x1f`. Ele permite verificar a consistência de alvo sem revelar os
componentes. Não prova host, identidade, autoridade da sessão ou atribuição a
DEV sem a atestação humana externa.

Os dois ledgers continuam independentes. O ledger nativo é lido somente para
posição opaca, cardinalidade, hash e padrão sanitizado da coluna `statements`.
Ele nunca é mapeado por versão, ordem ou semelhança temporal para uma migration
pública.

## Gate dos conselheiros e entrega humana posterior

O próximo gate único é uma conferência limitada de OpenCode e CLAUDE sobre B1,
B2 e regressão. Cada conselheiro precisa declarar `APTO` para o mesmo candidato
congelado, o mesmo manifesto e o mesmo SHA-256 de `DEV-READONLY-F1.sql` listado
acima. O julgamento conjunto `NAO_APTO` do candidato
`09eaa414ea222d4bb3c1675d799eba9124f81791c460e2fa5c4c7195b319d306` e a
revogação do `APTO` anterior permanecem vigentes até ambos concluírem esta nova
conferência. Até então, Raniel não abre a execução psql nem prepara tentativa
alternativa.

Somente depois desse gate e de uma execução humana encerrada, Raniel entrega ao
Orquestrador dois artefatos independentes:

1. a transcrição sanitizada da execução read-only, sem binding, dados de domínio,
   statement, nome de role inesperada ou identificador de sessão;
2. uma declaração separada `DEV_DATA_DISPOSITION` com exatamente um valor da
   ficha: `DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`,
   `DEV_DATA_DISPOSITION=VALUE_OR_PII_PRESENT` ou
   `DEV_DATA_DISPOSITION=UNKNOWN`.

Nenhum agente, inclusive os conselheiros, preenche, infere ou combina a
declaração `DEV_DATA_DISPOSITION` com a transcrição. A declaração não é uma
inferência de schema, ledger ou ausência de linhas e não autoriza recriação.

## Limitações conhecidas

- Um binding opaco apresentado ao `psql` comprova somente presença e formato
  local. A associação entre esse hash e o target DEV precisa ser atestada pelo
  operador no canal humano autorizado; um script read-only não consegue provar
  host, identidade ou não reuso sem uma âncora externa durável.
- Ausência de objeto não prova que uma migration não foi executada, pois uma
  migration pode ter abortado, sido compensada ou ter efeito condicional. A
  matriz somente admite `PHYSICAL_EFFECTS_PRESENT` após todas as assinaturas
  necessárias coincidirem.
- `NOT_SCHEMA_DECIDABLE` é deliberado para efeitos em linhas. F1 não lê dados
  para reduzir essa incerteza.
- O catálogo de sistema não atesta runtime, Data API, TLS, credencial, flag,
  deploy, RLS efetiva para um principal real ou estado PROD.

## Rollback

F1 não escreve em DEV, VPS ou PROD. A coleta humana encerra com `ROLLBACK`; se
ocorrer erro ou saída inesperada antes desse recibo, o único comando permitido
ao operador é `ROLLBACK;`. Raniel encerra a sessão e envia somente o erro
sanitizado. Não há nova tentativa sem nova conferência de OpenCode e CLAUDE
sobre o candidato, manifesto e SQL exatos. O rollback local é descartar este
diretório documental. O teste PG17 usa container local descartável, sem porta
publicada e sem rede.

## Próximo gate único

OpenCode e CLAUDE conferem independentemente o candidato, manifesto e
`DEV-READONLY-F1.sql` do hash exato registrado no manifesto como `APTO`, com a
revisão limitada a B1, B2 e regressão. Somente esse resultado conjunto permite
a Raniel executar o runbook em sessão DEV já autorizada e entregar,
separadamente, a transcrição sanitizada e a declaração `DEV_DATA_DISPOSITION`.
O gate não autoriza alteração de ledger, migration, cutover ou aplicação.
