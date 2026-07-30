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
});
