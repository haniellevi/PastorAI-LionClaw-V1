# Parecer final V2b: delta de quota e EVT7

## Artefato revisado

- Base destacada: `58bcd1808aa511cdfafc7957d5c36a9c0f8ee348`.
- Worktree de revisão: `/tmp/igreja12-v2b-agenda-review-20260927`.
- Manifesto: `V2B-FINAL-SNAPSHOT.json`, SHA-256
  `dacce45577655946a62810ab2a1563eae47a03b563e3473e3c45f83a625be9bd`.
- Patch agregado: `V2B-FINAL.patch`, SHA-256
  `5b691b9327ba995d0dc0b83a96433bfb55bab09a6996e724692e45b91dfe313a`.
- As 33 pós-imagens do manifesto conferem byte a byte. Os arquivos centrais
  deste delta são `notification_outbox.py`, SHA-256
  `41f049d91198741be95e956da5868bb4edb450c39de292d67cb33ccafc56cd02`,
  e `test_notification_outbox_evt7_e2e_pg.py`, SHA-256
  `7e0da512473b0625e15f0abb9176e64113945d5f2ce0fba17b4196ae75932870`.
- `git diff --check` contra a base não apresentou erro de espaço.

## Revisão do bloqueio EVT7

`_agenda_quota_rank` agora somente calcula a posição e o dia de reserva. Ele
não altera a linha antes das consultas de quota e destinatário. No caminho que
recebe lease, `delivery_reservation_day`, estado, token, prazo e worker são
alterados juntos antes de um único commit. O caminho acima do limite grava a
reserva e o terminal no mesmo commit. Assim, o autoflush intermediário que
alcançava a FK viva de `event_id` foi removido sem introduzir preflight ou outra
camada de sincronização.

A E2E EVT7 mantém um `Event FOR UPDATE` em conexão física separada e cria as
sessões do dispatcher com `statement_timeout` de 1,5 s. Ela despacha no início
da janela, um minuto depois e no deadline. Qualquer espera indevida pela FK
falharia pelo timeout. O teste verifica zero chamadas ao provider,
`transport_started_at` ausente, `attempts == 0` e terminal
`pre_envio_expirado` enquanto o lock ainda existe. Isso prova o efeito exigido:
o lock de origem é um deferral pré-envio limitado, sem envio tardio nem fila
zumbi.

O prazo EVT7 continua derivado de `created_at`, da primeira janela elegível e
de dez minutos. A claim verifica expiração antes do lease, a cerca verifica de
novo antes de HTTP, e o release só deixa retry cuja próxima execução ainda cabe
no prazo. A mesma E2E também cobre conexão indisponível e despacho iniciado
depois do prazo, ambos sem tentativa ao provider.

## RLS e efeitos

A E2E executa a rota real de confirmação com `TestClient`. Antes do enqueue,
ela comprova a sessão `authenticated`, sem `BYPASSRLS`, com `sub` humano, e as
três relações V2b com RLS forçada. Um pastor ativo confirma, cria uma única
intenção e o dispatcher comum entrega uma única vez por provider fake; a
repetição retorna 409. Um usuário pendente recebe 403 antes de alterar evento
ou outbox. A política humana, o GUC transacional e o enqueue anterior ao commit
permanecem nos hashes já revisados.

A quota segue compartilhada por Pessoa entre `agenda_reminder` e `agenda_evt7`.
O prefixo Conversation para Pessoa serializa as disputas, e a reserva só é
movida de dia por retry comprovadamente pré-envio. As cinco provas PG de quota
cobrem três dispatchers concorrentes para duas vagas, intenção antiga tardia,
virada de dia, ambiguidade, origem removida e identidade entre tenant,
recorrência, destinatário e finalidade.

Não reabri SQL ou S3: a migration permanece no hash previamente revisado
`1aff8b5dcc9a18d931f3944ff6d3f808d80fb4c708e6d300f4f004bbab59cf01`,
e o delta final não muda esses contratos.

## Evidência consultada

- `/tmp/v2b-final-offline.xml`, SHA-256
  `46d3ffdb3fec115085ff87607941459f7ea4b3642bfab9195a6b6e3321d15dde`,
  registra 5.915 testes, zero falhas, zero erros e zero skips.
- `/tmp/v2b-final-all-runtime-pg.xml`, SHA-256
  `9363b52f5a9cbf9d5f9e9fd5ad2cfd855c8c4015900f00c1204f68378b6698c7`,
  registra 66 testes PG, zero falhas, zero erros e zero skips. Inclui as cinco
  E2E EVT7, cinco de quota, cinco E2E Agenda S3, 46 V1a e cinco de cron.

Os testes foram executados pelo root; esta revisão conferiu os XMLs e não
executou PostgreSQL concorrente.

## Veredito

**Apto para PR e revisão de Sarah.** O bloqueio de contenção EVT7 do snapshot
anterior foi resolvido no delta congelado e a prova PG correspondente está
verde. Não encontrei bloqueador estático novo. Este parecer não autoriza merge,
migration aplicada, envio real ou mudança de gates.

## Próximo gate

Revisão humana de Sarah na PR.
