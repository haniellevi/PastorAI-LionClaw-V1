---
id: M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY
status: em_execucao
opened_at: 2026-09-14T21:33:30-03:00
authorized_by: Raniel
environment: local_com_preflight_dev_somente_leitura_por_operador_humano
---

# M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY

```yaml
id: M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY
objetivo: entregar um pacote único, executável e revisado para aplicação e rollback em DEV do catálogo público de 77 migrations, sem aplicar migration nesta missão
preflight:
  repositorio: github.com/haniellevi/PastorAI-LionClaw-V1, clone local
  branch: docs/migration-head77-dev-apply-readiness-readonly-20260915
  sha_efetivo: 5e2082e94db2b6af6b34cfe351d81cf54b85aa76
  worktree_limpo: true
  ambiente: local; DEV somente leitura executada pelo Raniel via Shell; PROD fora
  horario: 2026-09-14T21:33:30-03:00
  runbook_lido: docs/ops/MISSION-CONTROL.md; backend/migrations/README.md, executor v2 e estado operacional; docs/decisions/2026-09-03-migration-environment-attestation-executor-v2.md; docs/decisions/2026-09-10-catalog-bound-execution-v3-foundation.md; docs/ops/PRODUCTION-RUNBOOK.md, release imutável e travas
  grafo: indisponível por decisão de segurança; code-review-graph permanece desabilitado
worktree: .worktrees/migration-head77-dev-apply-readiness-readonly-20260915
branch: docs/migration-head77-dev-apply-readiness-readonly-20260915
sha_base: 5e2082e94db2b6af6b34cfe351d81cf54b85aa76
especialistas:
  - FORJA, gpt-5.6-terra max, redator técnico no worktree da missão
  - LENTE, gpt-5.6-terra max, exatamente uma rodada somente leitura em worktree própria do candidato congelado
arquivos_permitidos:
  - docs/missions/M-MIGRATION-HEAD77-DEV-APPLY-READINESS-READONLY.md
  - docs/ops/migration-head77-dev-apply-readiness/**
criterios_de_aceite:
  - registrar SHA do release e identidade da imagem do backend hoje na VPS somente a partir de saída sanitizada produzida pelo Raniel no Shell
  - capturar em DEV, por transação read-only executada pelo Raniel, versão PostgreSQL, identidade sanitizada, ledgers público e nativo, existência e metadados estruturais das relações E4b, sem selecionar dados de tenant
  - reconciliar a captura DEV com o catálogo público de 77 migrations, o head autenticado e a migration 20260910_142830, sem inferir aplicação pela presença no Git
  - entregar APPLICATION-PACKET.md com pré-condições fechadas, sequência exata, critérios de aborto, verificações pós-aplicação e limites de autorização
  - entregar ROLLBACK-PACKET.md com compensação forward-only ou reversão transacional comprovável, sem inventar downgrade destrutivo
  - nenhum comando da missão aplica migration, escreve no banco, altera VPS, lê segredo, abre PROD, envia mensagem ou muda flags
  - executar testes source-only focais, guarda de privacidade e git diff --check no candidato final
  - realizar exatamente uma rodada de revisão independente da LENTE no patch congelado
riscos_de_tenant:
  - consulta de dado de igreja; impedida por inventário exclusivo de catálogo, ledgers e metadados de schema sem payload de domínio
  - aplicação futura sob principal ou tenant incorreto; pacote deve falhar antes do SQL e exigir alvo DEV, identidade, PostgreSQL 17, TLS e bind ao SHA exato
  - divergência entre public.schema_migrations e supabase_migrations.schema_migrations; qualquer divergência não reconciliada bloqueia a aplicação
  - RLS ou ACL incompleta nas seis relações E4b; verificações pré e pós devem exigir igreja_id, RLS habilitada e forçada, policies fortes e revokes explícitos
plano_de_teste:
  - python source-only do verificador do catálogo e do executor V3, sem descritor de banco
  - pytest focal de catálogo, executor v2/V3 e migration E4b, sem conexão externa
  - pytest backend/tests/test_source_contact_privacy.py
  - git diff --check
plano_de_rollback:
  - nesta missão, descartar somente o patch local e a worktree, pois não há mutação de ambiente
  - para a aplicação futura, usar exclusivamente a compensação documentada no pacote e abortar antes do commit diante de qualquer pré-condição falsa
fora_de_escopo:
  - aplicar migration, executar apply_migrations.py, bootstrap, hardening, cutover ou DML
  - PROD, Supabase PROD, deploy, restart, firewall, certificado, runtime, writer, caller, webhook ou ativação
  - ler ou imprimir env, DSN, token, chave, segredo, PII ou dado pastoral
  - push, PR, merge ou commit
proximo_gate: Raniel decidir manter o NO_GO ou autorizar nominalmente uma missão própria de remediação do histórico DEV e do executor catalog-bound; este pacote não admite aplicação DEV direta
encerramento:
  status_final: pendente
  sha_final: patch local pendente
  branch_final: docs/migration-head77-dev-apply-readiness-readonly-20260915
  pr: nenhum
  mutacoes: nenhuma fora de documentação local; pendente de confirmação final
  evidencias: pendente
  riscos_residuais: pendente
  registro: docs/ops/migration-head77-dev-apply-readiness/FINAL-REPORT.md
```

## Ordem nominal

Raniel autorizou esta missão em 14/09/2026. A consulta da VPS e de DEV é feita
pelo próprio Raniel no Shell, com saída sanitizada. Agentes não abrem SSH,
Supabase, portal autenticado ou sessão PROD. O escopo não autoriza aplicação,
deploy, restart, alteração de configuração ou abertura de qualquer gate.
