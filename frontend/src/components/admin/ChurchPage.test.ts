// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdminAuthError,
  AdminRequestError,
  AdminSessionExpiredError,
} from "@/lib/admin-api";

import { ChurchPage } from "./ChurchPage";

const api = vi.hoisted(() => ({
  fetchIgrejaDetail: vi.fn(),
  fetchIgrejaAdmins: vi.fn(),
  fetchIgrejaAgente: vi.fn(),
  fetchIgrejaConsentGovernance: vi.fn(),
}));

vi.mock("@/lib/admin-api", () => {
  class MockAdminAuthError extends Error {
    readonly kind: "forbidden" | "network";
    constructor(kind: "forbidden" | "network", message: string) {
      super(message);
      this.kind = kind;
    }
  }
  class MockAdminRequestError extends Error {
    readonly status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  class MockAdminSessionExpiredError extends Error {}
  return {
    ...api,
    AdminAuthError: MockAdminAuthError,
    AdminRequestError: MockAdminRequestError,
    AdminSessionExpiredError: MockAdminSessionExpiredError,
    addIgrejaAdmin: vi.fn(),
    aprovarIgreja: vi.fn(),
    deleteIgreja: vi.fn(),
    fetchIgrejaAgenteRequests: vi.fn(),
    fetchOrquestrador: vi.fn(),
    removeIgrejaAdmin: vi.fn(),
    resendAdminInvite: vi.fn(),
    resetIgrejaAgente: vi.fn(),
    resolveAgenteRequest: vi.fn(),
    saveIgrejaAgente: vi.fn(),
    setIgrejaDono: vi.fn(),
    updateIgreja: vi.fn(),
  };
});

vi.mock("./ConsentGovernanceDraftTab", () => ({
  ConsentGovernanceDraftTab: () => h("div", { "data-testid": "governance-tab" }, "Governança draft"),
}));

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function flush() {
  return act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) =>
    button.textContent?.includes(label),
  );
}

const ENABLED_GOVERNANCE = {
  enabled: true,
  initialized: false,
  schemaVersion: "d2b2b3a/governance-draft/v1",
  revision: 0,
  purposes: [],
};

function render(onExpired = vi.fn()) {
  act(() => {
    root.render(
      h(ChurchPage, {
        igreja: {
          id: "igreja-1",
          nome: "Igreja de teste",
          status: "ativa",
          plano: null,
          setupFeeOverride: null,
          membros: 0,
          pessoas: 0,
          createdAt: null,
        },
        token: "tok",
        onBack: () => {},
        onExpired,
        onChanged: () => {},
        onDeleted: () => {},
      }),
    );
  });
  return { onExpired };
}

beforeEach(() => {
  Object.values(api).forEach((mock) => mock.mockReset());
  api.fetchIgrejaDetail.mockResolvedValue({
    id: "igreja-1",
    nome: "Igreja de teste",
    status: "ativa",
    plano: null,
    createdAt: null,
    mensalidade: null,
    setupFeeOverride: null,
    setupFeeAplicavel: 0,
    membros: 0,
    pessoas: 0,
    celulas: 0,
    custoIa: 0,
    tokensIa: 0,
    assinatura: null,
  });
  api.fetchIgrejaAdmins.mockResolvedValue([]);
  api.fetchIgrejaAgente.mockResolvedValue(null);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ChurchPage governança", () => {
  it("exibe a aba somente depois de o backend responder enabled=true", async () => {
    api.fetchIgrejaConsentGovernance.mockResolvedValue(ENABLED_GOVERNANCE);
    render();

    expect(container.textContent).not.toContain("Governança");
    await flush();

    const tab = [...container.querySelectorAll<HTMLButtonElement>("[role='tab']")].find(
      (button) => button.textContent === "Governança",
    );
    expect(tab).toBeDefined();
    expect(tab?.getAttribute("aria-controls")).toBe("church-panel-governanca");
    expect(tab?.tabIndex).toBe(-1);
    act(() => tab!.click());
    expect(container.querySelector("[data-testid='governance-tab']")).not.toBeNull();
    expect(tab?.getAttribute("aria-selected")).toBe("true");
    expect(container.querySelector("#church-panel-governanca")?.getAttribute("role")).toBe(
      "tabpanel",
    );
  });

  it("mantém a aba oculta sem banner quando a função está desabilitada", async () => {
    api.fetchIgrejaConsentGovernance.mockResolvedValue({
      enabled: false,
      initialized: false,
      schemaVersion: "d2b2b3a/governance-draft/v1",
      revision: 0,
      purposes: [],
    });
    render();
    await flush();

    expect(container.textContent).not.toContain("Governança");
    expect(findButton("Tentar novamente")).toBeUndefined();
  });

  it("carrega os dados principais sem aguardar a descoberta da governança", async () => {
    const governance = deferred<typeof ENABLED_GOVERNANCE>();
    api.fetchIgrejaConsentGovernance.mockReturnValue(governance.promise);
    render();
    await flush();

    const membersCard = [...container.querySelectorAll<HTMLElement>(".card")].find(
      (card) => card.textContent?.includes("Membros (painel)"),
    );
    expect(membersCard?.textContent).toContain("0");
    expect(membersCard?.textContent).not.toContain("…");

    governance.resolve(ENABLED_GOVERNANCE);
    await flush();
  });

  it("mostra 403 sanitizado, mantém a aba oculta e oferece retry", async () => {
    api.fetchIgrejaConsentGovernance.mockRejectedValue(
      new AdminAuthError("forbidden", "detalhe interno que não deve aparecer"),
    );
    render();
    await flush();

    expect(container.textContent).toContain("Acesso à governança desta igreja foi negado.");
    expect(container.textContent).not.toContain("detalhe interno");
    expect(findButton("Tentar novamente")).toBeDefined();
    expect(container.querySelector("#church-tab-governanca")).toBeNull();
  });

  it("mostra 500 sanitizado sem derrubar os dados principais", async () => {
    api.fetchIgrejaConsentGovernance.mockRejectedValue(
      new AdminRequestError(500, "stack e segredo internos"),
    );
    render();
    await flush();

    expect(container.textContent).toContain("A governança está temporariamente indisponível.");
    expect(container.textContent).not.toContain("stack e segredo");
    expect(container.textContent).toContain("Membros (painel)");
    expect(findButton("Tentar novamente")).toBeDefined();
  });

  it("permite retry depois de falha de rede e só então revela a aba", async () => {
    api.fetchIgrejaConsentGovernance
      .mockRejectedValueOnce(new AdminAuthError("network", "token em mensagem técnica"))
      .mockResolvedValueOnce(ENABLED_GOVERNANCE);
    render();
    await flush();

    expect(container.textContent).toContain("temporariamente indisponível");
    expect(container.textContent).not.toContain("token em mensagem técnica");
    expect(container.querySelector("#church-tab-governanca")).toBeNull();

    act(() => findButton("Tentar novamente")!.click());
    await flush();

    expect(api.fetchIgrejaConsentGovernance).toHaveBeenCalledTimes(2);
    expect(container.querySelector("#church-tab-governanca")).not.toBeNull();
  });

  it("encaminha 401 da descoberta da função para expiração da sessão", async () => {
    api.fetchIgrejaConsentGovernance.mockRejectedValue(new AdminSessionExpiredError());
    const { onExpired } = render();
    await flush();

    expect(onExpired).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toContain("Governança");
  });
});
