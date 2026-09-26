import { describe, expect, it } from "vitest";

import { formatAiCostUsd } from "./ai-cost";

// O Intl separa símbolo e valor com espaço não quebrável.
const plain = (text: string) => text.replace(/ /g, " ");

describe("formatAiCostUsd", () => {
  it("exibe o custo em dólar, não em real", () => {
    expect(plain(formatAiCostUsd(0.03))).toBe("US$ 0,03");
  });

  it("mantém frações de centavo do custo por igreja", () => {
    expect(plain(formatAiCostUsd(0.0012))).toBe("US$ 0,0012");
  });

  it("usa duas casas em valores redondos", () => {
    expect(plain(formatAiCostUsd(1.5))).toBe("US$ 1,50");
    expect(plain(formatAiCostUsd(0))).toBe("US$ 0,00");
  });
});
