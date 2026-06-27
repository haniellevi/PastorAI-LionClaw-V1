# Prompt de onboarding para Antigravity - PastorAI

Voce e o Antigravity trabalhando no projeto PastorAI. Esta conversa/frente usa
Antigravity; existe outra frente separada com Claude Code. Nao presuma que voce
conhece o que foi feito na outra conversa. Antes de implementar qualquer coisa,
estude o projeto local e entregue um relatorio do que entendeu.

## Contexto do produto

PastorAI e um SaaS de gestao pastoral para igrejas no modelo G12: ganhar,
consolidar, discipular e enviar. O objetivo atual nao e construir BI generico;
e operar uma fila de trabalho pastoral com pendencias reais, WhatsApp, IA e
decisao humana quando necessario.

Stack principal:

- Backend: FastAPI em `backend/`, entrada `backend/app/main.py`,
  SQLAlchemy/PostgreSQL Supabase, Clerk, LangGraph, Evolution API, Asaas,
  Brevo e Google Calendar.
- Frontend: Next.js 14 App Router em `frontend/`, Clerk, PWA e mobile-first.
- Banco: migrations SQL em `backend/migrations/`; historico `0001` a `0017`
  congelado. Novas migrations devem usar timestamp UTC no formato
  `AAAAMMDD_HHMMSS_slug.sql`.
- Multi-tenant: todo endpoint/query deve respeitar `igreja_id`.

## Fontes de verdade para leitura inicial

Leia nesta ordem:

1. `AGENTS.md`
2. `docs/ANTIGRAVITY_HANDOFF.md`
3. `CLAUDE.md` apenas como historico de regras equivalentes; adapte mentalmente
   "Claude Code" para "Antigravity" quando a regra for de engenharia.
4. `SPEC_PROGRESS.md`
5. `SPEC.md`
6. `docs/Docs20260611_163530/PRD20260611_163530.md`
7. `docs/sprints/README.md`
8. Sprints recentes em `docs/sprints/`
9. `backend/migrations/README.md`
10. Se disponivel, consulte o grafo local `code-review-graph` antes de
    grep/leitura ampla.

## Regras obrigatorias de seguranca

- Nao implemente nada antes de entregar o relatorio de entendimento e receber
  confirmacao.
- Nao faca reset, checkout destrutivo, rebase, limpeza de arquivos, delete
  recursivo ou sobrescrita de arquivos nao rastreados sem autorizacao explicita.
- Antes de qualquer feature, crie branch ou worktree isolado com prefixo claro,
  por exemplo `antigravity/<slug-da-feature>`.
- Rode `git status --short --branch` e relate branch atual, divergencia com
  remoto, arquivos modificados, arquivos nao rastreados e risco de conflito com
  trabalhos de outros agentes.
- Nunca commite `.env` real, chaves, tokens, dumps ou segredos. Use apenas
  `.env.example`.
- Para backend, preserve RLS e tenant safety. Nunca remova `set_tenant_context`
  nem bypass de tenant. O role Supabase pode ter BYPASSRLS, entao a seguranca
  depende do contexto correto.
- Mudanca estrutural fora do PRD exige atualizar PRD/SPEC ou registrar
  explicitamente como decisao pendente.
- Ao fechar sprint/bloco, registrar em `docs/sprints/AAAA-MM-DD-titulo.md`.

## Como usar Antigravity neste projeto

Use o modelo de trabalho com artefatos revisaveis:

- Para tarefa grande, primeiro gere um Implementation Plan/artefato de plano.
- Configure Artifact Review como "Request Review" quando disponivel.
- Use acesso de filesystem em modo estrito/restrito ao projeto quando possivel.
- Se MCP estiver disponivel, habilite/valide `code-review-graph` e use-o antes
  de explorar o codigo com busca textual.
- Se precisar de navegador para validar frontend, produza prova objetiva: URL
  local, viewport, prints ou checklist de fluxos.

## Relatorio que voce deve entregar agora

Entregue um relatorio em portugues com estas secoes:

1. **Resumo do Produto**
   - O que e o PastorAI.
   - Quem usa.
   - Qual e o fluxo pastoral principal.

2. **Arquitetura Entendida**
   - Backend, frontend, banco, servicos externos.
   - Onde ficam endpoints, services, models, migrations e telas principais.

3. **Estado Atual**
   - O que parece concluido segundo `SPEC_PROGRESS.md`.
   - O que os ultimos sprints registraram.
   - Estado real do git local.

4. **Regras Criticas**
   - Multi-tenant/RLS.
   - Migrations.
   - Git/branch/worktree.
   - Segredos.
   - Registro de sprint.

5. **Riscos Antes de Desenvolver**
   - Arquivos modificados/nao rastreados.
   - Divergencia com remoto.
   - Dependencias de ambiente.
   - Pontos que exigem confirmacao humana.

6. **Proposta de Proximo Passo**
   - 3 a 5 frentes pequenas e seguras para continuarmos.
   - Para cada frente: arquivos provaveis, testes, risco e criterio de pronto.

Nao escreva codigo ainda. Termine perguntando qual frente devemos executar
primeiro.
