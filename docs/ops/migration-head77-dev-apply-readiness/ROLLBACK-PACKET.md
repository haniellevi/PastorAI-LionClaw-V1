# Pacote de rollback e compensação segura

Status: `FORWARD_ONLY / NO_DESTRUCTIVE_DOWNGRADE`.

## Estado desta missão

Raniel executou somente o preflight DEV read-only, concluído com `ROLLBACK` e
zero alterações. Agentes não abriram conexão. Não houve aplicação de migration,
DDL, DML, alteração de VPS, deploy, commit ou outro efeito externo. O rollback
desta missão é descartar o patch documental local ou a worktree, conforme
decisão do Orquestrador. Não há rollback de banco a executar.

O estado DEV observado já contém divergência de ledger. Isso é condição de
aborto, não motivo para reordenar, preencher ou copiar entradas. A preservação
integral dos ledgers público e nativo é a única ação segura desta missão.

## Regra para aplicação futura

O SQL E4b declara recuperação `FORWARD_COMPENSATION`. Não existe autorização
para downgrade destrutivo, `DROP`, `DELETE`, truncamento, reexecução manual,
alteração de ledger, cópia entre ledgers ou restauração improvisada.

| Situação futura | Ação segura |
| --- | --- |
| Falha antes de decisão de commit | O executor futuro deve confirmar rollback da própria transação e encerrar. Não reaplicar nem reparar. |
| Perda de sessão, erro de transporte ou decisão de commit incerta | Classificar como estado desconhecido, congelar novas tentativas e iniciar apenas coleta read-only autorizada. |
| Commit comprovado, seguido de defeito de contrato | Suspender nova aplicação, preservar evidência sanitizada e abrir missão separada para migration forward-only de compensação. |
| Divergência de ledger ou metadado | Não alterar ledger nem objetos. Exigir decisão humana e investigação read-only separada. |
| Pedido de retorno a estado anterior por DDL | Recusar. A única rota é desenho, revisão, replay e gate próprios para compensação aditiva. |

## Requisitos de uma compensação futura

Uma migration de compensação precisa ser nova, append-only, `TENANT`, vinculada
ao SHA e ao head então aprovados, revisada sob RLS e ACL, comprovada em replay
PG17 descartável e autorizada nominalmente em missão separada. Ela deve
preservar a cadeia E4b, não apagar registros, não relaxar imutabilidade e não
assumir que ausência de payload equivale a ausência de aplicação.

Este pacote não autoriza a compensação, não determina seu SQL e não cria uma
janela DEV ou PROD.
