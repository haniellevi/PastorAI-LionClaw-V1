# Relatório curto: RLS shard 3

Causa raiz: `test_auth_session_revocation_pg.py` importava `migrated_database` do módulo UV, mas sua fixture `rls_database_url` usava `RLS_TEST_DATABASE_URL`. As migrations completas eram aplicadas em `rls_disposable`, tornando `pessoas.telefone` obrigatório e quebrando seeds posteriores.

Correção: logout agora usa e valida `UV_TURMAS_DATABASE_URL` em `uv_turmas_test`. A fixture operacional semeia a sessão sintética ativa do JTI usado pelo `FakeClerk`, mantendo as verificações de papel e status.

Testes: shard 3, 28 arquivos, 631 passaram, 0 skips, 0 falhas e 0 erros. Sequência focalizada: 67 passaram, 0 skips. Runtime local descartável: Python 3.13.14, Pytest 9.1.0 e PostgreSQL 17.6. Pytest registrou 4 warnings.

SHA da correção: `fa05aec907e74c45311ac69bff4dbde431065d06`
