// @vitest-environment jsdom
import { act, createElement as h, type ComponentType } from "react";
import { createRoot, hydrateRoot, type Root } from "react-dom/client";
import { renderToString } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resolveRootSurface } from "./public-auth-flow";
import { useHashRoute } from "./use-hash-route";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root | undefined;

function AuthSurface() {
  const [route] = useHashRoute();
  // A mesma decisão da raiz enquanto o provider ainda restaura a sessão.
  const surface = resolveRootSurface("loading", route);
  return surface === "login"
    ? h("form", { "aria-label": "Fluxo público" }, h("output", null, route))
    : h("div", { role: "status" }, "Carregando");
}

function Routes() {
  const [route, navigate] = useHashRoute();
  return h("main", null,
    h("output", null, route),
    h("button", { onClick: () => navigate("inbox") }, "Abrir conversas"),
    h("button", { onClick: () => navigate("#dashboard") }, "Abrir Hoje"),
  );
}

function serverMarkup(component: ComponentType) {
  // Fragmentos nunca chegam ao servidor; não há window na renderização SSR.
  vi.stubGlobal("window", undefined);
  try {
    return renderToString(h(component));
  } finally {
    vi.unstubAllGlobals();
  }
}

beforeEach(() => {
  root = undefined;
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  container.remove();
  window.history.replaceState(null, "", "/");
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useHashRoute: SSR e hidratação", () => {
  it.each(["redefinir-senha/token-sintetico", "ativar/token-sintetico"])(
    "hidrata acesso direto a %s sem substituir HTML por divergência",
    async (route) => {
      window.history.replaceState(null, "", `/#${route}`);
      container.innerHTML = serverMarkup(AuthSurface);
      expect(container.querySelector('[role="status"]')).not.toBeNull();
      const recoverable = vi.fn();
      await act(async () => {
        root = hydrateRoot(container, h(AuthSurface), { onRecoverableError: recoverable });
      });
      expect(container.querySelector("output")?.textContent).toBe(route);
      expect(container.querySelector('form[aria-label="Fluxo público"]')).not.toBeNull();
      expect(recoverable).not.toHaveBeenCalled();
      expect(window.location.hash).toBe(`#${route}`);
    },
  );

  it("preserva hashchange e navegação com ou sem prefixo após hidratar", async () => {
    window.history.replaceState(null, "", "/#dashboard");
    container.innerHTML = serverMarkup(Routes);
    const recoverable = vi.fn();
    await act(async () => {
      root = hydrateRoot(container, h(Routes), { onRecoverableError: recoverable });
    });
    expect(container.querySelector("output")?.textContent).toBe("dashboard");
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(window.location.hash).toBe("#inbox");
    expect(container.querySelector("output")?.textContent).toBe("inbox");
    await act(async () => {
      container.querySelectorAll<HTMLButtonElement>("button")[1]!.click();
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(window.location.hash).toBe("#dashboard");
    expect(container.querySelector("output")?.textContent).toBe("dashboard");
    await act(async () => {
      window.location.hash = "#calendario";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(container.querySelector("output")?.textContent).toBe("calendario");
    expect(recoverable).not.toHaveBeenCalled();
  });

  it("ressincroniza a mesma rota quando o histórico mudou sem hashchange", async () => {
    window.history.replaceState(null, "", "/#dashboard");
    await act(async () => {
      root = createRoot(container);
      root.render(h(Routes));
    });
    expect(container.querySelector("output")?.textContent).toBe("dashboard");

    window.history.replaceState(null, "", "/#inbox");
    expect(container.querySelector("output")?.textContent).toBe("dashboard");
    await act(async () => {
      container.querySelector<HTMLButtonElement>("button")!.click();
    });
    expect(window.location.hash).toBe("#inbox");
    expect(container.querySelector("output")?.textContent).toBe("inbox");
  });

  it("remove a assinatura de hashchange ao desmontar", async () => {
    const add = vi.spyOn(window, "addEventListener");
    const remove = vi.spyOn(window, "removeEventListener");
    await act(async () => {
      root = createRoot(container);
      root.render(h(Routes));
    });
    const subscriptions = add.mock.calls.filter(([type]) => type === "hashchange");
    expect(subscriptions).toHaveLength(1);

    await act(async () => root!.unmount());
    root = undefined;
    expect(remove).toHaveBeenCalledWith("hashchange", subscriptions[0]![1]);
  });
});
