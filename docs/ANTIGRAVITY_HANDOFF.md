# Antigravity handoff tecnico - PastorAI

Data: 2026-06-27
Branch de preflight: `codex/antigravity-preflight`
Base local: `95553d2` (`main` local)
Remoto: `origin/main` esta 68 commits a frente da base local

Este documento e o ponto de entrada operacional para continuar o PastorAI com
Antigravity. Ele nao substitui `AGENTS.md`; complementa com o estado real
encontrado no preflight.

## Status executivo

O projeto esta funcional localmente apos restaurar dependencias do frontend e
atualizar Next.js dentro da mesma major:

- Backend: suite `pytest -q` passou.
- Frontend: `npm run typecheck` passou.
- Frontend: `npm run build` passou com Next.js `14.2.35`.
- Grafo `code-review-graph` atualizado em 2026-06-27 11:35:35.

Mas ha riscos que devem ser tratados antes de feature nova:

- A base local esta atrasada 68 commits de `origin/main`.
- Ha uma alteracao visual grande ja existente em `frontend/src/app/globals.css`.
- Ha arquivos versionaveis ainda nao rastreados que precisam decisao humana.
- `npm audit` ainda falha com 10 vulnerabilidades, sem critica depois do patch
  de Next, mas com 9 altas e 1 moderada que exigem migracoes maiores.

## Estado Git

Comando de referencia:

```powershell
git status --short --branch
```

Estado apos o preflight:

```text
## codex/antigravity-preflight
 M .gitignore
 M frontend/package-lock.json
 M frontend/package.json
 M frontend/src/app/globals.css
?? AGENTS.md
?? backend/.dockerignore
?? backend/Dockerfile
?? deploy/.env.example
?? discovery-notes.md
?? docs/antigravity-onboarding-prompt.md
?? docs/ANTIGRAVITY_HANDOFF.md
?? docs/sprints/2026-06-27-antigravity-preflight.md
?? skills-lock.json
```

Nao fazer reset, rebase, checkout destrutivo ou limpeza automatica. A proxima
frente deve decidir explicitamente se parte desta branch ou de uma worktree nova
baseada em `origin/main`.

## Correcoes feitas neste preflight

1. Criada a branch `codex/antigravity-preflight` para parar de trabalhar em
   `main`.
2. Restauradas dependencias locais do frontend com `npm install`.
3. Atualizado `next` e `eslint-config-next` de `14.2.15` para `14.2.35`, sem
   salto major.
4. Atualizado `.gitignore` para bloquear estado local de agentes/IDEs:
   `.agents/`, `.claude/`, `.codex/`, `.lionclaw/`, `.mcp.json` e `*.bak`.
5. Atualizado `code-review-graph`.

Motivo do ignore: havia configs locais de agentes e worktrees nao rastreados.
`.claude/settings.local.json` continha permissoes/comandos locais historicos
com credenciais em texto. Nao versionar essa pasta.

## Validacao executada

Backend:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
```

Resultado: passou. Avisos observados:

- `StarletteDeprecationWarning` sobre `httpx`/`TestClient`.
- `InsecureKeyLengthWarning` em testes de Google OAuth por segredo de teste
  curto.
- `HTTP_422_UNPROCESSABLE_ENTITY` deprecated em alguns pontos.

Frontend:

```powershell
cd frontend
npm run typecheck
npm run build
```

Resultado: ambos passaram. Build confirmou Next.js `14.2.35`.

Auditoria:

```powershell
cd frontend
npm audit --audit-level=moderate
```

Resultado: falha residual com 10 vulnerabilidades: 9 high, 1 moderate. A
vulnerabilidade critica do Next 14.2.15 saiu com o patch para 14.2.35. As
restantes exigem `npm audit fix --force`, que hoje tentaria subir para:

- `@clerk/nextjs@7.5.9` (breaking change);
- `next@16.2.9` / `eslint-config-next@16.2.9` (breaking change).

Nao executar `npm audit fix --force` sem uma missao propria de upgrade.

## Contrato de seguranca e arquitetura

### Multi-tenant e RLS

Fonte principal: `backend/app/db/rls.py` e `backend/app/deps.py`.

Regra critica: a conexao Supabase pode usar role com `BYPASSRLS`; portanto nao
basta setar claims. O backend precisa chamar:

- `set_tenant_context(session, clerk_user_id)` em requests autenticados;
- `set_tenant_context_for_igreja(session, igreja_id)` em workers sem Clerk.

Ambos fazem `set local role authenticated` para a RLS valer.

Testes relevantes:

- `backend/tests/test_rls_context.py`
- `backend/tests/test_whatsapp_worker.py`
- `backend/tests/test_rbac.py`
- `backend/tests/test_platform_admin.py`

Excecao intencional: console de plataforma usa `get_platform_admin` sem
`set_tenant_context`, documentado em `backend/app/deps.py`, para operacao
cross-tenant via allowlist `platform_admins`. Nao reutilizar esse caminho em
endpoints normais de tenant.

### Migrations

Fonte: `backend/migrations/README.md`.

- Historico `0001` a `0017` esta congelado.
- Novas migrations usam timestamp UTC: `AAAAMMDD_HHMMSS_slug.sql`.
- Aplicacao no Supabase e manual, em ordem alfabetica.
- `ALTER TYPE ... ADD VALUE` nao deve ser usado na mesma transacao em que o
  novo valor e referenciado.

### Segredos

Arquivos reais de ambiente existem localmente e devem continuar ignorados:

- `backend/.env`
- `frontend/.env.local`

Templates versionaveis:

- `backend/.env.example`
- `frontend/.env.example`
- `deploy/.env.example`

Nao imprimir valores de `.env` no chat ou logs. Ao auditar, mostrar apenas nomes
de chaves e se estao `set`, `empty` ou `placeholder`.

## Arquitetura pelo code-review-graph

Estatisticas apos update:

- 206 arquivos
- 1.862 nos
- 15.268 arestas
- Linguagens: Python, SQL, JavaScript, TSX, TypeScript
- Testes indexados: 390

Comunidades principais:

- `routers-request`: backend HTTP/FastAPI.
- `services-client`: servicos externos e integracoes.
- `workers-message`: workers de WhatsApp/fila.
- `agent-node`: LangGraph/agente.
- `admin-screen`: telas React/TSX.
- `lib-fetch`: cliente API/tipos/fetch no frontend.
- `migrations-fn`: SQL/migrations.

Aviso arquitetural do grafo: alto acoplamento entre `admin-screen` e
`lib-fetch`. Mudancas em tipos/API frontend devem ser pequenas, com typecheck e
build obrigatorios.

## Riscos antes de entregar para Antigravity

1. **Divergencia com remoto**
   A base local esta atrasada 68 commits. O melhor caminho antes de feature nova
   e criar uma worktree limpa a partir de `origin/main` ou fazer merge/rebase em
   uma branch isolada apos salvar o que precisa desta branch.

2. **Mudanca visual grande em `globals.css`**
   Ja existia antes deste preflight. Nao reverter sem comparar com a branch de
   redesign/PR correspondente.

3. **Dependencias vulneraveis restantes**
   Clerk e Next/ESLint ainda exigem upgrade major para limpar audit. Tratar como
   missao separada com plano, leitura de changelog e testes de auth.

4. **Configs locais de agentes**
   Pastas `.claude/`, `.codex/`, `.agents/`, `.lionclaw/` e `.mcp.json` devem
   ficar fora do commit. Podem conter paths absolutos e historico operacional.

5. **Validacao RLS real**
   Testes locais validam SQL emitido e caminhos de app. A prova final de RLS
   precisa rodar contra Supabase/staging com dois tenants reais ou fixtures
   controladas.

## Proximas missoes seguras

1. **Sincronizacao limpa com `origin/main`**
   - Criar worktree/branch nova a partir de `origin/main`.
   - Reaplicar apenas `.gitignore`, Next patch e docs de handoff se ainda forem
     necessarios.
   - Criterio de pronto: `git status` claro, build/testes verdes.

2. **Upgrade major de Clerk/Next**
   - Plano separado para `@clerk/nextjs` 7 e Next 16.
   - Criterio de pronto: login, middleware, auth provider, build e audit.
   - Risco: auth e App Router.

3. **Gate RLS em staging**
   - Criar/verificar dois tenants.
   - Confirmar leitura/escrita isolada em endpoints criticos.
   - Criterio de pronto: evidencias com requests e respostas mascaradas.

4. **Triagem visual de `globals.css`**
   - Comparar com branches de redesign e design lock.
   - Criterio de pronto: decidir se a mudanca e desejada, mergeavel ou deve ser
     revertida numa branch propria.

## Instrucao para o Antigravity

Antes de implementar qualquer feature, o Antigravity deve:

1. Ler `AGENTS.md`.
2. Ler este arquivo.
3. Rodar `git status --short --branch`.
4. Confirmar se vai trabalhar nesta branch ou em worktree limpa de `origin/main`.
5. Entregar um relatorio de entendimento e plano de execucao.

Nao iniciar codigo novo enquanto a decisao sobre a divergencia com `origin/main`
nao estiver tomada.
