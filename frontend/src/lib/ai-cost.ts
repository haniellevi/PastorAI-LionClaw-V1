/**
 * Custo de IA do console. `ai_usage_logs.custo` é estimado em dólar pela tabela
 * de preços do provedor (backend `llm.estimate_cost`), então nunca pode ser
 * exibido como R$. Até 4 casas porque o custo por igreja costuma ficar abaixo
 * de um centavo.
 */
export function formatAiCostUsd(value: number): string {
  return value.toLocaleString("pt-BR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}
