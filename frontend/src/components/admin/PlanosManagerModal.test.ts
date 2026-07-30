// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlanosManagerModal } from "./PlanosManagerModal";

const {
  createPlano,
  deletePlano,
  fetchBillingSettings,
  listPlanos,
  updateBillingSettings,
  updatePlano,
} = vi.hoisted(() => ({
  createPlano: vi.fn(),
  deletePlano: vi.fn(),
  fetchBillingSettings: vi.fn(),
  listPlanos: vi.fn(),
  updateBillingSettings: vi.fn(),
  updatePlano: vi.fn(),
}));

vi.mock("@/lib/admin-api", () => ({
  AdminSessionExpiredError: class AdminSessionExpiredError extends Error {},
  createPlano,
  deletePlano,
  fetchBillingSettings,
  listPlanos,
  updateBillingSettings,
  updatePlano,
}));

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

function render(props: Partial<Parameters<typeof PlanosManagerModal>[0]> = {}) {
  act(() => {
    root.render(
      h(PlanosManagerModal, {
        token: "master-token",
        onClose: () => {},
        onExpired: () => {},
        ...props,
      }),
    );
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
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  for (const fn of [
    createPlano,
    deletePlano,
    fetchBillingSettings,
    listPlanos,
    updateBillingSettings,
    updatePlano,
  ]) {
    fn.mockReset();
  }
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("PlanosManagerModal — cobrança do master", () => {
  it("mostra e salva a taxa padrão mesmo sem planos cadastrados", async () => {
    listPlanos.mockResolvedValue([]);
    fetchBillingSettings.mockResolvedValue({ setupFeePadrao: 59.9 });
    updateBillingSettings.mockResolvedValue({ setupFeePadrao: 75 });
    const onChanged = vi.fn();

    render({ onChanged });
    await flush();

    expect(container.textContent).toContain("Nenhum plano cadastrado.");
    const setupInput = container.querySelector<HTMLInputElement>('input[type="number"]')!;
    expect(setupInput.value).toBe("59.9");

    setValue(setupInput, "75");
    const save = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Salvar taxa padrão"),
    )!;
    act(() => save.click());
    await flush();

    expect(updateBillingSettings).toHaveBeenCalledWith("master-token", {
      setupFeePadrao: 75,
    });
    expect(onChanged).toHaveBeenCalledTimes(1);
  });
});
