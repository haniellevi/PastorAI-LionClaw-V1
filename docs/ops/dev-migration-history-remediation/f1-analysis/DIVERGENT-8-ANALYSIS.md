# Análise F1, oito posições divergentes

## Escopo e regra de leitura

Este anexo cobre exatamente as posições `25` a `32` do ledger público DEV
registradas no anexo F1 congelado. A evidência sanitizada usada nesta análise
tem SHA-256 `b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b`.
Os nomes da ordem aplicada e do catálogo vêm dos artefatos versionados, não da
transcrição externa. Não houve reprodução de transcrição, consulta nova a DEV,
alteração de ledger, reordenação, backfill ou reaplicação.

A coluna de assinatura usa a auditoria estrutural corrigida da matriz e a
comparação de chaves seguras do anexo de referência, SHA-256 canônico
`944f77ac4e84421cf1ba89e6d0dc7bb52e314721ff5e7222baaaa611838a6e5e`.
Presença parcial de componentes não transforma o ledger aplicado em prefixo,
nem permite reconhecer uma entrada ausente como aplicada. Cada posição continua
uma dependência obrigatória de qualquer epoch ou cutover futuro.

| Posição DEV | Item aplicado no ledger | Item esperado pelo catálogo | Assinatura F1 do item esperado | Implicação para epoch ou cutover |
| ---: | --- | --- | --- | --- |
| 25 | `20260808_011500_messages_outbound_provider_id_uidx.sql` | `20260701_014654_evt6_google_event_dedup_index.sql` | `PHYSICAL_EFFECTS_PRESENT`, `REL 1/1; IDX 1/1` | A relação aplicada não corresponde ao primeiro item esperado. O índice esperado existe, mas o epoch deve modelar a inversão sem inferir histórico. |
| 26 | `20260801_031500_calendar_account_identity_binding.sql` | `20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql` | `PHYSICAL_EFFECTS_PRESENT`, `REL 1/1; COL 1/1` | A dependência de coluna está fisicamente presente; a ordem divergente permanece e não autoriza ledger backfill. |
| 27 | `20260805_105133_broadcast_delivery.sql` | `20260701_193000_evt7_pr2_agenda_alert_recipients.sql` | `PARTIAL_OR_CONFLICTING`, fonte `REL 1/1; COL 7/7; CON 2/2; IDX 2/2; POL 1/1`; R1 tem `CATALOG_RELATION 0/1` | O epoch deve preservar a comparação entre estrutura, RLS e ACL, sem reduzir o drift a uma lista de tabelas. |
| 28 | `20260805_120000_calendar_fk_indexes.sql` | `20260703_123803_celula_schema_base_pr1.sql` | `PARTIAL_OR_CONFLICTING`, fonte `REL 2/2; COL 15/15; CON 5/5; IDX 4/4; POL 1/1; TYPE 1/1`; R1 tem `CATALOG_RELATION 0/1` | Índices e FKs aplicados fora do prefixo dependem de contratos anteriores; a presença não reescreve essa dependência temporal. |
| 29 | `20260805_153000_security_definer_execute_hardening.sql` | `20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql` | `PARTIAL_OR_CONFLICTING`, fonte `REL 3/3; COL 25/25; CON 14/14; IDX 10/10; POL 3/3`; R1 tem `CATALOG_RELATION 0/3` | São três relações próprias, não quatro. A assinatura fonte fecha três relações, mas a comparação DEV/ref não fecha suas três chaves; o hardening aplicado continua fora da posição canônica e exige epoch explícito. |
| 30 | `20260808_135841_llm_model_selection_per_tenant.sql` | `20260705_120000_celula_pr3_reuniao_relatorio_campos.sql` | `PHYSICAL_EFFECTS_PRESENT`, `REL 1/1; COL 6/6; CON 1/1; IDX 1/1` | Schema não prova qualquer preenchimento histórico. O cutover futuro mantém a separação entre assinatura física e efeito em linhas. |
| 31 | `20260810_031050_explicit_deny_policies_for_closed_tables.sql` | `20260705_120100_celula_pr3_reuniao_registro.sql` | `PARTIAL_OR_CONFLICTING`, fonte `REL 1/1; COL 9/9; CON 6/6; IDX 2/2; POL 1/1`; R1 tem `CATALOG_RELATION 0/1` | Policies e ACL do item aplicado requerem revisão conjunta com RLS e defaults; não podem ser tratadas como reconhecimento implícito do item esperado. |
| 32 | `20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql` | `20260705_120200_celula_pr3_visitante.sql` | `PARTIAL_OR_CONFLICTING`, fonte `REL 1/1; COL 9/9; CON 4/4; IDX 2/2; POL 1/1`; R1 tem `CATALOG_RELATION 0/1` | A redefinição de função aplicada e a relação esperada pertencem a histórias distintas. Nenhuma associação entre as duas é autorizada. |

## Consequência operacional

Contagem: `8/8` posições, sem posição adicional. As posições 25, 26 e 30 têm
assinatura F1 fechada; 27, 28, 29, 31 e 32 ficam parciais pela comparação R1.
A ordem continua divergente nas oito posições e o ledger aplicado não é prefixo
do catálogo. A estratégia A continua precisar de um epoch explícito que
preserve os dois ledgers e trate cada dependência sem reaplicação por posição.
Este anexo não autoriza banco, DEV, VPS, PROD, migration, cutover ou modificação
de histórico.
