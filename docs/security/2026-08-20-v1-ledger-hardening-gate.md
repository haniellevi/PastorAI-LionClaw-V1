# V1 — gate de hardening do ledger de migrations

> Atualização de 2026-08-28: este documento preserva a operação histórica de
> `harden-ledger` para um ledger já existente. A implementação de
> `bootstrap-ledger`, desenvolvida e comprovada offline sobre a base
> `b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, foi integrada pela PR #323. Ela
> cria somente um ledger vazio e não está autorizada em DEV ou PROD.

## Objetivo e limite

`public.schema_migrations` é o ledger histórico usado pelo executor de arquivo
único. Em ambientes antigos ele pode ter a estrutura correta, mas ainda estar
sem RLS, policy restritiva e ACLs compatíveis. Nesse estado, o executor recusa
qualquer migration de propósito para não transformar um histórico divergente em
uma escrita insegura.

O subcomando abaixo é o único hardening previsto para esse caso:

```bash
cd backend
# O cofre/secret manager injeta a URL; nunca a coloque em argv, log ou conversa.
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada no ambiente do processo}"
python scripts/apply_migrations.py harden-ledger --confirm HARDEN_LEDGER
```

Ele não cria a tabela, não insere, remove ou reordena nomes no ledger, não toca
`supabase_migrations.schema_migrations` e não executa SQL de migration. É um
hardening de plano de controle, não um atalho para aplicar pendências.

## Bootstrap de ledger ausente, integrado e comprovado somente offline

`bootstrap-ledger` é uma operação distinta. Ela exige PostgreSQL 17,
`current_user=session_user`, confirmação literal antes da conexão e o destino
somente em `M06_MIGRATION_DATABASE_URL`:

```bash
cd backend
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada no ambiente do processo}"
python scripts/apply_migrations.py bootstrap-ledger \
  --confirm BOOTSTRAP_LEDGER
```

O comando cria numa única transação `SERIALIZABLE` apenas
`public.schema_migrations` vazio, no contrato final owner-only: colunas, chave
primária e defaults exatos, RLS habilitada, uma policy deny e revokes explícitos
de tabela e coluna para `PUBLIC`, `anon`, `authenticated`, `service_role` e,
quando existir, `agent_runtime`. Ele recusa PostgreSQL fora da versão 17,
executor público, `CREATE` alcançável no schema, default privileges perigosas,
membership que alcance o owner, objeto ou tipo homônimo, drift de estrutura,
índice, ACL, policy, trigger, rule, herança ou partição. Qualquer falha reverte
toda a criação. Reaplicar o contrato exato e vazio encerra sem mutação.

O bootstrap não descobre migrations locais, não lê, copia ou altera
`supabase_migrations.schema_migrations`, não faz backfill ou reconciliação e não
aplica nem registra migration. O ledger vazio não libera o runner: `status` e
`apply` falham fechados até uma reconciliação histórica humana produzir um
prefixo íntegro do catálogo com, no máximo, uma migration pendente.

A implementação offline, ainda não aplicada, sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, passou em 42/42 testes unitários,
87/87 em PostgreSQL 17-alpine descartável em duas execuções independentes e
87/87 em Supabase PG17 17.6.1.159 descartável em duas execuções independentes.
A revisão de segurança resultou em `GO`. A suíte RLS completa, em execução
serial limpa no PostgreSQL 17 descartável, passou em 326/326, com 3803
deselecionados e 2 warnings preexistentes, em 162.77s. A suíte offline
integral foi interrompida após 5 min sem saída ou progresso; o resultado é
`INCONCLUSIVO`, não verde nem falha e não foi reclassificado. Os workflows
Backend Tests da PR #323 e do pós-merge concluíram com `SUCCESS`. O merge
`3a5789c784017ab15a43e28c4270d25af8618359` gerou Preview e Production
automáticos do frontend na Vercel; essa metadata não prova backend, banco ou
runtime. Não houve deploy manual ou do backend, acesso aos bancos DEV ou PROD,
bootstrap, migration, credencial, restart ou alteração de flag em ambiente
compartilhado.

## Contrato fail-closed

A operação usa uma única transação `SERIALIZABLE` e um lock exclusivo da tabela.
Antes de qualquer alteração, exige:

- tabela existente com as colunas exatas `name text not null` e
  `applied_at timestamptz not null default now()`, chave primária `name` e sem
  duplicidades;
- todos os nomes do ledger público presentes no catálogo versionado local;
- papéis `anon`, `authenticated` e `service_role` com as propriedades mínimas
  esperadas;
- somente um dos estados iniciais conhecidos: RLS desligado e nenhuma policy,
  ou o estado final já endurecido;
- preservação exata dos privilégios efetivos que `service_role` já possuía.

Na mesma transação ele habilita RLS, cria exclusivamente a policy restritiva
`migration_ledger_service_role_bypass_only`, revoga ACLs de tabela e coluna de
`PUBLIC`, `anon` e `authenticated`, e então revalida grants efetivos, caminhos
por `SET ROLE`/`ADMIN OPTION`, owner e `BYPASSRLS`. Qualquer divergência faz
rollback integral; o comando não tenta corrigir roles, owners, memberships ou
histórico.

O sucesso esperado é explícito: o ledger fica protegido, mas a quantidade e a
ordem de nomes registrados permanecem exatamente as mesmas.

## Preflight operacional obrigatório

Antes de executar em qualquer ambiente hospedado, registrar o alvo, SHA do
código, autorização e os resultados somente leitura de:

1. catálogo local e SHA-256 dos arquivos que serão considerados depois;
2. `public.schema_migrations` (colunas, chave, RLS, policies, ACLs, nomes e
   duplicidades);
3. `supabase_migrations.schema_migrations` (inventário independente, sem
   preencher o ledger público a partir dele);
4. roles, owners e memberships relevantes;
5. advisors de segurança/performance e backup/restauração exigidos pelo
   ambiente.

Não usar `supabase db push`, `apply_migration`, SQL Editor ou qualquer executor
genérico para preencher lacunas históricas. Um nome presente apenas no histórico
nativo do Supabase é evidência para reconciliação humana, não autorização para
reaplicar ou registrar uma migration.

## Registro histórico dos gates V1

Os itens abaixo preservam a sequência que valia para o hardening V1. Eles não
autorizam execução atual e não substituem o estado vivo ou o gate vigente.

O hardening não libera aplicação genérica. Após preflight e smokes, cada
migration continua sendo um gate separado do executor de arquivo único. As duas
pendências V1 atuais são, nesta ordem:

1. `20260810_031050_explicit_deny_policies_for_closed_tables.sql`
   — SHA-256
   `1524fa0944dd3f4c259fa81f528570f8a4be5cff010515d4c44ac30a8df063c6`;
2. `20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql`
   — SHA-256
   `31f1f26f62594e19d6bd1cee3b4e8a4665da8207188192764d09272d880367d1`.

Cada aplicação requer o nome, SHA e `--confirm APPLY`, e deve repetir ledger,
advisors, RLS/billing sandbox e smokes antes de avançar para o próximo ambiente.

## Gate vigente

O pacote deny-state e o verificador stdlib separado do runner, comprovados
offline sobre a base `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram
integrados pela PR #325, HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no
merge `ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](../decisions/2026-08-28-migration-history-reconciliation-contract.md).
O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES HUMANAS PENDENTES / NÃO
APLICADO`. O verificador não acessa banco, rede,
ambiente ou variáveis de ambiente, não executa SQL, DML ou escrita e não
infere migration aplicada. Os ledgers permanecem independentes e todo sucesso
estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador foi integrado pela PR #327 e o hotfix pela PR #328, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. As saídas locais foram originalmente
materializadas com modo `0600` e `O_EXCL`; depois do versionamento, a proteção
dos seis artefatos depende da sanitização e da ACL do repositório, não do modo
do checkout. Eles registram inventários DEV e PROD capturados, não revisados e
bloqueados. Em PostgreSQL 17, DEV contém 33 linhas no ledger público e 6 no
nativo; PROD registra o ledger público `ABSENT_CONFIRMED`, com 0 linhas, e 32
linhas no nativo.
`native.name` permanece `null`. Ambos os pacotes estão
`EVIDENCE_CAPTURED_UNREVIEWED`, terminaram no verificador com exit `8` e
`HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou `CROSS_PACKAGE_OK`. A
matriz focal offline pós-captura passou com `163 passed, 2 skipped` em `1.40s`,
sem representar suíte integral ou reexecução PostgreSQL.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. O merge
gerou o deployment automático Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integração versiona
a evidência sanitizada já capturada, mas não revisa os inventários, não aplica
migration e não libera o runner ou qualquer autorização operacional.

A revisão independente bloqueada foi concluída; o registro externo de SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`
bloqueou DEV por divergência e PROD por evidência insuficiente. A decisão
OWNER-01 registrada está vinculada ao SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve a autorização operacional falsa e abriu somente a proposta offline.

O manifesto estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
Ele é `SOURCE_LEVEL_EXPECTATION_ONLY`, não prova o schema final de DEV ou PROD
e permanece com `OPERATIONAL_AUTHORIZATION=BLOCKED`. A revisão técnica foi
feita pelo mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. A decisão, as provas A/B idênticas
e os limites estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não altera o hardening ou o
runner. `OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`2026-08-29-offline-canonical-schema-derivation.md`](../decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

O tooling separado de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A decisão está em
[`2026-08-30-read-only-environment-attestation-tooling.md`](../decisions/2026-08-30-read-only-environment-attestation-tooling.md).
As provas terminaram em `81 passed` de `81` no foco offline,
`367 passed, 47 skipped` na seleção relacionada e `82 passed` de `82` no foco
PostgreSQL 17 TLS descartável. Sarah/Terra concluiu `GO`; Claude Opus passou no
healthcheck, mas a revisão completa travou com `Execution error` e não conta
como concluída.

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
O JSON Schema valida somente o envelope; o verificador Python é obrigatório.
O HMAC é correlação e anti-swap, não autorização humana nem observação direta
do project ref. Data API e Realtime permanecem
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
[`diagnóstico do preflight de identidade de DEV`](../decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
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

Naquele recorte histórico, foi proposto o gate
`SEPARATE_NOMINAL_DEV_FAILURE_LOGS_READ_ONLY_REVIEW_AUTHORIZATION`. O gate
proposto não foi consumido. Ele exigiria uma autorização humana nova, nominal,
exclusiva e separada para uma única revisão read-only e sanitizada dos logs da
falha DEV. A fonte, os filtros e a janela temporal mínima ainda não foram
delimitados e precisariam constar da autorização antes de qualquer acesso;
nenhum horário é inferido. Nenhum log foi acessado nesta PR. O gate proposto
não autoriza retry, nova invocação DEV, consulta a
PROD, banco ou SQL, exportação ou persistência de logs, captura,
materialização, DML,
reconciliação de ledger, corte de época, `bootstrap-ledger`, `harden-ledger`,
`status`, `apply`, migration, backfill, deploy, flag ou runtime. PROD continua
fora. UV e CD permanecem fora. Posteriormente, esse caminho foi supersedido
pelos diagnósticos de fase e pelo probe transport-only executados sob
autorizações humanas nominais próprias. O identificador permanece somente como
registro histórico e não é gate corrente nem próximo hoje.

A política de permissões foi implementada e comprovada offline pelo snapshot
privado descrito em
[`2026-09-03-trusted-repository-snapshot-policy.md`](../decisions/2026-09-03-trusted-repository-snapshot-policy.md).
O único estágio corrente global é
`OWNER_AUTHORIZE_IMPLEMENT_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`, restrito
à implementação e aos testes offline/PG17 descartáveis do executor sucessor.
Sua menção não registra consumo nem autoriza rede, captura viva, runner de
aplicação, banco compartilhado, DEV, PROD, migration ou cutover;
`operational_authorization=false` e `next_stage_authorized=false` permanecem
estritos.

## Evidência local

O comportamento foi exercitado em PostgreSQL 17 descartável com histórico fora
de ordem, RLS ausente, grants de tabela e coluna para papéis públicos, policy
inesperada, perda potencial de privilégio de `service_role` e memberships
alcançáveis por `SET ROLE`. Casos divergentes abortam e preservam o estado
anterior; o caso aprovado mantém o executor de arquivo único funcional sem
reconciliar o histórico.
