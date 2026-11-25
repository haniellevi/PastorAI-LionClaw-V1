# Preparação da auditoria das 52 migrations

25/11/2026. Plano operacional subordinado à [Fase 4 do ROADMAP](../../ROADMAP.md#fase-4--ferramenta-da-virada-apontada-para-a-main) e ao [runbook de produção](PRODUCTION-RUNBOOK.md). Organiza a revisão por assunto; não autoriza execução, não altera o seletor, o aplicador ou as proteções vigentes e não constitui outro roadmap.

## 1. Evidências e linha de base

| Fonte | O que está comprovado e limite |
|---|---|
| Git, `main` remota `f4bb30df1d8f67bb11702e1e41b1806828fc9561` (25/11) | Os 135 SQLs de topo são idênticos aos de A (`e1c63ed1dfaaacf26c21a3cc8d9c8c3151c0aae0`). Backend e frontend de A permanecem congelados. A atualização #705 de metadados de imagem integra a main, mas não comprova a correção de J4 ou a prontidão operacional de T. |
| [Reconciliação #701, §§1.2–1.4](PREPARACAO-JANELA-VIRADA-20261124.md#12-lista-exata-das-52-pendentes-esperadas) | Listas nominais e modos de execução; comparados com os arquivos desta base e os cabeçalhos de pausa. |
| Recibo de leitura autorizada, 25/11 às 12:37:41 UTC | Em `public.schema_migrations`: 78 nomes esperados, 78 observados, zero ausentes, extras ou duplicados. Origens: 63 `PROVA_OBJETO`, seis `BASELINE_V1_HISTORICO`, nove `MIGRATE_PY`. O ledger nativo tem 32 registros, apenas históricos. É uma observação pontual de nomes, não uma prova de schema, dados, permissões, VPS ou autorização de execução. |
| Auditoria local `task_403d48169df1` e incremental `task_ef857b2157aa`, 25/11 | Inventário e classificação estáticos, indícios de dependências e propostas de checagem. A leitura nominal posterior resolve a lacuna dos 78 nomes, mas não comprova as demais pré-condições. As propostas foram adaptadas à ordem lexical vigente. |
| Parecer estático Neon sobre 01 e 02, base `f4bb30df`, 25/11 | Identificou riscos funcionais e de integridade no contexto da baseline 78. Não houve execução, medição de candidatos ou teste sintético; os efeitos descritos são possíveis, não ocorrências comprovadas. |
| Complemento de 25/11: caracterização sintética de 01/02 e recibo de pré-contagem | 25 testes passaram em PG17.6 descartável com schema parcial; arquivos relevantes equivalentes a A, revisão independente pendente. A pré-contagem agregada autorizada às 12:52:26 UTC retornou zero candidatos em 01 e zero em ambas as verificações de 02. São provas distintas, com os limites registrados na seção 3. |
| Histórico da tentativa de 24/11, no ROADMAP | V9 em clone: 52 aplicadas, ledger 130 e maior migration de 0,372 s (total 105,988 s). A tentativa real parou em J4 antes do marcador de DDL; não prova a execução final, nem a validade de um novo ensaio. |

Partição nominal conferida nesta preparação: 135 arquivos de topo = 78 observados no ledger + 52 ativas pendentes (44 transacionais, oito concorrentes) + cinco bloqueadas. Portanto havia 57 nomes de topo fora do ledger no instante da leitura; apenas 52 integram o candidato. O SQL aninhado em `private_runtime/` e os SQLs auxiliares não entram nessa seleção. O catálogo histórico pausado não é um ledger. Nenhum arquivo de migration, ordem de aplicação ou registro do banco foi alterado.

## 1.1 Atualização de evidências por grupo

Atualização documental sobre a `main` `86eefd3d` e recibos existentes. A matriz nominal e a ordem lexical da seção 3 permanecem inalteradas. Os resultados abaixo são caracterizações sintéticas ou observações agregadas pontuais; não representam aceite de produção nem aprovação de T.

| Grupo | Resultado registrado | Limite e pendência |
|---|---|---|
| G1, M1–M4 | PRs test-only #707 e #708 integradas. Para M1/M2, 28 casos funcionais reportados em CI e pré-contagens agregadas pontuais 0/0/0. M4 registra 53 testes locais após ajuste, incluindo 8 casos afetados, e 15 checks. | M3 mantém a dívida de integridade do Item 29; esse identificador refere-se à M3, não à migration M29. Provas sintéticas não encerram compatibilidade nem aprovam a Fase 4. |
| G2, M6–M7 e M30 | Recibos existentes registram 37 casos para M6, 54 para M7 e 50 para M30. As contagens originais M5–M7 foram 20, 37 e 54, nessa ordem; recortes posteriores permanecem separados e não aditivos. M6 retornou zero reuniões na observação reportada. | PG descartável e contagens pontuais; não inferir estado atual. `btree_gist`, necessária a M30, foi reportada disponível, mas não instalada; a migration contém criação condicional. Revalidar no escopo apropriado. |
| G3, M8–M10 e M20 | #709 integrada; 8 casos focados M8–M10 reportados, além das suites existentes de UV. M20 foi reconciliada com testes Enviar/UV já contabilizados. | Não somar casos repetidos entre migrations; permanece registrada a lacuna de compatibilidade com legado para M20. |
| G4, M11–M14 e M21 | Recibo `task_9c1b3797c0a3` registra 281 casos existentes no conjunto. | Contagem coletiva sem atribuição individual por migration; replay integral do candidato final continua pendente. |
| G5, M15–M18 | Relatório funcional existente registra 342 testes no conjunto; leitura agregada pontual encontrou zero solicitações/referências inválidas. | Não atribuir o total a cada migration nem inferir estado posterior da leitura pontual. |
| G6, M23–M24 e M26 | Recibo M23–M24 registra 37 casos funcionais aprovados na cadeia sintética completa; suites de M26 também estão identificadas. | Não duplicar a contagem de 37 nem tratá-la como prova isolada das migrations ou do candidato final. `unaccent`, usada por M24, foi reportada disponível, mas não instalada; a migration prevê criação condicional. |
| G7A/G7B, M32–M41 e M45 | Relatórios M33–M39 e M44–M45 descrevem suites existentes de validade, semântica e planos. Leitura agregada de M41 encontrou zero duplicados. O recibo DB-only do Item 24 observou os oito índices da seleção válidos/prontos e nenhum inválido público. | Evidências estruturais e contagens pontuais não demonstram desempenho natural nem validade no candidato T final. Medição de performance permanece complementar, sem novo bloqueio. M45 depende da base M29. |
| G8A/G8B/G8C, M5, M19, M22, M25, M27–M29, M31, M42–M44 e M46–M51 | Suites existentes foram identificadas; pareceres estáticos M46–M51 concluídos. #710 adicionou cobertura test-only para M5. M29 é a base de retomada de M45. | A dívida do Item 29 pertence à M3. Provas sintéticas para memória privada não constituem aceite do replay final nem aprovam T. |
| G9, M52 | Relatório M52 registra 36/36 casos existentes aprovados em PG17.6 descartável: 26 unitários, 6 de regras PG e 4 de baixa; sem PR. | Prova sintética funcional, sem aplicação em produção ou aceite do candidato final. |

### Recibo DB-only e status geral

O recibo DB-only do Item 24 registra `test_zz_reconciled_baseline_accepts_pending_batch_with_team_migration` aprovado em PG17.6 descartável: baseline 78 para ledger sintético 130, com 52 ativas e cinco excluídas; os oito índices da seleção estavam válidos/prontos e nenhum índice público inválido foi observado. O recibo afirma equivalência de SQL e `migrate.py` com A (`e1c63ed1`) e a `main` (`86eefd3d`). É evidência de replay sintético, não de migrations aplicadas em produção nem de aprovação de T, 4.6, J4 ou dry-run.

O coordenador reporta nova leitura agregada pontual de `public.schema_migrations`: os mesmos 78 nomes, sem delta. Essa conferência não prova schema, dados ou prontidão operacional. PRs test-only #707 (`28567e2a`), #708 (`83e50f1b`), #709 (`86eefd3d`) e #710 (`e4ec2781`) foram integradas; os 15 checks reportados ficaram verdes. Para #709, avaliação independente e CI passaram; flags antigos não publicados e limites da caracterização foram registrados. Estes merges não alteram o estado bloqueado de T/J4 nem autorizam janela. Preservam-se os cinco SQLs pausados e a ordem lexical única. Os próximos passos de alto nível são concluir as provas agrupadas no candidato final e resolver as pendências de J4 e dry-run antes de qualquer decisão sobre janela.

### Atualização documental posterior, main `cd029ebc`

Desde a referência anterior `86eefd3d`, foram integradas #717–#719. A #717 acrescenta prova funcional sintética de compatibilidade legada para M20, em PG17.6 descartável, sem provar dados reais. As #718 e #719 caracterizam a integridade da exclusão cadastral M3 e a correlação do recibo, respectivamente; a F3 usa modelo fictício e não foi integrada. A decisão `e1081` adia a funcionalidade de exclusão/reset até a correção correspondente: o Item 29 fica encerrado como decisão, enquanto sua dívida de integridade continua antes de liberar o recurso. A política `e1071` preserva, para contas comuns, a política cadastral atual de exclusão de sessões; mantém a política cadastral atual para a trilha editorial; conserva o histórico dos pedidos privados, distinguindo-o do encerramento cadastral; e retém as sessões da identidade administrativa preservada até a expiração e o novo login, conforme aprovado. Não se declara a modelagem integrada nem o recurso liberado. Não se altera a partição de 52 migrations ativas e cinco pausadas nem a ordem lexical.

As #712–#716 registram a evolução: diagnóstico de recusas (#712), conferência local do layout (#713), dry-run local parcial (#714), fixação da identidade de A (#715) e classificação local de recibos de integridade (#716). O resultado continua `incomplete`, sem aprovação de J3–J6; não determina a causa de J4 nem constitui prova viva integral. A #718/#719 tampouco resolvem por si sós a dívida antes da liberação da funcionalidade. 4.6, T, J4 e dry-run integral continuam pendentes, sem janela liberada.

## 2. Grupos de revisão e critérios específicos

Os grupos abaixo são uma **sequência de revisão**, não lotes de aplicação. A matriz mantém a ordem lexical do aplicador e da ferramenta (uma migration por vez). Nos ensaios integrais, preservar essa ordem, inclusive quando duas linhas de um assunto estiverem separadas por outro grupo. Uma dependência indicada é um vínculo identificado na auditoria estática, a confirmar conforme o catálogo e o comportamento; não é prova de independência dos demais objetos.

| Grupo | IDs da matriz | Dependências e foco de aceite (pendentes de prova) |
|---|---|---|
| G1. Ajustes históricos | 01–04 | Revisar os dois ajustes de dados de pessoas em conjunto, incluindo o parecer específico abaixo, conferir efeito esperado dos registros e proteção dos administradores; Jev permanece inativo conforme seus gates. |
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

### Revisão estática específica dos itens 01 e 02 (G1)

O parecer Neon de 25/11 sobre os dois arquivos imutáveis identificou os seguintes riscos de integridade funcional, a validar no contexto completo da baseline 78:

| Escopo | Risco possível identificado | Aceite pendente em dados fictícios |
|---|---|---|
| 01 e 02 | Alteração do tipo de pessoa arquivada. | Preservação do histórico de pessoas arquivadas. |
| 01 | Promoção a membro a partir de vínculo residual em célula inativa ou de pessoa sem interesse; elegibilidade inconsistente. | Classificação coerente com atividade, vínculo e elegibilidade. |
| 02 | Reclassificação indevida diante de telefone ambíguo ou vinculado à liderança, inclusive referências antigas de conexão. | Preservação da classificação de líderes e de pessoas que não representam o número oficial; tratamento coerente de ambiguidades. |
| 01 e 02, em conjunto | Mudanças de tipo podem alterar etapa/subetapa via regras de pipeline e produzir efeitos na contagem faturável e em mudanças de plano; a redução posterior da contagem pode não desfazer um efeito intermediário. | Conferir integridade do pipeline, contagens e operações de billing antes/depois, inclusive no limite de um plano, sem efeitos externos. |

A revisão estática confirmou a necessidade de testar as duas migrations com suas dependências de domínio e efeitos combinados de pipeline/billing. Evidências complementares de 25/11:

- **Caracterização isolada:** relatório `igreja12-july-audit-f31ef6`, 25 testes aprovados em 3,62 s no PG17.6 descartável. O schema sintético parcial contém dependências de negócio relevantes, mas não reproduz integralmente a baseline 78. O ensaio caracteriza o comportamento existente, inclusive casos ambíguos; aprovação dos testes não comprova correção de regras de negócio, nem estado de produção. A revisão independente e o aceite de G1 com as provas restantes seguem pendentes.
- **Pré-contagem autorizada em produção:** 25/11 às 12:52:26 UTC, leitura agregada sem retorno de dados pessoais: 01 = 0 candidatos; 02 = 0 na pré-checagem ampla e 0 na conferência exata. Se esses conjuntos continuarem vazios no momento da execução, os efeitos potenciais sobre pessoas e billing das duas migrations não ocorrerão por atualização de registros. A observação não garante paridade de catálogo, direitos do aplicador nem estado futuro; revalidar antes da decisão autorizada. As duas migrations não foram executadas nem registradas, e as 52 continuam pendentes no ledger observado.

Nenhuma dessas provas aprova o grupo inteiro ou autoriza alteração de SQL, ordem ou política de execução. Eventual divergência deve ser registrada e submetida à decisão no processo vigente, antes de aceitar G1.

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
