# Revisão estática SQL V2b, snapshot congelado

## Escopo e limite

- Migration: `20260927_220000_notification_outbox_v2b.sql`, SHA-256
  `1aff8b5dcc9a18d931f3944ff6d3f808d80fb4c708e6d300f4f004bbab59cf01`.
- Prova PG fornecida: `test_notification_outbox_v2b_migration_pg.py`, SHA-256
  `32e78544e8b73b8521dae584a51915833b935b4ec6247825b30831452e52c0a8`.
- Cópias locais: `SQL-CANDIDATE-1aff8b5.sql` e
  `SQL-CANDIDATE-TEST-32e7854.py`.
- Revisão somente estática. PostgreSQL, providers, rede, ambiente compartilhado
  e dados reais não foram usados. O relato de nove testes PG verdes é da
  autoria e não foi reexecutado nesta revisão.

## Parecer limitado ao SQL

**Aprovado para avançar à revisão integrada de serviços.** Não aprova o
candidato V2b completo nem autoriza migration, deploy ou envio.

O delta elimina os bloqueadores do snapshot anterior:

- A policy humana exige `app_users` ativo, `clerk_user_id` correspondente ao
  `sub`, mesmo tenant e papel `pastor` ou `admin`. Membro e convidado são
  cobertos pela prova PG fornecida.
- O INSERT humano de EVT-7 exige evento confirmado sem fence e sem
  `notificado_em`, preferência Agenda ativa e já efetiva, além de recipient
  ativo vinculado à mesma Pessoa. Ele não pode criar preferência nem definir
  `delivery_reservation_day`.
- `agenda_alert_recipients.pessoa_id` é nullable, possui FK composta do tenant
  com `ON DELETE SET NULL`, e o índice parcial impede dois recipients ativos
  para a mesma Pessoa.
- A coluna canônica `igrejas.notification_outbox_cutover_at` permanece como
  único marcador de corte. A tabela snapshot foi removida do SQL e da ACL.
- `delivery_reservation_day` e seu índice estão presentes. A reserva persiste
  quando a origem viva é removida, conforme o teste estático fornecido.
- As três relações novas têm RLS habilitada e forçada, FKs tenant-bound e
  revogação de `DELETE` para `authenticated`. A migration não executa exclusão
  de linhas.

## Gates antes do parecer final

1. Revisar o backend congelado com o precheck de principal não ativo, para que
   `convidado` com papel pastor receba 403 controlado antes da transação, em
   vez de falha RLS no flush.
2. Provar na rota e no dispatcher a resolução atual, única e tenant-bound de
   telefone para Pessoa. O cache `recipient.pessoa_id` é evidência adicional;
   mudança de telefone, ambiguidade, vínculo obsoleto e exclusão não podem
   gerar transporte.
3. Provar no dispatcher a recomputação de `origin_fingerprint`, a versão atual
   do termo, opt-out, quotas compartilhadas Agenda mais EVT-7 e o uso correto
   de `delivery_reservation_day`, incluindo concorrência, linha tardia, retry
   pré-envio em virada de dia, ambíguo e remoção da origem.
4. Executar E2E real com rota autenticada NOBYPASSRLS, dispatcher e provider
   fake. A fixture SQL simplifica `current_igreja_id()` para um GUC e não
   substitui essa prova integrada.
5. Acrescentar na evidência final testes de FK/cache de recipient cross-tenant,
   exclusão de Pessoa/configuração e mudança/ambiguidade de telefone. Eles não
   constam nesta prova SQL isolada.
