/**
 * Semana do Histórico derivada em `America/Sao_Paulo` (P2-1 da review 2 da #221).
 *
 * A aba "Semana atual" não manda `?semana=` — quem resolve é o backend, também
 * em São Paulo. Se o Histórico usasse o fuso do NAVEGADOR, na virada da semana
 * ISO as duas abas pediriam a mesma semana: em `2026-08-03T00:30Z` o backend
 * responde `2026-W31` e um navegador em UTC calcularia `2026-W31` para o
 * histórico, em vez de `2026-W30`.
 *
 * Os instantes são passados explicitamente, então nada aqui depende do fuso nem
 * da data da máquina que roda o teste.
 */
import { describe, expect, it } from "vitest";

import { previousIsoWeekInSaoPaulo } from "./reports-api";

describe("previousIsoWeekInSaoPaulo", () => {
  it("na virada da semana ISO usa o dia civil de São Paulo, não o de UTC", () => {
    // 2026-08-03T00:30Z = domingo 02/08 21:30 em São Paulo (fim da W31), mas já
    // segunda 03/08 (W32) em UTC. Derivando pelo calendário UTC o histórico
    // pediria W31 — exatamente a semana que o backend devolve para a aba
    // "Semana atual". Em São Paulo o correto é W30.
    expect(previousIsoWeekInSaoPaulo(new Date("2026-08-03T00:30:00Z"))).toBe("2026-W30");
  });

  it("depois da meia-noite de São Paulo já conta o dia novo", () => {
    // 2026-08-03T03:30Z = segunda 03/08 00:30 em São Paulo (início da W32).
    expect(previousIsoWeekInSaoPaulo(new Date("2026-08-03T03:30:00Z"))).toBe("2026-W31");
  });

  it("meio de semana devolve a semana anterior", () => {
    // Quarta 29/07/2026 (W31) -> anterior = W30.
    expect(previousIsoWeekInSaoPaulo(new Date("2026-07-29T15:00:00Z"))).toBe("2026-W30");
  });

  it("atravessa a virada de ano ISO", () => {
    // 2027-01-07T12:00Z = quinta 07/01/2027, semana ISO 2027-W01 -> anterior
    // é a última semana de 2026 (W53).
    expect(previousIsoWeekInSaoPaulo(new Date("2027-01-07T12:00:00Z"))).toBe("2026-W53");
  });

  it("é estável para o mesmo instante, independente de quantas vezes rodar", () => {
    const instante = new Date("2026-08-03T00:30:00Z");
    expect(previousIsoWeekInSaoPaulo(instante)).toBe(previousIsoWeekInSaoPaulo(instante));
  });
});
