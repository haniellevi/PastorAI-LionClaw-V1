# Retomada local da refatoração

## Transporte simulado e entrada de trabalho

Worktree Codex própria, baseada em 11b34410, preserva todas as correções do executor anterior sem alterar suas worktrees. #463, #464 e #461 integrados; quatro checks pós-merge aprovados. Registro T02/T03/T04 atualizado com essas evidências.

F2a: 67 testes de transporte mais 14 do guard de privacidade aprovados (81); 4 testes de transporte/handler e 15 de visitante aprovados em PostgreSQL 17 descartável (19). Primeira suíte completa identificou um falso positivo: o guard de contatos percorria .venv-runtime/site-packages. Esse diretório é agora excluído como dependência; teste comprova que código do projeto continua protegido. Regressão completa será repetida com a T06.

Nenhum Redis/RLS/turno completo é alegado por F2a. Sem push, merge, deploy, acesso a PROD ou ativação de provedores reais nesta retomada.

## T06: validação de visitante no domínio

Regra pura e VisitorNameError em app/domain/visitor.py. Propostas preservam o adaptador ProposalContractError; serviço ministerial e parser passam a depender do domínio. Sem mudança de autorização, schema, comportamento humano ou contratos HTTP.

149 testes focados, 15 de visitante em PostgreSQL 17 e suíte backend sem RLS com 6431 passed, 866 deselected (55,59 s). Isso também revalida T05 após a correção do guard. Nenhum skip/falha registrado nessa seleção. Os 866 testes de integração não foram executados pela suíte offline.
