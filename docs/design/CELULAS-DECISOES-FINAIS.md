# Adendo — Decisões Finais do Módulo Células (Igreja 12)

> **Status:** Decisões **confirmadas pelo dono**. Adendo vinculante à série de PRDs e ao plano de implementação.
> **Data:** 2026-07-03.
> **Natureza:** docs-only. Nenhum código, migration, env, worker, Supabase ou deploy nesta entrega.
> **Efeito:** fecha as decisões abertas que bloqueavam o início da implementação. A partir daqui, o **PR1** pode começar.

## Fontes de verdade

1. [`docs/design/PLANO-IMPLEMENTACAO-CELULAS.md`](PLANO-IMPLEMENTACAO-CELULAS.md) — plano (decisões abertas 4.1–4.6, sequência de 10 PRs). Este adendo **resolve** as seções 3, 4 e 10 do plano.
2. [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — contrato vinculante (invariantes).
3. PRDs já em `main`: [Discípulo](PRD-MINHA-CELULA-DISCIPULO.md) · [Líder](PRD-MINHA-CELULA-LIDER.md) · [Solicitações](PRD-CELULAS-SOLICITACOES-APROVACAO.md) · [Central](PRD-CENTRAL-DE-CELULAS.md).

## 1. Objetivo do adendo

Versionar em `main` as **decisões finais** confirmadas pelo dono, para que a implementação comece sobre um alvo fechado. Este documento é o **despacho** que transforma os defaults provisórios e as perguntas abertas do plano em **regras firmes** — em especial as duas decisões estruturais (ocorrência/reunião e Solicitação/auditoria) que bloqueavam o PR2 e o PR5.

## 2. Contexto

- A **série de documentos do módulo Células está concluída** e mesclada em `main`: contrato UX/UI + PRD Discípulo + PRD Líder + PRD Solicitações & Aprovação + PRD Central + Plano de Implementação.
- O plano deixou **6 decisões abertas** (4.1–4.6), sendo **4.5** e **4.6** bloqueantes de código.
- **Este adendo fecha essas decisões** para iniciar a implementação. Nada de código nesta entrega; a implementação começa em PR próprio, depois deste adendo mesclado.

## 3. Decisões confirmadas pelo dono

### 3.1 — Papel da Central (resolve 4.1)
- **MVP:** **pastor/admin operam como Central de Células** (usa o papel já existente). São eles que aprovam/rejeitam/pedem ajuste e cadastram células.
- **Futuro:** criar papel específico **`lider_central`** (dedicado, por igreja). Fica como evolução, **fora do MVP**.
- **Segregação mantida:** quem origina uma solicitação (líder) não a aprova.

### 3.2 — Dados sensíveis (resolve 4.2 / discrepância 14.1)
- **São sensíveis:** **anfitrião, auxiliar, endereço, dia e horário.**
- **Fluxo:** o **líder solicita** a alteração; a **Central aprova antes de aplicar**. Nada muda direto.
- **Consequência:** a discrepância 14.1 (protótipo salvava anfitrião/auxiliar/endereço direto) é resolvida **a favor do contrato** — esses campos **não** são edição direta do líder. O protótipo será ajustado quando a UI for implementada (a tela real segue esta regra).
- **Contraponto (direto, sem Central):** dados leves (nome, link do grupo de WhatsApp, mensagem de convite, link da localização) e **entrada/adição de membro**.

### 3.3 — Saúde da célula (resolve 4.3)
- **v1 baseada nas últimas 10 reuniões.**
- **Critérios iniciais:** **relatório enviado**, **presença/frequência**, **visitantes** e **pendências**.
- **Fórmula sofisticada** (nota composta com pesos) fica para **evolução** (v2). A v1 exibe os sinais e ordena por saúde sem uma nota final ponderada elaborada.

### 3.4 — Célula comum ↔ Árvore Ministerial (resolve 4.4)
- A célula tem **cobertura/liderança como referência simples** (campo/FK).
- **Não misturar** célula comum com Árvore Ministerial — são conceitos separados (célula = reunião; árvore = quem lidera quem).
- **Integração profunda** (sincronização automática do organograma na multiplicação) fica para **PR futuro** (PR10, condicional).

### 3.5 — Ocorrência / reunião (resolve 4.5 — estrutural)
- **Criar entidade materializada** de reunião/ocorrência da célula (uma linha por reunião, com data/hora/tema/status).
- **Não usar reunião virtual** (calculada).
- **Destrava:** presença, expectativa de visitante, relatório, histórico e saúde. É o alicerce do PR2.

### 3.6 — Solicitação / auditoria / payload (resolve 4.6 — estrutural)
- **Criar entidade Solicitação** (genérica, extensível por `tipo`).
- **Auditoria append-only** (trilha de transições: quem, de→para status, quando, texto).
- **Payload JSONB tipado** (validado por `tipo` na aplicação).
- **A Central NÃO edita o payload antes de aprovar.** Se precisar mudar, **pede ajuste** (devolve ao líder com observação).
- **Aprovação aplica a mudança de forma transacional** (tudo-ou-nada; rollback em falha; idempotente contra duplo clique).

## 4. Impacto no plano de implementação

- **PR1 (schema/base de célula) pode iniciar** — os defaults viram regras firmes; nada mais o bloqueia.
- **PR2 destravado** pela decisão de **ocorrência materializada** (3.5).
- **PR5 destravado** pela decisão de **Solicitação + auditoria + payload JSONB tipado** (3.6).
- **PR6 (multiplicação)** herda a aprovação transacional (3.6) e a cobertura simples (3.4).
- **PR9 (saúde)** implementa a v1 dos critérios (3.3).
- **PR10 (Árvore)** permanece **condicional** — só se a integração profunda for exigida (3.4).
- **Defaults provisórios confirmados:** 4.1 (pastor/admin=Central), 4.2 (sensíveis = seguir contrato), 4.3 (saúde v1 = últimas 10 reuniões), 4.4 (cobertura simples). Deixam de ser "provisórios" e passam a ser **decisão firme de MVP**.

Sequência inalterada: **PR1 → PR2 → PR3 → PR4 → PR5 → PR6 → PR7 → PR8 → PR9 → (PR10 condicional).**

## 5. Regras que continuam fora de escopo

- **WhatsApp real** (disparo pelo agente: cobrar líder, avisar responsável/membro) — só a intenção é persistida até o fluxo estar validado.
- **Fórmula avançada de saúde** (nota composta com pesos) — v2.
- **Papel `lider_central` real** — usa pastor/admin no MVP.
- **Integração profunda com a Árvore Ministerial** — cobertura fica como referência simples; sincronização é PR futuro.
- **Edição de payload pela Central antes de aprovar** — não existe; o caminho é pedir ajuste.

## 6. Critérios para iniciar o PR1

Checklist para abrir o primeiro PR de implementação (schema/base de célula):

1. **Worktree limpo** — sem mudanças sujas de tracked files; branch/HEAD confirmados.
2. **Branch nova de `origin/main`** — não reutilizar branch de PR mesclado.
3. **Escopo = schema/base de célula** — tabelas `celula` + `celula_membro` (campos da seção 5 do plano) + políticas **RLS por `igreja_id`**; edição de dados leves pelo líder; entrada direta de membro. **Sensíveis** (anfitrião/auxiliar/endereço/dia/horário) **não** editáveis direto (seguem 3.2).
4. **Backend-first** — sem frontend no PR1, conforme o plano recomenda (back antes de front por camada); a UI da célula entra nos PRs seguintes.
5. **Migration DEV primeiro** — migration nova por **timestamp** (`scripts/new_migration.py`), aplicada e validada no Supabase **DEV** antes de qualquer PROD.
6. **Testes e RLS** — `pytest` verde; isolamento multi-tenant testado com 2 igrejas; sem regressão no stub `multiplicacoes` (que será evoluído, não recriado).

Somente com esse checklist satisfeito o PR1 deve ser aberto.

---

### Referências

- [`docs/design/PLANO-IMPLEMENTACAO-CELULAS.md`](PLANO-IMPLEMENTACAO-CELULAS.md) — plano (seções 3/4/6/7/10 resolvidas por este adendo).
- [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — contrato vinculante.
- PRDs: [Discípulo](PRD-MINHA-CELULA-DISCIPULO.md) · [Líder](PRD-MINHA-CELULA-LIDER.md) · [Solicitações](PRD-CELULAS-SOLICITACOES-APROVACAO.md) · [Central](PRD-CENTRAL-DE-CELULAS.md).
