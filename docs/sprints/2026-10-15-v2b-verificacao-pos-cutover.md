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

Eram eventos confirmados sem `notificado_em`, e a migration `_220000` os cercou (`legacy_evt7_sem_recibo`) para o código antigo não enviar. O serviço antigo só gravava `notificado_em` depois de enviar. Logo, um envio que teve sucesso e cujo processo morreu antes de gravar, ou um HTTP em voo no cutover, produziria exatamente este estado. **Classificação: entrega desconhecida**, não "nunca notificados". Enquanto não houver conciliação com o provedor ou com logs, notificá-los pode duplicar mensagem. Nenhum replay foi feito; a decisão de produto segue aberta e depende dessa conciliação.

## O que esta verificação não prova

- Não mostra `current_user`; a visibilidade integral em (a) é [INFERIDO] (6 usuários, contagem pequena).
- Um envio EVT-7 antigo em curso no cutover não deixa rastro no banco; os zeros só excluem V1a e a outbox nova.
- (b), gates de envio fechados (`ALLOW_REAL_SENDS`, `BREVO_SEND_MODE`, `BROADCAST_ASYNC_ENABLED`), **não verificado**.

## Veredito

Entrega ambígua não contabilizada não aparece nas tabelas consultadas. Não declaro o banco consistente: (a) segue pendente, e (b) e o EVT-7 em voo seguem sem prova.

## Pendências

1. Fechar (a): registrar `current_user` e comparar o total com o inventário independente aprovado (passo 0 da sequência de release V2b).
2. Verificar (b) com os valores atuais dos três gates em PROD.
3. Conciliar os 11 eventos com provedor/logs; só então decidir notificar ou não.

Relacionado: [registro V2b](2026-09-27-whatsapp-agenda-v2b.md).
