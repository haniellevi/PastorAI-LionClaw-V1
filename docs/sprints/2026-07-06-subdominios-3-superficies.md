# Subdomínios — 3 superfícies (painel/admin/app) — 2026-07-06

**Escopo:** frontend (separação de superfície/menu/visibilidade) + backend só CORS · **Deploy:** SIM (backend VPS + frontend Vercel + DNS) · **Sobre:** PR [#101](https://github.com/haniellevi/PastorAI-LionClaw-V1/pull/101), merge commit `354ac0a`

## Objetivo

Separar o sistema em **3 superfícies por subdomínio**, sem criar módulo novo — só
separar superfície, menu e visibilidade por papel/host:

| Domínio | Superfície | Rota interna |
|---|---|---|
| `painel.igreja12.com.br` | **Console master** (dono do sistema/plataforma) — antes em `admin.` | `/admin` (inalterada) |
| `admin.igreja12.com.br` | **Admin da igreja** (NOVO) — só ferramentas administrativas | `/gestao` (nova) |
| `app.igreja12.com.br` | **Uso diário** (todos os papéis; admin/pastor como usuário normal) | `/` |

## O que foi feito

### PR1 — separação (`6459839`)
- **`middleware.ts`**: `painel.` → rewrite `/admin` (console master); `admin.` → rewrite `/gestao` (NOVO); `app./admin` → redirect 307 para `painel.` (link legado do console).
- **`AdminAppShell`** (novo): shell da superfície admin reusando Sidebar/Topbar/ScreenView com menu próprio (`ADMIN_NAV_SECTIONS`), sem Jornada/BottomNav; allow-list de rota derivado do menu admin (deep-link `#dashboard`/`#inbox` não vaza pra dentro do admin); `assinatura` preserva gate OWNER_ONLY (admin não basta — só o dono).
- **`app/gestao/page.tsx`** (novo): raiz da superfície admin; não-admin autenticado é devolvido ao app.
- **`navigation.ts`**: seção "Configuração" (5 telas: whatsapp, agente, assinatura, permissoes, equipe) sai do menu operacional → vira `ADMIN_NAV_SECTIONS`.
- **`AppShell`**: telas ADMIN_ONLY bloqueadas por URL no app (inclusive para admin); botão **"Admin"** no menu (só papel admin) troca de superfície.
- **`auth-context.tsx`**: token de sessão também em cookie `pastorai_token` com `domain=.igreja12.com.br` → sessão compartilhada app.↔admin. (seamless); localStorage mantido como fallback.
- **`config.py`**: CORS deriva `painel.` além de `admin.` a partir de `app.` (única mudança de backend). Teste `test_config_cors.py` atualizado.

### PR2 — relocação da config da Agenda (`87a36bd`)
- **`IntegracoesScreen`** (nova, superfície admin): reúne os 2 cards admin-estrito que viviam embutidos na Agenda operacional — `CalendarConnectCard` (conexão Google + import) e `AlertRecipientsCard` (destinatários dos avisos). Cards reusados como estão.
- **`CalendarioScreen`**: cards removidos; a Agenda do app fica só operação. Criar/editar/excluir/confirmar evento + aba "A confirmar" **permanecem no app** (são pastor+admin, não admin-estrito — decisão do dono: mover tiraria capacidade do pastor).

### Fix (`5a8c89b`)
- `integracoes` adicionada a `ADMIN_ONLY` (permissions.ts): aparece no menu admin (Sidebar filtra por allowedScreens) e fica bloqueada por URL no app.

## Decisões do dono (registradas)
1. `admin.` = mesma app/repo/deployment, menu/layout próprio + gate por papel (sem árvore duplicada).
2. Sessão seamless via cookie no domínio-pai (fallback re-login documentado).
3. Console master migra de `admin.` → `painel.`; `app./admin` redireciona pra `painel.`.
4. Convite/gestão de equipe inteira no admin.
5. Controles **pastor+admin** (evento, Central de Célula, promover, células) **ficam no app** — mover seria feature nova.

## Deploy (2026-07-06)
- **DNS**: CNAME `painel` → `cname.vercel-dns.com` criado (Hostinger) + `vercel domains add painel.igreja12.com.br` (projeto pastorai-frontend).
- **Backend**: scp `config.py` → VPS `/opt/pastorai-lionclaw/backend/app/` + `docker compose up -d --build --no-deps backend` (em `deploy/`). `pastorai_backend` **healthy**; workers cron/queue **intactos** (Up 12 days). CORS prod verificado: preflight com Origin `painel.`/`admin.` retorna Allow-Origin correto.
- **Frontend**: `vercel --prod` do worktree (repo principal estava detached+dirty — não tocado). Deployment `pastorai-frontend-i8c9qhhfy` (inspect `5j5EYZ1VsxzTyqEjZpgwASs5cT9V`).

## Verificação
- Gates: backend ~942 passed · front typecheck+lint+build verdes · `git diff --check` limpo · 14 arquivos todos no escopo.
- Prod: `app.` 200 (Painel da Igreja) · `admin.` 200 (superfície admin/gestao) · `painel.` 200 (Console da Plataforma) · `app./admin` → 307 `painel.`.
- Validação manual do dono em localhost (login admin → botão Admin → /gestao → Integrações) antes do deploy.

## O que NÃO foi tocado
Migrations/Supabase · flag `CELULAS_REQUESTS_ENABLED` (segue off) · WhatsApp/Evolution · workers · env de prod (além do CORS já no código) · repo principal (detached+dirty, preservado).

## Pendências que ficaram
- Spot-check funcional em prod com login (validado em local; prod é o mesmo código).
- Repo principal `PastorAi-1.0` detached+dirty — reconciliar (fora desta frente).
- Próxima frente (autorizada, não iniciada): **EVT-8** — confirmar evento = configurar notificação (select de contatos do WhatsApp / coletivo por categoria + antecedência). PR #88 draft (EVT-8b modal) é insumo.
