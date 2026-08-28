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

Sobre a base `b43ad92028374fa6763ef10f5eb7a379afd3e7a2`, este delta
implementa e comprova offline `bootstrap-ledger`, separado de `harden-ledger`, com
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
progresso; o resultado é `INCONCLUSIVO`, não verde nem falha, e o workflow
Backend Tests da PR permanece gate. O bootstrap não descobre o catálogo,
não lê ou altera `supabase_migrations`, não reconcilia, não faz backfill e não
aplica ou registra migration. O ledger vazio preserva o bloqueio técnico de
`status` e `apply` até uma reconciliação histórica humana formar o prefixo
íntegro do catálogo, com no máximo uma migration pendente.

Esta missão não acessou DEV ou PROD, não aplicou bootstrap ou migration em
ambiente compartilhado, não provisionou credencial, não fez deploy ou restart
e não alterou flag, runtime, agente ou canário. O preflight PROD e o deployment
automático frontend da PR #321 continuam como evidência histórica separada.

Implementar e testar somente offline, sem acessar DEV ou PROD, uma PR
versionada de reconciliação histórica humana. Ela deve definir pacote
sanitizado e verificador somente leitura, sem DML e sem inferir migrations
aplicadas, para comparar futuramente o catálogo local com inventários
autorizados dos ledgers público e nativo. Toda divergência ou evidência ausente
permanece bloqueante; a PR não cria, altera ou preenche ledger e não autoriza
`bootstrap-ledger`, `harden-ledger`, `status` ou `apply` em ambiente
compartilhado. Painel do tenant, aprovações, catálogo, writer, migration
D2B2b3A, flag, D2C, credencial, wiring, deploy, restart, runtime, ativação e
canário continuam bloqueados.

A PR #320 já integrou a D2B2b3A no merge
`947d891c2ea278b7a3231fecd9ca1c90cfe29a1f`; o deployment automático
Vercel frontend Production `6140373952` ficou `SUCCESS`, sem provar backend,
banco ou Supabase. Esta missão não aplicou a migration D2B2b3A; DEV e PROD
confirmaram a ausência. A flag
`PURPOSE_CONSENT_GOVERNANCE_DRAFTS_ENABLED` permanece `false`. O preflight VPS
em si não executou deploy manual ou do backend, migration, restart, alteração da
flag ou outra mutação de estado.
