# Resumo privado por conversa — fatia 3

Geração candidata, desligada. Não cria ficha por pessoa nem implementa pedido
de exclusão. A [retomada privada da fatia 4](RETOMADA-PRIVADA.md) acrescenta um
consumidor separado, também desligado por padrão. Deploy, migration remota,
credencial e ativação: **não verificados**.

## Conteúdo e acesso

Uma versão corrente por conversa, pessoa atribuída exclusivamente pelo servidor,
referências compostas às mensagens e suas datas. Rótulo: **derivado, pode errar**.
Não constitui conhecimento oficial nem prova de cadastro, consentimento ou ação.

O primeiro vocabulário é intencionalmente estreito: perguntas exatas de horários
de culto e matrícula/informações de UV/CD (`private_summary_topic`). A conversa
inteira deve ter de 1 a 40 mensagens de texto recebidas do contato, todas nesse
vocabulário. Qualquer saída, texto livre, terceiro, ambiguidade, mídia,
transcrição, contexto privilegiado ou associação/proposta de oração recusa a
conversa **antes** do modelo. Esse corte produz falsos negativos deliberados;
não promete classificar semanticamente qualquer conversa. Ampliar o vocabulário
exige mudança global versionada, avaliação sintética e revisão de privacidade.

O provedor recebe somente os códigos operacionais permitidos, sem nomes,
telefones, texto original, identidade ou correção humana. Sua saída estrita
seleciona um assunto das fontes; o servidor produz o texto em pt-BR, até 1.000
caracteres. Saída inválida, duplicada, cortada pelo provedor ou fora das opções é
recusada; não há truncamento, fallback ou retry externo automático.

A API exige sessão web, tela inbox e admin/pastor atualmente autorizado à origem.
A função de elegibilidade também exige leitor autorizado ou worker, impedindo sondagem por usuário comum. O banco revalida subject, usuário ativo, papel, matriz inbox, pessoa ativa,
telefone canônico não ambíguo, origem e revisão. Apagar não concede leitura.
Não há endpoint por pessoa nem busca/agregação. Respostas usam `private, no-store`.

- `GET /conversations/{id}/private-summary`: versão, estado, texto, fontes e datas.
- `PATCH /conversations/{id}/private-summary`: `version`, `correction` ou
  `incorrect: true`. Versão divergente retorna 409. Correção também deve ser uma
  pergunta operacional reconhecida; texto livre é recusado com 422.
- `POST /conversations/{id}/private-summary/generate`: solicita tarefa durável,
  retorna 202/ID; recusa origem não elegível ou release desligada com 409.

Correção é restrição vigente na mesma linha, não histórico de versões. Ela
prevalece inclusive se for feita durante a chamada externa. Nova mensagem comum
suspende o derivado; regeneração válida reaplica a correção sem chamar o modelo.
Marcar incorreto impede geração automática de texto, até outra correção humana.
Excluir/proteger fonte remove também correções derivadas. Não há checkpoint,
expiração de 30 dias ou retenção de versões antigas.

## Worker, orçamento e gates

`private_summary_tasks` persiste IDs, revisão, geração, solicitante e estado;
nenhum prompt ou conteúdo. O cron consome tarefas, com descoberta nominal e
processamento tenant-scoped no papel `authenticated` NOBYPASSRLS. Duplicatas não
repetem a chamada. Novo pedido explícito recoloca a mesma tarefa `refused/budget_or_credential` em `queued`, sem duplicar; o worker revalida gates, credencial e orçamento antes de qualquer chamada. Outras recusas, inclusive resultado ambíguo do provedor, não são reenviadas. Reserva mensal atômica por igreja antes de cruzar o provedor;
falha, timeout ou crash conservam a reserva. Tarefa `running` abandonada por mais
de dois minutos vira `refused/provider_outcome_unknown`; não se presume sucesso,
não há nova chamada automática nem devolução de orçamento.

O teto usa microdólares de reserva conservadora: 100.000 (= USD 0,10) por tentativa,
para entrada limitada a códigos (menos de 2.048 bytes) e saída de até 512 tokens,
sem retries, nos três modelos fixos da allowlist existente. É um teto interno de
reserva, não conciliação de fatura. Preços/modelos devem ser reconferidos antes de
qualquer ativação; mudança de preço exige ajustar a reserva/allowlist primeiro.
A reutilização não chama o gerador: o consumidor separado da fatia 4 usa o
turno normal, sujeito ao custo e gates desse turno.

Todos precisam permitir geração: `APPROVED_RELEASE_ID` (**None**),
`APPROVED_IGREJA_IDS` (**vazia**), `private_summary_settings.enabled` (**false**) e
`monthly_limit_microusd` (**0**, nenhuma geração). Configuração ausente também
nega. Não há API para abrir esses gates. `ALLOW_REAL_SENDS` continua obrigatório
para o adaptador OpenAI real. `AgentConfig.ativo` e demais gates não são alterados.
Testes substituem exclusivamente o provedor e gates da fatia com valores
sintéticos; jamais ativam envios reais. Estado entregue: custo externo zero.

Leitura sob barreira compartilhada e lock de conversa → reserva/claim/commit →
chamada **sem sessão/transação/lock de igreja** → nova barreira e lock → revalidar
origem/revisão/geração/pessoa/credencial/gates/solicitante → publicar/commit.
Correção vigente é relida sob o lock de publicação. Exclusão durante a chamada
remove tarefa e impede ressurgimento local; não desfaz o que já foi enviado.

## Exclusão, invalidação e release

A migration `20261019_120001_private_conversation_summaries.sql` acrescenta FKs
compostas, ENABLE/FORCE RLS, revokes e funções SECURITY DEFINER com search_path
fixo. Amplia a mesma `private_delete_content` da #518: conta/remove resumos e
suas correções/fontes/tarefas antes de apagar mensagens, nos escopos conversa,
pessoa e igreja. Recibo declara texto já enviado ao provedor fora do alcance,
além de backups/cópias externas. A retenção externa permanece não verificada.

Triggers invalidam resumos/tarefas por edição/remoção da fonte; proteção de oração
ou criação de proposta apaga derivados; entrada de áudio (origem e âncora viva) e mensagem de mídia também apagam resumo, correção, fontes e tarefas. Remover a origem sensível não restaura o derivado. Troca de pessoa/telefone/responsável, arquivamento, opt-out e
mudança de célula/líder/vínculo canônico removem derivados, sem transferi-los.
O vínculo pessoa/conversa é sempre revalidado; identidade errada nunca é reparada
pelo modelo. Fonte movida para outra conversa é recusada pela FK composta.

Aplicar a cadeia ativa via `backend/scripts/migrate.py`, primeiro em PostgreSQL
sintético. Conter consumidores na atualização/rollback; publicar somente com
schema compatível. Rollback comentado restaura a função anterior antes de remover
tabelas/triggers; conteúdo apagado não é recuperável pelo rollback. Sem execução
remota autorizada nesta entrega. Revisão de Sarah: **RLS, migration e privacidade**.
