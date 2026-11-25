# Preparação da janela de virada: reconciliação e propostas para revisão

Data: 24/11/2026. Registro histórico da PR #701, mesclada em `d4f614c2`.
O [ROADMAP, Fase 4](../../ROADMAP.md#fase-4--ferramenta-da-virada-apontada-para-a-main)
registra a atualização vigente: A = `e1c63ed1`, revalidação pós-SIM aprovada
como procedimento, janela bloqueada até J4 corrigido com teste e dry-run
completo na VPS aprovado e limpo. A aprovação do procedimento não é SIM
operacional; este documento preserva a evidência e as propostas originais.

Critério de conclusão desta preparação: explicar nominalmente 52 versus 57,
propor aprovação com revalidação após a resposta do dono e explicitar a
implantação e a prova do link ativo no J9, sem executar a janela.

## Fontes, identidades e alcance

| Fonte | Evidência e limite |
|---|---|
| Git local, base `origin/main` conferida nesta preparação | `41c5b1802d733e289e83f579f890f3d610f812f7`; checkout inicialmente limpo. Todos os nomes e classificações de SQL abaixo foram derivados dessa árvore e confrontados com A. |
| Aplicação A, na preparação original da #701 | `6af9f75c8d673cb3454de1f8740a0acc509937ff`, backend e painel. Identidade histórica, substituída por `e1c63ed1`; nenhum retorno a `afdfb78d`. |
| Aplicador fixo | `37c7d68d60b6f86cfb1fe75d4c720530537845d6` (`EXECUTOR_SHA`). Não confundir com a ferramenta T. |
| Ferramenta T | O Git auditado contém o seletor atual. O SHA exato de T instalado/usado no V8 precisa vir do recibo operacional e ser conferido na futura leitura autorizada. Esta nota não afirma que a ponta documental está instalada na VPS. |
| Última leitura de produção informada pelo Raniel nesta tarefa | Em 24/11: 78 linhas em `public.schema_migrations`; última aplicada `20261002_173000_visitor_expectation_whatsapp.sql`, aplicada em 14/10/2026. Não foi feita nova consulta nem recebido aqui o conjunto nominal completo dessas 78 linhas. |
| Relato operacional de 24/11 fornecido nesta tarefa | Três tentativas de J1–J2 abortaram antes de J3; caso `e691`, cerca de 77 s úteis, resposta em cerca de 82 s, aproximadamente 5 s após expirar a idade da prova. Link ativo ausente, legado em `/opt/pastorai-lionclaw`; V8 preparou o layout de A com `production_ready=false`. São fatos reportados, sem revalidação nesta preparação. |

Foram lidos somente código, SQL e documentação versionados e metadados Git.
Não houve SSH/VPS, leitura de `.env`/segredos, consulta a banco remoto,
execução de ferramenta da virada, migration, backup ou alteração de produção.

## 1. Reconciliação nominal das migrations

O princípio é comparar conjuntos de nomes com a mesma regra de seleção.
Subtrair uma contagem do banco de uma contagem de arquivos não identifica o
conjunto pendente nem comprova ausência de nomes desconhecidos ou duplicados.

### 1.1 Como a seleção funciona no Git

Em [first_transition_adapter.py](../../deploy/first_transition_adapter.py),
`prepare()` usa `git_tree()` para ler os blobs de **A**, com o padrão
`backend/migrations/[A-Za-z0-9_.-]+\.sql`: apenas SQL diretamente no topo.
Exclui qualquer SQL que contenha `OPERATIONAL_AUTHORIZATION=BLOCKED`.
A baseline esperada é o conjunto ativo cujo nome é menor que `20261015`,
excetuando os quatro nomes de `MISSING` (os itens 1 a 4 da seção 1.2).
`Plan.pending` é a diferença entre as migrations ativas e essa baseline.
O próprio `prepare()` exige `(ativas, baseline, pendentes) = (130, 78, 52)`;
[first_transition_orchestrator.py](../../deploy/first_transition_orchestrator.py)
exige `SHAPE = (52, 44, 8)`.

Já [migrate.py](../../backend/scripts/migrate.py), funções `migration_files`,
`pending`, `_applied` e `cmd_status`, lista SQL de topo, exclui o mesmo marcador
e compara **o nome literal** com o ledger lido no banco. `cmd_apply` recusa
SQL pausado. Não há nessa seleção uma regra de equivalência por outro nome,
checksum ou alias. O plano da virada é uma expectativa fixa do Git; o status
com banco é uma observação viva. Não executar `status` nesta tarefa.

A conferência local encontrou os mesmos **135 nomes e bytes SQL** no topo de
`backend/migrations/` da base `41c5b180` e de A. A partição completa está nas
seções 1.2, 1.3 e 1.4, sem sobreposição ou arquivo omitido:

| Conjunto no Git | Quantidade | Interpretação |
|---|---:|---|
| SQL de topo | 135 | Contagem bruta, incluindo frentes bloqueadas. |
| Ativas para a ferramenta e `migrate.py` | 130 | 135 menos as cinco pausadas. |
| Baseline esperada pela ferramenta | 78 | Lista nominal da seção 1.4; não é cópia do ledger vivo. |
| Pendentes esperadas pela ferramenta | 52 | Lista exata da seção 1.2: 44 transacionais e 8 concorrentes. |
| Extras da diferença bruta | 5 | Lista da seção 1.3; excluídas por marcador explícito. |
| Diferença bruta contra a baseline esperada | 57 | 135 menos 78 = 52 ativas pendentes + 5 pausadas. |

**Conclusão de alta confiança no alcance do Git:** os cinco extras são SQL
de frentes pausadas, com aplicação operacional bloqueada. Nenhum dos cinco
é descartado como mero auxiliar ou arquivo sem efeito de aplicação. Não se
encontrou regra no seletor que os considere aplicados com outro nome.
A afirmação de que estes são exatamente os 57 nomes fora do **ledger de
produção** continua condicionada à igualdade nominal entre o ledger vivo e
a baseline da seção 1.4. Só 78 linhas e a última aplicada não provam isso.

O [catálogo histórico](../governance/migrations/migration-catalog-head-v1.json)
registra `current_head.migration_count = 77`, até
`20260910_142830_add_e4b_consent_persistence.sql`. É evidência offline de uma
frente de governança pausada, não um ledger nem a fonte das 130 ativas.
O [README de migrations](../../backend/migrations/README.md) suspende o
processo catalog-bound; não usar seus wrappers nem reabrir governança para
explicar esta diferença. O [ROADMAP](../../ROADMAP.md), quadro da seção 2 e
Fase 4, registra 130 ativas, cinco pausadas e 52 pendentes. Os trechos antigos
sobre 129/51 ou `afdfb78d` são históricos; a referência atual de A está no
[ROADMAP, Fase 4](../../ROADMAP.md#fase-4--ferramenta-da-virada-apontada-para-a-main).
Os SQLs de topo não mudaram entre a identidade histórica e a atual.
A lista antiga de 51 no [runbook do lote](RELEASE-LOTE-2026-10.md#lista-exata-das-51-pendentes-ordem-lexical-de-migratepy)
corresponde aos itens 1 a 51 abaixo, antes da inclusão do item 52.

### 1.2 Lista exata das 52 pendentes esperadas

Ordem lexical de aplicação. `tx`: transação; `NT`: `CREATE INDEX CONCURRENTLY`,
com `--no-transaction` pelo executor revisado. Os oito nomes NT vêm de
`REVIEWED_CONCURRENT`. A lista não autoriza aplicar nenhum arquivo.

| # | Nome em `backend/migrations/` | Modo |
|---|---|---|
| 1 | `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql` | tx |
| 2 | `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql` | tx |
| 3 | `20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` | tx |
| 4 | `20260926_120446_platform_jev_settings.sql` | tx |
| 5 | `20261016_180000_prayer_requests.sql` | tx |
| 6 | `20261017_180000_visit_events.sql` | tx |
| 7 | `20261017_180100_consolidacao_atribuicoes_aceite.sql` | tx |
| 8 | `20261017_210500_uv_turmas.sql` | tx |
| 9 | `20261017_220000_uv_presencas.sql` | tx |
| 10 | `20261017_230000_uv_marcos_conclusao.sql` | tx |
| 11 | `20261018_010000_cd_catalogo_turmas.sql` | tx |
| 12 | `20261018_020000_cd_matriculas.sql` | tx |
| 13 | `20261018_030000_cd_presencas.sql` | tx |
| 14 | `20261018_040000_cd_conclusoes_certificados.sql` | tx |
| 15 | `20261018_050000_enviar_avaliacoes.sql` | tx |
| 16 | `20261018_060000_enviar_nomeacao.sql` | tx |
| 17 | `20261018_070000_enviar_abertura.sql` | tx |
| 18 | `20261018_080000_enviar_reforcos.sql` | tx |
| 19 | `20261018_090000_exclusao_privada.sql` | tx |
| 20 | `20261018_100000_enviar_reencontro.sql` | tx |
| 21 | `20261018_110000_cd_equivalencias_versoes.sql` | tx |
| 22 | `20261018_120000_prayer_message_privacy.sql` | tx |
| 23 | `20261018_130000_conhecimento_oficial.sql` | tx |
| 24 | `20261018_140000_conhecimento_trechos.sql` | tx |
| 25 | `20261019_090001_exclusao_privada_pessoa_igreja.sql` | tx |
| 26 | `20261019_110001_conhecimento_exclusao.sql` | tx |
| 27 | `20261019_120001_private_conversation_summaries.sql` | tx |
| 28 | `20261020_100000_prayer_audio_privacy.sql` | tx |
| 29 | `20261020_200000_private_resume.sql` | tx |
| 30 | `20261021_100000_responsabilidades_setor.sql` | tx |
| 31 | `20261022_100000_private_erasure_requests.sql` | tx |
| 32 | `20261023_100000_ai_usage_force_rls.sql` | tx |
| 33 | `20261023_100001_ai_usage_tenant_created_idx.sql` | NT |
| 34 | `20261023_110000_operations_outbox_pending_metrics_fn.sql` | tx |
| 35 | `20261023_110001_notification_outbox_pending_created_idx.sql` | NT |
| 36 | `20261023_110002_notification_outbox_retry_created_idx.sql` | NT |
| 37 | `20261023_110003_notification_outbox_expired_lease_idx.sql` | NT |
| 38 | `20261023_110004_messages_pending_agent_created_idx.sql` | NT |
| 39 | `20261023_110005_work_queue_pending_created_idx.sql` | NT |
| 40 | `20261023_120000_auth_session_revocation.sql` | tx |
| 41 | `20261025_100000_team_pessoa.sql` | tx |
| 42 | `20261027_100000_reset_settles_erasure_requests.sql` | tx |
| 43 | `20261028_100000_private_memory_overview.sql` | tx |
| 44 | `20261028_100001_private_erasure_requests_overview_idx.sql` | NT |
| 45 | `20261028_100002_private_resume_delivered_overview_idx.sql` | NT |
| 46 | `20261029_100000_reset_settles_church_erasure_requests.sql` | tx |
| 47 | `20261030_100000_private_storage_worker_identity.sql` | tx |
| 48 | `20261030_110000_private_upload_attempt_witness.sql` | tx |
| 49 | `20261030_120000_private_send_release_identity.sql` | tx |
| 50 | `20261030_140000_private_summary_runtime_identity.sql` | tx |
| 51 | `20261030_160000_queue_worker_runtime_identity.sql` | tx |
| 52 | `20261112_160000_celula_alerta_regras.sql` | tx |

O item 52, **`20261112_160000_celula_alerta_regras.sql`**, integra A e a
seleção atual. Sua presença impede tratar a lista antiga de 51 como final.
O [runbook §12.7](PRODUCTION-RUNBOOK.md#127-conferências-estáticas-da-fase-44-sha-a--6af9f75c8d673cb3454de1f8740a0acc509937ff)
descreve também seu efeito em `cell_alerts`, RLS e permissões; sua aplicação
não autoriza ativar alertas.

### 1.3 Os cinco extras que explicam 57 no Git

Todos contêm o marcador literal `OPERATIONAL_AUTHORIZATION=BLOCKED` na linha 2.
São preservados no inventário e ficam fora de `prepare`, `status` e `apply`.

| Nome em `backend/migrations/` | Classificação pelo cabeçalho versionado |
|---|---|
| `20260827_230003_d2a_agent_runtime_private_context.sql` | Fundação privada/inativa D2A: identidade sem LOGIN, schema privado e helper de tenant; pausada. |
| `20260828_045213_d2b2_consentimento_finalidade_evento.sql` | Ledger oficial de consentimento por finalidade; pausada. |
| `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql` | Rascunhos governados por finalidade no Console Master; pausada. |
| `20260909_004005_consent_evidence_store_lab.sql` | Candidate de laboratório de evidências de consentimento, source-only até autorização própria; pausada. |
| `20260910_142830_add_e4b_consent_persistence.sql` | Persistência de consentimento E4B; pausada. |

Não remover esses arquivos, retirar o marcador, inserir nomes no ledger ou
renomeá-los para ajustar a aritmética. Presença no ledger sob outro nome e
aplicação histórica desses SQL em produção: **não verificadas**. Caso uma
futura leitura encontre alias, nome desconhecido ou pausada aplicada, registrar
a divergência e decidir nominalmente; não normalizar o ledger automaticamente.

### 1.4 Lista das 78 migrations da baseline esperada, derivada do Git

Esta lista completa, junto às 52 e às cinco acima, enumera **todos os 135 SQL
de topo da main auditada**. O rótulo baseline significa a expectativa do
seletor, sem afirmar que cada nome foi observado no banco em 24/11.

```text
0001_extensions_and_enums.sql
0002_schema_tables.sql
0003_rls_policies.sql
0004_triggers.sql
0005_seed.sql
0006_harden_function_search_path.sql
0007_remove_demo_data.sql
0008_add_operador_role.sql
0009_unify_system_managers.sql
0010_platform_admins.sql
0011_app_users_celula_pendente.sql
0012_planos.sql
0013_platform_audit_log.sql
0014_platform_orchestrator.sql
0015_message_media.sql
0016_message_author.sql
0017_app_user_status_revogado.sql
20260623_103319_pessoa_sem_interesse_csim.sql
20260623_122044_calendar_sync_oauth_por_igreja.sql
20260623_154500_pessoa_tipo_add_contato.sql
20260623_170000_igreja_dono_assinatura.sql
20260624_003030_current_igreja_id_guc_worker.sql
20260624_090102_current_igreja_id_guard_empty_claims.sql
20260624_171110_agent_config_requests_fila_requisicao_admin_master.sql
20260629_222635_evt1_events_agenda_schema_status_tipo_origem_recorrencia_confirmacao.sql
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
20260711_224403_celula_solicitacao_e13_open_unique.sql
20260713_013054_pessoa_arquivamento_schema.sql
20260713_032015_pessoa_offboarding_preflight_arquivamento_evento.sql
20260715_204540_msg_idemp1_messages_inbound_provider_id_uidx.sql
20260715_204541_consolidacao_aberta_unica_por_pessoa.sql
20260720_014832_pessoa_telefone_unico_por_tenant_ativa.sql
20260720_191143_consent_records_ator_id_reoptin.sql
20260730_205332_billing_setup_configuration.sql
20260731_120000_calendar_oauth_flows_pkce.sql
20260801_031500_calendar_account_identity_binding.sql
20260805_105133_broadcast_delivery.sql
20260805_120000_calendar_fk_indexes.sql
20260805_153000_security_definer_execute_hardening.sql
20260808_001059_billing_count_active_members.sql
20260808_011500_messages_outbound_provider_id_uidx.sql
20260808_014425_billing_member_plan_label_variants.sql
20260808_023500_billing_reconcile_prepared_member_upgrades.sql
20260808_135841_llm_model_selection_per_tenant.sql
20260810_031050_explicit_deny_policies_for_closed_tables.sql
20260810_042300_exclude_complimentary_plans_from_billing_autoupgrade.sql
20260822_225752_celula_membro_evento_audit_table.sql
20260824_180000_asaas_formal_isolation.sql
20260826_030508_separar_estado_resposta_agente_de_autor_mensagem.sql
20260826_094317_harden_recovery_artifacts_retention.sql
20260827_175634_d1a_tenant_runtime_integrity.sql
20260926_191500_agent_public_profile.sql
20260927_120000_church_cell_public_data.sql
20260927_170000_whatsapp_privilege_actions.sql
20260927_190000_cell_report_whatsapp_v1a.sql
20260927_210000_cell_report_audio_v1b.sql
20260927_220000_notification_outbox_v2b.sql
20260928_080000_whatsapp_consolidation_v3.sql
20261002_173000_visitor_expectation_whatsapp.sql
```

### 1.5 Reprodução local e pendência viva

Conferência reproduzível, sem importar ou executar os módulos da virada,
sem dependência de banco, arquivo privado ou `.env`. Rodar na árvore auditada;
o primeiro comando lista todos os SQL de topo da main dessa base:

```bash
git ls-tree --name-only 41c5b1802d733e289e83f579f890f3d610f812f7:backend/migrations | sort | rg '\.sql$'
python3.13 - <<'PYTHON'
import ast
import subprocess

base = "41c5b1802d733e289e83f579f890f3d610f812f7"
def blob(ref, path):
    return subprocess.check_output(["git", "show", f"{ref}:{path}"])
module = ast.parse(blob(base, "deploy/first_transition_adapter.py"))
assignments = {n.targets[0].id: n.value for n in module.body
               if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
a = ast.literal_eval(assignments["APPLICATION_SHA"])
missing = ast.literal_eval(assignments["MISSING"].args[0])
def sqls(ref):
    names = subprocess.check_output([
        "git", "ls-tree", "--name-only", f"{ref}:backend/migrations"
    ]).decode().splitlines()
    return {n: blob(ref, "backend/migrations/" + n)
            for n in names if n.endswith(".sql")}
files = sqls(base)
assert files == sqls(a)
paused = {n for n, sql in files.items() if b"OPERATIONAL_AUTHORIZATION=BLOCKED" in sql}
active = files.keys() - paused
baseline = {n for n in active if n < "20261015" and n not in missing}
pending = active - baseline
assert tuple(map(len, (files, active, baseline, pending, paused))) == (135, 130, 78, 52, 5)
for label, names in (("BASELINE_ESPERADA", baseline), ("PENDENTE_ESPERADA", pending), ("PAUSADA", paused)):
    for name in sorted(names):
        print(label, name)
PYTHON
```

Numa **nova leitura viva especificamente autorizada**, o operador deverá
obter somente os nomes e contagens do ledger pelo canal sanitizado previsto
no runbook, conferindo visibilidade e duplicações. Comparar o conjunto `L`
com as listas acima: `L == baseline`, `ativas - L == lista das 52`,
`SQL_de_topo - L == lista das 52 + cinco pausadas`, `L - ativas` vazio e
`L ∩ pausadas` vazio; contar linhas e nomes distintos separadamente.
Além de nomes, a janela exige a prova de catálogo/identidade e o preflight;
igualdade nominal não certifica o conteúdo integral do schema.
Se o conjunto divergir, a reconciliação viva fica pendente e a ferramenta
não deve ser contornada. Esta leitura não foi feita nem autorizada por esta PR.

## 2. Proposta de aprovação com prova de estado após a resposta

O princípio proposto é vincular o SIM à identidade e aos efeitos imutáveis
e medir a atualidade do estado **depois da resposta**, antes dos efeitos.
A proposta preserva os blocos SIM 2, SIM 3, SIM 4 e SIM 5; SIM 2 não passa a
autorizar `run`, DDL, A10, publicação do painel ou o backup real do J9.

### 2.1 Problema e evidência disponível

No relato do Raniel de 24/11, três tentativas de J1–J2 encerraram antes de
J3. No caso `e691`, restavam cerca de 77 s úteis e a resposta chegou cerca de
82 s depois, aproximadamente 5 s além da idade admitida da prova. A repetição
da mesma pergunta com uma prova já envelhecida recria o problema.
Os tempos são aproximados e vêm do relato desta tarefa, sem logs consultados.

O [runbook §12.2](PRODUCTION-RUNBOOK.md#122-janela) separa abertura/pausa do
backup (SIM 2) do `run` inteiro (SIM 3), e a
[§12.6](PRODUCTION-RUNBOOK.md#126-kit-e-roteiro-do-dia) exige os digests do
`prepare` final após fixar as exclusões do restore. Em
[first_transition_window.py](../../deploy/first_transition_window.py),
`prepare`/digests não são autorização humana; o modo operacional e as provas
de [first_transition_database.py](../../deploy/first_transition_database.py)
revalidam identidade, ledger e catálogo. A verificação estática dos arquivos
`deploy/first_transition*` não localizou implementação da validade da pergunta
SIM2 ou do caso `e691`: não se atribui o prazo do relato a um timer comprovado
nesses módulos. O registro operacional da pergunta/prova é uma evidência
adicional a conferir, não um comportamento novo implementado por esta PR.

### 2.2 Procedimento proposto na #701 (aceite posterior registrado no ROADMAP)

Registro da proposta original. O desenho foi aceito posteriormente, nos
limites da decisão da Fase 5 do ROADMAP, sem validar os SHAs ou artefatos
históricos abaixo para uma nova execução.

1. **Congelar o pedido antes de perguntar.** Identificar ambiente/igreja e
   operador, ação exata do bloco e efeitos, A completo acima, T integrado
   completo efetivamente conferido, `EXECUTOR_SHA`, ID/digest imutável da
   imagem, hash do pacote, `plan_digest`, `window_digest`, hashes das
   configurações públicas e bindings, identidade do banco, baseline e digest
   do catálogo, IDs dos quatro legados/candidatos aplicáveis, rede e entradas.
   Fixar o estado esperado dos gates principais e por finalidade e os
   parâmetros/recibos do V9, inclusive exclusões do restore. Registrar só
   hashes/metadados autorizados, nunca conteúdo privado. Campos ausentes
   impedem a emissão do pedido final de SIM.
2. **Emitir um pedido único e rastreável.** Anotar ID, UTC da pergunta, corte
   absoluto da pergunta e escopo. O pedido declara que, após o SIM, ocorrerá
   nova leitura sem efeito para provar o mesmo estado antes da ação. A idade
   da prova prévia não consome o tempo de resposta humana: ela é contexto e
   será renovada. Permanecem os cortes de **15 min** vigentes, cada qual com
   sua âncora e finalidade explicitadas no pedido; não somar, alongar ou
   reiniciar esses cortes para fabricar tempo. Registrar também a duração
   máxima total da janela do J1, separadamente.
3. **Vincular a resposta ao pedido.** Registrar o SIM do dono, o ID do pedido,
   o bloco e UTC da resposta. Antes de aceitar, conferir que o corte absoluto
   da pergunta e, se iniciada, a janela continuam válidos. A resposta
   autoriza somente a ação descrita e sua revalidação sem efeito. Prova
   prévia vencida isoladamente não exige pedir o mesmo SIM outra vez dentro
   deste desenho proposto.
4. **Produzir prova viva posterior ao SIM.** Antes de J1–J2, refazer as
   conferências sem efeito pertinentes: artefatos e T/A, `prepare` confrontado
   com os digests congelados, `check`, `check-bindings`, imagem/IDs, gates de
   todos os processos, estado do cron/backup e vizinhos. Cada leitura deve
   ter UTC posterior à resposta, duração e resultado; cumprir a idade máxima
   vigente para uso da prova, sem ampliar 15 min. Comparar todos os campos
   semânticos congelados; podem mudar apenas tempos/identificador da nova
   observação. Uma conferência parcial ou sem visibilidade não aprova o bloco.
   Revalidar imediatamente antes do efeito; mudanças posteriores continuam
   sujeitas às recusas e observações da ferramenta. Essa prova pontual não
   oferece atomicidade nem substitui contenção.
5. **Executar somente o bloco autorizado, se aprovado o novo procedimento.**
   Com identidade e estado iguais, registrar início do J1 e pausar apenas o
   backup da Igreja 12 no J2; SIM 3 continua separado e exclusivo para J3–J6,
   incluindo o ponto de não retorno. Uma demora até o SIM 3 exige prova nova
   do estado antes de `run`, preservando a identidade aprovada e os cortes.
   Não iniciar `run` como mecanismo de teste da aprovação.
6. **Parar com motivo objetivo.** Divergência de SHA, imagem, pacote,
   plano/window digest, configuração, ledger/catalogo, IDs ou gates invalida
   o pedido para execução; mostrar o que mudou e submeter novo pedido se o
   dono quiser adotar a alteração. Não recalcular e adotar silenciosamente
   uma identidade diferente, mesmo que venha de `origin/main`. Corte real
   vencido, revogação ou impossibilidade de prova também encerram a tentativa.
   Renovar a observação do mesmo estado dentro dos limites não renova a
   validade da pergunta nem da janela. Se J2 já ocorreu, registrar cron pausado
   e seguir recuperação/encerramento pelo estado real e autorização aplicável,
   sem deixar a pausa esquecida ou assumir que religar o cron é inofensivo.

Manter um recibo sanitizado único por pedido: identidade congelada, horários
de pergunta/resposta/prova/efeito, cortes e suas âncoras, comparação, resultado
e eventual motivo de parada. Não repetir SIM por latência da conversa quando
a identidade permanece igual e os cortes continuam válidos. Novo escopo,
identidade ou corte vencido exige decisão explícita. Se a camada operacional
atual não consegue separar essas validades, ela precisa de ajuste revisado e
ensaio sintético antes do uso; esta nota não permite ignorar sua recusa.

### 2.3 Texto sugerido para autorização futura

> Autorizo adotar o procedimento da seção 2.2 para o pedido identificado de
> SIM 2 da Igreja 12, com A, T, aplicador, imagem, pacote, digests, configurações,
> gates e efeitos integralmente preenchidos e congelados antes da minha
> resposta. Após meu SIM, o operador pode obter prova viva sem efeito e,
> somente se o estado e a identidade coincidirem e os cortes originais
> permanecerem válidos, executar J1–J2. Não autorizo troca de SHA, identidade
> ou escopo, extensão nem reinício dos cortes de 15 min. Divergência ou corte
> vencido encerra a tentativa. SIM 3, A10, publicação e J9 mantêm seus blocos
> próprios. Esta autorização do procedimento não é o SIM 2 de uma janela.

Na proposta original, o aceite do desenho era pendente. O aceite posterior
está registrado no ROADMAP; nenhum SIM operacional é inferido do merge da PR.

## 3. `/opt/pastorai-current`: lacuna e fechamento no J9

O princípio é publicar o ponteiro ativo somente quando A estiver efetivamente
ativo e provar o backup com a configuração real que o cron passará a usar.
Layout preparado não comprova release ativo nem backup funcional.

### 3.1 O que está documentado e o que foi reportado no host

O relato de 24/11 informa `/opt/pastorai-current` inexistente, instalação
legada viva em `/opt/pastorai-lionclaw` e layout de A preparado pelo V8 em
`/opt/pastorai-releases/6af9f75c8d673cb3454de1f8740a0acc509937ff/`, com
`production_ready=false`. Não foi feita inspeção do host nesta tarefa.

O [runbook §12.2/J9 e §12.2.2](PRODUCTION-RUNBOOK.md#1222-j9-backup-diário-e-topologia-efetiva-após-a-virada-43)
já descreve configurar o link e provar um backup antes de religar o cron;
a [§12.6/V8](PRODUCTION-RUNBOOK.md#126-kit-e-roteiro-do-dia) só prepara o layout.
A leitura estática de `first_transition_candidate.py` e do host driver não
mostra publicação desse symlink na primeira virada. O release normal em
[backend-release.sh](../../deploy/backend-release.sh) usa o link ativo;
não executar esse release para preencher o buraco da primeira transição.

[backup-production.sh](../../deploy/backup-production.sh) usa por padrão
`/opt/pastorai-current/deploy/.env` e
`/opt/pastorai-current/deploy/docker-compose.yml`, recusando se os arquivos
não estiverem disponíveis. O modelo aprovado usa arquivo privado externo
por `PASTORAI_ENV_FILE`, sem criar `.env` dentro do release. Assim, criar o
link sozinho não prova que o backup conseguirá rodar: Compose, overrides,
arquivo privado e entrada de cron precisam corresponder ao runtime efetivo.
A ausência atual do link não demonstra que o backup legado esteja quebrado,
pois sua configuração efetiva não foi inspecionada aqui.

O quadro do ROADMAP que ainda diz “J9 só religa o cron, sem testar” está
desatualizado em relação à sua própria tarefa 4.3 e ao runbook atual. A lacuna
vigente é de implantação e comprovação no host, incluindo a publicação do
link; esta nota não registra execução desses passos.

### 3.2 Proposta nominal de implantação, somente na janela autorizada

1. **Responsável e momento.** Raniel é o dono/aprovador; o agente operador
   nominal da janela executa somente sob o SIM explícito da fase 5.5 que
   inclua J9 e seus efeitos. Após A10 e J8 aprovados, antes do teste manual e
   de religar o cron, criar `/opt/pastorai-current` apontando para o diretório
   exato de A acima. Não criar no V8 nem apontar para o legado ou para um A
   apenas preparado. Registrar, antes do efeito, se o caminho segue ausente,
   qual é o release realmente ativo, a topologia e o alvo exato aprovado.
2. **Publicar sem sobrescrever estado inesperado.** Confirmar pacote/layout
   de A e Compose/overrides obrigatórios, projeto, rede, imagem e IDs ativos.
   Confirmar que o link continua ausente; se existir, resolver e comparar o
   alvo antes de qualquer mudança. Diretório/arquivo inesperado, link quebrado
   ou alvo diferente exige parar e informar o Raniel. Para ausência confirmada,
   criar symlink sem sobrescrita e conferir o caminho resolvido e o SHA.
   Qualquer substituição precisa de avaliação própria, preservando o estado
   anterior; não usar `ln -sfn` nem apagar caminho para forçar o resultado.
3. **Fixar as dependências do backup.** Usar o arquivo privado externo efetivo
   de `candidate.env_file`, root-owned regular `0600`, `nlink=1`, pai `0700`,
   sem copiar seu conteúdo para o release ou esta documentação. Preservar o
   `docker-compose.override.yml` obrigatório dentro do layout verificado;
   overrides transitórios A9/A10 ficam fora. Registrar caminhos, hashes,
   ordem dos `-f`, projeto e serviços de apoio. Conferir Compose sem imprimir
   configuração privada. Instalar/conferir o pacote de backup e seu helper
   do T aprovado, ainda com cron pausado, conforme §12.2.2.
4. **Provar J9 antes do cron.** Executar uma vez, sob autorização real, o mesmo
   comando e ambiente mínimo do cron novo, com `PASTORAI_ENV_FILE` externo e
   `PASTORAI_COMPOSE_FILE` sob o link ativo. Registrar início/fim UTC e log
   exclusivo protegido, sem anexar conteúdo. Exigir conjuntamente: `rc=0`,
   `BACKUP_OK` novo com stamp no intervalo da tentativa, archive diferente
   do anterior, `sha256sum -c` do archive e do `SHA256SUMS` interno aprovados,
   e manifesto `backup-status.json` com `status="verified"`, archive/hash e
   `completed_at` correspondentes à mesma tentativa. `rc=0` por lock ocupado
   e manifesto antigo não provam um novo backup. Registrar os mesmos IDs de
   `pastorai_evolution`, `pastorai_evo_postgres` e `pastorai_redis` antes/depois,
   todos `running`, `paused=false`. Conferir saúde e gates preservados.
5. **Religar e encerrar só com prova completa.** Publicar cron novo
   `root:root 0644`, com o mesmo comando/ambiente do teste e o agendamento
   anterior preservado no fuso do host. Preservar o `.pausado` como evidência;
   não devolvê-lo com `mv`, pois faltaria o arquivo privado externo. Proteger
   o log do cron e preservar overrides/topologia com hashes para recuperação,
   pois o pacote de backup não os arquiva. Conferir cron ativo, timer alternativo
   inativo/desabilitado e J10/vizinhos. Guardar recibo sanitizado do alvo do
   link, SHA A/T, configuração por hashes e prova completa do backup.

Falha no J9 mantém o cron pausado e a janela pendente de encerramento.
Conferir imediatamente os apoios, inclusive após erro do backup. Seguir
§12.2.2 para recuperar apenas pausas comprovadamente pertencentes à tentativa,
um serviço por vez e pelo mesmo ID, sem iniciar/recriar serviço ausente ou
parado. Não remover o link automaticamente nem voltar ao legado após DDL:
a recuperação segue o estado/diário e requer decisão aplicável.

**O que não fazer agora:** não criar symlink, não provisionar/copiar arquivo
privado, não instalar backup/helper, não pausar/religar cron, não executar
backup, migrations, release ou `run`. O teste do J9 lê banco e Storage reais,
pode puxar imagens, pausa serviços de apoio e grava artefatos; fica reservado
à fase 5.5 autorizada. Esta preparação não muda `production_ready=false`.

## Conferência desta entrega

Inventário Git: 135 nomes únicos, particionados em 78 esperados na baseline,
52 pendentes esperados (44 tx + 8 NT) e cinco pausados; nomes e bytes iguais
entre a base auditada e A. Documento revisto contra seletor, aplicador,
catálogo histórico, ROADMAP e runbooks citados. Somente este arquivo novo em
`docs/ops`; sem mudança de código, SQL, ROADMAP, runbook vigente ou gates.

Ledger nominal vivo, T instalado, estado atual do host, adoção do novo SIM,
criação do link e prova real do J9: **não verificados nesta tarefa**.
Os checks de integração continuam exigidos antes de eventual merge conforme
AGENTS/ROADMAP; não houve execução local de suítes de aplicação, pois não há
mudança de código. A entrega solicitada é uma PR aberta para revisão, sem merge.


## Verificação local parcial de artefatos

`run --dry-run --config <config-local> --expect-plan-digest <digest-esperado>`
verifica a configuração, o plano, a identidade do pacote e o layout preparado.
A ferramenta fixa o candidato aprovado `e1c63ed1dfaaacf26c21a3cc8d9c8c3151c0aae0`
e o aplicador `37c7d68d60b6f86cfb1fe75d4c720530537845d6`; outras identidades
são recusadas. A mudança do candidato ou do controlador invalida recibos
anteriores e exige novas provas no escopo aprovado.

A saída agrega os estados `ok`, `refused`, `unavailable` e `not_evaluated`;
a ausência do digest esperado deixa o plano e o layout não avaliados. Quando
uma dependência falha, o layout permanece não avaliado. A saída sempre indica
`incomplete`, `j3_j6_approved=false` e retorno 2, mesmo quando as quatro
verificações passam. Não observa o ambiente, gates, vínculos, ledger vivo,
V9, vizinhos ou painel e não autoriza J3 a J6 nem substitui o dry-run integral.

Para preservar a restrição de somente leitura na VPS, execute em ambiente local
isolado: obtenha apenas cópias autorizadas e sanitizadas da configuração pública,
do layout e do hold; aponte seus caminhos para essas cópias locais. Use também
uma cópia local do repositório Git que contenha os objetos dos commits fixados
e o código do controlador revisado, pois a verificação lê os blobs Git e os
arquivos do controlador, além da configuração, layout e hold. Não copie arquivos
privados nem credenciais; esta entrada não os lê. As cópias não comprovam o
estado vivo da VPS. A comparação de migrations cria e remove uma árvore
temporária privada no diretório temporário do processo e executa a regra de
seleção do `migrate.py` do pacote, portanto use código revisado e um diretório
temporário local gravável; não execute essa verificação na VPS sob a restrição
de somente leitura.
