# Anexo F1, oito posições divergentes do ledger público DEV

## Fonte e limite

Este anexo reproduz a comparação fonte-a-fonte já registrada no pacote
integrado. O ledger público DEV capturado tinha 33 entradas, coincidia com o
catálogo nas posições `0` a `24` e divergia nas posições `25` a `32`. O anexo
não reconsulta DEV, não afirma estado físico e não modifica os ledgers.

As dependências abaixo são dependências estruturais ou pré-condições de
revisão extraídas dos SQL versionados no SHA base. Elas indicam o que F1 deve
observar antes de qualquer epoch/cutover futuro. Não autorizam aplicar,
reordenar ou inferir que o efeito já exista.

| Posição aplicada DEV | Nome aplicado no ledger público | Item esperado pelo catálogo na mesma posição | Posição canônica do aplicado | Dependência relevante para futuro epoch/cutover | Evidência F1 necessária |
| ---: | --- | --- | ---: | --- | --- |
| 25 | `20260808_011500_messages_outbound_provider_id_uidx.sql` | `20260701_014654_evt6_google_event_dedup_index.sql` | 61 | O índice outbound exige as colunas de mensagem e seu predicado; a posição canônica 61 fica depois das fatias de agenda e célula. A criação original é concorrente e não equivale a um item transacional de cutover. | `CATALOG_RELATION`, `CATALOG_COLUMN`, `CATALOG_INDEX`, `PUBLIC_LEDGER_ENTRY`. |
| 26 | `20260801_031500_calendar_account_identity_binding.sql` | `20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql` | 56 | O binding de identidade depende das relações de OAuth e sincronização já existentes e referencia acesso de usuário. Não pode ser separado do contrato anterior de fluxo OAuth. | `CATALOG_RELATION`, `CATALOG_COLUMN`, `CATALOG_CONSTRAINT`, `PUBLIC_LEDGER_ENTRY`. |
| 27 | `20260805_105133_broadcast_delivery.sql` | `20260701_193000_evt7_pr2_agenda_alert_recipients.sql` | 57 | O esquema de broadcast depende de entidades de igreja, pessoa e broadcast e introduz relações, RLS e ACL. Qualquer epoch precisa revisar também suas policies e grants, não só as tabelas. | `CATALOG_RELATION`, `CATALOG_COLUMN`, `CATALOG_CONSTRAINT`, `CATALOG_INDEX`, `CATALOG_RLS_POLICY`, ACL/default ACL. |
| 28 | `20260805_120000_calendar_fk_indexes.sql` | `20260703_123803_celula_schema_base_pr1.sql` | 58 | Os índices OAuth pressupõem a coluna de vínculo introduzida pelo item aplicado na posição 26 e as relações Calendar. A ordem relativa entre 26 e 28 é dependência material, ainda que ambas apareçam fora do prefixo. | `CATALOG_COLUMN`, `CATALOG_INDEX`, `PUBLIC_LEDGER_ENTRY`. |
| 29 | `20260805_153000_security_definer_execute_hardening.sql` | `20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql` | 59 | O hardening depende das funções que fecha e das roles previstas. A eventual função opcional não pode ser tratada como prova positiva se estiver ausente. | `CATALOG_FUNCTION`, `RELACL_DIRECT_GRANTEE`, `DEFAULT_ACL_DIRECT_GRANTEE`, `PUBLIC_LEDGER_ENTRY`. |
| 30 | `20260808_135841_llm_model_selection_per_tenant.sql` | `20260705_120000_celula_pr3_reuniao_relatorio_campos.sql` | 64 | A coluna de modelo depende da relação de credenciais; também contém preenchimento de valores existentes. Schema pode provar a coluna/constraint, não a atualização histórica. | `CATALOG_COLUMN`, `CATALOG_CONSTRAINT`, `PUBLIC_LEDGER_ENTRY`; conclusão de linhas fica `NOT_SCHEMA_DECIDABLE`. |
| 31 | `20260810_031050_explicit_deny_policies_for_closed_tables.sql` | `20260705_120100_celula_pr3_reuniao_registro.sql` | 65 | As policies explícitas exigem quatro relações pré-existentes e roles de infraestrutura. ACL, RLS e policy devem ser observadas juntas, inclusive defaults e grantees inesperados. | `CATALOG_RELATION`, `CATALOG_RLS_POLICY`, `RELACL_DIRECT_GRANTEE`, `SCHEMA_ACL_DIRECT_GRANTEE`, `DEFAULT_ACL_DIRECT_GRANTEE`. |
| 32 | `20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql` | `20260705_120200_celula_pr3_visitante.sql` | 66 | A redefinição de função depende de relações de billing e operações já existentes e reconcilia somente certo subconjunto de linhas. A função é observável; a reconciliação não é. | `CATALOG_FUNCTION`, `CATALOG_TRIGGER`, `RELACL_DIRECT_GRANTEE`, `PUBLIC_LEDGER_ENTRY`; efeito de linhas fica `NOT_SCHEMA_DECIDABLE`. |

## Consequência para a decisão futura

O ledger aplicado não é prefixo do catálogo. Qualquer proposta de epoch/cutover
precisa tratar as oito posições como um conjunto ordenado de drift, preservar
os dois ledgers e separar a prova de cada assinatura física da decisão humana
sobre história. A estratégia recomendada continua ser a reconciliação do
ambiente divergente, não uma reaplicação por posição nem a recriação como
substituto do ensaio necessário para PROD.
