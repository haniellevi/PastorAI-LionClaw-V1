// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { expireSession, fetchPlanCatalog, fetchSubscription, createCheckout } = vi.hoisted(() => ({
  expireSession: vi.fn(),
  fetchPlanCatalog: vi.fn(),
  fetchSubscription: vi.fn(),
  createCheckout: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "tenant-token", expireSession }),
}));

vi.mock("@/lib/subscription-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/subscription-api")>();
  return {
    ...actual,
    createCheckout,
    fetchPlanCatalog,
    fetchSubscription,
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

  it("assinante ativo consegue trocar de plano: campo CPF/CNPJ na aba de planos", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "ativa",
      pessoas: 40,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
    });
    fetchPlanCatalog.mockResolvedValue({
      setupFee: 0,
      planos: [
        { code: "ate_100", label: "Até 100 pessoas", limite: 100, preco: 199 },
        { code: "101_200", label: "101–200 pessoas", limite: 200, preco: 299 },
      ],
    });
    createCheckout.mockResolvedValue({
      status: "pendente",
      invoiceUrl: "https://asaas.test/upgrade",
      setupInvoiceUrl: null,
      asaasSubscriptionId: "sub_2",
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    // Vai para a aba de planos — onde a ação "Contratar" existe para o
    // assinante ativo — e o campo de documento precisa estar visível.
    const plansTab = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Planos por porte"),
    )!;
    act(() => plansTab.click());
    await flush();

    const cpfInput = container.querySelector<HTMLInputElement>("#subscription-cpf-cnpj");
    expect(cpfInput).not.toBeNull();
    setValue(cpfInput!, "24971563792");

    const contratar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Contratar"),
    )!;
    act(() => contratar.click());
    await flush();

    expect(createCheckout).toHaveBeenCalledWith("tenant-token", {
      plano: "101_200",
      cpfCnpj: "24971563792",
    });
  });

  it("inadimplente sem link: o fallback continua sendo o botão de regularização", async () => {
    fetchSubscription.mockResolvedValue({
      plano: "ate_100",
      status: "inadimplente",
      pessoas: 10,
      limite: 100,
      proximaCobranca: null,
      setupPago: true,
      invoiceUrl: null,
      setupInvoiceUrl: null,
    });

    act(() => root.render(h(AssinaturaScreen)));
    await flush();

    const botaoRegularizar = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Regularizar pagamento"),
    );
    expect(botaoRegularizar).toBeDefined();
    expect(createCheckout).not.toHaveBeenCalled();
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
