# Relatório curto: logout no servidor

PR #568, branch `feat/logout-servidor`. Base desta correção:
`cbd57837550210e8b425bfd04197ad93ea277a47`.

Causa confirmada: identidades sintéticas com `jti`, mas sem registro em
`auth_sessions`. Reproduzidas cinco falhas 401: memória privada (`fresh` e
`upgrade`), dois testes de inbox e um EVT-7 encontrado com `rg`. A migration
`20261023_120000` já integra a cadeia das fixtures dos dois arquivos apontados;
o EVT-7 cria as tabelas pelo metadata ORM.

Arquivos alterados em `backend/tests/`:

- `conftest.py`: `FakeClerk` aceita `jti` próprio, preservando o padrão existente.
- `test_private_memory_overview_pg.py`: segundo admin com sessão registrada por
  `register_session` na transação sintética e `jti` distinto.
- `test_whatsapp_integrated_pg.py`: JWTs registrados por
  `register_session_with_backend_role`, como no login.
- `test_notification_outbox_evt7_e2e_pg.py`: sessão registrada na fixture EVT-7
  por `register_session`, também usado pelo registrador do login.

Validação local: Python 3.13.14, PostgreSQL 17.6 e Redis 7.4 descartáveis.

| Arquivo PG completo | Resultado |
|---|---:|
| `test_private_memory_overview_pg.py` | 44 passaram |
| `test_whatsapp_integrated_pg.py` | 8 passaram |
| `test_notification_outbox_evt7_e2e_pg.py` | 5 passaram |
| `test_auth_session_revocation_pg.py` | 7 passaram |
| `test_operational_usage.py` | 22 passaram |

Total PG: **86 passaram, zero skips**. Unitários: **111 passaram** em
`test_auth_login`, `test_auth_profile`, `test_auth_role_tenant`,
`test_clerk_password_auth`, `test_clerk_jwt_policy`,
`test_session_password_invalidation`, `test_team_revoke`, `test_team_roles` e
`test_auth_activate` (todos `.py`). Ruff e `git diff --check` passaram.
As 140 asserções existentes dos três arquivos PG alterados foram preservadas.

Cadeia de migrations aplicada somente pelo runner `backend/scripts/migrate.py`
em bancos sintéticos. Código de produção, validação/revogação, gates,
ROADMAP, catálogos e locks inalterados. Sem banco remoto, produção ou deploy.
Auditoria de `filelock` fora do escopo, conforme PR #570. Estes resultados são
locais; CI após o push precisa ser confirmado separadamente.
