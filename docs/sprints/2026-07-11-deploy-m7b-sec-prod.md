# Deploy M7B/SEC em produção — 2026-07-11

**Branch:** claude/m7b-sec-prod-deploy-05035f (worktree em `origin/main`)  ·  **Commits:** `8cbf78f` (== origin/main)  ·  **Deploy:** SIM — backend VPS (tarball cirúrgico) + frontend Vercel

Missão operacional (sem desenvolvimento): publicar em produção o lote já mergeado em `main`.

## O que foi feito
- Reconfirmado `origin/main` = `8cbf78f811b40f6d549bafbe13391be8561342ae` (esperado).
- Tarball backend-only via `git archive origin/main backend` → `pastorai-backend-8cbf78f.tar`
  (244 entradas; sem `.env` real, sem `Dockerfile`/`.dockerignore` → infra remota preservada).
  SHA-256 `73a0d432d5d41f0139a609819cb906973bdb31a2bf221580f0ecd9ba679bf631`.
- Prova de conteúdo (extraída do `.tar`): #148 `RateLimiter/enforce_ip` em `platform_admin.py`;
  #149 rota `GET /cells/{id}/membros` + guards 403 em `cells.py`; #150 `assert_membro_elegivel`,
  `find_ministerial_conflicts`, handler 409 em `main.py`, migration `20260711_152127_*`.
- VPS: SHA validado, backup `/opt/pastorai-lionclaw/backend.bak-20260711-175027` + img
  `pastorai-backend:pre-8cbf78f`, extração, `docker compose up -d --build --no-deps backend
  queue-worker cron-worker`. redis/caddy/evolution NÃO recriados (StartedAt idêntico, restarts=0).
- Frontend: `vercel --prod` de checkout limpo de main → deployment `6vsxqo97b`, alias
  `app.igreja12.com.br`.

## Decisões
- Tarball via `git archive` (não worktree novo): lê do object DB, elimina risco de arquivo solto
  e reproduz `origin/main` exato. Equivale ao "checkout limpo" pedido.
- Deploy frontend do próprio worktree (é main exata) copiando só o link `.vercel` do clone
  principal — não tocar o clone principal (está noutra branch, regra de concorrência).

## Pendente / próximo passo
- **M7B-W1.3** — "Minha Célula do Líder": esconder botões Transferir/Remover na visão do líder
  (resíduo visual confirmado no smoke D; não é regressão deste deploy).
- Housekeeping VPS: `System restart required` + 26 apt updates (1 security) — agendar janela.

## Verificação
- SHA local == pré-upload == VPS. Backup + rollback img criados.
- Health público `api.igreja12.com.br/health` = 200 `{"status":"ok"}`; Evolution→backend 200.
- Containers: backend healthy, workers up, redis/caddy healthy; evolution up e alcançável.
- Alias `app.igreja12.com.br` = 200 (Server: Vercel).
- Smokes A (admin/Central #149), B (master/rate-limit #148), C (WhatsApp online), D (líder/Minha
  Célula) = PASS atestados pelo dono. **Veredito: PROD PASS.**
