# SPEC_PROGRESS - PastorAi-1.0

## Registro historico: 5/5 sprints concluidas (pipeline architecture-review C1/RLS — run 20260707_112731-2c3953)
Ultima atualizacao do registro historico: 2026-07-07T19:14:45.251Z

## Estado reconciliado em 2026-08-28

Os marcadores `[CONCLUIDA]` abaixo preservam a evidencia das sprints que os produziram. Eles nao significam que a visao integral WhatsApp-first esteja pronta nem substituem a validacao do codigo atual.

Baseline confirmada no codigo:

- a baseline auditada e `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; ela nao
  e um ponteiro movel de branch. A implementacao D2B2b3A veio do merge #320
  `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`;
- o LangGraph atual e compilado sem checkpointer duravel; configurar `AGENT_GRAPH_CHECKPOINT_URL` apenas produz um aviso e a execucao continua stateless;
- o runtime resolve tenant, Pessoa, papel autenticado e permissoes no servidor antes das tools existentes;
- a PR #313 integrou a D2A no `origin/main`
  `1fbe1f499e81d22102d6f0507e31a59816a93055`; ela adiciona somente uma
  fronteira PostgreSQL privada e inativa, com `agent_runtime` sem login, helper
  de tenant e factory exclusiva ainda desconectada do worker e do LangGraph;
- `report_capture` extrai um resumo e registra evento de auditoria, mas nao persiste o relatorio canonico de `celula_reuniao`;
- OpenAI BYO e o provedor do PastorAI; OpenRouter nao faz parte do produto.

Roadmap funcional aprovado e ainda pendente:

1. contexto duravel e isolado por tenant, com historico privado, resumo e exclusao integral apos solicitacao da pessoa pelo WhatsApp e aprovacao admin;
2. conhecimento oficial formado por dados estruturados e documentos aprovados, sem promocao automatica de conversas;
3. consentimentos separados para atendimento solicitado, cuidado pastoral, tarefas operacionais e comunicados;
4. uma definicao global e versionada do LangGraph com especialistas comuns por dominio;
5. primeira vertical completa: relatorio de celula pelo WhatsApp, com lembrete, texto ou audio, resumo, confirmacao, gravacao canonica e comprovante;
6. painel web reservado a configuracao, governanca, supervisao, excecoes e conclusao de acoes sensiveis.

A PR #315 integrou a D2B1 no `origin/main`
`84c5b71b415340868c1b0664e892b8b0350d91f4`. Ela cria
`TrustedAgentContext` imutavel e tipado fora do `AgentState`, injeta a fronteira
por `StateGraph.context_schema`, revalida contexto e estado antes do caminho
compilado, do caminho direto e de cada node, e preserva a mesma instancia de
`PrivilegeContext` ate as tools. A entrada e o snapshot de Pessoa recusam
chaves de autoridade, IDs, telefone e campos nao necessarios ao turno.

O merge passou em 2.770 testes offline, com 278 desselecionados, e 278 testes
RLS, com zero skips. Os cinco workflows da PR e os cinco pos-merge ficaram
verdes. O monitor registrou 62 testes aprovados e tres skips; a validacao Node
registrou quatro testes aprovados. O LangGraph permanece stateless.

A PR #317 integrou a D2B2a no `origin/main`: HEAD
`8ba5c988e9169703c923b1f1a3e47d1c427531e1`, merge
`bce5a9a434077e488cea8baae3e9dd7c7c4ba0f1`. Ela adiciona migration, ORM,
dominio e servico interno sem caller para o ledger append-only
`public.consentimento_finalidade_evento`. As finalidades sao
`atendimento_solicitado|cuidado_pastoral|tarefas_operacionais|comunicados`; os
estados, `concedido|retirado`; e as fontes v1,
`whatsapp_inbound|painel_autenticado`. No INSERT inicial, usa `versao_termo` e
exige operador apenas no painel. A exclusao referencial posterior do AppUser
pode anonimizar o operador via `ON DELETE SET NULL`, preservando o evento. A
idempotencia e por tenant, e a sequencia por stream e atribuida em trigger sob
advisory lock transacional.

A tabela integrada forca RLS com barreira restritiva GUC-only e ACL minima.
Nao ha backfill do legado; opt-out global prevalece. Nao existe API, wiring ou
caller em WhatsApp, painel, worker, LangGraph, tool ou broadcast. A migration
nao foi aplicada em Supabase e nao fez deploy manual ou do backend, ativacao ou
canario. O merge gerou deployment frontend automatico pela integracao Vercel. Textos e
base juridica por finalidade, retencao e RBAC bloqueiam writers e ambiente
compartilhado.

Validacao local anterior ao merge: o modulo de contrato, incluindo a aplicacao do
SQL inalterado duas vezes em `public`, passou em 11 de 11 no PostgreSQL 17 e na
imagem Supabase PG17, sempre em bancos descartaveis; 288 de 288 testes RLS e 32
de 32 testes offline D2B2a. Os cinco workflows da PR #317 e os cinco
pos-merge ficaram verdes. Na PR: Backend `33145078616`, E2E `33145078590`,
Frontend `33145078637`, RLS `33145078608` e Tooling `33145078672`. Depois do
merge: Backend `33145205844`, E2E `33145205869`, Frontend `33145205852`, RLS
`33145205864` e Tooling `33145205854`. Todos concluiram com `SUCCESS`.

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, integrou a
D2B2b1 no merge `74951828f48994622a112d8e59eb978e5fb4f406`. A fatia fecha
apenas a fronteira tecnica pura: chave idempotente
opaca criada em componente confiavel do servidor, RBAC deny-first e negacao
incondicional de qualquer `concedido` enquanto faltar politica humana aprovada.
Ela nao reidrata chave por valor; retry entre processos aguarda um recibo
duravel autenticado que prove a origem da chave.
Ela nao adiciona migration, catalogo, evidence store, caller, banco, API,
LangGraph, writer ou efeito externo. `painel_autenticado`, papel amplo ou
autoria do operador nao provam manifestacao do titular; LLM e cliente nunca
escolhem finalidade, base juridica, versao, prova ou capacidade.

Validacao D2B2b1: 1.114 de 1.114 testes no recorte focal e fronteiras
adjacentes; 288 de 288 testes RLS contra PostgreSQL 17 descartavel, sem falhas
ou skips; Backend Tests integral e os outros quatro workflows da PR ficaram
verdes. Os cinco workflows pos-merge tambem ficaram verdes. A PR gerou Preview
e o merge gerou deployment frontend Vercel automatico classificado como
Production; nao houve deploy manual ou do backend, migration, Supabase,
ativacao ou canario. O PostgreSQL temporario foi removido.

Sequencia corrente: D2B2b3A integrada e inativa, com migration, persistencia,
API e painel do Console Master limitados a rascunhos por igreja; depois vem o
fluxo nominal de atestado e aprovacao do pacote humano e
juridico por finalidade. Somente uma fatia posterior pode projetar catalogo
imutavel, binding por tenant, prova correlacionada, retencao e callers
server-side seguros. `D2C` continua bloqueada. Depois dela, `D3` implementa
memoria privada duravel e exclusao integral.
O template D2B2b2 permanece `TEMPLATE_ONLY / NOT_APPROVED` e esta descrito em
`docs/decisions/2026-08-28-d2b2b2-consent-decision-packet-contract.md`; o merge
do template nao satisfaz o gate humano.
A decisao D2B2b3A esta em
`docs/decisions/2026-08-28-d2b2b3-master-governance-drafts.md`. Ela nao permite
ao Master escolher hipotese juridica, atestar, aprovar, representar papel da
igreja ou preencher registros nominais. E-mail nao e autoridade e todo rascunho
operacional permanece `DRAFT_NOT_APPROVED`.
A PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, foi integrada no
merge `947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`. Os cinco workflows da
PR concluiram com `SUCCESS`: Backend Tests `33165481522`, E2E Critical
`33165481590`, Frontend CI `33165481546`, RLS Integration `33165481561` e
Tooling Static Checks `33165481549`. Os cinco pos-merge tambem concluiram com
`SUCCESS`: Backend Tests `33167430903`, E2E Critical `33167430935`, Frontend CI
`33167430953`, RLS Integration `33167430898` e Tooling Static Checks
`33167430895`.
O merge gerou o deployment automatico Vercel frontend Production `6140373952`,
com `SUCCESS`. Essa metadata prova somente o frontend nesse ambiente; nao prova
backend, banco ou Supabase. No preflight historico de 2026-08-28, DEV e PROD
confirmaram a ausencia da migration D2B2b3A; o estado vivo atual nao foi
revalidado. Naquele registro, a flag
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` estava `false`, e nao houve deploy
manual ou do backend, wiring, ativacao ou canario.
No baseline `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD
somente leitura confirmou `DATABASE_URL` presente e
`M06_MIGRATION_DATABASE_URL` ausente. `current_user` e `session_user`
convergiram para a mesma identidade sanitizada; a role runtime possui
`NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, e owner de `public.igrejas` e
`public.app_users` e possui `SELECT` e `REFERENCES` efetivos nessas tabelas-pai.
A tabela alvo D2B2b3A, o validator e a propria `public.schema_migrations`
estavam ausentes. No preflight historico de 2026-08-28, DEV e PROD confirmaram
a ausencia da migration D2B2b3A; o estado vivo atual nao foi revalidado. A PR
#321 integrou a reconciliacao documental anterior
no merge `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o
deployment automatico Vercel frontend Production `6141449639`, com `SUCCESS`,
em 2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar
backend, banco ou Supabase. O preflight VPS em si nao executou deploy manual ou
do backend, migration, restart ou alteracao da flag. A leitura historica
comprovou identidade, ownership e ACL do caminho runtime observado naquele
preflight, mas nao o comportamento da tabela futura sob `FORCE RLS`. Naquele
preflight, o caminho de migration estava bloqueado pela ausencia de
`M06_MIGRATION_DATABASE_URL` e do ledger publico; o estado vivo atual desses
itens nao foi revalidado.
Universidade da Vida e Capacitacao Destino permanecem na visao futura, fora da
missao atual. A D2A continua inativa: a integracao nao aplicou migration em
ambiente compartilhado, nao provisionou credencial, nao conectou o runtime, nao
fez deploy manual ou do backend, nao promoveu a producao e nao ativou o agente.
O unico deploy associado a D2A foi o preview automatico da PR, que nao prova
execucao do backend nem ambiente compartilhado.

A D2B1 nao adicionou migration, nao acessou Supabase, nao provisionou
credencial, nao conectou a fronteira privada D2A, worker, fila ou checkpointer,
nao fez deploy manual ou do backend, nao promoveu a producao, nao ativou o
agente e nao executou canario. O preview automatico da PR nao prova execucao do
backend.

A implementacao foi desenvolvida e comprovada offline sobre a base versionada
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`. O codigo integrado pela PR #323
adiciona o subcomando explicito e fail-closed
`bootstrap-ledger`, separado de `harden-ledger`. Ele exige
`--confirm BOOTSTRAP_LEDGER` antes da conexao e aceita o destino somente por
`M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17, cria em uma transacao
`SERIALIZABLE` apenas o ledger vazio `public.schema_migrations`, com colunas,
chave primaria e defaults exatos, owner estavel, RLS, policy deny e ACL
owner-only. Conflito de objeto, schema, ownership, grants, default privileges,
membership ou forma fisica aborta com rollback; a reaplicacao exata e vazia e
um no-op.

Validacao da implementacao offline: 42/42 testes unitarios; 87/87 em PostgreSQL 17-alpine
descartavel em duas execucoes independentes; 87/87 em Supabase PG17 17.6.1.159
descartavel em duas execucoes independentes; revisao de seguranca `GO`. A suite
RLS completa, em execucao serial limpa no PostgreSQL 17 descartavel, passou em
326/326, com 3803 deselecionados e 2 warnings preexistentes, em 162.77s. A
suite offline integral foi interrompida apos 5 min sem saida ou progresso; o
resultado e `INCONCLUSIVO`, nao verde nem falha e nao foi reclassificado. Os
workflows Backend Tests da PR #323 e do pos-merge concluiram com `SUCCESS`. O comando
nao consulta nem altera `supabase_migrations`, nao descobre o catalogo, nao faz
backfill ou reconciliacao e nao aplica ou registra migration. `status` e
`apply` continuam bloqueados enquanto o ledger vazio nao tiver sido reconciliado
por humanos em um prefixo integro do catalogo, com no maximo uma migration pendente.

O `bootstrap-ledger` esta integrado em `main`, mas continua nao aplicado. A PR
#323, HEAD `74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada pelo
merge `3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`; seus cinco workflows e os cinco pos-merge concluiram
com `SUCCESS`. A Vercel registrou o Preview automatico frontend `6143773477`,
com `SUCCESS`, em `2026-08-28T15:22:43Z`, e o Production automatico frontend
`6143819601`, com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam
somente o frontend, sem provar backend, banco ou runtime. Nao houve deploy
manual ou do backend, acesso aos bancos DEV ou PROD, bootstrap ou migration
compartilhada, restart ou alteracao de credencial, flag, runtime, agente ou
canario. O preflight PROD e o deployment automatico frontend da PR #321
permanecem historia separada.

O pacote deny-state versionado e o verificador stdlib separado do runner,
desenvolvidos e comprovados offline sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram integrados pela PR #325,
HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
`docs/decisions/2026-08-28-migration-history-reconciliation-contract.md`.
O estado e `INTEGRADO / COMPROVADO OFFLINE / DECISOES HUMANAS PENDENTES / NAO
APLICADO`. A integracao nao acessou DEV ou PROD, nao materializou inventario de ambiente ou
decisao humana e nao reconciliou nenhum ledger. O verificador nao acessa banco,
rede, ambiente ou variaveis de ambiente, nao executa SQL, DML ou escrita e nao
infere migration aplicada. Os ledgers nativo e publico permanecem independentes
e todo sucesso estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

Os cinco workflows da PR e os cinco pos-merge concluíram com `SUCCESS`. A
Vercel registrou o Preview automatico frontend `6147914118`, com `SUCCESS`, em
`2026-08-28T20:16:00Z` no HEAD, e o Production automatico frontend
`6147952424`, com `SUCCESS`, em `2026-08-28T20:18:55Z` no merge. Essas metadatas
provam somente o frontend, sem provar backend, banco ou runtime; nao houve
deploy manual ou do backend, migration, bootstrap, hardening, restart, flag ou
runtime nesta missao.

A prova local preservada e `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador foram integrados pela PR #327, HEAD
`c4f7a25b81a8091a0d74783c816a168bb7adf44d`, no merge
`f9201a06495fad138e313e4149ad9275ff896900`. A PR #328 integrou o hotfix, HEAD
`2cbdfaf39ae11d984f0aa27dfcf0910c25984840`, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catalogo de base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe` contem 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`; o SQL
allowlisted tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`.

O estado e `INVENTARIOS DEV E PROD CAPTURADOS / REVISAO INDEPENDENTE BLOQUEADA
CONCLUIDA / DECISAO OWNER-01 REGISTRADA / NAO APLICADO`. Em PostgreSQL 17, DEV registrou
33 linhas no ledger publico e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger publico
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu sempre `null`. Os dois
pacotes estao em `EVIDENCE_CAPTURED_UNREVIEWED`; cada verificacao terminou com
exit `8`, `HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou
`CROSS_PACKAGE_OK`. A matriz focal offline pos-captura passou com `163 passed,
2 skipped` em `1.40s`; isso nao e suite integral nem reexecucao PostgreSQL.

A captura ocorreu somente em leitura e nao executou DML, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, deploy, flag ou runtime.
Os seis artefatos permanecem bloqueados e nao provam decisao humana, migration
aplicada, prefixo reconciliado ou autorizacao operacional.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pos-merge concluiram com `SUCCESS`. O merge
gerou o deployment automatico Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integracao versiona
a evidencia sanitizada ja capturada, mas nao revisa os inventarios, nao aplica
migration e nao libera o runner ou qualquer autorizacao operacional.

A revisao de `REVIEWER-01`, vinculada pelo SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`,
bloqueou DEV por divergencia do ledger e PROD por evidencia insuficiente.
`OWNER-01` aceitou o bloqueio no registro externo de SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve `operational_authorization=false` e autorizou somente a proposta
tecnica offline. Os registros externos nao foram versionados e os pacotes
continuam bloqueados.

O manifesto estatico de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`. Ele fixa 75 migrations e o
digest `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`,
mas declara `SOURCE_LEVEL_EXPECTATION_ONLY`: nao prova o schema final de DEV ou
PROD. O verificador terminou em
`SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY`, com
`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`ENVIRONMENT_ATTESTATION_COMPLETE=false`. A revisao tecnica foi feita pelo
mesmo executor e nao e independente.

A derivacao canonica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartavel, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. As execucoes A e B produziram os
mesmos 388390 bytes, o SHA-256
`7040a54d80c0ee4f37e1986ff0a579db275e45c129f4fdafcd66788e22a3eb3e` e o
fingerprint `8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370`.
A evidencia e os limites estao na
[`decisao de derivacao offline`](docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Isso nao atesta DEV, PROD, Data API ou Realtime; `OPERATIONAL_AUTHORIZATION=BLOCKED`
permanece obrigatorio.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisao de derivacao offline`](docs/decisions/2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

A ferramenta separada de atestacao read-only foi implementada no commit tecnico
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A prova focal offline passou em
`81/81`, a selecao relacionada terminou em `367 passed, 47 skipped` e a prova
focal em PostgreSQL 17 TLS descartavel passou em `82/82`. Sarah/Terra concluiu
`GO`; o healthcheck do Claude Opus passou, mas a revisao completa travou com
`Execution error` e nao foi reclassificada como revisao concluida.

A PR #337, HEAD `abf6f823336b81e93ec1c942dcd5a357d8ac797c`, integrou o tooling
no merge `278afb205a3b4735d4aeb66e2e585f71fd562ef7`, com
`mergedAt=2026-08-30T11:38:16Z`. Os sete workflows do push em `main`
concluiram com `SUCCESS`: Environment Attestation PG17 `33309430738`, Frontend
CI `33309430763`, Canonical Schema Derivation `33309430775`, Backend Tests
`33309430797`, Tooling Static Checks `33309430744`, E2E Critical `33309430731`
e RLS Integration `33309430799`.

A Vercel registrou o deployment frontend Production `6166209567`, com
`state=success`; o deployment e seu status registraram
`created_at=2026-08-30T11:39:02Z`. Essa metadata prova somente o frontend e nao
prova backend, banco ou runtime. O estado corrente e
`INTEGRADO E COMPROVADO OFFLINE / AMBIENTES NÃO CONSULTADOS / OPERAÇÃO BLOQUEADA`.

O tooling integrado permanece fail-closed, conforme a
[`decisao de atestacao read-only`](docs/decisions/2026-08-30-read-only-environment-attestation-tooling.md).
Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O schema JSON valida somente o envelope; o verificador Python continua
obrigatorio. O HMAC serve para correlacao e anti-swap, sem substituir
autorizacao humana nem observar diretamente o project ref. Data API e Realtime
permanecem `PLATFORM_SURFACES_UNATTESTED`.

`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false` permanecem invariantes. Runner, DML,
migration, reconciliacao, backfill, deploy, flag e runtime continuam
bloqueados.

Sobre a base versionada `fe7dcd394bd1cfdc96204ad994bcba9f0c96adb4`, o runner
DEV preflight-only foi implementado e comprovado offline antes da integracao.
Os SHA-256
congelados sao: runner
`1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`, testes
unitarios `d96fab1afe99531e3cee0f84bc285876de303ed0265fa41c51f8da9a7bcab0a0`,
prova PG17 `ceecfe9afa09066e4863e93be556b8f92c00a2992e0a0aef3b4253458f6fc318`,
testes de atestacao existentes
`68f9790a734f8adf78db8a716a5c2d99adad165f00737f922db90afa614b4ed8` e
workflow `80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
Os unitarios passaram em `210/210`; duas provas locais sequenciais no
PostgreSQL 17 TLS passaram em `1/1` para a atestacao existente e `1/1` para o
runner com CA por FD.

A PR #340, HEAD `b29d3f494eabc3a04fe7f2c434758ad274f03930`, integrou o
runner no merge `82413edb884125d4d8f6e7946ffcaaf48ed8491c`, com
`mergedAt=2026-08-30T13:55:11Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: E2E `33315460948`, Frontend `33315460933`, Tooling
`33315460941`, RLS `33315460942`, Backend `33315460949`, Environment
Attestation PG17 `33315460934` e Canonical Schema Derivation `33315460939`.
A Vercel registrou o deployment frontend Production `6167369343`, com
`state=success`, em `2026-08-30T13:55:56Z`. Essa metadata prova somente o
frontend e nao prova backend, banco ou runtime.

O contrato usa `TLS_MODE=VERIFY_FULL_EXPLICIT_CA` e exige que o digest da CA,
`TLS_CA_CERTIFICATE_SHA256`, esteja vinculado a autorizacao. O escopo
`PROCESS_INVOCATION_ONLY` exige nova autorizacao nominal para cada invocacao.
O HMAC serve somente correlacao e anti-swap e nao substitui autorizacao humana.
O resultado produz zero arquivo, zero recibo, zero captura e zero
materializacao. Os buffers de chave e nonce sao zerados, os descritores sao
fechados e os certificados TLS temporarios sao removidos apos a prova. DEV e
PROD nao foram consultados. PROD esta explicitamente
fora. PROD continua fora. Estado:
`INTEGRADO E COMPROVADO OFFLINE / DEV/PROD NÃO CONSULTADOS / OPERAÇÃO
BLOQUEADA`.

Em 2026-08-30, ja no `main`
`64cc157d649256a4a9819741f4276c0420590fd1`, duas invocacoes DEV foram feitas
sob autorizacoes humanas nominais distintas e exclusivas, cada uma limitada a
`PROCESS_INVOCATION_ONLY`. O timestamp operacional preciso nao foi preservado;
nenhum horario UTC foi inferido. Ambas terminaram com exit `7`,
`RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED`, `ROLLBACK_CONFIRMED=false` e
`CONNECTION_CLOSED=true`. Em ambas, `OPERATIONAL_AUTHORIZATION=false`,
`NEXT_STAGE_AUTHORIZED=false`, `CAPTURE_EXECUTED=false`,
`MATERIALIZATION_EXECUTED=false` e `PROD_ACCESSED=false`. Esses campos nao
provam se houve conexao, nao provam sucesso ou falha de autenticacao e nao
identificam a causa raiz.

O diagnostico posterior passou em `2/2` no caminho full-main sobre PostgreSQL
17 TLS descartavel e em `97/97` no foco offline. O runner permaneceu intacto,
SHA-256 `1973aab6c6af09105acfbfe03396b048c389d059ae87ff1b673198ba35fb280f`,
assim como o workflow, SHA-256
`80c53134e91a4221201052ff6c6782f76cdcaa9968c3406a46c3bca16e878ddf`.
A prova PG17 ampliada tem SHA-256
`ddbc092216604e65cf86070d409837c7d328da96116ae5ea8d0947195b421b9e`.
Essa prova local nao reclassifica DEV nem determina a causa do bloqueio. A
evidencia detalhada esta em
[`2026-08-30-dev-identity-preflight-diagnostics.md`](docs/decisions/2026-08-30-dev-identity-preflight-diagnostics.md).
Estado: `DUAS INVOCACOES DEV BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO
CONSULTADO / OPERACAO BLOQUEADA`.

A PR #342, HEAD `5076c47b19fffe503e823d68c6dadfc59b11ed5d`, integrou a
prova diagnostica no merge `bc202da6c0ef83e03ded4392e508441cd4d6a188`, com
`mergedAt=2026-08-30T15:24:45Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Canonical `33319560819`, Environment Attestation PG17
`33319560923`, E2E `33319560908`, RLS `33319560769`, Backend `33319560836`,
Frontend `33319560781` e Tooling `33319560786`. A Vercel registrou o
deployment frontend Production `6168185324`, com status `17531418022`,
`state=success` e `created_at=updated_at=2026-08-30T15:25:32Z`. Essa metadata
prova somente o frontend e nao prova backend, banco ou runtime.

A integracao nao repetiu o preflight, nao consultou logs, nao fez novo acesso a
DEV ou PROD e nao determinou a causa do exit `7`. Runner e workflow permanecem
intactos. Estado: `INTEGRADO E COMPROVADO OFFLINE / DUAS INVOCACOES DEV
BLOQUEADAS / CAUSA NAO DETERMINADA / PROD NAO CONSULTADO / OPERACAO
BLOQUEADA`.

Sobre a base `3685bbcaf11d5a20b3492953d897cb6a459701a8`, o candidato
pre-merge adiciona o enum estatico `PREFLIGHT_FAILURE_PHASE` com dez valores:
`PRECONNECT_GUARDS`, `CONNECT_TLS_AUTH`, `SERVER_VERSION`, `SESSION_GUARDS`,
`IDENTITY_VALIDATION`, `ROLLBACK`, `CURSOR_CLOSE`, `CONNECTION_CLOSE`,
`POSTCONNECT_TLS_CA_REVALIDATION` e `POST_IDENTITY_FINALIZATION`. A fase e
somente a ultima fronteira operacional iniciada, nunca a causa; em especial,
`CONNECT_TLS_AUTH` nao prova nem separa rede, TLS ou credencial. Cada saida
`BLOCKED` contem exatamente uma linha de fase, o sucesso nao a contem e a
primeira falha vence quando ha falhas posteriores.

Os SHA-256 congelados sao runner
`8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`,
unitarios `c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8` e
PG17 `d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9`.
Passaram `109 passed, 2 skipped` offline, `2/2` em PostgreSQL 17 TLS
descartavel e `222 passed, 2 skipped` no agregado relevante; `pycompile` e
`diff-check` ficaram verdes, os recursos temporarios foram removidos e
Sarah concluiu `GO`, sem P0, P1 ou P2. As duas execucoes DEV historicas com
exit `7` nao podem ser retroclassificadas. A unica `query_logs` anterior
retornou vazio e continua `EVIDENCE_INSUFFICIENT`. Esta missao nao repetiu a
consulta e nao acessou DEV ou PROD. A evidencia detalhada esta em
[`2026-08-30-dev-preflight-failure-phase-diagnostics.md`](docs/decisions/2026-08-30-dev-preflight-failure-phase-diagnostics.md).

O enum foi integrado pela PR #344 no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. Em `2026-08-31`, uma terceira e
unica invocacao DEV `PROCESS_INVOCATION_ONLY` nesse `main` terminou com exit
`7`, `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. A autorizacao era valida entre
`2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa janela nao e o horario
da execucao. O timestamp operacional preciso nao foi preservado nem inferido.
DNS, TCP, TLS, CA, senha, autenticacao, endpoint, disponibilidade, conexao,
transacao e identidade permanecem `UNKNOWN`. A autorizacao foi consumida;
nenhum log foi consultado e nao houve retry, captura, materializacao, DML,
migration, backfill, deploy, flag, runtime ou acesso a PROD.
A limpeza removeu o diretorio temporario de autorizacao, o launcher e a
worktree operacionais temporarios; o checkout ficou limpo, sem `__pycache__` ou
`.pyc`, e o registro Git obsoleto da worktree foi removido.

O probe para separar somente DNS, TCP e TLS foi preparado offline e permanece
`execution_disabled=true`; ele nao foi executado e nao possui autorizacao viva.
O contrato e os limites estao em
[`2026-08-31-dev-connect-tls-auth-transport-probe.md`](docs/decisions/2026-08-31-dev-connect-tls-auth-transport-probe.md).
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatorios.

A PR #346, HEAD `0c63dc29dc903e0e7012b9fb811b7b2ddb05ab51`, foi integrada no
merge `fb776e270bf3e2ffde0cbb28e400960591b74420`, com
`mergedAt=2026-08-31T13:02:07Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Tooling `33394774001`, Environment Attestation PG17 `33394774013`,
Canonical `33394773986`, E2E `33394774109`, Frontend `33394774063`, RLS
`33394773965` e Backend `33394774029`. A Vercel registrou o deployment
frontend Production `6181597461`, status `17569033825`, `state=success`, em
`2026-08-31T13:02:53Z`. Essa metadata prova somente o frontend e nao prova
saude funcional, backend, banco, DEV, PROD, probe ou migration. A integracao
versionou apenas o plano offline: `execution_disabled=true`, implementacao e
capacidade de rede ausentes, probe nao executado e operacao bloqueada.

A PR #347, HEAD `0a257e9aa1985860d5ea0a4506d4f7e84c7b2312`, foi integrada no
merge `36f8d13284a8f4964d0258a2a3b845323a80fe7e`, com
`mergedAt=2026-08-31T14:26:10Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`, e o deployment automatico Vercel frontend Production `6183047421`,
status `17572803614`, terminou com `state=success` em
`2026-08-31T14:26:57Z`. Essa metadata prova somente o frontend.

Sobre esse merge, o candidato implementa o probe transport-only em
`backend/scripts/probe_dev_connect_tls_auth_transport.py`, SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9`, e sua
matriz adversarial, SHA-256
`b79ff9d7473fdafd0a4fcd6ceba98b2c46f5470ef517b6663898812fe8b1296e`.
Passaram `90/90` testes exclusivamente offline, incluindo loopback TLS
sintetico descartavel. O runner recebe seis descritores privados, fixa o hash
do project-ref DEV e do registro de autorizacao, envia somente o SSLRequest
PostgreSQL de oito bytes, exige `S`, valida CA e hostname e fecha antes de
StartupMessage. Nao recebe senha, usuario, banco ou DSN e nao tenta
autenticacao nem SQL. O plano JSON permanece historico e byte-identico; seus
campos `execution_disabled=true` e `implementation_present=false` descrevem a
etapa anterior ja consumida. A unica rede desta rodada foi o `git fetch`
nominal autorizado para obter o merge; nenhum probe vivo, DEV, PROD, banco ou
log foi acessado. `operational_authorization=false` e
`next_stage_authorized=false` permanecem.

A PR #348, HEAD `af91e5218f9317a730aa29ad8d8c645312b30f19`, foi integrada no
merge `1e727cd2ea90ccfb68961174b802d595c71f355b`, com
`mergedAt=2026-08-31T15:22:49Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Tooling `33408103314`, Environment Attestation PG17 `33408103217`,
Canonical `33408103386`, Frontend `33408103193`, E2E `33408103279`, Backend
`33408103254` e RLS `33408103282`. A Vercel registrou o deployment automatico
frontend Production `6184050276`, status `17575418445`, `state=success`, em
`2026-08-31T15:23:35Z`. Essa metadata prova somente o deployment do frontend,
nao sua saude funcional, e nao prova backend, banco, DEV, PROD ou o probe. O
estado agora e `IMPLEMENTADO / INTEGRADO / COMPROVADO OFFLINE / PROBE NAO
EXECUTADO / OPERACAO BLOQUEADA`.

**Gate consumido em 2026-08-31:**
`SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`. Seu
consumo exige nova autorizacao humana nominal para exatamente uma invocacao
`PROCESS_INVOCATION_ONLY` no checkout de `main` `1e727cd2`, com runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e o
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e` exigido pelo
contrato interno. Nao autoriza retry, senha, autenticacao, sessao de banco,
SQL, logs,
captura, materializacao, DML, migration, reconciliacao, backfill, deploy manual
ou Production, flag, runtime e PROD continuam bloqueados.

Uma unica invocacao terminou com exit `7`,
`TRANSPORT_PROBE_FAILURE_PHASE=TLS_HANDSHAKE` e
`RESULT=BLOCKED_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE:TRANSPORT_BLOCKED`.
DNS, politica de endereco, TCP e a resposta `S` ao SSLRequest foram
confirmados; handshake e hostname nao foram confirmados. Nao houve retry,
senha, autenticacao, sessao de banco, SQL, logs ou PROD. A causa permanece
indeterminada e o resultado nao recebe categoria retroativa. A evolucao
offline adiciona somente uma categoria estatica de falha TLS, com runner
SHA-256 `0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191`,
testes SHA-256
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489` e
`95/95` testes verdes.

A PR #350, HEAD `58af39b760b8b5be85723d3ea693abd20fe3f3cf`, foi integrada no
merge `0f8c6a77bf489f9080743ab3f7ce71097d361aea`, com
`mergedAt=2026-08-31T16:38:27Z`. Os sete workflows pos-merge concluiram com
`SUCCESS`: Backend `33415223927`, Canonical `33415223885`, E2E `33415223922`,
Environment Attestation PG17 `33415223904`, Frontend `33415223881`, RLS
`33415223955` e Tooling `33415223892`. A Vercel registrou o deployment
automatico frontend Production `6185328714`, status `17578739446`, com
`SUCCESS`. Essa metadata prova somente o deployment do frontend, sem provar
saude funcional, backend, banco, DEV, PROD, probe, migration ou runtime.

O gate `REVIEW_AND_CI_DEV_TLS_HANDSHAKE_FAILURE_CATEGORY_PR` foi consumido pela
PR #350. A categoria TLS esta integrada e comprovada offline; o resultado
historico nao recebe categoria retroativa e a causa permanece indeterminada.
A arvore do merge e identica a do HEAD da PR.

O desenho `migration-epoch v3` devera tratar como `KNOWN_UNVERIFIED_DRIFT`, sem nova
consulta nem inferencia de migration aplicada, os sete indices observados por
evidencia operacional anterior: `idx_pessoas_igreja_ativa_created`,
`idx_pessoas_igreja_ativa_tipo`, `idx_celulas_igreja_ativo_lider`,
`idx_work_queue_igreja_status_responsavel`,
`idx_conversations_igreja_assumido`, `idx_app_users_igreja_nome` e
`idx_user_roles_igreja_user`. Essa observacao nao foi revalidada nesta missao
e nao prova o estado atual de DEV. A atestacao v1 valida somente envelopes que
continuam bloqueados; ela nao comprova conclusao e nao pode ser reinterpretada
como `environment_attestation_complete=true`. Os artefatos historicos v1 e v2
permanecem byte-identicos e fora do escopo.

O pacote candidato `migration-epoch v3` esta congelado como
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
A matriz nova passou `87/87`, a focal estavel passou `138/138`, e o verificador
terminou fail-closed com exit `8` e
`RESULT=BLOCKED_MIGRATION_EPOCH_V3:PENDING_SEPARATE_EVIDENCE`. O estado e
`RECOMMENDATION_ONLY_NOT_APPROVED`; isso comprova somente o desenho offline e
nao autoriza evidencia viva, cutover, migration ou runtime.

No batch offline depois integrado pela PR #351, a correcao de precedencia classifica `TimeoutError` e
`socket.timeout` como `DEADLINE_EXCEEDED` antes de `OSError` generico em cada
fronteira de rede. O batch integrado tem runner SHA-256
`2e2208bfbca1214c0cec024c58716eeac7c05789c33ce36d812c0265c3810809`, teste
SHA-256 `d7161cd7dd7c63935c07431193b0d916222e5341088edbdc6d4ef85ad3063689` e
`102/102` testes verdes. Nenhum probe vivo foi executado. Os hashes da PR #350
`0ac585b86dd1c96446622e9a46bccda8a1e43eb0bceb0dcc19226892cb88d191` e
`70334dfc33505ea0b5ddb85a6406672fe0d9154e105134da164c773978459489`
permanecem evidencia historica e nao sao substituidos.

O contrato D3 fail-closed integrado usa
`backend/app/agent/private_checkpoint.py`, SHA-256
`098d7186d59b2be9c231e3ca41e328b69901d4bc3e3f9b09651b902c07768f33`,
`backend/app/agent/context.py`, SHA-256
`b8d9ccea0041a81021cb2b4cf8edcbd8af0457ebf4401b021bd974edd29eea7d`, e
`backend/tests/test_agent_private_checkpoint_contract.py`, SHA-256
`2f91523e6a5daacd7c3ac08b933c7d9f857c3eec2a72b9f962c09c98d39f3c8b`.
A selecao `tests/test_agent*.py` terminou em `292 passed, 7 skipped`, com duas
advertencias preexistentes. A classificacao e `CONTRATO OFFLINE INTEGRADO E INATIVO`: nao
ha saver, migration ou wiring, e o LangGraph continua stateless.

A PR #351 foi integrada no merge
`bc97dd4e6f2fc9024e85afe8d611708699c8983a`. Os `7/7` checks pos-merge
concluiram com `SUCCESS`. A Vercel registrou o deployment automatico do frontend
Production `6187006353`, status `17583083885`, com `SUCCESS`. Essa metadata prova
somente o frontend e nao prova backend, banco ou runtime. A preparacao D3 de
estado efemero desta branch permanece candidata offline, sem saver, migration
ou retomada, e nao integra a evidencia pos-merge da PR #351.

A PR #352, HEAD `c5b2b4c775592641b308de6b2ac3cd069f34dcb3`, integrou essa
preparacao no merge `6c807717010a41edf3bfd3d1b2405c2f3527a696`, cuja arvore e
identica a do HEAD da PR. Os `7/7` workflows pos-merge concluiram com
`SUCCESS`: Backend Tests `33428905043`, Canonical Schema Derivation
`33428905057`, E2E Critical `33428905042`, Environment Attestation PG17
`33428905234`, Frontend CI `33428905212`, RLS Integration `33428905114` e
Tooling Static Checks `33428905041`. A Vercel registrou o deployment automatico
do frontend Production `6187746800`, status `17584957483`, com `SUCCESS`, em
`2026-08-31T19:09:09Z`. Essa metadata prova somente o frontend e nao prova
saude funcional, backend, banco, saver, migration, memoria ativa, deploy do
backend, flag ou runtime. O estado permanece `PREPARACAO D3 INTEGRADA E
INATIVA`.

Sobre esse merge, o commit tecnico local
`14b3d7ba15e88032cd53714008d36badd4578e80` introduziu o contrato puro
`AgentTurnIdentity` e `AgentEffectIntent`. Na branch local, o commit
`f82f76927ba8a6a265478ad7f21eae07b0d6504c` adiciona somente o adapter
confiavel de entrada, protegido por
`agent_trusted_inbound_identity_enabled=false` por padrao. O `Message.id` da
entrada persistida agora chega em `IngestionOutcome` nos caminhos novo e
duplicado. Antes de sessao, reserva, lease, runtime ou qualquer outro I/O, o
worker constroi a identidade com igreja, conversa, mensagem e ID Evolution
persistidos. Antes da primeira consulta, o runtime rederiva a identidade com
quatro entradas confiaveis e separadas: `igreja_id`, `conversation_id`, o UUID
inbound persistido de `Message.id` e o `provider_message_id` exato. Ele exige
igualdade integral dos quatro vinculos com a identidade construida pelo worker;
qualquer divergencia aborta.
`claim_id` permanece requisito separado de recuperacao, nunca entra no
`turn_id`; o caminho legacy e preservado somente com a flag desligada. O estado
do grafo continua recusando aliases de autoridade e nao recebe essa identidade.

O mesmo lote incorpora em
`7d1ed00d0add18162a89f3a9c39da6039e74017c` o contrato puro e inativo
`turn_execution`, originalmente revisado em
`576de558983622146a91417c65a85a2a321f585b`. Ele define plano canonico,
ordem versionada de efeitos, escopo opaco por tenant e conversa, recibos
estruturais, maquina pura da futura outbox de resposta e chave atual `v2`.
Nada disso persiste plano ou recibo, autentica uma store, serializa turnos,
garante FIFO ou cria atomicidade entre commit de dominio e outbox. `ACCEPTED`
significa somente aceite do transporte; `AMBIGUOUS` e terminal. Evidencia
legacy `v1` ou `v0` nao e derivada nem autenticada pelo contrato.

Os pins atuais sao `backend/app/agent/turn_identity.py`, SHA-256
`5be323d7fafa4a51d5c954749c8d2d5991e33313e269ee0a3b63bdfc9fb3923d`;
`backend/tests/test_agent_turn_identity.py`, SHA-256
`4072b76688552b6f870e89876426d3c608b34a362ec895315d733691dff101c5`;
`backend/app/agent/turn_execution.py`, SHA-256
`72a53515a835bac528280223e22f76a33f8606b5ce979dae11773d10ea6a1b2b`; e
`backend/tests/test_agent_turn_execution.py`, SHA-256
`7e22814f1715b7bdfc7f83431bf4e15cdf6d8f7d13d0d8d3afaa6811e95e0b2d`.
O wiring passou em `245/245` e em `401 passed, 7 skipped` na selecao
`tests/test_agent*.py`; o contrato de execucao passou em `86/86`, na revisao
independente `190/190` e em `462 passed, 7 skipped` na mesma selecao. As duas
revisoes terminaram `GO`, sem P0, P1 ou P2. A evidencia e local e pre-PR.

Na mesma branch, o commit tecnico local
`abafdffdc8252fa6dff7c9d1975cb6c241141971` adiciona o adaptador puro e
replay-only `turn_plan_adapter`. Ele projeta a saida fechada do grafo em um
plano deterministico, mas nao oferece status `EXECUTABLE`, callback injetavel
ou consumer de runtime. Plano armazenado ausente ou qualquer receipt terminal
ausente produz `FIRST_EXECUTION_UNSUPPORTED` e bloqueia a primeira execucao.
Somente um plano armazenado estruturalmente exato e vinculado ao digest, junto
de um receipt terminal valido para cada efeito, retorna `REPLAY_TERMINAL`; esse
resultado nao concede execucao, persistencia, transporte, retry ou mutacao de
dominio. `tool_calls` permanecem bloqueados. A oferta do relatorio e aceita
somente quando finita, nao negativa e exata em centavos, sendo vinculada como
inteiro `oferta_centavos`.

Os novos pins sao `backend/app/agent/turn_plan_adapter.py`, SHA-256
`c81dafec100734ee9a219d8c99a636636b6317b94c93c87cb89ba0f9af581002`;
`backend/tests/test_agent_turn_plan_adapter.py`, SHA-256
`328f3a2870fab8ea38f1901a02e640bec2f5bc9457c3d5261f350a45ef560d5e`.
A revisao integrada passou em `291/291`; a selecao `tests/test_agent*.py`
terminou em `625 passed, 7 skipped`. A revisao concluiu `GO`, com P0, P1 e P2
iguais a zero. Essa evidencia e local e pre-PR.

O lote ampliado permanece exclusivamente offline. O wiring de identidade
continua inativo porque a flag fica desligada por padrao e nenhuma ativacao
ocorreu. `turn_execution` e `turn_plan_adapter` nao possuem consumer de runtime
e executam zero I/O. Nao existem saver, checkpoint duravel, migration, plano ou
receipt persistido, FIFO, bloqueio serial real, atomicidade entre efeitos,
retomada, primeira execucao ou memoria ativa. Estado: `LOTE D3 OFFLINE
AMPLIADO LOCALMENTE / REPLAY-ONLY / FLAG DEFAULT FALSE / CANDIDATO NAO
INTEGRADO NO MAIN / RUNTIME NAO ATIVADO`.

O commit tecnico local `4988de11566f8f0675256b9958ca242e5a009fa3`
integra ao lote o snapshot agregado `cell-report/v2`. Ele preserva apenas os
totais de presentes, visitantes e decisoes; `presencas`, `visitantes` e
`records` individuais precisam permanecer arrays vazios, portanto o snapshot
nao inventa pessoas nem transforma totais em fatos individuais. Os pins sao
`backend/app/domain/cell_report_snapshot.py`, SHA-256
`19adb057c9f002776e3ad99d87de636de4975f5cf602a8fb06d2d8401a7d2aaa`, e
`backend/tests/test_cell_report_snapshot.py`, SHA-256
`08464997fa55cb9319d095f672fe0d78693280104d8b4247390e3e75d80ad7f9`.

O commit tecnico local `452aa6ff591b80dcbd3da90f1e5c18367cffd72b`
integra o workflow puro de coleta, revisao e confirmacao do relatorio. A
confirmacao literal apenas correlaciona a revisao corrente; o workflow nao
autentica o ator, nao concede autoridade e nao executa efeito. O estado
`COMMITTED` projeta uma comprovacao externa futura, sem gravar ou enviar nada.
Os pins sao `backend/app/domain/cell_report_workflow.py`, SHA-256
`87ec5691774eab1b2711fea0f07f9f311ddacf7f321fe36646730742b02569b5`, e
`backend/tests/test_cell_report_workflow.py`, SHA-256
`a5a542f6b0192964a0bdd238b8306a1b8ca162be4ec6e2f824773020300508c6`.

O hardening posterior foi composto pelos commits
`f40d39efeb847b84b30e495ba78f6d218437e8ad`,
`a84bb7d5f00bae6bb472d02c4a33d14442a294a2`,
`ef4aa00797e11bbbaa0189faa2c299bf9ace8a5b`,
`9ea14000065117bda4aa8e7627e78c07dd5d1b2a` e
`45323a64b17cd9f1fa4d4a86f3a32d769f525660`, sem reescrever os freezes
anteriores. Os pins finais sao adaptador SHA-256
`2d2adde74dd2bea21aa7a1a3a0e3551ebc62ab269885531162ffc0681e3c7629`,
teste do adaptador SHA-256
`380bf43ea70020ad30134ac56b1ff42823c3219c1950ee3c46c508acdd3290b8`,
snapshot SHA-256
`95a9c4f5ea68b3027b42416d858c5cfc3eed858198bf38f8bab638c1b293a53f`,
teste do snapshot SHA-256
`21c9799aed4d79003c5b3d3018fa5c6c61ff11c6452409056309e5b74d3b76ee`,
workflow SHA-256
`3213bcc9949661bd3db56717492babfc7b9a9c0d79c20b8da9ddc039ab1b129d`
e teste do workflow SHA-256
`7887a930b8d2fbf7f508acae0d6b256927ab52534a726b2a54fec7224c897dd6`.

O hardening de paridade local centraliza `MAX_REPORT_COUNT=1_000_000` e o
limite E2 de oferta em `R$ 999.999,99`; builder e revalidacao do snapshot
persistido usam os mesmos limites. O writer humano agora recusa `NaN`,
infinito, booleano, string, `-0.0` e mais de duas casas decimais. Isso ainda e
constante compartilhada mais validacao humana endurecida, nao um servico de
aplicacao compartilhado. Os pins adicionais sao
`backend/app/domain/cell_report_limits.py`, SHA-256
`cb0acd562ebd4e91f2f3170d59ff67cea3ac45f9b4a73f370b1c78522b330412`, e
`backend/tests/test_cell_report_limits.py`, SHA-256
`7f11003b18b0159815f54306002e87624045282d775de08d1ba47da1b6822e86`;
`backend/app/routers/cell_meetings.py`, SHA-256
`e72c1e8366a45ab487b38e1d04b110583b4825645daadaccf1957a04b913ddf5`; e
`backend/tests/test_cell_lider.py`, SHA-256
`07ffabd0260b573bad0fbd8ba572064d0acaaa3b361524dea06a35d8ac781b4d`.

Na revisão integrada final do HEAD
45323a64b17cd9f1fa4d4a86f3a32d769f525660, passaram 512 passed, 5 warnings;
633 passed, 7 skipped, 2 warnings; 398 passed, 18 warnings; e 34 passed
documentais. Links locais 89/89, matriz de pins e gates 13/13, py_compile,
secret scan e git diff --check ficaram verdes. O parecer foi GO, com P0, P1 e
P2 iguais a zero. A evidência é exclusivamente local e pré-PR; não prova
runtime, DEV, PROD, banco, deploy ou efeito vivo.

Ainda nao existe bridge ou wiring entre `turn_plan_adapter`, workflow e
snapshot. `REPLAY_TERMINAL` nao prova relatorio persistido: o plano atual de
`report_capture` contem somente intake, auditorias e resposta, sem efeito de
gravacao do relatorio. Um adapter futuro, em codigo confiavel, devera derivar o
escopo vinculado ao tenant, mapear centavos e string sob o mesmo limite de
produto E2 do painel e marcar `COMMITTED` somente depois de um commit externo
atomico comprovado.

As duas fatias permanecem restritas ao lote local. Nenhum runtime ou worker foi
acionado; nao houve acesso a banco, migration, rede, persistencia, mensagem ou
qualquer efeito vivo. Estado: `FUNDACAO OFFLINE DO RELATORIO DE CELULA
AMPLIADA LOCALMENTE / SNAPSHOT V2 AGREGADO / WORKFLOW PURO / CANDIDATO NAO
INTEGRADO NO MAIN / EFEITOS VIVOS BLOQUEADOS`.

O gate historico `REVIEW_AND_CI_OFFLINE_AGENT_FOUNDATION_BATCH_PR` foi consumido
pelo push, abertura, CI e Preview da PR #351. Ele nao autorizou o merge
posterior, permanece somente como evidencia historica e nao e um segundo gate
corrente.

O gate historico `REVIEW_AND_CI_D3_EPHEMERAL_EFFECT_STATE_PR` foi consumido
pelo push, abertura, CI e Preview da PR #352. O merge e o deployment automatico
do frontend Production foram autorizados separadamente; esse gate nao os
autorizou. Apos o consumo, ele permanece somente como evidencia historica e
nao e um segundo gate corrente.

O gate anterior `REVIEW_AND_CI_D3_TURN_IDENTITY_OFFLINE_PR` foi substituido
localmente, sem consumo, pelo lote combinado. Nao houve push, PR, CI ou Preview
sob esse gate, portanto ele nao e evidencia historica de uma acao externa.

O gate anterior
`REVIEW_AND_CI_D3_TURN_EXECUTION_AND_TRUSTED_INBOUND_WIRING_OFFLINE_PR` foi
substituido localmente, sem consumo, pelo lote ampliado replay-only. Nao houve
push, PR, CI ou Preview sob esse gate, portanto ele nao e evidencia historica
de uma acao externa.

O gate anterior `REVIEW_AND_CI_D3_TURN_FOUNDATION_REPLAY_ONLY_OFFLINE_PR` foi
substituido localmente, sem consumo, pela fundacao offline do relatorio de
celula. Nao houve push, PR, CI ou Preview sob esse gate, portanto ele nao e
evidencia historica de uma acao externa.

A fatia offline posterior foi congelada no commit tecnico original
`c24b910bcd4bf4015eda14847e9695497b5b8ef6` e consolidada, sem alteracao da
arvore tecnica, no HEAD local
`bcabbae0cf96a9b6e2cd47e8ff041b5aeaffbc84`, sobre a reconciliacao
documental `e0cb280`. Ela acrescenta o envelope fechado
`cell-report-pending-proposal/v1` e o servico
`cell_report_application`. A proposta usa `relatorio_snapshot` apenas
enquanto o relatorio esta pendente, com bindings opacos de tenant, reuniao,
conversa e ator, expiracao maxima de 24 horas, no maximo 32 operacoes
estruturais e digest do estado-base. O JSONB nao guarda UUIDs brutos, mas os
hashes nao sao autenticadores e o conteudo privado nao pode ser logado.

O servico exige transacao tenant-scoped ja ativa e pertencente ao caller,
adquire locks em ordem canonica e revalida conversa oficial sem handoff,
reuniao passada e nao cancelada; novas propostas e materializacoes exigem
relatorio pendente, enquanto replay final exato e permitido para enviado;
celula, lider e Pessoa ativos, opt-out,
`sem_interesse`, exatamente um `AppUser` utilizavel e ao menos um papel
ministerial. Proposta e confirmacao exigem `AgentTurnIdentity` e
`AgentEffectIntent` com payload exato. A confirmacao literal corrente troca o
envelope por `cell-report/v2`, atualiza `celula_reuniao` e faz somente
`flush`. O caller continua responsavel por commit ou rollback.

O hardening final persiste o `submission_effect_id` original e o
`submission_payload_digest` separado. A dupla nao prova proveniencia,
autorizacao, primeira execucao nem unicidade global, e o historico limitado da
proposta nao substitui plano, receipt duravel autenticado ou outbox. Os limites
compartilhados fixam `MAX_CELL_REPORT_OBSERVATIONS_LENGTH=2_000` caracteres e
`MAX_CELL_REPORT_OBSERVATIONS_BYTES=8_000` bytes UTF-8. Fetch de rows, fetch
de scalars e `flush` sanitizam `SQLAlchemyError` sem encadear a excecao
privada.

Nao existe caller no grafo, worker, webhook, router humano ou
`turn_plan_adapter`; a primeira execucao do agente e `tool_calls` continuam
bloqueados. O router humano ainda nao compartilha o servico nem o lock. Papel,
lideranca e opt-out nao substituem o consentimento `tarefas_operacionais`: a
fonte juridica e do controlador segue nao aprovada, o ledger D2B2a permanece
sem caller e sem aplicacao, e esta fatia nao le nem grava consentimento. Nao
houve migration, banco compartilhado, DEV, PROD, rede, mensagem ou efeito vivo.

Pins integrais do HEAD: `backend/app/domain/cell_report_limits.py`
`8c7a81ee9a8f0a14125c5918aba6f149582e6392d129c9b37744ac3a1d12bf42`;
`backend/app/domain/cell_report_pending_proposal.py`
`53769d79835803dc8c294928047d2d8766de491e17aecc9d57edb239f06c4056`;
`backend/app/domain/cell_report_snapshot.py`
`24e93a2b6e8cbe92a849ba3ccc081ff6fbd092a347a605494464fddc6aa3bc51`;
`backend/app/domain/cell_report_workflow.py`
`da16186dc28f18261967e10800c5f300dae2b11552ed6dff389cbe9d7a3bf877`;
`backend/app/routers/cell_meetings.py`
`59de2e7b9d12a4c9d36e16edf28c8a74ea590244b778dae8da44ac8f47f49067`;
`backend/app/services/cell_report_application.py`
`7dc9d0d9cc7bf09c3d8963e956bd60500038004c5e8d882c7d37dd30c3a3389b`;
`backend/tests/test_cell_health_service.py`
`19fbe602a4943fa76a3583e1e9e61a3e7979169caba5de15e157072262c8be69`;
`backend/tests/test_cell_lider.py`
`a0265297ec29895399bf4ea0bfac37f554ec935ae5fd6e157c4f348bd69cc6a5`;
`backend/tests/test_cell_report_application.py`
`30139bffee6be9c00f7068255c6150ee8507506a14ccb9649bebadbf39dc136e`;
`backend/tests/test_cell_report_limits.py`
`c1d4c2b89e3863e10fed7a3e84eb27b2cece6447c8a63e05237d24fff26196aa`;
`backend/tests/test_cell_report_pending_proposal.py`
`299b23c0795d9a1e70ac0e6ed46b4124c64a94e567f2e8a6d03732fde6165a3c`;
`backend/tests/test_cell_report_snapshot.py`
`7cbd65505095c7821bbb8328da9b6d22760fce0544ab80861ca765c82bbd87fb`;
`backend/tests/test_cell_report_workflow.py`
`704f036d1fd5632c7c33dd5c446e80e6f303fa712adacee892dde822b83f53a9`;
e `backend/tests/test_reports.py`
`fb511601265dfa374a7d9fbec35f913a7e4bdbde615ce82c1c7996e2d51177d2`.

A focal passou em `292 passed`; `tests/test_agent*.py` terminou em
`633 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`730 passed, 18 skipped, 35 warnings`. A suite ampla do backend, com
`migration_history` e Redis fora da selecao, chegou a
`4601 passed, 325 skipped, 499 deselected, 66 warnings`, sem classificacao
verde por uma assercao documental do pin anterior e duas falhas baseline de
modo group-writable `0664` no checkout `/tmp`. Apos esta reconciliacao, a
matriz documental passou em `34 passed`. A revisao independente repetiu
`729 passed` e `1363 passed, 25 skipped` e concluiu `GO`, com P0,
P1 e P2 iguais a zero. A evidencia e local e pre-PR.

Estado: `FRONTEIRA TRANSACIONAL OFFLINE DO RELATORIO AMPLIADA LOCALMENTE /
PROPOSTA PENDENTE FECHADA / FLUSH SEM COMMIT / CANDIDATO NAO INTEGRADO NO MAIN
/ RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior `REVIEW_AND_CI_D3_CELL_REPORT_OFFLINE_FOUNDATION_PR` foi
substituido localmente, sem consumo, pela fatia offline do servico de aplicacao
do relatorio. Nao houve push, PR, CI ou Preview sob esse gate, portanto ele nao
e evidencia historica de uma acao externa.

A composicao transacional posterior esta no HEAD local
`dac3a14cdd2bf857f84609518dd96050e203b4b3`. A reserva V2 foi criada no
commit tecnico original `4d08e783c2de1bb20dfeb29ffb8ee6a43c7a444f` e
integrada como `d6ee2323d658a91bb92724aaa13adea7222538b4`; a UoW veio de
`58b77a84e38ba7be4d3968d32834ef1b415b3a89` e foi integrada como
`17305af54e52aea74948e275ad68fae50427ae67`; os locks dos writers vieram
de `83b4810008f37250b9a9d00f9c9a83f04a3d0399` e foram integrados como
`b6a763cbcab41a78815a7777f2c9b682a6af1ddb`. O commit
`dac3a14cdd2bf857f84609518dd96050e203b4b3` reconciliou nos testes o
`expected_replayed` explicito. A revisao tecnica consolidada posterior
concluiu `GO`; a evidencia exata esta registrada abaixo.

A reserva `AgentOutboundReplyReservationV2` e um contrato puro derivado
somente de `AgentTurnIdentity`, antes de payload ou plano. Ela fixa o slot
`OUTBOUND_REPLY` ordinal zero e produz a mesma chave de compatibilidade V2 do
efeito posterior, sem usar `claim_id`. O valor nao reserva linha, nao prova
outbox, autenticacao, idempotencia global, aceite do provedor ou envio.
Compatibilidade V1/V0 continua somente como drain: a UoW pode vincular a chave
exata observada numa linha legacy ja bloqueada, sem deriva-la nem promove-la.

Os seis writers humanos `edit_meeting`, `set_real_attendance`,
`register_visitor`, `add_record`, `save_report` e `submit_report`
passam pela mesma boundary sanitizada e serializam a reuniao, a celula e o
acesso do lider com locks tenant-bound. Um envelope pendente reconhecido pode
ser invalidado por takeover humano explicito; snapshot pendente desconhecido
falha fechado. O reconhecedor puro do snapshot humano legacy exige shape
completo, metadados coerentes e UUIDs canonicos nao nulos. Assim, um submit
humano concorrente vira `REPORT_CONFLICT` para o agente, enquanto shape
malformado continua `DATA_INTEGRITY`. Os writers web continuam separados do
servico de aplicacao do agente; compartilhar locks nao equivale a compartilhar
servico.

A `cell_report_turn_uow` exige uma transacao tenant-scoped externa, um plano
fechado com `TOOL_CALL`, `AUDIT_EVENT` e `OUTBOUND_REPLY`, e uma
`Message` de reply pre-reservada. Ela bloqueia a mensagem, valida a chave V2
antes do banco ou, para V1/V0, a evidencia exata depois do lock; exige
`expected_replayed` booleano no servico de confirmacao; e requer concordancia
entre relatorio, audit sem conteudo e reply em replay. No caminho novo, agrupa o
snapshot, um `AgentConversationLog` sem texto pastoral e a `Message` com
estado `ia_pendente` na transacao do caller. Todo sucesso da UoW retorna
`requires_caller_commit=true`, inclusive replay observado na transacao atual.
A boundary faz somente `flush`: nao inicia, confirma ou reverte transacao, nao
envia mensagem e nao chama runtime, worker, grafo ou rede.

Esta fatia especifica fecha parte do staging atomico, mas nao cria outbox
generica, receipt global autenticado ou comprovante pos-commit. Nao existe
caller; consentimento `tarefas_operacionais`, `AgentConfig`, proveniencia
operacional, commit, send, primeira execucao generica pelo
`turn_plan_adapter`, migration, drain V1/V0 e efeitos vivos continuam
bloqueados. Nao houve banco compartilhado, DEV, PROD, rede, mensagem ou
deployment.

Pins SHA-256 integrais do HEAD:
`backend/app/agent/turn_execution.py`
`b729c3b25024cff41aa42b39aecd9d30712bf229c8f635c40fbd306cf52ac351`;
`backend/app/agent/turn_identity.py`
`59848ebee37c9be0c9488420c4634e1b323f611c22627328c8c4dd73d5e69998`;
`backend/app/domain/cell_report_legacy_snapshot.py`
`22dc8e5992f5661a5c110d6a4cc1ebedf7babfabfd45a56490b484de4695f869`;
`backend/app/routers/cell_meetings.py`
`9a04c1589f64179e7b60a8b18755a40ee21035a8e955f8ff5238c4c5eba3a18e`;
`backend/app/services/cell_report_application.py`
`0c8ddd4040b83e09fd496eeea3594c68309f0446b97b2466d5f32204babcc347`;
`backend/app/services/cell_report_turn_uow.py`
`1bdebab8fb70b081781fa0ace6152b1d83cdeb9161a125172b16ca5929795399`;
`backend/tests/test_agent_turn_execution.py`
`911cc7743b073c78b6d5eaffc29eee1171bdf25d1526bd94a32542302c92420e`;
`backend/tests/test_agent_turn_identity.py`
`6d60a2668810bf8c62e23658d95c54b886079e4e7ecf120f349e989de710e1cf`;
`backend/tests/test_cell_lider.py`
`0732667504127fb4bcdc163187b9b137e77f645e81a743413d8a7c4332f1ee0e`;
`backend/tests/test_cell_report_application.py`
`278e3d506ca5c0853b957529013991bb676320381727f33183afcadc7768f430`;
`backend/tests/test_cell_report_legacy_snapshot.py`
`57586f81accd27145d5877ce91fa9d98f82f29b1ee4f73828768cfe93134c354`;
e `backend/tests/test_cell_report_turn_uow.py`
`5ce3d8b37f672adfeaf04839183d43f7f67b51f5cf6d81b37b663bf9c2128db9`.

A revisao tecnica integrada no HEAD
`dac3a14cdd2bf857f84609518dd96050e203b4b3` concluiu `GO`, com P0, P1 e
P2 iguais a zero. A focal integrada terminou em `682 passed, 5 warnings`;
`tests/test_agent*.py` terminou em `649 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`960 passed, 18 skipped, 35 warnings`. Tambem passaram 200 vetores da reserva
V2 e 8 casos de corrupcao legacy. As validacoes de AST e `git diff --check`
para `d37d528..dac3a14` ficaram verdes. A evidencia e local e pre-PR. Ela
confirma ainda a ausencia de caller em runtime, worker ou webhook, de migration,
rede ou send e de `begin`, `commit` ou `rollback` na UoW.

Estado: `STAGING TRANSACIONAL OFFLINE COMPOSTO E REVISADO LOCALMENTE / RESERVA
V2 CLAIM-INDEPENDENT / WRITERS SERIALIZADOS / FLUSH SEM COMMIT / GO TECNICO
P0=P1=P2=0 / SEM CALLER / RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior
`REVIEW_AND_CI_CELL_REPORT_APPLICATION_SERVICE_OFFLINE_PR` foi substituido
localmente, sem consumo, pelo lote de staging transacional. Nao houve push, PR,
CI ou Preview sob esse gate, portanto ele nao e evidencia historica de uma acao
externa.

**Gate anterior consumido:**
O gate `REVIEW_AND_CI_CELL_REPORT_TRANSACTIONAL_STAGING_OFFLINE_PR` exigia
autorizacao humana posterior e separada que nomeie push, abertura da PR e
GitHub CI e aceite o Vercel Preview automatico. O gate cobre somente revisao e
CI do lote offline de staging transacional; nao autoriza merge, Vercel
Production, flag-on, caller, `AgentConfig`, primeira execucao do agente,
runtime, worker. Ele foi consumido pela autorizacao humana nominal da rodada
de PR. Na PR #354, o head
tecnico `69f9eecdfb95691b4633a42ef597452f63e82e48` contra `main`
`6c807717010a41edf3bfd3d1b2405c2f3527a696` permaneceu aberto,
`MERGEABLE/CLEAN`. Os sete workflows GitHub concluiram com `SUCCESS`: Backend
Tests `33456753518`, Canonical Schema Derivation `33456753672`, E2E Critical
`33456753444`, Environment Attestation PG17 `33456753406`, Frontend CI
`33456753394`, RLS Integration `33456753452` e Tooling Static Checks
`33456753430`. O Vercel Preview automatico do frontend, deployment
`6192384421`, status `17596918017`, tambem concluiu com `success`. Preview nao
e Vercel Production e esta evidencia nao prova runtime, banco ou efeito vivo.

**Próximo gate único daquele recorte histórico (consumido no merge da PR #354):**
O nome não constitui autorização já concedida. Naquele recorte histórico,
`REVIEW_AND_MERGE_CELL_REPORT_TRANSACTIONAL_STAGING_PR` era o sucessor fechado.
Posteriormente, ele foi consumido por autorização humana nominal exclusivamente
para o merge da PR #354, que ocorreu via squash no commit
`c24ea748ab5e484958590af481f08f1c2b185597` (`mergedAt=2026-09-01T02:27:21Z`), e
o deployment Vercel Production automático decorrente (`6193336784`). O deployment
Vercel Production automático decorrente prova somente o frontend. Seus limites
operacionais continuaram fechados: não autorizou caller, runtime, worker,
consentimento, banco, migration, commit, send, drain V1/V0,
receipt global, saver, probe vivo, DEV, PROD, logs, SQL, DML, outra rede,
deploy adicional, mensagem, tool call, flag ou qualquer efeito vivo, e o merge da
PR #354 não autorizou, alterou ou comprovou o estado vivo de `AgentConfig.ativo`.

---

## Sprint 001 - Fundacao de Database (Schema, RLS, Triggers, Seed) [CONCLUIDA]
- Schema completo de tabelas: Criar migrations com todas as tabelas da secao 2.1: igrejas, pessoas, app_users, user_roles, role_permissions, celulas, cell_alerts, conversations, messages, work_queue_items, reports, broadcasts, events, whatsapp_connections, agent_configs, llm_credentials, crons, subscriptions, system_managers, consolidacoes, consolidacao_etapas, decisions, multiplicacoes, consent_records, ai_usage_logs, agent_conversation_logs.
- RLS por tenant e current_igreja_id(): Habilitar RLS em todas as tabelas com igreja_id e criar a funcao current_igreja_id() que deriva o tenant de app_users a partir do clerk_user_id do JWT. Policies padrao USING/WITH CHECK por igreja_id; igrejas restrita ao proprio registro.
- Triggers de state machine e automacoes: Implementar os triggers da secao 2.3: trg_promote_pipeline, trg_link_cell_promote, trg_report_received_clears_queue, trg_decision_opens_consolidation, trg_consent_on_inbound, trg_subscription_autoupgrade, trg_set_updated_at.
- Seed da igreja piloto: Inserir os dados de seed da secao 2.4: igreja piloto, app_user admin (Clerk do pastor) com user_roles {admin,pastor}, role_permissions default, agent_configs default, whatsapp_connections offline, subscriptions piloto e amostras de dominio.

## Sprint 002 - Backend Core (FastAPI, Clerk Auth, Tenant Resolver, RBAC) [CONCLUIDA]
- App FastAPI e modelos: Criar app/main.py com CORS e mount de routers, app/config.py (settings/env conforme .env.example), app/db/session.py (client Supabase/Postgres) e app/db/models.py com os modelos das tabelas da secao 2.1.
- Auth Clerk + Tenant resolver: app/deps.py com validacao do JWT/sessao Clerk, populando current_user e clerk_user_id, e resolucao de current_igreja_id a partir de app_users injetando no contexto RLS do Postgres.
- RBAC require_role e api-login: Dependency require_role que revalida papeis acumulados (user_roles) por endpoint, e endpoint POST /auth/login retornando {token, churchId}. Config exige admin; login com credencial invalida nao revela existencia de e-mail.

## Sprint 003 - Frontend Foundation + Login + Layout/Sidebar [CONCLUIDA]
- Setup Next.js + tokens visuais: Configurar projeto Next.js (PWA), aplicar tokens de cores oklch, tipografia, espacamento e radii da secao 4.4 como sistema de design global, fiel ao artifact HTML travado.
- Sidebar-nav e roteamento por hash: Implementar sidebar-nav com grupos Gestao, Visao G12 e Configuracao (adminOnly), roteamento por hash (#rota) e montagem do menu pela uniao dos papeis acumulados, usando role_permissions como fonte de verdade.
- Tela de login (Clerk): Tela #login integrada ao Clerk SDK com estados idle/loading/error/success, consumindo api-login, redirecionando para #dashboard em sucesso.

## Sprint 004 - Backend Dominio Pastoral (Pessoas, Celulas, Pipeline, Fila de Trabalho) [CONCLUIDA]
- Contatos e vinculo de celula: Endpoints api-contacts (GET /contacts), api-create-contact (POST /contacts) e api-link-cell (POST /contacts/{id}/cell) sobre pessoas, com dedupe por telefone+igreja e paginacao.
- Celulas, alertas e descendencias: Endpoints api-cells (GET/POST /cells) e api-descendencias (GET /descendencias) usando celulas, cell_alerts e a hierarquia lider_id, com cobertura_espiritual obrigatoria.
- Pipeline (etapa/subetapa): Endpoint api-pipeline (GET/PUT /pipeline) para promover/avancar pessoas conforme state machine, respeitando criterios de promocao.
- Fila de trabalho e mensagem interna: Endpoints api-queue-action (POST /work-queue/{itemId}/action) e api-send-internal-message (POST /work-queue/{itemId}/message), com filtro por papel e tratamento de concorrencia (item ja resolvido).

## Sprint 005 - Backend Consolidacao, Decisoes e Multiplicacoes [CONCLUIDA]
- Lancar decisao e abrir consolidacao: Endpoint api-launch-decision (POST /consolidacao/decisao) que registra decisao e abre consolidacao; fluxo visitante define prazo de conexao de 24h.
- Avanco da trilha com gate por consolidador: Endpoints sobre consolidacoes/consolidacao_etapas (via api-pipeline: assign-consolidador, advance-stage) com confirmacao de etapa apenas pelo responsavel_id.
- Multiplicacoes: Endpoint api-multiplicacoes (GET/POST /multiplicacoes) para agendar e aprovar multiplicacoes, com aprovacao desabilitada quando supervisao_ok=false.

## Sprint 006 - Backend WhatsApp, Conversas, Handoff e Worker [CONCLUIDA]
- Conexao WhatsApp (Evolution API): Endpoint api-whatsapp-connection (GET/POST /whatsapp/connection) e service evolution.py para connect/reconnect retornando QR e status, mantendo 1 numero por igreja.
- Conversas e handoff: Endpoints api-conversations (GET /conversations) e api-conversation-handoff (POST /conversations/{id}/handoff) com estados ia/humano/aguardando e restricao de acesso a privilegiados.
- Webhook de mensagens e worker: Webhook Evolution com validacao de assinatura, dedupe por telefone+igreja, worker de filas (queue_worker) com reprocesso e registro de messages somente do numero oficial.

## Sprint 007 - Agente Orquestrador (LangGraph), LLM BYO e Tools [CONCLUIDA]
- Orquestrador e sub-agentes: Grafo LangGraph (app/agent/graph.py, nodes.py) com Orquestrador supervisor como unico ponto de entrada/saida no WhatsApp oficial (delta-034). Sub-agentes intake/onboarding/report_capture/handoff/consent retornam resultado ao supervisor, que emite resposta unica. Roteamento por intencao/estado (route_intent) com prioridade handoff > optout > consent > report > onboarding. Fallback direto quando o grafo falha. **Correcao de estado atual:** nao existe checkpoint duravel implementado; `AGENT_GRAPH_CHECKPOINT_URL` somente aciona um warning e o grafo permanece stateless.
- intake/onboarding/report/consent/optout: o registro historico da sprint previa que `report_capture` emitisse `registrar_decisao`. **Correcao de estado atual:** a implementacao vigente extrai o resumo agregado e registra somente `report_captured`; nao grava o relatorio canonico nem atribui decisoes agregadas ao remetente. Intake, consentimento e opt-out permanecem nas rotas atuais.
- Credencial LLM BYO por tenant: endpoints GET /agent/models, GET/POST /agent/credential e PUT /agent/model; chave e acesso ao modelo sao validados no provedor, a chave e cifrada (Fernet) e nunca exibida (RNF-03). Cada igreja seleciona um modelo da allowlist; o default economico e `gpt-5.6-luna`, e o fallback so desce Sol -> Terra -> Luna. Chave invalida nao ativa a credencial; runtime recusa operar sem credencial validada+ativa (US-27).
- Tools e logs de IA: app/agent/tools.py (registrar_decisao, marcar_presenca, vincular_celula, avancar_trilha) reaplicam as mesmas validacoes de um humano no escopo do tenant (F5). Cada interacao registra modelo/tokens/custo em ai_usage_logs e evento em agent_conversation_logs com payload mascarado (CPF/email/digitos longos) via app/agent/masking.py (RNF-24). Worker integra o orquestrador (run_agent_for_message) e envia a resposta unica pelo numero oficial.

## Sprint 007 - Agente Orquestrador (LangGraph), LLM BYO e Tools [CONCLUIDA]
- Orquestrador e sub-agentes: Grafo LangGraph com Orquestrador supervisor e sub-agentes intake, onboarding, report_capture, handoff e consent. Sub-agentes nunca falam direto no WhatsApp; resposta unica sai pelo Orquestrador.
- Credencial LLM BYO + tools + logs: Endpoint api-llm-credential (POST /agent/credential) com chave cifrada e validacao, tools do agente (registrar decisao, marcar presenca, vincular celula, avancar trilha) e logs em ai_usage_logs/agent_conversation_logs.

## Sprint 008 - Assistente do Painel e Motor de SLA/Cron [CONCLUIDA]
- Assistente do painel + SLA engine: Endpoint api-assistant (POST /assistant/message) ciente de papel/tenant, e SLA engine + cron_worker que detectam prazos (relatorio 2h, conexao 12h, fonovisita 24h) e disparam cobranca/escalonamento por WhatsApp.

## Sprint 009 - Backend Relatorios, Comunicados, Eventos e Equipe/Config [CONCLUIDA]
- Relatorios, comunicados e eventos: Endpoints api-reports (GET /reports), api-broadcasts (POST /broadcasts) respeitando opt-out, e api-events (GET/POST /events) com sync Google Calendar.
- Equipe, permissoes e gerentes: Endpoints api-team-invite (POST /team/invite; o provider vigente e Brevo, apesar da referencia historica a Resend), api-team-roles (PUT /team/{usuarioId}/roles), api-role-perms (GET/PUT /roles/permissions) e api-system-managers (GET/POST/DELETE /system-managers).
- Assinatura (Asaas) e config do agente: Endpoints api-subscription (GET/POST /subscription com webhook Asaas), api-agent-config (PUT /agent/config) e api-crons (POST /agent/crons).

## Sprint 010 - Frontend Dashboard / Fila de Trabalho Pastoral [CONCLUIDA]
- Fila de trabalho e acoes diretas: Renderizar work-queue-item por tipo (visitante/atendimento/relatorio/conectar_celula/fonovisita) com acoes assumir/atribuir e conectar a celula.
- Prazos e stat-cards: Exibir deadline-badge (dentro/alerta/atrasado) reordenando por prioridade e stat-cards de visao geral.

## Sprint 011 - Frontend Contatos & Visitantes (Ganhar) [CONCLUIDA]
- Ganhar (novos contatos e visitantes): Tela #ganhar com tabs novos-contatos/visitantes em data-table, status-pill e empty-state, consumindo api-contacts e api-pipeline.
- Contatos (lista e detalhe): Tela #contatos com lista e detalhe, criacao de contato (form-field/btn-primary) e vinculo de celula.

## Sprint 012 - Frontend Celulas, G12 e Enviar (Discipular/Enviar) [CONCLUIDA]
- Celulas (lista e detalhe): Tela #celulas com data-table, stat-card e tabs; criar/editar celula com cobertura_espiritual obrigatoria.
- G12 (organograma): Tela #g12 com organograma de descendencias consumindo api-descendencias.
- Enviar (multiplicacoes): Tela #enviar com tabs agendadas/sem-agendamento/aptos/historico, agendar e aprovar multiplicacao com gate de supervisao.

## Sprint 013 - Frontend Consolidacao (Consolidar / Individual) e Trilhas Bloqueadas [CONCLUIDA]
- Consolidar (dashboard restrito + decisao): Tela #consolidar com fila, estado 100-consolidadas e decision-modal (fluxo celula/visitante), restrita a lider_consol/admin/pastor.
- Consolidacao individual: Tela #consol-individual com fila e detalhe, avanco de etapas e conclusao com gate por consolidador.
- Trilhas bloqueadas (UV e Capacitacao): Placeholders #universidade-vida e #capacitacao no estado locked-em-breve, presentes no menu mas sem navegar para conteudo.

## Sprint 014 - Frontend Inbox & Conexao WhatsApp [CONCLUIDA]
- Inbox e handoff: Tela #inbox com conversation-list, conversation-thread (ia-active/human/waiting) e acoes assumir/devolver para IA, restrita a privilegiados.
- Conexao WhatsApp (QR): Tela #whatsapp com qr-connect e status-pill nos estados connected/disconnected/reconnecting, consumindo api-whatsapp-connection (admin only).

## Sprint 015 - Frontend Relatorios, Central-Celula, Comunicados e Calendario [CONCLUIDA]
- Relatorios e Central-Celula: Tela #relatorios (data-table, tabs, status-pill, estados received/pending) e #central-celula (lideres + relatorios + comunicar lideres) consumindo api-reports e api-broadcasts.
- Comunicados (segmentado): Tela #comunicados com passos compose/segment/review respeitando opt-out, toggle-switch e data-table de destinatarios.
- Calendario: Tela #calendario com calendar-month, criacao de evento (form-field/btn-primary) e sync Google Calendar.

## Sprint 016 - Frontend Equipe, Permissoes, Gerentes, Assinatura e Agente [CONCLUIDA]
- Equipe, Permissoes e Gerentes: Telas #equipe (list/invite/edit-roles), #permissoes (matrix/saved) e #gerentes (list/invite) consumindo api-team-*, api-role-perms e api-system-managers.
- Assinatura: Tela #assinatura com stat-card, tabs, status-pill nos estados active/past-due/plans, consumindo api-subscription.
- Agente IA: Tela #agente com tabs behavior/credential/crons, toggle-switch e form-field, consumindo api-llm-credential, api-agent-config e api-crons.

## Sprint 001 - Schema, Migration e Modelos SQLAlchemy (fundacao) [CONCLUIDA]
- Migration aditiva com 3 tabelas, FKs CASCADE, indexes e constraints: Novo arquivo SQL em backend/migrations/ com timestamp AAAAMMDD_HHMMSS_celula_pr2_reuniao_presenca_expectativa.sql que cria as 3 tabelas conforme a secao 2.1 da SPEC, sem tocar em tabelas existentes do PR1.
- RLS enable + policy tenant_isolation nas 3 tabelas: Na mesma migration, habilitar RLS e criar a policy tenant_isolation em cada uma das 3 tabelas novas, no padrao identico ao PR1 (20260703_123803_celula_schema_base_pr1.sql) e ao agenda_alert_recipients.
- Modelos SQLAlchemy CelulaReuniao, CelulaPresenca, CelulaExpectativaVisitante: Adicionar em backend/app/db/models.py os 3 modelos correspondentes, no estilo de Celula/CelulaMembro (mapped_column, server_default, timestamps).
- Testes de modelo/schema (test_celulas_pr2_models.py): Novo arquivo backend/tests/test_celulas_pr2_models.py cobrindo a estrutura dos modelos e da migration (colunas, unicidades, indexes, CHECKs, policies), no estilo dos testes existentes.

## Sprint 002 - Servico de calculo da proxima reuniao + endpoints de Reuniao [CONCLUIDA]
- Servico de calculo da proxima reuniao (domain/cell_meetings_schedule.py): Novo modulo backend/app/domain/cell_meetings_schedule.py com o parser PT-BR de dia_reuniao e o calculo da proxima data, com helper de relogio/data-base injetavel para testes deterministicos.
- Router cell_meetings.py + constantes + registro em main.py: Novo router backend/app/routers/cell_meetings.py que importa e reusa helpers de cells.py, define as constantes string de status/estado/origem e e incluido em main.py via include_router.
- GET /cells/{cellId}/reunioes (listar reunioes): Endpoint que lista as reunioes de uma celula escopadas ao tenant, sem paginacao, com ordenacao determinista.
- POST /cells/{cellId}/reunioes/next (materializar proxima reuniao, idempotente): Endpoint que materializa a proxima reuniao a partir de celulas.dia_reuniao/horario, criando em status planejada se nao existir ou retornando a existente, sempre 200.
- Testes dos endpoints de reuniao e do servico de calculo (US-01..US-04): Novo arquivo backend/tests/test_cell_meetings.py cobrindo o servico de calculo e os dois endpoints de reuniao.

## Sprint 003 - Endpoint de Presenca idempotente (propria e por lider) [CONCLUIDA]
- Helper _get_reuniao_or_404 + schema PresencaOut: Novo helper em cell_meetings.py que resolve a reuniao por id escopada ao tenant (nao exige cellId no path) e schema Pydantic PresencaOut em camelCase.
- POST /cell-reunioes/{reuniaoId}/presenca (auto + terceiro, upsert idempotente): Endpoint que confirma a propria presenca (sem pessoaId) ou marca terceiro (com pessoaId, exige lideranca), com upsert idempotente e checagem de vinculo ativo na celula da reuniao.
- Testes de presenca (US-05..US-08): Amplia backend/tests/test_cell_meetings.py com os cenarios de presenca.

## Sprint 004 - Endpoint de Expectativa de Visitante (nominal) [CONCLUIDA]
- Schemas Pydantic de expectativa (in/out) com validacao de borda: Schema de entrada com validacao de nomeVisitante/observacaoOracao e schema de saida ExpectativaVisitanteOut em camelCase.
- POST /cell-reunioes/{reuniaoId}/expectativas-visitantes (201 CREATED): Endpoint que registra a expectativa sempre da propria pessoa, permitindo N registros por membro/reuniao, sem efeitos externos.
- Testes de expectativa (US-09, US-10): Amplia backend/tests/test_cell_meetings.py com os cenarios de expectativa.

## Sprint 002 - Backend: auth + Minha Celula (Discipulo) [CONCLUIDA]
- Dependencies de autorizacao (deps/auth.py): Estender deps/auth.py com require_role(role), require_central() e get_current_cell_for_leader(). igreja_id e papel derivam sempre do contexto Clerk autenticado (nunca do payload). 'E lider desta celula' deriva de celulas.lider_id ligado a Pessoa do usuario (E9/6.6), nao de flag do cliente nem de celula_membro.papel. Setar set_tenant_context/current_igreja_id() por request.
- Endpoints do Discipulo: GET /api/cells/me/next-meeting, GET /api/cells/me/notices, GET /api/cells/me/history (paginado, projecao minimizada), POST e DELETE /api/cell-meetings/{id}/attendance/confirm, POST /api/cell-meetings/{id}/visitor-expectations. Reusar celula_expectativa_visitante (PR2) e celula_presenca (PR2). Mapear minha_presenca conforme E5 (compareceu->participou, ausente->faltou, confirmada->confirmou, sem linha->nao_confirmou). Fuso America/Sao_Paulo para 'passada'/'futura' (E4).

## Sprint 003 - Backend: Minha Celula (Lider) + Ciclo do relatorio [CONCLUIDA]
- Endpoints do Lider - reuniao, presenca, visitantes, registros: POST /api/cell-meetings (planejar reuniao pontual, relatorio_status nasce 'pendente'), PUT /api/cell-meetings/{id} (editar data/hora/tema; rejeitar campos sensiveis - RF-14), PUT /api/cell-meetings/{id}/attendance (presenca real em celula_presenca), POST /api/cell-meetings/{id}/visitors (celula_visitante, com expectativa_id opcional), GET /api/cell-meetings/{id}/visitor-expectations, POST e GET /api/cell-meetings/{id}/records (celula_reuniao_registro), GET /api/cells/{cell_id}/members (reusar cells.py). Todos restritos a propria celula (get_current_cell_for_leader).
- Ciclo do relatorio (draft, submit, consolidado): PUT /api/cell-meetings/{id}/report (grava oferta_valor e observacoes sem enviar), POST /api/cell-meetings/{id}/report/submit (consolida e muda relatorio_status para 'enviado', grava relatorio_enviado_em/por), GET /api/cell-meetings/{id}/report (consolidado: presencas, visitantes, records, oferta, observacoes, status). Validacoes E1/E2: oferta_valor >=0 e <=999999.99, observacoes <=2000. Regras E10/E11: apos enviado, relatorio bloqueado para edicao; sem reabertura no MVP.

## Sprint 004 - Backend: Solicitacoes de campo sensivel e Multiplicacao transacional [CONCLUIDA]
- Schemas discriminados por tipo e criacao com conflito: Schemas Pydantic de payload_proposto discriminados por tipo (alterar_dia/horario/endereco/anfitriao/auxiliar, transferir_membro, remover_membro, multiplicacao) conforme contratos da 6.3. POST /api/cell-requests: nasce 'aguardando', NAO altera dado real, gera evento 'criada' na mesma transacao, retorna 409 se ja existir solicitacao aberta conflitante (matriz E13/6.8). GET /api/cell-requests (lider ve as suas, Central ve da igreja, filtro por status). GET /api/cell-requests/{id} (detalhe + trilha de eventos).
- Decisao da Central e reenvio/cancelamento: cell_requests_service.py com aprovar/rejeitar/pedir ajuste/reenviar/cancelar. POST approve (Central, sem editar payload; aplica payload por tipo em transacao unica com auditoria 'aprovada'). POST reject e request-adjustment (observacao_central obrigatoria -> 422 se ausente; eventos 'rejeitada'/'ajuste_solicitado'). PUT resubmit (lider autor, so em ajuste_solicitado, evento 'reenviada'). POST cancel (lider autor, so em aguardando/ajuste_solicitado, evento 'cancelada', E12). Cada acao grava evento append-only na mesma transacao; falha parcial -> rollback total.
- Multiplicacao transacional e idempotente: cell_multiplication_service.py acionado por approve quando tipo='multiplicacao'. Exige idempotency_key. Em transacao unica: valida payload (6.3: novo_lider_id membro ativo da origem e presente em membros_transferidos_ids; minimo 1 membro), cria nova celulas com lider_id=novo_lider_id, desativa vinculos celula_membro antigos e cria vinculos ativos na nova celula, sincroniza pessoas.celula_id (espelho legado), grava multiplicacoes com solicitacao_id (UNIQUE), celula_id=origem e celula_nova_id=nova, registra auditoria. Reprocessar mesma aprovacao/idempotency_key nao duplica (RNF-06/07). GET /api/multiplicacoes lista pendentes (solicitacoes tipo multiplicacao aguardando) e registradas.

## Sprint 005 - Backend: Central (dashboard, fila, saude), Avisos e Materiais [CONCLUIDA]
- Avisos (cell_notices.py) e ponto de extensao de notificacao: POST /api/cell-notices (lider: origem='celula', escopo='celula' obrigatorio, so a propria celula; Central: origem='central', escopo celula ou igreja; regra de autoria validada no servidor), GET /api/cell-notices (alcance E15: escopo=igreja para todo usuario autenticado da igreja; escopo=celula para membros ativos+lider+Central; paginado), DELETE /api/cell-notices/{id} (inativa ativo=false por autor compativel). Tambem GET /api/cells/me/notices ja existente no dominio discipulo. cell_notify.py com funcoes notify_* no-op que apenas persistem intencao/estado (celula_aviso.notificado_em), sem chamada externa.
- Materiais (cell_materials.py): POST /api/cell-materials (Central; url obrigatoria iniciando com http://|https://, titulo<=120, descricao<=2000, url<=2048 - E2/6.1), GET /api/cell-materials (materiais ativos da igreja; lider e discipulo visualizam somente leitura - E14; paginado), DELETE /api/cell-materials/{id} (Central inativa ativo=false). Sem upload real de arquivo.
- Central: dashboard, fila de relatorios e saude (cell_central.py + cell_health_service.py): GET /api/cell-central/dashboard (contadores E16, nao paginado), GET /api/cell-central/pending-reports (reunioes passadas nao canceladas com relatorio_status='pendente', com celula_nome e lider_nome derivado de celulas.lider_id - 6.6; paginado), GET /api/cell-central/health (cell_health_service calcula on-read sobre ultimas 10 reunioes com 3 sinais e regras E6; ordena menos saudaveis primeiro). Fuso America/Sao_Paulo para 'passada'. Todos restritos a Central (require_central).

## Sprint 006 - Frontend: camada de API e Minha Celula (Discipulo) [CONCLUIDA]
- Camada de API tipada (*-api.ts): Criar/estender frontend/src/lib: cells-api.ts (getNextMeeting, getMyHistory, getCellMembers), cell-meetings-api.ts (planMeeting, updateMeeting, confirmAttendance, revertAttendance, setRealAttendance, indicateVisitor, getVisitorExpectations, registerVisitor, addRecord, getRecords, saveReport, submitReport, getReport), cell-notices-api.ts, cell-materials-api.ts, cell-requests-api.ts, cell-central-api.ts, multiplicacoes-api.ts (estender). fetch nativo, tipos TS espelhando snake_case do backend, erros ApiError/SessionExpiredError. Sem React Query/SWR/Zustand/Redux.
- Entrada por papel e visao Discipulo: MinhaCelulaEntry decide visao por papel autenticado (lider->Lider, so membro->Discipulo, sem alternador de demo). Disciple: NextMeetingCard (US-01 com empty), ConfirmAttendanceButton (US-02, 1 toque, otimista com rollback, desabilitado sem reuniao), IndicateVisitorModal (US-03, desabilita sem reuniao), NoticesFeed (US-04, celula=azul/central=vermelho), MaterialsFeed (US-21/E14 leitura), MeetingHistoryList (US-05). Reusar components/ui/ e primitivos. Copy pt-BR de E17.

## Sprint 007 - Frontend: Minha Celula (Lider) [CONCLUIDA]
- Painel, planejamento e relatorio da reuniao: LeaderPanel, PlanMeetingModal (US-06, data/hora/tema da reuniao pontual, nao altera padrao), MeetingReportForm em secoes/cards (nao wizard): AttendanceSection (US-07), VisitorsSection (US-08, registrar + confirmar esperados), RecordsSection (US-09), OfferingSection (US-10), SubmitReportButton (US-11, loading no botao, aguarda servidor). Toasts E17. Apos enviado, relatorio bloqueado.
- Discipulos, avisos da celula e solicitacoes: DisciplesList (US-12), CellNoticeForm (US-12A, aviso so da propria celula, azul) + LeaderNoticesFeed (US-12B, celula azul + central vermelho), SensitiveFieldRequestModal (US-13, abre fluxo de solicitacao, NAO salvar direto) + MyRequestsList (US-14: status + observacao_central; reenviar em ajuste_solicitado; cancelar em aguardando/ajuste_solicitado - E12). Materiais em leitura via MaterialsFeed reusado. Copy E17.

## Sprint 008 - Frontend: Central de Celulas (Jornada G12 > Discipular) [CONCLUIDA]
- Shell da Central e Dashboard/Gerenciar celulas: CentralTabs (Dashboard, Gerenciar celulas, Solicitacoes, Avisos, Materiais; abas roláveis) dentro de Jornada G12 > Discipular > Central de Celula, so para pastor/admin, nunca dentro de Minha Celula. Dashboard/WorkQueuePanel (US-22, cards + WorkQueueItem). ManageCells: CellHealthList (US-18, 10 bolinhas verde/vermelho/alerta, menos saudaveis primeiro), PendingReportsList (US-16, celula/lider/reuniao), MultiplicationsList (US-19, pendentes/registradas).
- Solicitacoes, Avisos e Materiais da Central: Requests: RequestsQueue (US-17, fila aguardando, master-detail no desktop) + RequestDecisionPanel (US-15, aprovar/rejeitar/pedir ajuste; observacao_central obrigatoria ao rejeitar/pedir ajuste; Central NAO edita payload). Notices/CentralNoticeForm (US-20, celula especifica ou igreja inteira, vermelho). Materials/MaterialsManager (US-21, publicar url obrigatoria + listar + inativar). Loading no botao nas acoes; toasts E17.

## Sprint 001 - PR1 - Superficie de teste RLS + observabilidade (aditivo) [CONCLUIDA]
- Config de teste opt-in (env + marker pytest): Adicionar a variavel de ambiente que liga os testes de integracao RLS e o marker pytest correspondente. Sem RLS_TEST_DATABASE_URL definida, os testes de integracao dao skip limpo (nao falham).
- conftest_rls.py com guard de producao + fixtures de banco descartavel: Criar backend/tests/conftest_rls.py com fixture de engine que le RLS_TEST_DATABASE_URL e faz pytest.skip limpo se ausente; guard de seguranca OBRIGATORIO que FALHA (nao skip) se a URL aparentar apontar para DEV/PROD; e fixtures que aplicam as policies + role authenticated NOBYPASSRLS e semeiam 2 igrejas (A, B) com dados no banco descartavel.
- test_rls_invariant.py com T1-T2 (baseline) e T3/T4 inativos: Criar backend/tests/test_rls_invariant.py marcado @pytest.mark.rls_integration com os testes T1 (sem contexto => nenhuma leitura tenant-scoped) e T2 (isolamento A<->B). T3 e T4 ficam declarados porem xfail/skip com motivo ('aguarda PR2 seam' / 'aguarda PR3-B worker'), ou testam o comportamento atual como baseline de nao-regressao.
- Sinal de observabilidade read-only (deteccao de sessao tenant em role de conexao): Criar um helper read-only, sem efeito sobre o runtime, que permita verificar num caminho de amostra se uma sessao tenant esta executando com current_setting('role')='authenticated' e current_igreja_id() nao-nulo. O objetivo e emitir um sinal (log/contador) quando uma sessao que deveria ser tenant-scoped roda em role de conexao (BYPASSRLS). Nao pode ser plugado em nenhum caminho de producao neste PR — apenas disponibilizado e coberto por teste.
- Job de CI com Postgres descartavel para a suite rls_integration: Provisionar um Postgres DESCARTAVEL num job de CI dedicado, aplicar as migrations minimas necessarias (policies RLS + role authenticated NOBYPASSRLS + tabelas tenant-scoped usadas pelos testes), setar RLS_TEST_DATABASE_URL APENAS nesse job e rodar a suite com o marker rls_integration. Sem esse job, os testes opt-in ficam sempre em skip e PR1 vira cobertura falsa (SPEC secao 10, risco 'CI sem Postgres -> T1-T4 sempre skip'). O job deve FALHAR se, com RLS_TEST_DATABASE_URL definida, os testes T1-T6 nao executarem (ex.: coletados 0 / todos skip). Ambiente local/offline sem a env var mantem skip limpo. Bloquear DEV/PROD como alvo reusando o guard do feat-002.

## Sprint 002 - PR2 - Criar o seam profundo tenant_session.py + listener after_begin [CONCLUIDA]
- Module tenant_session.py: mark_tenant_scoped / mark_cross_tenant / promote_to_tenant + excecoes: Criar app/db/tenant_session.py com as chaves de session.info (TENANT_IGREJA_KEY, TENANT_META_KEY, CROSS_TENANT_KEY) e as tres funcoes de marcacao com contrato de erro fail-closed. Definir a hierarquia de excecoes nomeadas (classe base TenantScopeError + TenantPinConflictError + TenantPromotionError).
- Listener after_begin fail-closed registrado uma unica vez: Registrar o listener SQLAlchemy after_begin que reaplica o escopo (set_config('app.tenant_igreja_id', igreja_id, true) + set local role authenticated) usando connection.exec_driver_sql (nao session.execute, para evitar reentrancia), SOMENTE quando session.info tem igreja_id marcado. O SQL deve ser byte-identico ao de set_tenant_context_for_igreja preservando bind param (anti-injecao). Registro uma unica vez no import (session.py) para nao empilhar handlers.
- test_tenant_session_unit.py (unit, sem DB): Testes unitarios do contrato de session.info e das excecoes, sem Postgres real (nao exercitam enforcement, so a mecanica das funcoes de marcacao).
- Ativar T3/T5/T6 e provar o seam em 1 HTTP read-only + 1 leitura worker (coexistencia): Ativar em test_rls_invariant.py os testes T3 (leitura pos-commit reabre escopo via listener), T5 (sem vazamento de role/GUC pelo pool) e T6 (listener fail-closed). Provar o seam num unico caminho HTTP read-only trivial e numa unica leitura do worker, SEM remover os ensure_tenant_context legados (coexistencia idempotente).

## Sprint 003 - PR3-A - Migrar auth (deps.py) + caso HTTP ancora (subscription.py) [CONCLUIDA]
- get_current_user marca a sessao com igreja_id resolvido: Substituir a semente set_tenant_context(db, identity.clerk_user_id) (deps.py:118) por: resolver o igreja_id do usuario e chamar mark_tenant_scoped(db, igreja_id, actor_sub=..., actor_role=..., source='http'). Resolver o ovo-e-galinha: manter a semente via sub APENAS para a query de resolucao do app_user, e assim que igreja_id for conhecido chamar mark_tenant_scoped (o GUC passa a governar, pois current_igreja_id() prioriza o GUC). Alternativa aceitavel: fase cross-tenant curta como no worker (OQ#1 — escolha do implementador, documentar).
- get_platform_admin marca a sessao como cross-tenant explicito: Adicionar mark_cross_tenant(db, actor_sub=..., source='platform_admin') em get_platform_admin (hoje a ausencia de chamada e o que da BYPASSRLS). Sem mudanca de comportamento: continua cross-tenant/BYPASSRLS, mas agora greppavel e a prova do listener (que nao reaplica escopo em sessao marcada cross-tenant).
- subscription.get_subscription: remover re-asserção manual pos-commit: Remover a re-asserção manual de ensure_tenant_context em subscription.py:193 (a chamada dupla pos-commit). Com o listener D2, notify_autoupgrade (comita) + db.refresh(sub) (linha 194) ja reabrem a transacao ja escopada. Manter a mesma resposta do endpoint. Este e o caso ancora provando que a estrutura substitui a convencao.

## Sprint 004 - PR3-B - Migrar worker + sweep de SLA por igreja [CONCLUIDA]
- ingest_message_event_ex: lookup cross-tenant -> promocao explicita: Em queue_worker.ingest_message_event_ex, o lookup de WhatsappConnection por instance (:111-115) passa a rodar numa sessao marcada mark_cross_tenant(db, source='worker_ingest'); apos obter igreja_id, chamar promote_to_tenant(db, igreja_id, source='worker_ingest') no lugar de set_tenant_context_for_igreja(db, igreja_id) (:128). A ordem 'lookup-antes-de-promocao' vira estrutura: a promocao FALHA se nao precedida da fase cross-tenant.
- run_agent_for_message: sessoes reabertas usam mark_tenant_scoped: Em queue_worker.run_agent_for_message, as duas sessoes reabertas (session_factory() em :428 e :453) passam a chamar mark_tenant_scoped(session, outcome.igreja_id, source='worker_agent') no lugar de set_tenant_context_for_igreja (:433, :456). Manter o guard 'if outcome.igreja_id is not None'. Garantir close()/context-manager em todos os caminhos (inclusive excecao) para nao devolver conexao ao pool em role authenticated.
- sla_engine.run_all_igrejas: sessao tenant-scoped por igreja: Ajustar sla_engine.run_all_igrejas (sla_engine.py:342-373, chamado por cron_worker.py:173). Hoje ele reusa UMA sessao compartilhada iterando igrejas (BYPASSRLS + filtro manual). Por causa do pinning de D3, reutilizar uma sessao marcada iterando igrejas diferentes violaria o pinning. Adotar a estrategia (a): criar uma NOVA sessao tenant-scoped por igreja dentro do sweep (mark_tenant_scoped(nova_sessao, igreja_id, source='cron_sla') por iteracao), cada uma fechada ao fim da iteracao. Cobrir com teste que nao ha vazamento entre igrejas.
- Ativar T4 (caminho worker nao depende so de filtro manual): Ativar em test_rls_invariant.py o teste T4: fase cross-tenant (lookup por instance) -> promote_to_tenant -> leituras/escritas escopadas a igreja; promote sem fase cross-tenant precedente FALHA; pinning: promover a igreja diferente FALHA.

## Sprint 005 - PR4+ - Migrar routers restantes + destino de ensure_tenant_context [CONCLUIDA]
- Remover ensure_tenant_context dos routers de alta densidade: Remover ensure_tenant_context(db, current_user) dos routers de maior densidade primeiro (cell_meetings.py=19, calendar.py=11, conversations.py=10, cell_requests.py/cells.py/cell_discipulo.py=8-9 ocorrencias). Cada router validado por T1-T6 + seus proprios testes. Comportamento observavel identico (a sessao ja vem marcada de get_current_user).
- Remover ensure_tenant_context dos routers restantes: Remover ensure_tenant_context(db, current_user) dos demais routers (restante dos ~20 routers apos os de alta densidade do feat-016), OBRIGATORIAMENTE em lotes pequenos com limite explicito por PR (maximo 3 routers por PR/commit), cada lote com gate proprio antes de seguir para o proximo. Nunca migrar todos de uma vez (blast radius, SPEC secao 10).
- Destino final de ensure_tenant_context em _common.py: Ao migrar o ultimo router, decidir e implementar o destino de ensure_tenant_context (OQ#3): remover de vez OU transforma-lo num shim de assert que FALHA (observabilidade fail-closed) se a sessao nao estiver marcada. Documentar a escolha. Auditar tambem chamadores de clear_tenant_context (rls.py:68) — quem quiser sair da RLS deve usar mark_cross_tenant, nao clear_tenant_context (que e inocuo no modelo novo).

---

## Apendice - Cronologia 2026-07-08 a 2026-07-18 (pos-pipeline C1/RLS)

Fonte: `docs/sprints/` e `docs/security/2026-07-08-seg-igreja12-remediation-plan.md`. Cada item traz PR e release (commit de `origin/main` deployado em producao).

- **SLA-ALIGN-1** — alinhamento do contrato `SLA_CONNECTION` para 24h. PR#175; release `82e1c6f` (2026-07-16).
- **MSG-IDEMP-1** — dedupe de mensagem inbound por indice unico (migration aplicada em PROD antes do deploy). PR#176; release `82e1c6f` (2026-07-16).
- **PIPE-1** — correcao da leitura de etapa `NULL` no pipeline pastoral. PR#178; release `82e1c6f` (2026-07-16).
- **CONSOL-1** — impede consolidacao aberta duplicada por pessoa (indice + savepoint; migration em PROD). PR#179; release `82e1c6f` (2026-07-16).
- **Wave visual W2** — papeis/status na UI de Pessoas. PR#173 (merge `d00bbb5`); deploy de frontend ~2026-07-15.
- **Wave visual W3** — Agenda + dialogos. PR#174 (merge `611a2ad`); deploy de frontend ~2026-07-15.
- **Wave visual W4A** — dialogos Report/NewContact/LinkCell migrados para `ds/Dialog`. PR#183 (merge `a67cae9`); deploy de frontend 2026-07-17 (`3aac399`).
- **Wave visual W4B** — dialogos admin (Create/Edit/Orquestrador Igreja) migrados para `ds/Dialog`. PR#184 (merge `70846d2`); deploy de frontend 2026-07-17 (`3aac399`).
- **SEC ALTO-003** — fonte unica para `CENTRAL_ROLES`. PR#181; release `70846d2` (2026-07-16).
- **SEC ALTO-004 (parte 1)** — hardening do OAuth state do Google Calendar via `verify_purpose_token`. PR#182; release `70846d2` (2026-07-16).
- **SEC ALTO-004 (conclusao) / unificacao JWT (verify)** — `verify_session/reset/invite_token` delegando a `verify_purpose_token`. PR#186; release `fd651f9` (2026-07-17). Reconciliacao REL-5 dos findings ALTO/MEDIO em `docs/security/` (PR#185/#187): 9 de 11 concluidos+deployados.
- **Fechamento `b5b990d`** (PR#188; release backend+frontend 2026-07-18): **MEDIO-004/CONTACT-TENANT-DEDUP-1** (dedupe de contato com filtro explicito de `igreja_id`), **MEDIO-005/JWT-MINT-1** (emissao dos 3 tokens de proposito unificada em helper unico) e **W5A** (ultimos 8 dialogos migrados para `ds/Dialog`). Smoke autenticado em PROD 2026-07-18: PASS.

## Delta-074 — seguranca de autoria e replay de migrations (2026-09-04)

O commit local `9b9395e29cc821d6808738a30a6afe367d4ffbea`, parent
`947af39d35544700188461d8c99332df70b57e07`, entrega autoria source-only
`draft`/`prepare-head` somente `TENANT`, snapshot validado, wrapper catalog-bound
v2 apenas `list` e replay do head em PostgreSQL 17 descartavel e loopback. Ele
nao foi integrado e nao passou por push, PR ou CI remoto.

No mesmo SHA, o verificador longitudinal confirmou 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`.
A focal terminou `274 passed, 6 skipped`; a prova PG17 real terminou `6/6`, com
E2E sintetico de 76a migration `TENANT`; duas revisoes independentes fecharam
`P0=0` e `P1=0`. O workflow agora usa PG17 descartavel e replay, sem tocar banco
compartilhado, DEV/PROD ou o runner legado de aplicacao.

O `apply_migrations.py` legado segue invocavel como risco residual. O replay nao
cobre views, outros schemas, funcoes, roles/memberships, `BYPASSRLS`, grants
nomeados, ACLs de schema/default ou semantica ampla DML/DDL. Worktree e
migrations estao observadas em `0755` e SQL em `0644`, mas ancestrais do
workspace/repositorio seguem `0775` e o `chmod` local nao e duravel; P2 global
permanece.

DEV continua `BLOCKED_LEDGER_DIVERGENCE`, PROD
`BLOCKED_EVIDENCE_INSUFFICIENT`, TLS DEV historico sem solucao, e revisao v3,
cutover, atestacoes vivas e apply pendentes. `operational_authorization=false`
e `next_stage_authorized=false`.

O gate
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_ENVIRONMENT_EXECUTOR_V2_OFFLINE`
foi proposto, nao consumido e substituido. O unico estagio corrente fechado e
`OWNER_AUTHORIZE_REMOTE_PREFLIGHT_PUSH_AND_PR_MIGRATION_SAFETY_R1`, sem
autorizar merge, banco compartilhado, DEV, PROD, migration, runner de aplicacao
ou flags. Trust anchors externos seguem futuros, nao correntes e nao
autorizados; o pacote v3 permanece inalterado.
