# Evidência de laboratório E1–E3

Estado final: E1/E2/E3 DONE em laboratório com estratégia C; FREEZE.
Desfecho: [E3-STRATEGY-C-REPORT.md](E3-STRATEGY-C-REPORT.md).
O corpo abaixo preserva o registro histórico anterior à estratégia C.
Fonte base: `d0df9a4feaf9a234705cea256858906de528f834`.
Worktree: `consent-evidence-store-e1-e3-v1`.
Branch: `feat/consent-evidence-store-e1-e3-v1`.
Relógio observado do host: 2026-09-08T18:03:16Z. A data 2026-09-09 das
decisões do controlador é identificação fornecida por ele, não esse relógio.

## E1

EXECUTADO: contrato operacional, decisões de retenção/cascata, matriz de
ameaças, locks, rollback e ADR da intent registrados. Índices atualizados.
OBSERVADO: ledger possui ON DELETE CASCADE de Pessoa; permanece inalterado.
Não existe promessa de prova anonimizada sobrevivente. Nenhuma consulta ao
cofre; payload/catálogo aprovados não alterados.
INDISPONÍVEL: aplicação/validação de ambiente compartilhado, fora do escopo.

## Regressão já executada

Imagem local `pastorai-agent-local-validation-v1-backend:3799272`, pull never,
rede none, fonte ro, processo UID/GID 1000:1000, bytecode/cache pytest desativados.

- Sete arquivos documentais de consentimento: 265 passed em 5.15s; sem skips.
- test_purpose_consent_domain.py, test_purpose_consent_service.py e
  test_purpose_consent_security.py: 964 passed em 2.07s; sem skips.
- git diff --check: exit 0.

Não são provas dos módulos novos, que terão seus resultados separados abaixo.

## E3: base autenticada

EXECUTADO: new_migration.py draft com expected-repository-sha exato criou
`backend/migrations/20260908_175522_consent_evidence_store_lab.sql`.
Nenhum head foi instalado/publicado. trusted_repository_snapshot.py criou
snapshot privado do SHA base (1095 arquivos, 99 árvores).

Replay das 75 migrations dessa fonte privada em container próprio PG17.6
descartável: RESULT=MIGRATION_CATALOG_CURRENT_HEAD_REPLAYED_PG17_DISPOSABLE.
Digest histórico: `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
Imagem PG: postgres:17.6-trixie, digest
`sha256:00bc86618629af00d2937fdc5a5d63db3ff8450acf52f0636ec813c7f4902929`.
Sem portas publicadas, rede externa ou volume persistente; banco exclusivo
`migration_catalog_current_head_disposable`. A conexão administrativa fica
somente no laboratório; não é fallback de aplicação.

Tentativas iniciais registradas: exit 2 por UID sem acesso ao snapshot;
exit 5 por configuração descartável incompleta. Ajustados usuário do processo
e configuração sintética do laboratório; nenhum guard/pin/permissão alterado.
Reexecução do replay terminou exit 0. apply_migrations.py não foi invocado.

Fonte de trabalho não commitada não é commit atestado de implementação completa.
O snapshot autentica a base; o SQL candidato foi carregado em bytes e teve
hash verificado antes/depois da execução no laboratório, separadamente.

## E2: domínio, UoW e adapter internos

EXECUTADO: DTOs fechados e fonte sintética explícita, default deny, validação
adulto/self, fonte/ator/tenant, retenção, chave opaca emitida pelo processo,
digest completo do vínculo, replay, recusa, flush e reconciliação read-only.
Arquivos: backend/app/domain/consent_evidence_store.py e
backend/app/services/consent_evidence_store{,_postgres}.py; testes domain/uow.
Nenhum caller importou esses módulos. Não há begin/commit/rollback do serviço.

OBSERVADO: revisão corrigiu colisão de alias SQL, validação de apresentação,
replay depois da expiração, tenant do recibo, subconjunto canônico sem números,
e observação da própria transação de escrita. Retenção de recusa/abandono/recibo
tem testes sintéticos, inclusive ano bissexto e não-renovação por reemissão.
INDISPONÍVEL: autoridade operacional real, provider, aplicação compartilhada;
todos fora do escopo. A classe de dados ou hash não é autenticação.

## E3: candidato e provas parciais, sem publicação

EXECUTADO: prepare-head aprovado após repor os dois marcadores obrigatórios
que a primeira revisão do draft havia omitido (primeira tentativa exit 6).
Candidato renderizado em `migration-head.candidate.json`, fora do caminho
canônico; 76 migrations representadas, sem instalar o head.

- SQL: `82a88d2326c7984dbb5c2aac3f16378aa802dba7370cf67544f9281277427cb9`.
- Head candidato: `c7902240f4bc38beff919663596fb8d89ec224f5fe6cd7450bc3866e994cf96a`.
- Intent TENANT: 3 relações, 12 nodeids PG17, sendo 4 cross-tenant.

Sobre a base canônica75 reconstruída: reprodução do SQL candidato e inspeção
do delta de todas as tabelas/partições public pelo verificador da fonte privada
passaram para exatamente desafio/evidência/recibo. Isso prova a fronteira
RLS/ACL das três relações, não todas as funções/roles ou o funcionamento da UoW.

Laboratório mínimo separado: oito testes PG17 passaram, incluindo RLS/ACL,
GUC inválido/ausente, FK cruzada, cascata de uma igreja sem apagar a outra,
concorrência, rollback e reconexão. Esse laboratório fornece grants explícitos
de fixture nos pais: NÃO representa permissões fornecidas pelas migrations
canônicas. O ledger simplificado ali é testemunha de cascata, não substitui
o ledger histórico. A prova adicional canônica foi mantida justamente para
detectar essa diferença.

OBSERVADO em 2026-09-08T18:39:15Z, banco próprio
migration_catalog_current_head_disposable, PostgreSQL 170006:
authenticated possui SELECT(table pessoas)=false, UPDATE(any column)=false,
SELECT(pessoas.id)=false e SELECT(pessoas.igreja_id)=false.
Os quatro testes de test_consent_evidence_store_canonical_pg17.py FALHARAM
no SELECT FOR UPDATE de Pessoa (permission denied). Sem skips ou concessão
de privilégios para esconder a falha. Por isso E3 NÃO está concluída.

INDISPONÍVEL: prova verde da UoW no schema canônico; restart em processo novo,
commit ambíguo, concorrência e cascata completa canônicos não alcançaram seus
asserts finais, embora estejam escritos. A simulação de perda de confirmação
de commit é explicitamente injetada, não queda física de rede. Nada disso é
declarado comprovado pelos testes unitários ou pelo laboratório mínimo.

## Resultado final dos testes

Execução conjunta final, exit 0: **1265 passed em 8.25s, zero skips**:

- 265 documentais de consentimento;
- 964 regressões de domínio/serviço/segurança do ledger existente;
- 23 unitários novos de domínio/UoW;
- 5 guards de fonte/pins/ausência de callers;
- 8 PG17 no laboratório mínimo, com a limitação acima.

Separadamente: **4 failed** nos testes canônicos PG17 por ACL de Pessoa.
As primeiras execuções encontraram erros de alias PL/pgSQL e fixtures
(escape de porcentagem, savepoints, contagem e chave de consulta); corrigidos
antes do resultado final. Não houve enfraquecimento do verificador ou ledger.

## Única decisão necessária para continuar

Revisar o contrato de acesso mínimo à Pessoa e o escopo/intent RLS/ACL.
O plano §7 proíbe ampliar privilégios existentes; a intent atual não declara
alteração de pessoas. Sem essa decisão, não acrescentar GRANT, retirar o lock,
usar papel privilegiado ou liberar aplicação. Ledger permanece inalterado.
E3 BLOCKED, arquivos locais preservados, sem commit/publicação. FREEZE.

Revisão independente final confirma ausência de alternativa dentro do escopo.
Antes de fechar E3 após a decisão ACL, também revisar memberships privilegiadas
de authenticated no preflight (não somente superuser/BYPASSRLS/owner), e
estreitar negativos PG hoje baseados em DBAPIError para SQLSTATE/constraint
esperado. Não considerar oito testes mínimos como certificação geral de
privilégios. Corrigida a prova canônica ainda bloqueada para não tentar mudar
a transação para READ ONLY depois de DML; observação usa transação nova.
Helpers calculam retenção, mas não há scheduler/purge operacional implementado.

## Pins preservados

- purpose_consent.py: `65a859c5db03916791b07e1a68245ccc0b953a765fd63fa59d89616b73d9ef28`.
- verify_migration_catalog_head.py: `2fe1a93bf9c9116426683e7fd86c4f7b7c20753f7ce11a8282d9ca06087ac30d`.
- apply_migrations.py: `36e63cde6751cd0cb33e1511091068b0b04f10029ace06703eead82e0e836c65`.
- head canônico: `a591923ce771349d286cdc424d599c593e070ecea0271f3909c64719258658b4`.

## Limites

Somente efeitos locais autorizados: arquivos de trabalho, snapshot privado,
container descartável, replay e testes sintéticos. Sem push/PR/merge, runtime,
caller, API, envio, flag ou banco compartilhado. Sem PII ou credencial real.
Nenhuma autorização operacional ou indicador técnico foi aberto.
Ao encerrar, removido somente o container descartável próprio
consent-e1e3-pg17-local (ID 239d3b4e46b4...), descartando dados sintéticos
temporários sem recuperação. Código, relatórios e snapshot privado preservados.
Revalidação documental após registrar o bloqueio: 265 passed em 4.60s, exit 0.
