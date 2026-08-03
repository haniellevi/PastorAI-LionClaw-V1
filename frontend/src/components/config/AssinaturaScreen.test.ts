// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const {
  expireSession,
  fetchPlanCatalog,
  fetchSubscription,
  createCheckout,
  recoverInvoice,
  createSetupCharge,
  changePlan,
} = vi.hoisted(() => ({
  expireSession: vi.fn(),
  fetchPlanCatalog: vi.fn(),
  fetchSubscription: vi.fn(),
  createCheckout: vi.fn(),
  recoverInvoice: vi.fn(),
  createSetupCharge: vi.fn(),
  changePlan: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "tenant-token", expireSession }),
}));

vi.mock("@/lib/subscription-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/subscription-api")>();
  return {
    ...actual,
    changePlan,
    createCheckout,
    createSetupCharge,
    fetchPlanCatalog,
    fetchSubscription,
    recoverInvoice,
  };
});

import { NoSubscriptionError } from "@/lib/subscription-api";
import { AssinaturaScreen } from "./AssinaturaScreen";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function setValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
  act(() => {
    setter.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  expireSession.mockReset();
  fetchPlanCatalog.mockReset();
  fetchSubscription.mockReset();
  createCheckout.mockReset();
  recoverInvoice.mockReset();
  createSetupCharge.mockReset();
  changePlan.mockReset();
  fetchSubscription.mockRejectedValue(new NoSubscriptionError());
  fetchPlanCatalog.mockResolvedValue({
    setupFee: 59.9,
    planos: [{ code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 }],
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("AssinaturaScreen — links do checkout", () => {
  it("mostra a taxa congelada no contrato mesmo se o catálogo mudou", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: false,
      setupFeeContracted: 59.9,
      invoiceUrl: null,
      setupInvoiceUrl: "https://asaas.test/setup",
      invoiceReversal: null,
      recoveryInvoiceUrl: null,
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 0,
      planos: [{ code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 }],
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const detalhes = [...container.querySelectorAll(".config-row")].find((row) =>
      row.textContent?.includes("Taxa de setup"),
    );
    expect(detalhes?.textContent).toContain("R$ 60");
    expect(detalhes?.textContent).not.toContain("R$ 0");
  });

  it("exibe links separados de mensalidade e setup depois da contratação", async () => {
    createCheckout.mockResolvedValue({
      status: "pendente",
      invoiceUrl: "https://asaas.test/mensalidade",
      setupInvoiceUrl: "https://asaas.test/setup",
      asaasSubscriptionId: "sub_1",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    setValue(container.querySelector<HTMLInputElement>("#subscription-cpf-cnpj")!, "24971563792");
    const contratar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Contratar"),
    )!;
    act(() => contratar.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "ate_100",
      cpfCnpj: "24971563792",
    });
    const monthly = [...container.querySelectorAll("a")].find((link) =>
      link.textContent?.includes("Pagar mensalidade"),
    );
    const setup = [...container.querySelectorAll("a")].find((link) =>
      link.textContent?.includes("Pagar taxa de setup"),
    );
    expect(monthly?.getAttribute("href")).toBe("https://asaas.test/mensalidade");
    expect(setup?.getAttribute("href")).toBe("https://asaas.test/setup");
  });

  it("reconstrói o painel de cobranças ao carregar uma assinatura pendente (reload)", async () => {
    // Simula o reload: nenhum checkout nesta sessão — os links vêm apenas do
    // GET /subscription, persistidos no backend.
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "pendente",
      pessoas: 0,
      limite: 100,
      proximaCobranca: null,
      setupPago: false,
      invoiceUrl: "https://asaas.test/mensalidade-persistida",
      setupInvoiceUrl: "https://asaas.test/setup-persistido",
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const monthly = [...container.querySelectorAll("a")].find((link) =>
      link.textContent?.includes("Pagar mensalidade"),
    );
    const setup = [...container.querySelectorAll("a")].find((link) =>
      link.textContent?.includes("Pagar taxa de setup"),
    );
    expect(monthly?.getAttribute("href")).toBe("https://asaas.test/mensalidade-persistida");
    expect(setup?.getAttribute("href")).toBe("https://asaas.test/setup-persistido");
    expect(createCheckout).not.toHaveBeenCalled();
    // O CPF/CNPJ não reaparece depois do checkout (não é persistido nem exibido).
    expect(container.querySelector("#subscription-cpf-cnpj")).toBeNull();
  });

  it("inadimplente com link persistido: Regularizar abre a fatura atual, sem novo checkout", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "inadimplente",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: "https://asaas.test/m2-overdue",
      setupInvoiceUrl: null,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const regularizar = [...container.querySelectorAll("a")].find((link) =>
      link.textContent?.includes("Regularizar pagamento"),
    );
    expect(regularizar?.getAttribute("href")).toBe("https://asaas.test/m2-overdue");
    // Nenhum botão de regularização dispara checkout quando o link existe —
    // um novo checkout criaria OUTRA assinatura recorrente no Asaas.
    const botaoRegularizar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Regularizar pagamento"),
    );
    expect(botaoRegularizar).toBeUndefined();
    expect(createCheckout).not.toHaveBeenCalled();
  });

  it("assinante ativo muda de plano com confirmação — sem CPF e sem checkout", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 40,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: null,
      recoveryInvoiceUrl: null,
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 0,
      planos: [
        { code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 },
        { code: "101_200", label: "101–200 pessoas", limite: 200, preco: 299 },
      ],
    });
    changePlan.mockResolvedValue({
      status: "ativa",
      plano: "101_200",
      precoMensal: 299,
      vigencia: "proximo_ciclo",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const plansTab = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Planos por porte"),
    )!;
    act(() => plansTab.click());
    await flush();

    // Assinante NÃO vê "Contratar" nem o campo de documento — a troca
    // atualiza a assinatura existente.
    expect(container.querySelector("#subscription-cpf-cnpj")).toBeNull();
    expect(
      [...container.querySelectorAll("button")].some((b) =>
        b.textContent?.includes("Contratar"),
      ),
    ).toBe(false);

    const mudar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Mudar plano"),
    )!;
    act(() => mudar.click());
    await flush();

    // Confirmação mostra plano/preço e a vigência no próximo ciclo.
    expect(container.textContent).toContain("Confirmar mudança de plano?");
    expect(container.textContent).toContain("101–200 pessoas");
    expect(container.textContent).toContain("Válido a partir do próximo ciclo");

    const confirmar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Confirmar mudança"),
    )!;
    act(() => confirmar.click());
    await flush();

    expect(changePlan).toHaveBeenCalledWith("tenant-token", { plano: "101_200" });
    expect(createCheckout).not.toHaveBeenCalled();
  });

  it("estado com pendência bloqueia a troca de plano", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 40,
      limite: 100,
      proximaCobranca: null,
      setupPago: false, // setup devido => troca bloqueada
      invoiceUrl: null,
      setupInvoiceUrl: "https://asaas.test/setup",
      invoiceReversal: null,
      recoveryInvoiceUrl: null,
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 59.9,
      planos: [
        { code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 },
        { code: "101_200", label: "101–200 pessoas", limite: 200, preco: 299 },
      ],
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const plansTab = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Planos por porte"),
    )!;
    act(() => plansTab.click());
    await flush();

    const mudar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Mudar plano"),
    )!;
    expect(mudar.disabled).toBe(true);
    expect(container.textContent).toContain(
      "Regularize as cobranças pendentes",
    );
    expect(changePlan).not.toHaveBeenCalled();
  });

  it("mensalidade REVERTIDA usa a ação específica de recuperação, nunca createCheckout", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "inadimplente",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: "refunded",
      recoveryInvoiceUrl: null,
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });
    recoverInvoice.mockResolvedValue({
      status: "inadimplente",
      invoiceUrl: null,
      recoveryInvoiceUrl: "https://asaas.test/recovery",
      setupInvoiceUrl: null,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const recuperar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Recuperar cobrança"),
    )!;
    expect(recuperar).toBeDefined();
    act(() => recuperar.click());
    await flush();

    expect(recoverInvoice).toHaveBeenCalledTimes(1);
    expect(createCheckout).not.toHaveBeenCalled();
  });

  it("cobrança de regularização emitida vira link direto no aviso de atraso", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "inadimplente",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: "refunded",
      recoveryInvoiceUrl: "https://asaas.test/recovery",
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const link = [...container.querySelectorAll("a")].find((a) =>
      a.textContent?.includes("Pagar cobrança de regularização"),
    );
    expect(link?.getAttribute("href")).toBe("https://asaas.test/recovery");
    expect(createCheckout).not.toHaveBeenCalled();
    expect(recoverInvoice).not.toHaveBeenCalled();
  });

  it("ciclo atual ativo ainda mostra a regularização anterior que bloqueia acesso", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: null,
      recoveryInvoiceUrl: "https://asaas.test/recovery-anterior",
      recoveryRequired: true,
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const link = [...container.querySelectorAll("a")].find((a) =>
      a.textContent?.includes("Pagar cobrança de regularização"),
    );
    expect(link?.getAttribute("href")).toBe("https://asaas.test/recovery-anterior");
    expect(container.textContent).toContain("Regularização anterior pendente");
    expect(container.textContent).not.toContain("Trocar para");
    expect(createCheckout).not.toHaveBeenCalled();
    expect(changePlan).not.toHaveBeenCalled();
  });

  it("dívida antiga reaberta sem link oferece gerar a cobrança explicitamente", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: null,
      recoveryInvoiceUrl: null,
      recoveryRequired: true,
      setupRecoveryRequired: false,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });
    recoverInvoice.mockResolvedValue({
      status: "ativa",
      invoiceUrl: null,
      recoveryInvoiceUrl: "https://asaas.test/recovery-reemitida",
      setupInvoiceUrl: null,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();
    const action = [...container.querySelectorAll("button")].find((b) =>
      b.textContent?.includes("Gerar cobrança de regularização"),
    );
    expect(action).toBeDefined();
    act(() => action!.click());
    await flush();

    expect(recoverInvoice).toHaveBeenCalledWith("tenant-token");
    expect(createCheckout).not.toHaveBeenCalled();
  });

  it("setup em aberto sem cobrança: 'Gerar nova taxa de setup' emite sem checkout e bloqueia clique duplo", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: false,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: null,
      recoveryInvoiceUrl: null,
      setupRecoveryRequired: true,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });
    let resolveCharge: (value: unknown) => void = () => {};
    createSetupCharge.mockReturnValue(
      new Promise((resolve) => {
        resolveCharge = resolve;
      }),
    );

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const gerar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Gerar nova taxa de setup"),
    )!;
    expect(gerar).toBeDefined();
    act(() => gerar.click());
    await flush();

    // Em andamento: botão desabilitado — clique duplo não dispara segunda emissão.
    const emitindo = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Emitindo…"),
    )!;
    expect(emitindo.disabled).toBe(true);
    act(() => emitindo.click());
    await flush();
    expect(createSetupCharge).toHaveBeenCalledTimes(1);
    expect(createCheckout).not.toHaveBeenCalled();

    resolveCharge({
      status: "ativa",
      invoiceUrl: null,
      recoveryInvoiceUrl: null,
      setupInvoiceUrl: "https://asaas.test/setup-novo",
    });
    await flush();
  });

  it("inadimplente sem link retoma a fatura rastreada sem exigir documento", async () => {
    createCheckout.mockResolvedValue({
      status: "inadimplente",
      invoiceUrl: "https://asaas.test/m2-recuperada",
      setupInvoiceUrl: null,
      asaasSubscriptionId: "sub_asaas_1",
    });
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "inadimplente",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const botaoRegularizar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Regularizar pagamento"),
    );
    expect(botaoRegularizar).toBeDefined();
    expect(container.querySelector("#subscription-cpf-cnpj")).toBeNull();

    act(() => botaoRegularizar!.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "ate_100",
    });
  });

  it("assinatura pendente sem links ainda mostra o painel com o aviso do Asaas", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "pendente",
      pessoas: 0,
      limite: 100,
      proximaCobranca: null,
      setupPago: false,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      hasTrackedSubscription: true,
      checkoutRequired: false,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    expect(container.textContent).toContain("Conclua as cobranças");
    expect(container.textContent).toContain(
      "Os links ainda estão sendo preparados pelo Asaas.",
    );
    expect(createCheckout).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// REVIEW-10 P1: checkout inicial que falha ANTES de rastrear a assinatura
// deixa um placeholder no backend. Sem um sinal semântico, a tela tratava esse
// registro como assinante: escondia o CPF/CNPJ, marcava "Plano atual" e
// desabilitava as ações — o usuário ficava sem nenhuma forma de retomar.
// ---------------------------------------------------------------------------
describe("AssinaturaScreen — placeholder de checkout falho", () => {
  function placeholder(over: Record<string, unknown> = {}) {
    return {
      plano: "ate_100",
      status: null,
      pessoas: null,
      limite: null,
      proximaCobranca: null,
      setupPago: false,
      invoiceUrl: null,
      setupInvoiceUrl: null,
      invoiceReversal: null,
      recoveryInvoiceUrl: null,
      setupRecoveryRequired: false,
      // Registro local existe, mas NÃO há recorrência no Asaas.
      hasTrackedSubscription: false,
      checkoutRequired: true,
      ...over,
    };
  }

  function textos(seletor: string) {
    return [...container.querySelectorAll(seletor)].map((el) => el.textContent ?? "");
  }

  it("após reload mostra CPF/CNPJ, nenhum 'Plano atual' e a retomada", async () => {
    fetchSubscription.mockResolvedValue(placeholder());
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 59.9,
      planos: [
        { code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 },
        { code: "101_200", label: "101–200 pessoas", limite: 200, preco: 299 },
      ],
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    // 1) CPF/CNPJ continua visível — o checkout ainda precisa acontecer.
    expect(container.querySelector("#subscription-cpf-cnpj")).not.toBeNull();
    // 2) Nada de "Plano atual" para um plano que nunca foi contratado.
    expect(container.textContent).not.toContain("Plano atual");
    // 3) Existe ação de retomada, e nenhuma de troca de plano.
    const botoes = textos("button");
    expect(botoes.some((t) => t.includes("Retomar contratação"))).toBe(true);
    expect(botoes.some((t) => t.includes("Mudar plano"))).toBe(false);
    // 6) Nenhuma UI de assinatura ativa.
    expect(container.textContent).not.toContain("Aguardando confirmação");
    expect(container.textContent).not.toContain("Em atraso");
  });

  it("retomar o mesmo plano chama createCheckout, nunca changePlan", async () => {
    fetchSubscription.mockResolvedValue(placeholder());
    createCheckout.mockResolvedValue({
      status: "pendente",
      invoiceUrl: "https://asaas.test/m1",
      setupInvoiceUrl: null,
      asaasSubscriptionId: "sub_1",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    setValue(container.querySelector<HTMLInputElement>("#subscription-cpf-cnpj")!, "24971563792");
    const retomar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retomar contratação"),
    )!;
    act(() => retomar.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "ate_100",
      cpfCnpj: "24971563792",
    });
    expect(changePlan).not.toHaveBeenCalled();
  });

  it("escolher outro plano ativo também passa pelo checkout", async () => {
    fetchSubscription.mockResolvedValue(placeholder());
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 59.9,
      planos: [
        { code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 },
        { code: "101_200", label: "101–200 pessoas", limite: 200, preco: 299 },
      ],
    });
    createCheckout.mockResolvedValue({
      status: "pendente",
      invoiceUrl: "https://asaas.test/m1",
      setupInvoiceUrl: null,
      asaasSubscriptionId: "sub_2",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    setValue(container.querySelector<HTMLInputElement>("#subscription-cpf-cnpj")!, "24971563792");
    const contratar = [...container.querySelectorAll("button")].find(
      (button) => button.textContent?.trim() === "Contratar",
    )!;
    act(() => contratar.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "101_200",
      cpfCnpj: "24971563792",
    });
    expect(changePlan).not.toHaveBeenCalled();
  });

  it("plano salvo fora do catálogo ativo ainda oferece retomada", async () => {
    fetchSubscription.mockResolvedValue(placeholder({ plano: "101_200" }));
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 59.9,
      planos: [{ code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 }],
    });
    createCheckout.mockResolvedValue({
      status: "pendente",
      invoiceUrl: "https://asaas.test/m1",
      setupInvoiceUrl: null,
      asaasSubscriptionId: "sub_3",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    setValue(container.querySelector<HTMLInputElement>("#subscription-cpf-cnpj")!, "24971563792");
    const retomar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retomar contratação"),
    )!;
    expect(retomar).toBeDefined();
    act(() => retomar.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "101_200",
      cpfCnpj: "24971563792",
    });
  });

  it("catálogo ativo vazio não esconde a retomada da intenção congelada", async () => {
    fetchSubscription.mockResolvedValue(placeholder({ plano: "101_200" }));
    fetchPlanCatalog.mockResolvedValue({ setupFee: 59.9, planos: [] });
    createCheckout.mockResolvedValue({
      status: "pendente",
      invoiceUrl: "https://asaas.test/m1",
      setupInvoiceUrl: null,
      asaasSubscriptionId: "sub_4",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    expect(container.textContent).toContain("Nenhum plano disponível no momento.");
    expect(container.querySelector("#subscription-cpf-cnpj")).not.toBeNull();
    setValue(container.querySelector<HTMLInputElement>("#subscription-cpf-cnpj")!, "24971563792");
    const retomar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Retomar contratação"),
    )!;
    expect(retomar).toBeDefined();
    act(() => retomar.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "101_200",
      cpfCnpj: "24971563792",
    });
    expect(changePlan).not.toHaveBeenCalled();
  });

  it("assinatura RASTREADA mantém a troca de plano in-place", async () => {
    fetchSubscription.mockResolvedValue(
      placeholder({
        status: "ativa",
        setupPago: true,
        pessoas: 10,
        limite: 100,
        hasTrackedSubscription: true,
        checkoutRequired: false,
      }),
    );
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 0,
      planos: [
        { code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 },
        { code: "101_200", label: "101–200 pessoas", limite: 200, preco: 299 },
      ],
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    // Assinante abre na visão geral; a tabela de planos vive na outra aba.
    const abaPlanos = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Planos por porte"),
    )!;
    act(() => abaPlanos.click());
    await flush();

    const botoes = textos("button");
    expect(botoes.some((t) => t.includes("Mudar plano"))).toBe(true);
    expect(botoes.some((t) => t.includes("Retomar contratação"))).toBe(false);
    expect(container.textContent).toContain("Plano atual");
    // Assinante não vê o campo de documento (a troca não passa por checkout).
    expect(container.querySelector("#subscription-cpf-cnpj")).toBeNull();
  });
});
