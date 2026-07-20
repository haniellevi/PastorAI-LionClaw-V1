> SUPERADO por docs/audits/2026-07-18-project-source-of-truth.md

# Igreja 12 - fonte de verdade de produto e codigo

**Data-base:** 2026-07-10
**Commit auditado:** `ac6f706fae7297185cbf2ef4ef4e265d8cb69240` (`origin/main`)
**Objetivo:** orientar as proximas missoes sem depender de chats antigos ou grafos desatualizados.

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

### Concluido

- Seam RLS/tenant-context completo: PRs #123, #124, #125 e #126.
- Guardas de lider e gestao de celula: PRs #130 e #132.
- Vinculo canonico `celula_membro`: PR #134.
- UX Pessoas/CSIM e paginacao completa: PR #136.
- Pessoas e Comunicacao em superficie admin-only: PR #137.
- Billing lendo o catalogo de `planos`: PR #140; grant de `dono_id`: PR #141.
- Setup/onboarding 7B: PR #142; fechamento documental: PR #143.
- Pausa da IA para CSIM e respeito a `AgentConfig.ativo`: PR #139.
- SEC-3B reset token single-use: PR #135.
- Idempotencia SLA/autoupgrade (SEC-4): PR #144.
- Sugestoes do assistente respeitam telas admin-only: PR #145.
- Fila admin da igreja -> master para configuracao do agente: migration aplicada
  em DEV e PROD, RLS/policy/indice validados e smoke funcional confirmado.

### Em desenvolvimento, fora desta baseline

- **M7B-W1 - identidade WhatsApp e classificacao de membro.** A branch de trabalho
  corrige pessoas com vinculo ativo de celula que ainda aparecem como `contato`
  e adiciona saudacao nominal confiavel. Nao considerar concluido ate PR, migration,
  deploy e smoke.

## Backlog priorizado

### P0 - fechar antes de ampliar o piloto

1. **M7B-W1 - identidade WhatsApp**
   - promover `contato`/`visitante` para `membro` ao criar vinculo ativo;
   - preservar tipos superiores;
   - backfill idempotente;
   - reutilizar a mesma Pessoa depois de apagar apenas a conversa;
   - saudar pelo nome cadastrado quando confiavel.

2. **M7B-W2 - desligamento seguro de pessoa**
   - separar "apagar historico da conversa" de "desligar pessoa";
   - inventariar celula, lideranca, acesso ao painel, consolidacao e atribuicoes;
   - bloquear desligamento enquanto houver vinculos ativos;
   - apresentar os vinculos que precisam ser encerrados;
   - preferir arquivamento auditavel a hard delete cotidiano.

3. **WhatsApp -> Ganhar -> Consolidar**
   - entrevista estruturada do primeiro contato;
   - classificacao de visitante, CSIM e necessidade pastoral;
   - encaminhamento humano e abertura do fluxo correto;
   - nenhum vinculo ministerial criado apenas por autodeclaracao.

### P1 - operacao da igreja

4. **Visitante de celula -> Pessoa/Ganhar**
   - cadastro com telefone e identidade canonica;
   - decisao por Jesus e encaminhamento para consolidacao;
   - evitar visitante solto apenas em relatorio de reuniao.

5. **Agenda em go-live**
   - revisar CRUD e sincronizacao Google;
   - decidir e ativar notificacoes somente apos recipients e smokes;
   - exibir proximos eventos para cada pessoa.

6. **Papeis e permissoes**
   - CRUD de papeis ainda nao esta fechado;
   - manter autorizacao real no backend, nunca somente menu oculto;
   - validar combinacao de papeis acumulados por tenant.

### P2 - expansao apos o piloto

7. Celulas avancadas: programacao, materiais, tags, comunicacao e operacao da Central.
8. Arvore ministerial/organograma separada da celula comum.
9. Memoria/RAG do agente somente depois dos fluxos transacionais estarem estaveis.
10. Redesign amplo somente depois dos fluxos funcionais e papeis estarem fechados.

## Trilha paralela de seguranca

- Usar `docs/security/2026-07-08-seg-igreja12-remediation-plan.md` como inventario.
- Nao assumir que o nome SEC-4 fecha todos os achados historicos: o PR #144 cobre
  especificamente idempotencia de SLA/autoupgrade.
- Revalidar findings restantes contra a `main` atual antes de abrir nova correcao.
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

## Evidencia do refresh de 2026-07-10

- CRG: 382 arquivos, 4.117 nos, 33.247 arestas.
- Graphify: 6.960 nos, 16.991 relacoes, 673 comunidades.
- Migrations representadas no Graphify: 46 arquivos / 80 nos.
- Benchmark Graphify: reducao estimada de 81x por consulta.
- Graphify package/skills atualizados para 0.9.12 em Codex, Claude Code e
  Antigravity.
