# D2B2b2: contrato do pacote de decisão de consentimento

Data: 2026-08-28

Status: `TEMPLATE_ONLY / NOT_APPROVED`

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

## Estado anterior confirmado

A PR #318, HEAD `ede4797003e044f582da9f9a3ab86554f708a73a`, foi integrada no
merge `74951828f48994622a112d8e59eb978e5fb4f406`. A D2B2b1 permanece
inativa, sem migration ou caller. Ela exige chave idempotente opaca gerada no
servidor, aplica autorização deny-first e recusa `concedido` antes de I/O.

Os indicadores abstratos de escopo ainda não substituem um builder
transacional vinculado a tenant, ator, Pessoa e recurso canônico. Retry entre
processos continua bloqueado até existir recibo durável autenticado. Nada
nesta decisão conecta catálogo, evidence store, writer, API, painel,
WhatsApp, LangGraph, banco ou Supabase.

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
- API, painel, WhatsApp, webhook, worker, LangGraph e tools;
- migration ou aplicação em Supabase DEV ou PROD;
- deploy, ativação do agente e canário;
- D2C, memória, conhecimento e outbox;
- Universidade da Vida e Capacitação Destino.

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

Materializar uma instância governada do template por igreja, com quatro pacotes
independentes, e obter o atestado do dono factual, a revisão de privacidade ou
do encarregado, a revisão jurídica quando designada e a decisão final do
representante autorizado do controlador, todos vinculados ao digest exato de
cada pacote, sem iniciar catálogo ou writer.
