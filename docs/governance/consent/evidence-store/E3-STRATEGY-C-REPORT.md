# E2/E3 — revisão C, laboratório offline

Estado: DONE E2/E3 C em laboratório; FREEZE, sem autorização operacional.

Divisão da PR #388: a prova abaixo pertence à entrega completa preservada no
commit `c48a62f3fb26d0f1646f63038f14573e7dfeb825`. SQL, dois testes PG17 e head
candidato foram retirados apenas do controle de versão, sem alterar seus bytes;
permanecem locais, congelados para o gate de transição de head. A árvore atual
da PR contém somente os 12 arquivos de código, testes não-PG e contratos.
As provas de ACL/intent e binding SQL/head do guard original também ficam
registradas naquele commit; não são testes executáveis desta fatia sem banco.
O guard versionado verifica protocolo, ausência de callers, pins históricos e
head aprovado de 75 entradas, sem depender dos quatro arquivos locais.
Os resultados PG17 abaixo são históricos, não CI desta PR dividida.

Base: d0df9a4feaf9a234705cea256858906de528f834.
Worktree: consent-evidence-store-e1-e3-v1; branch feat/consent-evidence-store-e1-e3-v1.
Decisão do controlador identificada como 2026-09-09; não é data inferida do host.

## EXECUTADO

- Protocolo C: idempotência → desafio novo/FK ou desafio existente bloqueado →
  advisory do stream idêntico ao trigger histórico → revalidação/ledger →
  persistência ou recuperação. Sem SELECT FOR UPDATE em Pessoa.
- Adapter exige READ COMMITTED e uma chave/stream por transação. Não cria
  transação, não controla commit, não chama ledger writer nem provedor.
- Conflito de criação deve recuperar/bloquear o vencedor antes do stream,
  comparar o vínculo imutável e rejeitar identidade diferente; nunca
  reinterpretar candidato descartado por ON CONFLICT como inserido.
- Falha após staging exige rollback externo. Fonte/relógio revalidados
  depois da espera; staging não é confirmação nem aprovação.
- Snapshot privado da base preservado; replay das 75 migrations em PG17.6
  local próprio, sem portas ou rede externa, fonte read-only.
- SQL candidato revisado; preflight inspeciona memberships privilegiadas,
  sem criá-las/removê-las. Delta declara somente três tabelas novas.

## OBSERVADO

Replay canônico75: PASS, digest
84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f.
No canônico puro, authenticated permanece SEM SELECT e UPDATE em pessoas;
nenhum GRANT/policy/trigger do ledger ou de pessoas foi modificado.

As provas precisam distinguir dois ambientes: (1) canônico75+candidato puro,
(2) laboratório de compatibilidade com permissões históricas explícitas nos
pais e ledger histórico real. O segundo não demonstra que o catálogo canônico
materializa os defaults do Supabase; não se afirma estado de produção.

O writer antigo continua negado no canônico puro. Essa limitação deve ter
teste negativo próprio, não skip, fallback privilegiado ou grant oculto.

## INDISPONÍVEL / limites permanentes

Não há fonte operacional real, aplicação compartilhada, runner operacional,
purge/scheduler, caller, API, worker, ativação, envio ou GO de canário.
Recusa não concede consentimento; concedido permanece negado pelo serviço
histórico byte-pinado. Nenhuma consulta ao cofre ou uso de PII.

Resultados finais, hashes do SQL/head candidato e prova concorrente são
registrados abaixo. Head canônico permanece intacto; fonte
candidata não commitada não será chamada de SHA de implementação atestado.

## Evidência final executada

- PG17.6 descartável, sem portas publicadas, network=none; testes conectados
  somente pelo namespace do próprio contêiner. Nenhum pull de imagem.
- Base reconstruída do snapshot privado criado por
  `trusted_repository_snapshot.py`, SHA exato d0df9a4feaf9a234705cea256858906de528f834.
  SQL candidato carregado integralmente em memória e hash conferido antes e
  depois do replay local. Não é atestação de uma árvore de implementação commitada.
- Replay final das 75 migrations: exit 0. Replay candidato/delta RLS/ACL:
  exit 0, observado em 2026-09-08T21:56:16Z (relógio UTC do host).
- SQL: `backend/migrations/20260908_175522_consent_evidence_store_lab.sql`,
  35.851 bytes, SHA-256
  `99818c24e9d41ad0e28f4d97b870da4f857b6a2fb35d53b28d14bf922d871302`.
- `new_migration.py prepare-head --expected-repository-sha d0df9a4feaf9a234705cea256858906de528f834 20260908_175522_consent_evidence_store_lab.sql`:
  exit 0, somente renderização. Arquivo `migration-head.candidate.json`, SHA-256
  `97acff70731ec4068bc4e0b613d009e389ca2cc4333dfb2b88b91f50a7c50e06`.
  Catálogo candidato: 76 entradas, digest
  `0d6fc0ecacf6767edf9e6956fb6eba5dd0b214d563408a8b156a9b4c0658196b`.
  O head canônico de 75 entradas não foi substituído/publicado.
- A intent enumera somente `public.consentimento_desafio`,
  `public.consentimento_evidencia`, `public.consentimento_recibo`, os 19
  nodeids PG17 efetivamente executados e cinco provas cross-tenant.
- Suíte final: **1.288 passed, 0 failed, 0 skipped, exit 0**, 10,78 s.
  Repetição após atualização de contrato/Wiki/cobertura: mesmos 1.288 passes,
  zero skips, exit 0, 9,35 s.
  Composição: 265 documentais de consentimento, 964 regressões do ledger,
  40 domínio/UoW/guard de fonte e 19 PG17. Não é toda a suíte do produto.

Arquivos executados, todos em `backend/tests/`, com pytest, `-o addopts=`,
`-q --tb=short -p no:cacheprovider`, código montado somente leitura:

- `test_consent_catalog_evidence_succession.py`
- `test_consent_filadelfia_catalog_entry.py`
- `test_consent_immutable_catalog.py`
- `test_d2b2b2_decision_packet_docs.py`
- `test_d2b2b2_decision_payload_schema.py`
- `test_d2b2b2_decision_payload_digest_synthetic_example.py`
- `test_consent_evidence_store.py`
- `test_purpose_consent_domain.py`
- `test_purpose_consent_service.py`
- `test_purpose_consent_security.py`
- `test_consent_evidence_store_domain.py`
- `test_consent_evidence_store_uow.py`
- `test_consent_evidence_store_source_boundary.py`
- `test_consent_evidence_store_pg17.py`
- `test_consent_evidence_store_canonical_pg17.py`

## O que a prova concorrente demonstra

- Recusa primeiro, desafio existente: transação permanece aberta;
  `pg_blocking_pids` e `wait_event=advisory` comprovam que o writer histórico
  RETIRADO espera o stream. Somente depois a primeira transação é liberada.
- Retirada primeiro, desafio novo: o INSERT/FK espera a Pessoa protegida pelo
  writer histórico (`Lock/transactionid` ou `tuple`), antes do stream.
  Após o commit da retirada, o ledger relido rejeita a recusa e a transação
  externa desfaz o desafio staged. Não confundir esse lock implícito com advisory.
- Exclusão concorrente, desafio novo e existente: a exclusão pelo owner do
  laboratório espera a primeira transação, comprovada por `pg_blocking_pids`;
  depois remove a cadeia. Nenhum grant de DELETE ao writer foi acrescentado.
- Duas igrejas: remoção da cadeia A não remove B; o teste histórico inclui o
  ledger real e evidencia que ele também sofre cascata, sem anonimização.
- Replay mesma chave, conflito de chaves diferentes no mesmo desafio,
  rollback e commit ambíguo: sem duplicação ou sucesso fictício. Commit ambíguo
  é injeção de perda de confirmação após commit real, não falha de rede real.
- Reinício: novo processo Python/reconexão hidrata a prova persistida;
  não é teste de crash físico/WAL nem liberação de autenticação operacional.

O arquivo canônico possui cinco testes no esquema puro e cinco no clone
histórico. O clone declara abertamente SELECT/UPDATE de pessoas para exercitar
o writer legado; esses grants são apenas pré-condições de laboratório e NÃO
entram na migration, na intent ou no replay puro. Os nove testes do laboratório
mínimo são complementares, não substituem as cinco provas canônicas puras.

## Ocorrências de validação e encerramento

Durante o desenvolvimento houve falhas de asserções de teste: expectativa de
LEDGER_CONFLICT com fonte já incompatível (que era corretamente SOURCE_INVALID),
e expectativa de erro bruto na injeção de staging (o serviço corretamente
sanitiza para DATA_INTEGRITY). As provas finais foram ajustadas para o contrato
real, sem relaxar o domínio. As barreiras antigas que apenas ordenavam operações
foram substituídas por espera comprovada no PostgreSQL.

Uma repetição do replay recusou o cluster reutilizado por conter roles do
scaffold (exit 6, DATABASE_CONTRACT_INVALID). O cluster próprio foi descartado
e reconstruído do zero; nenhuma validação foi removida ou role compensada.
Nenhum erro dessas tentativas é contabilizado como sucesso.

`concedido` permanece bloqueado. Serviço do ledger, SQL histórico, verificador
byte-pinado, script legado de aplicação e head canônico permanecem intactos.
Não houve commit, push, PR, merge, banco compartilhado, runtime, envio, flag,
PII ou consulta ao cofre. Houve apenas edições locais e DDL/DML sintéticos em
PostgreSQL descartável, não efeito operacional externo.

Verificação final após os testes: SELECT/UPDATE de authenticated em pessoas
no canônico puro continuam false/false. `git diff --check` e checagem de
whitespace dos arquivos novos passaram. O último contêiner próprio foi
removido após a prova; apenas seus dados sintéticos em tmpfs foram descartados
(recriáveis pelas fixtures, não recuperados como estado persistente).

Próximo gate humano único: revisão da entrega E2/E3 C. Nenhuma publicação,
aplicação, concessão ou integração está autorizada por este DONE. FREEZE.
