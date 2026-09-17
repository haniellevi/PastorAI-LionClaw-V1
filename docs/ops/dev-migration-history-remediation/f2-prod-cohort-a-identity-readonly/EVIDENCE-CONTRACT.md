# Contrato de evidência um-para-um

## Separação entre membresia e identidade

A membresia responde quais 22 linhas estão no recorte. Ela usa ordinal e os
hashes congelados de version e name. A identidade responde se o payload de uma
linha corresponde, de forma única, a um candidato do catálogo. As duas decisões
não podem compartilhar a mesma prova.

Ordinal, ordem, timestamp, version, name, cardinalidade global e proximidade
temporal são proibidos como prova de identidade. Um `NAME_SECONDARY_HASH_MATCH`
continua sendo apenas sinal secundário.

## Compromisso primário

Para cada linha selecionada, o SQL calcula:

```text
SHA256(
  binding_novo || 0x1f ||
  "F2-PROD-COHORT-A-FORWARD-v1" || 0x1f ||
  cardinality(statements) || 0x1f ||
  array_to_json(statements)
)
```

O binding tem 64 hexadecimais minúsculos, é exclusivo da tentativa e nunca é
impresso. A ordem interna dos statements faz parte do payload; a ordem das
linhas do ledger não faz. O SQL aborta se statements for nulo ou vazio, ou se
dois dos 22 compromissos primários coincidirem.

Rollback e idempotency usam domínios distintos e produzem compromissos
suplementares. Eles não substituem o compromisso primário e não são publicados
em claro. Ausência é emitida apenas como estado fechado.

## Saída permitida

Por entrada:

- ordinal público da membresia;
- `md5(version)` e `md5(name)`, exclusivamente para conferir o conjunto;
- cardinalidade de statements e rollback;
- presença ou ausência de idempotency;
- compromissos SHA-256 primário e suplementares.

São proibidos valores crus de version, name, statements, rollback,
idempotency_key, created_by, conexão, binding, tenant ou dado de domínio.

## Bijeção futura

Uma reclassificação exige, em missão offline posterior:

1. produzir compromissos do catálogo com a mesma representação exata de
   statements, sem usar posição, versão, nome ou timestamp;
2. provar que cada compromisso das 22 entradas encontra exatamente um candidato;
3. provar que nenhum candidato atende a mais de uma entrada;
4. manter captura, binding e material intermediário fora do repositório;
5. obter parecer dos dois conselheiros antes de registrar qualquer conclusão.

Se a representação do catálogo não puder ser reproduzida exatamente, o
resultado é `IDENTITY_EVIDENCE_INSUFFICIENT`. Similaridade textual,
normalização ad hoc ou execução para observar efeitos não são alternativas.

## Falha fechada

O procedimento aborta por fonte, modo, hash, binding, sessão, forma do ledger,
cardinalidade, teto, statements ausente, compromisso duplicado, recibo ou alvo
divergente. Abortamento não autoriza repetição. A coleta permanece fechada até
`OWNER_AUTHORIZE_PROD_UNMATCHED_IDENTITY_EVIDENCE_READ_ONLY`.
