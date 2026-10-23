# Release em lote, outubro de 2026

Atualizado em 23/10/2026 sobre a `main` no commit `4fd83232`.

Este runbook prepara a janela de release das migrations acumuladas e do
backend. Ele não autoriza nem executa acesso a PROD. Use também o
[runbook de produção](PRODUCTION-RUNBOOK.md), o
[runbook de backup](BACKUP-FIREWALL-RUNBOOK.md), o
[manual do release de backend](../../deploy/BACKEND-RELEASE-MANUAL.md) e o
[aplicador de migrations](../../backend/migrations/README.md).

## Estado e gates

O registro de 14/10 informa 78 migrations aplicadas e quatro pendentes:
`20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`,
`20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`,
`20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` e
`20260926_120446_platform_jev_settings.sql`. Os quatro arquivos continuam ativos
em `migrate.py::migration_files()`. `deploy/backend-release.sh` monta o manifesto
com todas as migrations ativas, e `deploy/check_backend_schema.py` bloqueia o
release se qualquer nome esperado faltar em `public.schema_migrations`.

**Decisão do dono (Raniel, 23/10/2026, no chat): opção (1), aplicar as quatro.**
Elas ficam ativas no manifesto e são aplicadas na ordem lexical global. O deploy
só é autorizado quando todas as migrations ativas do SHA candidato estiverem
registradas no ledger do ambiente alvo. A decisão vale só para a escolha da
opção; não autoriza aplicar nada: cada migration em PROD continua exigindo
autorização nominal própria, backup verificado antes e SHA registrado.

Condições por migration, acordadas com o Codex em análise só de leitura:

| Migration | Condição antes de aplicar |
|---|---|
| `20260711_023515` (backfill de tipo "membro") | **Conferir antes.** Muda dados de pessoas reais e não tem reversão automática. O operador roda a consulta de candidatos da seção "Consultas de conferência" (somente `SELECT`), o dono vê quem mudaria (sem exportar telefone) e só então autoriza. Guardar id, igreja e tipo original fora do repositório para eventual reversão. |
| `20260711_152127` (número de atendimento deixa de ser "membro") | **Conferir antes.** Mesma regra: consulta com o final de 4 dígitos do telefone, e o dono confirma que o alvo é o número conectado, não uma pessoa. Guardar o tipo anterior. |
| `20260925_183811` (usuário de plataforma sem igreja) | Sem conferência de dados: não altera linhas. Necessária para a exclusão de igreja. Rollback exige tratar os `igreja_id` NULL. |
| `20260926_120446` (configuração da Jev) | Cria tabela vazia e fechada. A Jev continua desligada: aplicar não abre gate, não insere chave nem lista de igrejas; ativação segue sujeita a DPA e gates próprios. |

Se a conferência de uma das duas primeiras mostrar candidato inesperado, parar,
não aplicar e voltar ao dono. O Codex sugeriu excluir a quarta enquanto a Jev
estiver pausada; o dono decidiu aplicar, e a exclusão exigiria um SHA candidato
revisado à parte, com risco maior do que uma tabela vazia. Não inferir aplicação
pelo número 78.

As migrations com `OPERATIONAL_AUTHORIZATION=BLOCKED` continuam fora da
seleção de `migrate.py`; não remover o marcador nem aplicá-las neste release.
O preflight e o deploy precisam usar o SHA exato aprovado da `main` e o ledger
`public.schema_migrations` do banco correto. Estado atual de PROD, pendências,
backup e gates: não verificado neste preparo.

Manter fechados em todos os quatro serviços (`backend`, `queue-worker`,
`cron-worker` e `broadcast-worker`):

- `ALLOW_REAL_SENDS=false`;
- `ASAAS_BILLING_ENABLED=false`;
- `BREVO_SEND_MODE=off`;
- `BROADCAST_ASYNC_ENABLED=false`;
- `AgentConfig.ativo=false` para cada igreja incluída;
- Jev sem `TYPESAFE_API_KEY` e sem igrejas em
  `JEV_SHADOW_TRIAGE_IGREJA_IDS`.

Todos esses gates continuam desligados durante o lote. Não imprimir `.env`,
credenciais ou valores secretos. `stuck_flow` permanece desligado até existir
credencial dedicada. O script de deploy existente confere os quatro gates de
serviço; `AgentConfig.ativo` e Jev continuam sendo verificações independentes.
Executar qualquer etapa em PROD exige autorização nominal do dono. Nenhum
resultado local prova PROD.

## Autorizações nominais

Cada ação de PROD exige autorização própria de Raniel, com ambiente, SHA,
escopo e operador registrados. A autorização para uma etapa não se estende à
seguinte.

| Etapa | Quem autoriza | Quem executa e registra |
|---|---|---|
| Gerar e validar backup | Raniel, dono | Operador nominal da janela, com acesso autorizado à VPS e ao projeto Supabase |
| Consultar estado e rodar preflight | Raniel, para uma leitura somente leitura no alvo identificado | Operador nominal, usando role com `BYPASSRLS` e sem imprimir a URL |
| Reconciliar um achado | Raniel e admin/pastor nominal da igreja afetada | Responsável autorizado pelo fluxo administrativo aprovado para aquele registro |
| Aplicar migrations | Raniel, para a lista exata aprovada e SHA | Operador nominal, uma migration por invocação de `migrate.py` |
| Deploy do backend | Raniel, para o SHA completo e janela | Operador nominal pelo workflow manual existente |
| Smoke pós-deploy | Raniel, para o SHA e janela | Operador nominal, somente com chamadas sem efeitos externos |
| Plano de volta | Raniel, para a volta ao SHA anterior | Operador nominal; script de release, sem rollback de schema |

Registrar autorizações e recibos fora deste repositório, sem PII ou segredos.
Este documento e o merge do código não são autorizações operacionais.

## Sequência do release

1. **Backup verificado antes de qualquer migration.** Com autorização nominal
   de Raniel, o operador executa
   o procedimento instalado `/usr/local/sbin/pastorai-backup.sh` conforme o
   runbook de backup. Confere que o manifesto sanitizado informa
   `status=verified`, que o SHA-256 do pacote confere e que o pacote contém o
   dump `supabase-prod-public.dump` e os demais itens previstos. Registra hora,
   nome do artefato e SHA-256, sem copiar o pacote ou conteúdo de PROD para este
   workspace. Se o pacote ou o checksum falhar, parar.
2. **Preflight inicial.** Na cópia exata do SHA aprovado, com acesso de banco
   fornecido pelo canal autorizado e nunca por argumento ou log, executar:

   ```bash
   python3 backend/scripts/release_preflight.py
   ```

   O comando lê `MIGRATION_DATABASE_URL` do ambiente seguro, inicia transação
   `REPEATABLE READ READ ONLY`, recusa role que não contorne RLS e executa
   somente `SELECT`. Guarda a saída sanitizada. As migrations são listadas em
   `migrate.py::migration_files()`; `APLICADA` e `PENDENTE` preservam a ordem
   lexical do aplicador. `sem_arquivo` conta entradas do ledger sem arquivo
   ativo. A base `20261014` limita a verificação das tabelas esperadas no
   backup; o preflight reporta todas as migrations ativas do aplicador.
   Qualquer achado de FK, duplicidade, tabela ausente ou entrada sem arquivo
   interrompe o lote até decisão humana nominal. Pendências só são aplicadas
   depois da decisão sobre as quatro antigas e sobre a lista nova. Exit `0`
   significa apenas ausência desses achados; não significa schema liberado,
   migrations concluídas ou release pronto. Exit `1` exige reconciliação; exit
   `2` indica que o preflight não conseguiu verificar o alvo. Para autorizar o
   deploy, nenhuma migration ativa do manifesto do SHA candidato pode faltar no
   ledger; aplique todas ou use a opção de exclusão em SHA revisado descrita em
   Estado e gates.
   A checagem da FK reproduz o par `(igreja_id, celula_id)` que será validado
   pela migration `20261018_080000`; a checagem de duplicidade usa
   `(igreja_id, pessoa_id)` não nulo, como o índice da #543.
3. **Reconciliação manual antes da #543.** Antes de aplicar
   `20261025_100000_team_pessoa.sql`, confirmar zero duplicidades da chave
   `(igreja_id, pessoa_id)`. Qualquer duplicidade de igreja/pessoa exige
   reconciliação manual pelo fluxo administrativo autorizado. O operador entrega
   ao dono e ao admin/pastor da igreja afetada somente contagens e UUIDs; não
   usar exclusão em lote, SQL de escrita, merge automático ou escolha do agente.
   Repetir o preflight depois da reconciliação. Só seguir com zero violações de
   FK e unicidade, zero tabela ausente e destino explícito para cada entrada
   `sem_arquivo` e migration pendente que afete o lote.
4. **Migrations por `migrate.py`.** Com a lista aprovada, conferir primeiro
   `python3 backend/scripts/migrate.py status`. Aplicar uma migration por vez,
   na ordem apresentada e com registro nominal da saída:

   ```bash
   python3 backend/scripts/migrate.py apply <arquivo.sql> --yes
   ```

   Para as migrations marcadas `CONCURRENTLY` na tabela abaixo e a migration
   anterior à base indicada após a tabela, usar as invocações exatas com
   `--no-transaction` listadas ali. Para as demais, manter a transação padrão.
   Não usar `apply_migrations.py`, SQL manual, wrappers catalog-bound,
   `--no-transaction` sem requisito explícito da migration, nem tentar fazer um
   teste passar abrindo gate. Antes da #543, repetir a checagem de duplicidades
   `(igreja_id, pessoa_id)`. Em erro, parar no primeiro arquivo e preservar o
   estado para decisão de Raniel. Depois da lista aprovada, repetir `status` e
   o preflight somente leitura. Nenhum item aprovado deve permanecer pendente;
   resolver nominalmente qualquer divergência antes do deploy. O segundo
   preflight verifica também se as tabelas criadas pelas migrations já
   registradas desde 15/10 existem em `public`, schema inteiro coberto pelo
   dump de backup.
5. **Deploy do backend.** Depois do banco e dos preflights, Raniel autoriza
   separadamente o SHA completo de 40 caracteres. O operador usa o workflow
   manual **Backend release** da `main`; ele chama
   `deploy/backend-release.sh` na VPS. Manter o mesmo SHA que foi aprovado e
   inspecionado. Não disparar workflow durante esta preparação.
6. **Smoke sem efeitos.** Com os gates acima fechados, conferir `/health` e
   `/ready` públicos e no loopback, `docker compose ps`, CORS e isolamento das
   portas 8000/8080, seguindo a seção 8 do runbook de produção. Usar somente
   GETs e conta de teste previamente aprovada. Não testar envio, cobrança,
   broadcast, recuperação que possa contatar usuário, WhatsApp nem Jev. Se
   saúde ou readiness falhar, seguir o plano de volta sem reabrir gates.
7. **Gates continuam fechados.** Conferir os quatro processos depois do
   restart, `AgentConfig.ativo=false` por igreja e Jev inativo. Registrar
   confirmação sem mostrar valores secretos. O smoke não autoriza ativação.
8. **Plano de volta.** Em falha, Raniel decide nominalmente a recuperação e o
   operador usa o rollback de código do `deploy/backend-release.sh`, que
   verifica a compatibilidade do SHA anterior antes de retomar os serviços.
   Migrations não são desfeitas automaticamente. Preservar banco, backup e
   evidências. Corrigir adiante ou preparar uma compensação de banco revisada
   sob autorização própria. Nunca restaurar dump por cima de PROD como
   rollback improvisado.

## Migrations do lote posteriores à base de 14/10

Conferi `backend/scripts/release_preflight.py` em
`origin/chore/release-preflight-checks`: `BASELINE_DATE=20261014` limita a
checagem de tabelas esperadas no backup, enquanto o relatório percorre
`migrate.py::migration_files()` e classifica cada arquivo como aplicada ou
pendente. Essa função exclui migrations pausadas e ordena os nomes
lexicalmente. A tabela contém as 41 migrations ativas posteriores à base no
checkout atual, na ordem de aplicação; não afirma que estejam aplicadas em
PROD. Cada rollback resume o comentário da migration e exige reversão de
callers, preservação de dados e migration compensatória aprovada via
`backend/scripts/migrate.py`; não executar SQL de rollback manualmente.

A main atual já integra #556, #558, #560, #561 e #562. As #556, #558 e #560
não adicionam migrations; #561 adiciona a migration de reset privado da igreja
ao fim da lista, e #562 adiciona as seis migrations de métricas e índices
operacionais abaixo. As origens de cada arquivo foram conferidas no histórico
Git.

A busca literal `grep -il 'concurrently' backend/migrations/*.sql` encontrou
`20260701_014654_evt6_google_event_dedup_index.sql`,
`20260808_011500_messages_outbound_provider_id_uidx.sql`,
`20261023_100001_ai_usage_tenant_created_idx.sql`,
`20261023_110001_notification_outbox_pending_created_idx.sql`,
`20261023_110002_notification_outbox_retry_created_idx.sql`,
`20261023_110003_notification_outbox_expired_lease_idx.sql`,
`20261023_110004_messages_pending_agent_created_idx.sql`,
`20261023_110005_work_queue_pending_created_idx.sql`,
`20261028_100001_private_erasure_requests_overview_idx.sql` e
`20261028_100002_private_resume_delivered_overview_idx.sql`. A migration
`20260701_014654` só cita `CONCURRENTLY` em comentário e executa `CREATE UNIQUE
INDEX` comum; as outras nove executam `CREATE INDEX CONCURRENTLY` ou
`CREATE UNIQUE INDEX CONCURRENTLY`. `20260808_011500` antecede a base de 14/10,
por isso não integra esta tabela, mas também exige `--no-transaction` se estiver
pendente. As oito posteriores à base estão identificadas nas linhas da tabela.

| Ordem | Origem | Migration e efeito | Rollback resumido |
|---:|---|---|---|
| 1 | #484 | `20261016_180000_prayer_requests.sql`: persiste propostas e pedidos próprios de oração com RLS. | Drenar respostas, preservar pedidos confirmados e autorização; manter gates fechados e remover schema só por compensação aprovada. |
| 2 | #487 | `20261017_180000_visit_events.sql`: registra evidências de visitas a células com auditoria. | Reverter callers, preservar evidências; remover tabela e funções por compensação aprovada. |
| 3 | #488 | `20261017_180100_consolidacao_atribuicoes_aceite.sql`: persiste convites e aceite explícito de atribuições. | Suspender writers, preservar histórico privado e restaurar a função de revisão V3 antes de remover schema. |
| 4 | #492 | `20261017_210500_uv_turmas.sql`: cria turmas, atividades, responsáveis e matrículas da UV. | Reverter callers, preservar registros de formação e remover as tabelas em compensação. |
| 5 | #493 | `20261017_220000_uv_presencas.sql`: cria presença atual e histórico imutável das aulas UV. | Reverter callers, preservar histórico e remover tabelas, triggers, funções e constraints em compensação. |
| 6 | #494 | `20261017_230000_uv_marcos_conclusao.sql`: registra marcos e conclusões UV e a origem da aptidão. | Reverter callers, preservar marcos e históricos; remover tabelas, triggers, funções, constraint e coluna em compensação. |
| 7 | #497 | `20261018_010000_cd_catalogo_turmas.sql`: cria currículo, módulos, aulas, turmas, calendário e responsáveis CD. | Reverter callers, preservar catálogo, calendário e responsáveis; remover tabelas em compensação. |
| 8 | #498 | `20261018_020000_cd_matriculas.sql`: cria matrículas CD e snapshots de eventos de estado. | Reverter callers, preservar matrículas e eventos; remover dependências em compensação. |
| 9 | #499 | `20261018_030000_cd_presencas.sql`: cria frequência CD atual e histórico imutável. | Reverter callers, preservar histórico e remover tabelas, triggers, funções e constraints em compensação. |
| 10 | #500 | `20261018_040000_cd_conclusoes_certificados.sql`: registra conclusões, certificados e revogações CD. | Reverter callers, preservar conclusões e certificados; remover triggers, funções e tabelas em compensação. |
| 11 | #503 | `20261018_050000_enviar_avaliacoes.sql`: persiste avaliações humanas e eventos privados de aptidão. | Restaurar callers, preservar decisões e eventos; remover objetos em compensação. |
| 12 | #504 | `20261018_060000_enviar_nomeacao.sql`: adiciona solicitação versionada de nomeação de líder. | Restaurar callers e preservar histórico; reverter constraints e índices em compensação. |
| 13 | #505 | `20261018_070000_enviar_abertura.sql`: permite solicitação de abertura sem origem, sem backfill. | Restaurar callers, preservar solicitações e eventos; nunca apagar histórico nem rebaixar líderes. |
| 14 | #505 | `20261018_080000_enviar_reforcos.sql`: valida a FK de célula e reforça isolamento da solicitação. | Manter a FK validada; só restaurar estado anterior da validação por compensação aprovada. |
| 15 | #509 | `20261018_090000_exclusao_privada.sql`: cria exclusão privada durável de conversa e derivados. | Conter consumidores, drenar tarefas e preservar recibos; conteúdo apagado não é restaurável. |
| 16 | #510 | `20261018_100000_enviar_reencontro.sql`: registra evidência de Reencontro como marco oficial. | Reverter callers, preservar marcos e revogações; reconciliar duplicidades antes de reverter constraints. |
| 17 | #511 | `20261018_110000_cd_equivalencias_versoes.sql`: registra equivalências entre versões de currículo CD. | Reverter callers, preservar evidências e vínculos de certificados; remover view, tabelas e função em compensação. |
| 18 | #515 | `20261018_120000_prayer_message_privacy.sql`: restringe leitura do histórico de oração por igreja e papel. | Reverter consulta do backend junto com o schema, preservar recibos/tarefas #509 e manter gates fechados. |
| 19 | #513 | `20261018_130000_conhecimento_oficial.sql`: cria documentos, versões e operações de conhecimento oficial. | Parar callers e preservar documentos; não remover schema se houver documentos ou operações. |
| 20 | #516 | `20261018_140000_conhecimento_trechos.sql`: cria trechos transacionais e busca lexical autorizada. | Parar callers, preservar snapshots e citações; remover dependências em compensação. |
| 21 | #518 | `20261019_090001_exclusao_privada_pessoa_igreja.sql`: adiciona exclusão privada por pessoa ou igreja com recibos. | Conter consumidores, preservar recibos/barreiras e restaurar a função de #515 antes de compensar; conteúdo apagado não é restaurável. |
| 22 | #524 | `20261019_110001_conhecimento_exclusao.sql`: registra exclusão definitiva de documentos e citações oficiais vinculadas. | Parar callers e preservar auditoria; conteúdo apagado não é restaurável nem deve ser recriado. |
| 23 | #526 | `20261019_120001_private_conversation_summaries.sql`: cria resumos privados operacionais sem consumidor ativo. | Parar e drenar workers, preservar recibos e restaurar a função de exclusão anterior antes de remover schema. |
| 24 | #529 | `20261020_100000_prayer_audio_privacy.sql`: restringe áudio de oração ao pastor, inclusive compartilhamentos legados. | Restaurar políticas/funções só após aprovação pastoral; preservar associações e tarefas privadas. |
| 25 | #531 | `20261020_200000_private_resume.sql`: habilita retomada explícita de resumo, desligada por padrão. | Conter consumidores e restaurar a função anterior de invalidação; manter retomada desligada. |
| 26 | #530 | `20261021_100000_responsabilidades_setor.sql`: registra responsabilidades por setor e vigência sem conceder acesso. | Restaurar callers e preservar histórico; remover tabela e função em compensação aprovada. |
| 27 | #535 | `20261022_100000_private_erasure_requests.sql`: registra pedidos de exclusão privada e decisões do admin. | Parar consumidores e preservar pedidos, decisões e recibos; não compensar enquanto houver pedido pendente. |
| 28 | #544 | `20261023_100000_ai_usage_force_rls.sql`: força RLS na tabela de logs de uso, mantendo a política existente. | Restaurar apenas o comportamento anterior de FORCE RLS; manter RLS habilitada e a política. |
| 29 | #544 | `20261023_100001_ai_usage_tenant_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa logs de uso por igreja e data. | Conferir validade e remover índice com `DROP INDEX CONCURRENTLY` em migration compensatória. |
| 30 | #562 | `20261023_110000_operations_outbox_pending_metrics_fn.sql`: agrega métricas pendentes por igreja para admin ativo. | Remover a função por compensação após conter callers; a remoção também elimina seu ACL. |
| 31 | #562 | `20261023_110001_notification_outbox_pending_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens pendentes da outbox por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 32 | #562 | `20261023_110002_notification_outbox_retry_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens de retry da outbox por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 33 | #562 | `20261023_110003_notification_outbox_expired_lease_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa leases expirados da outbox por igreja e claim. | Conferir validade e remover índice concorrentemente por compensação. |
| 34 | #562 | `20261023_110004_messages_pending_agent_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa intenções de saída da IA por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 35 | #562 | `20261023_110005_work_queue_pending_created_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa itens acionáveis da fila por igreja e criação. | Conferir validade e remover índice concorrentemente por compensação. |
| 36 | #543 | `20261025_100000_team_pessoa.sql`: aplica unicidade de Pessoa por igreja e cria auditoria técnica. Exige reconciliação manual prévia de duplicidades `(igreja_id, pessoa_id)`. | Reverter callers e preservar auditoria; remover índice e tabela somente por compensação aprovada. |
| 37 | #541 | `20261027_100000_reset_settles_erasure_requests.sql`: faz reset manual de pessoa cumprir pedidos privados pendentes. | Parar consumidores, preservar pedidos/recibos e restaurar wrapper anterior; não reabrir pedidos cumpridos. |
| 38 | #546 | `20261028_100000_private_memory_overview.sql`: expõe contagens administrativas sem conteúdo ou ação automática. | Remover a função por compensação; não há dados apagados e RLS/grants existentes permanecem. |
| 39 | #546 | `20261028_100001_private_erasure_requests_overview_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa inventário de pedidos por igreja, estado e idade. | Conferir validade e remover índice concorrentemente por compensação. |
| 40 | #546 | `20261028_100002_private_resume_delivered_overview_idx.sql` (**CONCURRENTLY; `--no-transaction`**): indexa retomadas privadas entregues por igreja. | Conferir validade e remover índice concorrentemente por compensação. |
| 41 | #561 | `20261029_100000_reset_settles_church_erasure_requests.sql`: faz reset privado da igreja cumprir os pedidos cobertos pelo recibo. | Parar consumidores, preservar pedidos/recibos e restaurar wrapper #541; não reabrir pedidos cumpridos. |

As invocações abaixo usam a ordem lexical entre as migrations concorrentes. Cada
uma deve ser aplicada somente quando alcançar sua posição na ordem global
mostrada por `migrate.py status`, depois dos prechecks descritos no próprio
arquivo:

```bash
python3 backend/scripts/migrate.py apply 20260808_011500_messages_outbound_provider_id_uidx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_100001_ai_usage_tenant_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110001_notification_outbox_pending_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110002_notification_outbox_retry_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110003_notification_outbox_expired_lease_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110004_messages_pending_agent_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261023_110005_work_queue_pending_created_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261028_100001_private_erasure_requests_overview_idx.sql --yes --no-transaction
python3 backend/scripts/migrate.py apply 20261028_100002_private_resume_delivered_overview_idx.sql --yes --no-transaction
```

## Consultas de conferência das migrations 1 e 2 (somente leitura)

Rodar no banco correto, com autorização nominal, dentro de `BEGIN READ ONLY; ...
ROLLBACK;`, e **antes** de aplicar `20260711_023515` e `20260711_152127`. O
resultado mostra nomes e identificadores: ver só na sessão do operador e do dono;
não copiar para chat, issue, log de CI nem documento. Nenhuma consulta mostra o
telefone completo (a segunda mostra só o final de 4 dígitos).

Para poder reverter, o operador guarda **fora do repositório** apenas
`id`, `igreja_id` e o tipo atual (`atual`) de cada linha listada, em local
autorizado, antes de aplicar. Se aparecer linha inesperada, parar e voltar ao dono.

```sql
-- Migration 1: pessoas com vínculo ativo na mesma igreja que passariam a "membro"
SELECT p.id, p.igreja_id, p.nome, p.tipo AS atual, 'membro' AS proposto
FROM public.pessoas p
WHERE (p.tipo IS NULL OR p.tipo::text IN ('contato','visitante'))
  AND EXISTS (SELECT 1 FROM public.celula_membro cm
              WHERE cm.pessoa_id = p.id AND cm.igreja_id = p.igreja_id AND cm.ativo IS TRUE)
ORDER BY p.igreja_id, p.nome, p.id;

-- Migration 2: registro cujo telefone canônico coincide com o número conectado
-- da mesma igreja, sem vínculo ativo, hoje "membro" (passaria a "contato")
WITH p AS (
  SELECT id, igreja_id, nome, tipo,
         CASE WHEN length(d) > 11 AND left(d, 2) = '55' THEN substr(d, 3) ELSE d END AS d
  FROM (SELECT id, igreja_id, nome, tipo,
               regexp_replace(coalesce(telefone, ''), '\D', '', 'g') AS d
        FROM public.pessoas) s),
pn AS (
  SELECT *, CASE WHEN length(d) = 10 THEN substr(d, 1, 2) || '9' || substr(d, 3) ELSE d END AS k
  FROM p),
w AS (
  SELECT igreja_id,
         CASE WHEN length(d) > 11 AND left(d, 2) = '55' THEN substr(d, 3) ELSE d END AS d
  FROM (SELECT igreja_id, regexp_replace(coalesce(numero, ''), '\D', '', 'g') AS d
        FROM public.whatsapp_connections WHERE numero IS NOT NULL) s),
wn AS (
  SELECT igreja_id,
         CASE WHEN length(d) = 10 THEN substr(d, 1, 2) || '9' || substr(d, 3) ELSE d END AS k
  FROM w)
SELECT p.id, p.igreja_id, p.nome, right(p.k, 4) AS fone_final_4,
       p.tipo AS atual, 'contato' AS proposto
FROM pn p
WHERE p.tipo = 'membro' AND p.k <> ''
  AND NOT EXISTS (SELECT 1 FROM public.celula_membro cm
                  WHERE cm.pessoa_id = p.id AND cm.igreja_id = p.igreja_id AND cm.ativo IS TRUE)
  AND EXISTS (SELECT 1 FROM wn w WHERE w.igreja_id = p.igreja_id AND w.k = p.k)
ORDER BY p.igreja_id, p.nome, p.id;
```

Estas consultas não são executadas por `release_preflight.py` nem pelo CI. Os
dois `SELECT`s passaram por sintaxe e resultado em `BEGIN READ ONLY; ...
ROLLBACK;` em PostgreSQL 17 descartável com duas igrejas e dados sintéticos. A
consulta 1 retornou somente pessoas com vínculo ativo e tipo `contato`,
`visitante` ou `NULL`. A consulta 2 retornou membros sem vínculo ativo nas
formas `+55` com e sem 9º dígito e local com 9º dígito, incluindo vínculo
inativo; não retornou vínculo ativo, pessoa de outra igreja com o mesmo
telefone nem DDD distinto com o mesmo sufixo. A consulta 2 reproduz o predicado
e os passos de canonicalização da função `pg_temp.pastorai_canon_phone` da
migration `20260711_152127`, comparando o telefone canônico completo. A saída
da consulta 2 não projeta o telefone completo e mostra somente seus quatro
dígitos finais. Nenhum banco real foi consultado.

## Ensaio de restauração sintética

O ensaio não lê nem toca backups reais nem arquivos `.env`. Recusa `DOCKER_HOST`
explícito e contexto Docker cujo endpoint não seja um socket Unix local. Usa
apenas a imagem PostgreSQL 17 já presente na máquina, container com rede
desabilitada e diretório de dados em `tmpfs`. Cria um dump custom do schema
`public` com UUIDs e linhas fictícias, restaura em outro banco do mesmo
container descartável e exige as contagens `synthetic_private_records=2` e
`synthetic_team_events=1`.

```bash
bash backend/scripts/release_restore_synthetic.sh
```

Saída esperada: `RESTORE_SINTETICO=OK tabelas=2 contagens=2:1`. A ausência da
imagem local interrompe o ensaio; não baixar imagem automaticamente na janela
de produção. O script remove o container e os arquivos temporários ao terminar.

## O que não fazer

- Não conectar a PROD, VPS, banco remoto, deploy ou serviço externo durante a
  preparação deste runbook.
- Não abrir `ALLOW_REAL_SENDS`, `ASAAS_BILLING_ENABLED`, `BREVO_SEND_MODE`,
  `BROADCAST_ASYNC_ENABLED`, `AgentConfig.ativo` ou qualquer gate Jev.
- Não aplicar migrations fora da lista e da ordem aprovada por `migrate.py`.
- Não automatizar reconciliação, apagar duplicidades, ignorar RLS ou mascarar
  achado com migration manual.
- Não copiar PII, dados pastorais, dumps reais, URLs, credenciais, chaves ou
  conteúdo de `.env` para relatório, chat, log, teste ou commit.
- Não usar backup real no ensaio local nem restaurar backup sobre banco de
  produção.
