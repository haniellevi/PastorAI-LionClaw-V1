# Pacote de decisão de tratamento e consentimento: finalidade `tarefas_operacionais`

> **Natureza:** artefato interno de governança do Igreja 12 / PastorAI  
> **Estado:** `DRAFT_NOT_APPROVED`  
> **Autoridade de runtime:** inexistente  
> **Efeitos operacionais:** bloqueados  
> **Escopo:** uma finalidade, uma versão e uma igreja por materialização

## 0. Objeto, alcance e leitura obrigatória

Este documento define o conteúdo de governança proposto para o tratamento de
dados pessoais na finalidade `tarefas_operacionais` do Igreja 12 / PastorAI,
plataforma SaaS multitenant de gestão pastoral com interfaces web, WhatsApp,
inteligência artificial e integrações de terceiros.

O pacote disciplina apenas operações opcionais e delimitadas de organização de
células, presença, visitantes, agenda, consolidação objetiva, tarefas e
processos de Enviar ou multiplicação. Ele não cobre atendimento solicitado,
cuidado pastoral, comunicados, cobrança, emergência ou qualquer outra
finalidade. Cada finalidade exige instrumento próprio e não pode aproveitar a
manifestação registrada para `tarefas_operacionais`.

Este texto é uma versão completa de conteúdo, mas ainda não é uma instância
materializada para uma igreja. Identidade institucional, configuração real,
contratos, regiões de processamento, responsáveis e evidências variam por
tenant e devem ser obtidos das fontes documentais indicadas neste pacote. A
ausência ou divergência de qualquer fato obrigatório produz falha fechada.

Nenhum trecho deste arquivo, isoladamente ou em conjunto, concede autoridade
ao catálogo, ao evidence store, ao writer, ao ledger, ao WhatsApp, ao painel,
à API, ao worker, ao LangGraph, a tools, a banco compartilhado ou a qualquer
outro componente de runtime.

## 1. Metadados de governança

| Campo | Valor ou regra vinculante |
|---|---|
| `schema_version` | `d2b2b2/v1` |
| `payload_schema_version` | `d2b2b2/decision-payload/v1` |
| `artifact_kind` | `purpose_consent_decision_packet` |
| `purpose` | `tarefas_operacionais` |
| `document_version` | `1.0.0-draft.1` |
| `notice_version` | `TO-BR-PT-v1.0.0` |
| `language` | `pt-BR` |
| `purpose_status` | `DRAFT_NOT_APPROVED` |
| `controller_approved` | `false` |
| `human_packet_complete` | `false` |
| `catalog_ready` | `false` |
| `writer_eligible` | `false` |
| `consent_based_operation` | `true` |
| `runtime_authority` | `false` |
| `operational_authorization` | `false` |
| `next_stage_authorized` | `false` |
| `minor_applicability_status` | `APPLICABLE` |
| `content_digest` | `null`, pois ainda não existe `decision_payload` materializado e congelado para um tenant |
| `supersedes_content_digest` | `null`, pois esta é a primeira versão documental desta finalidade |
| `facts_attested_at` | `null`, porque os fatos por tenant ainda não foram atestados |
| `approved_at` | `null`, porque o pacote não foi aprovado |
| `effective_at` | `null`, porque o pacote não está vigente |
| `review_due_at` | `null`, a data somente nasce após eventual vigência |
| `runtime_effects` | `BLOCKED` |
| `source_repository_sha` | `37992722c6299116d1fdb3adb78718a92dae134b` |
| `normative_reference_date` | `2026-09-05` |
| `next_gate` | `OWNER_AUTHORIZE_REVIEW_CONSENT_PACKET_TAREFAS_OPERACIONAIS` |

O valor `consent_based_operation=true` classifica o desenho proposto desta
finalidade. Ele não equivale a consentimento concedido por qualquer pessoa e
não altera os demais indicadores. Enquanto `writer_eligible=false`, todo
evento `concedido` permanece proibido.

### 1.1 Cardinalidade e materialização por tenant

Cada igreja terá uma instância independente. Não existe aprovação global que
substitua a materialização por tenant.

| Campo materializado | Regra obrigatória de preenchimento |
|---|---|
| `package_id` | UUID opaco gerado pelo servidor após vinculação ao tenant; não deriva de nome, telefone, mensagem ou documento civil |
| `package_version` | Versão semântica imutável; a primeira materialização usa a versão aprovada a partir deste rascunho |
| `tenant_binding` | `igreja_id` canônico selecionado e validado no servidor; nunca aceito do modelo, da mensagem ou de campo livre do cliente |
| `controller_identity_and_institutional_contact` | Denominação e contato institucional da igreja controladora, conforme cadastro e documento real vigentes |
| `platform_operator_identity` | Identidade da pessoa ou entidade que explora a plataforma na data da materialização, conforme instrumento contratual vigente |
| `privacy_contact` | Canal institucional monitorado, exibido ao titular e capaz de receber solicitações e comunicações da ANPD |
| `notice_location` | Endereço permanente e autenticável no domínio oficial da igreja ou da plataforma, vinculado ao tenant e à versão |
| `transfer_notice_location` | Endereço permanente do inventário de destinatários, países ou regiões e mecanismos aplicáveis ao fluxo real |
| `controller_authority_ref` | Referência opaca ao registro que comprova os poderes da pessoa que representa a igreja, mantida fora deste arquivo |

Se qualquer campo obrigatório não puder ser obtido de uma fonte real, a
materialização mantém `purpose_status=DRAFT_NOT_APPROVED` e todos os efeitos
continuam bloqueados.

### 1.2 Estados do contrato

Os estados possíveis do D2B2b2 são `DRAFT_NOT_APPROVED`, `FACTS_ATTESTED`,
`PRIVACY_REVIEWED`, `CHANGES_REQUIRED`, `CONTROLLER_APPROVED`,
`CATALOG_BOUND`, `REJECTED`, `SUSPENDED`, `EXPIRED` e `SUPERSEDED`. Este
documento não realiza transição. Correção de conteúdo após qualquer registro
vinculado ao digest exige nova versão, sem edição retroativa do payload
anterior.

## 2. Princípios que governam a decisão

1. **Finalidade determinada:** todo dado deve corresponder a uma operação
   específica descrita neste pacote. Reutilização incompatível é proibida.
2. **Adequação e necessidade:** coletar apenas o mínimo capaz de produzir o
   resultado operacional, preferindo contagens e referências internas a texto
   livre.
3. **Livre escolha:** recusa ou retirada não reduz participação em culto,
   célula, atividade religiosa ou atendimento humano.
4. **Transparência por camadas:** a pessoa recebe resumo no canal, aviso
   completo antes da escolha e recibo durável depois da manifestação.
5. **Não discriminação:** dado religioso não pode fundamentar constrangimento,
   punição, exclusão, publicidade, perfil comportamental ou exposição.
6. **Proteção reforçada:** dado misto ou capaz de revelar religião recebe a
   classificação mais alta presente no registro.
7. **Melhor interesse:** tratamento de criança ou adolescente é projetado a
   partir da proteção integral, da autonomia progressiva e do melhor interesse
   avaliado no caso concreto.
8. **Segurança e prevenção:** acesso mínimo, isolamento por tenant,
   criptografia, rastreabilidade sanitizada e resposta a incidentes integram o
   desenho desde a origem.
9. **Qualidade e confirmação:** extração ou sugestão de IA não altera registro
   canônico antes da confirmação de pessoa autorizada.
10. **Responsabilização:** as decisões, instruções, versões e controles devem
    ser demonstráveis sem criar um segundo acervo de conteúdo íntimo.
11. **Separação de autoridade:** conteúdo de governança, registro de escolha e
    permissão para produzir um efeito são controles distintos.
12. **Falha fechada:** tenant, identidade, idade, papel, finalidade, versão ou
    consentimento ausente, ambíguo, expirado ou divergente sempre nega o efeito.

## 3. Base normativa e controle de atualização

Este pacote foi estruturado com base nas seguintes fontes oficiais vigentes na
data de referência:

| Fonte | Aplicação ao pacote |
|---|---|
| [Constituição Federal](https://www.planalto.gov.br/ccivil_03/constituicao/constituicao.htm), art. 5º, VI, X, XII e LXXIX | Liberdade religiosa, intimidade, sigilo das comunicações e proteção de dados pessoais |
| [Lei nº 13.709/2018, LGPD, texto compilado](https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709compilado.htm) | Conceitos, princípios, bases legais, consentimento, dados sensíveis, menores, término, direitos, agentes, registros, segurança, incidentes e transferência internacional |
| [Lei nº 8.069/1990, Estatuto da Criança e do Adolescente](https://www.planalto.gov.br/ccivil_03/leis/l8069.htm) | Proteção integral, prioridade, dignidade, liberdade, crença, imagem e privacidade de crianças e adolescentes |
| [Lei nº 15.211/2025, Estatuto Digital da Criança e do Adolescente](https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2025/lei/l15211.htm) | Deveres de proteção por padrão, aferição de idade, supervisão, avaliação de riscos e mecanismos de reporte no ambiente digital |
| [Decreto nº 12.880/2026](https://www.planalto.gov.br/ccivil_03/_ato2023-2026/2026/decreto/d12880.htm) | Proteção de menores em serviços digitais, práticas manipulativas e salvaguardas de modelos de linguagem e agentes conversacionais |
| [Enunciado CD/ANPD nº 1/2023](https://www.gov.br/anpd/pt-br/assuntos/noticias/anpd-divulga-enunciado-sobre-o-tratamento-de-dados-pessoais-de-criancas-e-adolescentes) | Hipóteses dos arts. 7º e 11 para menores, sempre com prevalência do melhor interesse |
| [Resolução CD/ANPD nº 15/2024](https://www.gov.br/anpd/pt-br/canais_atendimento/agente-de-tratamento/comunicado-de-incidente-de-seguranca-cis) | Comunicação e registro de incidentes de segurança |
| [Resolução CD/ANPD nº 18/2024](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/encarregado-completo_ocultado.pdf) | Atuação do encarregado, autonomia técnica e conflito de interesses |
| [Resolução CD/ANPD nº 19/2024](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd/resolucao-cd-anpd-no-19-de-23-de-agosto-de-2024) | Mecanismos e cláusulas-padrão para transferência internacional |
| [Resolução CD/ANPD nº 32/2026](https://www.gov.br/anpd/pt-br/acesso-a-informacao/institucional/atos-normativos/regulamentacoes_anpd) | Reconhecimento de adequação da União Europeia e do alcance territorial definido no ato |
| [Lei nº 12.965/2014, Marco Civil da Internet](https://www.planalto.gov.br/ccivil_03/_ato2011-2014/2014/lei/l12965.htm) | Privacidade, segurança e guarda de registros de acesso quando a plataforma estiver no âmbito da obrigação legal |

As referências legais não eliminam a análise da operação concreta. Alteração
normativa, nova orientação da ANPD ou mudança relevante do produto aciona a
regra de mudança material da seção 13 e não modifica silenciosamente este
arquivo.

## 4. Agentes de tratamento e separação de papéis

### 4.1 Regra por operação

| Agente | Papel neste pacote | Limite |
|---|---|---|
| Cada igreja que decide a rotina pastoral | Controladora dos dados pastorais e operacionais do próprio tenant | Define finalidade, pessoas autorizadas, registros canônicos, conservação e resposta a direitos dentro de sua atuação real |
| Plataforma Igreja 12 / PastorAI | Operadora quando trata dados pastorais em nome e sob instruções documentadas da igreja | Não pode ampliar finalidade, compartilhar dados ou utilizar conteúdo pastoral em benefício próprio |
| Plataforma em contas, segurança, prevenção a abuso, cobrança e relação comercial | Controladora própria somente quando decide os meios e fins desses tratamentos | Esses fluxos ficam fora de `tarefas_operacionais` e exigem instrumentos e bases próprios |
| Pastores, líderes, consolidadores, administradores e voluntários autorizados | Pessoas que atuam sob autoridade da controladora ou da operadora | O cargo religioso ou acesso ao grupo não gera permissão automática |
| Provedores de infraestrutura, autenticação, mensageria, IA e calendário | Operadores ou suboperadores conforme a atuação real | A classificação depende de contrato, instruções, finalidade, região e capacidade decisória efetivos |

### 4.2 Fatos atuais da estrutura central

A operação central da plataforma é hoje assumida por pessoa natural e está em
transição para uma pessoa jurídica ainda em formação. Até a formalização e a
transferência documentada das relações aplicáveis, a identidade vigente em
cada contrato continua determinante. A futura pessoa jurídica não herda
silenciosamente as posições, instruções ou responsabilidades anteriores.

Esse fato não substitui a controladoria de cada igreja sobre os dados pastorais
que ela decide tratar. Também não transforma a plataforma em controladora de
todo conteúdo hospedado. O papel deve ser classificado fluxo a fluxo.

O dono factual foi indicado para acumular a função de encarregado da operação
central e a representação de decisões da própria plataforma. A acumulação não
é aceita de modo automático: a seção 17 estabelece mitigação obrigatória de
conflito. A indicação central não designa a mesma pessoa para todas as igrejas;
cada controladora deve manter seu registro e canal próprios.

### 4.3 Regras de identificação por igreja

A materialização consulta documentos e cadastros reais para obter:

- denominação vigente da igreja controladora;
- natureza da organização e dados institucionais necessários;
- pessoa com poderes vigentes para representar a controladora;
- canal institucional do controlador e canal de privacidade;
- contrato e instruções que vinculam a plataforma como operadora;
- lista de suboperadores e funções efetivamente habilitadas;
- responsáveis internos por direitos, incidentes, proteção de menores e
  segurança;
- estrutura de papéis, células, equipes e recursos canônicos do tenant.

Este arquivo não recebe números de documentos pessoais, endereço residencial,
telefone pessoal, e-mail pessoal, segredos, procurações integrais ou cópias de
documentos. O sistema de custódia mantém apenas referências opacas aos
documentos comprobatórios.

## 5. Delimitação da finalidade `tarefas_operacionais`

### 5.1 Formulação da finalidade

Permitir que a igreja controladora receba, estruture, apresente para correção,
confirme e registre dados mínimos necessários à execução de tarefas objetivas
de célula, presença, visitantes, agenda, consolidação e multiplicação, com
acesso por função, manifestação específica da pessoa, proteção reforçada para
dado religioso e confirmação humana antes de alterar registro oficial.

O termo **Enviar**, com inicial maiúscula, designa uma etapa objetiva da
Jornada G12. Ele não representa permissão para disparar mensagens.

### 5.2 Operações incluídas

| Operação incluída | Dados mínimos permitidos | Necessidade, limites e confirmação humana |
|---|---|---|
| Relatório de célula | `igreja_ref`, `celula_ref`, `reuniao_ref`, data, pessoa autorizada que reporta, totais agregados e referências individuais estritamente necessárias | Priorizar contagens. Exibir resumo estruturado e exigir confirmação do líder real ou substituto formal antes do registro canônico |
| Presença | `pessoa_ref`, `reuniao_ref`, estado de presença e instante | Não guardar narrativa, geolocalização ou motivo íntimo. A pessoa autorizada confirma a lista ou o evento individual |
| Visitante | nome mínimo, referência interna quando criada, reunião de origem, condição objetiva de primeira visita e contato fornecido voluntariamente para retorno | Não inferir adesão religiosa. O responsável confere o cadastro; sem continuidade autorizada, aplica-se o prazo curto da seção 14 |
| Decisão religiosa declarada | `pessoa_ref`, categoria objetiva escolhida, data, fonte da declaração e responsável pelo registro | É dado sensível. Nunca inferir de sentimento, oração, presença ou silêncio. A declaração deve ser repetida ou confirmada de forma inequívoca antes do registro |
| Tarefa operacional | título objetivo, recurso de origem, responsável autorizado, prazo, prioridade operacional e estado | Proibir conteúdo de aconselhamento ou crise. A atribuição com efeito sobre terceiro exige competência no recurso e confirmação do destinatário ou supervisor, conforme a regra da tarefa |
| Agenda e confirmação | `evento_ref`, data e horário, resposta de participação, responsável e estado | O titular confirma sua própria resposta; alteração de terceiro exige papel específico. Convite geral fica fora desta finalidade |
| Estágio objetivo de consolidação | `pessoa_ref`, código de estágio previamente definido, evento que comprova a mudança, data e responsável | Somente fatos enumerados. Avaliação espiritual, emocional ou disciplinar é proibida. A alteração exige confirmação do consolidador atribuído ou supervisor |
| Enviar e multiplicação | célula, pessoa candidata, critérios objetivos previamente publicados, marcos, data e decisão humana | Nenhuma promoção pela IA. A alteração final exige dupla conferência dos papéis previstos na regra de negócio |
| Extração de campos de texto | referência da mensagem, campos propostos, confiança e versão do extrator | Texto livre é transitório. O sistema mostra cada campo e exige correção ou confirmação antes de qualquer gravação oficial |
| Extração de campos de áudio | referência da mídia, transcrição transitória, campos propostos, confiança e versão do extrator | Não criar identificador de voz. A mídia e a transcrição seguem prazos curtos; a pessoa autorizada confirma antes do efeito |
| Aviso interno de tarefa | `tarefa_ref`, destinatário autorizado, prazo, estado e canal | Apenas aviso individual ou de equipe diretamente responsável. A emissão exige tarefa válida e confirmação do criador quando proativa |

### 5.3 Operações excluídas

| Operação excluída | Dados admitidos por este pacote | Regra de bloqueio e encaminhamento |
|---|---|---|
| Comunicados, broadcast, campanha, convite geral ou marketing | Nenhum | Usar pacote independente de `comunicados`; grupo, lista ou segmento não converte aviso em tarefa individual |
| Cuidado pastoral, confissão, oração ou aconselhamento | Nenhum conteúdo | Encerrar a extração operacional e encaminhar ao fluxo humano de `cuidado_pastoral`, sem copiar o relato para tarefa |
| Emergência, risco à vida, automutilação, abuso, exploração ou violência | Apenas o mínimo transitório necessário ao encaminhamento seguro, fora do ledger desta finalidade | Acionar protocolo humano específico; o consentimento operacional não condiciona medida de proteção prevista em regra própria |
| Cobrança, oferta, dízimo, cartão, conta bancária ou capacidade econômica | Nenhum | Tratar em fluxo financeiro separado, com base, acesso, retenção e fornecedores próprios |
| Saúde, vida sexual ou dado financeiro incidental | Nenhum campo canônico | Interromper classificação, ocultar o conteúdo de quem não precisa vê-lo e encaminhar somente quando houver finalidade e regra próprias |
| Localização contínua ou histórico de deslocamento | Nenhum | Bloqueio por desenho; data e local nominal do evento não autorizam rastreamento da pessoa |
| Biometria, reconhecimento facial ou voz como identificador | Nenhum | Bloqueio por desenho; áudio serve apenas como conteúdo transitório e não como identidade biométrica |
| Treinamento ou ajuste de modelo | Nenhum | Conteúdo pastoral e operacional não pode compor treinamento geral, avaliação comercial ou conjunto reutilizável |
| Perfilamento comportamental, emocional, espiritual ou publicitário | Nenhum | Proibir inferências, segmentos e pontuações dessa natureza |
| Universidade da Vida e Capacitação Destino | Nenhum | Exigem PRDs, máquinas de estado, pacotes e controles próprios antes de implementação |
| Decisão disciplinar, restrição de participação ou sanção religiosa | Nenhum | Exige processo humano próprio; esta finalidade não fornece recomendação ou prova automática para punição |

Conteúdo excluído que apareça em texto ou áudio não amplia a finalidade. O
sistema deve reduzir sua exposição, impedir a gravação em campos operacionais e
aplicar a política de descarte transitório.

### 5.4 Quem pode solicitar e confirmar

| Ação | Solicitante admitido | Confirmação exigida |
|---|---|---|
| Relatório de célula | Líder real ou substituto formal da célula | Próprio líder, substituto formal ou supervisor dentro do recurso |
| Presença e visitante | Líder real da reunião ou pessoa formalmente delegada | Pessoa com responsabilidade vigente sobre a reunião |
| Decisão religiosa declarada | Próprio titular ou pessoa que recebeu a declaração | Confirmação inequívoca do titular ou conferência da origem por pessoa autorizada, com correção acessível |
| Agenda | Próprio titular ou responsável por evento | Titular para sua resposta; gestor do evento para mudança administrativa |
| Estágio de consolidação | Consolidador formalmente atribuído | Consolidador atribuído ou supervisor do mesmo escopo |
| Tarefa operacional | Pessoa com competência sobre a equipe ou recurso | Destinatário ou supervisor, conforme o efeito |
| Enviar ou multiplicação | Liderança competente segundo regra canônica | Papéis humanos definidos na regra de negócio, com segregação de função |
| Campo sugerido pela IA | O modelo não é solicitante autorizado | Pessoa autenticada e autorizada no recurso específico |

## 6. Classificação dos dados

### 6.1 Dados pessoais comuns possíveis

- referências internas de pessoa, igreja, célula, reunião, tarefa e evento;
- nome e contato quando estritamente necessários à operação escolhida;
- papel operacional, responsável, prazo, estado e confirmação;
- faixa etária mínima para aplicar salvaguardas;
- metadados técnicos mínimos de apresentação, manifestação, segurança e
  idempotência.

### 6.2 Dados pessoais sensíveis ou capazes de revelá-los

Convicção religiosa é dado pessoal sensível pelo art. 5º, II, da LGPD. Neste
produto, também recebem proteção sensível:

- decisão religiosa declarada;
- filiação ou vínculo identificável com organização religiosa;
- presença, função, consolidação, Enviar ou multiplicação quando o contexto
  revelar convicção, prática ou pertencimento religioso;
- inferência de religião produzida a partir de mensagens, eventos ou papéis;
- qualquer registro misto que combine dado comum com informação religiosa;
- saúde, vida sexual, biometria, origem racial ou étnica, opinião política ou
  outro dado sensível que apareça incidentalmente, embora seu uso esteja fora
  desta finalidade.

### 6.3 Regra para dado misto, inferido ou incerto

O registro recebe a classe mais alta entre seus elementos e inferências
razoavelmente possíveis. Um visitante não pode ser rotulado como adepto apenas
por estar presente, mas a vinculação identificada ao evento religioso ainda
merece controles reforçados. Incerteza sobre a sensibilidade bloqueia o efeito,
aciona avaliação humana e favorece a exclusão do excedente.

## 7. Hipóteses legais deste pacote

| Classe e situação | Hipótese adotada no desenho | Condições cumulativas |
|---|---|---|
| Dados comuns nas operações opcionais incluídas | Consentimento, art. 7º, I, da LGPD | Manifestação livre, informada, inequívoca, anterior, por finalidade e demonstrável |
| Dados sensíveis, inclusive informação religiosa | Consentimento específico e destacado, art. 11, I, da LGPD | Finalidade específica, destaque real, minimização, manifestação afirmativa e possibilidade de retirada |
| Criança quando o tratamento se baseia em consentimento | Arts. 7º, I, ou 11, I, combinados com art. 14, especialmente § 1º | Melhor interesse, consentimento específico e destacado de pelo menos um dos pais ou responsável legal, esforços razoáveis de verificação e informação adequada |
| Adolescente | Art. 7º, I, ou art. 11, I, conforme a classe, sempre com art. 14 e melhor interesse | Participação do adolescente, linguagem adequada e salvaguarda adicional de responsável definida na seção 12 |

O legítimo interesse do art. 7º, IX, não se aplica a dados pessoais sensíveis,
pois não integra as hipóteses do art. 11. Ele não será usado para contornar a
necessidade de consentimento específico desta finalidade.

Autorizações genéricas são nulas nos termos do art. 8º, § 4º. Aceite de termos
gerais, silêncio, primeira mensagem, presença em grupo, permanência na igreja,
função ministerial, botão ambíguo ou opção marcada previamente não registram
consentimento.

Tratamento fundado em obrigação legal, execução contratual, exercício regular
de direitos, proteção da vida, segurança ou outra hipótese válida deve possuir
política, transparência e retenção próprias. Ele não gera evento `concedido`
para `tarefas_operacionais`. Retirada de consentimento, oposição e opt-out são
fatos diferentes.

## 8. Campos obrigatórios antes de apresentar o aviso

O aviso somente pode ser renderizado quando o servidor obtiver todos os campos
abaixo de fonte confiável do tenant. Eles não são editados pela pessoa no fluxo
de consentimento.

| Campo de renderização | Fonte e regra |
|---|---|
| Nome de exibição do controlador | Cadastro institucional vigente da igreja vinculada ao `igreja_id` |
| Contato do controlador | Canal institucional testado e monitorado |
| Canal de privacidade | Registro vigente do controlador; deve funcionar no mesmo dia da apresentação |
| Identidade da operadora | Contrato vigente da plataforma com a igreja |
| Link do aviso completo | URL oficial, versionada, acessível e presa ao tenant |
| Link do inventário de transferências | URL oficial com destinatários, países ou regiões e mecanismos do fluxo real |
| Link da política de retenção e direitos | URL oficial vinculada à mesma versão do pacote |
| Caminho de retirada no painel | Rota autenticada da própria pessoa, sem exigir contato com liderança religiosa |
| Comando de retirada no WhatsApp | Literal `RETIRAR TAREFAS`, reservado e versionado |

Ausência, falha de carregamento ou divergência entre esses campos e o pacote
impede a apresentação de opções de consentimento.

## 9. Aviso e manifestação de consentimento em português do Brasil

### 9.1 Aviso completo

O cabeçalho da tela ou da mensagem identifica, com os campos da seção 8, a
igreja controladora, seu contato institucional, a operadora, a versão do aviso
e os links permanentes. Em seguida, apresenta exatamente o texto abaixo:

> **Tarefas operacionais da sua igreja**
>
> A igreja identificada neste aviso pede sua autorização para usar o Igreja 12
> em tarefas operacionais específicas. Se você aceitar, a igreja poderá
> registrar e acompanhar, quando necessário, sua presença em célula ou evento,
> condição de visitante, decisão religiosa que você tenha declarado, etapa
> objetiva de consolidação, tarefa ou responsabilidade, agenda, confirmação e
> participação em processo de Enviar ou multiplicação.
>
> Esses dados podem revelar sua participação ou convicção religiosa. Por isso,
> são tratados como dados sensíveis e recebem proteção reforçada. A igreja deve
> usar somente os dados necessários para cada tarefa e permitir que você
> consulte e corrija o registro.
>
> O sistema pode receber texto ou áudio e usar inteligência artificial para
> propor campos organizados. A IA não decide sua fé, seu papel, sua disciplina
> ou sua aptidão e não altera registro oficial sem confirmação de uma pessoa
> autorizada.
>
> A plataforma e os fornecedores identificados no inventário de transferências
> podem tratar os dados mínimos para prestar o serviço. Quando houver
> processamento fora do Brasil, o inventário informa o destinatário, o país ou
> a região e o mecanismo aplicável. A autorização desta tela não substitui esse
> mecanismo.
>
> Você pode recusar. A recusa impede apenas as automações de
> `tarefas_operacionais` e não impede sua participação em culto, célula ou
> atividade religiosa, nem reduz cuidado pastoral ou atendimento humano. A
> igreja deve oferecer alternativa humana viável para a operação quando isso
> for necessário.
>
> Você pode retirar sua autorização gratuitamente a qualquer momento usando
> `RETIRAR TAREFAS` no WhatsApp oficial, o controle próprio no painel ou o canal
> de privacidade exibido neste aviso. A retirada bloqueia novos usos baseados
> neste consentimento e inicia a eliminação ou restrição dos dados alcançados,
> ressalvadas as hipóteses legais de conservação.
>
> Você pode solicitar confirmação de tratamento, acesso, correção,
> anonimização, bloqueio, eliminação, portabilidade quando regulamentada,
> informação sobre compartilhamentos, informação sobre a possibilidade de
> recusar, revogação e revisão de decisões automatizadas, nos termos da LGPD.
> Os canais e os prazos internos estão na política vinculada a este aviso.

### 9.2 Manifestação destacada para pessoa adulta

A interface apresenta duas escolhas com igual peso visual, mesma área, mesma
legibilidade e número equivalente de etapas. Nenhuma opção inicia selecionada.

**Escolha de aceitar**

> **ACEITAR TAREFAS OPERACIONAIS**
>
> Li o aviso `TO-BR-PT-v1.0.0`. Autorizo o tratamento dos dados comuns
> estritamente necessários às operações descritas e consinto de forma
> específica e destacada com o tratamento dos dados que revelem minha
> participação ou convicção religiosa para essa mesma finalidade. Sei como
> recusar, retirar a autorização e exercer meus direitos.

**Escolha de recusar**

> **RECUSAR TAREFAS OPERACIONAIS**
>
> Não autorizo as automações desta finalidade. Entendi que a recusa não impede
> minha participação religiosa, meu atendimento humano ou o exercício dos meus
> direitos.

O botão de conclusão usa o rótulo `CONFIRMAR MINHA ESCOLHA` e somente fica
disponível após a escolha consciente de uma das duas opções. A tela não usa
contagem regressiva, cor punitiva, dupla negativa, urgência fabricada ou caminho
mais longo para recusar.

### 9.3 Resumo inicial para WhatsApp

Antes de qualquer desafio de manifestação, enviar em conversa individual:

> A igreja identificada nesta conversa quer usar o Igreja 12 para organizar
> tarefas como presença, relatório de célula, visitante, agenda, consolidação
> objetiva e decisão religiosa que você tenha declarado. Isso pode revelar
> informação religiosa e pode envolver IA para organizar texto ou áudio, sempre
> com conferência humana antes de registro oficial. Você pode recusar sem perder
> participação religiosa ou atendimento humano. Leia o aviso completo no link
> oficial mostrado nesta mensagem. Depois responda exatamente `ACEITAR TAREFAS
> OPERACIONAIS` ou `RECUSAR TAREFAS OPERACIONAIS`.

O cabeçalho da própria mensagem mostra nome da igreja, versão do aviso, link
completo, canal de privacidade e informação sobre transferência internacional.
Uma resposta só é válida quando existe desafio ativo, individual, não expirado
e correlacionado ao mesmo tenant, pessoa, finalidade e versão.

### 9.4 Versão para painel autenticado

O painel exibe, na mesma tela e antes dos controles:

1. nome e contato institucional da igreja controladora;
2. identidade da operadora e funções dos fornecedores;
3. versão, data de publicação e finalidade específica;
4. operações incluídas e excluídas;
5. destaque para dado religioso, menores, IA e transferência internacional;
6. resumo dos prazos de retenção;
7. links permanentes para inventário, política e direitos;
8. escolhas de aceitar e recusar com igual destaque;
9. confirmação final sem opção pré-selecionada;
10. acesso ao recibo e à retirada depois do registro.

Fonte, CSS, contraste, ordem de foco e leitor de tela não podem ocultar ou
rebaixar a recusa. A autenticação identifica o ator, mas não substitui sua
manifestação afirmativa.

### 9.5 Fluxo para criança ou adolescente e responsável legal

**Aviso adequado à pessoa menor**

> Sua igreja quer usar o Igreja 12 para ajudar a organizar presença, agenda e
> tarefas da célula. Algumas informações podem mostrar que você participa da
> igreja. A inteligência artificial pode ajudar a organizar uma mensagem, mas
> uma pessoa responsável confere antes de mudar um registro importante. Você
> pode perguntar, dizer que não quer e mudar de ideia. Um responsável legal
> também recebe a explicação e participa da escolha.

**Manifestação do responsável legal**

> **AUTORIZAR TAREFAS OPERACIONAIS PARA A PESSOA SOB MINHA RESPONSABILIDADE**
>
> Recebi o aviso `TO-BR-PT-v1.0.0`, confirmei o vínculo de
> responsabilidade pelo meio indicado pela igreja e compreendi a finalidade,
> os dados comuns e religiosos, o uso limitado de IA, os destinatários, a
> transferência internacional, os prazos, a recusa, a retirada e os direitos.
> Autorizo as operações específicas descritas no aviso, observada a opinião e o
> melhor interesse da pessoa menor.

**Escolha de recusar do responsável legal**

> **RECUSAR TAREFAS OPERACIONAIS PARA A PESSOA SOB MINHA RESPONSABILIDADE**
>
> Não autorizo as automações desta finalidade. Entendi que a recusa não reduz a
> participação religiosa, o atendimento humano ou os direitos da pessoa menor.

O sistema registra a manifestação da pessoa menor em linguagem adequada à sua
idade e não usa autoridade religiosa, familiar ou emocional para induzir a
aceitação. Discordância da pessoa menor bloqueia o efeito automático e aciona
avaliação humana baseada no melhor interesse.

### 9.6 Recibo ao titular

Depois do commit confirmado, o canal apresenta:

> **Recibo de escolha sobre `tarefas_operacionais`**
>
> Sua escolha foi registrada pela igreja identificada neste recibo. O recibo
> mostra a decisão, a data e hora com fuso, o canal, a versão do aviso e um
> identificador opaco. Para retirar uma autorização, use `RETIRAR TAREFAS` no
> WhatsApp oficial, o controle próprio no painel ou o canal de privacidade
> exibido aqui. A retirada é gratuita.

O recibo nunca exibe número de documento civil, segredo, token, endereço
residencial, conteúdo de mensagem, áudio, transcrição, motivo íntimo ou
identificador interno reversível da pessoa.

## 10. Recusa, retirada e direitos do titular

### 10.1 Efeito da recusa

A recusa inicial produz os seguintes efeitos:

- não cria evento `concedido`;
- impede coleta ou novo tratamento baseado neste pacote;
- impede extração por IA e alteração de registro canônico sob esta finalidade;
- não altera consentimentos independentes de outras finalidades;
- não impede presença física, culto, célula, atividade religiosa, cuidado
  humano ou exercício de direitos;
- não pode gerar retaliação, constrangimento, exposição, classificação negativa
  ou redução de suporte;
- exige alternativa humana razoável quando a igreja precisar executar a tarefa
  sem automação.

Se uma funcionalidade específica não puder operar sem determinado dado, o
aviso deve explicar essa limitação antes da escolha e demonstrar por que o dado
é necessário. A limitação técnica da funcionalidade não pode ser transformada
em impedimento à participação religiosa.

### 10.2 Retirada ou revogação

O titular ou responsável legal pode retirar a autorização, sem justificativa e
sem custo, pelo mesmo canal usado para consentir, pelo controle próprio no
painel ou pelo canal institucional de privacidade. O fluxo futuro deverá:

1. autenticar o solicitante de modo proporcional ao risco;
2. localizar o tenant e a finalidade no servidor;
3. registrar evento `retirado` com chave idempotente opaca;
4. bloquear imediatamente novos tratamentos dependentes deste consentimento;
5. cancelar propostas e tarefas ainda não concluídas quando dependam
   exclusivamente da autorização retirada;
6. impedir que filas, retries ou checkpoints concluam efeito incompatível;
7. iniciar exclusão, anonimização ou restrição em todas as superfícies e
   fornecedores alcançados;
8. preservar apenas evidência mínima e registros cobertos por conservação
   permitida e documentada;
9. fornecer recibo da retirada;
10. manter válidos apenas os tratamentos anteriores realizados licitamente até
    a manifestação, observados pedidos de eliminação e o art. 16 da LGPD.

Retirada desta finalidade não equivale a opt-out de `comunicados`. Opt-out de
`comunicados` também não reativa, retira ou concede `tarefas_operacionais`.

### 10.3 Direitos dos arts. 17 a 22 da LGPD

O canal institucional deve permitir, conforme aplicável:

| Direito | Regra de atendimento |
|---|---|
| Confirmação da existência de tratamento | Resposta em formato simplificado imediatamente quando tecnicamente possível, sem revelar dado de outro tenant |
| Acesso | Forma simplificada imediata ou declaração clara e completa em até 15 dias, conforme art. 19 da LGPD |
| Correção | Validar a origem e corrigir o registro canônico e os derivados que reproduzam o erro |
| Anonimização, bloqueio ou eliminação de dado desnecessário, excessivo ou irregular | Aplicar a todas as superfícies e comunicar os agentes alcançados quando cabível |
| Portabilidade | Atender quando a regulamentação e a interoperabilidade aplicáveis permitirem, preservados segredos comercial e industrial |
| Eliminação de dados tratados com consentimento | Eliminar, ressalvadas somente as hipóteses do art. 16 e a conservação específica documentada |
| Informação sobre compartilhamento | Informar entidades públicas e privadas, funções, destinos e finalidades efetivas |
| Informação sobre não consentir | Explicar a possibilidade de recusa e a consequência limitada à automação desta finalidade |
| Revogação | Oferecer procedimento gratuito, facilitado e tão acessível quanto a concessão |
| Petição e reclamação | Informar os canais do controlador, dos órgãos de defesa do consumidor e da ANPD |
| Oposição | Receber e avaliar quando houver tratamento realizado sem consentimento em descumprimento à LGPD; esse fato não cria `concedido` |
| Revisão de decisão automatizada | Suspender efeito relevante, fornecer informação clara sobre critérios e procedimentos e submeter o caso à pessoa competente |

Como padrão interno, pedidos que não possuam prazo legal próprio recebem
confirmação de recebimento no mesmo canal e resposta, execução ou plano
fundamentado em até 15 dias corridos. Esse prazo interno não é apresentado como
prazo legal universal. Risco à vida, incidente em curso ou situação envolvendo
pessoa menor recebe encaminhamento humano imediato.

Identidade é verificada pelo meio menos invasivo compatível com o risco. A
verificação não pode exigir dado que o sistema não necessita para o pedido nem
revelar se outra pessoa possui registro.

## 11. Contrato de evidência de apresentação e manifestação

### 11.1 Separação de superfícies

O ledger D2B2a representa apenas eventos de estado `concedido` ou `retirado`.
O evidence store futuro demonstrará o aviso apresentado e a manifestação que
lhe corresponde. O recibo será a representação entregue ao titular. Nenhuma
dessas superfícies, isoladamente, autoriza uma ação de domínio.

A recusa inicial deve produzir recibo e evidência de escolha sem criar
`concedido`. Se o ledger não possuir estado para recusa, a projeção permanece
`ausente`, e a evidência de recusa serve para impedir novas solicitações
repetitivas dentro da vigência definida pela política de UX.

### 11.2 Campos mínimos sanitizados

| Grupo | Campos permitidos |
|---|---|
| Vínculo | `tenant_ref`, `controller_ref`, `person_ref`, `purpose` |
| Conteúdo apresentado | `package_version`, `content_digest`, `notice_version`, `language` |
| Apresentação | `channel`, `presented_at`, `timezone`, `renderer_version`, `delivery_state`, `correlation_id` |
| Desafio | `challenge_ref`, `challenge_created_at`, `challenge_expires_at`, `single_use_state` |
| Manifestação | `selected_action`, `manifested_at`, `actor_ref`, `authentication_method_ref`, `interaction_ref` |
| Menor | `age_band`, `guardian_ref`, `guardian_relation_evidence_ref`, `minor_notice_version`, `minor_view_state` |
| Idempotência | `idempotency_key`, `durable_receipt_ref`, `previous_event_ref`, `withdrawn_event_ref` |
| Integridade | versão do schema, algoritmo, resultado do digest e referência ao armazenamento imutável |

O ledger, o evidence store e o recibo não armazenam número ou imagem de
documento civil, endereço residencial, telefone em claro, texto integral de
conversa, áudio, transcrição, relatório pastoral, motivo íntimo, token,
credencial, segredo, prompt completo ou dado biométrico.

### 11.3 Regras de correlação e prova

- entrega de mensagem não prova leitura ou vontade;
- `sim`, `ok`, emoji ou reação sem desafio ativo não valem como manifestação;
- o desafio é individual, de uso único e ligado a tenant, pessoa, finalidade,
  versão e canal;
- o prazo do desafio é de 30 minutos no WhatsApp e de uma sessão autenticada no
  painel, com máximo de 30 minutos de inatividade;
- resposta após expiração inicia nova apresentação do aviso vigente;
- uma resposta encaminhada, editada ou originada de outro número ou sessão não
  satisfaz o desafio;
- o evento só é confirmado após commit atômico do estado e do recibo;
- divergência de digest, versão, identidade ou tenant nega a gravação;
- qualquer nova redação material exige novo aviso e novo digest.

### 11.4 Estado de implementação

O contrato desta seção é requisito futuro. Neste documento:

- `presentation_and_manifestation_evidence_implemented=false`;
- `durable_receipt_implemented=false`;
- `consent_writer_enabled=false`;
- `content_digest=null`.

Portanto, nenhuma manifestação pode ser coletada como `concedido` com base
neste arquivo.

## 12. Crianças, adolescentes e idade desconhecida

### 12.1 Aplicabilidade e fundamento factual

| Campo | Valor ou regra |
|---|---|
| `applicability_status` | `APPLICABLE` |
| Justificativa | O produto atende células de infância e juventude e prevê interação digital por WhatsApp, painel e IA |
| Avaliação de melhor interesse | Documento específico por tipo de fluxo, ligado ao tenant e à versão antes de qualquer materialização |
| Avaliação de riscos e impacto | Documento que mapeia riscos, medidas, responsáveis, testes, riscos residuais e revisão periódica |
| Evidência da política | Referência opaca aos documentos acima, sem conteúdo pessoal neste arquivo |
| Regra de bloqueio | Ausência, desatualização ou incompatibilidade de qualquer avaliação mantém `catalog_ready=false` e `writer_eligible=false` |

O art. 14 da LGPD exige prevalência do melhor interesse. Seu § 1º trata
expressamente do consentimento de crianças por pelo menos um dos pais ou
responsável legal. O Enunciado CD/ANPD nº 1/2023 admite as hipóteses dos arts.
7º e 11 para crianças e adolescentes, sempre subordinadas ao melhor interesse.
Para esta finalidade opcional e sensível, o produto adota proteção adicional
de participação do responsável para toda pessoa menor de 18 anos, sem afirmar
que esse formato seja exigido para todo tratamento de adolescentes.

### 12.2 Política por faixa etária

| Faixa | Regra obrigatória |
|---|---|
| Idade ou faixa desconhecida | Falha fechada para consentimento e automação. Solicitar apenas o sinal de faixa etária necessário e oferecer atendimento humano enquanto não houver confirmação proporcional |
| Criança com menos de 12 anos completos | Consentimento específico e destacado de pelo menos um dos pais ou responsável legal, esforços razoáveis de verificação, aviso infantil e registro da opinião ou objeção da criança |
| Adolescente de 12 a 15 anos | Aviso adequado, manifestação ativa do adolescente e participação confirmada do responsável legal como salvaguarda do produto |
| Adolescente de 16 a 17 anos | Aviso adequado, manifestação afirmativa do adolescente e participação confirmada do responsável legal para esta finalidade sensível |
| Pessoa com 18 anos ou mais | Manifestação própria segundo a seção 9.2; consentimento anterior prestado por responsável não é reutilizado automaticamente |

A mudança de faixa etária aciona revisão da configuração. Ao completar 18 anos,
a pessoa recebe o aviso vigente e decide por conta própria antes da continuação
das automações.

### 12.3 Aferição proporcional de idade e vínculo do responsável

O mecanismo deve:

1. começar pelo sinal menos invasivo capaz de separar as faixas necessárias;
2. preferir cadastro já verificado e referência de responsável mantida pela
   igreja a nova coleta de documentos;
3. elevar o grau de verificação apenas quando o risco concreto exigir;
4. não depender exclusivamente de autodeclaração quando houver indício de
   divergência ou efeito sensível relevante;
5. usar dado de idade exclusivamente para proteção etária e governança;
6. manter a prova detalhada fora do ledger, com acesso restrito e retenção
   própria;
7. impedir que líder, voluntário ou modelo se declare responsável legal;
8. permitir contestação, atualização de responsável e correção de faixa;
9. proibir biometria como mecanismo desta versão;
10. registrar apenas `age_band` e referências opacas no evidence store.

### 12.4 Melhor interesse e autonomia progressiva

Antes de habilitar o fluxo para menores, a avaliação deve demonstrar:

- benefício concreto da automação para a pessoa menor;
- inexistência de alternativa menos intrusiva com resultado equivalente;
- categorias e volumes mínimos de dados;
- risco de exposição religiosa, discriminação, pressão espiritual, contato
  indevido, manipulação e reidentificação;
- desenho acessível à idade, inclusive compreensão da recusa e retirada;
- supervisão adequada que não se converta em acesso indiscriminado a conversa
  privada;
- canal de ajuda e reporte compreensível pela pessoa menor;
- participação da criança ou do adolescente nas decisões que a afetem;
- possibilidade real de desligar IA não essencial;
- teste periódico das medidas e registro de risco residual.

### 12.5 Salvaguardas de IA para menores

Em conformidade com o Estatuto Digital e o Decreto nº 12.880/2026, o produto
deve:

- informar de modo claro que a interação é sintética e automatizada;
- prevenir manipulação comportamental, pressão emocional, urgência fabricada,
  escolhas enviesadas e exploração de vulnerabilidade etária ou religiosa;
- avaliar risco algorítmico à segurança, saúde e desenvolvimento físico,
  mental e psicossocial;
- bloquear análise emocional, publicidade comportamental e perfilamento;
- impedir que o modelo produza decisão sobre fé, disciplina, função, crise ou
  proteção;
- encaminhar situações de risco para equipe humana treinada, sem interrogatório
  automatizado repetitivo;
- oferecer controles de supervisão e intervenção proporcionais;
- manter mecanismo gratuito e acessível de reporte de violações;
- realizar testes de segurança específicos para prompts, memória e isolamento
  de menores.

Relato de violência, abuso, exploração, automutilação ou risco à vida sai
imediatamente deste fluxo e segue protocolo de proteção próprio. O consentimento
para tarefas não é condição para medida de proteção admitida por outra regra.

## 13. Vigência, mudança material e reaceite

### 13.1 Início, duração e revisão

Nenhum aviso desta versão está vigente enquanto `effective_at=null`. Após
eventual materialização e aprovação, o consentimento de pessoa adulta pode
permanecer ativo apenas enquanto:

- finalidade, controlador, classes de dados, destinatários e meios relevantes
  permanecem compatíveis com o aviso;
- existe vínculo operacional real;
- não houve retirada, suspensão, expiração ou substituição do pacote;
- a operação continua necessária e proporcional;
- o pacote passa por revisão de governança a cada 12 meses.

A revisão anual não renova nem extingue automaticamente o consentimento de
pessoa adulta. Após 12 meses consecutivos sem qualquer operação desta
finalidade, a retomada exige nova apresentação e nova manifestação. Para
pessoa menor, a confirmação da política ocorre a cada 12 meses, na mudança de
faixa etária ou na alteração do responsável, o que acontecer primeiro.

### 13.2 Mudança material

Exige nova versão do `decision_payload`, novo digest, nova apresentação e novo
consentimento quando afetar a escolha:

- mudança da igreja controladora ou de sua identidade institucional;
- sucessão da pessoa ou entidade que explora a plataforma quando alterar
  responsabilidades, contratos ou transparência;
- ampliação da finalidade ou inclusão de operação;
- nova categoria de dado ou inferência, especialmente sensível;
- novo público ou nova política para menores;
- novo canal, fornecedor, destinatário, país ou região;
- troca do mecanismo de transferência internacional;
- aumento de prazo de retenção ou redução material de direito;
- uso novo de IA, memória, vetor, modelo, treinamento ou decisão automatizada;
- alteração que torne a recusa mais gravosa;
- mudança de controles que eleve o risco residual.

Correção ortográfica, atualização de contato equivalente ou melhoria de
segurança que não mude finalidade, dado, destinatário, prazo, escolha ou direito
pode gerar revisão não material. A decisão, a justificativa e a comparação de
versões devem ficar registradas.

### 13.3 Regras de substituição

O payload anterior nunca é editado. A nova versão nasce em
`DRAFT_NOT_APPROVED`, aponta `supersedes_content_digest`, passa pelos mesmos
controles e somente substitui a anterior após a transição formal. Durante a
transição, ausência de manifestação na nova versão produz
`reaceite_necessario`, não `concedido`.

## 14. Retenção e descarte por superfície

### 14.1 Regra geral

Os prazos abaixo são política interna desta versão e devem ser confirmados
contra a operação, o contrato e obrigações específicas de cada tenant. O prazo
vence pelo primeiro evento aplicável, salvo conservação obrigatória
documentada. Conteúdo não recebe retenção geral de cinco anos. Esse período se
restringe à evidência mínima, aos registros de governança e ao registro de
incidente quando exigido.

| Superfície | Início da contagem e prazo máximo | Destino e controles |
|---|---|---|
| Ledger de consentimento | 5 anos após o último entre retirada, expiração, substituição ou encerramento do vínculo | Excluir ou anonimizar irreversivelmente; manter apenas referências, estado, versão, digest e instante |
| Evidence store | Mesmo prazo do evento correspondente no ledger | Excluir com prova de descarte; não conservar conversa, mídia ou documento civil |
| Mensagens usadas na tarefa | 90 dias após confirmação do registro canônico ou abandono; até 180 dias se houver divergência formal em apuração | Excluir conteúdo e anexos; preservar apenas o registro canônico necessário |
| Mídia de áudio ou imagem | 30 dias após extração e confirmação; 7 dias após abandono sem extração; até 90 dias se houver contestação formal | Excluir o objeto, miniaturas, cópias temporárias e derivados; nunca reutilizar como biometria |
| Transcrições | 90 dias após confirmação ou abandono | Excluir texto integral e trechos de cache; campos canônicos mínimos seguem prazo próprio |
| Resumos | 90 dias após substituição por registro canônico ou 180 dias de inatividade, o que ocorrer primeiro | Excluir; narrativa íntima é proibida nesta finalidade |
| Checkpoints | 30 dias após conclusão, retirada, expiração ou abandono | Excluir estado e impedir retomada; checkpoint não comprova consentimento |
| Vetores | Criação proibida nesta versão | Se houver criação indevida, bloquear uso, excluir fonte e vetor em até 72 horas e registrar o desvio sem copiar conteúdo |
| Logs de acesso à aplicação | 6 meses quando incidir o art. 15 do Marco Civil; fora dessa hipótese, 180 dias como prazo de segurança desta política | Conservar somente metadados exigidos ou necessários, sem conteúdo; excluir ao fim, salvo ordem válida |
| Logs de segurança e auditoria técnica | 12 meses após o evento | Agregar ou excluir; acesso restrito e sem payload pastoral |
| Incidentes de segurança | Mínimo de 5 anos a partir do registro do incidente, conforme Resolução CD/ANPD nº 15/2024 | Manter registro de governança minimizado, inclusive quando não comunicado; eliminar após o prazo e revisão de obrigações adicionais |
| Dead-letter | 30 dias desde a falha | Reprocessar uma única vez sob idempotência válida ou excluir; não manter payload sensível quando referência basta |
| Cache e arquivo temporário | 24 horas ou fim da execução, o que ocorrer primeiro | Purga automática, sem restauração operacional |
| Backups | Janela rolante máxima de 35 dias | Criptografar, restringir acesso, impedir uso ativo e expirar por rotação; exclusão é reaplicada após qualquer restauração |

Se um fornecedor não puder cumprir o prazo, a operação que depende dele
permanece bloqueada até mudança de arquitetura ou justificativa específica que
gere nova versão deste pacote.

### 14.2 Registros operacionais canônicos

| Registro canônico | Prazo máximo | Destino |
|---|---|---|
| Relatório de célula e presença identificada | 24 meses após a reunião | Anonimizar contagens úteis e excluir vínculos pessoais não necessários |
| Visitante sem vínculo posterior | 90 dias após o último contato operacional | Excluir identificação e contato; conservar apenas estatística realmente anônima |
| Agenda e confirmação | 12 meses após o evento | Excluir vínculo individual; conservar agenda institucional sem lista pessoal quando necessária |
| Tarefa operacional | 12 meses após conclusão ou cancelamento | Excluir conteúdo e vínculo; conservar métrica anônima quando útil |
| Estágio objetivo de consolidação | Durante o estágio e por 24 meses após encerramento | Excluir ou anonimizar histórico pessoal não necessário |
| Estado de Enviar ou multiplicação | Durante o papel e por 24 meses após seu encerramento | Excluir histórico pessoal; ato mínimo de governança pode seguir prazo de 5 anos sem narrativa |
| Registro mínimo de decisão de acesso ou papel | 5 anos após o encerramento da autorização | Excluir após verificação de obrigação adicional; não copiar conteúdo pastoral |
| Contagem verdadeiramente anônima | Enquanto houver utilidade documentada e teste periódico contra reidentificação | Excluir quando perder utilidade ou deixar de ser anônima |

### 14.3 Exclusão integral e restauração

A exclusão alcança banco, objeto, mensagem, mídia, transcrição, resumo,
checkpoint, vetor, índice, busca, cache, fila, dead-letter, log com conteúdo,
fornecedor e cópia operacional. O coordenador de exclusão mantém uma lista de
supressão minimizada para que um backup restaurado não reintroduza o uso.

Pedidos válidos devem ser propagados aos processadores alcançados em até 5 dias
úteis. A eliminação das superfícies ativas deve terminar em até 30 dias
corridos; backups expiram dentro da janela máxima de 35 dias. Impedimento
técnico ou obrigação específica deve ser registrado com escopo, fundamento,
responsável e data de nova revisão, sem manter acesso operacional ao conteúdo.

## 15. Opt-out, eliminação, legal hold e reativação

| Evento | Efeito vinculante |
|---|---|
| Recusa inicial | Projeção permanece sem concessão; o sistema não insiste durante 180 dias, salvo solicitação espontânea da pessoa |
| Retirada | Novo evento `retirado`, bloqueio de novos usos e início da cascata de exclusão |
| Opt-out global | Prevalece sobre qualquer autorização anterior para envios alcançados por sua política e nunca cria consentimento |
| Correção | Atualiza registro canônico e derivados relevantes, preservando histórico mínimo quando necessário à integridade |
| Eliminação | Exclui ou anonimiza os dados alcançados, ressalvadas apenas as hipóteses do art. 16 da LGPD e conservação excepcional válida |
| Legal hold ou conservação excepcional | Restringe somente os registros estritamente necessários por obrigação, ordem ou exercício regular de direitos documentado |
| Reativação | Exige nova manifestação afirmativa na versão vigente e novo recibo; login, mensagem, retorno à igreja ou limpeza de opt-out não bastam |

O `legal_hold` deve ter fundamento, categorias abrangidas, evento
que a iniciou, responsável, acesso restrito, revisão a cada 90 dias e condição
de encerramento. Ela não permite uso operacional, publicidade, treinamento,
perfilamento ou análise pastoral. Quando a causa termina, a exclusão suspensa é
retomada.

Reativação não recupera autorização expirada ou retirada. Propostas e tarefas
antigas incompatíveis permanecem canceladas; qualquer nova operação começa a
partir do estado atual do domínio.

## 16. Transferência internacional de dados

### 16.1 Regra por fluxo

Cada transferência internacional exige cumulativamente:

1. base válida para o tratamento no Brasil;
2. mecanismo aplicável do art. 33 da LGPD;
3. finalidade e necessidade documentadas;
4. transparência sobre destinatário, função, país ou região, dados, duração e
   transferências posteriores;
5. contrato e medidas técnicas e organizacionais adequados;
6. atendimento de direitos e propagação de correção, retirada e eliminação;
7. evidência de que a configuração real corresponde ao inventário.

Assim, a regra é **base + mecanismo + transparência**. Consentir com
`tarefas_operacionais` não autoriza, sozinho, a saída de dados do Brasil. Uma
frase genérica aceitando transferência internacional é insuficiente.

### 16.2 Mecanismo por destino

| Situação real do destinatário | Mecanismo exigido nesta política | Resultado sem comprovação |
|---|---|---|
| Entidade localizada em Estado membro da União Europeia, Islândia, Liechtenstein ou Noruega, ou instituição, órgão ou agência da União Europeia, dentro do alcance da Resolução CD/ANPD nº 32/2026 | Decisão de adequação do art. 33, I, limitada ao destinatário e ao fluxo efetivamente cobertos | Fluxo bloqueado |
| Destinatário fora do alcance de decisão de adequação | Cláusulas-padrão contratuais brasileiras da Resolução CD/ANPD nº 19/2024, incorporadas integralmente ao instrumento aplicável | Fluxo bloqueado |
| País, região, entidade contratada ou cadeia posterior desconhecida | Nenhum mecanismo presumido | Fluxo proibido |
| Consentimento genérico para transferência | Não aceito como mecanismo desta arquitetura | Fluxo proibido |

Adequação não dispensa base legal, minimização, segurança, transparência,
direitos ou controle de transferência posterior. Mudança de região ou
suboperador exige nova avaliação antes do primeiro envio.

### 16.3 Inventário de fornecedores e funções

| Fornecedor ou função | Dados ou função possível nesta finalidade | Verificações documentais obrigatórias | Estado deste rascunho |
|---|---|---|---|
| Supabase ou PostgreSQL gerenciado | Banco, storage, backup e metadados do tenant | Entidade contratada, região primária e de backup, suboperadores, DPA, exclusão, segurança e mecanismo por fluxo | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| Vercel | Entrega do painel, edge, logs técnicos e observabilidade | Regiões, campos transmitidos, logs, subprocessadores, DPA, retenção e mecanismo | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| Clerk | Identidade, autenticação, sessão e vínculo de acesso | Campos, entidade, regiões, retenção, DPA, suboperadores e separação entre autenticação e conteúdo pastoral | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| WhatsApp / Meta | Transporte de mensagens, mídia e metadados da conversa oficial | Produto e termos contratados, papéis reais, países, retenção, acesso, suboperadores e mecanismo | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| Evolution API | Ponte de mensageria, webhook, sessão e mídia | Confirmar se é auto-hospedada ou serviço de terceiro, local, operadores, logs, backups, acesso e descarte | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| OpenAI com credencial fornecida pela igreja | Texto ou áudio mínimo para extração e resposta estruturada | Entidade contratada, controles de dados, uso para treinamento, retenção, região, suboperadores, DPA, exclusão e mecanismo | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| Google Calendar | Evento, agenda, confirmação e token de integração quando habilitado | Escopos, conta controladora, dados enviados, entidade, regiões, retenção, DPA e mecanismo | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| Brevo | Eventual aviso transacional individual de tarefa | Confirmar participação real; broadcast e campanha são excluídos. Se usado, verificar entidade, região, DPA, retenção e mecanismo | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| Asaas | Cobrança e dados financeiros | Função excluída desta finalidade; nenhuma informação de tarefa operacional deve ser enviada | `NOT_APPLICABLE_TO_THIS_PURPOSE` |

O nome do fornecedor não comprova entidade contratada, localização, produto,
configuração ou mecanismo. Cada tenant materializado deve apontar evidência
contratual atual e mapear transferências posteriores. Falha de qualquer elo
mantém a integração correspondente desligada.

## 17. Direitos, incidentes e revisão periódica

### 17.1 Responsabilidades operacionais

| Função | Regra de designação e atuação |
|---|---|
| Recebimento de direitos | Canal institucional da igreja controladora, publicado no aviso e monitorado com continuidade |
| Decisão sobre direitos | Pessoa da controladora com competência e acesso apenas ao tenant correspondente |
| Apoio técnico | Equipe da plataforma na qualidade aplicável, sem decidir finalidade pastoral por conta própria |
| Encarregado | Pessoa ou serviço formalmente indicado pelo agente de tratamento, com contato público, recursos, autonomia técnica e conflito controlado |
| Incidentes | Controladora decide comunicação; operadora detecta, contém, preserva fatos e informa sem demora |
| Proteção de menores | Pessoa treinada e designada pela igreja, fora da decisão do modelo |
| Segurança | Responsável técnico com poder de conter acesso, chave, sessão, fila ou integração afetada |
| Revisão periódica | Dono factual da operação, privacidade, controladora e segurança, cada qual no próprio escopo |

### 17.2 Mitigação de conflito do encarregado

O fato atual informa que o dono factual acumula a função de encarregado da
operação central e a representação de decisões da própria plataforma. Como a
Resolução CD/ANPD nº 18/2024 admite acumulação somente quando inexiste conflito
e exige ética, integridade e autonomia técnica, a manutenção dessa estrutura
depende de controles formais:

- mapa das decisões estratégicas tomadas pela mesma pessoa;
- declaração periódica de conflito real ou potencial;
- acesso direto à direção e liberdade para registrar recomendações;
- orçamento, tempo e informação suficientes para a função;
- substituição ou segunda análise independente quando a pessoa avaliaria ato
  próprio;
- impedimento de retaliação por orientação de privacidade;
- suplência em férias, ausência ou impedimento;
- canal confidencial e registro das medidas adotadas;
- avaliação por caso concreto e substituição quando o risco não puder ser
  afastado.

Cada igreja controladora deve avaliar sua própria designação. O vínculo da
pessoa com a plataforma não a transforma automaticamente em encarregada de
todos os tenants.

### 17.3 Comunicação e registro de incidentes

A operadora deve notificar internamente a controladora imediatamente e, como
meta contratual, em até 24 horas da ciência de incidente que possa afetar dados
do tenant. O aviso interno contém fatos conhecidos, categorias, pessoas
potencialmente afetadas, medidas de contenção e lacunas, sem conclusões
especulativas.

Quando o incidente puder acarretar risco ou dano relevante, a controladora
comunica a ANPD e os titulares em até 3 dias úteis, contados do conhecimento de
que o incidente afetou dados pessoais e ressalvada legislação específica,
conforme a Resolução CD/ANPD nº 15/2024. Informação incompleta pode
ser complementada de forma fundamentada no procedimento regulatório. Todo
incidente, comunicado ou não, recebe registro mínimo por pelo menos 5 anos a
partir do registro.

Dados religiosos, dados de menores, autenticação, conteúdo de conversa e
exposição cross-tenant elevam o risco. O plano cobre detecção, contenção,
erradicação, recuperação, preservação de evidência, classificação, comunicação,
lições aprendidas e teste periódico.

### 17.4 Frequência de revisão

O pacote é revisto a cada 12 meses e também quando ocorrer:

- incidente relevante;
- mudança normativa ou orientação nova da ANPD;
- troca de controlador, operadora, fornecedor, região ou mecanismo de
  transferência;
- introdução de nova IA, memória, ferramenta ou operação;
- alteração de retenção, RBAC ou fluxo de menor;
- auditoria que encontre excesso, desvio de finalidade ou falha de exclusão;
- aumento material de escala, risco ou tipo de público.

A revisão não altera silenciosamente o payload vigente. Mudança material segue
a seção 13.

## 18. RBAC e binding no servidor

### 18.1 Matriz mínima por papel

| Papel | Escopo máximo nesta finalidade |
|---|---|
| Titular adulto | Seus próprios avisos, escolhas, recibos e registros permitidos |
| Responsável legal | Escolhas e registros permitidos da pessoa menor vinculada e somente durante a autoridade comprovada |
| Líder de célula | Reuniões e pessoas da célula real sob responsabilidade vigente |
| Consolidador | Casos formalmente atribuídos e campos objetivos necessários |
| Supervisor | Recursos pertencentes à sua descendência ou escopo formal vigente |
| Administrador da igreja | Recursos da própria igreja conforme necessidade e segregação de função |
| Suporte da plataforma | Metadados técnicos por padrão; conteúdo somente por acesso excepcional, justificado, temporário e auditado |
| Admin Master | Rascunho factual de governança permitido; sem manifestação pelo titular, mudança de estado ou acesso pastoral por padrão |
| Modelo de IA | Resultado mínimo de ferramentas tipadas; nenhum acesso direto a banco, diretório completo, papel ou configuração de consentimento |

### 18.2 Binding obrigatório

Para cada leitura, proposta ou escrita futura, o servidor deverá:

1. autenticar o ator e resolver seu acesso ativo;
2. derivar `igreja_id` da sessão confiável ou da instância Evolution vinculada;
3. rejeitar tenant, identidade, papel ou consentimento recebidos do modelo,
   mensagem, query string ou payload como autoridade;
4. resolver `pessoa_ref`, célula, reunião, tarefa e evento no backend;
5. verificar que todos os recursos pertencem ao mesmo tenant;
6. revalidar papel, capacidade, atribuição e estado do domínio no instante do
   efeito;
7. verificar finalidade, versão, projeção de consentimento e opt-out;
8. aplicar RLS e autorização de aplicação como barreiras independentes;
9. gerar idempotência e recibo no servidor;
10. gravar e confirmar somente após transação atômica;
11. retornar ao modelo apenas resultado mínimo e sanitizado;
12. falhar fechado diante de ausência, duplicidade, corrida ou divergência.

Um líder não amplia o próprio escopo digitando nome de outra célula, pessoa ou
igreja. Admin, autoria da mensagem, presença em grupo ou e-mail conhecido não
substituem capacidade específica. Suporte excepcional expira automaticamente,
exige justificativa e registra tenant, ator, recurso, motivo e instante sem
copiar conteúdo.

### 18.3 Evidência técnica exigida no gate futuro

A implementação deverá provar, no SHA exato e em PostgreSQL descartável:

- testes negativos com pelo menos dois tenants;
- GUC de tenant ausente, inválido, divergente e reaproveitamento de pool;
- RLS forçada, ACL mínima, grants e revokes explícitos;
- rejeição de autoridade enviada pelo cliente ou pelo modelo;
- corrida de idempotência e repetição sem duplicar efeito;
- retirada concorrente prevalecendo sobre proposta incompatível;
- ausência de conteúdo sensível em logs e recibos;
- rollback ou compensação sem apagar histórico material.

Neste documento, `server_side_resource_binding_implemented=false` e nenhuma
evidência técnica futura está sendo aceita por antecipação.

## 19. Recibo durável e idempotência

### 19.1 Unidade de intenção

Cada tentativa de registrar apresentação, concessão, retirada, recusa ou ação
operacional deve possuir uma chave idempotente opaca gerada por componente
confiável do servidor. A chave é vinculada internamente a tenant, pessoa,
finalidade, versão, ação e intenção, sem incorporar esses valores em texto
reversível.

Telefone, nome, texto da mensagem, ID recebido do provedor, conteúdo pastoral,
prompt ou identificador fornecido pelo modelo não podem compor a autoridade da
chave. Uma chave aceita em um tenant nunca é válida em outro.

### 19.2 Contrato do recibo

O recibo durável futuro contém:

| Campo | Regra |
|---|---|
| `receipt_ref` | Identificador opaco gerado no servidor |
| `tenant_ref` | Referência interna derivada no servidor |
| `person_ref` | Referência interna protegida |
| `purpose` | Valor fixo `tarefas_operacionais` |
| `intent_type` | Apresentação, escolha, retirada ou ação operacional enumerada |
| `package_version` | Versão exata materializada para o tenant |
| `content_digest` | Digest exato do `decision_payload` vigente |
| `idempotency_key_ref` | Referência à chave, sem expor material interno |
| `result_state` | Resultado enumerado, sem texto livre |
| `committed_at` | Instante do commit com fuso e relógio confiável |
| `previous_receipt_ref` | Referência ao evento anterior quando houver |
| `expires_at` | Prazo definido pela retenção da evidência correspondente |

O cliente recebe somente os campos necessários à compreensão e ao exercício de
direitos. O recibo não contém dado pessoal bruto, mensagem, mídia ou segredo.

### 19.3 Repetição, conflito e falha

- repetição da mesma intenção devolve o mesmo resultado confirmado;
- reutilização da chave com payload divergente falha fechada;
- ausência do recibo após falha de rede não autoriza repetir o efeito sem
  reconciliação autenticada;
- retirada prevalece sobre ação incompatível ainda não confirmada;
- dead-letter não concede permissão e não inventa nova chave;
- sucesso HTTP, resposta do fornecedor ou texto do modelo não prova commit;
- o canal informa sucesso apenas depois da persistência atômica;
- correção de histórico ocorre por novo evento, nunca por alteração silenciosa
  do evento anterior.

Neste pacote, `durable_idempotency_receipt_implemented=false`. A política está
definida, mas nenhum caller está autorizado.

## 20. Inteligência artificial, memória, derivados e isolamento por tenant

### 20.1 Dados enviados ao modelo

Somente o trecho indispensável à operação corrente pode ser enviado à IA. O
servidor deve remover ou mascarar documento civil, contato, endereço, segredo,
detalhe pastoral íntimo e contexto histórico que não contribuam para os campos
objetivos solicitados.

Cada chamada registra, sem conteúdo sensível, tenant, finalidade, operação,
modelo, versão da política, campos solicitados, instante e resultado de
segurança. A credencial OpenAI fornecida pela igreja pertence ao tenant e nunca
é compartilhada com outra igreja.

### 20.2 Limites da IA

O modelo pode propor estrutura, apontar campo ausente e resumir para
confirmação. O modelo não pode:

- escolher tenant, identidade, papel, capacidade ou estado de consentimento;
- conceder, retirar ou reativar consentimento;
- gravar diretamente no banco ou ledger;
- inferir convicção, conversão, saúde, sexualidade, crise, aptidão ou disciplina;
- promover ou rebaixar pessoa em papel religioso;
- concluir etapa de consolidação sem fato objetivo confirmado;
- decidir Enviar ou multiplicação;
- enviar mensagem externa sensível por iniciativa própria;
- transformar conversa privada em conhecimento institucional;
- usar conteúdo para treinamento geral, publicidade ou perfilamento;
- ocultar incerteza ou afirmar que uma ação ocorreu antes do commit.

### 20.3 Memória privada e conhecimento institucional

Mensagens, mídias, transcrições, resumos e checkpoints são memória privada da
conversa. Registros oficiais confirmados e documentos publicados pela igreja
formam conhecimento institucional. A promoção automática de memória privada
para conhecimento é proibida.

Uma ferramenta de dados vivos consulta serviços tipados e retorna somente os
campos necessários. Embedding ou resumo nunca substitui a fonte transacional.
Se um vetor vier a ser autorizado em nova versão, ele herdará tenant,
classificação, ACL, retenção e pedido de exclusão da fonte.

### 20.4 Isolamento e exclusão de derivados

- memória, conhecimento, índice, credencial, configuração e execução são
  separados por `igreja_id`;
- namespace, metadado de tenant e RLS devem concordar;
- busca sem tenant confiável retorna nenhum resultado;
- teste adversarial deve tentar recuperar conteúdo de outra igreja;
- toda derivação herda a classificação mais alta da origem;
- retirada ou eliminação alcança mensagem, mídia, transcrição, resumo,
  checkpoint, cache, índice, vetor e fornecedor;
- restauração de backup reaplica a lista de supressão antes de liberar acesso;
- ausência de informação oficial produz resposta de lacuna, não invenção.

### 20.5 Provedor autorizado pela arquitetura atual

O desenho documental do projeto prevê OpenAI com credencial própria da igreja.
OpenRouter não integra este pacote. Novo provedor, novo modelo com política de
dados materialmente diferente ou nova região exige inventário, avaliação de
transferência, atualização do aviso e aplicação da seção 13 antes de uso.

## 21. Aprovações nominais e registros de decisão

### 21.1 Slots do gate humano

Este documento define os slots do contrato D2B2b2, mas não contém nomes nem
registra decisão por qualquer pessoa.

| Slot | `record_ref` | `decision` | Estado atual |
|---|---|---|---|
| `operation_owner` | `null` | `null` | `NOT_RECORDED` |
| `privacy_or_dpo_reviewer` | `null` | `null` | `NOT_RECORDED` |
| `legal_reviewer_when_designated` | `null` | `null` | `NOT_RECORDED` |
| `authorized_controller_representative` | `null` | `null` | `NOT_RECORDED` |

O slot `legal_reviewer_when_designated` aceita futuramente `NOT_DESIGNATED`
somente nas condições do contrato D2B2b2. Neste rascunho, nenhuma escolha foi
registrada para o slot.

### 21.2 Slots do gate técnico futuro

| Slot | `record_ref` | `decision` | Estado atual |
|---|---|---|---|
| `security_or_architecture_reviewer` | `null` | `null` | `FUTURE_TECHNICAL_GATE` |
| `independent_technical_verifier` | `null` | `null` | `FUTURE_TECHNICAL_GATE` |

### 21.3 Contrato dos registros

Cada registro futuro deverá conter somente:

- `record_ref`;
- `recorded_by_identity_ref`;
- `attested_content_digest`;
- `decision`, limitado a `APPROVED`, `CHANGES_REQUIRED`, `REJECTED` ou
  `NOT_DESIGNATED` quando permitido;
- `recorded_at`.

As referências devem apontar para identidade autenticada e ficar fora do
`decision_payload`. Nome, documento civil, contato pessoal, credencial e prova
integral de identidade não aparecem neste arquivo. Todos os registros do mesmo
pacote devem atestar exatamente o mesmo digest.

Os quatro slots do gate humano continuam sem registro. Os dois slots técnicos
pertencem a etapa posterior e não podem ser antecipados. Consequentemente,
`controller_approved=false` e `human_packet_complete=false`.

## 22. Ficha factual por tenant

Esta ficha define fatos que devem ser confirmados por documento ou estado real.
Ela não deixa campos abertos: cada item possui fonte, regra e classificação
atual.

| ID | Fato ou campo a confirmar | Fonte exigida | Classificação atual |
|---|---|---|---|
| F-01 | O sistema é multitenant e atende igrejas de portes diversos | Arquitetura, contrato e cadastro de tenants | `OWNER_REPORTED_NOT_ATTESTED` |
| F-02 | Cada igreja decide as operações sobre seus dados pastorais | Contrato, instruções e matriz de responsabilidades do tenant | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-03 | A operação central é hoje exercida por pessoa natural e migra para pessoa jurídica em formação | Instrumentos vigentes e atos de transição quando existirem | `OWNER_REPORTED_TRANSITION_NOT_DOCUMENTED` |
| F-04 | Há crianças e adolescentes em células de infância e juventude | Configuração de público, políticas e registros agregados da igreja | `OWNER_REPORTED_NOT_ATTESTED` |
| F-05 | O consentimento atual é informal e não possui evidência correlacionada | Inventário do legado, amostra sanitizada e consulta ao schema | `OWNER_REPORTED_NO_D2B2B2_EVIDENCE` |
| F-06 | Nenhum consentimento legado será promovido por backfill | Plano de transição e testes do writer futuro | `RULE_DEFINED_NOT_IMPLEMENTED` |
| F-07 | As operações reais coincidem com a seção 5.2 | Mapeamento de processo e responsáveis de cada igreja | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-08 | Comunicado e cuidado pastoral estão separados desta finalidade | Catálogo de finalidades, UX e testes de roteamento | `RULE_DEFINED_NOT_IMPLEMENTED` |
| F-09 | Existe alternativa humana viável para quem recusa | Procedimento da igreja, responsáveis e teste de atendimento | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-10 | A política para menores atende ao melhor interesse no fluxo real | Avaliação de melhor interesse e avaliação de riscos e impacto | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-11 | A relação do responsável legal pode ser verificada proporcionalmente | Processo, controles, contestação e retenção da evidência | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-12 | O encarregado e o canal institucional de direitos estão formalmente definidos | Ato de designação, publicação do canal e teste de continuidade | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-13 | A acumulação de funções do dono factual possui conflito mitigado | Mapa de decisões, avaliação de conflito, suplência e medidas | `OWNER_REPORTED_ACCUMULATION_REQUIRES_MITIGATION` |
| F-14 | A igreja possui representante com poderes vigentes | Documento institucional e registro de autoridade | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-15 | Plataforma e igreja possuem relação controlador-operadora documentada | Contrato, anexo de tratamento, instruções e auditoria | `REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION` |
| F-16 | Fornecedores, entidades, produtos, regiões e suboperadores coincidem com a seção 16.3 | Contratos, painéis oficiais e inventário de dados atual | `REQUIRES_DOCUMENTARY_CONFIRMATION` |
| F-17 | O dono factual aceita transferência internacional somente com base, mecanismo do art. 33 por fluxo e transparência, nunca por aceite genérico | DPA, localização, cláusulas aplicáveis e aviso ao titular | `OWNER_REPORTED_DIRECTION_REQUIRES_DOCUMENTARY_CONFIRMATION` |
| F-18 | Os prazos da seção 14 são tecnicamente executáveis | Configurações, contratos, jobs de descarte e teste de restauração | `RULE_DEFINED_NOT_IMPLEMENTED` |
| F-19 | A exclusão alcança todos os derivados e fornecedores | Inventário de dados, testes de cascata e recibos de exclusão | `RULE_DEFINED_NOT_IMPLEMENTED` |
| F-20 | RBAC e binding impedem acesso cross-tenant e ampliação de escopo | Código, migration, RLS e testes adversariais no SHA exato | `FUTURE_TECHNICAL_EVIDENCE_REQUIRED` |
| F-21 | Recibo durável e idempotência resistem a retry e concorrência | Implementação, testes de corrida e reconciliação | `FUTURE_TECHNICAL_EVIDENCE_REQUIRED` |
| F-22 | O aviso renderizado corresponde ao payload e ao digest | Catálogo imutável e teste de renderização por canal | `FUTURE_TECHNICAL_EVIDENCE_REQUIRED` |

Nenhum item classificado como `OWNER_REPORTED_NOT_ATTESTED`,
`REQUIRES_TENANT_DOCUMENTARY_CONFIRMATION`,
`REQUIRES_DOCUMENTARY_CONFIRMATION`, `RULE_DEFINED_NOT_IMPLEMENTED` ou
`FUTURE_TECHNICAL_EVIDENCE_REQUIRED` pode ser tratado como fato comprovado.

## 23. Contrato do `decision_payload` e digest

### 23.1 Conteúdo imutável por finalidade e tenant

O `decision_payload` materializado deve conter, no mínimo:

| Grupo | Conteúdo |
|---|---|
| Identificação | schema, finalidade, `package_id`, versão, digest substituído e vínculo ao tenant |
| Agentes | controlador, contato institucional, operadora, suboperadores e atuação real |
| Escopo | operações incluídas e excluídas, dados mínimos, pessoas, destinatários e compartilhamentos |
| Classificação e bases | dados comuns, sensíveis, mistos e hipóteses legais separadas |
| Informação e escolha | textos exatos por canal, idioma, versão, recusa, retirada e recibo |
| Evidência | apresentação, desafio, manifestação, responsável legal e correlação |
| Menores | aplicabilidade, melhor interesse, idade, responsável, riscos e salvaguardas |
| Ciclo de vida | vigência, mudança material, reaceite, retenção, descarte, opt-out, eliminação, conservação excepcional e reativação |
| Transferência | fornecedores, funções, entidades, países ou regiões, mecanismos e transferências posteriores |
| Responsabilidades | direitos, incidentes, revisão periódica, conflito e proteção de menores |
| Segurança | RBAC, binding no servidor, idempotência, recibo, IA, memória e isolamento por tenant |

### 23.2 Algoritmo e canonicalização

| Campo | Valor |
|---|---|
| Algoritmo | SHA-256 |
| Encoding | UTF-8 |
| Canonicalização | JCS, RFC 8785 |
| Escopo | Somente um `decision_payload` imutável, de uma finalidade e um tenant |
| Schema do payload | `d2b2b2/decision-payload/v1` |
| Envelope de governança | Excluído do digest |
| Indicadores derivados | Excluídos do digest |
| Registros nominais | Excluídos do digest e vinculados por `attested_content_digest` |

A fórmula é:

```text
content_digest = lowercase_hex(
  SHA-256(UTF8(JCS(decision_payload)))
)
```

A geração rejeita chave JSON duplicada, número não representável pelo JCS,
valor não determinístico, normalização divergente e campo não previsto pelo
schema. O digest deve ser reproduzido por implementação independente antes de
ser aceito.

### 23.3 Estado atual e custódia

`content_digest=null` é o único estado correto deste arquivo porque o tenant,
os documentos institucionais, os fornecedores e as evidências ainda não foram
materializados. Um hash do Markdown não substitui o digest do payload e não
fecha qualquer gate.

Depois da materialização, o payload congelado fica em repositório documental
governado. Este repositório de código recebe somente referência sanitizada,
digest, versão, tenant opaco e indicadores mínimos. Documentos institucionais,
provas de identidade e registros detalhados permanecem na custódia apropriada,
sempre vinculados ao mesmo digest.

## 24. Indicadores, efeitos e invariantes

### 24.1 Indicadores atuais

```text
purpose_status=DRAFT_NOT_APPROVED
controller_approved=false
human_packet_complete=false
catalog_ready=false
writer_eligible=false
consent_based_operation=true
runtime_authority=false
operational_authorization=false
next_stage_authorized=false
runtime_effects=BLOCKED
```

### 24.2 Efeitos proibidos

Este documento não autoriza:

- criar ou publicar catálogo de consentimento;
- criar, conectar ou gravar evidence store;
- habilitar writer ou registrar evento `concedido`;
- interpretar consentimento informal ou legado como concessão;
- criar API ou painel de aprovação;
- apresentar ou coletar consentimento em WhatsApp ou painel;
- enviar mensagem, aviso, broadcast ou campanha;
- conectar webhook, fila, worker, LangGraph, agente ou tool;
- criar memória, conhecimento, vetor, índice ou outbox;
- aplicar migration ou acessar banco compartilhado para materialização;
- alterar Supabase DEV ou PROD;
- habilitar Google Calendar, Brevo, Asaas ou outro fornecedor;
- fazer deploy, restart, mudança de flag ou credencial;
- ativar agente ou executar canário;
- implementar Universidade da Vida ou Capacitação Destino.

### 24.3 Separação entre gates

Mesmo que o gate humano seja concluído no futuro, isso não torna
`catalog_ready` ou `writer_eligible` verdadeiros e não liga runtime. Catálogo,
evidence store, writer e cada integração exigem decisão técnica, PR, testes
adversariais e autorização próprios. Merge, teste verde, digest calculado,
credencial válida ou deployment automático não substituem esses gates.

Qualquer estado `CHANGES_REQUIRED`, `REJECTED`, `SUSPENDED`, `EXPIRED` ou
`SUPERSEDED`, qualquer divergência de tenant ou qualquer retirada força a
negação dos efeitos incompatíveis.

## 25. Critério de aceite do gate humano

O gate humano somente poderá ser considerado concluído quando, para uma igreja
específica e uma versão específica, todos os requisitos abaixo forem
satisfeitos:

1. `package_id`, `tenant_binding`, controlador, contato institucional,
   operadora e responsáveis foram materializados de fontes reais;
2. todas as operações reais coincidem com o escopo e os dados mínimos deste
   pacote;
3. a ficha factual não contém condição sem comprovação necessária ao gate;
4. o aviso completo e suas versões de WhatsApp, painel, adulto, menor e recibo
   estão congelados no payload;
5. a política de recusa, retirada, direitos, reaceite, retenção, eliminação e
   conservação excepcional está completa e executável;
6. `applicability_status=APPLICABLE` está acompanhado de avaliação de melhor
   interesse, avaliação de riscos e impacto, medidas de idade e fluxo de
   responsável;
7. todos os fornecedores e transferências possuem entidade, função, dados,
   país ou região, base, mecanismo e transparência comprovados;
8. o canal institucional de direitos e o processo de incidentes foram testados;
9. o conflito decorrente da acumulação de funções foi avaliado e mitigado;
10. o `decision_payload` passou no schema e foi canonicalizado por JCS;
11. duas implementações independentes produziram o mesmo SHA-256;
12. os quatro registros do gate humano referenciam identidades autenticadas,
    decisão admitida, instante e o mesmo `content_digest`;
13. o estado transitou pela máquina permitida até `CONTROLLER_APPROVED`;
14. `controller_approved=true` e `human_packet_complete=true` foram derivados
    por verificador independente dos campos editáveis;
15. nenhuma etapa técnica posterior foi tratada como consequência automática.

Na versão presente, esses requisitos não foram satisfeitos. O estado permanece
`DRAFT_NOT_APPROVED`, `controller_approved=false` e
`human_packet_complete=false`.

O encerramento futuro desse gate autoriza apenas usar o pacote como entrada de
governança para a próxima decisão. Ele não autoriza catálogo, evidence store,
writer, evento `concedido`, migration, deploy, envio, runtime ou canário.

## 26. Próximo gate fechado e único

`OWNER_AUTHORIZE_REVIEW_CONSENT_PACKET_TAREFAS_OPERACIONAIS`

O escopo exclusivo desse gate é a revisão humana do conteúdo e dos fatos deste
pacote antes de qualquer materialização por tenant ou cálculo de digest. Até
uma autorização nominal e específica para esse gate, não há próxima etapa
autorizada.
