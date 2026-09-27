# Revisão V1a, outbox e retenção, rodada intermediária

**Estado:** NÃO APTO neste snapshot. Três achados precisam de correção e revisão do delta.

## Blobs conferidos

| Arquivo | SHA-256 |
| --- | --- |
| `backend/app/services/cell_report_reminders.py` | `83eaef93a21bc2a7b11050b5f99516f939b198c59567c2c4b0d4268ff04ae2a5` |
| `backend/app/agent/runtime.py` | `06336b1f64e6a663eaa38da33472881d4ce4c722686d6c8b5ab7caa39d1849fd` |

Não repeti os dez cenários já identificados pelo root: gates de envio/piloto, identidade e telefone ambíguo, estado da reunião, liderança/célula, horário e destino alterado entre claim e fence.

## P1, deadlock entre PARAR e claim

O dispatcher trava primeiro `CellReportReminder`, depois `Conversation` e `Pessoa`, em `_claim_next_reminder()` e `_reminder_gates_allow()`. O comando persistido `PARAR LEMBRETES` trava `Conversation`, depois `Pessoa`, e atualiza os reminders em `disable_cell_report_reminders()`.

Dois processos podem formar o ciclo R→C→P e C→P→R. Se a transação de recusa for vítima, o controle do usuário reverte e o dispatcher ainda pode alcançar o transporte. A correção deve usar uma ordem comum, preferencialmente Conversation→Pessoa→Reminder, com seleção sem claim, revalidação e claim do reminder somente depois dos locks do contexto. O teste PG precisa barreirar PARAR contra claim e provar ausência de 40P01 e de transporte após o commit da recusa.

## P2, deadlock entre scheduler e confirmação de relatório

O scheduler trava Reunião/Célula e depois Conversation/Pessoa. A confirmação S3 trava Conversation e o finalizador trava Reunião/Célula. Na mesma reunião, scheduler e SIM podem formar M→C e C→M. Um dos lados aborta; a confirmação pode exigir retry.

A mesma ordem canônica deve abranger essa trilha, com Pessoa/Conversation antes de Reunião/Célula ou uma serialização equivalente por líder. O teste PG deve colocar scheduler e confirmação em barreira e exigir finalização ou cancelamento seguro, sem 40P01 e sem lembrete depois de relatório enviado.

## P2, retry sem teto

`reminder_result_transition()` devolve `retry` sem incrementar `attempts` quando `consume_retry_budget=False`. A própria prova focal trata isso como comportamento válido. Até a janela de 24 horas, um adaptador que mantenha essa classificação pode repetir indefinidamente, contrariando o limite aprovado de duas tentativas pré-envio em 1 e 5 minutos.

Contar toda falha pré-envio no orçamento, ou registrar formalmente uma exceção aprovada de backpressure, fecha a ambiguidade. Sem uma dessas decisões, o contrato não é verificável.

## Pontos já corretos no snapshot

A mensagem é fixa e não leva PII; a outbox guarda apenas digest. Claim e fence são confirmados em transações curtas antes de HTTP, e erro/resultado desconhecido vira ambíguo, sem reenvio automático. O fence relê os gates e a purga terminaliza claims vencidos e limpa rascunho expirado mesmo com a feature desligada.

O root informou sete testes PG básicos verdes neste snapshot. Não executei banco, transporte ou provedores.

## Limites

Cron e orçamento permanecem fora deste parecer, conforme escopo. Este relatório também não prova deploy, flag ativa, envio real ou operação em ambiente compartilhado.


## P1, relógio congelado durante o lote

`dispatch_cell_report_reminders()` calcula `current` uma vez e reutiliza esse instante em claim, fence, horário permitido, expiração e resultado. Em produção, um lote lento pode enviar um item depois das 21h locais usando a prova de 20:59, ou renovar uma lease para um instante que já passou.

O dispatcher deve buscar relógio novo por claim, fence e resultado quando `now` não foi injetado. O `now` explícito dos testes pode continuar fixo. A prova precisa simular avanço de relógio no lote e exigir ausência de HTTP fora da janela e ausência de fence com lease já vencida.
