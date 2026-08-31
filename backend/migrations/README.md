# Migrations

Este projeto usa migrations SQL imperativas e versionadas. Nenhuma migration é
aplicada automaticamente por merge, deploy ou inicialização do backend.

## Convenção de nomes

- Histórico `0001` a `0017`: numeração congelada, sem renomear ou reutilizar.
- Novas migrations: timestamp UTC no formato
  `AAAAMMDD_HHMMSS_slug.sql`.

Para criar o arquivo:

```bash
cd backend
python scripts/new_migration.py "add coluna x em pessoas"
```

O nome ordena o catálogo local, mas não prova que o arquivo foi aplicado em
qualquer ambiente. O histórico nativo do Supabase
`supabase_migrations.schema_migrations` e o ledger de controle do runner
`public.schema_migrations` são objetos diferentes e nunca são reconciliados por
inferência.

## Executor fail-closed

`scripts/apply_migrations.py` possui operações distintas:

- `list`: lista o catálogo local sem conexão;
- `status`: consulta somente um ledger público já seguro e exige prefixo íntegro
  com, no máximo, uma migration pendente;
- `harden-ledger`: endurece um ledger público histórico já existente, sem criar
  ou preencher entradas;
- `bootstrap-ledger`: cria somente o ledger público vazio no contrato
  owner-only final, sem ler ou copiar histórico;
- `apply`: aplica um único arquivo previamente aprovado, com basename, SHA-256
  e confirmação literal, somente quando o ledger já forma o prefixo seguro.

O destino é aceito exclusivamente pela variável de processo
`M06_MIGRATION_DATABASE_URL`. A CLI não aceita DSN em argumento e nunca deve
receber URL, senha, token ou host em conversa, documentação ou log.

O bootstrap exige PostgreSQL 17 e confirmação explícita:

```bash
cd backend
: "${M06_MIGRATION_DATABASE_URL:?injete a URL aprovada pelo canal secreto}"
python scripts/apply_migrations.py bootstrap-ledger \
  --confirm BOOTSTRAP_LEDGER
```

Esse comando não descobre o catálogo local, não consulta ou altera
`supabase_migrations`, não registra migrations e não autoriza `status` ou
`apply`. Em um ledger vazio com múltiplos arquivos locais, ambos continuam
bloqueados.

## Estado operacional atual

`bootstrap-ledger` foi integrado pela PR #323 e comprovado somente offline,
ainda não aplicado, sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`: 42/42 testes unitários, 87/87 em
PostgreSQL 17-alpine descartável em duas execuções independentes e 87/87 em
Supabase PG17 17.6.1.159 descartável em duas execuções independentes, com
revisão de segurança `GO`. A suíte RLS completa, em execução serial limpa no
PostgreSQL 17 descartável, passou em 326/326, com 3803 deselecionados e 2
warnings preexistentes, em 162.77s. A suíte offline integral foi interrompida
após 5 min sem saída ou progresso; o resultado é `INCONCLUSIVO`, não verde nem
falha e não foi reclassificado. Os workflows Backend Tests da PR #323 e do
pós-merge concluíram com `SUCCESS`.

O merge `3a5789c784017ab15a43e28c4270d25af8618359` integrou o código em
`main`. A Vercel produziu Preview e Production automáticos do frontend; essa
metadata não prova deploy do backend, banco ou runtime.

Até a missão anterior, nenhuma execução havia ocorrido em DEV ou PROD. A
captura somente leitura documentada abaixo não altera esse estado de aplicação.
Não use `bootstrap-ledger`, `harden-ledger`, `status`, `apply`, SQL Editor,
`apply_migration`, `db push` ou MCP para preencher, reaplicar ou reconciliar
histórico em ambiente compartilhado.

O pacote deny-state versionado e o verificador stdlib separado do runner, comprovados
offline sobre a base `cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram
integrados pela PR #325, HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no
merge `ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`. O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES
HUMANAS PENDENTES / NÃO APLICADO`. O contrato está em
[`2026-08-28-migration-history-reconciliation-contract.md`](../../docs/decisions/2026-08-28-migration-history-reconciliation-contract.md).
O verificador não acessa banco, rede, ambiente ou variáveis de ambiente, não
executa SQL, DML ou escrita e não infere migration aplicada. Um sucesso
estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED` e não libera qualquer
comando desta CLI.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador foram integrados pela PR #327, no merge
`f9201a06495fad138e313e4149ad9275ff896900`, e o hotfix da PR #328 foi integrado
no merge `04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catálogo usado tem base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe`, 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.

O SQL allowlisted de captura tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`,
é somente um canal nominal e permite extrair apenas o `sanitized_capture` final.
O materializador offline recebe a captura e a chave HMAC por descritores de
arquivo independentes. O digest esperado do target binding entra somente pelo
argumento sanitizado `--expected-target-binding-sha256`; a fonte permanece
independente. `native.name` fica em `null`. Na materialização local, as saídas
são originalmente criadas com modo `0600` e `O_EXCL`; depois do versionamento,
a proteção depende da sanitização e da ACL do repositório, não do modo do
checkout. Os basenames exatos são
`migration-history-reconciliation-dev-evidence-v1.json` e
`migration-history-reconciliation-prod-evidence-v1.json`. Todo pacote permanece
bloqueado: o materializador começa por `OPERATIONAL_AUTHORIZATION=BLOCKED` e
produz `EVIDENCE_CAPTURED_UNREVIEWED`. O verificador só termina em
`HUMAN_EVIDENCE_BLOCKED` depois de validar a integridade e confirmar o ledger
nativo `PRESENT_COMPLETE` não vazio. Casos anteriores podem terminar em
`INVENTORY_BLOCKED` ou no motivo fail-closed correspondente.

O estado atual é `INVENTÁRIOS DEV E PROD CAPTURADOS / REVISÃO INDEPENDENTE
BLOQUEADA CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / NÃO APLICADO`. Em PostgreSQL 17,
DEV registrou 33 linhas no ledger público e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger público
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu `null`. Os seis artefatos
foram originalmente materializados localmente com modo `0600` e `O_EXCL`;
versionados, sua proteção depende da sanitização e da ACL do repositório,
não do modo do checkout. Ambos os pacotes estão
`EVIDENCE_CAPTURED_UNREVIEWED`, terminaram no verificador com exit `8` e
`HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou `CROSS_PACKAGE_OK`.
A matriz focal offline pós-captura passou com `163 passed, 2 skipped` em
`1.40s`; isso não é suíte integral nem reexecução PostgreSQL.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. O merge
gerou o deployment automático Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integração versiona
a evidência sanitizada já capturada, mas não revisa os inventários, não aplica
migration e não libera o runner ou qualquer autorização operacional.

A revisão independente bloqueada foi concluída e registrada sob o SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`;
ela bloqueou DEV por divergência do ledger e PROD por evidência insuficiente.
A decisão OWNER-01 registrada está vinculada pelo SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve a autorização operacional falsa e abriu somente uma proposta técnica
offline. Os registros externos não são versionados.

A captura foi somente leitura, sem DML, runner, `bootstrap-ledger`,
`harden-ledger`, `status`, `apply`, deploy, flag ou runtime. O manifesto
estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`, com 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
Ele é `SOURCE_LEVEL_EXPECTATION_ONLY`, não prova o schema final de DEV ou PROD
e permanece com `OPERATIONAL_AUTHORIZATION=BLOCKED`. A revisão técnica foi
feita pelo mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. A decisão, os 75/75 arquivos,
as provas A/B idênticas e os limites estão em
[`2026-08-29-offline-canonical-schema-derivation.md`](../../docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Ela não atesta DEV, PROD, Data API ou Realtime e não libera este executor.
`OPERATIONAL_AUTHORIZATION=BLOCKED` permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`2026-08-29-offline-canonical-schema-derivation.md`](../../docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

O tooling separado de atestação somente leitura foi implementado no commit
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A decisão está em
[`2026-08-30-read-only-environment-attestation-tooling.md`](../../docs/decisions/2026-08-30-read-only-environment-attestation-tooling.md).
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
[`2026-08-30-dev-identity-preflight-diagnostics.md`](../../docs/decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
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

A PR #344 integrou o enum sanitizado no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. Em `2026-08-31`, uma terceira e
única invocação DEV `PROCESS_INVOCATION_ONLY`, feita nesse `main`, terminou com
exit `7`, `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. A autorização nominal ficou válida
entre `2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa janela não é o
timestamp da execução. O horário operacional preciso não foi preservado e não
foi inferido.

DNS, TCP, TLS, CA, senha, autenticação, endpoint, disponibilidade, conexão,
transação e identidade permanecem `UNKNOWN`. `ROLLBACK_CONFIRMED=false` não
prova falha de rollback, e `CONNECTION_CLOSED=true` não prova que uma conexão
foi estabelecida. A autorização foi consumida. Nenhum log foi consultado e não
houve retry, captura, materialização, DML, migration, backfill, deploy, flag,
runtime ou acesso a PROD.
A limpeza removeu o diretório temporário de autorização, o launcher e a
worktree operacionais temporários; o checkout ficou limpo, sem `__pycache__` ou
`.pyc`, e o registro Git obsoleto da worktree foi removido.

O plano versionado do probe de transporte está em
[`dev-connect-tls-auth-transport-probe-plan-v1.json`](../../docs/governance/migrations/dev-connect-tls-auth-transport-probe-plan-v1.json)
e permanece `execution_disabled=true`. Esta missão somente preparou o contrato
offline: nenhum DNS foi resolvido, nenhum socket foi aberto e nenhum tráfego
TCP ou TLS foi produzido. O probe futuro deverá encerrar antes de qualquer
`StartupMessage`, usuário, banco, senha, autenticação ou SQL. A decisão e os
limites completos estão em
[`2026-08-31-dev-connect-tls-auth-transport-probe.md`](../../docs/decisions/2026-08-31-dev-connect-tls-auth-transport-probe.md).

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`. A Vercel registrou o deployment
frontend Production `6181597461`, status `17569033825`, `state=success`, em
`2026-08-31T13:02:53Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, DEV, PROD, probe ou migration. A integração
versionou apenas o plano offline: `execution_disabled=true`, implementação e
capacidade de rede ausentes, probe não executado e operação bloqueada.

O `next_gate` embutido no plano JSON conserva como evidência histórica o gate
`REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_OFFLINE_DIAGNOSTICS_PR`, consumido pela PR
#346. Ele não é um segundo gate corrente e não autoriza nova ação. O artefato
técnico permanece byte a byte intacto; o único gate corrente é o definido a
seguir e validado pelo teste documental.

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pós-merge e o deployment
automático frontend Vercel Production `6183047421`, status `17572803614`,
`state=success`, ficaram verdes. Essa metadata prova somente o frontend.

O candidato offline sobre esse `main` adiciona o runner de transporte, SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9`, e
seus testes, SHA-256
`b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
A matriz passou em `90/90`, com TLS sintético somente em loopback. O runner usa
seis descritores privados, hash DEV fixo, registro de autorização byte-bound,
CA explícita, um único DNS, endereço global determinístico e somente o
SSLRequest PostgreSQL antes do TLS; fecha antes de qualquer `StartupMessage` e
não recebe senha, usuário, banco, DSN ou SQL. O plano JSON histórico permanece
inalterado e seus campos `implementation_present=false` e
`network_capability_present=false` descrevem somente o estágio anterior. Não
houve execução real, acesso a DEV, PROD, banco ou logs.

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, integrou esse
runner no merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pós-merge ficaram em
`SUCCESS`. A Vercel registrou o deployment automático frontend Production
`6184050276`, status `17575418445`, `state=success`, em
`2026-08-31T15:23:35Z`; essa metadata prova somente o deployment do frontend e
não prova saúde funcional, backend, banco, DEV, PROD ou o probe. O estado é
`IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NÃO EXECUTADO /
OPERAÇÃO BLOQUEADA`.

O gate `SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`
foi consumido por exatamente uma invocação no checkout `1e727cd2`, runner
SHA-256 `4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9`
e `source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e`.
Ela terminou com exit `7`, fase `TLS_HANDSHAKE` e
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED`.
Resolução, política de endereço, TCP e a resposta `S` ao SSLRequest foram
confirmados; handshake e hostname não foram confirmados. Não houve retry,
senha, autenticação, sessão de banco, SQL, logs ou PROD. A causa permanece
indeterminada e o resultado não recebe categoria retroativa.

A evolução offline subsequente adiciona somente a categoria estática de falha
do handshake. O candidato tem runner SHA-256
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191`,
testes SHA-256
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489` e
`95/95` testes verdes.

A PR #350, HEAD `58af39b760b8b5be85723d3ea693abd20fe3f3cf`, foi integrada no
merge `0f8c6a77bf489f9080743ab3f7ce71097d361aea`, com
`mergedAt=2026-08-31T16:38:27Z`. Os sete workflows pós-merge concluíram com
`SUCCESS`: Backend `33415223927`, Canonical `33415223885`, E2E `33415223922`,
Environment Attestation PG17 `33415223904`, Frontend `33415223881`, RLS
`33415223955` e Tooling `33415223892`. A Vercel registrou o deployment
automático frontend Production `6185328714`, status `17578739446`, com
`SUCCESS`. Essa metadata prova somente o deployment do frontend, sem provar
saúde funcional, backend, banco, DEV, PROD, probe, migration ou runtime.

O gate `REVIEW_AND_CI_DEV_TLS_HANDSHAKE_FAILURE_CATEGORY_PR` foi consumido pela
PR #350. A categoria TLS está integrada e comprovada offline; o resultado
histórico não recebe categoria retroativa e a causa permanece indeterminada.
A árvore do merge é idêntica à do HEAD da PR.

O desenho `migration-epoch v3` deverá tratar como `KNOWN_UNVERIFIED_DRIFT`, sem nova
consulta nem inferência de migration aplicada, os sete índices observados por
evidência operacional anterior: `idx_pessoas_igreja_ativa_created`,
`idx_pessoas_igreja_ativa_tipo`, `idx_celulas_igreja_ativo_lider`,
`idx_work_queue_igreja_status_responsavel`,
`idx_conversations_igreja_assumido`, `idx_app_users_igreja_nome` e
`idx_user_roles_igreja_user`. Essa observação não foi revalidada nesta missão
e não prova o estado atual de DEV. A atestação v1 valida somente envelopes que
continuam bloqueados; ela não comprova conclusão e não pode ser reinterpretada
como `environment_attestation_complete=true`. Os artefatos históricos v1 e v2
permanecem byte-idênticos e fora do escopo.

O pacote candidato `migration-epoch v3` está congelado como
`OFFLINE_EPOCH_CUTOVER_DECISION_PACKAGE_BLOCKED`. O verificador
`backend/scripts/verify_migration_history_divergence_remediation_proposal_v3.py`
tem SHA-256 `8d7712be4f63ead2eff2c9e7af236e610b0c148acb07c85ebcd81db1f6d0877d`;
o teste `backend/tests/test_migration_history_divergence_remediation_v3.py`
tem SHA-256 `b34bd0677feb9d4453477d7503dc19beffcaf6cc8648acb85be56113b7578e24`;
a proposta
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.json`
tem SHA-256 `076d04ed179c5128c4707c07cacd8240896101a9bea62e328d2d0569900cd10e`;
e seu schema
`docs/governance/migrations/migration-history-divergence-remediation-proposal-v3.schema.json`
tem SHA-256 `88f7972780f07c7071bb4e4292e1f21c258fff47daf2ab207fc709ff34631b38`.
A matriz nova passou `87/87`, a focal estável passou `138/138`, e o verificador
terminou fail-closed com exit `8` e
`RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE`. O estado é
`RECOMMENDATION_ONLY_NOT_APPROVED`; isso comprova somente o desenho offline e
não autoriza evidência viva, cutover, migration ou runtime.

No batch offline depois integrado pela PR #351, a correção de precedência classifica
`TimeoutError` e `socket.timeout` como `DEADLINE_EXCEEDED` antes de `OSError`
genérico em cada fronteira de rede. O batch integrado tem runner SHA-256
`2e2208bfbca1214c0cec024c58716eeac7c05789c33ce36d812c0265c3810809`, teste
SHA-256 `d7161cd7dd7c63935c07431193b0d916222e5341088edbdc6d4ef85ad3063689` e
`102/102` testes verdes. Nenhum probe vivo foi executado. Os hashes da PR #350
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191` e
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489`
permanecem evidência histórica e não são substituídos.

O contrato D3 fail-closed integrado usa
`backend/app/agent/private_checkpoint.py`, SHA-256
`098d7186d59b2be9c231e3ca41e328b69901d4bc3e3f9b09651b902c07768f33`,
`backend/app/agent/context.py`, SHA-256
`b8d9ccea0041a81021cb2b4cf8edcbd8af0457ebf4401b021bd974edd29eea7d`, e
`backend/tests/test_agent_private_checkpoint_contract.py`, SHA-256
`2f91523e6a5daacd7c3ac08b933c7d9f857c3eec2a72b9f962c09c98d39f3c8b`.
A seleção `tests/test_agent*.py` terminou em `292 passed, 7 skipped`, com duas
advertências preexistentes. A classificação é `CONTRATO OFFLINE INTEGRADO E INATIVO`: não
há saver, migration ou wiring, e o LangGraph continua stateless.

A PR #351 foi integrada no merge
`bc97dd4e6f2fc9024e85afe8d611708699c8983a`. Os `7/7` checks pós-merge
concluíram com `SUCCESS`. A Vercel registrou o deployment automático do frontend
Production `6187006353`, status `17583083885`, com `SUCCESS`. Essa metadata prova
somente o frontend e não prova backend, banco ou runtime. A preparação D3 de
estado efêmero desta branch permanece candidata offline, sem saver, migration
ou retomada, e não integra a evidência pós-merge da PR #351.

A PR #352, HEAD `c5b2b4c775592641b308de6b2ac3cd069f34dcb3`, integrou essa
preparação no merge `6c807717010a41edf3bfd3d1b2405c2f3527a696`, cuja árvore é
idêntica à do HEAD da PR. Os `7/7` workflows pós-merge concluíram com
`SUCCESS`: Backend Tests `33428905043`, Canonical Schema Derivation
`33428905057`, E2E Critical `33428905042`, Environment Attestation PG17
`33428905234`, Frontend CI `33428905212`, RLS Integration `33428905114` e
Tooling Static Checks `33428905041`. A Vercel registrou o deployment automático
do frontend Production `6187746800`, status `17584957483`, com `SUCCESS`, em
`2026-08-31T19:09:09Z`. Essa metadata prova somente o frontend e não prova
saúde funcional, backend, banco, saver, migration, memória ativa, deploy do
backend, flag ou runtime. O estado permanece `PREPARAÇÃO D3 INTEGRADA E
INATIVA`.

O gate histórico `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` foi consumido
pelo push, abertura, CI e Preview da PR #351. Ele não autorizou o merge
posterior, permanece somente como evidência histórica e não é um segundo gate
corrente.

O gate histórico `REVIEW_AND_CI_D3_EPHEMERAL_EFFECT_STATE_PR` foi consumido
pelo push, abertura, CI e Preview da PR #352. O merge e o deployment automático
do frontend Production foram autorizados separadamente; esse gate não os
autorizou. Após o consumo, ele permanece somente como evidência histórica e
não é um segundo gate corrente.

**Próximo gate único:**
`REVIEW_AND_CI_D3_TURN_IDENTITY_OFFLINE_PR`. O nome não constitui autorização
já concedida. Seu consumo exige autorização humana posterior e separada que
nomeie push, abertura da PR e GitHub CI e aceite o Vercel Preview automático.
A próxima fatia permanece exclusivamente offline e limita-se à identidade
estável de mensagem e turno e ao contrato de idempotência. Este gate não
autoriza merge, Vercel Production, saver, probe vivo, acesso a DEV ou PROD,
banco, logs, SQL, DML, migration, reconciliação, backfill, deploy, flag,
runtime, execução externa, `bootstrap-ledger`, `harden-ledger`, `status` ou
`apply`.

## Transações especiais

Algumas migrations históricas com `ALTER TYPE ... ADD VALUE` possuem contrato
transacional próprio. O executor valida os bytes e recusa controles de
transação que possam quebrar a atomicidade. Não remova wrappers ou divida um
arquivo para fazê-lo passar; qualquer incompatibilidade exige revisão da
migration e um gate separado.
