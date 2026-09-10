# E4b C2: boundary em memória com portas abstratas

## Estado do candidato

Ambiente: local, source-only. Base Git:
`f76ee78db98f722cbe468f7bb88c2df6340fec83`. Branch:
`feat/e4b-c2-boundary-v1`. Este é um candidato local sem commit, push, PR,
merge, banco, rede ou efeito externo.

O módulo `backend/app/services/e4b_consent_boundary.py` implementa duas
operações fechadas. `replay_intent` recebe intenção C0 e contexto atestado pelo
servidor, faz no máximo uma leitura por porta abstrata e devolve apenas `NEW`,
`EXACT_REPLAY`, `CONFLICT` ou `DENIED`. `reconcile` aceita exatamente um
seletor E4b por `I` ou `C`, faz no máximo uma leitura read-only e devolve
apenas `CONFIRMED`, `NOT_FOUND` ou `UNKNOWN`.

`E4bBoundaryFailure` é um resultado interno sanitizado e disjunto dos dois
conjuntos de negócio. Fonte indisponível não equivale a ausência comprovada.
Em replay, cadeia observada incompleta ou incoerente falha fechada. Em
reconciliação, uma cadeia incompleta ou incoerente atestada pela fonte produz
`UNKNOWN`; payload bruto, proveniência ausente e tenant ou seletor divergente
permanecem falhas internas.

Presença de payload e prova histórica têm cardinalidade fechada. Em replay,
operação ou origem `PRESENT` exige seu payload e sua identidade histórica;
`ABSENT` e `NOT_APPLICABLE` exigem ambos ausentes. Em reconciliação, somente
`CONFIRMED` transporta operação e identidade; `NOT_FOUND`, `UNKNOWN` e
`INCOMPLETE_OR_INCONSISTENT` não transportam nenhum dos dois. O boundary
revalida esse shape após a leitura e antes da classificação C0 ou do
mapeamento de ausência. Contradição retorna `SNAPSHOT_UNTRUSTED`, nunca um
resultado de negócio.

Quando o C0 nega após uma observação válida, `replay_intent` propaga o
`E4bDenialReason` sanitizado da classificação para a decisão `DENIED`. Um
motivo ausente ou de tipo inválido nessa fronteira vira falha interna, em vez
de construir uma decisão inválida.

## Contrato C1 convertido em C2

| Critério | Evidência no boundary |
| --- | --- |
| C2-O1 | Contextos, seletores, requests, snapshots e proveniência usam tipos E4b fechados, scoped à igreja. Dicionário livre, credencial e artefato não servem como autoridade. |
| C2-O2 | `ELIGIBLE` vira `NEW` somente com ausência E4b atestada de `K`; replay, conflito e negação C0 têm saídas exclusivas. |
| C2-O3 | Contexto, intenção, seletor, porta ou shape de snapshot estruturalmente inválidos falham antes da classificação ou da ausência de negócio; I, C e autoridade aninhada são revalidados após construção. |
| C2-O4 | Validações cobrem tenant, `K`, `F`, `C`, `I`, origem, receipt allowlist, estado canônico de operação e concessão, autoridade histórica aninhada, e a cardinalidade entre payload e prova histórica. Snapshot de outra consulta não é reutilizado. |
| C2-O5 | `E4B_FUTURE_LOGICAL_ORDER` declara `autoridade e tenant -> K -> L -> C -> stream -> revalidação -> staging -> owner externo`, sem adquirir recurso. |
| C2-O6 | Artefato legado na intenção C0 é `DENIED` pré-leitura; artefato ou credencial no envelope é falha interna. Saídas não expõem Pessoa, operador, finalidade, `K` ou snapshot bruto. |
| C2-FC-01 | Porta de replay ausente ou indisponível nunca gera `NEW`; cadeia sem prova ou shape contraditório recebe falha sanitizada. |
| C2-FC-02 | `NOT_FOUND` exige ausência E4b atestada sem operação ou identidade histórica; porta indisponível ou shape contraditório falha internamente; incerteza autorizada vira `UNKNOWN`. |
| C2-FC-03 | Decisões de replay, reconciliação e falha têm tipos e enums disjuntos. |

Antes de `EXACT_REPLAY` ou `CONFIRMED`, o snapshot deve trazer
`E4bHistoricalOperationIdentity`. Ela contém `I`, `R`, `K`, `F`, ação,
origem, referência ACCEPT e uma autoridade histórica fechada. O boundary
recompõe F dessa identidade e a liga à operação e ao receipt, comparando igreja,
`I`, `R`, `K`, `C`, ação, origem, titular, manifestante, papel, responsável,
operador, finalidade, versões e digest. `operator_kind` e
`operator_role_links`, ausentes em `E4bConfirmedOperation`, entram por essa
identidade para que não sejam inferidos. Prova canônica contraditória em shape
válido falha fechada em replay e devolve `UNKNOWN` em reconciliação.

Os oráculos também exercitam `WITHDRAW`: ACCEPT ativo E4b com concessão ativa
e prova de origem histórica canônica resulta em `NEW`; prova da origem ausente
e identidade anexada a origem ausente ou inaplicável resultam em falha interna.
O replay histórico exato de `WITHDRAW` preserva somente o receipt allowlisted
da retirada, sem reativar concessão. Origem de outra finalidade resulta em
`DENIED` com `ORIGIN_PURPOSE_MISMATCH`; ACCEPT com concessão ativa resulta em
`DENIED` com `ACTIVE_CONCESSION`; os dois caminhos fazem uma leitura. Origem
de outro tenant é rejeitada pelo construtor fechado do snapshot.

## Correções R4 pós-construção

O boundary não confia na imutabilidade declarada de um objeto recebido pela
porta. Antes de classificação C0, `NEW`, `EXACT_REPLAY`, `CONFIRMED` ou
projeção de receipt, ele reconstitui `E4bConfirmedOperation` e
`E4bConcession` para reaplicar os invariantes fechados do domínio. Assim,
ACCEPT com estado de concessão `WITHDRAWN`, ação alterada incompatível e
concessão marcada `ACTIVE` enquanto ainda transporta `withdraw_operation_id`
resultam em `SNAPSHOT_UNTRUSTED`; não retornam receipt nem resultado de
negócio.

Para payload histórico `PRESENT` de replay, operação e identidade devem
pertencer à igreja e à mesma `K` do request, antes de C0 poder inferir
ausência. Isso bloqueia uma operação canônica de outra `K` ou tenant, inclusive
quando seu `F` foi preservado. A concessão e a ACCEPT de origem também devem
pertencer ao tenant do request após a leitura. Em reconciliação `CONFIRMED`,
operação, identidade e `K.igreja_id` são ligados ao tenant do seletor antes de
qualquer receipt; as regressões pós-construção cobrem tanto `I` quanto `C`.
Uma cadeia histórica contraditória no mesmo tenant continua sendo `UNKNOWN`
quando a prova histórica é incompleta, sem converter payload cross-tenant em
incerteza de negócio.

## Correções R5 de valores aninhados e entradas

`_authority_has_closed_shape` reconstitui `E4bAuthorityResolution` sem
normalizar o valor recebido. A identidade histórica reconstitui essa autoridade
e a própria `E4bHistoricalOperationIdentity`, reaplicando tipos, vínculos de
manifestante, papéis, versões, digest, `K`, igreja externa e a igualdade entre
`authority.igreja_id` e `identity.igreja_id`. Uma autoridade interna de outro
tenant, mesmo com `F` recalculado e copiado para a operação, é
`SNAPSHOT_UNTRUSTED` em replay e reconciliação, antes de `CONFLICT`,
`CONFIRMED`, `UNKNOWN` ou receipt.

O mesmo shape fechado é reaplicado aos contextos server-resolved atuais de
replay e reconciliação. Uma autoridade adulterada, por exemplo com
`operator_role_links` como `set`, retorna `INVALID_CONTEXT` antes da porta.
Uma atestação booleana válida, ainda que semanticamente falsa, não é tratada
como corrupção estrutural e preserva a negação C0 já contratada. A entrada
reconstitui I e C antes da porta: UUID nulo ou texto adulterado retorna
`INVALID_SELECTOR` com zero leituras.

As únicas interfaces de fonte são `E4bReplayReadPort` e
`E4bReconciliationReadPort`, ambas abstratas e somente de leitura. Não existe
adapter concreto no candidato. Os dublês em memória ficam exclusivamente em
`backend/tests/test_e4b_consent_boundary.py`.

## Evidência local sanitizada

Horário da validação final: `2026-09-09T23:47:11-03:00`.

| Verificação | Comando | Resultado |
| --- | --- | --- |
| Sintaxe | `PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX=/tmp/e4b-c2-boundary-pycache /tmp/pastorai-pr390-full-gNlSYEGL/venv/bin/python -B -m py_compile backend/app/domain/e4b_consent.py backend/app/services/e4b_consent_boundary.py backend/tests/test_e4b_consent_domain.py backend/tests/test_e4b_consent_boundary.py` | Aprovada, com cache somente em `/tmp`. |
| Domínio e boundary puros | `PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=. /tmp/pastorai-pr390-full-gNlSYEGL/venv/bin/python -B -m pytest -c /dev/null --noconftest -p no:cacheprovider -q tests/test_e4b_consent_domain.py tests/test_e4b_consent_boundary.py` em `backend` | `67 passed in 0.41s`, sem carregar `conftest.py` global. |
| Espaços no patch | `git -C /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/e4b-c2-boundary-v1 diff --check` e `git diff --no-index --check /dev/null <cada arquivo novo>` | Sem saída; os três `--no-index` retornaram somente o código esperado de diferença, sem erro de espaço. |
| Escopo | Busca estática delimitada aos três arquivos C2 | Sem import de ORM, sessão, engine, SQL, DML, migration, transação, lock, router, worker ou adapter concreto no módulo. |

Hash SHA-256 de código: `b1bc5f6f4179f02b993b615c6a8a382eef17f38347c96818d6477e90e7042c00`.
Hash SHA-256 de teste: `11840bb01dad211b0c4fdc7a59e7baada53b07cfce3dfc8ae685cc3c2c3dd21b`.
O plano adversarial e o aceite final da LENTE, além do parecer final da
SENTINELA, foram lidos antes da execução. Eles distinguem fonte indisponível,
ausência comprovada, cadeia observada incompleta e shape contraditório. O
parecer R3 e os probes sanitizados R4 e R5 de tenant, estado, autoridade e
entradas pós-construção foram lidos para orientar estas regressões, sem acesso
a dado real.

## Limites, risco residual e rollback

Contextos e proveniência são atestações de pré-condições server-owned. Eles não
provam autenticação, autorização humana, origem real de snapshot, persistência,
unicidade, serialização, RLS, ACL ou dado vivo. Este recorte não faz staging,
retry, escrita, commit, rollback, lock, stream, caller, runtime, migration,
banco, schema, integração ou ativação.

O teste verde cobre somente os dados sintéticos e os caminhos exercitados neste
SHA. Ele não aprova commit, C3, banco, schema, migration, RLS, ACL, caller,
runtime, ativação ou efeito externo.

O rollback é abandonar o candidato local e preservar a worktree e o histórico.
Não há dado, ambiente ou efeito externo para compensar. O único próximo gate é
autorização humana nominal para o commit local do candidato C2 revisado.
