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

Next 15.5.27 e eslint-config-next 15.5.27, sem salto de major. Alterações do lock limitadas aos 12 pacotes Next/ESLint/SWC correspondentes. Node 24.19.0: audit de produção limpo, lint, tsc, 1165 testes, build e smoke HTTP de headers aprovados. E2E e CI remoto pendentes.

Fontes: [advisory SSG/ISR](https://github.com/advisories/GHSA-4jqv-mc3x-m676), [advisory cache](https://github.com/advisories/GHSA-mcj8-r9mp-w47p) e documentação Next via Context7, consultados em 09/10. Auditoria do grafo completo continua separada em S4.
