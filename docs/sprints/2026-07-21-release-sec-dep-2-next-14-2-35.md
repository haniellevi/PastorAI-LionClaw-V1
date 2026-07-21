# Release Next 14.2.35 (SEC-DEP-2) — 2026-07-21

**Branch:** fix/next-14-2-35 (mergeada em `main` via PR #201)  ·  **Commits:** `93c855c72289c7e62490a23263e06e5a2e95fd2d` (merge, 2 pais: `f5a81ad6` + `507dae65`)  ·  **Deploy:** SIM — frontend Vercel PROD

## O que foi feito
- PR #201 mergeada em `main` por merge commit real `93c855c72289c7e62490a23263e06e5a2e95fd2d` — 2 pais (`f5a81ad6...` + `507dae65...`), sem squash, sem rebase; branch `fix/next-14-2-35` preservada.
- `next` e `eslint-config-next` atualizados de `14.2.15` para `14.2.35` (`frontend/package.json` + `frontend/package-lock.json`; diff restrito a esses 2 arquivos).
- Deploy frontend em produção: novo deployment `dpl_4ytrpHi8gJtL2jwZ5SKj4ZmJQwmH`, estado **READY**, target `production`.
- Aliases `app.igreja12.com.br`, `admin.igreja12.com.br` e `painel.igreja12.com.br` promovidos para o novo deployment.
- Nenhuma alteração em backend, banco de dados ou migration nesta missão.

## Decisões
- Bump estrito (só versão de dependência), sem tocar código de aplicação — reduz superfície de regressão.
- `14.2.35` tratado como **hardening intermediário**, não como estado livre de vulnerabilidades: a série Next 14 é EOL e não recebe backport dos advisories mais recentes.
- Rollback primário mantido no deployment de produção imediatamente anterior a esta publicação (preservado, não removido) — disponível para reversão caso necessário.

## Pendente / próximo passo
- **SEC-DEP-3 (obrigatório)**: missão de re-grounding e migração major do Next. `15.5.20` foi a baseline considerada na auditoria anterior — cobre os advisories diretos do framework analisados até então, mas **não é alvo garantidamente limpo**: fixa `postcss@8.4.31`, abaixo do patch `8.5.10` (`GHSA-qx2v-qp2m-jg93`). A versão-alvo final deve ser decidida com audit e compatibilidade vigentes no momento da execução de SEC-DEP-3 — não fica fixada a priori nesta release.
- **Rechecagem do audit (2026-07-21)**: `npm audit --omit=dev` aponta **7 pacotes vulneráveis (6 high, 1 moderate)** em dois grupos independentes:
  - **Next/PostCSS** — `next` (múltiplos advisories sem backport pra série 14: DoS, SSRF via WebSocket, cache poisoning, XSS via CSP nonce, bypass i18n) + `postcss` (XSS moderate). Orientação atual do audit: `next@16.2.10`.
  - **Clerk/js-cookie** — `@clerk/clerk-react`/`@clerk/shared`/`@clerk/backend` + `js-cookie` (prototype hijack em `assign()`). Orientação atual do audit: `@clerk/nextjs@7.5.20`.
- **Clerk como frente separada** de avaliação/upgrade, independente do bump de Next: `@clerk/clerk-react` 5.12.0 continua nominalmente sinalizado pelo advisory `GHSA-w24r-5266-9c3c`, mas não foi encontrado no código o pré-requisito explorável (combinação organization/billing/reverification em `has()`/`auth.protect()`) — conclusão da auditoria anterior, preservada.

## Verificação
- Smoke público (read-only, sem autenticação) nos 3 domínios: **3/3 PASS** — HTTP 200, páginas não vazias, conteúdo/roteamento consistente.
- Smoke autenticado read-only — **verificação externa pelo Codex, sessão separada, após o deployment PROD** (não executado por este agente):
  - Admin: Pessoas carregou, abas responderam, sem erro de console.
  - App: Dashboard carregou, navegação para Agenda funcionou, console limpo.
  - Painel central: sessão super-admin carregou; Orquestrador abriu com foco inicial em "Nome do agente", fechou sem salvar e devolveu foco ao botão de abertura; console limpo.
  - Nenhum formulário enviado, nenhum dado alterado.
- `npm ci`, suíte de testes, typecheck, lint e build de produção: todos verdes antes do deploy.
- **Este runtime não está livre de vulnerabilidades** — 7 findings remanescentes documentados acima. O fechamento exige revalidação do framework e do Clerk, novo audit e todos os gates após as atualizações.
