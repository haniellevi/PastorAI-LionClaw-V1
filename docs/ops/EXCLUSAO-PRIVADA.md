# Exclusão privada — conversa, pessoa e igreja

Código candidato; aplicação/deploy/operação remotos **não verificados**.
Não autoriza release, acesso remoto ou alteração de gates. Testes usam dados
fictícios e provedores simulados.

## Contrato e autorização web

- `DELETE /conversations/{id}` continua admin-only e responde com recibo.
- `DELETE /contacts/{id}/private-content` apaga o acervo privado da Pessoa.
- `DELETE /igreja/private-content` apaga o acervo privado da igreja autenticada.
- Os dois últimos exigem JSON com `operation_id` UUID gerado pelo cliente e
  `confirmacao: "EXCLUIR CONTEUDO PRIVADO"`. Repetir o mesmo identificador
  recupera o recibo original; outra exclusão de conteúdo novo exige outro UUID.
- `GET /igreja/private-deletions/{receipt_id}` acompanha progresso. O GET anterior
  `/conversations/{id}/deletion-receipt` permanece disponível.

O backend exige admin autenticado web; a função SQL revalida subject, vínculo
admin ativo e igreja. O admin apaga conteúdo pastoral sem ganhar SELECT desse
conteúdo. Recibos contêm somente IDs, geração e contagens. Nenhum texto,
telefone, transcrição, caminho ou hash de conteúdo entra no recibo.

**Escopo privado:** preserva cadastros oficiais de Pessoa/igreja,
`pessoas.optout` e o ledger `consentimento_finalidade_evento`.
Os eventos de aceite de áudio V1b (`cell_report_audio_consent_events`) são
apagados com a conversa por FK CASCADE; ausência de aceite vale como sem
consentimento e exige novo aceite antes de processar áudio. Não muda o contrato de
`archive_pessoa`: arquivamento continua uma ação distinta. Exclusão cadastral
ou reset global continuam no [runbook nominal](TENANT-DELETION-RESET-RUNBOOK.md).
Esse caminho agora chama a mesma limpeza privada **antes** das cascatas,
na mesma transação e sem provedores. Seu contrato cadastral de consentimento
não foi alterado. Não existe endpoint web para reset global.

## Retenção V1b — decisão pastoral 15

Em 18/10/2026, Raniel decidiu retirar a exclusão automática em 24 horas
somente para capturas sob consentimento `v2`: `cell_report_audio_inputs`
conserva mídia no Storage, transcrição e hashes até
exclusão pelo admin (conversa/pessoa/igreja), ou pedido da pessoa aprovado pelo
admin. Revogação de transcrição, cancelamento, confirmação do relatório e
handoff encerram o processamento, sem apagar o conteúdo já registrado. O aviso
de aceite passa a informar essa retenção. O consentimento passa à versão `v2`:
aceite `v1` não autoriza novo processamento; exige novo aviso entregue e novo
`ACEITO AUDIO`, sem reativar áudio anterior ao aceite. O relatório oficial é independente.

A exclusão de conversa da PR #509 é ampliada nesta candidata para pessoa/igreja. Não há nova aprovação
via WhatsApp nem nova superfície de leitura. O cron continua processando tarefas
de exclusão aprovadas, recuperando handoffs e purgando capturas pré-v2 com
gates fechados. A purga automática mantém a promessa de até 24h para `v1`,
versões desconhecidas e registros sem versão. O critério é o snapshot
`cell_report_audio_inputs.consent_version`, gravado a partir do aceite na
captura. Somente o valor exato `v2` dispensa TTL; aceite vinculado renovado
não reclassifica registros anteriores. Sem snapshot, aplica-se purga
conservadora, mesmo com aceite vinculado v2; não se infere retenção por data.
A seleção e o claim sob lock aplicam o mesmo filtro; retry de Storage e
tombstone de replay permanecem. A exclusão oficial apaga ambas as versões.
Falhas de upload já registradas também ficam retidas; limpeza de objeto que
nunca virou registro não é substituída por TTL. A fronteira de uploads tardios
da exclusão oficial permanece preservada.

`expires_at` permanece como prazo de processamento e de purga para pré-v2
(no máximo 24h após `received_at`), assim como estados/colunas
de purga por compatibilidade. Sem migration ou backfill destrutivo; registros
já purgados não são recuperados nem reativados por esta mudança.

**Acesso conferido no código:** RLS ENABLE/FORCE em `cell_report_audio_inputs`,
policy `cell_report_audio_inputs_worker_only`: igreja corrente e worker
`authenticated` sem subject; o usuário HTTP não ganha SELECT da transcrição.
O serviço revalida igreja e autorização para processar. No painel não há leitura
direta dessa tabela: o inbox mantém os endpoints de mensagens e URLs assinadas
curtas, com `require_screen("inbox")`, autorização da conversa (admin/pastor com visão completa; responsável
somente na conversa atribuída) e igreja; áudio
referenciado em mensagens segue essa permissão. Resumos já presentes em mensagens
seguem o mesmo acesso. Nenhuma policy, permissão ou tela mudou. Isso é inspeção
do código candidato, não comprovação de políticas aplicadas remotamente.

**Risco:** maior volume privado retido e custo de Storage; monitorar capacidade
no procedimento operacional autorizado. A retenção externa de OpenAI/Evolution
e backups não é alterada nem verificada por esta fatia.

## Camadas, inventário e recibos anteriores

A transação enumera e apaga mensagens (incluindo protegidas), logs vinculados,
entradas V1b com âncoras vivas ou imutáveis e suas transcrições/hashes/leases.
Pessoa inclui entradas V1b órfãs identificadas pela pessoa; igreja inclui todas.
Conversas sem vínculo são identificadas por fontes privadas tipadas ou pela
chave canônica completa de telefone (+55/nono dígito), nunca só por sufixo.
Cascatas removem desafios/provas de identidade, propostas/recibos de ação,
drafts de relatório, avisos/eventos de áudio e pedidos/propostas de oração.
O recibo enumera essas camadas; associações de mensagens protegidas da #515 também são contadas. `transcricoes` conta texto presente;
`entradas_audio` conta entradas, mesmo ainda não transcritas.

| Tabela / referências | Conteúdo e tratamento na exclusão |
|---|---|
| `agent_conversation_logs.conversation_id` (anulável, SET NULL) | Payload pode conter relatório e `pessoaId`; linhas da conversa são apagadas explicitamente na mesma transação, antes da FK anular a referência. Camada `logs_agente` conta as linhas removidas. |
| `cell_report_audio_inputs.live_conversation_id` / `live_message_id` (anuláveis, SET NULL), âncoras `conversation_id` / `inbound_message_id` | Transcrição, hashes e caminho: remoção explícita por âncoras imutáveis ou vivas, incluindo referências já nulas; mídia enumerada antes da remoção. Camadas `transcricoes` e `midias`. |
| `agent_action_proposals.summary_message_id` / `confirmation_message_id` (anuláveis) | Payload/resumo removidos por CASCADE da conversa obrigatória e das mensagens. |
| `messages`, `agent_identity_challenges`, `agent_identity_proofs`, `agent_action_proposals`, `agent_action_receipts`, `cell_report_drafts`, `cell_report_audio_notices`, `cell_report_audio_consent_events` | FK da conversa obrigatória com CASCADE; nenhum conteúdo fica órfão por SET NULL. |
| `conversations.secretaria_oferta_message_id` / `secretaria_oferta_resposta_message_id` (anuláveis) | Os quatro campos `secretaria_oferta_*` são zerados no mesmo UPDATE antes de apagar mensagens, respeitando CHECKs e as duas FKs NO ACTION. |
| `pedido_oracao_mensagem` | Associação sem conteúdo; removida por cascata da mensagem. Mensagens pastorais e seus caminhos são enumerados dentro da função SECURITY DEFINER, sem SELECT do admin; depois da fila durável, mensagens são apagadas explicitamente para suportar FK composta sem cascata legada. |
| `private_deletion_uploads`, `private_deletion_sends` | Sem FK de propósito: somente IDs, geração e tempos, sem conteúdo/pessoa/telefone. Conservam a fronteira externa após a remoção da origem. |

Resumos, checkpoints e vetores privados duráveis ainda não têm tabelas ativas:
contagem zero, sem implementação de memória nova nesta fatia. Registros
oficiais publicados não são convertidos em memória nem apagados por este reset.

Recibos coletivos incluem as tarefas e envios de recibos anteriores associados,
sem transferir ou duplicar tarefas. A igreja inclui todos os anteriores;
Pessoa inclui sua proveniência e recibos antigos sem proveniência de pessoa
(inclusive resets da igreja), conservadoramente. Isso pode manter o recibo da
pessoa pendente por limpeza histórica de outro contato. Contagens agregam
camadas diretamente apagadas por cada operação, sem duplicar transitivamente.

Logs sem conversa não permitem provar a pessoa de origem. Exclusões coletivas
limpam seus **payloads** na igreja inteira, conservando IDs/eventos de dedupe:
apagar o marcador operacional poderia provocar reenvio. Logs vinculados a
outra conversa/pessoa e todos os dados de outra igreja permanecem intactos.

## Concorrência e limpeza externa

Ingestão adquire barreira advisory compartilhada por igreja antes dos locks de
Pessoa/conversa. Exclusão adquire a exclusiva antes dos locks; pais usam KEY
SHARE, compatível com FKs de mensagens. Conversas são bloqueadas em ordem de
UUID; sua geração avança antes da remoção. Writers existentes revalidam geração
sob lock. Novos eventos após o snapshot podem abrir conversa nova; não é uma
suspensão permanente de atendimento. Replay de eventos excluídos é recusado por
token opaco derivado da identidade do evento, nunca do conteúdo.

Tarefas de Storage são gravadas antes de eliminar referências. O cron limitado
usa `remove_tenant_media` estrito e retry/backoff. Sucesso apaga o caminho;
falha conserva somente código fechado `storage_unavailable`. Recibos/tarefas,
dependências e barreiras sobrevivem à remoção cadastral da igreja.

Upload iniciado tem ownership durável; tarefa não conclui enquanto ele existir.
Retorno tardio encontra a tarefa por `source_id`, inclusive sem conversa viva,
reabre limpeza e remove ownership atomicamente. Falha/timeout com resultado
externo desconhecido conserva pendência; lease vencida não prova fim do efeito.

Envio tem marcador durável criado com `ia_em_transporte`; geração/prazo são
revalidados antes do HTTP e ao persistir resultado. A janela de 60s autoriza
início, mas **não conclui recibo por tempo**: `pendente_envio` permanece até o
transporte retornar e liberar ownership. Não há reenvio após expiração.
Processo perdido exige reconciliação explícita; nunca apagar marcador somente
para deixar o recibo verde. HTTP iniciado pode ter chegado ao provedor.

O cron usa `process_storage_tasks` antes do gate de envios, com purga automática por prazo somente para capturas pré-v2. Cada passagem é limitada; usa escopo de igreja, exclusão estrita
`remove_tenant_media`, locks e retry com backoff exponencial de 30 s a 1 h.
Falhas guardam apenas código fechado `storage_unavailable`; a tarefa continua
pendente. Após sucesso o caminho é apagado da tarefa. O recibo só aparece
`concluido` quando todas as tarefas estiverem concluídas e não houver envio
com ownership ainda não reconciliado, mesmo após expiração.

## Release, RLS e limites

Aplicar na ordem `20261018_090000_exclusao_privada.sql` →
`20261018_120000_prayer_message_privacy.sql` →
`20261019_090001_exclusao_privada_pessoa_igreja.sql`, via `scripts/migrate.py`,
antes de publicar novos writers/cron. A última substitui a função de conversa
por um wrapper do mesmo caminho de pessoa/igreja, conservando a enumeração
SECURITY DEFINER e exclusão explícita de mensagens protegidas da #515.
A cadeia real completa é exercitada em PostgreSQL sintético, incluindo RLS,
associações de oração, mídia e retenção V1b v1/v2. Conter a ingestão da versão
anterior durante a troca: writers antigos ainda não tomam a barreira compartilhada.
O rollback de 090001 restaura a função de 120000; somente ao reverter depois
120000 e remover suas associações restaura-se a versão 090000.

Tabelas novas têm `igreja_id`, ENABLE/FORCE RLS, FKs compostas e revokes.
O helper interno só é executável pelo proprietário SQL; HTTP chama wrapper
que revalida admin. Processing mantém o escopo tenant NOBYPASSRLS da #509.

**Pré-requisitos antes de qualquer ativação:** procedimento de reconciliação
de upload ambíguo necessário; resolver explicitamente identidade do worker e
retenção de tombstones. Pendências técnicas: identidade de worker ainda segue o
padrão servidor confiável sem subject da #509; reconciliação automática de
upload que falhou é ausente (falha pode ser ambígua); tombstones não expiram
sem política aprovada e horizonte comprovado de replay/restauração. Logs sem
âncora não têm proveniência individual retroativa; a limpeza é conservadora.
O frontend apresenta ID/estado do recibo no feedback da exclusão; não há nova
central de acompanhamento persistente no painel.

Recibo cobre banco operacional e objetos referenciados, não backups, cópias de
provedor ou objetos órfãos anteriores sem referência. A fila legada de reset
mantém a limpeza do namespace completo. Restauração exige reaplicar exclusões
posteriores ao snapshot antes de reabrir consumidores. Aplicação em PROD,
retenção jurídica e execução nominal continuam gates humanos separados.

O owner das funções deve ignorar FORCE RLS; conferir no release autorizado,
com backup. Não publicar contra schema anterior. Conter consumidores, drenar
tarefas e preservar recibos/barreiras antes do rollback. Backups, cópias de
provedores e seus prazos de retenção não foram verificados nesta entrega.
