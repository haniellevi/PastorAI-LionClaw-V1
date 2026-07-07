# Relatorio de Validacao de Sprints

- Projeto: Arquitetura-07/07- Igreja 12 (architecture-review)
- Run: 20260707_112731-2c3953
- SPEC: C1 — Seam profundo de RLS/tenant-context (decisoes D1–D5)
- Sprints: 5 sprints / 19 features (18 + 1 apos ajustes)
- Data da validacao: 2026-07-07
- Status geral: AJUSTES APLICADOS — aguardando aprovacao final do usuario

## 1. Mapa de rastreabilidade SPEC -> Sprints

| SPEC (PR / secao) | Sprint | Features | Status |
|---|---|---|---|
| PR1 — Testes + observabilidade (D5, §6/§8) | S1 (sprint-001) | feat-001..004 | COBERTO |
| PR2 — Seam tenant_session.py + listener (D1/D2/D3/D4, §4/§5.1/§8) | S2 (sprint-002) | feat-005..008 | COBERTO |
| PR3-A — deps.py + subscription.py (D1, §5.2/§6) | S3 (sprint-003) | feat-009..011 | COBERTO |
| PR3-B — worker + SLA sweep (D3/D4, §5.4/§6) | S4 (sprint-004) | feat-012..015 | COBERTO |
| PR4+ — routers restantes + destino ensure_tenant_context (§6) | S5 (sprint-005) | feat-016..018 | COBERTO |

### Rastreabilidade das decisoes do run (D1–D5)
- D1 (default scoped via provider): S2 (feat-005) + S3 (feat-009). OK
- D2 (listener after_begin): S2 (feat-006), testes T3/T6 em feat-008. OK
- D3 (igreja_id em session.info + pinning): S2 (feat-005) + S4 (feat-014 SLA por igreja). OK
- D4 (saida cross-tenant nomeada): S2 (feat-005) + S3 (feat-010) + S4 (feat-012). OK
- D5 (testes opt-in Postgres real): S1 (feat-002/003) + ativacoes T3-T6 em S2/S4. OK

### Testes T1–T6 (SPEC §8) vs sprints
- T1/T2: S1 feat-003 (baseline). OK
- T3/T5/T6: S2 feat-008. OK
- T4: S4 feat-015. OK
- Unit test_tenant_session_unit.py: S2 feat-007. OK
- Guard test conftest_rls: S1 feat-002. OK

## 2. Cobertura — conclusao
Cobertura funcional COMPLETA. Todo PR da SPEC tem sprint, toda decisao D1–D5 e rastreavel,
toda a matriz T1–T6 e o test unitario estao alocados. Sem scope creep material (feat-004
observabilidade esta autorizada pela SPEC §10 e OQ#9).

## 3. Achados — RESOLVIDOS

- G1 [Media] RESOLVIDO — Adicionada feature feat-019 em S1 (sprint-001): job de CI com
  Postgres descartavel efemero, migrations minimas (policies RLS + role authenticated +
  tabelas tenant-scoped), RLS_TEST_DATABASE_URL so nesse job, execucao com marker
  rls_integration, FALHA se T1-T6 nao executarem quando a env var esta definida, skip limpo
  offline, e reuso do guard DEV/PROD do feat-002. Sizing de S1 subiu de 2 para 3 rounds.

- G2 [Baixa/Media] RESOLVIDO — Adicionado criterio de observabilidade em feat-009 (S3, caminho
  HTTP de amostra) e em feat-013 (S4, caminho worker de amostra): liga o helper read-only do
  feat-004 num ponto minimo ligado ao seam, emitindo log/evento estruturado ao detectar perda
  de contexto / leitura cross-tenant / fallback inesperado, sem dados sensiveis, documentado
  como fonte do gatilho de rollback da SPEC §9/§10.

- G3 [Baixa] RESOLVIDO — feat-017 agora exige loteamento pequeno com limite explicito
  (max 3 routers por PR/commit) e gate por lote (T1-T6 + suite offline + testes do router do
  lote); um lote vermelho bloqueia os seguintes.

- G4 [Baixa] RESOLVIDO — Nota de arquitetura de S4 registra que a independencia de sprint-003
  e INTENCIONAL: PR3-A e PR3-B podem ser desenvolvidos em paralelo apos sprint-002, mas o
  deploy/merge de cada um deve respeitar os gates de ambos.

- Nota [informativa] — Criterios "comportamento observavel identico / mesma resposta"
  (feat-009/011/016/017) dependem de smoke test do caminho tocado; aceitavel dado o gate de
  merge da SPEC §7.4. Nao bloqueante.

## 3b. Rematriz SPEC -> Sprints -> Testes (pos-ajuste)

- PR1/D5: S1 feat-001..004 + feat-019 (CI). T1/T2 baseline (feat-003), guard (feat-002),
  observabilidade helper (feat-004), execucao real T1-T6 garantida por feat-019. OK
- PR2/D1-D4: S2 feat-005..008. Listener (feat-006), unit (feat-007), T3/T5/T6 (feat-008). OK
- PR3-A/D1: S3 feat-009..011. Observabilidade HTTP ativada (feat-009). OK
- PR3-B/D3-D4: S4 feat-012..015. Observabilidade worker ativada (feat-013), T4 (feat-015). OK
- PR4+: S5 feat-016..018. Loteamento com gate por lote (feat-017). OK
- Matriz T1-T6: T1/T2->S1, T3/T5/T6->S2, T4->S4; execucao real assegurada por feat-019 (S1).
  SEM lacuna. SEM scope creep. Rastreabilidade D1-D5 integra.

## 4. Sizing / ordem / dependencias
- Ordem PR1->PR2->PR3-A->PR3-B->PR4+ respeitada nos indices e dependencies. OK
- Sem dependencia circular. OK
- Estimativas de rounds coerentes (S2/S4 = high/3; S1/S3/S5 = 2-3). OK

## 5. Historico de edicoes no arquivo de sprints
- 2026-07-07: G1 — adicionada feat-019 (job de CI Postgres descartavel) em sprint-001.
- 2026-07-07: G1 — sprint-001 estimated_rounds 2 -> 3 (5 features agora).
- 2026-07-07: G2 — criterio de observabilidade adicionado em feat-009 (S3, HTTP amostra).
- 2026-07-07: G2 — criterio de observabilidade adicionado em feat-013 (S4, worker amostra).
- 2026-07-07: G3 — feat-017: loteamento max 3 routers/PR + gate por lote (descricao + criterios).
- 2026-07-07: G4 — nota de arquitetura de sprint-004: paralelismo intencional + respeitar gates de ambos.
- 2026-07-07: metadata.total_features 18 -> 19.
