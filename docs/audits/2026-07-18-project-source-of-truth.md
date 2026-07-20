# Igreja 12 - fonte de verdade de produto e codigo

**Data-base:** 2026-07-18
**Commit auditado:** `ceef64d629f95adde724f265995159c718b26812` (`origin/main`)
**Objetivo:** orientar as proximas missoes sem depender de chats antigos ou grafos desatualizados.
**Substitui:** `docs/audits/2026-07-10-project-source-of-truth.md` (baseline `ac6f706`).

## Como usar esta fonte

A ordem de confianca e:

1. `origin/main` e o codigo executavel.
2. Este documento registra o estado funcional e a ordem das proximas missoes.
3. `code-review-graph` responde estrutura, impacto, callers e testes do codigo atual.
4. `graphify-out/graph.json` responde arquitetura ampla, codigo e documentos.
5. Smokes em DEV/PROD comprovam ativacao operacional; merge isolado nao comprova deploy.

Antes de implementar, a conversa deve confirmar que o commit-base do grafo e o
commit do worktree sao iguais. Se divergirem, o codigo vence e o grafo deve ser
reconstruido.

## Estado confirmado na main

### Concluido (acumulado ate a baseline de 2026-07-10)

Tudo o que a baseline `ac6f706` listava como concluido permanece valido
(seam RLS/tenant-context, guardas de lider, `celula_membro` canonico, billing
por catalogo, SEC-1..SEC-4 iniciais etc.) — ver o documento de 2026-07-10.

### Concluido entre 2026-07-10 e 2026-07-18

- **M7B-W1 - identidade WhatsApp e classificacao de membro:** concluido e
  deployado (PR#147 e sucessores; nao esta mais "em desenvolvimento").
- **Arquivamento seguro de Pessoa (W3.2A/B):** backend PR#163 + frontend
  PR#169, com preflight de vinculos e trilha `pessoa_arquivamento_evento`.
- **TOCTOU de solicitacoes de celula (SEC-4B):** PRs #156, #157, #158, #159.
- **Capacidade `pode_transferir` (D2):** PR#160.
- **Redesign visual Fable F0 + gates 6-10:** PRs #161, #164, #165, #166,
  #167, #168.
- **CONV-AI-1:** `sem_interesse` pausa a IA (PR#170).
- **Preflight com multiplos `app_users`:** fix de 500 (PR#171).
- **Release backend `82e1c6f` (2026-07-16):** SLA-ALIGN-1 (PR#175),
  MSG-IDEMP-1 (PR#176, migration em PROD), PIPE-1 (PR#178) e CONSOL-1
  (PR#179, migration em PROD).
- **Waves visuais:** W2 (PR#173), W3 (PR#174), W4A (PR#183), W4B (PR#184) —
  dialogos migrados para o primitive `ds/Dialog`; frontend deployado
  (~2026-07-15 e 2026-07-17).
- **Release backend `70846d2` (2026-07-16):** SEC ALTO-003 (PR#181,
  `CENTRAL_ROLES` fonte unica) e SEC ALTO-004 parte 1 (PR#182, OAuth state
  do Google Calendar via `verify_purpose_token`).
- **Release backend `fd651f9` (2026-07-17):** conclusao de SEC ALTO-004 /
  unificacao da verificacao JWT (PR#186); reconciliacao REL-5 em
  `docs/security/` (PR#185/#187) — 9 de 11 findings ALTO/MEDIO concluidos e
  deployados.
- **Release backend+frontend `b5b990d` (2026-07-18, PR#188):**
  MEDIO-004/CONTACT-TENANT-DEDUP-1 (dedupe de contato com filtro explicito de
  `igreja_id`), MEDIO-005/JWT-MINT-1 (emissao unificada dos 3 tokens de
  proposito) e W5A (ultimos 8 dialogos em `ds/Dialog`). Smoke autenticado em
  PROD 2026-07-18: PASS (PR#189/#191).
- **Decisoes de fechamento do MVP registradas:**
  `docs/decisions/2026-07-18-decisoes-fechamento-mvp.md` (PR#190).
- **SPEC/SPEC_PROGRESS sincronizados com a main real (M6):** SPEC §2.1 com as
  45 tabelas de `backend/app/db/models.py`; cronologia 2026-07-08..18 no
  SPEC_PROGRESS.

## Backlog priorizado (missoes abertas do fechamento do MVP)

Fonte: `docs/decisions/2026-07-18-decisoes-fechamento-mvp.md` e plano de
fechamento.

1. **M4 - DOC-REL retroativos:** registrar em `docs/sprints/` os releases de
   frontend sem doc versionado (~2026-07-14/15/17).
2. **M5 - UNIQ-PESSOA-1:** unicidade canonica de Pessoa por telefone+igreja.
3. **M7 - SEC-BAIXO-REVAL:** revalidar findings BAIXO restantes contra a main
   atual antes de qualquer correcao nova.
4. **OPTIN-1:** re-opt-in administrativo de comunicacoes (backend+frontend,
   sem migration).
5. **REATIVAR-1:** reativacao administrativa de pessoa arquivada (campos ja
   existem, sem migration).
6. **ROTULO-1:** renomear "Sem interesse (CSIM)" para "Fora da igreja"
   (frontend-only).
7. **AGENDA-ORD-1:** aba "A confirmar" ordenada por data (frontend-only).
8. **M10 - fechamento:** consolidacao final do plano de fechamento do MVP
   (registro de sprint + atualizacao desta fonte de verdade).

## Trilha paralela de seguranca

- Usar `docs/security/2026-07-08-seg-igreja12-remediation-plan.md` como
  inventario; ultima reconciliacao REL-5 (2026-07-17) + fechamento de
  MEDIO-004/MEDIO-005 em `b5b990d`.
- Restam os findings **BAIXO** (missao M7 - SEC-BAIXO-REVAL).
- Todo finding multi-tenant exige teste com Postgres real e role sem BYPASSRLS.

## Protocolo para novas conversas Claude Code

1. Abrir conversa nova por missao independente.
2. `git fetch origin --prune`.
3. Criar worktree limpo de `origin/main`; nunca reutilizar checkout antigo.
4. Ler este documento e o documento especifico da missao.
5. Rodar `code-review-graph status`; o commit deve corresponder ao worktree.
6. Consultar CRG antes de Grep/Read. Usar Graphify para arquitetura e docs.
7. Explicar contrato e escopo antes de editar.
8. Implementar em PR draft atomico; sem ready/merge/deploy sem autorizacao.
9. Revisao separada: implementador -> revisor limpo -> gate externo.
10. Relatar `PASS / FAIL / BLOCKED / SKIP` e sempre indicar o papel do smoke.

## Cadencia dos grafos

- **CRG:** rebuild no inicio de cada worktree importante e update depois de edits.
- **Graphify estrutural:** `graphify update . --force` apos blocos relevantes.
- **Graphify semantico:** rebuild periodico quando docs/PRD mudarem bastante.
- **Fechamento:** registrar merge/deploy/smoke em `docs/sprints/`; o grafo nao
  substitui historia operacional.
