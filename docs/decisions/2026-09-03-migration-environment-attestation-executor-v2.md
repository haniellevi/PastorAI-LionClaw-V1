# Executor v2 de atestação de ambiente de migrations

**Data:** `2026-09-03`

**Estado:** `IMPLEMENTADO E COMMITADO LOCALMENTE / PROVA UNITÁRIA OFFLINE / PROVA PG17
DESCARTÁVEL IMPLEMENTADA E PENDENTE DE CI / NÃO INTEGRADO / TRUST ANCHORS
EXTERNOS PENDENTES / DEV E PROD BLOQUEADOS`

**Base versionada:** `11ae294fd4459e55cb31b3342fb8f0a766ac0a03`

**Commit local:** `1b299e7fcc709ae2528db1c3f76aa15f14dbcf06`, filho direto de
`11ae294fd4459e55cb31b3342fb8f0a766ac0a03`. A base integrada anterior
permanece `c2fb16ad9a6b028c317c56a0b02c4362ae903e26`.

## Decisão

O gate
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE` foi
consumido exclusivamente para implementar e provar unitariamente offline o
executor
`backend/scripts/execute_migration_history_environment_attestation_v2.py`, seu
schema de autorização, testes, workflow PG17 e documentação. A prova PostgreSQL
17 TLS descartável foi implementada, mas sua execução final permanece pendente
no CI/PR do commit local `1b299e7fcc709ae2528db1c3f76aa15f14dbcf06`.
O consumo não incluiu
credencial, conexão ou captura viva, DEV, PROD, migration, runner de aplicação,
cutover, deploy, flag ou runtime.

O executor é um candidato local fail-closed. O processo público materializa o
SHA Git completo solicitado por meio de
`backend/scripts/trusted_repository_snapshot.py` e reinvoca o mesmo programa a
partir desse snapshot privado. DSN, CA, registro de autorização, chave HMAC e
nonce entram somente por descritores privados herdados; não pertencem a argv,
ambiente, artefato ou saída sanitizada.

DEV e PROD possuem gates e confirmações distintos. Uma execução aceita somente
PostgreSQL 17, TLS `verify-full`, CA explícita e porta `5432` em rota direta ou
session pooler. A porta `6543` de transaction pooler é recusada porque não pode
demonstrar uma sessão estável entre as fases.

## Fronteira transacional e resultado

Quando todas as validações anteriores passam, o executor abre exatamente uma
conexão PostgreSQL e fixa o mesmo backend PID para identidade e captura. Nessa
conexão ele executa **duas transações e dois snapshots PostgreSQL separados**,
ambos `REPEATABLE READ READ ONLY`:

1. a primeira transação valida identidade, versão, visibilidade e alvo e termina
   em `ROLLBACK`;
2. a segunda captura a estrutura e os invariantes allowlisted e também termina
   em `ROLLBACK`.

Portanto, "mesma conexão/PID" não significa um único snapshot transacional.
Falha de identidade, continuidade da sessão, rollback, fechamento, publicação
ou limpeza impede uma atestação positiva.

A conexão é fechada antes de materializar e publicar o único artefato v1
sanitizado. O arquivo publicado é reaberto e validado pelo verificador v1, e a
limpeza fica vinculada ao inode observado para não remover um substituto. Mesmo
no caminho técnico completo, o resultado deliberado é bloqueado, com exit `8`,
`ENVIRONMENT_ATTESTATION_COMPLETE=false`,
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false`.
`APPEND_ONLY_AUDIT_INTEGRITY`, Data API e Realtime continuam fora da prova.

O executor não contém caminho para DML, bootstrap, hardening, status, apply,
reconciliação, backfill ou migration. Um artefato produzido por ele não libera
o runner e não aprova a proposta `migration-epoch v3`.

Por hashes e `path-checks`, o candidato fecha a cadeia executável transitiva
offline `materializer -> canonical derivation -> source manifest verifier ->
catalog head verifier`. Esse fechamento prova somente o encadeamento estático
no snapshot confiado; não declara que a prova PostgreSQL 17 foi executada.

## Trust anchors ainda ausentes

O candidato **não está pronto para DEV ou PROD**. Antes que qualquer segredo
seja entregue ao processo ainda faltam, fora da confiança autoafirmada do
próprio executor:

- autenticação do gate humano nominal por assinatura verificável ou launcher
  externo confiável; os campos `owner` e `executor` e o HMAC atual vinculam o
  registro, mas não provam por si só quem autorizou;
- runtime e dependências pinados e atestados externamente. O processo público e
  o child exigem Python `3.13.14`, `-I -B`, `isolated`, `safe_path`,
  `no_user_site` e `dont_write_bytecode`; o child ainda exige
  `psycopg2-binary==2.9.12`, libpq 17 e módulos sob o prefixo privado sem
  escrita ampla. Mesmo assim, o bootstrap/interpreter inicial precisa ser
  confiado antes da abertura dos descritores secretos;
- anti-replay durável. `single_attempt=true`, nonce e
  `PROCESS_INVOCATION_ONLY` valem apenas no processo e não formam um registro
  persistente de consumo;
- cerimônia segura para fornecer uma credencial temporária de visibilidade
  integral, a CA oficial vigente e hashes independentes de project ref, banco e
  `system_identifier`, sem chat, `.env`, Git ou logs.

Processos sob o mesmo UID permanecem na mesma fronteira de confiança POSIX. O
token do child e o snapshot protegem continuidade e anti-swap dentro dessa
fronteira; não são uma sandbox contra um processo hostil com o mesmo UID.
O checkout físico `0775`, consumidores legados ainda não migrados e o bootstrap
anterior ao launcher mantêm o P2 de permissões aberto globalmente; o snapshot
mitiga o caminho somente para consumidores migrados sob trust anchor externo.

Por isso a saída declara explicitamente
`AUTHORIZATION_TRUST_REQUIREMENT=EXTERNAL_NOMINAL_GATE_AUTHENTICATION_REQUIRED`
e `RUNTIME_TRUST_REQUIREMENT=EXTERNALLY_PINNED_RUNTIME_REQUIRED`. Essas linhas
registram requisitos ausentes; não são prova de que o processo público, o
launcher ou os file descriptors já estejam sob uma raiz externa confiável.

## Estado histórico preservado

A execução DEV anterior terminou em `TLS_HANDSHAKE`; sua causa continua não
determinada e esta implementação offline não a reclassifica. DEV permanece
`BLOCKED_LEDGER_DIVERGENCE`, PROD permanece
`BLOCKED_EVIDENCE_INSUFFICIENT` e a revisão independente da proposta v3
permanece `PENDING_INDEPENDENT_REVIEW_OF_V3`. Nenhuma atestação de ambiente,
decisão humana de cutover ou aplicação de migration foi realizada.

O `next_gate` `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` permanece no
pacote v3 congelado, byte-idêntico, como registro histórico consumido pela PR
#351. Ele não é o gate global corrente e não deve ser reescrito in-place.

## Provas e rollback

A matriz unitária adversarial foi executada localmente. A prova PostgreSQL 17
TLS descartável está implementada para cobrir os dois ambientes sintéticos com
CAs e endereços separados, mas ainda precisa executar sem skips no CI do commit
local `1b299e7fcc709ae2528db1c3f76aa15f14dbcf06`. Esses testes não usam segredo
do GitHub nem equivalem a DEV ou PROD. Os totais PG17 do job de CI só podem ser
registrados após essa execução.

As evidências locais foram reexecutadas em `2026-09-03` com Python `3.12.3` e
pytest `9.1.1`, mantendo três contextos distintos:

1. No snapshot privado `0700/0600` criado por
   `trusted_repository_snapshot.py` para o SHA exato `1b299e7`, a seleção
   `tests/test_*migration*.py`, `tests/test_trusted_repository_snapshot.py` e
   `tests/test_d2b2b2_decision_packet_docs.py` coletou 961 testes: 801
   aprovados, 160 skips, zero falhas e zero erros
   (`2026-09-03T22:50:56-03:00` a `22:51:11-03:00`).
2. No mesmo snapshot privado, os 102 testes do probe histórico de transporte
   TLS, os 22 testes de seu plano e o teste de regressão de CA privada passaram
   `125/125` (`2026-09-03T22:50:14-03:00` a `22:50:18-03:00`). Essa é prova do
   probe histórico, não do executor v2 nem do job PG17.
3. No checkout compartilhado, a seleção explícita dos testes documentais, da
   proposta v3, das 58 unidades do executor v2, dos três casos PG17 do executor
   e apenas do contrato estático do workflow coletou 186 itens. Após a
   reconciliação documental, terminou com 183 aprovados, três skips PG17 e zero
   falhas (`2026-09-03T22:53:49-03:00` a `22:53:53-03:00`). Essa seleção não
   inclui a suíte legada v1 completa, que permanece fail-closed quando executada
   diretamente sob o layout `0775`.

Essas evidências são offline e não substituem a execução sem skips do job
PostgreSQL 17 no CI, nem provam ambiente compartilhado.

Como não houve efeito vivo, o rollback consiste em não integrar ou em reverter
o candidato local. Artefatos e snapshots temporários devem ser removidos por
identidade; nenhuma permissão do checkout compartilhado deve ser alterada.

## Próximo gate único

O único estágio corrente global é
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`,
restrito à consulta remota somente leitura de `refs/heads/main`, ao preflight da
base, ao push da branch candidata, à abertura da PR e à observação do CI e do
Vercel Preview automáticos. Não autoriza merge, banco compartilhado, DEV, PROD,
migration, runner ou alteração de flags;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

Somente após a integração posterior sob gate próprio e o CI verde, o estágio
funcional futuro poderá ser
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_EXECUTOR_V2_EXTERNAL_TRUST_ANCHORS_OFFLINE`;
ele não é o estágio corrente nem está autorizado.
