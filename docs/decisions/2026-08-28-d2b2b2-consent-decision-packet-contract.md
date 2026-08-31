# D2B2b2: contrato do pacote de decisão de consentimento

Data: 2026-08-28

Status: `TEMPLATE_ONLY / NOT_APPROVED / DRAFT_SURFACE_AUTHORIZED`

Baseline: `74951828f48994622a112d8e59eb978e5fb4f406`

## Resultado desta decisão

Esta decisão cria somente um formulário vazio e verificável para organizar as
decisões humanas, jurídicas, de privacidade e operacionais que ainda bloqueiam
o consentimento por finalidade. O arquivo
[`d2b2b2-decision-packet.template.json`](../governance/consent/d2b2b2-decision-packet.template.json)
é um template, não um pacote aprovado.

Merge, revisão de PR, teste verde, preenchimento parcial, texto em Git ou valor
`approved` escrito manualmente não constituem aprovação jurídica, autorização
do controlador nem autoridade de runtime. Esta decisão não é parecer jurídico.

A decisão sucessora
[`D2B2b3A`](2026-08-28-d2b2b3-master-governance-drafts.md) autoriza o Admin
Master a preparar rascunhos vinculados a uma igreja no Console. Ela não muda o
estado deste template e não permite ao Master escolher hipótese jurídica,
atestar, aprovar, representar outro papel ou preencher registros nominais.

## Estado anterior confirmado

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, foi integrada no
merge `74951828f48994622a112d8e59eb978e5fb4f406`. A D2B2b1 permanece
inativa, sem migration ou caller. Ela exige chave idempotente opaca gerada no
servidor, aplica autorização deny-first e recusa `concedido` antes de I/O.

Os indicadores abstratos de escopo ainda não substituem um builder
transacional vinculado a tenant, ator, Pessoa e recurso canônico. Retry entre
processos continua bloqueado até existir recibo durável autenticado. Nada
nesta decisão conecta catálogo, evidence store, writer, WhatsApp, LangGraph ou
Supabase. Somente a sucessora D2B2b3A pode criar persistência, API e painel
estritamente limitados ao preparo de rascunhos pelo Console Master.

## Fontes primárias consideradas

Links oficiais conferidos em 2026-08-28:

- [Lei nº 13.709/2018, texto compilado](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm),
  especialmente conceitos, princípios, hipóteses de tratamento,
  consentimento, transparência, dados sensíveis, direitos e segurança;
- [Guia Orientativo para Definições dos Agentes de Tratamento e do
  Encarregado](https://www.gov.br/anpd/pt-br/centrais-de-conteudo/materiais-educativos-e-publicacoes/guia_agentes_de_tratamento_e_encarregado___defeso_eleitoral.pdf/%40%40display-file/file),
  porque controlador, operador e suboperador dependem da atuação real em cada
  operação;
- [Resolução CD/ANPD nº 19/2024](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024),
  para inventário, mecanismo e transparência de eventual transferência
  internacional;
- [Lei nº 15.211/2025](https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15211.htm),
  [Decreto nº 12.880/2026](https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2026/decreto/d12880.htm)
  e a [página oficial da ANPD sobre o ECA
  Digital](https://www.gov.br/anpd/pt-br/assuntos/eca-digital), para que o
  controlador decida, com revisão jurídica, se as regras de proteção de
  crianças e adolescentes em ambientes digitais se aplicam à operação real.

O repositório não escolhe hipótese jurídica nem interpreta essas fontes em
nome de uma igreja.

## Regra de separação por finalidade

Cada igreja ou controlador materializa uma instância governada do envelope. A
instância contém quatro pacotes independentes, versionados e aprovados
separadamente:

1. `atendimento_solicitado`;
2. `cuidado_pastoral`;
3. `tarefas_operacionais`;
4. `comunicados`.

Uma aprovação agregada do envelope não satisfaz o gate. Cada pacote vincula a
igreja e o controlador materializado, a própria finalidade, a operação real, a
classe de dados, o texto apresentado, a evidência exigida, a política de
retenção e seis slots de registros nominais ao longo do ciclo. Quatro slots
pertencem ao gate humano desta etapa; segurança ou arquitetura e verificação
técnica independente pertencem somente ao futuro gate técnico do writer.

O digest de cada pacote usa SHA-256 sobre UTF-8 canonicalizado conforme RFC
8785 JCS. O escopo é exclusivamente o objeto imutável `decision_payload`, que
inclui versão de schema, finalidade, identificador e versão do pacote, vínculo
ao tenant e todo o conteúdo humano ou jurídico analisado. O envelope de
governança, incluindo status, digest armazenado, referências de aprovação,
instantes e indicadores derivados, fica fora do hash. Cada registro externo de
aprovação referencia o digest, o papel nominal, a identidade autenticada por
referência, a decisão e o instante. Depois do primeiro registro, qualquer
mudança no `decision_payload` exige uma nova versão e um novo digest; não se
edita o payload já atestado. A canonicalização, o algoritmo e o escopo estão
fixados também no template para que a prova seja reprodutível e não circular.

Se a análise humana concluir que uma operação usa hipótese jurídica diferente
de consentimento, o ledger `consentimento_finalidade_evento` não pode registrar
`concedido` como substituto. Essa operação exigirá contrato próprio de política
de tratamento, transparência e oposição. Retirada de consentimento, oposição e
opt-out não são eventos intercambiáveis.

## Conteúdo obrigatório de cada pacote

Cada um dos quatro pacotes da instância deve preencher, sem defaults jurídicos:

1. identificação, versão, vigência, digest e versão substituída;
2. controlador, operador, suboperadores e atuação real por operação;
3. finalidade específica, operações, dados mínimos, titulares, destinatários
   e compartilhamentos;
4. classificação de dado comum, sensível ou incerta, inclusive inferências;
5. hipótese jurídica separada para dados comuns e sensíveis, responsável pela
   escolha, justificativa e evidência;
6. texto exato por canal e idioma, consequências da recusa, direitos,
   retirada ou oposição e confirmação posterior;
7. evidência correlacionada de apresentação e manifestação, com identidade,
   finalidade, versão, canal, instante e desafio pendente;
8. decisão explícita `APPLICABLE`, `NOT_APPLICABLE` ou `UNCERTAIN` sobre as
   regras de proteção de crianças e adolescentes, com justificativa, evidência
   e revisor. `UNCERTAIN` bloqueia catálogo e writer. Se aplicável, o pacote
   exige avaliação de melhor interesse, medidas de idade ou responsável e
   avaliação de riscos e impacto;
9. mudança material, expiração, reaceite e tratamento da recusa;
10. retenção e destino de ledger, evidência, mensagens, mídia, transcrição,
    resumo, checkpoint, vetores, logs, dead-letter e backups;
11. opt-out, retirada, eliminação, legal hold e reativação;
12. inventário e mecanismo de transferência internacional;
13. responsáveis por direitos, incidentes e revisão periódica;
14. RBAC por finalidade, ação e escopo, mais binding server-side ao recurso;
15. contrato futuro do recibo idempotente durável;
16. dados enviados ao modelo, memória, derivados, isolamento por tenant,
    acesso humano e eliminação;
17. slots de referências nominais do dono factual da operação, segurança ou
    arquitetura, privacidade ou encarregado, jurídico quando designado, representante
    autorizado do controlador e verificador técnico independente. Cada
    registro externo contém referência, digest atestado, decisão e instante.
    Se não houver revisor jurídico designado, o slot exige registro assinado
    pelo controlador declarando essa decisão, sem ser tratado como parecer.

No gate humano, campos de decisão vazios, `desconhecido`, `pendente` ou `não
aplicável` sem justificativa mantêm o pacote bloqueado, assim como qualquer um
dos quatro registros exigidos nesse estágio. Os dois slots técnicos podem
permanecer vazios até a fatia futura de catálogo e writer, quando passam a ser
obrigatórios e vinculados ao mesmo digest aprovado.

## Perguntas específicas

| Finalidade | Decisões que não podem ser genéricas |
|---|---|
| `atendimento_solicitado` | O que inicia e encerra o atendimento, duração, respostas incluídas e comportamento após opt-out |
| `cuidado_pastoral` | Limites do cuidado, dados sensíveis, confidencialidade, acesso por vínculo real, menores, crise e escalonamento humano |
| `tarefas_operacionais` | Tarefas permitidas, quem solicita e confirma, registros oficiais alteráveis, duração do papel e prevenção de instrução indevida |
| `comunicados` | Categorias, segmentação, frequência, horários, canais, compartilhamentos, consequência da recusa e retirada independente |

## Materialização e custódia

O template versionado contém apenas estrutura vazia. O pacote preenchido pode
conter identidade institucional, contatos, assinaturas, pareceres e outras
informações restritas. Ele deve ficar em repositório documental governado com
controle de acesso, histórico e identidade autenticada. O Git armazena somente
uma referência sanitizada, o digest da versão aprovada e os metadados mínimos
necessários para rastreabilidade.

Na D2B2b3A, o Console Master pode persistir somente o schema fechado de
rascunho operacional permitido pelo contrato sucessor. Esse material é
separado do `decision_payload` e não é promovido automaticamente. O tenant e o
ator são derivados no servidor,
o e-mail do operador não é autoridade nem configuração versionada e toda
finalidade permanece `DRAFT_NOT_APPROVED`. Hipóteses jurídicas, declaração de
operação baseada em consentimento, decisão sobre menores, atestados, pareceres,
aprovações, digest atestado e registros nominais não são editáveis pelo Master.

A implementação integrada e inativa não prova o wiring do banco. No baseline
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`, o preflight PROD somente leitura
confirmou `DATABASE_URL` presente e `M06_MIGRATION_DATABASE_URL` ausente.
`current_user` e `session_user` convergiram para a mesma identidade sanitizada;
a role runtime possui `NOSUPERUSER`, `BYPASSRLS`, `LOGIN` e `INHERIT`, é owner
de `public.igrejas` e `public.app_users` e possui `SELECT` e `REFERENCES`
efetivos nessas tabelas-pai. A tabela alvo D2B2b3A, o validator e a própria
`public.schema_migrations` estavam ausentes. Isso comprova identidade, ownership
e ACL do caminho runtime atual, mas não o comportamento da tabela futura sob
`FORCE RLS`; o caminho de migration permanece bloqueado pela ausência de
`M06_MIGRATION_DATABASE_URL` e do ledger público.

A PR #321 integrou a reconciliação documental anterior no merge
`15deaf88fd4cab5b4bebdd1435a81c8b33c2b159`; esse merge gerou o deployment
automático Vercel frontend Production `6141449639`, com `SUCCESS`, em
2026-08-28T12:53:35Z. Essa metadata prova somente o frontend, sem provar backend,
banco ou Supabase. O preflight VPS em si não executou deploy manual ou do
backend, migration, restart ou alteração da flag.

Nenhum texto jurídico plausível, contato pessoal, assinatura ou parecer deve
ser usado como exemplo no template. Nenhum processo de runtime lê o template
ou o pacote preenchido como autoridade.

## Estados, aprovações e elegibilidade

O template permanece `DRAFT_NOT_APPROVED`, com `controller_approved=false`,
`human_packet_complete=false`, `catalog_ready=false` e
`writer_eligible=false`. Uma futura governança poderá avançar somente pelas
transições fechadas do template:
`DRAFT_NOT_APPROVED`, `FACTS_ATTESTED`, `PRIVACY_REVIEWED`,
`CHANGES_REQUIRED`, `CONTROLLER_APPROVED`, `CATALOG_BOUND`, `REJECTED`,
`SUSPENDED`, `EXPIRED` e `SUPERSEDED`.

O estágio humano exige registros digest-bound do dono factual, revisão de
privacidade ou encarregado, jurídico quando designado e decisão final do
representante autorizado do controlador. Segurança ou arquitetura e o
verificador técnico independente passam a ser obrigatórios para
`writer_eligible`, depois de uma futura implementação.

`human_packet_complete` é derivado de completude, ausência de pendência ou
incerteza, digest válido, status `CONTROLLER_APPROVED`, quatro registros
humanos vinculados, decisão sobre menores, vigência e retenção. Esse resultado
não torna o catálogo utilizável. `catalog_ready` exige ainda uma entrada de
catálogo presa ao digest aprovado, contrato de evidence store implementado e
autorização técnica separada. `writer_eligible` exige
`consent_based_operation=true`, status `CATALOG_BOUND`, os seis registros
nominais vinculados, evidência implementada, binding server-side, recibo
idempotente durável e outra autorização técnica. Qualquer valor diferente de
`true` em `consent_based_operation` força `writer_eligible=false` e proíbe
`concedido` nesta fatia.

Os status `CHANGES_REQUIRED`, `SUSPENDED` ou qualquer alteração material não
reabrem o payload já atestado. A correção nasce como novo pacote em
`DRAFT_NOT_APPROVED`, com `supersedes_content_digest` apontando para a versão
anterior; a versão anterior segue auditável e pode ser marcada `SUPERSEDED`.

Continuam bloqueados:

- catálogo imutável e evidence store;
- qualquer writer de `concedido`;
- API e painel do tenant, API ou painel de aprovação, WhatsApp, webhook, worker,
  LangGraph e tools;
- qualquer migration posterior ao artefato draft-only da D2B2b3A e qualquer
  aplicação desse artefato em Supabase DEV ou PROD;
- deploy, ativação do agente e canário;
- D2C, memória, conhecimento e outbox;
- Universidade da Vida e Capacitação Destino.

A única abertura integrada no código é a persistência, API e aba de painel do Console Master para
criar e atualizar rascunhos por igreja, sem transição de estado, aprovação,
registro nominal ou caller operacional.

## Critério de conclusão do gate humano

O gate só termina quando os quatro pacotes da instância estiverem completos,
sem condição pendente, vinculados ao controlador e às operações reais,
atestados pelo dono factual, revisados pela função de privacidade ou pelo
encarregado e pelo jurídico quando designado, e aprovados pelo representante
autorizado do controlador. Todos os registros devem referenciar o digest exato
do conteúdo.

Mesmo após isso, catálogo, evidence store e writer exigirão uma PR técnica
separada, testes adversariais e nova autorização. O pacote aprovado será
insumo governado, nunca autoridade direta do runtime.

## Próximo gate único

Desenvolvida e comprovada offline sobre a base
`b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, a implementação foi integrada
pela PR #323. `bootstrap-ledger` é separado de `harden-ledger`, com
confirmação literal `BOOTSTRAP_LEDGER` e destino somente por
`M06_MIGRATION_DATABASE_URL`. Em PostgreSQL 17 ele cria atomicamente apenas o
ledger vazio `public.schema_migrations`, no contrato exato owner-only com RLS,
policy deny e ACL mínima. Homônimos, grants, default privileges, membership,
ownership ou forma física divergentes abortam e revertem; a reaplicação exata é
um no-op.

A prova terminou com 42/42 testes unitários, 87/87 em PostgreSQL 17-alpine
descartável em duas execuções independentes, 87/87 em Supabase PG17 17.6.1.159
descartável em duas execuções independentes e revisão de segurança `GO`. A
suíte RLS completa, em execução serial limpa no PostgreSQL 17 descartável,
passou em 326/326, com 3803 deselecionados e 2 warnings preexistentes, em
162.77s. A suíte offline integral foi interrompida após 5 min sem saída ou
progresso; o resultado é `INCONCLUSIVO`, não verde nem falha e não foi
reclassificado. Os workflows Backend Tests da PR #323 e do pós-merge concluíram
com `SUCCESS`. O bootstrap não descobre o catálogo,
não lê ou altera `supabase_migrations`, não reconcilia, não faz backfill e não
aplica ou registra migration. O ledger vazio preserva o bloqueio técnico de
`status` e `apply` até uma reconciliação histórica humana formar o prefixo
íntegro do catálogo, com no máximo uma migration pendente.

O `bootstrap-ledger` está integrado em `main`, mas continua não aplicado. A PR
#323, HEAD `74d3f2d87a7ffad501432b2d9fc4163bd3b4ada4`, foi integrada pelo
merge `3a5789c784017ab15a43e28c4270d25af8618359` em
`2026-08-28T15:24:58Z`; seus cinco workflows e os cinco pós-merge concluíram
com `SUCCESS`. A Vercel registrou o Preview automático frontend `6143773477`,
com `SUCCESS`, em `2026-08-28T15:22:43Z`, e o Production automático frontend
`6143819601`, com `SUCCESS`, em `2026-08-28T15:25:43Z`. Essas metadatas provam
somente o frontend, sem provar backend, banco ou runtime. Não houve deploy
manual ou do backend, acesso aos bancos DEV ou PROD, bootstrap ou migration
compartilhada, restart ou alteração de credencial, flag, runtime, agente ou
canário. O preflight PROD e o deployment automático frontend da PR #321
continuam como evidência histórica separada.

O pacote deny-state versionado e o verificador stdlib separado do runner,
desenvolvidos e comprovados offline sobre a base auditada
`cfeba13c0a9d08288f8c956ee2f35ddc1c0c35b7`, foram integrados pela PR #325,
HEAD `d9595c3958fec98a875d15de2b6647d6b1de435e`, no merge
`ab7d09f07db96d5c63a2cc32dddf3f910e23bac2` em
`2026-08-28T20:18:08Z`, conforme
[`2026-08-28-migration-history-reconciliation-contract.md`](2026-08-28-migration-history-reconciliation-contract.md).
O estado é `INTEGRADO / COMPROVADO OFFLINE / DECISÕES HUMANAS PENDENTES / NÃO
APLICADO`. Nenhuma decisão humana está aprovada. A integração não acessou DEV
ou PROD, não materializou inventário de ambiente e não reconciliou nenhum ledger. O
verificador não acessa banco, rede, ambiente ou variáveis de ambiente, não
executa SQL, DML ou escrita e não infere migration aplicada. Os ledgers nativo
e público permanecem independentes e todo sucesso estrutural conserva
`OPERATIONAL_AUTHORIZATION=BLOCKED`.

Os cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. A
Vercel registrou o Preview automático frontend `6147914118`, com `SUCCESS`, em
`2026-08-28T20:16:00Z` no HEAD, e o Production automático frontend
`6147952424`, com `SUCCESS`, em `2026-08-28T20:18:55Z` no merge. Essas metadatas
provam somente o frontend, sem provar backend, banco ou runtime; não houve
deploy manual ou do backend, migration, bootstrap, hardening, restart, flag ou
runtime nesta missão.

A prova local preservada é `98/98` testes do verificador, `26/26` testes
documentais e `42/42` testes offline do runner: agregado de
`166 passed/45 skipped`. O template deny-state terminou bloqueado com exit `8`.

O capturador e o materializador foram integrados pela PR #327, HEAD
`c4f7a25b81a8091a0d74783c816a168bb7adf44d`, no merge
`f9201a06495fad138e313e4149ad9275ff896900`. A PR #328 integrou o hotfix, HEAD
`2cbdfaf39ae11d984f0aa27dfcf0910c25984840`, no merge
`04e5c1720bf89313718c4159a2ac9d0eeeed3c25`. O catálogo de base
`656d1d9eebe90ad4b2cbb35c21939a6796c46bfe` contém 75 migrations e digest
`84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`; o SQL
allowlisted tem SHA-256
`8b589e5dda722691fead34cbd63cab75a7a22f32e0cf4bdfe64d6cef603866ee`.

O estado é `INVENTÁRIOS DEV E PROD CAPTURADOS / REVISÃO INDEPENDENTE BLOQUEADA
CONCLUÍDA / DECISÃO OWNER-01 REGISTRADA / NÃO APLICADO`. Em PostgreSQL 17, DEV registrou
33 linhas no ledger público e 6 no nativo em
`2026-08-28T22:43:11.454382Z`; PROD registrou o ledger público
`ABSENT_CONFIRMED`, com 0 linhas, e 32 linhas no nativo em
`2026-08-28T22:47:43.965243Z`. `native.name` permaneceu sempre `null`. Os dois
pacotes estão em `EVIDENCE_CAPTURED_UNREVIEWED`; cada verificação terminou com
exit `8`, `HUMAN_EVIDENCE_BLOCKED`, e a checagem conjunta terminou
`CROSS_PACKAGE_OK`. A matriz focal offline pós-captura passou com `163 passed,
2 skipped` em `1.40s`; isso não é suíte integral nem reexecução PostgreSQL.

A captura ocorreu somente em leitura e não executou DML, runner,
`bootstrap-ledger`, `harden-ledger`, `status`, `apply`, deploy, flag ou runtime.
Os seis artefatos permanecem bloqueados e não provam decisão humana, migration
aplicada, prefixo reconciliado ou autorização operacional.

A PR #329 integrou e versionou os seis artefatos, com HEAD
`c5ae430aa865dbd6371953d43e4a4447ca8e6618`, no merge
`341f38a7f1c6993c74d85e99748cb60046cd4501` em `2026-08-29T00:04:50Z`. Os
cinco workflows da PR e os cinco pós-merge concluíram com `SUCCESS`. O merge
gerou o deployment automático Vercel frontend Production `6150482852`, com
`SUCCESS`, em `2026-08-29T00:05:33Z`. Essa metadata prova somente o frontend,
sem provar deploy manual ou do backend, banco ou runtime. A integração versiona
a evidência sanitizada já capturada, mas não revisa os inventários, não aplica
migration e não libera o runner ou qualquer autorização operacional.

A revisão de `REVIEWER-01`, vinculada pelo SHA-256
`18ec23b3634ae591e771c9df2e2b6d3c44f69f72e6e2bbd854fbb1fc0fb0b133`,
bloqueou DEV por divergência do ledger e PROD por evidência insuficiente.
`OWNER-01` aceitou o bloqueio no registro externo de SHA-256
`0c2e46025b2650eea089777d17cebe5c566fb3d6ed9b68b4f9a1b5e049c59240`,
manteve `operational_authorization=false` e autorizou somente a proposta
técnica offline. Os registros externos não foram versionados e os pacotes
continuam bloqueados.

O manifesto estático de expectativas da fonte foi criado sobre a base
`7f18f7e8b44cd50e6f6033867fb97bfa9eb9c9e6`. Ele fixa 75 migrations e o
digest `84ddbdb1a858c46e4cd6086698d4738574293fa4b72e122e413557a608f9097f`,
mas declara `SOURCE_LEVEL_EXPECTATION_ONLY`: não prova o schema final de DEV ou
PROD. O verificador terminou em
`SCHEMA_EXPECTATION_MANIFEST_VERIFIED_SOURCE_ONLY`, com
`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`ENVIRONMENT_ATTESTATION_COMPLETE=false`. A revisão técnica foi feita pelo
mesmo executor e não é independente.

A derivação canônica foi reproduzida e verificada somente offline, duas vezes,
em PostgreSQL 17 descartável, sobre a base
`07d2c05c687d1a0e8deeacbb7f8b16fbdd0e4e86`. As execuções A e B produziram os
mesmos 388390 bytes, o SHA-256
`7040a54d80c0ee4f37e1986ff0a579db275e45c129f4fdafcd66788e22a3eb3e` e o
fingerprint `8ac17d4352a77fb3c5885f9c1a55813a5b7dfcd6fb84c4bd4e9117c1c7883370`.
A evidência e os limites estão na
[`decisão de derivação offline`](2026-08-29-offline-canonical-schema-derivation.md).
Isso não atesta DEV, PROD, Data API ou Realtime; `OPERATIONAL_AUTHORIZATION=BLOCKED`
permanece obrigatório.

A PR #334, HEAD `a864730f0b678cca39cebfa6bb378243ba031cd6`, foi integrada no
merge `c8427b1a505c0aad2a5f675d3bf456ee33716690`; o Git registra
`commit date=2026-08-29T21:21:15Z`, e o GitHub registra
`mergedAt=2026-08-29T21:21:16Z`. Os seis checks da PR e os seis pós-merge
concluíram com `SUCCESS`; os detalhes da API do deployment automático Vercel
frontend Production `6160229001` estão na evidência detalhada em
[`decisão de derivação offline`](2026-08-29-offline-canonical-schema-derivation.md).
Os checks provam apenas o comportamento exercitado naquele SHA; a metadata do
deployment prova somente o frontend e não prova backend, banco, migration,
runtime ou atestação de ambiente.

A ferramenta separada de atestação read-only foi implementada no commit técnico
`be958ce96e65d3d497923b7f5f912676634e9587`, sobre a base
`1072e6a8e85d201a1c82f37a8ddeac5417300c49`. A prova focal offline passou em
`81/81`, a seleção relacionada terminou em `367 passed, 47 skipped` e a prova
focal em PostgreSQL 17 TLS descartável passou em `82/82`. Sarah/Terra concluiu
`GO`; o healthcheck do Claude Opus passou, mas a revisão completa travou com
`Execution error` e não foi reclassificada como revisão concluída.

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

O tooling integrado permanece fail-closed, conforme a
[`decisão de atestação read-only`](2026-08-30-read-only-environment-attestation-tooling.md).
Nenhum DEV ou PROD foi consultado e nenhum artefato ambiental foi produzido.
O schema JSON valida somente o envelope; o verificador Python continua
obrigatório. O HMAC serve para correlação e anti-swap, sem substituir
autorização humana nem observar diretamente o project ref. Data API e Realtime
permanecem `PLATFORM_SURFACES_UNATTESTED`.

`OPERATIONAL_AUTHORIZATION=BLOCKED` e
`environment_attestation_complete=false` permanecem invariantes. Runner, DML,
migration, reconciliação, backfill, deploy, flag e runtime continuam
bloqueados.

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
[`diagnóstico do preflight de identidade de DEV`](2026-08-30-dev-identity-preflight-diagnostics.md).
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

Sobre a base `3685bbcaf11d5a20b3492953d897cb6a459701a8`, o candidato
pré-merge adiciona o enum estático `PREFLIGHT_FAILURE_PHASE` com dez valores:
`PRECONNECT_GUARDS`, `CONNECT_TLS_AUTH`, `SERVER_VERSION`, `SESSION_GUARDS`,
`IDENTITY_VALIDATION`, `ROLLBACK`, `CURSOR_CLOSE`, `CONNECTION_CLOSE`,
`POSTCONNECT_TLS_CA_REVALIDATION` e `POST_IDENTITY_FINALIZATION`. A fase é
somente a última fronteira operacional iniciada, nunca a causa; em especial,
`CONNECT_TLS_AUTH` não prova nem separa rede, TLS ou credencial. Cada saída
`BLOCKED` contém exatamente uma linha de fase, o sucesso não a contém e a
primeira falha vence quando há falhas posteriores.

Os SHA-256 congelados são runner
`8da631fbb602488bb8c82ce1529c9d8ba17acbae8a318ea9b0fc24cdd8f65cd2`,
unitários `c55726f0ad8abf7680de868cba155388f7e56773aa8054e556be89dc87aa90a8` e
PG17 `d86037d759d254581d2259026585ac768e4b2d68595473371ec65daf6c6de5a9`.
Passaram `109 passed, 2 skipped` offline, `2/2` em PostgreSQL 17 TLS
descartável e `222 passed, 2 skipped` no agregado relevante; `pycompile` e
`diff-check` ficaram verdes, os recursos temporários foram removidos e Sarah
concluiu `GO`, sem P0, P1 ou P2. As duas execuções DEV históricas com exit `7`
não podem ser retroclassificadas. A única `query_logs` anterior retornou vazio
e continua `EVIDENCE_INSUFFICIENT`. Esta missão não repetiu a consulta e não
acessou DEV ou PROD. A evidência detalhada está na
[`decisão de fase sanitizada`](2026-08-30-dev-preflight-failure-phase-diagnostics.md).

O enum sanitizado foi integrado pela PR #344 no `main`
`bab031a7e0067a257eedb4a24c786cc925801463`. Em `2026-08-31`, uma terceira e
única invocação DEV `PROCESS_INVOCATION_ONLY` nesse `main` terminou com exit
`7`, `RESULT=BLOCKED_DATABASE_PREFLIGHT_FAILED` e
`PREFLIGHT_FAILURE_PHASE=CONNECT_TLS_AUTH`. A autorização era válida entre
`2026-08-31T11:03:30Z` e `2026-08-31T11:18:30Z`; essa janela não é o horário
da execução. O timestamp operacional preciso não foi preservado nem inferido.
DNS, TCP, TLS, CA, senha, autenticação, endpoint, disponibilidade, conexão,
transação e identidade permanecem `UNKNOWN`. A autorização foi consumida;
nenhum log foi consultado e não houve retry, captura, materialização, DML,
migration, backfill, deploy, flag, runtime ou acesso a PROD.
A limpeza removeu o diretório temporário de autorização, o launcher e a
worktree operacionais temporários; o checkout ficou limpo, sem `__pycache__` ou
`.pyc`, e o registro Git obsoleto da worktree foi removido.

O probe para separar somente DNS, TCP e TLS foi preparado offline e permanece
`execution_disabled=true`; ele não foi executado e não possui autorização viva.
O contrato e os limites estão na
[`decisão de 2026-08-31`](2026-08-31-dev-connect-tls-auth-transport-probe.md).
`OPERATIONAL_AUTHORIZATION=false` e `NEXT_STAGE_AUTHORIZED=false` permanecem
obrigatórios.

O gate único corrente é
`REVIEW_AND_CI_DEV_CONNECT_TLS_AUTH_OFFLINE_DIAGNOSTICS_PR`. Ele autoriza
somente abrir e revisar a PR offline e executar o CI do mesmo SHA. Não
autoriza merge nem integração. O merge em `main` e qualquer deployment
automático frontend Vercel Production exigem autorização humana posterior
específica que nomeie e aceite ambos. Execução do probe, retry, nova invocação
DEV, DNS, TCP, TLS, senha, autenticação, logs, banco, SQL, captura,
materialização, DML, migration, reconciliação, backfill, deploy, flag, runtime
e PROD continuam bloqueados.

A PR #320 já integrou a D2B2b3A no merge
`947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`; o deployment automático
Vercel frontend Production `6140373952` ficou `SUCCESS`, sem provar backend,
banco ou Supabase. Esta missão não aplicou a migration D2B2b3A; DEV e PROD
confirmaram a ausência. A flag
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permanece `false`. O preflight VPS
em si não executou deploy manual ou do backend, migration, restart, alteração da
flag ou outra mutação de estado.
