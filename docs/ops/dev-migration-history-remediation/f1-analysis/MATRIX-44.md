# Matriz F1, auditoria estrutural dos 44 SQLs

## Proveniência, método e limite

Esta análise usa somente a transcrição sanitizada externa em modo leitura. A
evidência tem SHA-256 `b1c3e1bda63b55e7c5496d318bcf039d9a4d130de60ced535d918be233313e1b`,
modo `0600` e coleta informada em `2026-09-15T11:18:39-03:00`. Seus bytes não
foram copiados para o repositório.

Os anchors congelados permanecem o SQL F1
`8829decd0f0101329058ad07900ce7b7ca8b1c4fe5695f4e3cec05cff4bf288c` e o
agregado F1 `956187b9711ea9d67e9f8fdf31c3980e3ebbf64da98401c275f1dc80d2a91a29`.
Nenhum dos dez arquivos congelados foi alterado.

Cada SQL foi reaberto e auditado pela sua estrutura executável. Comentários,
literais e nomes apenas mencionados por `REFERENCES` não contam como efeitos
criados. Uma FK entra em `CON` no objeto que a declara, mas a relação
referenciada não aumenta `REL`. Funções `pg_temp` contam como temporárias e não
como função persistente. A assinatura escrita em cada linha é a auditoria de
fonte e referência; a igualdade DEV/ref por chave segura, hash e flags vem de
`R1`. Assim, uma assinatura de fonte `REL 3/3` não equivale a três chaves DEV
idênticas sem a confirmação `R1`.

- `REL`: relações persistentes alvo de CREATE, ALTER, índice, policy ou trigger.
- `COL`: colunas persistentes criadas ou adicionadas.
- `CON`: constraints explícitas e as chaves, uniques e FKs geradas pela declaração.
- `IDX`: nome, unicidade, parcialidade e flags de validade, prontidão e vida.
- `POL`: relação, policy e RLS; `FUN`: somente função persistente; `TRG`:
  relação, trigger e estado; `TYPE`: tipo e enum quando aplicável.
- `ACL`: somente quando o F1 enumera o nível de privilégio necessário. Grant
  por coluna não é enumerado pelo F1 e portanto não fecha uma assinatura.

Os hashes de definição, expressão e configuração permanecem evidência opaca do
catálogo, sem definição bruta no repositório. `PHYSICAL_EFFECTS_PRESENT` exige
que todas as subassinaturas estruturais aplicáveis da linha coincidam e que
`R1` seja `EQUAL`, sem chave do traço ausente da referência;
`PHYSICAL_EFFECTS_ABSENT` exige que nenhuma exista; `PARTIAL_OR_CONFLICTING`
cobre uma lacuna ou um nível de ACL não observável. Para DML, seed,
reconciliação ou no-op condicional, a coluna própria registra o estado
estrutural separado e a classe final é `NOT_SCHEMA_DECIDABLE`.

O índice opaco `R1` V3 separa `ACL_ONLY` quando toda diferença atribuível está
somente no campo `acl_state` de schema ou relation. Esse caso pode resultar da
execução local diante do contrato de plataforma Supabase e, isoladamente, não
prova drift DEV. Ele continua `PARTIAL_OR_CONFLICTING`, porque não é `EQUAL`.
Grants diretos, default ACL e grantee não são normalizados como `ACL_ONLY`.

Fatos sanitizados comuns: `PG170006`, `REPEATABLE READ`, `read_only=on`,
`row_security=off`, `TARGET_DIGEST` válido, `EXPECTED_33`, `EXPECTED_6`,
zero abortos F1, históricos `0/0` e nenhum record de domínio. O recibo externo
declarado é `ROLLBACK_COMPLETED_F1`; o índice opaco da transcrição observou o
comando psql de rollback, sem copiar a transcrição. A declaração humana independente é
`DEV_DATA_DISPOSITION=NO_VALUE_NO_PII`; esta matriz não a inferiu.

`D02` identifica somente as contagens e os históricos opacos dos ledgers;
`D03` o catálogo público; `D04` a ausência sanitizada de `agent_private`,
`recovery` e `agent_runtime`; `D05` os dois privilégios opacos de schema
público. `R1` é o replay PG17 local das 77 migrations, o traço por chave segura
e a comparação DEV/ref documentada no anexo de referência. Nenhum código de
evidência prova aplicação de migration.

| # | Migration do catálogo | Evidência DEV sanitizada | Assinatura estrutural auditada | Limite de DML ou histórico | Classificação F1 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `20260701_014654_evt6_google_event_dedup_index.sql` | `D02,D03,R1` | `REL 1/1; IDX 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 2 | `20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql` | `D02,D03,R1` | `REL 1/1; COL 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 3 | `20260701_193000_evt7_pr2_agenda_alert_recipients.sql` | `D02,D03,R1` | `REL 1/1; COL 7/7; CON 2/2; IDX 2/2; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 4 | `20260703_123803_celula_schema_base_pr1.sql` | `D02,D03,R1` | `REL 2/2; COL 15/15; CON 5/5; IDX 4/4; POL 1/1; TYPE 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 5 | `20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql` | `D02,D03,R1` | `REL 3/3; COL 25/25; CON 14/14; IDX 10/10; POL 3/3`. São exatamente três relações criadas; FKs não somam uma quarta relação. `R1` fecha `CATALOG_RELATION 0/3` em DEV/ref. | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 6 | `20260705_120000_celula_pr3_reuniao_relatorio_campos.sql` | `D02,D03,R1` | `REL 1/1; COL 6/6; CON 1/1; IDX 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 7 | `20260705_120100_celula_pr3_reuniao_registro.sql` | `D02,D03,R1` | `REL 1/1; COL 9/9; CON 6/6; IDX 2/2; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 8 | `20260705_120200_celula_pr3_visitante.sql` | `D02,D03,R1` | `REL 1/1; COL 9/9; CON 4/4; IDX 2/2; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 9 | `20260705_120300_celula_pr3_solicitacao_evento.sql` | `D02,D03,R1` | `REL 2/2; COL 25/25; CON 13/13; IDX 5/5; POL 2/2; FUN 1/1; TRG 1/1` | O DML em corpo de função não é executado pela criação da função. | `PARTIAL_OR_CONFLICTING` |
| 10 | `20260705_120400_celula_pr3_aviso.sql` | `D02,D03,R1` | `REL 1/1; COL 13/13; CON 6/6; IDX 2/2; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 11 | `20260705_120500_celula_pr3_material.sql` | `D02,D03,R1` | `REL 1/1; COL 11/11; CON 3/3; IDX 1/1; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 12 | `20260705_120600_celula_pr3_multiplicacoes_evolucao.sql` | `D02,D03,R1` | `REL 1/1; COL 5/5; CON 2/3; IDX 3/3; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 13 | `20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql` | `D02,D03,R1` | Estado estrutural: `REL 1/1; COL 1/1`. | A conversão de linhas não foi lida. | `NOT_SCHEMA_DECIDABLE` |
| 14 | `20260706_230000_evt8_pr1_notify_config.sql` | `D02,D03,R1` | `REL 2/2; COL 9/9; CON 6/6; IDX 4/4; POL 1/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 15 | `20260707_011455_igreja_logo_branding.sql` | `D02,D03,D05,R1` | `REL 1/1; COL 1/1; POL 1/1; ACL coluna 0/1`. | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 16 | `20260708_160128_sec3a_app_users_password_changed_at.sql` | `D02,D03,R1` | `REL 1/1; COL 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 17 | `20260708_164756_backfill_celula_membro_canonico.sql` | `D02,R1` | Estado estrutural persistente: `REL 0/0`. | Backfill e inserções históricas não foram lidos. | `NOT_SCHEMA_DECIDABLE` |
| 18 | `20260708_172106_sec3b_password_reset_tokens_single_use.sql` | `D02,D03,R1` | `REL 1/1; COL 6/6; CON 2/2; IDX 2/2`; os contadores fecham, mas `R1` tem chave do traço ausente da referência e não é `EQUAL`. | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 19 | `20260708_221808_igreja_dono_id_grant_update.sql` | `D02,D05,R1` | `ACL coluna 0/1`; o grant por coluna não é enumerado por `relacl`. | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 20 | `20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql` | `D02,D03,R1` | `REL 1/1; IDX 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 21 | `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql` | `D02,R1` | Estado estrutural persistente: `REL 0/0`. | Reclassificação de linhas não foi lida. | `NOT_SCHEMA_DECIDABLE` |
| 22 | `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql` | `D02,R1` | Estado estrutural persistente: `REL 0/0; FUN 0/0`; uma função temporária foi excluída. | Reclassificação de linhas não foi lida. | `NOT_SCHEMA_DECIDABLE` |
| 23 | `20260711_224403_celula_solicitacao_e13_open_unique.sql` | `D02,D03,R1` | `REL 1/1; IDX 2/2` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 24 | `20260713_013054_pessoa_arquivamento_schema.sql` | `D02,D03,R1` | `REL 1/1; COL 3/3` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 25 | `20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql` | `D02,D03,R1` | `REL 2/2; COL 9/9; CON 6/6; IDX 2/2; POL 1/1; FUN 1/1; TRG 1/1` | Preflight não lê dados nesta análise. | `PARTIAL_OR_CONFLICTING` |
| 26 | `20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql` | `D02,D03,R1` | `REL 1/1; COL 1/1; IDX 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 27 | `20260715_204541_consolidacao_aberta_unica_por_pessoa.sql` | `D02,D03,R1` | `REL 1/1; IDX 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 28 | `20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql` | `D02,D03,R1` | `REL 1/1; IDX 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 29 | `20260720_191143_consent_records_ator_id_reoptin.sql` | `D02,D03,R1` | `REL 1/1; COL 1/1` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 30 | `20260730_205332_billing_setup_configuration.sql` | `D02,D03,R1` | Estado estrutural: `REL 6/6; COL 55/55; CON 9/9; IDX 6/6; POL 4/4; FUN 1/1; ACL deny-only`. Não há alvo de schema `recovery`; `monthly_recovery` é literal ou comentário, não objeto estrutural. | Seed e reconciliação em linhas não foram lidos. | `NOT_SCHEMA_DECIDABLE` |
| 31 | `20260731_120000_calendar_oauth_flows_pkce.sql` | `D02,D03,R1` | `REL 1/1; COL 12/12; CON 5/5; POL 1/1; ACL 3/3`. | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_PRESENT` |
| 32 | `20260808_001059_billing_count_active_members.sql` | `D02,D03,R1` | Estado estrutural: `REL 1/1; FUN 1/1; TRG 1/1; ACL 1/1`. | Contagem, atualização e reconciliação de linhas não foram lidas. | `NOT_SCHEMA_DECIDABLE` |
| 33 | `20260808_014425_billing_member_plan_label_variants.sql` | `D02,R1` | Estado estrutural persistente: `REL 0/0`. | Atualização de labels não foi lida. | `NOT_SCHEMA_DECIDABLE` |
| 34 | `20260808_023500_billing_reconcile_prepared_member_upgrades.sql` | `D02,R1` | Estado estrutural persistente: `REL 0/0`. | Reconciliação de operações não foi lida. | `NOT_SCHEMA_DECIDABLE` |
| 35 | `20260822_225752_celula_membro_evento_audit_table.sql` | `D02,D03,R1` | `REL 1/1; COL 10/10; CON 7/7; IDX 3/3; POL 1/1; FUN 1/1; TRG 1/1` | O DML em corpo de função não é executado pela criação da função. | `PARTIAL_OR_CONFLICTING` |
| 36 | `20260824_180000_asaas_formal_isolation.sql` | `D02,D03,R1` | `REL 3/4; COL 0/8; CON 0/4; IDX 0/7; POL 0/1; ACL deny-only` | Preflight histórico não foi lido. | `PARTIAL_OR_CONFLICTING` |
| 37 | `20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql` | `D02,D03,R1` | `REL 1/1; COL 0/1; CON 0/1` | Sem efeito de linhas na aplicação. | `PARTIAL_OR_CONFLICTING` |
| 38 | `20260826_094317_harden_recovery_artifacts_retention.sql` | `D02,D04,R1` | Estado estrutural: `REL criado 0/0`; os alvos preexistentes são condicionais e mascarados. | No-op condicional e preservação de acesso ou retenção não são decidíveis por schema. | `NOT_SCHEMA_DECIDABLE` |
| 39 | `20260827_175634_d1a_tenant_runtime_integrity.sql` | `D02,D03,R1` | `REL 7/7; CON 13/13; IDX 11/11; FUN persistente 0/0`. Três helpers `pg_temp` foram excluídos; o coletor também vê três índices de suporte a constraints, separados da assinatura `IDX`. | Preflight só confirma invariantes no momento da aplicação, sem leitura nesta análise. | `PHYSICAL_EFFECTS_PRESENT` |
| 40 | `20260827_230003_d2a_agent_runtime_private_context.sql` | `D02,D04,R1` | `SCHEMA 0/1; ROLE 0/1; FUN 0/1; ACL de schema/default 0/1`. | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_ABSENT` |
| 41 | `20260828_045213_d2b2_consentimento_finalidade_evento.sql` | `D02,D03,R1` | `REL 0/1; COL 0/11; CON 0/13; IDX 0/1; POL 0/3; FUN 0/2; TRG 0/2; ACL 0/requerido` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_ABSENT` |
| 42 | `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql` | `D02,D03,R1` | `REL 0/1; COL 0/11; CON 0/10; IDX 0/2; FUN 0/1; ACL 0/requerido` | Preflight temporário não é DML de domínio. | `PHYSICAL_EFFECTS_ABSENT` |
| 43 | `20260909_004005_consent_evidence_store_lab.sql` | `D02,D03,R1` | `REL 0/3; COL 0/33; CON 0/35; IDX 0/2; POL 0/10; FUN 0/5; TRG 0/5; ACL 0/requerido` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_ABSENT` |
| 44 | `20260910_142830_add_e4b_consent_persistence.sql` | `D02,D03,R1` | `REL 0/6; COL 0/78; CON 0/53; IDX 0/9; POL 0/12; FUN 0/5; TRG 0/8; ACL 0/requerido` | Sem efeito de linhas na aplicação. | `PHYSICAL_EFFECTS_ABSENT` |

## Fechamento de cobertura

- Linhas de catálogo auditadas: `44/44`.
- `PHYSICAL_EFFECTS_PRESENT`: `13`.
- `PARTIAL_OR_CONFLICTING`: `17`.
- `PHYSICAL_EFFECTS_ABSENT`: `5`.
- `NOT_SCHEMA_DECIDABLE`: `9`.

O replay corrigiu classificações que antes dependiam de contagem e nome: doze
assinaturas de fonte não fecham por chave segura, hash ou flag contra DEV e por
isso passam a `PARTIAL_OR_CONFLICTING`. O item 5 mantém `REL 3/3` na fonte,
mas o anexo mostra `CATALOG_RELATION 0/3` em DEV/ref; o item 30 continua
`NOT_SCHEMA_DECIDABLE` pelo DML e sem referência a `recovery`; o item 39 fecha
por referência com 13 constraints e 11 índices explícitos, além de três
índices de suporte a constraints. O item 18 passa a parcial porque igualdade
de contagens não compensa uma chave do traço ausente da referência. O ledger
público permanece não-prefixo do catálogo; nenhuma classe autoriza alterar,
reordenar ou reconhecer entrada de ledger.
