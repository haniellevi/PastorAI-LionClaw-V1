# Evolution Agent Foundation

Data: 2026-08-25

## Decisão

O Evolution é o único transporte de WhatsApp do PastorAI nesta fase. Hermes e
BotConversa não integram o caminho de mensagens. O PastorAI permanece como fonte
de verdade de pessoa, conversa, consentimento, autorização, auditoria e efeitos
de domínio.

    WhatsApp
      -> Evolution
      -> webhook e fila idempotente
      -> tenant pela instância
      -> pessoa pelo telefone canônico
      -> privilégio resolvido no servidor
      -> workflow determinístico
      -> refino opcional de linguagem
      -> outbox e Evolution

## Identidade

1. A instância Evolution registrada identifica a igreja.
2. O processamento é promovido para o tenant antes de consultar pessoas.
3. O telefone recebido é normalizado e comparado somente com Pessoas ativas.
4. Uma correspondência ativa é reutilizada.
5. Nenhuma correspondência cria um contato sem privilégios.
6. Mais de uma correspondência ativa é anomalia e falha fechada. O item pode ser
   repetido e depois enviado para dead-letter, sem executar agente ou ferramenta.
7. Cadastros arquivados não recebem a conversa e não impedem um novo contato
   ativo.

O telefone comprova controle do número no canal, mas não substitui autenticação
forte. Ações da Central exigem um único acesso ativo vinculado à Pessoa, com
identidade Clerk e papel admin ou pastor. Uma afirmação escrita na conversa,
como "sou pastor", nunca concede privilégio.

## Matriz efetiva

| Perfil resolvido | Decisão | Presença | Avançar trilha | Vincular célula |
|---|---:|---:|---:|---:|
| Contato | não | não | não | não |
| Membro | não | não | não | não |
| Líder ou pastor apenas por cadastro/célula, sem acesso utilizável | não | não | não | não |
| Líder de célula ou multiplicador com acesso utilizável | não | não | não | não |
| Líder G12 com acesso utilizável | não | não | sim | não |
| Líder de consolidação com acesso utilizável | sim | não | sim | não |
| Admin com acesso utilizável | sim | não | sim | sim |
| Pastor com acesso utilizável | sim | não | sim | sim |
| CSIM, acesso duplicado ou tool desconhecida | não | não | não | não |

Toda ferramenta precisa estar registrada em uma capacidade explícita. A ausência
de registro nega a execução. Nesta fundação, as ferramentas existentes só podem
alterar a própria Pessoa reconhecida pelo número. Ações sobre terceiros exigirão
um fluxo posterior com confirmação e autorização próprias. `marcar_presenca`
permanece desabilitada até usar o mesmo modelo de reuniões do fluxo humano.

## Comportamento

O master define nome, tom e comportamento padrão, depois revisa a configuração
de cada igreja. A igreja fornece e valida sua própria credencial e modelo de IA.
Esses dois requisitos são independentes:

- credencial válida não liga o agente;
- configuração ausente ou inativa impede qualquer resposta automática;
- somente o master pode ativar a configuração da igreja;
- a configuração altera estilo, nunca identidade, tenant, papel, autorização ou
  ferramentas.

O LLM não recebe o texto bruto da mensagem durante o refino. Ele recebe apenas a
resposta-base determinística. Nesta fase, somente onboarding pode ser refinado.
Consentimento, opt-out, relatório, handoff e confirmações de efeito permanecem
determinísticos.

## Tratamento humano

O agente pausa quando:

- a conversa está em atendimento humano;
- a Pessoa fez opt-out;
- a Pessoa está marcada como sem interesse;
- falta credencial válida;
- falta configuração ativa;
- a identidade telefônica é ambígua;
- uma ferramenta não está registrada ou o perfil não possui capacidade.

## Gate de produção

Esta decisão não ativa o agente e não abre envios externos. Antes do primeiro
teste real por uma igreja piloto:

1. revisar o comportamento padrão no console master;
2. criar a configuração da igreja com ativo igual a falso;
3. validar a credencial BYO sem expor a chave;
4. executar testes por perfil e cross-tenant;
5. comprovar handoff, opt-out, duplicidade, restart do webhook e dead-letter;
6. escolher uma conversa e um número autorizados;
7. obter autorização humana específica para ativar o agente e o envio necessário.

## Fora do escopo

- Hermes;
- BotConversa;
- broadcast;
- memória conversacional durável;
- RAG documental;
- criação ou transferência de célula pelo agente;
- qualquer migration ou ativação em produção.
