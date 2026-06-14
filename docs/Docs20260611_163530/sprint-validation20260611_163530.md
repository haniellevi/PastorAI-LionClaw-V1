# Relatorio de Validacao de Sprints — PastorAi-1.0 (Development Pipeline 2.0)

> Gerado pelo Sprint Validator em 2026-06-13.
> Fontes: `SPEC.md`, `sprints20260611_163530.json`, `design/design-contract.json`, `design/artifact.html`.
> Plano: 16 sprints / 45 features. Design Lock: APROVADO (13/13).

---

## 1. Regra de Design Lock (obrigatoria deste pipeline)

Verificacao: toda sprint com `touchesUI=true` precisa ter `affectedScreenIds` nao vazio (ou nota), IDs vindos do `design-contract.json` e `designArtifactPath` apontando ao artifact travado.

| Sprint | touchesUI | affectedScreenIds | IDs no contract? | designArtifactPath | Resultado |
|--------|-----------|-------------------|------------------|--------------------|-----------|
| sprint-001 | false | [] | n/a | null | [PASS] |
| sprint-002 | false | [] | n/a | null | [PASS] |
| sprint-003 | true | login, dashboard | sim | artifact.html | [PASS] |
| sprint-004 | false | [] | n/a | null | [PASS] |
| sprint-005 | false | [] | n/a | null | [PASS] |
| sprint-006 | false | [] | n/a | null | [PASS] |
| sprint-007 | false | [] | n/a | null | [PASS] |
| sprint-008 | false | [] | n/a | null | [PASS] |
| sprint-009 | true | dashboard | sim | artifact.html | [PASS] |
| sprint-010 | true | ganhar, contatos | sim | artifact.html | [PASS] |
| sprint-011 | true | celulas, g12, enviar | sim | artifact.html | [PASS] |
| sprint-012 | true | consolidar, consol-individual, universidade-vida, capacitacao | sim | artifact.html | [PASS] |
| sprint-013 | true | inbox, whatsapp | sim | artifact.html | [PASS] |
| sprint-014 | true | relatorios, central-celula, comunicados, calendario | sim | artifact.html | [PASS] |
| sprint-015 | true | equipe, permissoes, gerentes, assinatura, agente | sim | artifact.html | [PASS] |
| sprint-016 | true | dashboard, inbox, contatos, celulas, consolidar, consol-individual, ganhar, g12, enviar, agente, equipe, permissoes, assinatura | sim | artifact.html | [PASS] |

**Resultado da regra de design lock: nenhum FAIL.** Todas as sprints UI tem `affectedScreenIds` populado, todos os screenIds existem no `design-contract.json` e o `designArtifactPath` aponta ao artifact travado.

> Nota N1 (designArtifactPath): a instrucao do pipeline citou `artifact/index.html`, mas o artifact travado (com sha256 no SPEC) e `docs/Docs20260611_163530/design/artifact.html`. As sprints apontam para o arquivo correto e existente. Mantido como esta.

---

## 2. Cobertura SPEC (US-01..US-43) -> Sprints

| Story | Backend | Frontend | Status |
|-------|---------|----------|--------|
| US-01 login | sprint-002 | sprint-003 | OK |
| US-02 multi-tenant/RLS | sprint-001, sprint-002 | transversal | OK |
| US-03 gestao usuarios | sprint-008 | sprint-015 | OK |
| US-04 RBAC | sprint-002, sprint-008 | sprint-015 | OK |
| US-05/06/07 WhatsApp conexao | sprint-006 | sprint-013 | OK |
| US-08 atendimento automatico | sprint-006, sprint-007 | sprint-013 | OK |
| US-09 coleta/criacao contato | sprint-004, sprint-007 | sprint-010 | OK |
| US-10 onboarding | sprint-007 | sprint-010 | OK |
| US-11 inbox | sprint-006 | sprint-013 | OK |
| US-12/13 handoff | sprint-006 | sprint-013 | OK |
| US-14 fila humana | sprint-006 | sprint-013 | OK (ver O2) |
| US-15/16/17 dashboard | sprint-004 | sprint-009 | OK |
| US-18 visitantes s/ acompanhamento | sprint-004 | sprint-010 | OK |
| US-19 detalhe contato | sprint-004 | sprint-010 | OK |
| US-20 conectar celula | sprint-004 | sprint-010 | OK |
| US-21 cadastro celulas | sprint-004 | sprint-011 | OK |
| US-22 membros/visitantes celula | sprint-004 | sprint-011 | OK |
| US-23 alertas liderados | sprint-004 | sprint-011 | OK |
| US-24 relatorio via WhatsApp | sprint-007 | sprint-014 | OK |
| US-25 visualizar relatorios | sprint-008 | sprint-014 | OK |
| US-26 relatorio vira acao | sprint-001 (trigger) | sprint-009/014 | OK |
| US-27 credencial LLM BYO | sprint-007 | sprint-015 | OK |
| US-28 config agente | sprint-008 | sprint-015 | OK |
| US-29 crons | sprint-008 | sprint-015 | OK |
| US-30 eventos/calendario | sprint-008 | sprint-014 | OK |
| US-31 consentimento | sprint-001, sprint-007 | sprint-014 | OK |
| US-32 opt-out | (lacuna) | sprint-014 (respeita) | PARCIAL (ver O1) |
| US-33 envio segmentado | sprint-008 | sprint-014 | OK |
| US-34/35/36 assinatura | sprint-008 | sprint-015 | OK |
| US-37 lancar decisao | sprint-005 | sprint-012 | OK |
| US-38 dashboard consolidacao | sprint-005 | sprint-012 | OK |
| US-39 etapas consolidacao | sprint-005 | sprint-012 | OK |
| US-40 pendencias 24h/fonovisita | sprint-001, sprint-005 | sprint-009/012 | OK |
| US-41 assistente | sprint-007 | sprint-016 | OK |
| US-42/43 super-admin | fora de escopo (stub) | fora de escopo (stub) | OK (intencional) |

Nenhuma feature critica da SPEC esta sem sprint. Stubs (US-42/43) corretamente excluidos do painel operacional (delta-024).

---

## 3. Problemas identificados

- **O1 [Media] Opt-out (US-32 / RNF-06 / delta-040):** nenhum backend (sprint-004/006/007/008) tem criterio de aceite que *escreva* `pessoas.optout` ou registre opt-out. `comunicados` (sprint-008/014) apenas *respeita* o flag. Falta o ponto que seta o opt-out (provavel sub-agente do WhatsApp ou endpoint de contato).
- **O2 [Baixa] LGPD consent_records / termo (delta-040):** a tabela existe (sprint-001) e o sub-agente `consent` apresenta o termo (sprint-007), mas nenhum criterio cobre a *gravacao* de `consent_records` (versao + data/hora) nem o *re-aceite em nova versao*. Recomenda-se reforcar o criterio em sprint-007.
- **O3 [Baixa] Dupla reivindicacao da tela `dashboard`:** `dashboard` aparece em `affectedScreenIds` da sprint-003 (so casca/rota) e da sprint-009 (tela real). Para o cross-check de design lock isso gera ambiguidade. Recomenda-se remover `dashboard` da sprint-003 (mantendo apenas `login`) ou adicionar nota explicando que e somente a casca.
- **O4 [Baixa] Componente fora da area da SPEC (sprint-003):** `status-pill` esta em `affectedComponentIds` da sprint-003, mas a area "Autenticacao & Multi-tenant" (SPEC 4.8) lista apenas `btn-primary`, `form-field`, `sidebar-nav`. O ID e valido no contract, mas extrapola o escopo declarado da area.
- **O5 [Media] Sizing da sprint-007:** concentra Orquestrador LangGraph + sub-agentes + credencial LLM + tools + logs + assistente do painel + SLA engine + cron worker. E a sprint mais densa do plano (3 features, mas cada uma substancial). Avaliar dividir em duas (Orquestrador/WhatsApp vs Assistente+SLA/cron).

---

## 4. Dependencias e Sizing (resumo)

- Ordem geral correta: DB (001) -> backend core (002) -> dominio (004/005/006/007/008) -> frontend (003, 009-016). Cada sprint de frontend depende do backend que consome.
- sprint-016 (assistant-panel) depende corretamente de sprint-007 + todas as telas (009-015).
- Sizing geral coerente (estimativas 2-3 rounds). Atencao apenas a sprint-007 (O5).

---

## 5. Status

Usuario escolheu opcao 1 (aplicar todos). Aplicado em 2026-06-13:
- **O1 [APLICADO]** sprint-007/feat-021: novo criterio de opt-out (pessoas.optout=true via WhatsApp, exclui de comunicados — US-32/RNF-06).
- **O2 [APLICADO]** sprint-007/feat-021: novo criterio de gravacao de consent_records (termo_versao + aceite_em) e re-aceite em nova versao (delta-040).
- **O3 [APLICADO]** sprint-003/metadata: removido `dashboard` de affectedScreenIds; adicionada nota explicando que entrega so a casca/rota.
- **O4 [APLICADO]** sprint-003/metadata: removido `status-pill` de affectedComponentIds (fora da area "Autenticacao" da SPEC 4.8).
- **O5 [APLICADO]** split da sprint-007 executado (usuario confirmou opcao "a") — ver secao 6.

---

## 6. O5 — Split da sprint-007 (APLICADO em 2026-06-13)

Split executado com renumeracao completa do plano. Layout final:

- **sprint-007 (index 6):** "Agente Orquestrador (LangGraph), LLM BYO e Tools" — feat-021 + feat-022.
- **sprint-008 (index 7, NOVO):** "Assistente do Painel e Motor de SLA/Cron" — feat-023; deps [sprint-001,002,004,005,006,007]; complexity high; estimated_rounds 2.
- **sprint-008..016 antigas -> sprint-009..017** (shift +1 em id e index).
- `dependencies` atualizadas em todas as sprints que citavam sprint-008+; referencias de hints/architecture_notes do assistant-panel corrigidas (sprint-014 -> sprint-017; sprint-008 -> sprint-009).
- UI do assistente (agora sprint-017) aponta para backend do assistente (sprint-008) e telas (sprints 010-016).
- Metadados de topo: version 1->2, `updated_at` adicionado, total_sprints 16->17, total_features 45 (inalterado).

Resultado: plano final com **17 sprints / 45 features**. Todas as referencias cruzadas validadas. Nenhum FAIL de design lock remanescente.

---

## 7. Conclusao

Todos os 5 problemas (O1-O5) foram aplicados. Cobertura SPEC completa (US-01..US-43, com US-42/43 como stubs intencionais). Design lock sem FAIL. Plano aprovado para avancar.
