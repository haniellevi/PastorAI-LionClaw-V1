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

## Painel: reset privado por pessoa — Memória 6, primeira fatia

No inbox, o admin abre **Ver pessoa → Excluir conteúdo privado da pessoa**.
O diálogo identifica a pessoa selecionada e exige digitar exatamente
`EXCLUIR CONTEUDO PRIVADO`. O servidor continua revalidando admin web,
igreja e alvo na rota e no serviço SQL existentes; o botão não concede acesso
a conteúdo protegido. Nenhuma migration, capability do agente ou gate novo.
Gates de geração, retomada, pedidos e efeitos externos permanecem inalterados.

O cliente gera um UUID por operação e mantém o mesmo UUID em tentativas após
falha/resultado ambíguo, enquanto o diálogo desta pessoa permanecer montado na
mesma sessão. Cancelar/reabrir para a mesma pessoa conserva a operação.
Não recarregue a página nem troque de pessoa para tentar novamente após falha:
isso pode criar outra operação. O UUID aparece no diálogo para conferência.
Após recibo válido, limpa conversas/rascunhos locais da pessoa e invalida cargas
em andamento; mantém o diálogo fora do painel desmontado. **Atualizar recibo**
faz somente GET, distingue envio em andamento, limpeza externa pendente e
conclusão operacional, mostrando contagens e ID. Backups e cópias do provedor
permanecem fora do alcance. Não há envio automático à pessoa.

O recibo fica na sessão da tela; recuperação pela interface após reload,
histórico de operações e uma segunda exclusão explícita de conteúdo novo da
mesma pessoa são fatias futuras (as rotas existentes já suportam novo UUID).
Não confundir reset privado com exclusão cadastral ou reset global.

## Painel: reset privado por igreja

No Hoje do admin, o reset da igreja usa a rota e o serviço/fila de exclusão
privada já existentes. O admin precisa estar ativo (`status='ativo'`) e digitar
o nome canônico exato da igreja e `EXCLUIR CONTEUDO PRIVADO DA IGREJA`; o
backend compara o nome com o cadastro da igreja antes de criar a operação.
Cada operação usa UUID idempotente. Repetição recupera o mesmo recibo; uma nova
operação exige novo acionamento e nova confirmação. O recibo é cumulativo pelas
dependências de exclusão existentes. Cadastros, opt-out, consentimentos e o
ledger de consentimento são preservados. Os pedidos de exclusão privados
pendentes da igreja são aprovados e vinculados ao recibo do reset na mesma
transação, deixando de aparecer como pendentes ou vencidos no painel. A migration
preserva as policies e os grants existentes; nenhum gate novo é introduzido.

## SLA dos pedidos de exclusão

O painel administrativo mostra a idade do pedido e destaca o vencimento; Hoje
exibe a contagem vencida. A política atual é
`PRIVATE_ERASURE_SLA_POLICY_VERSION='v1'` e `PRIVATE_ERASURE_SLA_DAYS_V1=15`.
O prazo afeta somente a apresentação e as contagens: não aprova, recusa ou apaga
pedidos automaticamente.

**Inventário restante de Memória 6:** visão admin agregada de flags/contagens
sem conteúdo/PII; registro de pedido pela equipe (decisão 28); indicador na
Central de pendências. O reset por igreja e o SLA são candidatos locais sem
release ou ativação. Nenhuma expiração/recusa automática libera memória. Esta
fatia **não conclui Memória 6**.
Deploy, banco remoto, funcionamento em produção e ativação: **não verificados**.

## Trilha de vínculo Pessoa (#543) após exclusão

Contrato atual conferido no código; produção **não verificada**. Esta seção não
cria retenção, purga nem anonimização.

- **O que fica:** cada vínculo/desvínculo entre acesso e Pessoa grava em
  `team_pessoa_eventos` ([migration](../../backend/migrations/20261025_100000_team_pessoa.sql))
  `id` técnico, `igreja_id`, `actor_id` (admin), `usuario_id`, `pessoa_id`,
  `operacao` e `criado_em`, sem nome, e-mail ou telefone. A tabela não tem FKs
  de propósito, e os caminhos atuais conferidos (exclusão privada, exclusão da
  igreja, reset global e arquivamento) a preservam. Não há prazo de retenção
  definido.
- **Reset privado** (conversa, pessoa ou igreja) e arquivamento de Pessoa não
  tocam a trilha; como os cadastros ficam, os UUIDs continuam resolvíveis.
- **Exclusão cadastral da igreja ou reset global**
  ([runbook nominal](TENANT-DELETION-RESET-RUNBOOK.md)) removem igreja e
  Pessoas, mas as linhas da trilha ficam com os UUIDs originais. Contas de
  platform admin são preservadas, então seus UUIDs continuam resolvíveis.
- **Reconciliação excepcional** de duplicidade
  ([release](RELEASE-LOTE-2026-10.md)) grava em `platform_audit_log` UUIDs e
  hashes técnicos (operação, igreja, Pessoa, contas mantida e corrigida, admin
  da igreja, operador, hash do payload e SHA do release); também sem FK e
  preservado nesses caminhos.
- **Quem lê:** não há endpoint de leitura de `team_pessoa_eventos`. O acesso
  continua sujeito às RLS e ACL atuais; não presumir que excluir a igreja torne
  essa trilha inacessível. Leitura operacional somente por procedimento
  autorizado. `GET /admin/audit` expõe o `detalhe` de `platform_audit_log` a
  platform admins, nas últimas 1 a 200 entradas.
- **Limite:** UUID sem texto continua sendo identificador e pode ser
  correlacionado com qualquer registro ou cópia que guarde o mesmo ID (outros
  cadastros preservados, auditorias, recibos, logs, exports, backups). Esta trilha **não** é
  anonimizada pela exclusão; não declarar exclusão completa ao solicitante.

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

### Áudio de oração — decisão pastoral 15

Após iniciar explicitamente a coleta de oração, o contato pode enviar áudio.
O arquivo permanece em `messages.media_path`, protegido desde a transação de
entrada pela associação `pedido_oracao_mensagem`. Não há transcrição automática,
entrada V1b nem TTL de mídia: expiração/cancelamento da coleta não apagam áudio.
O resumo de confirmação identifica o pedido em áudio, sem inventar seu conteúdo.
Pedidos com áudio aceitam somente destinatários pastores. A proteção do inbox
também restringe a pastores coletas legadas com áudio anteriormente compartilhadas
com líder; mensagens de texto sem áudio conservam a regra anterior.

A exclusão administrativa de conversa/pessoa/igreja enumera o caminho do áudio
na fila `private_deletion_tasks` antes de remover a mensagem, sem conceder leitura
pastoral ao admin. Pedido de exclusão da pessoa depende de aprovação do admin;
esta fatia não cria canal de aprovação pelo WhatsApp. Áudio enviado antes da
coleta explícita ou após seu prazo não é reclassificado por esta implementação.
Migration candidata: `20261020_100000_prayer_audio_privacy.sql`; aplicação e
operação remotas **não verificadas**. Gates permanecem desligados. Riscos de
volume retido e retenção nos provedores/backups seguem os limites acima.

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

A fatia 3 candidata acrescenta `private_conversation_summaries`, correções vigentes,
`private_summary_sources` e `private_summary_tasks`: exclusão nos três escopos
conta os resumos e remove os derivados antes das fontes. Texto já enviado ao
provedor é declarado fora do alcance do recibo. Checkpoints e vetores seguem
sem tabelas ativas/contagem zero. Ver [resumos privados](RESUMOS-PRIVADOS.md). Registros
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

Reset manual por pessoa também atende o pedido pendente da mesma pessoa/igreja:
na mesma transação, usa o estado existente `aprovado`, com administrador, data e
recibo do reset (sem conteúdo). A aprovação posterior devolve esse recibo;
a recusa retorna conflito e não reabre memória apagada. A limpeza externa pode
continuar pendente no recibo. Repetir uma operação antiga não encerra pedidos
novos. Migration `20261027_100000_reset_settles_erasure_requests.sql` deve ser
aplicada após `20261022_100000`, antes do backend/painel desta correção.
Nenhuma migration anterior foi editada; policies RLS e permissões são preservadas.

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
Resposta 2xx do Storage após o prazo (`StorageLateSuccess`, com resposta e
cliente fechados sem erro) prova a gravação: resolve a ownership pelo mesmo
caminho atômico, mas a cadeia de áudio falha como antes (handoff conservador
`ambigua`/`externo_ambiguo`), sem orçamento, transcrição ou resposta. Só resolve
se o caminho devolvido for exatamente o do claim, na igreja do claim; caminho
divergente mantém ownership e interrompe a cadeia sem apagar o objeto devolvido.
Timeout, erro de transporte/fechamento, 3xx/4xx/5xx e processo perdido
continuam ambíguos. Falha ao finalizar não é repetida: a transação atômica
decide (o commit pode ter ocorrido com retorno incerto). Esta fatia não resolve
uploads realmente ambíguos, identidade do worker nem política de tombstones.

**Reconhecimento positivo de upload commitado sem resposta** (candidata local,
migration `20261030_110000_private_upload_attempt_witness.sql`, só em PostgreSQL
sintético; não aplicada em PROD). Cada tentativa recebe um token UUID aleatório,
gravado e commitado com a ownership antes do POST e enviado como `x-metadata`
(JSON estrito em base64, só esse token; nada pastoral). O POST continua único,
sem retry, e o finish normal/tardio remove só a ownership do próprio token
(CAS; uma tentativa nova nunca é liberada por um finish antigo). No ciclo de
limpeza, antes de `process_storage_tasks`, `reconcile_upload_attempts` consulta
em lote limitado (10 por tick) apenas ownership com token que bloqueia tarefa
pendente: descoberta cross-tenant devolve só IDs; leitura do token/caminho e
mutação usam o login dedicado com escopo da igreja, sem transação ou lock aberto
durante o `GET /object/info/authenticated` (um por consulta, sem retry). A
reserva da consulta trava só a linha da ownership (agenda) e lê tarefa/caminho
sem lock, sem esperar segurando outro lock. O GET roda em `httpx.AsyncClient`
sob um único prazo cancelável de 5 s (`asyncio.timeout`) que cobre conexão,
cabeçalhos e corpo e fecha a conexão ao estourar, sem thread residual; servidor
que goteja ou não responde é cortado no prazo e conta como não provado. Fica
fora do prazo apenas a resolução DNS do sistema (`asyncio.run` espera a thread
do resolvedor ao encerrar, com teto interno de 300 s do asyncio); não há prova
de limite absoluto do sistema operacional. Corpo bruto sem compressão
(`Accept-Encoding: identity`) de até 16 KiB. Por item do lote, o progresso do
heartbeat avança após no máximo ~5 s de GET mais 5 s de `lock_timeout`.
Só libera com HTTP 200 e caminho, bucket e token exatos, `version` UUID,
`is_versioned` e `is_delete_marker` falsos e `archived_at` nulo presentes; em
nova transação de liberação, toma o lock do recibo antes de tarefa/ownership
(ordem da limpeza e do finish), revalida tarefa pendente e mesmo caminho e
remove a ownership pelo token. Erro antes do COMMIT conserva a ownership; ACK
de COMMIT incerto deixa o resultado desconhecido, seguro porque só se libera
tentativa já provada commitada. A limpeza estrita então
apaga o caminho. Ausência (`NoSuchKey`, HTTP 400 neste Storage), outro token,
metadata vazia, versionamento, 3xx/4xx/5xx, timeout, JSON inválido ou tempo
decorrido **nunca** liberam: o intervalo (60 s dobrando até 1 h) só agenda a
próxima leitura. Ownership legada (token nulo), upload abortado ou ainda em voo e
ownership sem tarefa pendente continuam retidos, sem liberação automática.
O testemunho prova o commit da linha da tentativa, não os bytes; duplicata
idêntica do mesmo POST não é distinguível pelo token (mesmo limite do 2xx). Prova
física só contra storage-api público `6dd28b4` compilado localmente; versão,
gateway (`x-metadata`, rota/forma do info), `versioning_status` DISABLED desde
sempre do bucket e ausência de outro writer no prefixo, no Supabase hospedado,
**não verificados** e pré-requisitos do release. Rollback comentado na migration:
reverter antes da `20261030_100000`; ownership retida vira legada e continua
bloqueando o recibo.

Envio tem marcador durável criado com `ia_em_transporte`; geração/prazo são
revalidados antes do HTTP e ao persistir resultado. A janela de 60s autoriza
início, mas **não conclui recibo por tempo**: `pendente_envio` permanece até o
transporte retornar e liberar ownership. Não há reenvio após expiração.
Processo perdido exige reconciliação explícita; nunca apagar marcador somente
para deixar o recibo verde. HTTP iniciado pode ter chegado ao provedor.
Na candidata abaixo, só o login `private_send_runtime` libera o marcador.

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
antes de publicar novos writers/cron. Na cadeia ativa completa, preservar também
as migrations intercaladas: `20261018_090000` < `20261018_100000` <
`20261018_110000` < `20261018_120000` < `20261018_130000` <
`20261018_140000` < `20261019_090001`, sem timestamps duplicados.
Fixtures de inbox que usam schema isolado precisam instalar também `090001`:
`create_all` não cria `private_delete_scope(uuid,text,uuid,uuid)`, chamada pelo
serviço atual, e funções de outro schema não substituem essa dependência.
A última substitui a função de conversa
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

### Identidade do runtime de Storage privado (tarefas e uploads)

Candidata local, migration `20261030_100000_private_storage_worker_identity.sql`
(aplicada só em PostgreSQL sintético; não aplicada em PROD). Tarefas de limpeza e ownership de upload de áudio passam a usar
somente o login `private_storage_runtime`, configurado em
`PRIVATE_STORAGE_DATABASE_URL`, sem fallback para `DATABASE_URL`. O papel nasce
NOLOGIN, sem senha, NOINHERIT, NOBYPASSRLS, sem superuser/createdb/createrole/
replication nem memberships. Papel preexistente é recusado se tiver atributo que
amplie a identidade, membership, objetos próprios, grants, policies ou default
ACLs neste banco, grant sobre o próprio banco (ex.: CREATE), ACL de parâmetro
(`GRANT SET ON PARAMETER`) ou de tablespace, ou se for dono de objeto
compartilhado. Objetos e grants de outros bancos do cluster pertencem a eles:
são aceitos e nunca alterados daqui; a migration recusa, não corrige o papel. A migration não é
idempotente por si: reaplicar só depois do rollback, via `migrate.py`.

A identidade é o próprio login (`session_user`), comprovada em cada transação,
inclusive após commit: o cliente fixa `search_path = pg_catalog, public, pg_temp`
(`pg_temp` explícito por último, para tabela TEMP homônima não sombrear) e o GUC de igreja com `pg_catalog.set_config` local antes de qualquer consulta e
prova login, `current_user`, atributos, `row_security` e esse `search_path`.
Opções da URL, defaults do papel, schema ou TEMP homônimos não mudam a
resolução de nomes; as funções da migration usam o mesmo caminho. Não há `SET ROLE` nem GUC como identidade; o checkout do pool só
descarta conexão com GUC de igreja persistido. Dentro das funções SECURITY
DEFINER `current_user` é o dono: elas conferem `session_user`, LOGIN ativo e
os atributos do login; NOLOGIN passa a recusar também conexões já abertas,
mas não as encerra (contenção continua operacional).

Grants: SELECT/UPDATE nas colunas já usadas de `private_deletion_tasks`,
SELECT/DELETE em `private_deletion_uploads`, RLS por igreja (GUC da transação)
e execução de quatro funções: descoberta só de IDs e recibo, caminho da tarefa,
início de upload (recusa campos nulos, trava a geração da conversa e insere a
ownership na mesma transação, sem acesso do papel a conversas) e verificação do
login. Nenhum acesso a conversas, mensagens, pessoas ou transcrições.
`authenticated` perde o ramo de worker sem subject nessas duas tabelas e na
função de caminho; o admin web mantém o progresso do recibo.

Sem o login comprovado, o dispatch V1b não reivindica **novas** entradas de
áudio: elas ficam pendentes, sem download, upload nem transcrição. Recuperação
de handoffs, reenvio de respostas já preparadas e os demais envios do cron e do
queue continuam. Sem credencial, a limpeza de Storage não roda e os recibos
permanecem pendentes.

Conexão: o usuário da URL pode ser `private_storage_runtime` (direta) ou a forma
do pooler compartilhado Supabase `private_storage_runtime.<project-ref>` (ref de
20 minúsculas/dígitos; [documentação](https://supabase.com/docs/guides/database/connecting-to-postgres)).
Isso é só formato: a prova continua sendo `session_user`/`current_user` exatos no
banco. Endpoint, modo (sessão/transação) e rede do ambiente hospedado não foram
testados e precisam ser validados no release; esta fatia não presume IPv6 nem
add-on.

O reconhecimento positivo acima só age sobre tarefa pendente da fonte; ownership
cuja tarefa já esteja concluída não é descoberta e continua retida (conservador).
A `20261030_110000` acrescenta duas funções (início com token e descoberta por
IDs) e UPDATE só das colunas de agendamento da ownership, nunca do token.

Release: conter consumidores antigos, backup, aplicar via `migrate.py`,
provisionar LOGIN/senha e configurar só no cron sob autorização nominal
(ver "Distribuição" na seção seguinte), publicar o código, provar a identidade
e retomar. Limites: envios (exceto a liberação, na seção seguinte), fences de
evento e tarefas de resumo seguem o padrão anterior de servidor confiável; o
dono/superuser do banco e operadores com CREATEROLE ou ADMIN sobre o papel
continuam podendo alterá-lo ou agir como ele. Rollback comentado na migration,
executável e ensaiado em PostgreSQL sintético (aplicar → rollback → reaplicar):
recusa LOGIN provisionado antes de qualquer mudança, restaura o contrato
anterior e só remove o papel se nenhum outro banco depender dele, sem tocar em
grants de outros bancos. Exige consumidores contidos e ownership drenada.

### Identidade da liberação de envios (`private_deletion_sends`)

Candidata local, migration `20261030_120000_private_send_release_identity.sql`
(só PostgreSQL sintético; não aplicada em PROD). INSERT com o CAS
`ia_pendente → ia_em_transporte`, renovação antes do HTTP e conferência de
geração continuam nas mesmas transações e locks do login principal. Só a
liberação, que já era uma transação isolada no `finally` da entrega, passa ao
login `private_send_runtime` (`PRIVATE_SEND_DATABASE_URL`, sem fallback),
chamando `private_send_release(igreja, source)`: SECURITY DEFINER com
`search_path` fixo, confere `session_user`/atributos/LOGIN ativo e igreja igual
ao GUC (o GUC delimita, não autoriza), apaga por chave e devolve se havia linha.
Não confere geração, de propósito: precisa liberar também depois da exclusão.
O papel não tem grant em tabela nem acesso a mensagens, conversas, caminhos,
áudio ou funções de Storage; mesma guarda de papel preexistente, prova por
transação e formato de URL (direta ou pooler) da identidade de Storage.
`authenticated` sem subject perde só o DELETE (policies por comando com as
mesmas expressões); o contador do admin continua.

Alcance: sessões `authenticated` (API, cron e fila com escopo de igreja) não
conseguem mais apagar ownership para deixar recibo verde. Não protege contra
dono/superuser/BYPASSRLS, inclusive o login principal usado sem `SET ROLE`
(modo cross-tenant), nem contra quem tem CREATEROLE/ADMIN sobre o papel, nem
contra um queue-worker comprometido, que tem as duas credenciais.

A liberação nunca lança `Exception`: não mascara mais `AgentReplyRetryable`
(backoff) nem `ClaimOwnershipLost` (parada do worker); antes, uma falha do banco
nesse `finally` substituía a exceção original. Logs só com código fechado
(`private_send_release_unavailable`, `_failed`, `_unknown`) e classe da exceção.
Falha antes do COMMIT retém a ownership; falha no próprio COMMIT tem resultado
desconhecido (pode ter liberado). Sem o login, as respostas **continuam** sendo
enviadas, mas cada envio deixa a ownership retida: recibos de conversas
excluídas ficam `pendente_envio` e uma resposta `falhou_retentavel` não é
reenviada (a nova tentativa colide na mesma chave e falha antes do HTTP, sem
duplicata), até a ownership ser resolvida; não há ferramenta de reconciliação.
Resultado ambíguo (`desconhecido`, confirmação incerta) continua liberando como
antes: texto enviado ao provedor segue `fora_do_alcance` do recibo, e mudar
isso exige revisão própria desse contrato.

Distribuição: API, queue, cron e broadcast compartilham o mesmo `env_file` no
compose; uma URL colocada nele chega a todos. "Configurar só no queue" (ou só
no cron, para a identidade de Storage) não é segregação real sem env por
serviço ou override explícito vazio nos demais, a decidir no release.
Release: conter queue-worker e toda entrega de respostas pelo procedimento de
parada segura do [runbook do lote](RELEASE-LOTE-2026-10.md) (código antigo contra
o schema novo falha a liberação). Confirmar a parada dos consumidores e conferir
separadamente intents em `ia_em_transporte`, leases e registros de
`private_deletion_sends`: contar esses registros não prova o fim de um HTTP.
Resultados incertos e ownership retida exigem reconciliação explícita; não
apagar marcadores por prazo nem para concluir recibos. Depois, backup, aplicar
via `migrate.py`, provisionar LOGIN/senha nominalmente, configurar a URL,
publicar, provar com `private_send_runtime_session()` a partir do queue-worker
e retomar. Esta preparação não autoriza executar essas operações em produção.
Rollback comentado e ensaiado (aplicar → rollback → reaplicar por `migrate.py`):
recusa LOGIN provisionado, preserva as linhas de ownership, restaura `send_worker`
e o DELETE de `authenticated`, só remove o papel sem dependência em outro banco.
Ownership retida em janela de falha não é revisitada pelo código antigo.

**Pré-requisitos antes de qualquer ativação:** procedimento de reconciliação
de upload ambíguo necessário; resolver explicitamente identidade do worker e
retenção de tombstones. Pendências técnicas: tarefas e uploads têm identidade
SQL própria (#583), e a liberação de envios na candidata seguinte (#585);
INSERT/renovação de envios e fences ainda seguem o padrão servidor confiável
sem subject da #509; reconciliação de upload com
resultado desconhecido é parcial (2xx tardio confirmado e, pela
`20261030_110000` (#584), testemunho exato de tentativa commitada; abortado/em voo e
legado seguem retidos sem saída automática); dono das
funções privadas com `row_security=off`: o preflight de release acusa dono sem
SUPERUSER/BYPASSRLS nas funções já existentes da lista fixa (cinco da #587 e duas
da #584, sete; dez com a candidata de resumos, que acrescenta descoberta, fontes e reserva, cujo
corpo lê tabela com FORCE RLS; snapshot, solicitante e credencial ficam fora
porque leem só tabelas sem FORCE, legítimas para um dono que também as possui;
se o dono não as possuir, falham fechadas),
mas não examina as de migrations pendentes nem corpo, ACL ou dono de funções
aninhadas como `private_summary_origin_valid` (repetir após aplicação
autorizada; dono real em PROD não verificado);
`private_delete_content` não declara `row_security=off` e hoje falha fechada só
porque o INSERT do recibo é recusado por RLS (prova sintética); tombstones não expiram
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

A migration candidata de resumos `20261019_120001_private_conversation_summaries.sql`
vem após `20261019_090001`. Sem aplicação remota ou ativação.
