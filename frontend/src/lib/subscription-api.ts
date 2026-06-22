/**
 * Cliente da API de assinatura Asaas (tela #assinatura).
 * Consome o backend (sprint-009 / US-34..36):
 *
 *   GET  /subscription   -> { plano, status, pessoas, limite, proximaCobranca, setupPago }
 *   POST /subscription   -> { status, invoiceUrl, asaasSubscriptionId }   (checkout)
 *
 * O upgrade automático por porte é feito pelo trigger `trg_subscription_autoupgrade`
 * (refletido no GET). O acesso é admin-only (delta-005). Pagamento pendente não
 * libera acesso (status `pendente` => "aguardando confirmação"); inadimplente
 * exibe regularização.
 *
 * O catálogo de planos espelha `app/domain/billing.py` (fonte de verdade dos
 * limites/preços); os rótulos seguem o artifact travado. A taxa de setup é
 * design-locked (cobrada uma vez, refletida em `setupPago`).
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

/** Códigos de plano (subscriptions.plano) — escada de porte. */
export type PlanCode = "ate_100" | "101_200" | "acima_201";

/** Status normalizado da assinatura no backend. */
export type SubscriptionStatus = "ativa" | "pendente" | "inadimplente";

/** Estado de UI derivado para a tela (#assinatura). */
export type SubscriptionUiState = "active" | "pending" | "past-due" | "plans";

export interface Subscription {
  plano: PlanCode;
  status: SubscriptionStatus | null;
  pessoas: number | null;
  limite: number | null;
  proximaCobranca: string | null;
  setupPago: boolean;
}

export interface CheckoutResult {
  status: string;
  invoiceUrl: string | null;
  asaasSubscriptionId: string | null;
}

export interface PlanInfo {
  code: PlanCode;
  label: string;
  /** Limite de pessoas (null = ilimitado). */
  limite: number | null;
  /** Mensalidade em BRL. */
  preco: number;
}

/** Taxa de implantação (setup fee) — cobrada uma vez (design-locked). */
export const SETUP_FEE = 290;

/** Catálogo de planos (espelha billing.py + catálogo `planos` do PRD: 199/299/399). */
export const PLAN_CATALOG: PlanInfo[] = [
  { code: "ate_100", label: "Célula", limite: 100, preco: 199 },
  { code: "101_200", label: "Comunidade", limite: 200, preco: 299 },
  { code: "acima_201", label: "Rede", limite: null, preco: 399 },
];

export function planInfo(code: PlanCode): PlanInfo {
  return PLAN_CATALOG.find((p) => p.code === code) ?? PLAN_CATALOG[0]!;
}

/** Indica o estado de UI a partir do status da assinatura. */
export function subscriptionUiState(sub: Subscription | null): SubscriptionUiState {
  if (!sub) return "plans";
  switch (sub.status) {
    case "ativa":
      return "active";
    case "pendente":
      return "pending";
    case "inadimplente":
      return "past-due";
    default:
      return "plans";
  }
}

/** Assinatura não encontrada (404) — a igreja ainda não contratou um plano. */
export class NoSubscriptionError extends Error {
  constructor() {
    super("Assinatura não encontrada");
    this.name = "NoSubscriptionError";
  }
}

export async function fetchSubscription(token: string): Promise<Subscription> {
  const res = await authedFetch(token, "/subscription");
  if (res.status === 404) {
    throw new NoSubscriptionError();
  }
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar a assinatura.");
  }
  return (await res.json()) as Subscription;
}

export async function createCheckout(
  token: string,
  payload: { plano: PlanCode; cpfCnpj?: string },
): Promise<CheckoutResult> {
  const res = await authedFetch(token, "/subscription", {
    method: "POST",
    body: JSON.stringify({ plano: payload.plano, cpfCnpj: payload.cpfCnpj ?? null }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível iniciar o checkout.");
  }
  return (await res.json()) as CheckoutResult;
}
