# Revisão parcial, testes legados S2/S2b

## Escopo e evidência

- Patch inicialmente revisto: `S2B-BACKEND-TESTS.patch`, SHA-256 `04db6f8f3e28fb70a3b3b5d8543baff60b14537ec51993fce4e4a8c7afdd33dd`.
- Delta corretivo: `S2B-BACKEND-RLS-DELTA.patch`, SHA-256 `599bd582667e1523490def4fabf21003e1331401ab9a50c424072597b52ce7bd`.
- Arquivo RLS após o delta: SHA-256 `66fddbac165338b6f3201f0d79f3661dfaf57003b90a8fec5b4b5ad8e9d3ec5d`.
- Revisados apenas `backend/tests/test_agent_public_profile.py` e `backend/tests/test_agent_public_profile_rls.py`. Não executei PostgreSQL.

## P1 fechado no delta

O patch inicial aplicava somente a migration S2 de `agent_configs`, mas esperava `PUT /igreja/cadastro` com sucesso. A fixture não tinha a policy `igrejas_self_update` nem o grant de UPDATE das colunas canônicas, portanto essa expectativa não podia provar S2b.

O delta removeu os dois PUTs canônicos, semeia os fatos somente como owner da fixture, preserva o teste da migration S2 e verifica:

- GET canônico isolado por tenant;
- ausência de fallback do JSON legado;
- filtragem de células não publicadas ou inativas;
- ausência de endereço residencial, link privado e dados do outro tenant;
- PUT legado com 409 e sem eco do payload;
- catálogo/RLS/ACL de `agent_configs` preservado.

A própria docstring agora delimita que este teste não atesta migration, grants ou PUT de S2b. Isso elimina a falsa prova.

## Parecer

**APTO apenas para este delta de testes legados.** Não há outro P1/P2 nos dois arquivos revisados.

O candidato S2b continua dependente de prova PG separada, no SHA congelado da migration S2b, para grant por coluna e policy de `Igreja`, PUT canônico próprio e cross-tenant. Este parecer não aprova o backend, migration, runtime ou oferta de secretaria.
