# Retomada local da refatoração

## Transporte simulado e entrada de trabalho

Worktree Codex própria, baseada em 11b34410, preserva todas as correções do executor anterior sem alterar suas worktrees. #463, #464 e #461 integrados; quatro checks pós-merge aprovados. Registro T02/T03/T04 atualizado com essas evidências.

F2a: 67 testes de transporte mais 14 do guard de privacidade aprovados (81); 4 testes de transporte/handler e 15 de visitante aprovados em PostgreSQL 17 descartável (19). Primeira suíte completa identificou um falso positivo: o guard de contatos percorria .venv-runtime/site-packages. Esse diretório é agora excluído como dependência; teste comprova que código do projeto continua protegido. Regressão completa será repetida com a T06.

Nenhum Redis/RLS/turno completo é alegado por F2a. Sem push, merge, deploy, acesso a PROD ou ativação de provedores reais nesta retomada.

## T06: validação de visitante no domínio

Regra pura e VisitorNameError em app/domain/visitor.py. Propostas preservam o adaptador ProposalContractError; serviço ministerial e parser passam a depender do domínio. Sem mudança de autorização, schema, comportamento humano ou contratos HTTP.

149 testes focados, 15 de visitante em PostgreSQL 17 e suíte backend sem RLS com 6431 passed, 866 deselected (55,59 s). Isso também revalida T05 após a correção do guard. Nenhum skip/falha registrado nessa seleção. Os 866 testes de integração não foram executados pela suíte offline.

## T07: fila, migrations e policies reais

7 passed, 0 skipped, 25,994 s. Redis com enqueue/claim/ACK/lease, QueueWorker.run em thread e banco reconstruído pelas 82 migrations ativas. Authenticated sem BYPASSRLS; dois tenants exercem ação positiva, leituras e escrita cruzadas recusadas. API verifica JWT e papel reais. Consentimento, opt-out, replay, membership revogado e falha antes do commit com rollback/retry exercitados. Saída HTTP confinada ao simulador ASGI; banco/Redis loopback e recursos por teste.

Critério corrigido para o contrato existente: indicar visitante próprio não exige papel de gestão, mas vínculo e membership. O teste de ausência de papel refere-se à API de gestão. Nenhuma autorização do produto alterada para adequar o teste ao texto. Esta prova não demonstra boot/rede entre processos de F3 nem CI remoto.

## T12: leitura pública da resposta persistida

AgentReplyIntent, ReplyReadContext, consulta com fence e projeção legada em agent_reply_reader. Identidade/lock usam o mesmo algoritmo puro compartilhado em provider_identity. O turno privilegiado compõe sessão e usa leitura pública sem importar o worker para essa leitura. Áudio usa a projeção pública; worker mantém aliases internos de compatibilidade e todas as mutações existentes. Nenhum ciclo inteiro é declarado eliminado.

398 testes focados, 27 testes PG (44,143 s, nenhum skip), 6431 testes backend sem RLS (53,00 s). Prova PG cobre ausência, chave histórica com sufixo, estado NULL, tenants positivos, recusa de contexto divergente e fence observado por outra transação. F2b repassou após extração. Baseline backend antes: 6431 passed; depois: 6431 passed. CI, merge e publicação permanecem pendentes.

## S3: Next patch e ferramentas alinhadas

Next 15.5.27 e eslint-config-next 15.5.27, sem salto de major. Alterações do lock limitadas aos 12 pacotes Next/ESLint/SWC correspondentes. Node 24.19.0: audit de produção limpo, lint, tsc, 1165 testes, build e smoke HTTP de headers aprovados. E2E posterior aprovado; CI remoto pendente.

Fontes: [advisory SSG/ISR](https://github.com/advisories/GHSA-4jqv-mc3x-m676), [advisory cache](https://github.com/advisories/GHSA-mcj8-r9mp-w47p) e documentação Next via Context7, consultados em 09/10. Auditoria do grafo completo continua separada em S4.

## S4: grafo completo do frontend

Auditoria inicial: 8 pacotes altos e 3 moderados. Após S3 e atualização compatível de js-yaml 4.3.2, undici 7.30.0, brace-expansion 1.1.21/5.0.12 e Vitest 4.1.11: zero moderados e cinco pacotes altos ligados ao único [advisory braces sem patch](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm). São braces, micromatch, fast-glob, eslint-config-next e @next/eslint-plugin-next, no grafo de desenvolvimento. Audit de produção sem vulnerabilidades. Não executado audit fix --force nem downgrade para Next 14.

A atualização do Vitest também atualiza os transitivos permitidos de Vite/Rolldown/LightningCSS e ferramentas relacionadas; não é descrita como quatro alterações isoladas. Lint, tsc, 1165 testes, build E2E e 69 E2E Chromium passaram. Build de produção e smoke final aprovados. O aviso residual permanece visível e exige correção upstream ou uma substituição independente justificada.


## T09/T10: preparação parcial de DEV e promoção

Imagem production contém somente scripts/migrate.py; development acrescenta devtools e as entradas dev_online/dev_local. Allowlist de build exclui configurações privadas e scripts administrativos. Identidade da imagem vinculada ao SHA por ENV e label; rebuild final será registrado fora do Git para evitar referência circular.

Seed DEV valida projeto nominal, URL Supabase, host/usuário do banco, TLS verify-full, ambiente development e gates fechados antes do SQL. Idempotente sobre duas igrejas sintéticas, recusa dataset inesperado e não consulta Clerk nem apaga dados. Identificadores de seed não provam ausência de dados reais: a verificação autorizada do recurso continua necessária. Entrada CLI local mantém seu guard loopback anterior.

DevCoordinator usa flock compartilhado por deploy/reset/reserva/aceite. Impede versão antiga e manifesto frontend/backend divergente; preserva recibos concluídos e invalida reservas expiradas/resetadas. Persiste recovery_required antes do primeiro efeito; SIGKILL e falha do callback exigem prova separada de recuperação. 24 testes de controles DEV aprovados (12 alvo, 12 coordenação), sem skips. O primeiro teste de SIGKILL travou no mutex de espera da fixture; corrigido para signal.pause e reexecutado com sucesso, sem mudar o contrato do produto.

Compatibilidade é provada por catálogo nominal reconstruído, ledger exato, roles/grants/RLS/policies, funções, índices, triggers, defaults e tipos. PG17 com 82 migrations reais comprova alteração aditiva/backfill, recusa de drift/incompatibilidade e rollback de SQL falho. Seed e schema: 2 passed, zero skipped, 3,63 s. O checker legado permanece em uso; este módulo ainda precisa ser ligado ao executor físico. Não há workflow DEV, contenção física de consumidores, promoção frontend por alvo nem recuperação completa ensaiada.

T08 ainda não foi respondida: recursos, região, teto e executor são decisões do proprietário. T09/T10 permanecem parciais e T11 não foi executada. Backlogs condicionados B1-B6 não foram promovidos a escopo automático. Nenhum acesso de infraestrutura ou efeito externo nesta retomada.

## Validação consolidada local

6443 testes backend offline aprovados, 876 integrações deselected (51,61 s). 874 integrações RLS/PG/Redis aprovadas, zero skips (394,307 s), mais os 2 novos testes PG aprovados separadamente. Não houve uma única execução de 876 integrações nesta fotografia. Deploy/monitor: 123 passed, 3 skipped, 59 subtests passed; manutenção Python e monitor Node aprovados. Pip check e verificação dos manifests aprovados; pip-audit nos dois locks sem vulnerabilidades conhecidas. Frontend Node 24.19.0: 1165 testes, 69 E2E Chromium, lint, tipos, build de produção e headers aprovados. Audit produção limpo; grafo completo conserva o advisory braces descrito acima.

A main integrada 52286af7 já é ancestral desta branch, recebida pela worktree T05 antes da retomada. Os resultados são locais e não substituem os quatro checks obrigatórios no futuro PR. Alterações foram separadas em commits; integração deve preservar a ordem das fatias, com S3/S4 como manutenção independente. Não realizado push, merge remoto, publicação ou limpeza de worktrees alheias.


Revisão final da compatibilidade (d82d0d7c): ownership, ACL de coluna e opções de relação também entram no catálogo. Coluna obrigatória sem default, nova constraint ou índice único em tabela anterior são recusados mesmo depois de backfill. Coluna com default e índice comum permitem INSERT pela versão anterior. Prova PG reexecutada: 1 passed, zero skipped, 2,24 s. Inventário SQL isolado exigido pelo CI: 11 testes unittest aprovados, sem rede nem acesso ao banco da aplicação.
