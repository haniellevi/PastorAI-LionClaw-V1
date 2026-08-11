# Fontes e rastreabilidade

## 1. Preflight

- Horário local do prompt: 2026-08-10 11:03:32, America/Sao_Paulo.
- Worktree: `C:\Users\hanie\.codex\worktrees\fd55\PastorAi-1.0`.
- HEAD: detached.
- Base SHA: `3f085ec7228d770649b0d9041f0e16154fe37629`.
- `origin/main`: mesmo SHA no preflight.
- Estado inicial: árvore limpa.
- Estado final esperado desta missão: somente `Plan-Designer-Igreja12/` como pasta nova não rastreada.

## 2. Gate de grafo

Não foram encontrados:

- `graphify-out/manifest.json` válido;
- `graphify-out/graph.json` validado;
- `.codegraph/codegraph.db` validado.

Sem manifesto, timestamp, raiz, commit e saúde comprováveis, Graphify e CodeGraph foram classificados como `NÃO COMPROVADO`. Nenhum índice antigo foi usado como evidência e nenhum grafo foi atualizado. A auditoria utilizou leitura direta de documentação e código no SHA atual.

## 3. Fontes originais do usuário

- `fontes-originais/01-visao-geral-igreja-g12-agentes.txt`
- `fontes-originais/02-pessoas-papeis-permissoes.txt`
- `fontes-originais/03-agenda-eventos.txt`
- `fontes-originais/04-celulas-central.txt`
- mensagem desta tarefa com propósito do agente, atualização cadastral, dashboards, permissões, agentes e prioridades da Filadélfia.

## 4. Documentação de design e produto

Fontes principais consultadas:

- `docs/design/PLANO-MESTRE-REFATORACAO-VISUAL-IGREJA12.md`
- `docs/design/AUDITORIA-UX-UI-IGREJA12-2026-07-11.md`
- `docs/design/IDENTIDADE-VISUAL-DIAMANTE-LAPIDADO-IGREJA12.md`
- `docs/design/REDESIGN-UX-AJUSTES-POS-F4.md`
- `docs/design/RECONCILIACAO-igreja12.md`
- `docs/design/prototypes/igreja12-quiet-operations/`
- `docs/design/CELULAS-DECISOES-FINAIS.md`
- `docs/design/ONBOARDING-IGREJA-PRIMEIROS-PASSOS.md`
- `docs/design/pontos-melhoria.md`
- especificações e PRDs de Agenda e Células em `docs/design/`
- decisões de fechamento e pós-MVP em `docs/decisions/`
- sprints F0 a F4 em `docs/sprints/`
- `DESIGN.md`
- `PRODUCT.md`
- `PRD.md`
- `SPEC.md`
- `docs/PRD_MVP.md`, quando aplicável.

Documentos antigos foram tratados como histórico quando divergiam do código atual.

## 5. Código e contratos consultados

### Shell e design

- `frontend/src/app/design-tokens.css`
- `frontend/src/app/globals.css`
- `frontend/src/app/ds.css`
- `frontend/src/lib/navigation.ts`
- `frontend/src/lib/permissions.ts`
- `frontend/src/lib/roles.ts`
- `frontend/src/components/shell/`
- `frontend/src/components/dashboard/`
- `frontend/src/components/config/SetupChecklistScreen.tsx`
- `backend/app/routers/setup.py`

### Pessoas, papéis e conversas

- `frontend/src/components/contacts/`
- `frontend/src/components/pipeline/`
- `frontend/src/components/team/`
- `backend/app/routers/contacts.py`
- `backend/app/routers/pipeline.py`
- `backend/app/routers/team.py`
- `backend/app/routers/roles.py`
- `backend/app/routers/conversations.py`
- `backend/app/routers/dashboard.py`
- `backend/app/routers/work_queue.py`

### Agenda

- `frontend/src/components/calendario/`
- `frontend/src/lib/events-api.ts`
- `frontend/src/lib/calendar-api.ts`
- `backend/app/routers/events.py`
- `backend/app/routers/calendar.py`
- `backend/app/services/event_recipients.py`
- `backend/app/services/event_notify.py`

### Células

- `frontend/src/components/cells/`
- `frontend/src/components/minha-celula/`
- `frontend/src/components/central-celula/`
- APIs de célula em `frontend/src/lib/`
- routers de célula em `backend/app/routers/`
- services e domínio de solicitações e multiplicação.

### Agente e WhatsApp

- `backend/app/workers/queue_worker.py`
- `backend/app/workers/cron_worker.py`
- `backend/app/agent/`
- `backend/app/domain/consent.py`
- `backend/app/domain/classification.py`
- `backend/app/domain/broadcast.py`
- `backend/app/routers/agent.py`
- `backend/app/routers/platform_admin.py`
- `backend/app/routers/whatsapp.py`
- `backend/app/routers/broadcasts.py`
- `backend/app/services/evolution.py`
- `backend/app/services/pessoa_dedup.py`
- migrations relacionadas a pessoas, agente, Agenda, Células e broadcasts.

## 6. Pesquisa oficial

- [WCAG 2.2, W3C](https://www.w3.org/WAI/standards-guidelines/wcag/)
- [Novidades da WCAG 2.2, W3C](https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/)
- [WAI-ARIA Authoring Practices Guide](https://www.w3.org/WAI/ARIA/apg/)
- [Core Web Vitals, web.dev](https://web.dev/articles/vitals)
- [Acessibilidade, web.dev](https://web.dev/learn/accessibility)
- [Next.js Font](https://nextjs.org/docs/app/api-reference/components/font)
- [Next.js Image](https://nextjs.org/docs/app/api-reference/components/image)
- [Next.js Linking and Navigating](https://nextjs.org/docs/app/getting-started/linking-and-navigating)

## 7. Observação do produto

Foram preservadas capturas públicas sanitizadas em:

- `assets/research/login-publico-390-sanitizado.jpg`
- `assets/research/login-publico-1440-sanitizado.jpg`

A sessão autenticada não estava disponível para uma auditoria completa por papel. Assim, layout interno em produção, dados reais, flags, workers e performance de campo permanecem `NÃO COMPROVADO`.

## 8. Ativos

### Canônicos no SHA atual

- seis ativos em `assets/brand/` copiados de `frontend/public/brand/`.

### Conceitual

- `assets/concepts/conceito-farol-de-hoje.png`.

### Históricos

- quatro imagens do protótipo Quiet Operations em `assets/references/`.

## 9. Limites

- nenhuma migration aplicada;
- nenhum banco consultado ou alterado;
- nenhum serviço externo alterado;
- nenhuma mensagem enviada;
- nenhum segredo solicitado ou exposto;
- nenhum commit, push, PR, merge ou deploy;
- nenhuma alegação de produção ativa baseada apenas no código.

## 10. Regra de atualização deste plano

Quando o produto evoluir:

1. registrar novo SHA e ambiente;
2. executar gate de grafo novamente;
3. comparar o comportamento atual com a matriz;
4. mover itens entre implementado, parcial, ausente e não comprovado;
5. preservar decisões aprovadas;
6. nunca copiar requisitos históricos sobre uma melhoria mais recente sem análise.
