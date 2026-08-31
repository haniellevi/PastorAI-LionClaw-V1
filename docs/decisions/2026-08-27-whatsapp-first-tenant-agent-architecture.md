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
