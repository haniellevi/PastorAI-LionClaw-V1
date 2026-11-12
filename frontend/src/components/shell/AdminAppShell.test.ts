// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const screenState = vi.hoisted(() => ({
  props: null as null | { route: string; param?: string | null },
}));
const authState = vi.hoisted(() => ({
  user: { roles: ["admin"], isOwner: true } as null | { roles: string[]; isOwner: boolean },
}));
const preloadScreenModule = vi.hoisted(() => vi.fn());
const failedChunk = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: authState.user,
    logout: vi.fn(),
  }),
}));
vi.mock("./screen-loaders", () => ({ preloadScreenModule }));
vi.mock("@/components/config/EquipeScreen", () => {
  failedChunk();
  throw new Error("Synthetic chunk unavailable");
});

vi.mock("./ScreenView", () => ({
  ScreenView: (props: { route: string; param?: string | null }) => {
    screenState.props = props;
    return null;
  },
}));

// Dispatch browser events through the shell's public Sidebar contract. Include
// invalid targets to prove that the shell also validates speculative requests.
vi.mock("./Sidebar", () => ({
  Sidebar: ({ onPreload }: { onPreload?: (target: string) => void }) =>
    h(
      "nav",
      null,
      ["setup", "equipe", "assinatura", "perfil", "inbox", "unknown"].map((target) =>
        h(
          "a",
          {
            key: target,
            href: `#${target}`,
            onMouseEnter: () => onPreload?.(target),
            onFocus: () => onPreload?.(target),
            onPointerDown: () => onPreload?.(target),
          },
          target,
        ),
      ),
    ),
}));
vi.mock("./Topbar", () => ({ Topbar: () => null }));

const { AdminAppShell } = await import("./AdminAppShell");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  authState.user = { roles: ["admin"], isOwner: true };
  screenState.props = null;
  Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
  Object.defineProperty(navigator, "connection", { configurable: true, value: undefined });
  window.location.hash = "";
  window.matchMedia =
    window.matchMedia ??
    ((query: string) =>
      ({
        matches: false,
        media: query,
        addEventListener: () => {},
        removeEventListener: () => {},
      }) as unknown as MediaQueryList);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  window.location.hash = "";
  vi.unstubAllGlobals();
});

function intent(target: string, event = "mouseover") {
  const link = container.querySelector<HTMLAnchorElement>(`a[href="#${target}"]`);
  expect(link).not.toBeNull();
  act(() => link!.dispatchEvent(new Event(event, { bubbles: true })));
}

describe("AdminAppShell — deep-link parametrizado", () => {
  it("oferece salto para o conteúdo principal na superfície administrativa", () => {
    window.location.hash = "#setup";

    act(() => root.render(h(AdminAppShell)));

    const skip = container.querySelector<HTMLAnchorElement>(".skip-link");
    const main = container.querySelector<HTMLElement>("#main-content");
    expect(skip?.getAttribute("href")).toBe("#main-content");
    expect(main?.getAttribute("aria-labelledby")).toBe("screen-title");
  });

  it("preserva o ID de #contatos/<id> até o ScreenView", () => {
    window.location.hash = "#contatos/p1";

    act(() => root.render(h(AdminAppShell)));

    expect(window.location.hash).toBe("#contatos/p1");
    expect(screenState.props).toEqual({ route: "contatos", param: "p1" });
  });
});

describe("AdminAppShell: intenção de navegação", () => {
  it.each(["mouseover", "focusin", "pointerdown"])(
    "aquece o JS de uma tela permitida em %s sem navegar nem consultar dados",
    (event) => {
      const fetch = vi.fn();
      vi.stubGlobal("fetch", fetch);
      window.location.hash = "#setup";
      act(() => root.render(h(AdminAppShell)));

      expect(preloadScreenModule).not.toHaveBeenCalled();
      intent("equipe", event);

      expect(preloadScreenModule).toHaveBeenCalledExactlyOnceWith("equipe");
      expect(window.location.hash).toBe("#setup");
      expect(screenState.props?.route).toBe("setup");
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("não aquece a tela ativa, uma rota operacional ou uma rota desconhecida", () => {
    window.location.hash = "#setup";
    act(() => root.render(h(AdminAppShell)));
    for (const target of ["setup", "inbox", "unknown"]) intent(target);
    expect(preloadScreenModule).not.toHaveBeenCalled();
  });

  it("permite Assinatura somente para o dono e mantém Perfil disponível", () => {
    window.location.hash = "#setup";
    authState.user = { roles: ["admin"], isOwner: false };
    act(() => root.render(h(AdminAppShell)));
    intent("assinatura");
    expect(preloadScreenModule).not.toHaveBeenCalled();
    intent("perfil");
    expect(preloadScreenModule).toHaveBeenCalledExactlyOnceWith("perfil");

    authState.user = { roles: ["admin"], isOwner: true };
    act(() => root.render(h(AdminAppShell)));
    intent("assinatura");
    expect(preloadScreenModule).toHaveBeenLastCalledWith("assinatura");
  });

  it.each([
    { visibility: "hidden", connection: undefined },
    { visibility: "visible", connection: { saveData: true, effectiveType: "4g" } },
    { visibility: "visible", connection: { effectiveType: "2g" } },
    { visibility: "visible", connection: { effectiveType: "slow-2g" } },
  ])("respeita visibilidade e economia de dados: %j", ({ visibility, connection }) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: visibility });
    Object.defineProperty(navigator, "connection", { configurable: true, value: connection });
    window.location.hash = "#setup";
    act(() => root.render(h(AdminAppShell)));
    intent("equipe");
    expect(preloadScreenModule).not.toHaveBeenCalled();
  });

  it("não aquece módulos sem usuário autenticado", () => {
    authState.user = null;
    act(() => root.render(h(AdminAppShell)));
    expect(container.querySelector("nav")).toBeNull();
    expect(preloadScreenModule).not.toHaveBeenCalled();
  });

  it("não aquece telas administrativas quando o usuário perde o papel admin", () => {
    window.location.hash = "#setup";
    authState.user = { roles: ["membro"], isOwner: false };
    act(() => root.render(h(AdminAppShell)));
    intent("equipe");
    expect(preloadScreenModule).not.toHaveBeenCalled();
  });

  it("uma falha no download especulativo não rejeita a navegação atual", async () => {
    window.location.hash = "#setup";
    act(() => root.render(h(AdminAppShell)));
    const loaders = await vi.importActual<typeof import("./screen-loaders")>("./screen-loaders");
    loaders.preloadScreenModule("equipe");
    await vi.dynamicImportSettled();
    expect(failedChunk).toHaveBeenCalledOnce();
    expect(window.location.hash).toBe("#setup");
    expect(screenState.props?.route).toBe("setup");
  });
});
