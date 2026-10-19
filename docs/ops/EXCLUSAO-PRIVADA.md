# Exclusão privada — fatia 1, conversa

Código candidato; aplicação/deploy/operação remotos **não verificados**. Esta
fatia não autoriza release, acesso remoto nem alteração de gates. Dados locais
são sintéticos; Storage/OpenAI/Evolution são simulados nos testes.

## Contrato e autorização

`DELETE /conversations/{id}` continua restrito a admin autenticado da igreja.
Agora responde `200` com recibo, inclusive na repetição. A função SQL revalida
vínculo admin ativo e igreja do subject autenticado; o serviço não troca o JWT
pelo contexto de worker para ler o V1b. UUID sem conversa/recibo visível dá 404.
`GET /conversations/{id}/deletion-receipt` permite ao admin acompanhar o mesmo
recibo após a exclusão. O frontend atual pode continuar ignorando o body de
sucesso; não se deve interpretar remoção da lista como conclusão do Storage.

O recibo guarda IDs, geração e contagens por camada: encontradas, apagadas,
pendentes e falhas atuais. Mensagens, logs do agente e registros privados V1b são removidos na
mesma transação. Uma entrada V1b conta como uma transcrição/registro derivado,
mesmo quando ainda não transcrita; inclui texto, hashes e leases. Mídias são
objetos únicos por caminho, incluindo ponteiros V1b com referências vivas nulas.
Resumos, checkpoints e vetores ainda ausentes contam zero. Não há texto,
telefone, transcrição, caminho de Storage nem hash de conteúdo no recibo.

## Inventário de referências privadas

Busca por `conversation_id`/`message_id` em models e migrations ativas:

| Tabela / referências | Conteúdo e tratamento na exclusão |
|---|---|
| `agent_conversation_logs.conversation_id` (anulável, SET NULL) | Payload pode conter relatório e `pessoaId`; linhas da conversa são apagadas explicitamente na mesma transação, antes da FK anular a referência. Camada `logs_agente` conta as linhas removidas. |
| `cell_report_audio_inputs.live_conversation_id` / `live_message_id` (anuláveis, SET NULL), âncoras `conversation_id` / `inbound_message_id` | Transcrição, hashes e caminho: remoção explícita por âncoras imutáveis ou vivas, incluindo referências já nulas; mídia enumerada antes da remoção. Camadas `transcricoes` e `midias`. |
| `agent_action_proposals.summary_message_id` / `confirmation_message_id` (anuláveis) | Payload/resumo removidos por CASCADE da conversa obrigatória e das mensagens. |
| `messages`, `agent_identity_challenges`, `agent_identity_proofs`, `agent_action_proposals`, `agent_action_receipts`, `cell_report_drafts`, `cell_report_audio_notices`, `cell_report_audio_consent_events` | FK da conversa obrigatória com CASCADE; nenhum conteúdo fica órfão por SET NULL. |
| `conversations.secretaria_oferta_message_id` / `secretaria_oferta_resposta_message_id` (anuláveis) | Referências dentro da própria conversa removida; não criam camada sobrevivente. |
| `private_deletion_uploads`, `private_deletion_sends` | Sem FK de propósito: somente IDs, geração e tempos, sem conteúdo/pessoa/telefone. Conservam a fronteira externa após a remoção da origem. |

Não foram encontradas outras FKs anuláveis/SET NULL para conversa/mensagem
que conservem conteúdo nessa busca. Isso não declara exclusão da pessoa,
igreja ou de registros oficiais de domínio.

## Persistência e corridas

A conversa é bloqueada antes dos derivados, sua geração avança e a transação
enfileira Storage **antes** de apagar referências. Ingestão comum e upload
humano mantêm o lock da conversa até persistir/commit; o V1b captura a geração
no claim e a revalida sob lock antes de persistir. Registros V1b são apagados,
incluindo âncoras imutáveis, transcrição e todos os hashes da entrada.

A barreira contra replay fica em `private_deletion_event_fences`: somente
identificador opaco de revogação derivado da identidade do evento do provedor,
igreja e recibo. Não retém o ID bruto do provedor, telefone, conteúdo ou hash de
conteúdo. É consultada antes de resolver/criar contato/conversa e novamente
após adquirir o lock da conversa. Essa tabela não é conhecimento nem memória.

Antes de um upload V1b, `private_deletion_uploads` registra em transação própria
IDs e geração; nenhum I/O de Storage acontece nessa transação. A finalização
reabre eventual tarefa de limpeza e remove o registro de upload em uma única
transação. Falha de banco conserva o registro durável, impedindo conclusão
falsa. O retorno tardio não recria áudio, transcrição ou mensagem.

O envio automático registra `private_deletion_sends` com geração na mesma
transação do CAS para `ia_em_transporte`. Antes do HTTP, um lock curto reconfirma
conversa, geração e prazo do marcador e renova a janela completa de 60 segundos
para o POST (sondagens anteriores não consomem essa janela). Marcador já vencido
é recusado. Não há lock de banco durante a rede.
Depois do HTTP, toda transição revalida a geração sob o mesmo lock; conversa
apagada/geração alterada impede confirmação, snapshot ou retorno a pendente.
O marcador é liberado ao terminar, inclusive no timeout do transporte.

A exclusão retorna `pendente_envio` enquanto existir marcador válido. A camada
`envios` conta fronteiras encontradas, resolvidas e pendentes, sem afirmar que
uma mensagem aceita pelo provedor foi recolhida. O prazo durável é de 60 segundos
(o cliente Evolution usa timeout de I/O de 15 segundos); marcador vencido não
autoriza novo HTTP nem persistência. Processo perdido expira a pendência, sem
recolocar o intent em fila: `ia_em_transporte` e a barreira de replay impedem
reenvio. Um HTTP já iniciado pode ter chegado ao provedor; o recibo não atesta
eliminação da cópia externa. Nenhum gate é aberto para reconciliar isso.

## Limpeza e recuperação

O cron usa `process_storage_tasks` antes do gate de envios, assim como a purga
já existente. Cada passagem é limitada; usa escopo de igreja, exclusão estrita
`remove_tenant_media`, locks e retry com backoff exponencial de 30 s a 1 h.
Falhas guardam apenas código fechado `storage_unavailable`; a tarefa continua
pendente. Após sucesso o caminho é apagado da tarefa. O recibo só aparece
`concluido` quando todas as tarefas estiverem concluídas e não houver envio
com marcador válido.

**Upload com processo perdido/resultado desconhecido:** não expirar a barreira
somente pelo relógio. A tarefa fica pendente mesmo após a lease vencer. Uma
retomada autorizada precisa comprovar que o processo/HTTP antigo não pode mais
escrever e reconciliar o objeto antes de finalizar o upload pelo mesmo serviço.
Não remover o registro para fazer o recibo ficar verde. Esta fatia prioriza não
perder exclusão; não automatiza essa decisão operacional ambígua.

Recibos, tarefas, barreiras e registros de upload/envio não têm FK para igreja ou
conversa: sobrevivem à origem. Tarefas e barreiras de evento têm FK composta
para o recibo, impedindo mistura de igreja. Todas as tabelas usam ENABLE/FORCE
RLS. `public`, `anon` e `service_role` não recebem privilégios. O backend faz
descoberta de IDs na sessão cross-tenant nomeada; o processamento ocorre como
`authenticated` sem BYPASSRLS. Esse papel tem apenas leitura de recibos/barreiras,
leitura sem path e atualização de tarefas e SELECT/INSERT/DELETE de uploads,
com policies restritas ao worker sem subject. HTTP admin só lê progresso; o
path é obtido por função exclusiva de worker. A função destrutiva é o único
writer de recibos/tarefas/barreiras e revalida admin no banco.

## Release e limites

Aplicar `20261018_090000_exclusao_privada.sql` antes dos novos writers/cron;
usar `backend/scripts/migrate.py` e o procedimento nominal de release, com
backup. Não publicar este código contra schema anterior. Rollback comentado
exige conter consumidores, drenar tarefas e preservar recibos/barreiras.

O recibo cobre banco operacional e objetos referenciados do bucket privado;
não atesta eliminação de backups, cópias do provedor ou objetos sem referência
anteriores a esta implementação. Prazos dessas cópias dependem do contrato e
procedimento de retenção e **não foram verificados** nesta entrega. Antes de
restaurar backup, preservar as exclusões posteriores ao snapshot e reaplicar
recibos/barreiras/limpeza antes de reabrir consumidores. Exclusão integral da
pessoa e integração igreja/reset pertencem às fatias 2–3; não são declaradas
concluídas por esta PR.
