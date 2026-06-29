# EVT-0 — Decisão da Agenda de Eventos — 2026-06-29

**Branch:** `docs/evt0-agenda-decisao` · **Commits:** (ver PR) · **Deploy:** não (docs-only)

## O que foi feito
- Auditoria E0 (read-only) da Agenda concluída na base `baeb26c`: a feature **não é greenfield** — já há tabela `events`, tela mensal, GET/POST parcial, push app→Google com risco de token global, OAuth por igreja robusto porém inerte para escrita.
- Registrada a decisão técnica/produto em `docs/design/AGENDA-EVENTOS-EVT0-decisao.md` (fonte única do módulo).
- PRD anotado (`docs/Docs20260611_163530/PRD20260611_163530.md`): **delta-049/050/051** + pointers inline em RF-34/RF-35, na entidade `evento` e na tela `calendario`.
- SPEC anotada (`SPEC.md`): seção 6.4 calendario e Área Calendario & Eventos apontando para o doc de decisão (módulo em expansão; mês-only = baseline atual).

## Decisões
- **Honrar a spec nova das 5 abas** (Semana/Mês/Ano/A confirmar/Planejamento) — feature funcional, não reskin. Diverge do PRD (RF-35 = mês/semana/dia) → anotado por delta (regra #2).
- **Reuso:** estender a tabela `events` existente (não criar "eventos" paralela); evoluir endpoints/tela atuais (regra #4).
- **Google = direção IMPORT** (Google→app como `a_confirmar`), **fora do MVP**. Risco alto: o push usa token GLOBAL (Legacy), desconectado do OAuth por igreja (`calendar_sync`) → cruzamento entre tenants. **Não implementar Google antes de corrigir o token por igreja** (primeiro passo do EVT-6).
- **MVP = EVT-1..5**, 100% manual: CRUD, Semana/Mês/Ano, criar/editar/detalhe, status `confirmado`/`a_confirmar`, aba "A confirmar", confirmação manual **sem envio real**.
- **Sem envio real no MVP**; outbound guard B2 mantido. Envio só no EVT-7 (com dedup persistido).
- **Papéis:** Pastor/Admin (`admin`+`pastor`) criam/editam/confirmam/configuram; líderes e demais só veem. **Remover `lider_g12`** da criação no EVT-2 (hoje líder cria, diverge da spec).
- **Status:** evento manual nasce `confirmado`; importado nasce `a_confirmar`. Antes do EVT-6, pendentes só por seed/teste/inserção técnica manual — nunca por Google real.

## Pendente / próximo passo
- **EVT-1** — schema/migration/RLS/model/tests (estender `events`).
- EVT-6 (Google import, começa pelo fix de token por igreja) e EVT-7 (planejamento/assistente/envios) ficam pós-MVP.
- Paridade visual das telas novas (abas/confirmação/planejamento) pendente de design — resolvida nas PRs de frontend.

## Verificação
- Docs-only: zero alteração em frontend, backend, migrations, env e scripts de deploy. `git diff --check` limpo.
- Sem deploy, sem migration, sem teste de app executado (não aplicável a docs).
