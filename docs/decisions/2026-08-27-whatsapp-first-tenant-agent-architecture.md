# Arquitetura do agente tenant-isolated e WhatsApp-first

Data: 2026-08-27

Status: aprovada para implementação incremental

## Contexto

A fundação do agente Evolution comprovou resolução de igreja, identidade,
autorização fail-closed, autoria de mensagens, handoff e contenção. O primeiro
canário ativo passou nos invariantes técnicos, mas as respostas ficaram
robóticas, repetitivas e sem conhecimento suficiente da igreja.

O requisito de produto é mais amplo: visitantes, membros, líderes e
responsáveis devem resolver o trabalho cotidiano pelo WhatsApp. O painel web é
uma superfície de configuração, governança, auditoria, exceção e segurança.

## Decisão

### Um produto, um grafo global, dados isolados

Haverá uma definição global e versionada de LangGraph. Ela será composta por um
grafo pai e subgrafos especialistas incrementais. Atendimento, Central de
Células, Agenda e Consolidação integram a missão atual. Universidade da Vida e
Capacitação Destino permanecem na visão futura e exigem PRDs e missões próprias
antes de qualquer implementação.

Não haverá uma cópia divergente do código do agente por igreja. O mesmo grafo
executa para todos os tenants, enquanto dados, memória, conhecimento,
credenciais, responsáveis e configuração operacional permanecem isolados por
`igreja_id`.

O servidor monta um contexto imutável por turno contendo:

- `igreja_id` e `conversation_id`;
- Pessoa ativa identificada;
- papéis e capacidades efetivas;
- consentimentos aplicáveis;
- finalidade, canal, idioma, fuso e correlação de auditoria.

Tenant, Pessoa, papéis e capacidades nunca vêm do prompt ou de argumentos do
modelo. A instância Evolution identifica a igreja e o backend revalida todo o
contexto antes de qualquer ferramenta.

Especialistas não conversam livremente entre si e não enviam mensagens. Cada
subgrafo retorna um resultado estruturado ao grafo pai. O grafo pai aplica
políticas e emite, no máximo, uma resposta externa por turno.

### Memória privada

O histórico completo de conversas é memória privada e permanece retido até a
pessoa solicitar exclusão pelo WhatsApp e um admin aprovar no painel.

A execução usa três camadas:

1. mensagens e mídias privadas como histórico auditável;
2. resumo incremental e trechos recentes como contexto conversacional;
3. checkpoints duráveis para estado retomável do workflow.

O modelo não recebe todo o histórico em cada turno. Recuperação deve respeitar
tenant, conversa, Pessoa, finalidade e necessidade. Uma exclusão aprovada
remove mensagens, mídia, transcrições, resumos, checkpoints e vetores
derivados. Permanece apenas auditoria mínima sem conteúdo.

### Conhecimento oficial

Somente estas fontes são tratadas como informação oficial da igreja:

- registros estruturados do sistema;
- documentos enviados, revisados e publicados por um admin autorizado.

Dados vivos, como pessoas, células, agenda, relatórios e formação, são lidos
por ferramentas tipadas sobre serviços de domínio. Documentos institucionais
podem usar busca textual e vetorial, sempre com `igreja_id`, audiência, versão,
vigência, fonte e estado de publicação.

Uma conversa privada nunca alimenta automaticamente a base institucional. Ela
pode originar uma pendência ou um rascunho separado, que exige redação, revisão
e publicação humana antes de virar conhecimento oficial.

Quando não houver informação oficial suficiente, o agente responde que a
informação ainda não está confirmada, registra a lacuna sem expor a conversa e
a encaminha ao responsável configurado para o setor. O admin recebe somente
lacunas sem responsável ou escaladas.

### Consentimento por finalidade

Substituir o consentimento genérico por eventos independentes e auditáveis:

- `atendimento_solicitado`;
- `cuidado_pastoral`;
- `tarefas_operacionais`;
- `comunicados`.

Cada evento registra versão, fonte, instante, concessão ou retirada. O opt-out
global atual continua bloqueando envios. Consentimento antigo não concede por
inferência todas as novas finalidades.

### Ações pelo WhatsApp

Ações comuns podem terminar no WhatsApp:

- relatório da própria célula;
- confirmação de agenda;
- atualização dos próprios dados;
- resposta e conclusão de tarefa operacional atribuída.

O agente apresenta um resumo estruturado e pede confirmação explícita. Uma
proposta durável guarda alvo, payload, autorização, validade e chave de
idempotência. Ao receber a confirmação, o backend revalida identidade,
capacidade, consentimento e estado do domínio, executa o mesmo serviço usado
pelo painel e só confirma sucesso após commit.

Ações sensíveis terminam no painel autenticado:

- permissões e papéis;
- vínculos ou movimentações de terceiros;
- dados pastorais restritos;
- publicação de conhecimento;
- exclusão de dados;
- finanças, integrações e configuração da igreja.

O WhatsApp pode criar a solicitação e enviar um link sem payload sensível. O
painel revalida Clerk, tenant e capacidade antes de exibir impacto e permitir a
aprovação.

### Notificações proativas

Notificações serão dirigidas por eventos de domínio e uma outbox durável. A
plataforma aplica finalidade, consentimento, destinatário, horário silencioso,
deduplicação, retry, dead-letter e escalonamento antes de chamar a Evolution.

Os serviços existentes de SLA, Agenda, célula e broadcast devem convergir para
esse contrato. Uma intenção persistida não pode ser exibida como mensagem
entregue. Sem recibo do provedor, o estado máximo é aceito pelo provedor.

### Primeira vertical: relatório de célula

A primeira entrega funcional será o relatório completo pelo WhatsApp:

1. identificar líder, célula e reunião esperada;
2. lembrar 30 minutos após o término, dentro da janela permitida;
3. aceitar texto ou áudio e extrair presentes, visitantes, decisões, oferta e
   observações;
4. apresentar resumo corrigível;
5. gravar somente depois de `Confirmar`;
6. usar a fonte canônica `celula_reuniao` e seu `relatorio_snapshot`;
7. responder sucesso somente após a transação concluir;
8. fazer um lembrete no dia seguinte e escalar após 24 horas.

Transcrição de áudio usa a credencial OpenAI BYO da própria igreja, com limites
de tipo, tamanho, custo e finalidade. O áudio e a transcrição continuam
privados e não viram conhecimento oficial.

## Segurança e persistência

O checkpointer LangGraph deve usar PostgreSQL em schema privado, fora da Data
API. No banco compartilhado, todas as tabelas de checkpoint e blobs possuem
`igreja_id uuid not null`, diretamente ou por uma relação composta que impeça
reassociação entre tenants. O schema revoga privilégios de `PUBLIC`, `anon` e
`authenticated`.

O acesso ocorre por uma role dedicada `agent_runtime`, `NOSUPERUSER` e
`NOBYPASSRLS`. As tabelas habilitam e forçam RLS, e suas policies exigem o
tenant fixado pelo backend com `set_config('app.tenant_igreja_id', ..., true)`
na mesma transação. Ausência do contexto nega acesso. O tenant vem da instância
Evolution validada no servidor, nunca do modelo, do cliente, de `thread_id` ou
de argumentos de ferramenta. Service role, owner com bypass e conexão como
`postgres` ficam proibidos no caminho de execução.

O namespace derivado de igreja e conversa permanece defesa adicional, sem ser
a barreira primária. A adoção exige migration controlada, grants e revokes
explícitos, backup, exclusão em cascata e testes adversariais com dois tenants,
contexto ausente e conexão de pool reutilizada. Outra estratégia de isolamento
exige uma nova decisão arquitetural; não pode ser substituída por convenção de
prefixo ou filtro de aplicação.

Documentos institucionais e seus vetores precisam de RLS por igreja e audiência.
O filtro de autorização ocorre antes da recuperação e continua aplicado na
consulta. Embeddings não contêm mensagens privadas sem uma base jurídica e uma
decisão futura explícitas.

### Preparação D3 offline: fronteira efêmera por turno

A preparação D3 offline separa `AgentTurnInput`, `AgentState` e
`AgentTurnOutput` por `input_schema` e `output_schema`. `AgentTurnEffects` é um
envelope completo de intenções do turno, reinicializado antes do roteamento,
substituído como um único valor e exposto por `UntrackedValue`. Ele não usa
reducer acumulativo, não entra em checkpoint e não comprova nem autoriza a
execução de efeito.

Os nodes continuam puros, e o runtime recebe somente a saída validada para
aplicar as intenções pelos serviços existentes. O fallback automático para o
caminho direto só é permitido quando a ausência de checkpointer e store está
comprovada; uma fronteira persistente ou indeterminada falha fechada.

Esta preparação não instala saver, não cria migration ou schema e não oferece
memória, resumo, recuperação ou retomada. O envelope é deliberadamente
turn-local. A memória privada durável de D3 permanece ausente até existir o
contrato de isolamento, idempotência, serialização, retenção e exclusão.
O freeze técnico pré-merge e exclusivamente offline desta preparação vincula:

- `backend/app/agent/context.py`, SHA-256
  `b81afb549b6110553bd4ba5e6b861a9094278670d86c92b128e04fc081f3a729`;
- `backend/app/agent/graph.py`, SHA-256
  `2d0e729e9756e09b161c300fca032fb54e0ee30bc1c963fcaf538295eedcf2c9`;
- `backend/app/agent/nodes.py`, SHA-256
  `e16ffbab8163e58af96e192976f580e1a7690b0932eb720a3b3e2874443d6454`;
- `backend/app/agent/private_checkpoint.py`, SHA-256
  `aa54f4f474fb6aa40ef02b738c5ad1d82905cbd8a1745ce805e7a19a5991dcc6`;
- `backend/app/agent/runtime.py`, SHA-256
  `f3bc2404f9335e5846c9e8a1d70ca30dd4189cc2219bca59d9ec098e05cc1a9e`;
- `backend/tests/test_agent_turn_effect_state.py`, SHA-256
  `eb8b26c43bd958965564668f9763de368a310afa4f658161d7b04b906256fbf8`.

A focal terminou em `144/144`, e a seleção `tests/test_agent*.py` terminou em
`309 passed, 7 skipped`. Essa evidência é local e pré-merge; não prova CI,
integração, saver, migration, memória ativa, deploy ou runtime.

A PR #352, HEAD
`c5b2b4c775592641b308de6b2ac3cd069f34dcb3`, integrou a preparação D3 no
merge `6c807717010a41edf3bfd3d1b2405c2f3527a696`. A árvore do merge é
idêntica à árvore do HEAD da PR. Os sete workflows pós-merge concluíram com
`SUCCESS`: Backend Tests `33428905043`, Canonical Schema Derivation
`33428905057`, E2E Critical `33428905042`, Environment Attestation PG17
`33428905234`, Frontend CI `33428905212`, RLS Integration `33428905114` e
Tooling Static Checks `33428905041`.

A Vercel registrou o deployment automático do frontend Production
`6187746800`, status `17584957483`, com `SUCCESS`, em
`2026-08-31T19:09:09Z`. Essa metadata prova somente o deployment do frontend;
não prova saúde funcional, backend, banco, saver, migration, memória ativa,
deploy do backend, flag ou runtime. A classificação pós-merge permanece
`PREPARAÇÃO D3 INTEGRADA E INATIVA`.

### Preparação D3 offline: identidade estável e intenções determinísticas

Sobre o merge integrado `6c807717010a41edf3bfd3d1b2405c2f3527a696`, o
commit técnico local `14b3d7ba15e88032cd53714008d36badd4578e80`
adiciona um contrato puro e ainda inativo. `AgentTurnIdentity` vincula os UUIDs
não nulos de `igreja_id`, `conversation_id` e da mensagem inbound já persistida
ao provedor fechado `evolution` e ao `provider_message_id` exato. A derivação
usa domínio, versão e enquadramento binário por comprimento para produzir um
`turn_id` estável. `claim_id` fica deliberadamente fora dos campos e do hash.

`AgentEffectIntent` separa a identidade do efeito de seu conteúdo. O
`effect_id` deriva do turno, do slot semântico versionado e de um `ordinal`
estável; o `payload_digest` vincula separadamente o efeito, o tipo e o JSON
canônico limitado. Os tipos mínimos são `intake_update`, `apply_optout`,
`apply_consent`, `tool_call`, `audit_event` e `outbound_reply`. O `ordinal`
deverá vir de um plano futuro, determinístico e persistido, nunca do modelo, da
ordem transitória de uma lista, de retry ou de índice em memória.

A validação recebe a identidade esperada de uma fonte confiável, limita o
turno a 256 intenções e rejeita outro turno, slot duplicado, conflito de
payload e colisão estrutural. O JSON canônico aceita somente valores JSON
exatos, com limites explícitos de profundidade, nós, inteiros, strings e bytes.
Erros e `repr` expõem somente códigos estáticos, mas o objeto ainda contém IDs
brutos: essa proteção não autoriza log, `asdict` ou serialização. Os hashes são
namespaces determinísticos, não autenticadores, segredo ou autoridade de
tenant.

O commit local `f82f76927ba8a6a265478ad7f21eae07b0d6504c` adiciona um
adaptador confiável atrás de
`agent_trusted_inbound_identity_enabled=false` por padrão. A ingestão propaga o
UUID de `Message.id` já persistido tanto no registro novo quanto nos caminhos
de duplicata. O worker exige uma mensagem inbound, UUIDs não nulos, o ID
Evolution persistido e um `claim_id` UTF-8 imprimível de até 128 bytes. O claim
permanece requisito separado de recuperação e nunca altera o `turn_id`.

Com a flag ligada, a identidade é construída antes de coerção de tenant,
callback de ownership, reserva durável, criação de sessão, lease, import do
runtime ou qualquer efeito. Antes da primeira consulta, o runtime rederiva a
identidade com quatro entradas confiáveis e separadas: `igreja_id`,
`conversation_id`, o UUID inbound persistido de `Message.id` e o
`provider_message_id` exato. Ele exige igualdade integral dos quatro vínculos
com a identidade construída pelo worker; qualquer divergência aborta. Falhas
expõem somente
`TrustedInboundIdentityErrorCode` ou `AgentTurnContractErrorCode` sanitizados.
O caminho ligado nunca volta ao fluxo legacy; com a flag desligada, a
assinatura e o comportamento legacy são preservados. O `AgentState` continua
recusando `turn_identity`, `inbound_message_id`, provider, claim e effect como
aliases de autoridade. A identidade chega somente à fronteira confiável do
runtime, não ao grafo, checkpointer ou modelo.

Esse wiring não foi ativado nem testado em ambiente compartilhado. O validador
de `provider_message_id` continua mais estrito que o ingresso histórico; um
preflight de compatibilidade dos IDs persistidos é requisito obrigatório antes
de qualquer flag-on futuro. A existência da flag ou o merge do código não
autoriza sua ativação.

### Preparação D3 offline: plano estrutural de execução

O contrato puro `turn_execution`, originalmente revisado no commit
`576de558983622146a91417c65a85a2a321f585b` e incorporado localmente em
`7d1ed00d0add18162a89f3a9c39da6039e74017c`, é stdlib e depende somente do
contrato congelado de identidade. Nenhum código de produção o importa.

`AgentTurnExecutionPlan` ordena deterministicamente o conjunto completo de
intenções: intake, opt-out, consentimento, tools, auditoria e, por último, no
máximo uma resposta. Efeitos singleton exigem ordinal zero. O escopo opaco de
serialização deriva somente de igreja e conversa; ele identifica a fronteira,
mas não adquire lock, não agenda turnos e não garante FIFO.

`AgentEffectReceipt`, `AgentReplyOutboxEntry` e as transições da outbox são
valores estruturais imutáveis. Eles não são linhas duráveis nem prova de uma
store confiável. `ACCEPTED` significa somente que transporte ou provedor
aceitou a tentativa, sem provar entrega ou leitura. `AMBIGUOUS` é terminal; só
uma falha pré-envio comprovada por futuro adaptador pode retornar de
`IN_TRANSPORT` para `PENDING`.

A compatibilidade `v2` deriva do `effect_id`. As chaves vivas `v1` e `v0`
incluem material instável de claim ou resposta e só podem ser vinculadas como
evidência exata carregada por futuro adaptador; o contrato não as deriva,
autentica ou aceita como correlação suficiente. Texto, horário, telefone,
proximidade e saída do modelo nunca são evidência de correspondência.

O freeze local vincula:

- `backend/app/agent/turn_identity.py`, SHA-256
  `5be323d7fafa4a51d5c954749c8d2d5991e33313e269ee0a3b63bdfc9fb3923d`;
- `backend/tests/test_agent_turn_identity.py`, SHA-256
  `4072b76688552b6f870e89876426d3c608b34a362ec895315d733691dff101c5`;
- `backend/app/agent/turn_execution.py`, SHA-256
  `72a53515a835bac528280223e22f76a33f8606b5ce979dae11773d10ea6a1b2b`;
- `backend/tests/test_agent_turn_execution.py`, SHA-256
  `7e22814f1715b7bdfc7f83431bf4e15cdf6d8f7d13d0d8d3afaa6811e95e0b2d`;
- `backend/app/config.py`, SHA-256
  `c97f3c62c872b0e6a1d2e745f7effbdbb395617f5533abf7e4c82f6a681fcfe3`;
- `backend/app/workers/queue_worker.py`, SHA-256
  `54b15a3ceb60bf05eee66a88971d25cafb56f5b9e8e2d3d10ce7fcb8793a861c`;
- `backend/app/agent/runtime.py`, SHA-256
  `28208ccdd3dcfb13e24c48400cb8495d55e382c1af4829b6c68d6394d2903085`;
- `backend/app/agent/context.py`, SHA-256
  `35eee0c1ac36a983b9f28799dc7c0febb59989dc3378c94056b7f4765c199d08`;
- `backend/tests/test_agent_tenant_runtime.py`, SHA-256
  `bca0708077d6f3e065445c6b3ca97bb49c46461c8335ea871b045bbbd9cd437b`;
- `backend/tests/test_agent_trusted_context.py`, SHA-256
  `880f6f51eb77eaee38b26a9b77fb4c5a16b205044b3723ab2f9d4424312605e8`;
- `backend/tests/test_whatsapp_worker.py`, SHA-256
  `c1d2a0600e41fe44e23cba89929bbfa29f0e951312f1b6735124a2d39a1b08fd`.

O wiring passou em `245/245` e em `401 passed, 7 skipped` na seleção
`tests/test_agent*.py`. O contrato de execução passou em `86/86`, na revisão
independente `190/190` e em `462 passed, 7 skipped` na mesma seleção. As duas
revisões terminaram `GO`, sem P0, P1 ou P2. A evidência é local e pré-PR.

Não existe persistência de plano, receipt ou outbox, store autenticada, lock
de conversa, FIFO, fronteira atômica entre commit de domínio e outbox, saver,
checkpoint durável, migration, memória, retomada, replay seguro, flag-on ou
runtime ativado.

### Preparação D3 offline: adaptador replay-only da saída do turno

Na mesma branch, o commit técnico local
`abafdffdc8252fa6dff7c9d1975cb6c241141971` adiciona o módulo puro
`turn_plan_adapter`. Ele aceita somente o envelope fechado e versionado da
saída atual do grafo, revalida rota, resposta e eventos, projeta as intenções e
constrói um `AgentTurnExecutionPlan` determinístico. O módulo não oferece
status `EXECUTABLE`, callback injetável, I/O ou consumer de runtime; worker,
grafo e runtime não o importam.

A reconciliação é exclusivamente replay-only. Plano armazenado ausente ou
qualquer receipt terminal ausente produz `FIRST_EXECUTION_UNSUPPORTED`, que
bloqueia a primeira execução. Somente um plano armazenado estruturalmente exato
e vinculado ao digest projetado, junto de exatamente um receipt terminal válido
por efeito, retorna `REPLAY_TERMINAL`. O retorno não concede autoridade para
executar, persistir, transportar, repetir ou mutar domínio. Receipt sem plano,
plano conflitante, recibo inesperado ou duplicado falham fechados.

`tool_calls` são bloqueados mesmo quando parecem estruturalmente plausíveis.
O único `float` admitido fica no campo fechado
`report_captured.relatorio.oferta`; ele precisa ser finito, não negativo e
exato em centavos, sendo convertido e vinculado como inteiro
`oferta_centavos`. Nenhum outro float entra no payload canônico.

O freeze local ampliado vincula:

- `backend/app/agent/turn_plan_adapter.py`, SHA-256
  `c81dafec100734ee9a219d8c99a636636b6317b94c93c87cb89ba0f9af581002`;
- `backend/tests/test_agent_turn_plan_adapter.py`, SHA-256
  `328f3a2870fab8ea38f1901a02e640bec2f5bc9457c3d5261f350a45ef560d5e`.

A revisão integrada passou em `291/291`, e a seleção
`tests/test_agent*.py` terminou em `625 passed, 7 skipped`. A revisão concluiu
`GO`, com P0, P1 e P2 iguais a zero. A evidência é local e pré-PR.

O lote ampliado permanece sem plano ou receipt persistido, store autenticada,
lock de conversa, FIFO, fronteira atômica, saver, checkpoint durável,
migration, memória, primeira execução, flag-on ou runtime ativado. A
classificação é `LOTE D3 OFFLINE AMPLIADO LOCALMENTE / REPLAY-ONLY / FLAG
DEFAULT FALSE / CANDIDATO NÃO INTEGRADO NO MAIN / RUNTIME NÃO ATIVADO`.

### Preparação D3 offline: snapshot e workflow do relatório de célula

O commit técnico local `4988de11566f8f0675256b9958ca242e5a009fa3`
integra ao lote o snapshot agregado `cell-report/v2`. O snapshot canônico
guarda os totais de presentes, visitantes e decisões, a oferta decimal
canônica, observações limitadas e um `submission_effect_id` opaco de
correlação. Os arrays `presencas`, `visitantes` e `records` precisam ser listas
vazias; qualquer material individual falha fechado. Assim, o snapshot não
inventa pessoas nem converte uma contagem agregada em identidade ou presença
individual. O identificador de correlação não é tenant, autorização, recibo
durável ou prova de idempotência.

O commit técnico local `452aa6ff591b80dcbd3da90f1e5c18367cffd72b`
integra o workflow puro de coleta, revisão e confirmação, com valores
imutáveis. Campos
ausentes permanecem distintos de zero; cada revisão completa produz proposta e
código novos, e somente o comando literal da revisão corrente pode chegar a
`CONFIRMATION_ACCEPTED`. Essa confirmação apenas correlaciona valores, sem
autenticar ator, consentimento, tenant ou capacidade e sem conceder execução.
A confirmação literal apenas correlaciona a revisão corrente; não autentica o
ator, não concede autoridade e não executa efeito. O estado `COMMITTED` projeta
uma comprovação externa futura. `mark_cell_report_committed` somente projeta
essa comprovação como valor; a função não grava, envia nem executa o efeito.

Ainda não existe bridge ou wiring entre `turn_plan_adapter`, workflow e
snapshot. `REPLAY_TERMINAL` não prova relatório persistido: o plano atual de
`report_capture` contém somente intake, auditorias e resposta, sem efeito de
gravação do relatório. Um adapter futuro, executado em código confiável,
precisa derivar um escopo vinculado ao tenant, mapear centavos e string sob o
mesmo limite de produto E2 do painel, revalidar autoridade e marcar
`COMMITTED` somente depois do commit externo atômico do relatório.

O freeze local dessas fatias vincula:

- `backend/app/domain/cell_report_snapshot.py`, SHA-256
  `19adb057c9f002776e3ad99d87de636de4975f5cf602a8fb06d2d8401a7d2aaa`;
- `backend/tests/test_cell_report_snapshot.py`, SHA-256
  `08464997fa55cb9319d095f672fe0d78693280104d8b4247390e3e75d80ad7f9`;
- `backend/app/domain/cell_report_workflow.py`, SHA-256
  `87ec5691774eab1b2711fea0f07f9f311ddacf7f321fe36646730742b02569b5`;
- `backend/tests/test_cell_report_workflow.py`, SHA-256
  `a5a542f6b0192964a0bdd238b8306a1b8ca162be4ec6e2f824773020300508c6`.

O hardening posterior foi composto pelos commits
`f40d39efeb847b84b30e495ba78f6d218437e8ad`,
`a84bb7d5f00bae6bb472d02c4a33d14442a294a2`,
`ef4aa00797e11bbbaa0189faa2c299bf9ace8a5b`,
`9ea14000065117bda4aa8e7627e78c07dd5d1b2a` e
`45323a64b17cd9f1fa4d4a86f3a32d769f525660`, sem reescrever os freezes
anteriores. Os pins finais são adaptador SHA-256
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
limite E2 de oferta em `R$ 999.999,99`. O builder e a revalidação do snapshot
persistido aplicam exatamente os mesmos limites. O writer humano e o snapshot
recusam zero negativo; o writer também recusa `NaN`, infinito, booleano, string
e mais de duas casas decimais. Isso ainda é constante compartilhada mais
validação humana endurecida, não um serviço de aplicação compartilhado. Os
pins finais adicionais são `backend/app/domain/cell_report_limits.py`, SHA-256
`cb0acd562ebd4e91f2f3170d59ff67cea3ac45f9b4a73f370b1c78522b330412`;
`backend/tests/test_cell_report_limits.py`, SHA-256
`7f11003b18b0159815f54306002e87624045282d775de08d1ba47da1b6822e86`;
`backend/app/routers/cell_meetings.py`, SHA-256
`e72c1e8366a45ab487b38e1d04b110583b4825645daadaccf1957a04b913ddf5`;
e `backend/tests/test_cell_lider.py`, SHA-256
`07ffabd0260b573bad0fbd8ba572064d0acaaa3b361524dea06a35d8ac781b4d`.

Na revisão integrada final do HEAD
45323a64b17cd9f1fa4d4a86f3a32d769f525660, passaram 512 passed, 5 warnings;
633 passed, 7 skipped, 2 warnings; 398 passed, 18 warnings; e 34 passed
documentais. Links locais 89/89, matriz de pins e gates 13/13, py_compile,
secret scan e git diff --check ficaram verdes. O parecer foi GO, com P0, P1 e
P2 iguais a zero. A evidência é exclusivamente local e pré-PR; não prova
runtime, DEV, PROD, banco, deploy ou efeito vivo.

As duas fatias estão integradas somente ao lote local. Nenhum runtime ou worker
foi acionado, e não houve acesso a banco, migration, rede, persistência,
mensagem ou qualquer efeito vivo. A classificação é `FUNDAÇÃO OFFLINE DO RELATÓRIO DE
CÉLULA AMPLIADA LOCALMENTE / SNAPSHOT V2 AGREGADO / WORKFLOW PURO / CANDIDATO
NÃO INTEGRADO NO MAIN / EFEITOS VIVOS BLOQUEADOS`.

O gate anterior
`REVIEW_AND_CI_D3_TURN_EXECUTION_AND_TRUSTED_INBOUND_WIRING_OFFLINE_PR` foi
substituído localmente, sem consumo, pelo lote ampliado replay-only. Não houve
push, PR, CI ou Preview sob esse gate, portanto ele não é evidência histórica
de uma ação externa.

O gate anterior `REVIEW_AND_CI_D3_TURN_FOUNDATION_REPLAY_ONLY_OFFLINE_PR` foi
substituído localmente, sem consumo, pela fundação offline do relatório de
célula. Não houve push, PR, CI ou Preview sob esse gate, portanto ele não é
evidência histórica de uma ação externa.

### Preparação D6 offline: proposta pendente e serviço transacional

O commit técnico original `c24b910bcd4bf4015eda14847e9695497b5b8ef6`
foi consolidado localmente, sem alteração da árvore técnica, no HEAD
`bcabbae0cf96a9b6e2cd47e8ff041b5aeaffbc84`, sobre a reconciliação documental
`e0cb280`. A fatia acrescenta o envelope fechado
`cell-report-pending-proposal/v1` e o serviço
`cell_report_application`. O envelope ocupa `relatorio_snapshot` somente
enquanto `relatorio_status=pendente`; ele contém o workflow reidratável,
expiração UTC de no máximo 24 horas, até 32 operações estruturais, digest do
estado-base e bindings separados de tenant, reunião, conversa e ator. Os UUIDs
brutos não entram no JSONB, mas os hashes não são autenticadores. Observações
continuam conteúdo privado e não podem aparecer em logs ou erros.

O serviço exige uma transação tenant-scoped já ativa e pertencente ao caller.
Dentro dela, fixa o tenant com `require_tenant_scope`, adquire locks em ordem
canônica e revalida conversa oficial sem handoff humano, reunião passada e não
cancelada. Novas propostas e materializações exigem relatório pendente,
enquanto replay final exato é permitido para enviado. Célula e líder ativos,
Pessoa não arquivada, sem `sem_interesse` e sem opt-out, exatamente um
`AppUser` utilizável e ao menos um papel em
`MINISTERIAL_ROLES`. A proposta e cada revisão são vinculadas a um
`AgentTurnIdentity` e a um `AgentEffectIntent` do tipo `TOOL_CALL` com payload
exato. Na confirmação literal corrente, o serviço substitui o envelope pelo
`cell-report/v2`, atualiza os campos canônicos de `celula_reuniao` e executa
somente `flush`. Ele nunca inicia, confirma ou reverte a transação; o resultado
novo declara `requires_caller_commit=true`, e uma falha sanitizada ainda exige
rollback pelo caller.

O hardening final preserva no snapshot o `submission_effect_id` original e o
`submission_payload_digest` separado. A dupla vincula identidade e conteúdo
do efeito planejado, mas não prova proveniência, autorização, entrega,
primeira execução ou unicidade global. O histórico de operações da proposta é
limitado e vinculado à mesma linha; não substitui plano persistido, receipt
durável autenticado ou outbox. Os limites compartilhados agora fixam
`MAX_CELL_REPORT_OBSERVATIONS_LENGTH=2_000` caracteres e
`MAX_CELL_REPORT_OBSERVATIONS_BYTES=8_000` bytes UTF-8, além dos limites de
contagem e oferta já congelados. Fetch de rows, fetch de scalars e `flush`
convertem `SQLAlchemyError` em categoria estática sem encadear a exceção
privada.

Essa fronteira tem capacidade ORM quando um caller futuro a invocar, portanto
não é código puro. Mesmo assim, não existe caller no grafo, worker, webhook,
router humano ou `turn_plan_adapter`; o adaptador replay-only continua
recusando `tool_calls` e retornando `FIRST_EXECUTION_UNSUPPORTED` para a
primeira execução do agente. `AgentConfig`, proveniência inbound, plano e
receipts duráveis, outbox e resposta pós-commit continuam fora. O router web
humano ainda não usa o serviço nem adquire o mesmo lock da reunião, condição
obrigatória antes de ativação para eliminar corrida entre writers.

A revalidação de liderança, papel e opt-out não equivale ao consentimento
`tarefas_operacionais`. A fonte jurídica e do controlador continua não
aprovada, o ledger D2B2a segue sem caller e sem aplicação em Supabase, e esta
fatia não lê nem grava consentimento. Também não há transcrição de áudio,
lembrete, escalonamento, migration, teste em banco compartilhado, acesso a DEV
ou PROD, rede, mensagem ou efeito vivo.

Os pins integrais do HEAD são:

- `backend/app/domain/cell_report_limits.py`, SHA-256
  `8c7a81ee9a8f0a14125c5918aba6f149582e6392d129c9b37744ac3a1d12bf42`;
- `backend/app/domain/cell_report_pending_proposal.py`, SHA-256
  `53769d79835803dc8c294928047d2d8766de491e17aecc9d57edb239f06c4056`;
- `backend/app/domain/cell_report_snapshot.py`, SHA-256
  `24e93a2b6e8cbe92a849ba3ccc081ff6fbd092a347a605494464fddc6aa3bc51`;
- `backend/app/domain/cell_report_workflow.py`, SHA-256
  `da16186dc28f18261967e10800c5f300dae2b11552ed6dff389cbe9d7a3bf877`;
- `backend/app/routers/cell_meetings.py`, SHA-256
  `59de2e7b9d12a4c9d36e16edf28c8a74ea590244b778dae8da44ac8f47f49067`;
- `backend/app/services/cell_report_application.py`, SHA-256
  `7dc9d0d9cc7bf09c3d8963e956bd60500038004c5e8d882c7d37dd30c3a3389b`;
- `backend/tests/test_cell_health_service.py`, SHA-256
  `19fbe602a4943fa76a3583e1e9e61a3e7979169caba5de15e157072262c8be69`;
- `backend/tests/test_cell_lider.py`, SHA-256
  `a0265297ec29895399bf4ea0bfac37f554ec935ae5fd6e157c4f348bd69cc6a5`;
- `backend/tests/test_cell_report_application.py`, SHA-256
  `30139bffee6be9c00f7068255c6150ee8507506a14ccb9649bebadbf39dc136e`;
- `backend/tests/test_cell_report_limits.py`, SHA-256
  `c1d4c2b89e3863e10fed7a3e84eb27b2cece6447c8a63e05237d24fff26196aa`;
- `backend/tests/test_cell_report_pending_proposal.py`, SHA-256
  `299b23c0795d9a1e70ac0e6ed46b4124c64a94e567f2e8a6d03732fde6165a3c`;
- `backend/tests/test_cell_report_snapshot.py`, SHA-256
  `7cbd65505095c7821bbb8328da9b6d22760fce0544ab80861ca765c82bbd87fb`;
- `backend/tests/test_cell_report_workflow.py`, SHA-256
  `704f036d1fd5632c7c33dd5c446e80e6f303fa712adacee892dde822b83f53a9`;
- `backend/tests/test_reports.py`, SHA-256
  `fb511601265dfa374a7d9fbec35f913a7e4bdbde615ce82c1c7996e2d51177d2`.

No freeze técnico, a focal passou em `292 passed`; a seleção
`tests/test_agent*.py` terminou em `633 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`730 passed, 18 skipped, 35 warnings`. A suíte ampla do backend, com
`migration_history` e Redis fora da seleção, chegou a
`4601 passed, 325 skipped, 499 deselected, 66 warnings`, mas não foi
classificada verde: restaram a asserção documental do pin anterior, corrigida
por esta reconciliação, e duas falhas baseline dos verificadores causadas pelo
modo group-writable `0664` dos artefatos no checkout `/tmp`. Após esta
reconciliação, a matriz documental passou em `34 passed`. A revisão independente
repetiu `729 passed` e `1363 passed, 25 skipped` e concluiu `GO`,
com P0, P1 e P2 iguais a zero. Toda evidência é local e pré-PR.

A classificação corrente é `FRONTEIRA TRANSACIONAL OFFLINE DO RELATÓRIO
AMPLIADA LOCALMENTE / PROPOSTA PENDENTE FECHADA / FLUSH SEM COMMIT / CANDIDATO
NÃO INTEGRADO NO MAIN / RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior `REVIEW_AND_CI_D3_CELL_REPORT_OFFLINE_FOUNDATION_PR` foi
substituído localmente, sem consumo, pela fatia offline do serviço de aplicação
do relatório. Não houve push, PR, CI ou Preview sob esse gate, portanto ele não
é evidência histórica de uma ação externa.

### Preparação D6 offline: reserva V2, writers serializados e staging atômico

A composição técnica corrente está no HEAD local
`dac3a14cdd2bf857f84609518dd96050e203b4b3`. A reserva V2 foi criada no
commit original `4d08e783c2de1bb20dfeb29ffb8ee6a43c7a444f` e integrada
como `d6ee2323d658a91bb92724aaa13adea7222538b4`; a UoW veio de
`58b77a84e38ba7be4d3968d32834ef1b415b3a89` e foi integrada como
`17305af54e52aea74948e275ad68fae50427ae67`; a serialização dos writers
veio de `83b4810008f37250b9a9d00f9c9a83f04a3d0399` e foi integrada como
`b6a763cbcab41a78815a7777f2c9b682a6af1ddb`. O commit
`dac3a14cdd2bf857f84609518dd96050e203b4b3` reconciliou nos testes o
`expected_replayed` explícito. A revisão técnica consolidada posterior
concluiu `GO`; a evidência exata está registrada abaixo.

`derive_agent_outbound_reply_effect_id` fixa o único slot
`OUTBOUND_REPLY` ordinal zero a partir de `AgentTurnIdentity`.
`build_agent_outbound_reply_reservation_v2` usa esse identificador para
produzir, antes de payload e plano, a mesma chave que
`build_agent_effect_compatibility_key` produzirá para o reply posterior. O
vetor é claim-independent e separa tenant, conversa e inbound por meio da
identidade confiável, mas continua sendo namespace determinístico, não
autenticador. A reserva é somente valor puro: não cria linha, lease, outbox,
receipt, unicidade global, aceite do provedor ou send.

As chaves V1 e V0 continuam fora da derivação confiável porque carregam
material instável de claim ou resposta. A UoW aceita esses formatos somente
como evidência exata lida da `Message` legacy já bloqueada e vinculada ao mesmo
reply planejado. Isso oferece um caminho de drain futuro, sem migrar linhas,
promover formato antigo, inferir chave por texto ou ativar compatibilidade no
runtime.

Os seis writers humanos `edit_meeting`, `set_real_attendance`,
`register_visitor`, `add_record`, `save_report` e `submit_report` agora passam
por `_report_writer_storage_boundary`. Cada um bloqueia e revalida a reunião,
a célula e o `AppUser` tenant-bound antes da escrita, usando
`populate_existing` para não confiar no snapshot anterior da sessão. O painel
pode assumir explicitamente um envelope `cell-report-pending-proposal/v1` e
invalidá-lo; qualquer snapshot pendente desconhecido permanece intacto e gera
conflito. Falhas SQLAlchemy são convertidas em erro estático, com rollback
best-effort sem ecoar statement, parâmetro ou exceção privada.

O reconhecedor puro `cell_report_legacy_snapshot` aceita somente a projeção
schema-less completa que o submit humano pode construir. Chaves, metadados,
limites, listas, identidades e UUIDs canônicos não nulos precisam coincidir.
Quando um writer humano vence a corrida, a confirmação do agente retorna
`REPORT_CONFLICT`; material parecido, incompleto ou com UUID nulo continua
`DATA_INTEGRITY`. O reconhecedor nunca devolve o conteúdo. Os writers web
continuam em endpoints próprios e não passaram a chamar o serviço de aplicação
do agente; a mudança fecha a serialização compartilhada, não uma unificação de
serviços.

A `cell_report_turn_uow` recebe exatamente três efeitos do mesmo turno:
`TOOL_CALL` para confirmar o relatório, `AUDIT_EVENT` sem conteúdo pastoral e
`OUTBOUND_REPLY`. Ela reconstrói o plano canônico, exige transação tenant-scoped
já ativa e bloqueia uma `Message` outbound de IA pré-reservada. Para V2, a
chave esperada precisa coincidir antes de qualquer consulta; para V1/V0, a
evidência exata é vinculada somente depois do lock da linha.

O estado da `Message` e a existência do audit determinam a expectativa de
replay sob lock. `confirm_cell_report` exige agora o booleano
`expected_replayed` e falha antes de mutar se o estado oficial da reunião
discordar. Um replay aceito exige simultaneamente snapshot final exato,
`Message` `ia_pendente` com o mesmo texto e audit com os mesmos effect IDs,
payload digests e `plan_digest`. Essa observação não prova commit anterior,
pois pode enxergar escritas da transação atual.

No caminho novo, a UoW agrupa o snapshot `cell-report/v2`, um
`AgentConversationLog` sem texto pastoral e a transição da `Message` para
`ia_pendente`. O resultado declara `requires_caller_commit=true` em todo
sucesso, inclusive replay. A UoW faz somente `flush`: nunca inicia, confirma ou
reverte transação, nunca chama runtime, worker, grafo ou provedor e nunca envia
a mensagem. Depois de falha sanitizada, descartar a transação continua dever do
caller futuro.

Essa fronteira fecha staging atômico específico dentro de uma transação
externa, sem criar outbox genérica, receipt global autenticado ou comprovante
pós-commit. Não existe caller. Consentimento `tarefas_operacionais`,
`AgentConfig`, proveniência operacional, commit, send, primeira execução
genérica pelo `turn_plan_adapter`, migration e drain V1/V0 continuam
bloqueados. Não houve banco compartilhado, DEV, PROD, rede, mensagem ou
deployment.

Os pins SHA-256 integrais do HEAD são:

- `backend/app/agent/turn_execution.py`,
  `b729c3b25024cff41aa42b39aecd9d30712bf229c8f635c40fbd306cf52ac351`;
- `backend/app/agent/turn_identity.py`,
  `59848ebee37c9be0c9488420c4634e1b323f611c22627328c8c4dd73d5e69998`;
- `backend/app/domain/cell_report_legacy_snapshot.py`,
  `22dc8e5992f5661a5c110d6a4cc1ebedf7babfabfd45a56490b484de4695f869`;
- `backend/app/routers/cell_meetings.py`,
  `9a04c1589f64179e7b60a8b18755a40ee21035a8e955f8ff5238c4c5eba3a18e`;
- `backend/app/services/cell_report_application.py`,
  `0c8ddd4040b83e09fd496eeea3594c68309f0446b97b2466d5f32204babcc347`;
- `backend/app/services/cell_report_turn_uow.py`,
  `1bdebab8fb70b081781fa0ace6152b1d83cdeb9161a125172b16ca5929795399`;
- `backend/tests/test_agent_turn_execution.py`,
  `911cc7743b073c78b6d5eaffc29eee1171bdf25d1526bd94a32542302c92420e`;
- `backend/tests/test_agent_turn_identity.py`,
  `6d60a2668810bf8c62e23658d95c54b886079e4e7ecf120f349e989de710e1cf`;
- `backend/tests/test_cell_lider.py`,
  `0732667504127fb4bcdc163187b9b137e77f645e81a743413d8a7c4332f1ee0e`;
- `backend/tests/test_cell_report_application.py`,
  `278e3d506ca5c0853b957529013991bb676320381727f33183afcadc7768f430`;
- `backend/tests/test_cell_report_legacy_snapshot.py`,
  `57586f81accd27145d5877ce91fa9d98f82f29b1ee4f73828768cfe93134c354`;
- `backend/tests/test_cell_report_turn_uow.py`,
  `5ce3d8b37f672adfeaf04839183d43f7f67b51f5cf6d81b37b663bf9c2128db9`.

A revisão técnica integrada no HEAD
`dac3a14cdd2bf857f84609518dd96050e203b4b3` concluiu `GO`, com P0, P1 e
P2 iguais a zero. A focal integrada terminou em `682 passed, 5 warnings`;
`tests/test_agent*.py` terminou em `649 passed, 7 skipped, 2 warnings`; e
`tests/test_cell*.py tests/test_reports.py` terminou em
`960 passed, 18 skipped, 35 warnings`. Também passaram 200 vetores da reserva
V2 e 8 casos de corrupção legacy. As validações de AST e `git diff --check`
para `d37d528..dac3a14` ficaram verdes. A evidência é local e pré-PR. Ela
confirma ainda a ausência de caller em runtime, worker ou webhook, de migration,
rede ou send e de `begin`, `commit` ou `rollback` na UoW.

Estado: `STAGING TRANSACIONAL OFFLINE COMPOSTO E REVISADO LOCALMENTE / RESERVA
V2 CLAIM-INDEPENDENT / WRITERS SERIALIZADOS / FLUSH SEM COMMIT / GO TÉCNICO
P0=P1=P2=0 / SEM CALLER / RUNTIME E EFEITOS VIVOS BLOQUEADOS`.

O gate anterior `REVIEW_AND_CI_CELL_REPORT_APPLICATION_SERVICE_OFFLINE_PR` foi
substituído localmente, sem consumo, pelo lote de staging transacional. Não
houve push, PR, CI ou Preview sob esse gate, portanto ele não é evidência
histórica de uma ação externa.

**Próximo gate único:**
`REVIEW_AND_CI_CELL_REPORT_TRANSACTIONAL_STAGING_OFFLINE_PR`. O nome não
constitui autorização já concedida. Seu consumo exige autorização humana
posterior e separada que nomeie push, abertura da PR e GitHub CI e aceite o
Vercel Preview automático. O gate cobre somente revisão e CI do lote offline de
staging transacional. Não autoriza merge, Vercel Production, flag-on, caller,
`AgentConfig`, primeira execução do agente, runtime, worker, consentimento,
commit, send, drain V1/V0, receipt global, saver, probe vivo, acesso a DEV ou
PROD, banco, logs, SQL, DML, migration, outra rede, deploy, mensagem, tool call
ou qualquer efeito vivo.



## Configuração e ativação

O master governa a política global e a versão do grafo. O admin alimenta dados
básicos, documentos aprovados, responsáveis, horários e políticas da própria
igreja por um onboarding guiado.

A credencial da igreja é OpenAI BYO. OpenRouter pertence ao ambiente pessoal do
GPT Desktop e não integra o PastorAI.

Credencial válida não ativa o agente. `AgentConfig.ativo=false` permanece até
o checklist da igreja passar e existir autorização nominal para canário. Asaas,
Brevo e broadcast mantêm gates e canários independentes.

## Consequências

### Benefícios

- comportamento consistente entre igrejas sem misturar dados;
- continuidade de conversa com exclusão auditável;
- respostas fundamentadas em fontes oficiais;
- automação do trabalho pastoral com confirmação e rastreabilidade;
- especialistas extensíveis sem permitir autonomia externa descontrolada.

### Custos e obrigações

- novos contratos de consentimento, memória, conhecimento, propostas e outbox;
- política de retenção e exclusão propagada para todos os derivados;
- observabilidade por tenant sem registrar conteúdo sensível;
- avaliação humana de naturalidade, além dos testes funcionais;
- PRDs próprios para Consolidação, UV e CD antes de seus subgrafos escreverem
  dados.

## Fora do escopo desta decisão

- ativar agente ou envio em produção;
- abrir Asaas, Brevo ou broadcast;
- usar conversas como treinamento automático;
- fine-tuning automático por igreja;
- permitir que o modelo escolha tenant, autorização ou efeito externo;
- implementar UV ou CD a partir dos placeholders existentes.

## Critérios de aceite arquitetural

- nenhuma leitura, memória, vetor, checkpoint ou ação cruza igrejas;
- nenhuma ação é gravada antes da confirmação exigida;
- replay, concorrência e timeout não duplicam efeitos;
- exclusão aprovada remove todos os conteúdos e derivados privados;
- ausência de fonte oficial produz resposta honesta e pendência atribuída;
- todo envio proativo possui finalidade, consentimento e ledger;
- avaliação humana aprova naturalidade e ausência de repetição;
- deploy e canário continuam gates separados da implementação.
