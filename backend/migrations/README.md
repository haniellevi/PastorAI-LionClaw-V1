# Migrations — processo simples do MVP

Planejamento ativo: [ROADMAP.md](../../ROADMAP.md). Este runbook mantém o
processo simples de migrations. O processo anterior (catálogo, head, atestação, executor catalog-bound) está pausado e
preservado na branch `archive/governanca-2026-09`.

## Criar

1. Crie `backend/migrations/AAAAMMDD_HHMMSS_slug.sql`. O nome define a ordem.
2. Tabela nova de tenant: coluna `igreja_id`, `ENABLE`/`FORCE ROW LEVEL SECURITY`
   e policies por `igreja_id`, no mesmo padrão das tabelas existentes.
3. Escreva o rollback como comentário no fim do arquivo.
4. Nunca edite uma migration que já foi aplicada em PROD; crie outra. No
   banco local, basta `./dev.sh reset`.
5. O aplicador controla a transação. Um `begin;`/`commit;` que envolve o
   arquivo inteiro é removido automaticamente (é o padrão histórico).
   Qualquer outro controle de transação no meio do arquivo é recusado.

## Aplicar

```bash
cd backend
MIGRATION_DATABASE_URL="<url do banco>" python scripts/migrate.py status
MIGRATION_DATABASE_URL="<url do banco>" python scripts/migrate.py apply <arquivo>.sql --yes
```

- Aplica um arquivo por vez e registra o nome em `public.schema_migrations`
  na mesma transação.
- `--no-transaction` existe só para `CREATE INDEX CONCURRENTLY`.
- **Local primeiro.** `./dev.sh reset` recria o banco local do zero com todas
  as migrations e os dados de teste; `./dev.sh up` aplica as pendentes
  (`docs/ops/AMBIENTE-LOCAL.md`). PROD só no release, com **backup antes**
  (runbook de produção), anotando na descrição da PR/release o que
  foi aplicado e quando.
- A URL nunca vai para argumento de linha de comando, log ou commit.

## Pausadas

Arquivos com `-- OPERATIONAL_AUTHORIZATION=BLOCKED` (E4B, laboratório de
evidência de consentimento, sessão dedicada D2A e consentimento por finalidade)
ficam fora de `status` e `apply` até a Fase 5.

## Histórico

`0001`–`0017` são as migrations originais. `private_runtime/` pertence à
fundação D2A, que está pausada; não aplique esses arquivos no MVP.

## V1a: relatório de célula por texto (candidata)

`20260927_190000_cell_report_whatsapp_v1a.sql` depende da migration S3
`20260927_170000_whatsapp_privilege_actions.sql`. Acrescenta estado privado
de rascunho, preferências/lembretes e reservas de custo, com RLS, e amplia
o catálogo S3 somente para o relatório agregado. O worker recebe apenas SELECT/INSERT/UPDATE nas cinco tabelas novas; reaplicar revoga DELETE residual. Um índice parcial único impede duas propostas V1a executadas para a mesma igreja/reunião/ação. Propostas canceladas/expiradas não impedem a correção. A execução usa
`lock_timeout = '2s'`; se o lock não vier, parar e tentar em outra janela.

A verificação local usa PostgreSQL 17 descartável e aplica o SQL duas vezes.
Isso não prova aplicação em DEV/PROD. Preservar os SQLs congelados das PRs
426/428, reconciliar a base e revisar novamente antes de qualquer aplicação.
A flag `CELL_REPORT_ENABLED_IGREJA_IDS` fica vazia e
`CELL_REPORT_APPROVED_RELEASE_ID=None`; migration e deploy não ativam envios.
Rollback comentado no próprio SQL exige tratar pendências antes de remover
o schema; relatórios já confirmados continuam sendo registros do domínio.

Observação Sarah registrada na branch V1b, mantendo PR430 `a8bf21d` congelado:
a guarda do índice compara texto de `pg_get_expr`. A representação depende da
versão PostgreSQL; divergência aborta com segurança, mas exige revisão e replay
antes de adotar outra versão. A prova atual cobre PostgreSQL17.

## V1b: áudio do relatório de célula (candidata)

`20260927_210000_cell_report_audio_v1b.sql` depende da V1a e acrescenta quatro
tabelas privadas: avisos de áudio, eventos de aceite/revogação, entradas de áudio
e reservas. Mantém RLS/FORCE RLS, policies de worker, FKs compostas e somente
SELECT/INSERT/UPDATE. Reaplicar revoga DELETE residual. O número de áudio é
único por igreja/reunião e limitado a três; reservas encerradas conservam esse
número. O custo é compartilhado com as quatro extrações textuais permitidas.

As referências vivas de pessoa/conversa/mensagem podem ser anuladas por
exclusão; a âncora imutável e a chave de storage sobrevivem para limpeza.
Âncora sem fonte viva não autoriza processamento. Purga continua com flags
fechadas. Antes de qualquer rollback destrutivo, concluir a remoção dos objetos
e registrar ausência de pendências, conforme comentário no SQL.

A migration usa `lock_timeout='2s'` e não altera os SQLs congelados 426/428/430.
Somente PostgreSQL17 descartável foi usado nesta missão. Aplicação compartilhada
e deploy mantêm gates próprios; `CELL_REPORT_AUDIO_ENABLED_IGREJA_IDS` vazia e
`CELL_REPORT_AUDIO_APPROVED_RELEASE_ID=None` ficam cumulativos a V1a/S3.

## V2b: outbox comum para lembretes e EVT-7 (candidata)

`20260927_220000_notification_outbox_v2b.sql` depende de S3 e V1a e amplia
os checks S3 para a confirmação de lembrete de Agenda. Adiciona outbox,
preferências por finalidade e inscrição por ocorrência, com RLS/FORCE RLS,
FKs compostas por tenant e grants sem DELETE. `lock_timeout='2s'` limita
espera por locks; se falhar, interromper e revisar a janela da release.

O corte fica em `igrejas.notification_outbox_cutover_at`, preenchido uma vez
para igrejas existentes e pelo DEFAULT para novas. A reaplicação não move
essa fronteira. Fences preservam terminais e ambiguidades do legado e não
convertem o marcador EVT-7 de corte em comprovante de envio.

`agenda_alert_recipients.pessoa_id` é vínculo nullable preenchido pelo servidor.
A configuração antiga sem vínculo fica inelegível até ser salva novamente;
isso não cria consentimento nem permite replay. Telefone e Pessoa continuam
sujeitos a resolução atual única antes do transporte. Exclusão da Pessoa
anula o vínculo; exclusão de origem não apaga a reserva nem a ambiguidade.

A futura release exige quiescência comprovada dos processos antigos antes
da migration e publicação coordenada do consumidor novo. SQL não recolhe
HTTP já iniciado. O [runbook V2b](../../docs/ops/v2b-agenda-20260927/README.md)
detalha o corte e o rollback: fechar gates, preservar históricos e não
reativar consumo legado automaticamente. Migration/deploy/ativação continuam
com gates próprios; flags vazias e releases None não autorizam envio.

SHA256 do SQL V2b atual: `bbec98a290a8af6b4985a807db191ed38cc993d31298981d0d161e8adfcd8ef7`.
Relativo ao snapshot `a1f875032252262c77924ea18f2ad1fed7530f48cdc4d92644a4c629b6b887c3` (que já diferia só no comentário de rollback do snapshot `1aff8b5dcc9a18d931f3944ff6d3f808d80fb4c708e6d300f4f004bbab59cf01`), a mudança é executável: o bloco de ACL passa a `revoke all privileges ... from authenticated` antes dos grants (14/10, revisão da Sarah).
Prova SQL local histórica: PostgreSQL 17 sintético, reaplicação real e RLS sob
`authenticated` sem BYPASSRLS no snapshot anterior. A prova histórica não atesta aplicação compartilhada.

## V3: consolidação pelo WhatsApp (candidata)

`20260928_080000_whatsapp_consolidation_v3.sql` depende de S3 e V2b.
Acrescenta origem exata da decisão, revisão de atribuição e vínculo canônico
entre consolidação e tarefa; cada nova consolidação recebe uma fonovisita,
sem backfill das anteriores. A outbox ganha três finalidades V3, mantendo
unicidade por tenant, destinatário, ocorrência e finalidade. Para fonovisita,
o pai é derivado exclusivamente da tarefa, sem referência redundante na outbox.

A nova `consolidation_whatsapp_activation` tem RLS/FORCE RLS e acesso somente
worker SELECT/INSERT/UPDATE, sem DELETE ou linhas inseridas pela migration.
O corte permanece durante a época aberta e no fechamento; somente a reabertura
observada pode avançá-lo. Nenhuma alteração autoriza alertas retroativos.

`lock_timeout='2s'` limita espera por locks. O rollback comentado preserva
recibos, terminais e ambiguidades. Na futura release, drenar processos antigos,
aplicar a migration V3 e passar pela pré-verificação somente de leitura do
[runbook V3](../../docs/ops/v3-consolidacao-20260928/README.md), incluindo
inventário e decisão humana registrada para identidades LID legadas, **antes** de
publicar ou reiniciar backend e workers novos. As cinco colunas e a tabela de
ativação são usadas por caminhos sem guarda V3; inverter a ordem pode causar
erros 42703/42P01 mesmo com flags fechadas. Falha ou resultado inconclusivo exige
PARAR e manter os binários antigos. Aplicação, deploy e ativação conservam gates
próprios. Flags vazias e release `None` continuam inertes.
A evidência e o hash do candidato constam no
[registro V3](../../docs/ops/v3-consolidacao-20260928/README.md).

## G12 PR 3: aceite da fonovisita (candidata)

`20261017_180100_consolidacao_atribuicoes_aceite.sql` depende da V3 e cria o
histórico privado de convites com FKs compostas, RLS/FORCE RLS e sem DELETE
para `authenticated`. Não altera atribuições existentes. Novos convites vencem
em 24h corridas, verificadas pelo servidor sob lock, sem cron nem novo prazo
operacional. Criar convite também avança a revisão de atribuição; aceitar
promove o candidato e sincroniza tarefas na mesma transação. A autoatribuição
pela fila grava aceite imediato; repetição do responsável efetivo não cria
histórico nem avança revisão. Convite pendente impede terceiros de assumir.
Um trigger torna identidade/prazo imutáveis e aceita somente transições do
convite pendente para os quatro estados finais. GET não bloqueia nem grava:
expiração é projetada na leitura e persistida pelos writers. WhatsApp limita
destinatários a admin/pastor/lider_consol, além da capacidade exigida. O painel
aceita status NULL legado ou ativo, com Pessoa vinculada e capacidade.
Nenhum aviso externo novo é criado.

A tabela é usada por caminhos sem flag: uma futura release precisa aplicar a
migration antes do backend novo. O rollback comentado exige preservar o
histórico e restaurar a função V3 de revisão sem reduzir o contador; o check
aditivo de recibos deve continuar aceitando os recibos já gravados. Somente
PostgreSQL local descartável foi autorizado nesta entrega. Banco remoto,
publicação, restart e gates continuam sem autorização.

## Enviar PR 2: avaliação humana (candidata)

`20261018_050000_enviar_avaliacoes.sql` acrescenta avaliações e eventos privados,
com FKs compostas, RLS/FORCE RLS e grants de leitura/inserção mínimos. Não faz
backfill: a origem legada é derivada de `apto_lider` quando ainda não há decisão.
Cada inserção de avaliação cria um evento via trigger; ambos recusam UPDATE e
DELETE, inclusive pelo owner. O endpoint decide sob lock da Pessoa e atualiza a
projeção na mesma transação; CSIM registra uma decisão de sistema negativa.

Aplicar antes dos novos callers em uma futura release, usando `scripts/migrate.py`.
Somente PostgreSQL 17 descartável foi exercitado nesta fatia; aplicação remota,
deploy e gates não foram autorizados. O rollback comentado exige preservar o
histórico e restaurar os callers. Exclusão aprovada desses registros privados
exige procedimento de manutenção específico; o papel da aplicação não apaga
avaliações nem eventos. A exclusão de igreja já aprovada pelo console remove
esses dados pela cascata Pessoa → avaliação → evento, atomicamente. Somente
a cascata de um pai já removido em sessão privilegiada admite DELETE; chamadas
diretas, UPDATE e cascatas no papel de tenant continuam recusados.

O dono das funções SECURITY DEFINER dos gatilhos desta migration precisa
ignorar RLS: conferir BYPASSRLS (ou superusuário/owner quando aplicável).
Como estas tabelas usam FORCE ROW LEVEL SECURITY, ser apenas owner da tabela
não basta. O runbook da futura release deve conferir o proprietário de cada
função e sua capacidade efetiva de ignorar RLS antes de aplicar/usar os callers;
sem essa conferência, o pré-requisito permanece não verificado.


## Ordem obrigatória de release — UV/CD/Enviar

Antes do deploy deste backend, aplique via `scripts/migrate.py`, na ordem dos
nomes, todas as migrations UV (`20261017_210500`–`20261017_230000`), CD
(`20261018_010000`–`20261018_040000`) e Enviar
(`20261018_050000`–`20261018_080000`, seguidas de
`20261018_100000_enviar_reencontro.sql`). O backend consulta as novas tabelas e
colunas diretamente: publicar antes de migrar causa falhas de consulta.
A pré-checagem de FK de `_080000` continua obrigatória.

`20261018_100000_enviar_reencontro.sql` substitui o nome ainda não aplicado
`20261018_090000_enviar_reencontro.sql`, evitando colisão com a exclusão privada
(#509). O índice parcial admite só um marco ativo por igreja/pessoa/tipo.
Revalidação exige coordenação e novo ID; não desfaz revogação nem apaga histórico,
nem refaz conclusão UV existente. O rollback comentado exige preservar e
reconciliar o histórico antes de restaurar a unicidade antiga.

Ensaiar primeiro no PostgreSQL sintético. Aplicação remota exige autorização
nominal e backup prévio no release; aplicação remota e deploy permanecem
**não verificados**. Não abrir gates de envio/WhatsApp com esta mudança.
