# Relatório curto: logout no servidor

Base: `ed6c2440b87fdaf7a595448da807e07b5f605d2d`.

Corrigidos grants/RLS de `auth_sessions`, emissão pelo papel privilegiado do
backend, limpeza diária pelo `cron-worker`, compatibilidade do FK composto com
admins de plataforma sem igreja e sequência/rollback no runbook. O ROADMAP
registra o logout como candidato ainda não integrado.

Validação: 36 testes focados passaram; 7 testes PostgreSQL passaram com zero
skip em banco descartável local; Ruff passou. A cadeia de migrations foi
aplicada somente no PostgreSQL descartável por `backend/scripts/migrate.py`.

Sem acesso a banco remoto, produção ou deploy. Nenhum gate de efeito foi alterado.
