# Relatório de Validação de Sprints — PR2 Células

- **Data:** 2026-07-04 17:31:16
- **SPEC:** SPEC20260704_173116.md
- **Sprints:** sprints20260704_173116.json (4 sprints, 15 features)
- **Status geral:** PRONTO PARA APROVAÇÃO — C1 e C2 aplicados; Z1 mantido (S2 unificada) por decisão do usuário

## Mapa de IDs
| ID | Sprint | Features | Complexidade | Rounds |
|----|--------|----------|--------------|--------|
| S1 | Schema, Migration e Modelos SQLAlchemy | feat-001..004 | medium | 2 |
| S2 | Serviço de cálculo + endpoints de Reunião | feat-005..009 | high | 3 |
| S3 | Endpoint de Presença idempotente | feat-010..012 | high | 3 |
| S4 | Endpoint de Expectativa de Visitante | feat-013..015 | medium | 2 |

---

## 1. Cobertura (SPEC → Sprint)

| User Story (SPEC) | Domínio | Coberta por | Status |
|-------------------|---------|-------------|--------|
| US-01 Materializar próxima reunião | A | S2 (feat-008) | OK |
| US-02 Rejeitar dados insuficientes | A | S2 (feat-005/008) | OK |
| US-03 Listar reuniões | A | S2 (feat-007) | OK |
| US-04 Bloquear membro comum | A | S2 (feat-008) | OK |
| US-05 Confirmar própria presença | B | S3 (feat-011) | OK |
| US-06 Idempotência da presença | B | S3 (feat-011) | OK |
| US-07 Líder marca terceiro | B | S3 (feat-011) | OK |
| US-08 Isolamento por tenant (presença) | B | S3 (feat-010/011) | OK |
| US-09 Registrar expectativa | C | S4 (feat-014) | OK |
| US-10 Validação do payload | C | S4 (feat-013) | OK |
| US-11 Migration + RLS | D | S1 (feat-001/002) | OK |
| US-12 Cobertura pytest | D | S1/S2/S3/S4 (feat-004/009/012/015) | OK |

**Conclusão de cobertura:** Todas as 12 US da SPEC têm sprint correspondente. Nenhuma lacuna crítica de cobertura funcional.

## 2. Scope creep / Contradições

- **[C1 — CRÍTICO] Contradição no campo `project.description` do JSON.** A descrição do projeto diz: *"celula_expectativa_visitante (quantidade CHECK>=0)"*. Isso **contradiz frontalmente a SPEC** (§2.1 e Endpoint 4), que define o modelo como **NOMINAL** — `nome_visitante` NOT NULL + `observacao_oracao` opcional, **sem coluna `quantidade` e sem CHECK de quantidade**, permitindo N linhas por membro/reunião. As features das sprints (feat-013/014) estão CORRETAS (nominais), mas a descrição do projeto está desatualizada e pode induzir o Coder ao erro. **Recomendação:** corrigir a `project.description`.
- **[C2 — MENOR] Imprecisão no `project.description`.** Diz *"celula_reuniao (... unique celula_id+data)"*. O UNIQUE real da SPEC é `(igreja_id, celula_id, data, coalesce(hora,''))`. As features (feat-001) estão corretas; apenas a descrição resume de forma imprecisa. **Recomendação:** alinhar texto.

## 3. Dependências

- S1 → [] ; S2 → [S1] ; S3 → [S1, S2] ; S4 → [S1, S2, S3]
- Ordem respeita dependências reais: S2 usa modelos de S1; S3 usa router/constantes de S2; S4 usa `_get_reuniao_or_404` criado em S3.
- Sem dependências circulares. Sem dependências faltantes.
- **OK.**

## 4. Sizing

- **[Z1 — MODERADO] S2 é a sprint mais carregada:** 5 features (serviço de cálculo determinístico + parser PT-BR + 2 endpoints + registro em main.py + testes), `high`, 3 rounds — no teto de `max_rounds_per_sprint=3`. Risco de estouro. Ponto de discussão: manter ou dividir (ex.: serviço+cálculo numa sprint, endpoints noutra).
- S1 (4 feats/2 rounds), S3 (3 feats/3 rounds) e S4 (3 feats/2 rounds): dimensionamento adequado.

## 5. Critérios de aceite

- Critérios majoritariamente verificáveis por código/teste (status codes, colunas, constraints, allowlist do parser, ordenação, idempotência 200 vs 201). Boa qualidade.
- Sem critérios vagos ("funcionar bem"/"boa UX"). **OK.**

## 6. Hints e contexto

- Hints referenciam corretamente arquivos criados em sprints anteriores (ex.: S3/S4 apontam `cell_meetings.py` da S2, `_get_reuniao_or_404` da S3).
- Interfaces-chave, paths e notas de arquitetura presentes. **OK.**

---

## Itens abertos para discussão com o usuário
1. **C1 (crítico):** corrigir `project.description` — remover "quantidade CHECK>=0" e refletir modelo nominal.
2. **C2 (menor):** ajustar texto do UNIQUE de `celula_reuniao` na descrição.
3. **Z1 (moderado):** decidir se S2 permanece como está ou é dividida.

## Decisões registradas
- **C1 (crítico) — APLICADO** (2026-07-04): `project.description` corrigida. Removido "quantidade CHECK>=0"; inserido modelo NOMINAL (`nome_visitante` NOT NULL + `observacao_oracao` opcional, N linhas por membro/reunião, sem coluna `quantidade` e sem UNIQUE). Alinha com SPEC §2.1 e Endpoint 4.
- **C2 (menor) — APLICADO** (2026-07-04): `project.description` — texto do UNIQUE de `celula_reuniao` alterado para `(igreja_id, celula_id, data, coalesce(hora,''))`.
- **Z1 (moderado) — MANTIDO (opção a)** (2026-07-04): S2 permanece unificada por decisão do usuário. Sem split. Eventual estouro dos 3 rounds será tratado em execução; não compensa a coordenação extra de divisão agora.

## Conclusão
Plano validado: cobertura completa das 12 US, dependências corretas, critérios verificáveis e hints suficientes. Correções de escopo (C1/C2) aplicadas. **PLANO PRONTO PARA APROVAÇÃO.**
