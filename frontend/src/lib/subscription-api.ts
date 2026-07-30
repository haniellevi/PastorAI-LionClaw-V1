/**
 * Cliente da API de assinatura Asaas (tela #assinatura).
 * Consome o backend (sprint-009 / US-34..36):
 *
 *   GET  /subscription          -> { plano, status, pessoas, limite, proximaCobranca, setupPago }
 *   POST /subscription          -> { status, invoiceUrl, setupInvoiceUrl, asaasSubscriptionId }
 *   GET  /subscription/planos   -> { planos: PlanInfo[], setupFee }             (catálogo)
 *
 * O upgrade automático por porte é feito pelo trigger `trg_subscription_autoupgrade`
 * (refletido no GET). O acesso é admin-only (delta-005). Pagamento pendente não
 * libera acesso (status `pendente` => "aguardando confirmação"); inadimplente
 * exibe regularização.
 *
 * O catálogo de planos e a taxa de setup vêm da tabela `planos` (migration
 * 0012, editada pelo master em /admin/planos) via GET /subscription/planos —
 * não é mais um array fixo aqui, senão a edição do master não valia pro tenant.
 */

import { ApiError, authedFetch, readDetail } from "./dashboard-api";

/** Código de plano (subscriptions.plano / planos.codigo) — catálogo dinâmico
 * definido pelo master, não uma escada fixa de 3 valores. */
export type PlanCode = string;

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
  setupInvoiceUrl: string | null;
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

/** Catálogo de planos ativos + taxa de setup vigente. */
export interface PlanCatalog {
  planos: PlanInfo[];
  setupFee: number;
}

interface RawPlanoOut {
  codigo: string;
  nome: string;
  limitePessoas: number | null;
  precoMensal: number;
}

interface RawPlanCatalogOut {
  planos: RawPlanoOut[];
  setupFee: number;
}

export function planInfo(catalog: PlanInfo[], code: PlanCode): PlanInfo | undefined {
  return catalog.find((p) => p.code === code);
}

/** Catálogo de planos ATIVOS (tabela `planos`, editada pelo master) + taxa de setup. */
export async function fetchPlanCatalog(token: string): Promise<PlanCatalog> {
  const res = await authedFetch(token, "/subscription/planos");
  if (!res.ok) {
    throw new ApiError(res.status, "Não foi possível carregar o catálogo de planos.");
  }
  const data = (await res.json()) as RawPlanCatalogOut;
  return {
    setupFee: data.setupFee,
    planos: data.planos.map((p) => ({
      code: p.codigo,
      label: p.nome,
      limite: p.limitePessoas,
      preco: p.precoMensal,
    })),
  };
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
  payload: { plano: PlanCode; cpfCnpj: string },
): Promise<CheckoutResult> {
  const res = await authedFetch(token, "/subscription", {
    method: "POST",
    body: JSON.stringify({ plano: payload.plano, cpfCnpj: payload.cpfCnpj }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível iniciar o checkout.");
  }
  return (await res.json()) as CheckoutResult;
}
