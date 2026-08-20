// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const screenState = vi.hoisted(() => ({
  props: null as null | { route: string; param?: string | null },
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    user: { roles: ["admin"], isOwner: true },
    logout: vi.fn(),
  }),
}));

vi.mock("./ScreenView", () => ({
  ScreenView: (props: { route: string; param?: string | null }) => {
    screenState.props = props;
    return null;
  },
}));

vi.mock("./Sidebar", () => ({ Sidebar: () => null }));
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
  screenState.props = null;
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
});

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
