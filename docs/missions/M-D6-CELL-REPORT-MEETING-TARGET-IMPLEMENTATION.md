# M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION

Estado: CONCLUÍDA LOCAL/OFFLINE em 2026-09-13T23:40:34.788324-03:00. Ordem nominal de Raniel de 13/09/2026 atendida. Ficha de abertura preservada abaixo.

## Ficha MISSION-CONTROL

Objetivo: implementar somente o adaptador resolvedor -> alvo opaco e testes offline, conforme ficha executável P1 do FINAL-REPORT D6, sem integração operacional.
Preflight: workspace IGREJA 12 - MANUAL; terminal Orquestrador; repo haniellevi/PastorAI-LionClaw-V1, clone local; horário 2026-09-13T22:57:58.301022-03:00; ambiente local/offline; grafo indisponível/desabilitado.
Worktree: /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-meeting-target-implementation-20260913
Branch: feat/d6-cell-report-meeting-target-offline-20260913
SHA base e HEAD inicial: 7a7afa3d08927f3f5b2ed116638aed3131dde88b
Estado inicial: limpo antes desta ficha; nenhum hook Git ativo; .codex/.agents ausentes. Nenhum novo andar visual.
Controle: /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/maestri-astra-workspace-plan, HEAD ea40c436e7a06f9d58fdf14c337fb3cc36e91ad1, mudanças anteriores preservadas.
Runbooks: AGENTS.md, docs/ai/AI-BOOTSTRAP.md, docs/ai/PRD-COVERAGE.md e docs/WIKI-IGREJA12.md da base; MISSION-CONTROL.md, MAESTRI-PERSISTENCE-MANIFEST.md e MAESTRI-ASTRA-WORKSPACE-PLAN.md do pacote de controle.
Fontes D6 somente leitura (hashes em OPENING.json do controle):
- /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-operational-contract-20260913/docs/ops/d6-cell-report-contract/FINAL-REPORT.md SHA256 5898d6ce260fcc9fb689f7466d1b09b5bac43244f285c7c21389cad93f72b6bd
- /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-operational-contract-20260913/docs/decisions/2026-09-13-d6-cell-report-operational-contract.md SHA256 a6879c11b808b74558afeb1584f8beaaa2e2c16874e692e235d1e93a74baeacb
- /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-operational-contract-20260913/docs/ops/d6-cell-report-contract/SCENARIO-MATRIX.md SHA256 006e7f9b23a063895fa3bd9902bfb4047bcbe099fc882ccf832f2442c8f63264

## Especialistas e responsabilidade

FORJA: IMPLEMENTADOR, gpt-5.6-terra max, sessão com -C nesta worktree; único escritor durante implementação. Modelo efetivo deve ser confirmado pelo banner.
LENTE: gpt-5.6-terra max, exatamente UMA rodada read-only em sessão separada, worktree própria do candidato exato identificada por base + SHA256 do patch; preparar após congelar candidato.
Orquestrador: único operador Maestri, notas e integração de evidência; não escreve concorrentemente ao especialista. Reporta preparação e encerramento via maestri ask OpenCode.

## Allowlist de escrita

- backend/app/services/cell_report_meeting_target_adapter.py (novo)
- backend/tests/test_cell_report_meeting_target_adapter.py (novo)
- docs/missions/M-D6-CELL-REPORT-MEETING-TARGET-IMPLEMENTATION.md
- docs/ops/d6-meeting-target-implementation/ (recibos sanitizados, EXECUTION-RECORD.md, FINAL-REPORT.md)
- docs/sprints/2026-09-13-d6-cell-report-meeting-target-implementation.md

Coordenador, resolvedor, guardas, manifesto e flags são somente leitura. O candidato documental D6 permanece na worktree anterior, sem alterações, stage ou commit. Nenhum commit nesta missão; candidato identificado por base + hash do patch.

## Critérios fechados de aceite

A1. Interface única resolve_cell_report_meeting_target(db, *, current_user, turn_identity, clock) -> CellReportMeetingTarget. CurrentUser e AgentTurnIdentity confiáveis, clock obrigatório chamado uma vez; IDs canônicos, sem parâmetros de ator/igreja/reunião/finalidade não confiáveis.
A2. Mesmo tenant de identidade/CurrentUser e require_tenant_scope antes de leituras. Reusar obrigatoriamente _load_bound_inbound com locks, consulta limitada e validação integral de Message/Conversation; nenhuma cópia de SELECT/atalho/validador inbound paralelo.
A3. Transação raiz externa já ativa; guardar handles root/nested retornados. Derivar ator humano via _load_actor_pessoa_id e igualar ao inbound antes e após resolução. Resolver existente com mesmo CurrentUser e now=clock(). Revalidar RLS e identidade exata dos handles antes do mint. Sem abrir/fechar transação.
A4. Somente CANDIDATE emite alvo pela função EXISTENTE _mint_cell_report_meeting_target. Essa emissão de alvo é parte autorizada; mint/permit POSITIVO DE CONSENTIMENTO é proibido. NONE, AMBIGUOUS, overflow, dado/escopo inválido, transação/RLS/ator trocados falham fechado com erro sanitizado, sem alvo.
A5. Testes cobrem IDs/tipos inválidos, tenant/RLS inicial divergente, transação ausente/trocada root/nested, inbound ausente/duplicado/adulterado, ator divergente antes/depois, NONE/AMBIGUOUS/overflow, relógio fixo com igualdade inelegível e estritamente posterior elegível, alvo válido só mesmo identity/contexto e adulteração inbound/ator/reunião rejeitada. Doubles estritamente de leitura rejeitam escrita, flush, commit e rollback; zero staging/proposta/confirmação/outbox/efeito de domínio. UUIDs sintéticos com letras hex, sem PII.
A6. Consentimento tarefas_operacionais permanece EXTERNO e deny-all; C09/C10 BLOCKED_BY_E4B. Sem writer falso, mint/permit de consentimento positivo, Pessoa.consentimento ou bypass purpose_consent. Não executar suite inteira do coordenador.
A7. Runner offline imutável: testes novos + resolvedor existente, zero falhas/erros/skips/guard_denials; guarda de privacidade pertinente também passa. Limites: doubles não provam RLS/locks/concorrência PostgreSQL reais nem consentimento/integração WhatsApp.
A8. Uma rodada LENTE sobre candidato exato; achados preservados com arquivo:linha e correções objetivamente verificadas sem segunda rodada. FINAL-REPORT aponta M-D6-CELL-REPORT-COORDINATOR-INTEGRATION-OFFLINE como proposta de próximo passo de integração, sem novo contrato e sem executá-la.

## Riscos de tenant

Alvo de outra igreja/pessoa/inbound: prevenir por identidade canônica, RLS, caminho humano, inbound bloqueado e selo existente. Troca de tenant/transação/ator durante resolução deve recusar antes do mint. Nenhum teste cria autorização operacional nem prova infraestrutura viva.

## Plano de teste (comando exato)

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /home/raniel-linux/workspace/PastorAi-1.0/backend/.venv-runtime/bin/python -I -B /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/maestri-astra-workspace-plan/docs/ops/pr364-rebase/run_offline_pytest.py /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-meeting-target-implementation-20260913 /home/raniel-linux/workspace/PastorAi-1.0/.worktrees/d6-cell-report-meeting-target-implementation-20260913/docs/ops/d6-meeting-target-implementation/pytest tests/test_cell_report_meeting_target_adapter.py tests/test_cell_report_meeting_resolver.py tests/test_source_contact_privacy.py
```

Python pinado 3.13.14. Runner SHA256 0131eb6d64607da7ff4ffc6745223e0590625b280319fd57f3d73af7cb74cbfd, não editar. Ambiente vazio; rede/DB/arquivos protegidos bloqueados. Nenhum install, credencial, banco sequer local ou suite permissiva. Recibos JSON/XML devem preservar comando, horário, ambiente, saída e limites. Se um teste falhar, corrigir somente allowlist e repetir o pertinente.

## Fora de escopo

Caller/runtime/worker/webhook, banco local/DEV/PROD, credenciais, E4b, LLM/rede, envio, ativação, publicação, push/PR/merge, incidente PROD #392; migration, propósito positivo, novos contratos, mudança de manifesto/flags/guardas. PR362 continua áudio adiado e não é alterado. Ferramentas Maestri locais do Orquestrador são apenas coordenação nominalmente autorizada.

## Rollback

Reverter somente o patch local desta missão após conferir hashes; preservar recibos, notas, worktrees, histórico e mudanças anteriores. Sem reset --hard, clean, remoção de worktree, refs remotas ou banco. Não executar rollback automaticamente.

## Único próximo gate humano

Raniel revisar o resultado e autorizar nominalmente o recorte da missão M-D6-CELL-REPORT-COORDINATOR-INTEGRATION-OFFLINE. Nenhum gate intermediário para execução/revisão desta missão já autorizada. Esse próximo passo não concede consentimento, publicação, runtime, envio ou E4b.

Encerramento: preencher ao concluir, com base/hash, testes, parecer único, limitações, mutações locais e registro de sprint. PR nenhum.

## Encerramento MISSION-CONTROL

status_final: concluída local/offline, P1 corrigido e verificado objetivamente
sha_final: 7a7afa3d08927f3f5b2ed116638aed3131dde88b (base/último commit; nenhum commit da missão)
branch_final: feat/d6-cell-report-meeting-target-offline-20260913
pr: nenhum
horario: 2026-09-13T23:40:34.788324-03:00
mutacoes: dois arquivos novos de produto, ficha/recibos/relatório/sprint locais, worktrees próprias e notas canvas; duas sessões locais FORJA/LENTE; reportes OpenCode autorizados; nenhuma mutação operacional ou remota
evidencias: docs/ops/d6-meeting-target-implementation/FINAL-REPORT.md, pytest.json/xml, P1-VERIFIED.json, LENTE-REVIEW.md, CLOSURE-RECEIPT.json; inventário/patch final no controle
revisao: exatamente uma rodada LENTE, NAO APTO no original b972ddf7…, somente P1 autoflush; corrigido pela FORJA e verificado pelo Orquestrador; sem novo APTO LENTE
testes: 62/62; falhas 0, erros 0, skips 0, guard_denials 0; 32 adapter, 17 resolvedor, 13 privacidade
riscos_residuais: doubles não provam PostgreSQL/RLS/locks/concorrência reais; tarefas_operacionais externo deny-all, C09/C10 BLOCKED_BY_E4B; sem integração ou efeitos externos
registro: docs/sprints/2026-09-13-d6-cell-report-meeting-target-implementation.md
proximo_gate: Raniel revisar resultado e autorizar M-D6-CELL-REPORT-COORDINATOR-INTEGRATION-OFFLINE no recorte proposto, sem novo contrato
