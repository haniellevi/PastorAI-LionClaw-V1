# V2b: verificação de banco pós-cutover, 2026-10-15

**Escopo:** só leitura no banco PROD. Nenhuma escrita, deploy, migration ou alteração de gate. Sem `igreja_id` neste registro.

## Resultado

| Item | Resultado | Leitura |
|---|---|---|
| (a) `app_users` sem status | 0 de 6 | cumpre `sem_status = 0` |
| (c1) outbox nova ambígua, em envio ou retry | 0 | nada preso |
| (c2) V1a ambíguo | 0 | nenhum lembrete em envio no cutover |
| (c3) EVT-7 cercado | 11, todos `legacy_evt7_sem_recibo` | ver abaixo |

## Os 11 eventos EVT-7

Eram eventos confirmados sem `notificado_em`: nunca foram notificados. A migration `_220000` os cercou para o código antigo não enviar. Não é envio ambíguo e não há risco de duplicidade. Se devem ou não ser notificados é decisão de produto, **ainda aberta**; nenhum replay foi feito.

## O que esta verificação não prova

- Não mostra `current_user`; a visibilidade integral em (a) é [INFERIDO] (6 usuários, contagem pequena).
- Um envio EVT-7 antigo em curso no cutover não deixa rastro no banco; os zeros só excluem V1a e a outbox nova.
- (b), gates de envio fechados (`ALLOW_REAL_SENDS`, `BREVO_SEND_MODE`, `BROADCAST_ASYNC_ENABLED`), **não verificado**.

## Veredito

Entrega ambígua não contabilizada não aparece em nenhuma tabela. V2b: consistente no banco; (b) e o EVT-7 em voo seguem sem prova.

## Pendências

1. Verificar (b) com os valores atuais dos três gates em PROD.
2. Decisão de produto sobre notificar ou não os 11 eventos.

Relacionado: [registro V2b](2026-09-27-whatsapp-agenda-v2b.md).
