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

## Proximo gate unico

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

O gate atual e `SEPARATE_READ_ONLY_ENVIRONMENT_ATTESTATION`, em missao e autorizacao proprias,
somente leitura.
Ele nao autoriza DML, reconciliacao de ledger, corte de epoca, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, migration, backfill,
deploy, flag ou runtime. Universidade da Vida e Capacitacao Destino permanecem
fora.
