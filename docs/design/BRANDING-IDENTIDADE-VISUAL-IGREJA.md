# Branding — Identidade Visual por Igreja (Missão 4)

**Status:** Spec aprovada pelo dono (2026-07-06). PR0 docs-only. Nada implementado ainda.
**Escopo:** logo customizada por igreja + fallback pelo nome da igreja. Superfícies `admin.*` (configura) e `app.*` (exibe). `painel.*` (master) fora do escopo.

---

## 1. Decisões fechadas (dono, 2026-07-06)

| # | Decisão |
|---|---------|
| D1 | **Modelo de dados:** coluna `igrejas.logo_path text null` (sem tabela satélite). Policy RLS de UPDATE restrita à própria igreja + **grant por coluna** (tenant só atualiza `logo_path`). `igreja_id` sempre do token/contexto, nunca do payload. |
| D2 | **Onde aparece:** bloco "Sua igreja" (`.side-church`) da sidebar. A marca do produto "Igreja 12" **não muda** — logo customizada é do tenant, marca principal é do sistema. |
| D3 | **Nome da igreja:** read-only para o admin da igreja no MVP. Só o master (painel) edita nome. Admin edita somente a logo. |
| D4 | **Storage:** bucket público novo `church-logos`, path tenant-scoped `{igreja_id}/logo.{ext}`. Criação manual em DEV e PROD (registrado no runbook, §6). Zero env nova (`SUPABASE_URL`/keys atuais bastam). |
| D5 | **Upload:** base64-em-JSON (padrão atual do projeto). Backend valida: png/jpeg/webp, magic bytes, máx. 1 MB, sem SVG no MVP. Frontend valida e faz preview, mas backend é a fonte de segurança. |
| D6 | **Fora do escopo:** login, PWA/favicon/manifest, Células/Agenda/EVT-8, WhatsApp. Sem deploy, sem migration aplicada e sem bucket em PROD sem autorização do dono. |

## 2. Estado atual (scout Fase 0, verificado)

- `igrejas` = `id, nome (NOT NULL), status, plano, dono_id, created_at` (`backend/app/db/models.py:45-65`). Nenhum campo de branding.
- **RLS de `igrejas` é SELECT-only** (`igrejas_self_select`, `backend/migrations/0003_rls_policies.sql:69-77`). Todo request tenant roda `SET LOCAL ROLE authenticated` (`backend/app/db/rls.py`); um `UPDATE igrejas` hoje é no-op silencioso (0 linhas).
- `GET /auth/me` devolve só `churchId` — o nome da igreja não chega ao frontend (`backend/app/routers/auth.py:401-412`). `get_current_user` já carrega `app_user.igreja`, então expor nome/logo é aditivo.
- Nenhum endpoint tenant-facing de igreja; só o master edita via `PATCH /admin/igrejas/{id}` (`platform_admin.py`).
- Storage existente: `backend/app/services/storage.py` (`SupabaseStorage`, REST via httpx, service-role key, bucket privado `whatsapp-media`, signed URL 1h). Buckets são criados manualmente, fora de migrations.
- Upload existente: base64-em-JSON (decisão anti `python-multipart`, `backend/app/routers/conversations.py:164-175`); frontend usa `FileReader` (`frontend/src/lib/conversations-api.ts:200-244`). Sem Pillow; sem validação de dimensão em lugar nenhum.
- Shell: marca "Igreja 12" hardcoded na sidebar (`frontend/src/components/shell/Sidebar.tsx:136-141`); bloco `.side-church` mostra texto fixo "Painel da Igreja" + iniciais do usuário (`Sidebar.tsx:153-166`) — é o slot natural do branding do tenant. Sidebar é compartilhada entre app (`AppShell`) e admin (`/gestao`, `AdminAppShell`).
- Tela admin: superfície `admin.*` → `/gestao` (middleware), nav `ADMIN_NAV_SECTIONS` (`frontend/src/lib/navigation.ts:117-138`); receituário de tela = `IntegracoesScreen` (cards auto-gated por papel admin).

## 3. Arquitetura proposta

### 3.1 Banco (migration nova, padrão timestamp)

```sql
-- AAAAMMDD_HHMMSS_igreja_logo_branding.sql (gerar com scripts/new_migration.py)
alter table igrejas add column if not exists logo_path text null;

-- Tenant só enxerga UPDATE na própria linha…
create policy igrejas_self_update on igrejas
  for update
  using (id = current_igreja_id())
  with check (id = current_igreja_id());

-- …e só na coluna logo_path (grant por coluna).
revoke update on igrejas from authenticated;
grant update (logo_path) on igrejas to authenticated;
```

Notas:
- `logo_path` guarda o **path no bucket** (ex.: `{igreja_id}/logo.png`), não a URL completa — a URL pública é derivada no backend. Banco nunca guarda binário.
- Grant por coluna garante que, mesmo com a policy de UPDATE existindo, o tenant **não** consegue alterar `nome/status/plano/dono_id` (D3).
- Testar escrita **sob role `authenticated`** — o role de conexão tem BYPASSRLS e mascara erro de policy em dev.
- Migration **não aplicada** neste PR; aplicação manual DEV → PROD com autorização (D6).

### 3.2 Backend (PR1)

Router novo `backend/app/routers/church.py` (ou similar), todos os endpoints com o gate padrão `Depends(require_role(["admin"]))` + `ensure_tenant_context` (mesmo padrão de `/calendar/recipients`):

| Endpoint | Função |
|---|---|
| `GET /igreja/branding` | Retorna `{ nome, logoUrl }` da igreja do token. Leitura coberta pela policy `igrejas_self_select` existente. |
| `PUT /igreja/logo` | Body JSON `{ mime, base64 }`. Valida (§5), sobe pro bucket `church-logos` em `{igreja_id}/logo.{ext}` (path derivado do token), grava `logo_path`, retorna `logoUrl`. Sobrescreve logo anterior (remove objeto antigo se a extensão mudou). |
| `DELETE /igreja/logo` | Remove objeto do bucket + `logo_path = null`. Volta ao fallback por nome. |

Além disso, **`MeResponse` (`GET /auth/me`) ganha campos aditivos** `igrejaNome` e `igrejaLogoUrl` — é assim que o shell do `app.*` recebe o branding sem request extra. Mudança aditiva, não quebra o bootstrap do frontend.

Storage: reutilizar o padrão de `SupabaseStorage` com bucket público `church-logos` (URL pública estável `{SUPABASE_URL}/storage/v1/object/public/church-logos/{path}` — sem TTL, ao contrário do signed URL 1h do `whatsapp-media`). Cache-busting simples via query `?v=` derivado de timestamp de atualização, para o navegador não servir logo antiga após troca.

O master (`PATCH /admin/igrejas/{id}`) **não** ganha edição de logo no MVP — se necessário no futuro, é aditivo.

### 3.3 Frontend (PR2)

- **Shell (`app.*` e `admin.*`):** bloco `.side-church` da sidebar passa a renderizar:
  - com logo: `<img src={logoUrl} alt={igrejaNome} title={igrejaNome}>` com `object-fit: contain`, altura ~32px (caixa atual do `.church-avatar`), `onError` → cai para o nome;
  - sem logo: nome completo da igreja (vem de `/auth/me`), com ellipsis (`.church-meta` já tem) + `title` com nome completo;
  - sidebar colapsada: logo em variante compacta (mesma caixa 32×32, `object-fit: contain`) ou herda o comportamento de esconder labels;
  - mobile ≤860px: sidebar aparece via drawer — nada extra a fazer, o bloco vem junto.
- **Tela nova "Identidade Visual"** na superfície `/gestao`, seção "Configuração da Igreja" (`ADMIN_NAV_SECTIONS` + `SCREEN_META` + case no `ScreenView`, componente em `components/config/`), contendo:
  - logo atual (ou fallback atual com o nome — o admin vê exatamente o que os usuários veem);
  - nome da igreja **read-only** (D3), com nota "para alterar o nome, fale com o suporte";
  - upload: `<input type="file" accept="image/png,image/jpeg,image/webp">` oculto + botão; preview local via `FileReader` **antes** de salvar; validação client-side de formato/tamanho/dimensões (aviso);
  - instruções: PNG/JPG/WebP · máx. 1 MB · recomendado 512×160 ou 1024×320 (proporção 2:1 a 4:1, altura mínima útil 64px);
  - ação "Remover logo" (volta ao nome);
  - toast ok/err no padrão do projeto (`{kind, text}`, auto-dismiss ~3,2s).
- API client: `frontend/src/lib/branding-api.ts` no molde `authedFetch`/`ApiError`.

## 4. RLS / segurança

1. **Leitura:** policy `igrejas_self_select` existente já cobre o `GET`.
2. **Escrita:** policy `igrejas_self_update` nova + grant por coluna (§3.1). Sem isso o UPDATE é no-op silencioso — o teste do PR1 deve provar a escrita sob role `authenticated`.
3. **Storage:** a service-role key **bypassa** a RLS do Storage; o isolamento é disciplina de código — path sempre `{igreja_id do CurrentUser}/logo.{ext}`, nunca derivado do payload (mesmo padrão de `conversations.py`).
4. **Autorização:** endpoints de escrita são admin-only (`require_role(["admin"])`); pastor/líder/membro sem papel admin não editam. Leitura do branding via `/auth/me` é para qualquer usuário autenticado da igreja.
5. Uma igreja nunca vê/altera branding de outra: leitura via RLS, escrita via RLS + grant + path do token.

## 5. Limites e validação de upload

| Regra | Onde | Como |
|---|---|---|
| Formatos png/jpeg/webp | backend (fonte de verdade) + frontend (`accept=`) | whitelist de MIME **e** magic bytes (`\x89PNG`, `\xFF\xD8\xFF`, `RIFF....WEBP`) — ~10 linhas, sem dependência nova |
| SVG | rejeitado no MVP (sem sanitização no projeto; risco XSS) | 400 |
| Tamanho máx. 1 MB | backend (após decode base64) + frontend (aviso antes do envio) | 400 se exceder |
| base64 válido | backend | `b64decode(validate=True)` → 400 (padrão existente) |
| Dimensões/proporção (512×160–1024×320, 2:1–4:1, altura ≥64px) | **frontend apenas** (aviso não-bloqueante no preview) | backend não inspeciona pixels no MVP (sem Pillow); `object-fit: contain` garante que nada quebra |
| Payload base64 infla ~33% | aceito | 1 MB de imagem ≈ 1,37 MB de JSON — irrelevante |

## 6. Runbook — bucket `church-logos` (manual, fora de migrations)

Criar **antes do deploy do PR1**, em cada ambiente (mesma pegadinha do `whatsapp-media` — não esquecer o PROD):

1. Supabase Dashboard → Storage → New bucket → nome `church-logos` → **Public bucket: ON**.
2. DEV: projeto `cxmjojnocigekgcxhubi`. PROD: projeto `pffafnchtxbimpwyaczq` (⚠️ só com autorização do dono).
3. Sem policy de Storage adicional: escrita só via backend (service-role); leitura pública é intencional (logo é asset público).
4. Zero env nova — o backend já tem `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`.

## 7. Plano de PRs

| PR | Conteúdo | Precisa de |
|---|---|---|
| **PR0** (este) | Spec docs-only | — |
| **PR1** | Backend-only: migration (§3.1, não aplicada), constantes/serviço de bucket público, `GET /igreja/branding` + `PUT/DELETE /igreja/logo`, `MeResponse.igrejaNome/igrejaLogoUrl`, validação §5, testes (pytest, incl. escrita sob role authenticated e rejeições 400/403) | migration DEV+PROD, bucket DEV+PROD, recreate backend — **cada passo só com autorização** |
| **PR2** | Frontend: `branding-api.ts`, shell `.side-church` (logo/nome/fallback/ellipsis/colapsada/mobile), tela "Identidade Visual" em `/gestao` (preview, remover, toasts) | deploy Vercel |

PR1 é inerte até o PR2 consumir — sem feature flag.

## 8. Riscos

1. **RLS no-op silencioso**: sem a policy/grant, o PUT "funciona" e não persiste. Mitigação: teste automatizado sob role `authenticated` no PR1.
2. **Bucket manual esquecido em PROD**: upload retornaria 502. Mitigação: runbook §6 + smoke pós-deploy.
3. **Service-role bypassa RLS do Storage**: path fora do token vazaria/sobrescreveria logo alheia. Mitigação: path derivado exclusivamente do `CurrentUser`, coberto por teste.
4. **Cache de logo antiga** após troca/remoção: mitigação `?v=` cache-buster (§3.2).
5. **Sidebar colapsada/mobile**: logo horizontal em caixa pequena — `object-fit: contain` + variante compacta; validar visualmente no PR2.
6. **Master não edita logo** no MVP: se uma igreja subir imagem imprópria, o caminho de remoção é via suporte/SQL até existir ação no painel (dívida aceita, aditivo no futuro).

## 9. Smoke esperado (pós-PR1+PR2, por ambiente)

1. Admin abre `/gestao` → tela Identidade Visual → vê fallback com nome da igreja.
2. Upload PNG válido ≤1 MB → preview → salvar → toast ok → logo aparece na tela e no bloco "Sua igreja" do shell (app e admin).
3. Re-login / outro usuário da mesma igreja → vê a logo (via `/auth/me`).
4. Usuário de **outra** igreja → não vê a logo da primeira (nem consegue PUT — 403 se não-admin, RLS/path isolam entre igrejas).
5. Upload inválido (SVG, >1 MB, base64 corrompido, mime falsificado) → 400 com mensagem clara; nada persiste.
6. Remover logo → volta ao nome da igreja em todas as superfícies.
7. URL de logo quebrada manualmente (objeto apagado no bucket) → `onError` cai para o nome, layout intacto.
8. Nome longo → ellipsis + `title` com nome completo; mobile ≤860px sem overflow.
