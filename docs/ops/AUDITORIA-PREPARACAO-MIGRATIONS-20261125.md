# Preparação da auditoria das 52 migrations

25/11/2026. Plano operacional subordinado à [Fase 4 do ROADMAP](../../ROADMAP.md#fase-4--ferramenta-da-virada-apontada-para-a-main) e ao [runbook de produção](PRODUCTION-RUNBOOK.md). Organiza a revisão por assunto; não autoriza execução, não altera o seletor, o aplicador ou as proteções vigentes e não constitui outro roadmap.

## 1. Evidências e linha de base

| Fonte | O que está comprovado e limite |
|---|---|
| Git, `main` remota `f4bb30df1d8f67bb11702e1e41b1806828fc9561` (25/11) | Os 135 SQLs de topo são idênticos aos de A (`e1c63ed1dfaaacf26c21a3cc8d9c8c3151c0aae0`). Backend e frontend de A permanecem congelados. A atualização #705 de metadados de imagem integra a main, mas não comprova a correção de J4 ou a prontidão operacional de T. |
| [Reconciliação #701, §§1.2–1.4](PREPARACAO-JANELA-VIRADA-20261124.md#12-lista-exata-das-52-pendentes-esperadas) | Listas nominais e modos de execução; comparados com os arquivos desta base e os cabeçalhos de pausa. |
| Recibo de leitura autorizada, 25/11 às 12:37:41 UTC | Em `public.schema_migrations`: 78 nomes esperados, 78 observados, zero ausentes, extras ou duplicados. Origens: 63 `PROVA_OBJETO`, seis `BASELINE_V1_HISTORICO`, nove `MIGRATE_PY`. O ledger nativo tem 32 registros, apenas históricos. É uma observação pontual de nomes, não uma prova de schema, dados, permissões, VPS ou autorização de execução. |
| Auditoria local `task_403d48169df1` e incremental `task_ef857b2157aa`, 25/11 | Inventário e classificação estáticos, indícios de dependências e propostas de checagem. A leitura nominal posterior resolve a lacuna dos 78 nomes, mas não comprova as demais pré-condições. As propostas foram adaptadas à ordem lexical vigente. |
| Histórico da tentativa de 24/11, no ROADMAP | V9 em clone: 52 aplicadas, ledger 130 e maior migration de 0,372 s (total 105,988 s). A tentativa real parou em J4 antes do marcador de DDL; não prova a execução final, nem a validade de um novo ensaio. |

Partição nominal conferida nesta preparação: 135 arquivos de topo = 78 observados no ledger + 52 ativas pendentes (44 transacionais, oito concorrentes) + cinco bloqueadas. Portanto havia 57 nomes de topo fora do ledger no instante da leitura; apenas 52 integram o candidato. O SQL aninhado em `private_runtime/` e os SQLs auxiliares não entram nessa seleção. O catálogo histórico pausado não é um ledger. Nenhum arquivo de migration, ordem de aplicação ou registro do banco foi alterado.

## 2. Grupos de revisão e critérios específicos

Os grupos abaixo são uma **sequência de revisão**, não lotes de aplicação. A matriz mantém a ordem lexical do aplicador e da ferramenta (uma migration por vez). Nos ensaios integrais, preservar essa ordem, inclusive quando duas linhas de um assunto estiverem separadas por outro grupo. Uma dependência indicada é um vínculo identificado na auditoria estática, a confirmar conforme o catálogo e o comportamento; não é prova de independência dos demais objetos.

| Grupo | IDs da matriz | Dependências e foco de aceite (pendentes de prova) |
|---|---|---|
| G1. Ajustes históricos | 01–04 | Revisar os dois ajustes de dados de pessoas em conjunto, conferir efeito esperado dos registros e proteção dos administradores; Jev permanece inativo conforme seus gates. |
| G2. Visitas, consolidação e setor | 06, 07, 30 | Baseline; conferir vínculos, recibos de aceite e disponibilidade/compatibilidade de `btree_gist` para responsabilidades. |
| G3. Universidade da Vida | 08–10, 20 | Turmas antes de presenças e marcos, que antecedem Reencontro; preservar etapa de pessoa e integridade do vínculo. |
| G4. Capacitação Destino | 11–14, 21 | Catálogo/turmas, matrículas, presenças, conclusões/certificados e equivalências; validar encadeamento e referências. |
| G5. Enviar | 15–18 | Avaliações; nomeação antes de abertura e reforços. Conferir consistência dos vínculos em solicitações de célula antes da validação das restrições. |
| G6. Conhecimento oficial | 23, 24, 26 | Base, trechos, exclusão; conferir existência de `unaccent`, origem oficial dos documentos e exclusão de derivados. |
| G7A. Segurança, métricas e pessoas | 32, 34, 40, 41 | Conferir isolamento, contrato de métricas e autenticação; validar ausência de duplicidades incompatíveis de vínculo de pessoa e efeito de revogação de sessões na troca de versão. |
| G7B. Índices concorrentes | 33, 35–39, 45 | Conferir tabela e índice esperados, validade após ensaio; 45 depende da base de retomada (29, G8B). Revisão deste índice fica condicionada à de sua base. |
| G8A. Oração e exclusão privada | 05, 19, 22, 25, 28 | Pedido de oração e exclusão formam a base para sigilo de mensagens, escopo de pessoa/igreja e mídia. Conferir proteção e retenção conforme PRD. |
| G8B. Memória, exclusão e reset | 27, 29, 31, 42, 43, 44, 46 | Depende de G8A; solicitações de exclusão antes dos resets, índice 44 depende de 31; conferir resumos, retomadas e visão consolidada. |
| G8C. Identidades de execução | 47–51 | Depende da base privada (G8A/B); 48 depende de 47. Revisão independente da segregação das identidades e dos contratos de acesso, com equivalência dos privilégios efetivos no ambiente autorizado. |
| G9. Alertas de célula | 52 | Baseline; conferir restrições, contrato do painel, RLS e permissões na tabela existente, sem ativar os alertas. |

## 3. Matriz nominal de revisão

`tx`: transacional; `NT`: índice concorrente, modo não transacional já previsto no executor. Todos os itens abaixo estão **pendentes de aceite de auditoria no candidato final**, inclusive os que tiveram prova histórica no V9. As checagens específicas complementam os critérios comuns da seção 5, não são resultados de testes.

| ID | Arquivo em `backend/migrations/` | Modo | Grupo | Foco da revisão |
|---|---|---|---|---|
| 01 | `20260711_023515_backfill_pessoa_tipo_membro_por_vinculo_ativo.sql` | tx | G1 | Efeito nas classificações e vínculos de pessoas; dados afetados, sem rollback comentado. |
| 02 | `20260711_152127_reclassifica_pessoa_do_numero_whatsapp_fora_de_membro.sql` | tx | G1 | Reclassificação de pessoas; dados afetados, sem rollback comentado. |
| 03 | `20260925_183811_preserve_platform_admins_on_tenant_deletion.sql` | tx | G1 | Preservação dos admins de plataforma na exclusão do tenant; compatibilidade de `app_users`. |
| 04 | `20260926_120446_platform_jev_settings.sql` | tx | G1 | Contrato de configuração Jev; nenhuma ativação. |
| 05 | `20261016_180000_prayer_requests.sql` | tx | G8A | Pedido de oração, privacidade e vínculo à igreja. |
| 06 | `20261017_180000_visit_events.sql` | tx | G2 | Eventos de visita, referências e ciclo de estado. |
| 07 | `20261017_180100_consolidacao_atribuicoes_aceite.sql` | tx | G2 | Atribuições, aceite e compatibilidade de recibos do agente. |
| 08 | `20261017_210500_uv_turmas.sql` | tx | G3 | Turmas, integridade de vínculos e acesso. |
| 09 | `20261017_220000_uv_presencas.sql` | tx | G3 | Presenças e dependência de turmas (08). |
| 10 | `20261017_230000_uv_marcos_conclusao.sql` | tx | G3 | Marcos/conclusão e impacto em `pessoas` (08–09). |
| 11 | `20261018_010000_cd_catalogo_turmas.sql` | tx | G4 | Catálogo versionado e turmas. |
| 12 | `20261018_020000_cd_matriculas.sql` | tx | G4 | Matrículas vinculadas às turmas (11). |
| 13 | `20261018_030000_cd_presencas.sql` | tx | G4 | Presença de matrícula (12). |
| 14 | `20261018_040000_cd_conclusoes_certificados.sql` | tx | G4 | Conclusões/certificados e integridade das presenças (13). |
| 15 | `20261018_050000_enviar_avaliacoes.sql` | tx | G5 | Avaliações e vínculo à pessoa. |
| 16 | `20261018_060000_enviar_nomeacao.sql` | tx | G5 | Nomeação; compatibilidade de `celula_solicitacao`. |
| 17 | `20261018_070000_enviar_abertura.sql` | tx | G5 | Abertura após nomeação (16). |
| 18 | `20261018_080000_enviar_reforcos.sql` | tx | G5 | Reforços após abertura (17); consistência das linhas existentes. |
| 19 | `20261018_090000_exclusao_privada.sql` | tx | G8A | Base de exclusão privada e compatibilidade de conversas. |
| 20 | `20261018_100000_enviar_reencontro.sql` | tx | G3 | Reencontro após turmas e marcos UV (08–10). |
| 21 | `20261018_110000_cd_equivalencias_versoes.sql` | tx | G4 | Equivalências entre versões e conclusões (11–14). |
| 22 | `20261018_120000_prayer_message_privacy.sql` | tx | G8A | Sigilo de mensagens de oração (05); compatibilidade de mensagens. |
| 23 | `20261018_130000_conhecimento_oficial.sql` | tx | G6 | Conhecimento oficial e autorização de publicação. |
| 24 | `20261018_140000_conhecimento_trechos.sql` | tx | G6 | Trechos derivados da base (23); disponibilidade de extensão. |
| 25 | `20261019_090001_exclusao_privada_pessoa_igreja.sql` | tx | G8A | Exclusão por pessoa/igreja (19); completude do escopo. |
| 26 | `20261019_110001_conhecimento_exclusao.sql` | tx | G6 | Exclusão de conhecimento e derivados (23–24). |
| 27 | `20261019_120001_private_conversation_summaries.sql` | tx | G8B | Resumos privados; contrato de conversas (19). |
| 28 | `20261020_100000_prayer_audio_privacy.sql` | tx | G8A | Privacidade de áudio e relação com orações (05, 22). |
| 29 | `20261020_200000_private_resume.sql` | tx | G8B | Retomada privada; vínculo com base de conversas e resumos. |
| 30 | `20261021_100000_responsabilidades_setor.sql` | tx | G2 | Responsabilidade por setor; restrições de vigência. |
| 31 | `20261022_100000_private_erasure_requests.sql` | tx | G8B | Pedidos de exclusão; base de exclusão (19, 25). |
| 32 | `20261023_100000_ai_usage_force_rls.sql` | tx | G7A | RLS de uso de IA; compatibilidade das permissões vigentes. |
| 33 | `20261023_100001_ai_usage_tenant_created_idx.sql` | NT | G7B | Índice de uso de IA por tenant e data. |
| 34 | `20261023_110000_operations_outbox_pending_metrics_fn.sql` | tx | G7A | Contrato de métricas de notificações pendentes. |
| 35 | `20261023_110001_notification_outbox_pending_created_idx.sql` | NT | G7B | Índice de criação das notificações pendentes. |
| 36 | `20261023_110002_notification_outbox_retry_created_idx.sql` | NT | G7B | Índice de repetição de notificações. |
| 37 | `20261023_110003_notification_outbox_expired_lease_idx.sql` | NT | G7B | Índice de notificações com lease expirado. |
| 38 | `20261023_110004_messages_pending_agent_created_idx.sql` | NT | G7B | Índice de mensagens pendentes do agente. |
| 39 | `20261023_110005_work_queue_pending_created_idx.sql` | NT | G7B | Índice de itens pendentes em `work_queue_items`. |
| 40 | `20261023_120000_auth_session_revocation.sql` | tx | G7A | Revogação de sessões e comportamento de autenticação. |
| 41 | `20261025_100000_team_pessoa.sql` | tx | G7A | Vínculo pessoa/equipe; ausência de duplicidade incompatível. |
| 42 | `20261027_100000_reset_settles_erasure_requests.sql` | tx | G8B | Reset de pessoa e fechamento de pedidos (31). |
| 43 | `20261028_100000_private_memory_overview.sql` | tx | G8B | Visão de memória privada, completude e isolamento. |
| 44 | `20261028_100001_private_erasure_requests_overview_idx.sql` | NT | G8B | Índice dos pedidos de exclusão (31). |
| 45 | `20261028_100002_private_resume_delivered_overview_idx.sql` | NT | G7B | Índice de retomadas entregues (29). |
| 46 | `20261029_100000_reset_settles_church_erasure_requests.sql` | tx | G8B | Reset de igreja e fechamento de pedidos (31). |
| 47 | `20261030_100000_private_storage_worker_identity.sql` | tx | G8C | Identidade de storage; revisão de acesso e domínio. |
| 48 | `20261030_110000_private_upload_attempt_witness.sql` | tx | G8C | Registro de tentativa de upload (47). |
| 49 | `20261030_120000_private_send_release_identity.sql` | tx | G8C | Identidade de envio privado; autorização e contrato do runtime. |
| 50 | `20261030_140000_private_summary_runtime_identity.sql` | tx | G8C | Identidade de resumos; autorização e escopo de memória. |
| 51 | `20261030_160000_queue_worker_runtime_identity.sql` | tx | G8C | Identidade da fila; execução e isolamento. |
| 52 | `20261112_160000_celula_alerta_regras.sql` | tx | G9 | Regras de alerta, compatibilidade da tabela existente e painel; RLS e permissões. |

## 4. Exclusões preservadas

Os cinco nomes abaixo estão ausentes do ledger observado e têm o marcador explícito de pausa no Git. Permanecem fora de qualquer replay ou execução desta janela; a ausência nominal no ledger não prova inexistência de efeitos históricos no catálogo.

| Arquivo | Estado |
|---|---|
| `20260827_230003_d2a_agent_runtime_private_context.sql` | Bloqueada |
| `20260828_045213_d2b2_consentimento_finalidade_evento.sql` | Bloqueada |
| `20260828_094914_d2b2b3_purpose_consent_governance_drafts.sql` | Bloqueada |
| `20260909_004005_consent_evidence_store_lab.sql` | Bloqueada |
| `20260910_142830_add_e4b_consent_persistence.sql` | Bloqueada |

## 5. Aceite de auditoria e compatibilidade

Cada grupo tem um registro curto de revisão (IDs, SHA de A/T, ambiente, data, evidências, resultado, limites e pendências), referenciado nas provas já exigidas pelas tarefas 4.1–4.6. Não criar gates paralelos. O resultado estático só demonstra a composição do candidato; os demais critérios abaixo estão **pendentes** para T final.

- **Integridade:** provar a seleção nominal, os 44 modos tx e oito NT, a ausência das cinco bloqueadas, a continuidade dos contratos de dados e as dependências e pré-condições específicas da matriz. Confirmar o estado real das extensões, vínculos, dados e privilégios aplicáveis somente em leitura autorizada; nenhuma contagem de dados foi realizada nesta preparação.
- **Prova sintética:** aproveitar os testes existentes de domínio, isolamento e transição. Ensaiar no PG17 descartável, com dados fictícios e configuração prevista no runbook; manter a ordem lexical, o aplicador e os limites vigentes. Registrar resultados por migration e grupo, conferir o ledger nominal final, a validade dos índices concorrentes, integridade e catálogo. A regra D9 é tempo individual de até 60 s. O tempo total é informativo. Conferir o contrato de espera e a role aplicadora equivalente no ensaio, sem alterações no ambiente real.
- **Compatibilidade:** mudanças em objetos compartilhados com o legado (pessoas, usuários, recibos, solicitações, conversas, mensagens, uso de IA e alertas) exigem verificação; criação de objeto novo não basta para garantir compatibilidade. O verificador do release normal tem restrições sobre mudanças em objetos existentes, incluindo a migration 52; permanece a primeira virada prevista, sem tentar contorná-lo. Revisar contrato API/painel no SHA exato de A, inclusive alertas com pessoa opcional, e manter separada a prova de publicação e smoke autorizados. Nunca considerar o legado compatível com um schema parcial por inferência.
- **Revisão independente:** Sarah deve registrar GO vinculado ao candidato final para a revisão prevista na 4.5, incluindo autenticação, RLS, permissões e caminho de aplicação. O aceite por grupo e o CI documental não substituem essa revisão.

## 6. Recuperação e condições para a janela

No laboratório, registrar a falha e repetir o ensaio completo sob as condições previstas após resolução revisada; não aproveitar estado parcial como prova de êxito. As duas primeiras migrations não têm rollback comentado segundo a auditoria estática; os comentários dos demais arquivos tampouco autorizam reversão em produção. Em falha concorrente, estado incerto de DDL ou divergência de ledger/catálogo, interromper e usar o diagnóstico e a decisão previstos no runbook, sem retry ou rollback improvisados.

Em produção, preservar o ponto de não retorno definido pelo marcador de DDL, e não pela primeira migration que retornar sucesso. Antes do marcador, eventual retomada do legado depende do estado e do procedimento vigente. Depois dele, manter a contenção e submeter correção adiante ou restauração do backup fechado da janela a decisão própria, com avaliação das escritas posteriores. Nenhum grupo de revisão autoriza retorno parcial ao legado, mudança em gates ou publicação independente.

**Bloqueio atual:** a causa de `containment-partial` em J4 continua não comprovada. J4 precisa de correção e teste de regressão, T final integrado e revisado, e dry-run completo aprovado e limpo na VPS dentro do escopo autorizado pelo dono. Respeitar a recusa de medição Nginx, sem contorno ou substituição por prova parcial. O dry-run, o aceite e a data dependem de Raniel; a janela é única, acompanhada por ele, com SIM por bloco e nova prova viva pós-SIM dentro dos cortes vigentes. Qualquer divergência ou falta de evidência impede avanço conforme o ROADMAP. Os gates devem permanecer fechados; a leitura de nomes de 25/11 não revalida o estado vivo da VPS, os efeitos da preparação ou as permissões.

Nesta PR documental não foram executados ensaios de migration, consultas remotas, comandos na VPS ou alterações de SQL, código e configuração. Os checks ordinários de CI e o workflow sintético existente podem verificar o checkout documental; seus resultados são vinculados ao SHA da PR, não à operação em produção. O ensaio integral e as demais provas do candidato final seguem pendentes.
