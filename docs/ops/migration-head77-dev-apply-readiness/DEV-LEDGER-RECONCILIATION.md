# Reconciliação do catálogo 77 com DEV

Status: `NO_GO / BLOCKED_LEDGER_DIVERGENCE`.

Base Git: `5e2082e94db2b6af6b34cfe351d81cf54b85aa76`.
Catálogo: 77 migrations, digest
`162854e0f753f5ad867aacae6b450d46d5c4bd68f8c3089be144d133ddc73801`.
Coleta DEV: `2026-09-14T23:18:03-03:00`, atribuída a `Igreja12-dev` por
confirmação humana de Raniel.

## Resultado determinístico

| Checagem | Resultado |
| --- | --- |
| Nomes públicos capturados | 33 |
| Nomes públicos desconhecidos no catálogo | 0 |
| Prefixo canônico coincidente | posições `0` a `24` |
| Posições capturadas divergentes | 8, posições `25` a `32` |
| Arquivos do catálogo ausentes do ledger público | 44 |
| Relações E4b | seis ausentes |
| Ledger nativo | seis versões independentes, sem mapeamento inferido |

O runner legado recusaria esse estado antes de SQL: o ledger público não é um
prefixo íntegro do catálogo e existem mais de uma migration pendente. Esta
constatação não autoriza alterar, preencher, reordenar ou copiar ledgers.

## Oito divergências de posição

| Posição | Ledger DEV | Catálogo canônico | Posição canônica do item DEV |
| --- | --- | --- | --- |
| 25 | `20260808_011500_messages_outbound_provider_id_uidx.sql` | `20260701_014654_evt6_google_event_dedup_index.sql` | 61 |
| 26 | `20260801_031500_calendar_account_identity_binding.sql` | `20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql` | 56 |
| 27 | `20260805_105133_broadcast_delivery.sql` | `20260701_193000_evt7_pr2_agenda_alert_recipients.sql` | 57 |
| 28 | `20260805_120000_calendar_fk_indexes.sql` | `20260703_123803_celula_schema_base_pr1.sql` | 58 |
| 29 | `20260805_153000_security_definer_execute_hardening.sql` | `20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql` | 59 |
| 30 | `20260808_135841_llm_model_selection_per_tenant.sql` | `20260705_120000_celula_pr3_reuniao_relatorio_campos.sql` | 64 |
| 31 | `20260810_031050_explicit_deny_policies_for_closed_tables.sql` | `20260705_120100_celula_pr3_reuniao_registro.sql` | 65 |
| 32 | `20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql` | `20260705_120200_celula_pr3_visitante.sql` | 66 |

## Quarenta e quatro arquivos ausentes do ledger público

```text
20260701_014654_evt6_google_event_dedup_index.sql
20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql
20260701_193000_evt7_pr2_agenda_alert_recipients.sql
20260703_123803_celula_schema_base_pr1.sql
20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql
20260705_120000_celula_pr3_reuniao_relatorio_campos.sql
20260705_120100_celula_pr3_reuniao_registro.sql
20260705_120200_celula_pr3_visitante.sql
20260705_120300_celula_pr3_solicitacao_evento.sql
20260705_120400_celula_pr3_aviso.sql
20260705_120500_celula_pr3_material.sql
20260705_120600_celula_pr3_multiplicacoes_evolucao.sql
20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql
20260706_230000_evt8_pr1_notify_config.sql
20260707_011455_igreja_logo_branding.sql
20260708_160128_sec3a_app_users_password_changed_at.sql
20260708_164756_backfill_celula_membro_canonico.sql
20260708_172106_sec3b_password_reset_tokens_single_use.sql
20260708_221808_igreja_dono_id_grant_update.sql
20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql
20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql
20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql
20260711_224403_celula_solicitacao_e13_open_unique.sql
20260713_013054_pessoa_arquivamento_schema.sql
20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql
20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql
20260715_204541_consolidacao_aberta_unica_por_pessoa.sql
20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql
20260720_191143_consent_records_ator_id_reoptin.sql
20260730_205332_billing_setup_configuration.sql
20260731_120000_calendar_oauth_flows_pkce.sql
20260808_001059_billing_count_active_members.sql
20260808_014425_billing_member_plan_label_variants.sql
20260808_023500_billing_reconcile_prepared_member_upgrades.sql
20260822_225752_celula_membro_evento_audit_table.sql
20260824_180000_asaas_formal_isolation.sql
20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql
20260826_094317_harden_recovery_artifacts_retention.sql
20260827_175634_d1a_tenant_runtime_integrity.sql
20260827_230003_d2a_agent_runtime_private_context.sql
20260828_045213_d2b2_consentimento_finalidade_evento.sql
20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql
20260909_004005_consent_evidence_store_lab.sql
20260910_142830_add_e4b_consent_persistence.sql
```

Esta lista é diferença de catálogo para ledger, não uma fila autorizada de
aplicação. Presença física, equivalência de schema e efeitos históricos de
cada item não foram atestados nesta coleta.
