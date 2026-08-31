# D2B2b3A: rascunhos governados no Console Master

Data: 2026-08-28

Status: `IMPLEMENTED_DRAFT_ONLY / INACTIVE`

Baseline documental de entrada:
`f249408f5bf7a14c0badb91d705e13cf4d1f7ea1`

Implementacao integrada:
PR #320, HEAD `66ce06d9a356a52e63366b3a6528b0b83170d12e`, merge
`947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`

## Decisao

O Admin Master autenticado no Console da plataforma pode preparar e manter, por
igreja, um rascunho independente para cada uma das quatro finalidades
canonicas:

1. `atendimento_solicitado`;
2. `cuidado_pastoral`;
3. `tarefas_operacionais`;
4. `comunicados`.

O Console e a superficie administrativa para organizar esse trabalho. Nenhum
e-mail, inclusive o do operador que iniciou a configuracao, integra o contrato
de autorizacao, o schema ou o codigo. A identidade do Master vem da sessao
autenticada e da allowlist server-side ja existente; igreja e ator sao
vinculados pelo backend, nunca por um valor de autoridade aceito do formulario.

Esta decisao autoriza somente a implementacao de rascunhos. Ela nao materializa
aprovacao humana ou juridica, nao constitui parecer e nao concede autoridade ao
runtime.

## Separacao entre preparar e decidir

O Master pode registrar e atualizar informacoes administrativas e fatos ainda
nao atestados para que os responsaveis da igreja executem o fluxo governado
posterior. Cada registro permanece explicitamente
`DRAFT_NOT_APPROVED`, mesmo quando todos os campos editaveis estiverem
preenchidos.

O Master nesta superficie nao pode:

- escolher hipotese juridica para dados comuns ou sensiveis;
- declarar que a operacao depende de consentimento;
- decidir a aplicabilidade das regras para criancas e adolescentes;
- atestar fatos, emitir parecer, aprovar, rejeitar ou mudar estado;
- agir como dono factual, encarregado, revisor de privacidade, juridico ou
  representante autorizado do controlador;
- preencher, importar ou fabricar registros nominais de aprovacao;
- calcular ou registrar digest como se fosse conteudo atestado;
- liberar catalogo, evidence store, writer ou qualquer caller downstream de
  aprovacao, ledger ou runtime.

Uma mesma pessoa somente podera desempenhar outro papel em etapa futura quando
essa designacao existir de forma autentica, nominal e auditavel no fluxo da
igreja. O papel de Admin Master, isoladamente, nunca implica essa designacao.

## Schema fechado do rascunho operacional

O rascunho D2B2b3A e material preparatorio separado do `decision_payload`
imutavel do pacote aprovado. Ele aceita somente oito campos opcionais de texto:

1. agentes reais do processamento;
2. operacoes e dados minimos;
3. avaliacao operacional da sensibilidade, sem classificacao juridica;
4. necessidade operacional;
5. sistemas e destinatarios;
6. inventario de retencao e descarte, sem aprovacao da politica;
7. instrucoes operacionais;
8. questoes em aberto.

Cada campo tem limite de 4.000 caracteres e o conjunto, limite de 16.000. Texto
vazio e normalizado para nulo e caracteres de controle nao permitidos sao
recusados. Chaves adicionais falham fechadas. Uma etapa humana posterior deve
revisar e transpor o material aplicavel para uma nova versao governada do
`decision_payload`; a aplicacao nao promove o rascunho automaticamente.

## Superficies permitidas nesta fatia

A D2B2b3A pode adicionar somente:

- migration imperativa versionada para persistencia de rascunhos;
- ORM e servico interno limitados ao estado de rascunho;
- API autenticada do Console Master para consultar o estado, inicializar os
  quatro rascunhos vazios e atualizar uma finalidade em uma igreja
  explicitamente selecionada;
- aba de governanca na pagina da igreja no Console, com quatro finalidades e o
  aviso permanente `RASCUNHO, NAO APROVADO`;
- auditoria administrativa com metadados minimos, sem copiar o payload do
  pacote, parecer, contato pessoal ou conteudo restrito para o log.

A disponibilidade da superficie usa
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED`, com default `false` em todos os
ambientes. Essa flag libera somente o workspace de rascunhos e nunca implica
aprovacao, catalogo, writer, agente ou efeito externo.

A migration faz parte do artefato de codigo e deve ser validada em PostgreSQL
17 descartavel. Ela nao autoriza aplicacao em Supabase DEV, Supabase PROD ou
outro banco compartilhado.

## Contrato de persistencia e concorrencia

Cada igreja possui no maximo um envelope ligado por chave estrangeira e
unicidade a `igreja_id`. O envelope contem exatamente as quatro chaves de
finalidade, sem chaves adicionais, e uma revisao positiva independente para
cada rascunho. A finalidade vem da rota tipada; o backend revalida igreja,
Master e escopo antes da leitura ou escrita. O ator gravado e o identificador
interno derivado da sessao, nunca um e-mail fornecido pelo cliente.

O update de uma finalidade exige a revisao esperada desse rascunho e incrementa
as revisoes correspondentes no servidor sob lock do envelope. Uma revisao
obsoleta falha sem sobrescrever trabalho concorrente. Nao existe delete na API
desta fatia. O payload aceita apenas campos conhecidos, tipados e limitados;
chaves arbitrarias, campos de autoridade, estados de ciclo e registros nominais
sao recusados.

Se a tabela ficar em schema exposto, a migration deve habilitar e forcar RLS e
revogar privilegios de `PUBLIC`, `anon`, `authenticated`, `service_role` e
`agent_runtime`. Nao existe policy de Data API para esses rascunhos. O acesso
ocorre exclusivamente pelo caminho privilegiado e auditado do Console Master,
com tenant explicito. RLS e privilegios sao barreiras independentes.

A implementacao integrada e inativa nao prova esse wiring. No baseline
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD somente leitura
confirmou `DATABASE_URL` presente e `M06_MIGRATION_DATABASE_URL` ausente.
`current_user` e `session_user` convergiram para a mesma identidade sanitizada;
a role runtime possui `NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, e owner
de `public.igrejas` e `public.app_users` e possui `SELECT` e `REFERENCES`
efetivos nessas tabelas-pai. A tabela alvo D2B2b3A, o validator e a propria
`public.schema_migrations` estavam ausentes. Isso comprova identidade, ownership
e ACL do caminho runtime atual, mas nao o comportamento da tabela futura sob
`FORCE RLS`; o caminho de migration permanece bloqueado pela ausencia de
`M06_MIGRATION_DATABASE_URL` e do ledger publico.

A PR #321 integrou a reconciliacao documental anterior no merge
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o deployment
automatico Vercel frontend Production `6141449639`, com `SUCCESS`, em
2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar backend,
banco ou Supabase. O preflight VPS em si nao executou deploy manual ou do
backend, migration, restart ou alteracao da flag.

## Contrato da interface

A tela deve explicar, em linguagem operacional, que o Master prepara somente o
rascunho operacional e que os responsaveis designados pela igreja revisam esse
material, formam o pacote governado e o atestam e aprovam em etapa posterior.
Completude de rascunho e apenas uma ajuda de preenchimento e nao pode usar
rotulos como aprovado, valido, consentido, apto ou liberado.

Campos fora da competencia do Master aparecem bloqueados ou ficam ausentes da
edicao. A interface nao oferece botoes de atestar, aprovar, registrar parecer,
vincular assinatura, mudar status, publicar, ativar ou enviar.

## Invariantes que permanecem fechados

- `controller_approved=false`;
- `human_packet_complete=false`;
- `catalog_ready=false`;
- `writer_eligible=false`;
- nenhum evento `concedido` e criado;
- nenhum estado do ledger D2B2a e alterado;
- nenhuma configuracao, gate ou credencial e alterada;
- nenhum payload e lido pelo WhatsApp, webhook, worker, LangGraph, tool ou
  agente;
- nenhum acesso e concedido ao painel do tenant nesta fatia;
- esta missao nao aplicou a migration D2B2b3A; DEV e PROD confirmaram a
  ausencia;
- nenhum deploy manual ou do backend, ativacao ou canario e executado;
- D2C, memoria, conhecimento e outbox continuam bloqueados;
- Universidade da Vida e Capacitacao Destino permanecem fora da missao atual.

## Criterios de aceite da PR

1. O schema e o backend falham fechados para tenant ausente, finalidade
   invalida, Master nao autorizado, campo proibido e revisao obsoleta.
2. Testes com ao menos duas igrejas comprovam que um rascunho nunca aparece ou
   e alterado pela selecao de outro tenant.
3. A migration e idempotente, explicita RLS, grants e revokes e passa em
   PostgreSQL 17 descartavel sem acessar Supabase compartilhado.
4. A API nao aceita e-mail, identidade, papel, igreja, status, aprovacao ou
   digest como autoridade enviada no payload.
5. A tela preserva o aviso de rascunho e nao oferece transicao humana ou
   operacional.
6. A auditoria registra igreja, finalidade, ator, revisao e instante, sem
   copiar conteudo do pacote.
7. Testes e documentacao nao usam PII ou dados reais.

## Itens explicitamente posteriores

Uma nova decisao e uma nova PR serao necessarias para o fluxo nominal de
atestado, revisao de privacidade, revisao juridica quando designada e aprovacao
final do controlador. Continuam posteriores tambem catalogo imutavel, evidence
store, digest e recibos governados, writers, WhatsApp, runtime do agente e
qualquer ambiente compartilhado.

## Evidencia de integracao

Os cinco workflows da PR #320 e os cinco workflows pos-merge concluiram com
`SUCCESS`. O merge gerou o deployment automatico Vercel frontend Production
`6140373952`, tambem com `SUCCESS`. Essa metadata prova somente o frontend nesse
ambiente; nao prova backend, banco ou Supabase. Esta missao nao aplicou a
migration D2B2b3A; DEV e PROD confirmaram a ausencia. A flag
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permanece `false`. No recorte da PR
#320 nao houve deploy manual ou do backend, wiring, ativacao ou canario. O preflight PROD
somente leitura do baseline `15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`
confirmou os atributos e bloqueios sanitizados descritos acima. O preflight VPS
em si nao executou deploy manual ou do backend, migration, restart ou alteracao
da flag.

Desenvolvida e comprovada offline sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, a implementacao foi integrada
pela PR #323. `bootstrap-ledger` e separado de `harden-ledger`, com
confirmacao literal `BOOTSTRAP_LEDGER` e destino somente por
`M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17 ele cria atomicamente apenas o
ledger vazio `public.schema_migrations`, no contrato exato owner-only com RLS,
policy deny e ACL minima. Homonimos, grants, default privileges, membership,
ownership ou forma fisica divergentes abortam e revertem; a reaplicacao exata e
um no-op.

A prova terminou com 42/42 testes unitarios, 87/87 em PostgreSQL 17-alpine
descartavel em duas execucoes independentes, 87/87 em Supabase PG17 17.6.1.159
descartavel em duas execucoes independentes e revisao de seguranca `GO`. A
suite RLS completa, em execucao serial limpa no PostgreSQL 17 descartavel,
passou em 326/326, com 3803 deselecionados e 2 warnings preexistentes, em
162.77s. A suite offline integral foi interrompida apos 5 min sem saida ou
progresso; o resultado e `INCONCLUSIVO`, nao verde nem falha e nao foi
reclassificado. Os workflows Backend Tests da PR #323 e do pos-merge concluiram
com `SUCCESS`. O bootstrap nao descobre o catalogo,
nao le ou altera `supabase_migrations`, nao reconcilia, nao faz backfill e nao
aplica ou registra migration. O ledger vazio preserva o bloqueio tecnico de
`status` e `apply` ate uma reconciliacao historica humana formar o prefixo
integro do catalogo, com no maximo uma migration pendente.

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
continuam como evidencia historica separada.

O pacote deny-state versionado e o verificador stdlib separado do runner,
desenvolvidos e comprovados offline sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram integrados pela PR #325,
HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
`2026-08-28-migration-history-reconciliation-contract.md`. O estado e
`INTEGRADO / COMPROVADO OFFLINE / DECISOES HUMANAS PENDENTES / NAO APLICADO`.
Nenhuma decisao humana esta aprovada. A integracao nao acessou DEV ou PROD, nao
materializou inventario de ambiente e nao reconciliou nenhum ledger. O verificador nao acessa banco,
rede, ambiente ou variaveis de ambiente, nao executa SQL, DML ou escrita e nao
infere migration aplicada. Os ledgers nativo e publico permanecem independentes
e todo sucesso estrutural conserva `OPERATIONAL_AUTHORIZATION=BLOCKED`.

Os cinco workflows da PR e os cinco pos-merge concluiram com `SUCCESS`. A
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
[`decisao de derivacao offline`](2026-08-29-offline-canonical-schema-derivation.md).
Isso nao atesta DEV, PROD, Data API ou Realtime; `OPERATIONAL_AUTHORIZATION=BLOCKED`
permanece obrigatorio.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisao de derivacao offline`](2026-08-29-offline-canonical-schema-derivation.md).
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
[`decisao de atestacao read-only`](2026-08-30-read-only-environment-attestation-tooling.md).
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
[`diagnostico do preflight de identidade de DEV`](2026-08-30-dev-identity-preflight-diagnostics.md).
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
`diff-check` ficaram verdes, os recursos temporarios foram removidos e Sarah
concluiu `GO`, sem P0, P1 ou P2. As duas execucoes DEV historicas com exit `7`
nao podem ser retroclassificadas. A unica `query_logs` anterior retornou vazio
e continua `EVIDENCE_INSUFFICIENT`. Esta missao nao repetiu a consulta e nao
acessou DEV ou PROD. A evidencia detalhada esta na
[`decisao de fase sanitizada`](2026-08-30-dev-preflight-failure-phase-diagnostics.md).

O enum sanitizado foi integrado pela PR #344 no `main`
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
O contrato e os limites estao na
[`decisao de 2026-08-31`](2026-08-31-dev-connect-tls-auth-transport-probe.md).
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

O gate abaixo foi consumido em 2026-08-31:
`SEPARATE_NOMINAL_DEV_CONNECT_TLS_AUTH_TRANSPORT_PROBE_AUTHORIZATION`. Seu
consumo exige nova autorizacao humana nominal para exatamente uma invocacao
`PROCESS_INVOCATION_ONLY` no checkout de `main` `1e727cd2`, com runner SHA-256
`4196e218e023f5ef16fe333f62b756b55239d0bdde1c11aed12e59af888f6cc9` e o
`source_main_git_sha=36f8d13284a8f4964d0258a2a3b845323a80fe7e` exigido pelo
contrato interno. Nao autoriza retry, senha, autenticacao, sessao de banco,
SQL, logs,
captura, materializacao, DML, migration, reconciliacao, backfill, deploy manual
ou Production, flag, runtime e PROD continuam bloqueados.

Uma unica invocacao terminou com exit `7`, fase `TLS_HANDSHAKE` e
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
`14b3d7ba15e88032cd53714008d36badd4578e80` congela exclusivamente offline o
contrato puro `AgentTurnIdentity` e `AgentEffectIntent`. A identidade vincula
`igreja_id`, conversa, mensagem inbound persistida, provedor Evolution e ID do
provedor exato; `claim_id` nao participa. O `effect_id` deriva do turno, do
slot semantico versionado e de um ordinal estavel, enquanto um digest separado
vincula o payload JSON canonico. O ordinal ainda exige um futuro plano
deterministico e persistido, e a validacao recebe a identidade esperada de uma
fonte confiavel.

Na branch local, o commit
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

**Proximo gate unico:**
`REVIEW_AND_CI_D3_CELL_REPORT_OFFLINE_FOUNDATION_PR`. O nome nao constitui autorizacao
ja concedida. Seu consumo exige autorizacao humana posterior e separada que
nomeie push, abertura da PR e GitHub CI e aceite o Vercel Preview automatico.
O gate cobre somente revisao e CI da fundacao offline ampliada do relatorio de
celula. Nao autoriza merge, Vercel Production, flag-on, runtime, worker, saver,
probe vivo, acesso a DEV ou PROD, banco, logs, SQL, DML, migration, rede,
deploy, mensagem, tool call ou qualquer efeito vivo.
