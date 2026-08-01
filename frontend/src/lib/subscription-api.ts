/**
 * Cliente da API de assinatura Asaas (tela #assinatura).
 * Consome o backend (sprint-009 / US-34..36):
 *
 *   GET  /subscription          -> { plano, status, ..., setupPago, invoiceUrl, setupInvoiceUrl }
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
  /** Link da fatura da mensalidade — presente enquanto pendente/vencida. */
  invoiceUrl: string | null;
  /** Link da cobrança de setup — presente só enquanto o setup não foi pago. */
  setupInvoiceUrl: string | null;
  /** Motivo da reversão da cobrança mensal atual ('deleted'|'refunded'). */
  invoiceReversal: "deleted" | "refunded" | null;
  /** Link da cobrança avulsa de recuperação mensal, quando emitida. */
  recoveryInvoiceUrl: string | null;
  /** Setup devido sem link pagável: a UI oferece gerar nova taxa. */
  setupRecoveryRequired: boolean;
  /**
   * Existe recorrência RASTREADA no Asaas. `false` = só o registro local
   * placeholder (criado antes de um POST que falhou): a igreja ainda NÃO
   * contratou. Sinal semântico explícito — a UI nunca deduz "assinante" da
   * mera existência do objeto, e o id remoto não é exposto para ela inferir.
   */
  hasTrackedSubscription: boolean;
  /** Espelho de conveniência: a tela de contratação inicial ainda é devida. */
  checkoutRequired: boolean;
}

/** Registro local sem recorrência no Asaas: contratação inicial incompleta. */
export function isPlaceholderSubscription(sub: Subscription | null): boolean {
  return sub !== null && !sub.hasTrackedSubscription;
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
  // Placeholder de checkout falho: não há assinatura para exibir estado — a
  // tela é a de contratação, exatamente como quando não existe registro algum.
  if (!sub.hasTrackedSubscription) return "plans";
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

/** Resultado das ações explícitas de recuperação de cobrança. */
export interface RecoveryResult {
  status: string;
  invoiceUrl: string | null;
  recoveryInvoiceUrl: string | null;
  setupInvoiceUrl: string | null;
}

/** Recupera a mensalidade REVERTIDA (restore da excluída ou cobrança avulsa de
 * recuperação da estornada) — nunca cria assinatura nem passa por checkout. */
export async function recoverInvoice(token: string): Promise<RecoveryResult> {
  const res = await authedFetch(token, "/subscription/recover-invoice", {
    method: "POST",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível recuperar a cobrança.");
  }
  return (await res.json()) as RecoveryResult;
}

/** Resultado da troca de plano (assinatura Asaas atualizada in-place). */
export interface ChangePlanResult {
  status: string;
  plano: PlanCode;
  precoMensal: number;
  /** Sempre "proximo_ciclo": cobranças já emitidas não mudam. */
  vigencia: string;
}

/** Troca o plano ATUALIZANDO a assinatura Asaas existente (nunca cria outra
 * recorrência). Vale a partir do próximo ciclo; não pede CPF/CNPJ. */
export async function changePlan(
  token: string,
  payload: { plano: PlanCode },
): Promise<ChangePlanResult> {
  const res = await authedFetch(token, "/subscription/change-plan", {
    method: "POST",
    body: JSON.stringify({ plano: payload.plano }),
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível mudar o plano.");
  }
  return (await res.json()) as ChangePlanResult;
}

/** (Re)emite a taxa de setup em aberto como cobrança avulsa — nunca cria
 * assinatura nem passa pelo checkout. */
export async function createSetupCharge(token: string): Promise<RecoveryResult> {
  const res = await authedFetch(token, "/subscription/setup-charge", {
    method: "POST",
  });
  if (!res.ok) {
    const detail = await readDetail(res);
    throw new ApiError(res.status, detail ?? "Não foi possível emitir a taxa de setup.");
  }
  return (await res.json()) as RecoveryResult;
}
