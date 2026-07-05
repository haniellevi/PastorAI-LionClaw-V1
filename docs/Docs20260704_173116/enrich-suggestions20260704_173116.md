# Sugestoes de Enriquecimento — SPEC PR2 Células (Reuniões, Presença, Expectativa)

> Arquivo de memoria persistente do SPEC Enricher. Fonte de verdade sobre o status de cada item.

## FEATURE: Expectativa de Visitante (Endpoint 4)

- **E1** [APLICADO] [EXPECTATIVA VISITANTE] Ambiguidade no status code de criacao de expectativa ("201 ou 200 conforme convenção do repo").
  Opcoes: a) cravar 201 CREATED (criação real, N por membro/reunião, igual add_cell_member cells.py:520 = HTTP_201_CREATED) b) 200 c) deixar ambiguo.
  Sugestao: opcao a) - é criação real de N linhas por membro/reunião e bate com o padrão de add_cell_member. Presença permanece 200 (upsert idempotente).
  Resolucao (usuario, 2026-07-04): APROVADO opcao a. Aplicado em §3.2 (Endpoint 4 = 201 CREATED cravado, sem "ou 200"), bullet explicitando 201 (expectativa) vs 200 (presença) e assercoes esperadas nos testes, e Anexo rastreabilidade US-09.

## Ressalvas mantidas como estao (decisao do usuario)

- **E2** [REJEITADO] [REUNIAO] `hora` nullable em `celula_reuniao`. Mantido nullable future-proof — sem produtor no PR2 (materialização sempre nasce com hora). Sem alteracao.
- **E3** [REJEITADO] [SCHEMA/MIGRATION] Nome da migration `AAAAMMDD_HHMMSS_celula_pr2_reuniao_presenca_expectativa.sql`. Mantido como placeholder. Sem alteracao.
- **E4** [REJEITADO] [SCHEMA] `updated_at` gerenciado pela aplicação (sem trigger), igual ao PR1. Mantido. Sem alteracao.
- **E5** [REJEITADO] [REUNIAO] Comentário do `ON DELETE CASCADE` no modelo `CelulaReuniao`. Já exigido na SPEC (§2.1). Sem alteracao adicional.

## Status geral: SPEC PRONTA PARA APROVACAO (E1 aplicado; E2-E5 mantidos por decisao do usuario)

---

# Rodada 2 — Análise SPEC × PRD (2026-07-04)

> Nova varredura comparando a SPEC contra o PRD. PR2 é backend-only; itens de UI/design/responsividade não se aplicam.

## FEATURE: Reunião (materialização / listagem)

- **E6** [APLICADO] [REUNIÃO] Timezone da regra "se hoje é o dia mas o horário já passou, avança para a próxima semana" (RF-05) não está definido. Como `celulas.horario` é `HH:MM` sem fuso, comparar com "agora" é ambíguo (UTC vs America/Sao_Paulo). Sem fuso fixo, a materialização deixa de ser determinística perto da virada do dia/horário.
  Opções: a) Fixar `America/Sao_Paulo` (coerente com o restante do produto) b) Usar UTC c) Tornar o fuso injetável junto com o helper de data-base
  Sugestão: opção a — padronizar `America/Sao_Paulo`, mantendo o helper de data-base injetável (RNF-07) para testes.
  Resolução (usuário, 2026-07-04): APROVADO opção a. Aplicado em §3.2 (Serviço de cálculo): comparação de "hoje"/"horário já passou" usa `America/Sao_Paulo`, relógio/data-base injetável.

- **E7** [APLICADO] [REUNIÃO] `GET /cells/{cellId}/reunioes` diz "ordenadas por `data`" mas não define a DIREÇÃO (ASC/DESC) nem o desempate quando há mais de uma reunião no mesmo dia (legado com horas diferentes).
  Opções: a) `data ASC, hora ASC NULLS FIRST` (cronológico) b) `data DESC, hora DESC` (mais recentes primeiro) c) `data ASC` com desempate por `created_at`
  Sugestão: opção b — `data DESC` (telas tendem a mostrar a próxima/última reunião primeiro), desempate por `hora`. A confirmar pelo dono.
  Resolução (usuário, 2026-07-04): APROVADO. Aplicado em Endpoint 1: `ORDER BY data DESC, hora DESC NULLS LAST, id DESC`.

- **E8** [APLICADO] [REUNIÃO] `POST /cells/{cellId}/reunioes/next` descreve pré-check `SELECT` + `INSERT`, mas NÃO especifica o tratamento de CORRIDA (dois requests simultâneos calculam a mesma data e colidem no UNIQUE `(igreja_id, celula_id, data, coalesce(hora,''))`). Sem tratamento, a 2ª corrida vira `IntegrityError` → risco de HTTP 500.
  Opções: a) Espelhar a presença: capturar `IntegrityError`, `rollback`, recuperar a linha existente e retornar 200 b) Deixar propagar 500 c) `INSERT ... ON CONFLICT DO NOTHING` + `SELECT`
  Sugestão: opção a — coerente com RNF-05 (idempotência nas DUAS UNIQUE) e com o desfecho já adotado na presença. Explicitar no Endpoint 2.
  Resolução (usuário, 2026-07-04): APROVADO opção a. Aplicado em Endpoint 2: corrida → `IntegrityError`/`rollback`/recupera existente → 200; status codes reforçados (NUNCA 409/500).

- **E9** [APLICADO] [REUNIÃO] O parser PT-BR de `dia_reuniao` (RF-04) define nomes canônicos + acentos + sufixo "-feira", mas NÃO define comportamento para abreviações ("seg", "qua", "sáb"), dígitos ("2", "3"), ou texto com ruído ("toda quinta", "quinta à noite"). Como `dia_reuniao` é texto livre, isso é fonte real de 422 inesperado.
  Opções: a) Aceitar SOMENTE os 7 nomes canônicos (com/sem acento, com/sem "-feira") por match exato após normalizar; resto → 422 b) Aceitar também abreviações (seg/ter/qua/qui/sex/sab/dom) c) Match por substring dentro do texto livre
  Sugestão: opção a — regra estrita e testável; documentar a lista fechada aceita e que o resto é 422.
  Resolução (usuário, 2026-07-04): APROVADO variante — allowlist FECHADA normalizada (minúsculo, sem acento, trim, sem "-feira") = 7 nomes completos + abreviações de 3 letras (seg/ter/qua/qui/sex/sab/dom); resto → 422, sem match por substring. Aplicado em §3.2 (Serviço de cálculo).

## FEATURE: Presença

- **E10** [APLICADO] [PRESENÇA] Semântica da REMARCAÇÃO idempotente está contraditória: US-06/RF-11 falam em "upsert (não insere segunda linha)", mas BK-DEC-04 (Opção A) diz "recupera a linha existente e retorna 200". Não está definido se a 2ª marcação ATUALIZA a linha ou retorna a existente intacta — o que importa quando `origem` diverge (membro se auto-confirma `auto`, depois líder marca a mesma pessoa `lider`) e se `updated_at` é tocado.
  Opções: a) Retornar a existente SEM update (1ª vence; `origem` e `updated_at` preservados) b) Atualizar `origem`/`updated_at` (última vence) c) Não sobrescrever `origem`, mas tocar `updated_at`
  Sugestão: opção a — alinhada ao texto "recupera a existente e retorna 200"; preserva a trilha de auditoria de quem registrou primeiro. Explicitar no Endpoint 3.
  Resolução (usuário, 2026-07-04): APROVADO com CORREÇÃO — NÃO usar "primeira vence". UPSERT REAL (last-write-wins): remarcação deliberada faz UPDATE de estado/origem/updated_at (semântica US-06/RF-11); a corrida concorrente é que "recupera a existente" (BK-DEC-04, evita 500). Ambos 200. Sem máquina de estado no PR2. Aplicado em Endpoint 3 (bullet de idempotência = upsert com 3 caminhos: INSERT / UPDATE / corrida).

- **E11** [APLICADO] [PRESENÇA/EXPECTATIVA] O "vínculo ativo em `celula_membro`" precisa ser explicitamente atrelado à célula DA REUNIÃO. Como o índice único parcial garante 1 pessoa → 1 célula ativa, a pessoa pode estar ativa em OUTRA célula diferente da reunião. A SPEC não diz o que ocorre nesse caso.
  Opções: a) Exigir vínculo ativo em `reuniao.celula_id`; ativo em outra célula → 403 b) Aceitar qualquer vínculo ativo no tenant c) Exigir célula-correta só para auto-confirmação
  Sugestão: opção a — a presença é de uma reunião concreta; o vínculo deve ser na célula daquela reunião. Explicitar o predicado (`celula_membro.celula_id = reuniao.celula_id AND ativo = true`).
  Resolução (usuário, 2026-07-04): APROVADO opção a (vale p/ a própria pessoa e p/ o alvo marcado pelo líder). Aplicado em Endpoint 3 (Auth+bullet), Endpoint 4 (Auth+bullet) e Security §5.1.

- **E12** [APLICADO] [PRESENÇA/EXPECTATIVA] Não está definido se presença/expectativa podem ser registradas em reunião com `status` != `planejada` (legado importado pode ter `cancelada`/`realizada`, já que o CHECK aceita os 4 valores). Um dev precisaria decidir se bloqueia.
  Opções: a) Não checar status no PR2 (aceitar qualquer status) b) Bloquear em `cancelada` (→ 409/422) c) Bloquear em `cancelada` e `realizada`
  Sugestão: opção a — coerente com o Escopo Negativo (sem transição de status no PR2); registrar explicitamente que o status da reunião NÃO é validado nesses endpoints.
  Resolução (usuário, 2026-07-04): APROVADO opção a. Aplicado em Endpoint 3 e Endpoint 4 (bullet "Status da reunião NÃO é validado (E12)", sem máquina de estado nesta PR).

## FEATURE: Expectativa de Visitante

- **E13** [APLICADO] [EXPECTATIVA] A validação de `nomeVisitante` "não-vazio" não define: (1) se string só com espaços é rejeitada (trim antes de checar) e (2) tamanho MÁXIMO de `nomeVisitante` e de `observacaoOracao`. Sem limite, há risco de payload abusivo em coluna `text`.
  Opções: a) `nomeVisitante`: trim + ≥1 char após trim (whitespace-only → 422) + máx (ex.: 200); `observacaoOracao`: opcional + máx (ex.: 500) b) Só não-vazio literal, sem trim e sem limite c) Trim + não-vazio, sem limite máximo
  Sugestão: opção a — validar trim no Pydantic e definir limites (nome ≤ 200, observação ≤ 500); valores exatos a confirmar pelo dono.
  Resolução (usuário, 2026-07-04): APROVADO opção a — `nomeVisitante` trim + 1..200 chars (whitespace-only → 422); `observacaoOracao` ≤ 500. Aplicado em Endpoint 4 (Request Body, status codes, bullet de validação) e checklist §5.2.

## Status geral (Rodada 2): TODOS os itens E6–E13 APLICADOS na SPEC (2026-07-04). Nenhum item pendente.

