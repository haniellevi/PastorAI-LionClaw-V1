# Inventário F1, catálogo ausente do ledger público DEV

## Regra de leitura

Esta matriz é fonte estática do SHA base
`e1da65d0a6fa5286674f425f855600eb3e4982bb`. A diferença de 44 arquivos vem
do recibo sanitizado já versionado em
`docs/ops/migration-head77-dev-apply-readiness/DEV-LEDGER-RECONCILIATION.md`.
Ela não é uma fila para aplicação e não constitui observação nova de DEV.

`Status F1` é o estado atual e deve ser `PENDING_DEV_OBSERVATION` nas 44
linhas. `Teto sem dados` define a única classe terminal possível depois de
coletar os metadados: para migrações com efeito em linhas, seed ou no-op
condicional, a conclusão final precisa incluir `NOT_SCHEMA_DECIDABLE`, sem ler
domínio. Uma assinatura estrutural encontrada nunca transforma esse limite em
prova de DML histórico.

| Código | Evidência necessária no `DEV-READONLY-F1.sql` |
| --- | --- |
| `E1` | `CATALOG_RELATION`, `CATALOG_COLUMN` e `CATALOG_TYPE`, sem ler linhas |
| `E2` | `CATALOG_CONSTRAINT` e `CATALOG_INDEX`, por hash de definição e flags |
| `E3` | `CATALOG_RLS_POLICY`, incluindo flags RLS e hash de expressão, sem expressão bruta |
| `E4` | `CATALOG_FUNCTION` e `CATALOG_TRIGGER`, por hash de definição e metadados seguros |
| `E5` | `SCHEMA_ACL_DIRECT_GRANTEE`, `RELACL_DIRECT_GRANTEE`, `PROACL_DIRECT_GRANTEE`, `DEFAULT_ACL_DIRECT_GRANTEE` e `UNEXPECTED_CUSTOM_GRANTEE_SUMMARY`, nos escopos `public`, `agent_private`, `recovery` mascarado e global `defaclnamespace=0`; cada ACL mantém `grantee_class` e emite `grantee_ref=PUBLIC`, nome somente para `ALLOWLIST_ROLE` ou `PLATFORM_ROLE`, ou `UNEXPECTED_CUSTOM_GRANTEE` sem nome ou OID para grantee fora da allowlist |
| `E6` | `CATALOG_ROLE_AGENT_RUNTIME` e `CATALOG_ROLE_AGENT_RUNTIME_MEMBERSHIP` |
| `E7` | `PUBLIC_LEDGER_ENTRY`, `NATIVE_LEDGER_ENTRY` e `NATIVE_LEDGER_STATEMENT_FINGERPRINT`; uso apenas secundário |

| # | SQL do catálogo e SHA-256 | Efeito esperado, fonte estática | Evidência read-only necessária | Teto sem dados | Status F1 |
| ---: | --- | --- | --- | --- | --- |
| 1 | `20260701_014654_evt6_google_event_dedup_index.sql`<br>`497e51e3401ee23fe3a3ddd8ec92a27bb22dd3173a9402450d0ac16a9fb248e7` | Índice único de deduplicação de evento externo em `events`. | `E1,E2,E7`: relação-base, índice, predicado hash e posição opaca do ledger. | Estrutural: `PHYSICAL_EFFECTS_PRESENT`, `PHYSICAL_EFFECTS_ABSENT` ou `PARTIAL_OR_CONFLICTING`. | `PENDING_DEV_OBSERVATION` |
| 2 | `20260701_164352_evt7_events_notificado_em_aviso_confirmacao.sql`<br>`673d80cad9af0a6aef43162862c09e6884be38bc8392bf5f413bff4e8687d176` | Coluna temporal de notificação em `events`. | `E1,E7`: tipo, nulidade, default hash e ledger. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 3 | `20260701_193000_evt7_pr2_agenda_alert_recipients.sql`<br>`65a9100c7c8130b6197a42e1cc198dd7b482ede8ba18f5bf46e7db3af1d96ead` | Relação de destinatários de alerta, índices, RLS e policy tenant. | `E1,E2,E3,E5,E7`: relação, colunas, constraints, índices, RLS/policy e ACL/default ACL. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 4 | `20260703_123803_celula_schema_base_pr1.sql`<br>`09607912f73c40cce56285de6545a1b8224566de67334d2a6df4f748ccca8ec3` | Campos de `celulas`, enum de papel e relação de membros com índices/RLS. | `E1,E2,E3,E5,E7`: colunas, enum hash, relação, constraints, índices e policy. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 5 | `20260704_100000_celula_pr2_reuniao_presenca_expectativa.sql`<br>`af1293c536ba79909db28125a7278aeabbc5959519611320f539b4023ab9609a` | Relações de reunião, presença e expectativa, com checks, índices e RLS. | `E1,E2,E3,E5,E7` para as três relações. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 6 | `20260705_120000_celula_pr3_reuniao_relatorio_campos.sql`<br>`689b8391f75ae212e69f3d6a50394433570031632563deae7a84f4d88306e69f` | Campos e estado de relatório na relação de reunião, check e índice. | `E1,E2,E7`: colunas, default hash, check e índice. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 7 | `20260705_120100_celula_pr3_reuniao_registro.sql`<br>`c8c43027f40ee9ac5a4e7b286afcbeac8241ea398a2f8c80e26796a3065ceeff` | Relação de registros de reunião, índices e isolamento tenant. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 8 | `20260705_120200_celula_pr3_visitante.sql`<br>`ecd7328b95df43a82cd3ae6e9bf1261f9cc1e257ccf67a6614c716b2f3a18afe` | Relação de visitante de reunião, índices e isolamento tenant. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 9 | `20260705_120300_celula_pr3_solicitacao_evento.sql`<br>`8a1ffcd7947ca68689ae8970944a50b2fcd0858eb7f395f3b7fad1e06c442bf1` | Relações de solicitação e evento append-only, índices, RLS, função e trigger. | `E1,E2,E3,E4,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 10 | `20260705_120400_celula_pr3_aviso.sql`<br>`aee8a18764a3ec0fe53efb3d802ed05d3519db90e4763c47b1c14e4e2b5ac263` | Relação de avisos de célula, índices e isolamento tenant. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 11 | `20260705_120500_celula_pr3_material.sql`<br>`d39c83f2023160a98211160212b4724f70525f3777b0011ce192132f00d68922` | Relação de material de célula, índice e isolamento tenant. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 12 | `20260705_120600_celula_pr3_multiplicacoes_evolucao.sql`<br>`3846299ac5c06abc750028c8cb91844de8ff82eac584af49c8ebc53ab777f4a2` | Campos, FKs, checks, índices e policy na relação de multiplicações. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 13 | `20260706_221311_pessoas_apto_lider_e_converte_legado_tipo_lider.sql`<br>`ee557f4bcdf50fb8ec3e6f0a6e82046cf519f2f0523ea40a81e4d27d0fdaf2e0` | Campo de aptidão e conversão de classificação legada de pessoas. | `E1,E7` somente para a coluna; a conversão não é lida. | `NOT_SCHEMA_DECIDABLE` para a conversão de linhas. | `PENDING_DEV_OBSERVATION` |
| 14 | `20260706_230000_evt8_pr1_notify_config.sql`<br>`1c172564734812522466fd6cc20087c0a8af3d8673dde4882ea4a807fa3d9b71` | Campos de notificação em eventos e relação de destinos com índices/RLS. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 15 | `20260707_011455_igreja_logo_branding.sql`<br>`dbebd871c779d6dac52f6c6dfe5cecef8e054c59236fe52d774eb4b746ae069d` | Campo de branding, policy de atualização própria, ACL de coluna e atributo de função. | `E1,E3,E4,E5,E7`: coluna, policy, função hash e ACL direta/default. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 16 | `20260708_160128_sec3a_app_users_password_changed_at.sql`<br>`6e6efad7a4ca0a4062496e1854a9ada1d85b1acdd1e2bd12c041c9d982cf79e6` | Coluna temporal de troca de senha em `app_users`. | `E1,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 17 | `20260708_164756_backfill_celula_membro_canonico.sql`<br>`614419cf2e6122b2b6438a3fda9cc27adebd47d3a88b44e5e2fa2909ed19d803` | Reconciliação e inserção de vínculos canônicos de membros. | `E7` somente como evidência secundária; F1 não lê `celula_membro`. | `NOT_SCHEMA_DECIDABLE`. | `PENDING_DEV_OBSERVATION` |
| 18 | `20260708_172106_sec3b_password_reset_tokens_single_use.sql`<br>`9a9ba9f5059c97db68053fbac4ff91adedbbbe8c0111c2909623e910a60951f3` | Relação de tokens de recuperação e índices de busca/expiração. | `E1,E2,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 19 | `20260708_221808_igreja_dono_id_grant_update.sql`<br>`18afa38fb59fe9aca65a467732da9d38926d3b8921d1d83ab1acad9f235d265d` | Grant de atualização de coluna de responsável da igreja. | `E5,E7`: ACL direta e defaults; nenhuma linha é lida. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 20 | `20260709_204500_sec4_agent_event_idempotency_marker_uidx.sql`<br>`11fdad1ad9aca3e1eb1c627cb551083e94b98bc948b73b0e6cb0c77a6ad3a34f` | Índice único de marcador idempotente em log do agente. | `E1,E2,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 21 | `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql`<br>`d8b55db78f765d48006b739d2b3524f00e7ad059a342b92ac78ae7c6b336408c` | Reclassificação de pessoas por vínculo ativo. | `E7` somente secundário; nenhuma relação de domínio é lida. | `NOT_SCHEMA_DECIDABLE`. | `PENDING_DEV_OBSERVATION` |
| 22 | `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql`<br>`e4112a55e5cde97fd9e8b409d418c00ae85857b121c7e277ba8c8e3472603edf` | Reclassificação de pessoas baseada em normalização temporária de telefone. | `E7` somente secundário; F1 não consulta dados de pessoa. | `NOT_SCHEMA_DECIDABLE`. | `PENDING_DEV_OBSERVATION` |
| 23 | `20260711_224403_celula_solicitacao_e13_open_unique.sql`<br>`0afeb7815d8f532cd53fdfc97ff7f41e08e142914faa5350848df4c3845aa295` | Dois índices únicos parciais para solicitações abertas. | `E1,E2,E7`: índices, validade e predicado hash. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 24 | `20260713_013054_pessoa_arquivamento_schema.sql`<br>`de5974001f0cc8cf9ea81a83bac9ff855a4f357940e4ba26a869a3c4f95461fa` | Campos de arquivamento em pessoas. | `E1,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 25 | `20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql`<br>`38ec86859577aa1bd7a92e7f37068746d63f8aa3c8bd995e012624725bf2ebef` | Campos de abandono, relação de evento append-only, índices, RLS, função e trigger. | `E1,E2,E3,E4,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 26 | `20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql`<br>`bc0de9a9f9cd72d6c0b48b59b343331fb2d0a6e3e486afc6144b439801918949` | Ajuste de metadado de mensagem e índice único parcial para identificador inbound. | `E1,E2,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 27 | `20260715_204541_consolidacao_aberta_unica_por_pessoa.sql`<br>`9c35fdb7688f96b4f7ce911bd3b55d9779fb6ae471998778ae148f463bcfbfdf` | Índice único parcial de consolidação aberta por pessoa. | `E1,E2,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 28 | `20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql`<br>`a960dc473c827f883e19c689b3f17aaadbe5d72c1484e8f912ca74b1a7de3486` | Índice único parcial de telefone ativo por tenant. | `E1,E2,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 29 | `20260720_191143_consent_records_ator_id_reoptin.sql`<br>`2e51ac31c71c2ccd512c2777625546535697aa803c5df4c9c192030dbda431aa` | Coluna de ator em registros de consentimento. | `E1,E2,E7`: coluna e eventual FK/constraint. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 30 | `20260730_205332_billing_setup_configuration.sql`<br>`b90e080a63078a157be099bb5560851fc4515e5795a8925226c5e66139ad401d` | Campos de billing, operações duráveis, funções, triggers, RLS/ACL e configuração inicial. | `E1,E2,E3,E4,E5,E7`; a configuração seed não é lida. | `NOT_SCHEMA_DECIDABLE` para seed e qualquer reconciliação em linhas. | `PENDING_DEV_OBSERVATION` |
| 31 | `20260731_120000_calendar_oauth_flows_pkce.sql`<br>`33ad252c321cade9ec4f104461c4aa5db7c367c4a5bb99a4e5661cca57f76762` | Relação de fluxo OAuth com PKCE, RLS e ACL explícita. | `E1,E2,E3,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 32 | `20260808_001059_billing_count_active_members.sql`<br>`46b99e59173aea51e939b133af0cf2e2ab715923d84f9502e6e6d8651775a3c6` | Função e trigger de contagem, ACL de função e reconciliação de dados/labels. | `E1,E2,E4,E5,E7`; não lê subscriptions, planos ou operações. | `NOT_SCHEMA_DECIDABLE` para atualizações e reconciliação em linhas. | `PENDING_DEV_OBSERVATION` |
| 33 | `20260808_014425_billing_member_plan_label_variants.sql`<br>`1bf06d9d876f1170ffe312573a94cba03071962171f3917163b5383f6a49a8ad` | Atualização de labels de planos existentes. | `E7` somente secundário; F1 não lê `planos`. | `NOT_SCHEMA_DECIDABLE`. | `PENDING_DEV_OBSERVATION` |
| 34 | `20260808_023500_billing_reconcile_prepared_member_upgrades.sql`<br>`a2fac3d504991885233e5c1537933f30d133aaa6684df51f4f891ed477a6888f` | Reconciliação de operações de upgrade preparadas. | `E7` somente secundário; F1 não lê operações ou assinaturas. | `NOT_SCHEMA_DECIDABLE`. | `PENDING_DEV_OBSERVATION` |
| 35 | `20260822_225752_celula_membro_evento_audit_table.sql`<br>`e4958484f2edacb795a8eea209118819200f9cc2e17e69f768b34fd43ac010ac` | Relação de auditoria append-only, índices, RLS, função e trigger. | `E1,E2,E3,E4,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 36 | `20260824_180000_asaas_formal_isolation.sql`<br>`0cacaf819ca2113b284673886700eb8be79b71094a7ac180c2b4c72c84d3e3e3` | Constraints e índices de billing, relação de recibos, RLS e ACL formal. | `E1,E2,E3,E5,E7`; pré-condições de linhas não são consultadas. | Estrutural para efeitos físicos; preflight histórico não é inferido. | `PENDING_DEV_OBSERVATION` |
| 37 | `20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql`<br>`6d02a1437f9d71d05dba7c294c05b1db30b9e580c30b9efb4aadc92a7368430c` | Separação de estado de resposta e autoria em metadados de mensagem. | `E1,E2,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 38 | `20260826_094317_harden_recovery_artifacts_retention.sql`<br>`a6fa9abccbfec240ceb460d52f5bcbbda677c18691230d0e0c4f047fdd603fb0` | Hardening condicional de artefatos de recuperação já existentes, com RLS, deny policy e ACL. | `E1,E3,E5,E7`, com nomes de artefato mascarados; F1 não conta nem lê linhas. | `NOT_SCHEMA_DECIDABLE`: ausência pode ser no-op válido e preservação histórica de acesso não é reconstituível por schema. | `PENDING_DEV_OBSERVATION` |
| 39 | `20260827_175634_d1a_tenant_runtime_integrity.sql`<br>`7ac3191bbe7217beff4e9601da78c29aef13abfef229505335ba7017a630d0c3` | FKs compostas tenant, validação e índices de integridade de runtime. | `E1,E2,E7`: constraints validadas, índices e predicados por hash. | Estrutural para efeitos físicos; preflight de dados não é inferido. | `PENDING_DEV_OBSERVATION` |
| 40 | `20260827_230003_d2a_agent_runtime_private_context.sql`<br>`3071b0d7c2f8f7103914e161383ddac5d15698dccfd2e9860251c4bd98f7ec83` | Role sem login, schema privado, helper tenant e ACLs/memberships mínimos. | `E1,E4,E5,E6,E7`: `agent_private` e `public` quando aplicável, função por hash, `nspacl`, `relacl`, `proacl`, default ACL do schema e global, atributos e memberships; `grantee_ref` nomeia somente `ALLOWLIST_ROLE` ou `PLATFORM_ROLE`, preserva `PUBLIC` e mascara qualquer grantee customizado sem nome/OID. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 41 | `20260828_045213_d2b2_consentimento_finalidade_evento.sql`<br>`30742755922b42e6e1407743df51b28d4619efd2a5e6b474bcba1beb7b8443ea` | Ledger de consentimento, constraints, índices, funções, triggers, RLS e ACL mínima. | `E1,E2,E3,E4,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 42 | `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql`<br>`506bb53f81caed2f30c8ae250c159e0653fdade12bd9124c1f9fd2dda4bf4666` | Envelope de rascunhos de governança, validador, índices, RLS e ACL fechada. | `E1,E2,E3,E4,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 43 | `20260909_004005_consent_evidence_store_lab.sql`<br>`caccfbbcdfc3f57d5adc0ee9d9016e92e8fa1bc05929059966d86292ddb43b1a` | Relações de desafio, evidência e recibo, guardas, triggers, RLS, policies e ACL. | `E1,E2,E3,E4,E5,E7`. | Estrutural. | `PENDING_DEV_OBSERVATION` |
| 44 | `20260910_142830_add_e4b_consent_persistence.sql`<br>`64c031beea4d74feed83337ea623173d0f8d848c685ffcf5365b279a6ea7d1fd` | Seis relações E4b, índices, guardas, triggers, RLS forçada, policies e revokes. | `E1,E2,E3,E4,E5,E7` para todas as seis relações. | Estrutural. | `PENDING_DEV_OBSERVATION` |

## Checagem de completude estática

- Linhas de inventário: `44`.
- Itens com teto `NOT_SCHEMA_DECIDABLE`: `9`.
- Itens que ainda podem ser classificados por assinaturas exclusivamente de
  schema: `34`, sem que isso prove a história do ledger.
- Todas as 44 linhas continuam pendentes de observação DEV humana.

Qualquer objeto homônimo, diferença de tipo, hash, constraint, índice, policy,
trigger, ACL, default ACL, role ou RLS deve resultar em
`PARTIAL_OR_CONFLICTING`, nunca em aplicação inferida. A saída do ledger
nativo só pode corroborar o fluxo de execução por fingerprint; ela não altera
essa regra.
