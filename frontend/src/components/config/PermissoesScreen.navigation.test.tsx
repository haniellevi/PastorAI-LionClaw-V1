// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  expireSession: vi.fn(), fetchPermissions: vi.fn(), savePermissions: vi.fn(), setMatrix: vi.fn(),
}));
vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ token: "tenant-token-sintetico", expireSession: mocks.expireSession }),
}));
vi.mock("@/lib/permissions-context", () => ({ usePermissions: () => ({ setMatrix: mocks.setMatrix }) }));
vi.mock("@/lib/roles-api", async () => ({
  ...await vi.importActual<typeof import("@/lib/roles-api")>("@/lib/roles-api"),
  fetchPermissions: mocks.fetchPermissions, savePermissions: mocks.savePermissions,
}));

import { PermissoesScreen } from "./PermissoesScreen";
import { useHashRoute } from "@/lib/use-hash-route";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let downstream: ((event: PopStateEvent) => void) | undefined;
const savedState = { __NA: true, __PRIVATE_NEXTJS_INTERNALS_TREE: ["gestao-sintetica"], testEntry: "permissoes" };

function Surface() {
  const [route] = useHashRoute();
  return route === "permissoes" ? h(PermissoesScreen) : h("main", null, `Tela ${route}`);
}

function inbox() {
  const checkbox = container.querySelector<HTMLInputElement>('input[aria-label="Pastor vê Conversas"]');
  if (!checkbox) throw new Error("Acesso Conversas não encontrado");
  return checkbox;
}

async function dirtyScreen() {
  await act(async () => root.render(h(Surface)));
  await act(async () => inbox().click());
  expect(inbox().checked).toBe(false);
  expect(container.textContent).toContain("1 alteração não salva");
}

async function traverse() {
  await moveHistory("back");
}

async function hashEntry(route: string, state: object) {
  await act(async () => {
    window.history.pushState(state, "", `/gestao#${route}`);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

async function moveHistory(direction: "back" | "forward") {
  await act(async () => {
    window.history[direction]();
    // jsdom agenda a travessia e seus eventos em tarefas separadas.
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
}

function discardDraft() {
  const discard = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((button) => button.textContent === "Descartar")!;
  act(() => discard.click());
}

async function dirtyWithPreviousEntry() {
  window.history.replaceState({ __NA: true, testEntry: "setup" }, "", "/gestao#setup");
  await act(async () => root.render(h(Surface)));
  await hashEntry("permissoes", savedState);
  await act(async () => inbox().click());
  expect(inbox().checked).toBe(false);
}

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.fetchPermissions.mockResolvedValue({ pastor: ["dashboard", "inbox"], membro: ["dashboard"] });
  window.history.replaceState(savedState, "", "/gestao#permissoes");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  downstream = undefined;
});

afterEach(() => {
  if (downstream) window.removeEventListener("popstate", downstream);
  act(() => root.unmount());
  container.remove();
  vi.restoreAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("PermissoesScreen: confirmação antes do roteador de histórico", () => {
  it("ordem real do Window mantém rascunho quando o assinante de hash precede o guard", async () => {
    const add = vi.spyOn(window, "addEventListener");
    await dirtyScreen();
    const sync = add.mock.calls.find(([type, , capture]) => type === "hashchange" && !capture)?.[1] as EventListener;
    const guard = add.mock.calls.find(([type, , capture]) => type === "popstate" && capture === true)?.[1] as EventListener;
    expect(sync).toBeTypeOf("function");
    expect(guard).toBeTypeOf("function");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    // Sequência observada no Chromium: popstate confirma o cancelamento e
    // inicia a volta; no hashchange, o assinante antigo roda antes do capture.
    await act(async () => {
      window.history.pushState(null, "", "/gestao#setup");
      guard(new PopStateEvent("popstate", { state: null }));
      sync(new HashChangeEvent("hashchange"));
    });
    expect(inbox().checked).toBe(false);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
    expect(window.location.hash).toBe("#permissoes");
    expect(inbox().checked).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(mocks.fetchPermissions).toHaveBeenCalledTimes(1);
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });

  it("cancelar um fragmento nativo com state null não dispara restore do wrapper Next nem perde o rascunho", async () => {
    const nativeReplace = window.history.replaceState.bind(window.history);
    const restore = vi.fn(() => queueMicrotask(() => {
      flushSync(() => root.render(h("div", null, "ACTION_RESTORE")));
      flushSync(() => root.render(h(Surface)));
    }));
    // Contrato instalado do App Router 15.5.25: dados internos passam direto;
    // os demais disparam ACTION_RESTORE quando replaceState recebe uma URL.
    vi.spyOn(window.history, "replaceState").mockImplementation((data, unused, url) => {
      if (data?.__NA || data?._N) return nativeReplace(data, unused, url);
      const state = { ...data,
        __NA: window.history.state?.__NA,
        __PRIVATE_NEXTJS_INTERNALS_TREE: window.history.state?.__PRIVATE_NEXTJS_INTERNALS_TREE };
      if (url) restore();
      nativeReplace(state, unused, url);
    });
    await dirtyScreen();
    const originalState = window.history.state;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await act(async () => {
      // Como location.hash/anchor no navegador, esta entrada não herda state.
      window.location.hash = "setup";
      expect(window.history.state == null).toBe(true);
      await new Promise((resolve) => setTimeout(resolve, 50));
    });

    expect(restore).not.toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#permissoes");
    expect(window.history.state).toEqual(originalState);
    expect(inbox().checked).toBe(false);
    expect(mocks.fetchPermissions).toHaveBeenCalledTimes(1);
    expect(mocks.savePermissions).not.toHaveBeenCalled();
    discardDraft();
    await moveHistory("forward");
    expect(window.location.hash).toBe("#setup");
    expect(window.history.state).toMatchObject(savedState);
    expect(restore).not.toHaveBeenCalled();
  });

  it("Back cancelado preserva a entrada anterior e permite Back/Forward depois de descartar", async () => {
    window.history.replaceState({ __NA: true, testEntry: "setup" }, "", "/gestao#setup");
    await act(async () => root.render(h(Surface)));
    const teamState = { __NA: true, testEntry: "equipe" };
    await hashEntry("equipe", teamState);
    await hashEntry("permissoes", savedState);
    await act(async () => inbox().click());
    const originalState = window.history.state;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    await moveHistory("back");

    expect(window.location.hash).toBe("#permissoes");
    expect(window.history.state).toEqual(originalState);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(inbox().checked).toBe(false);
    discardDraft();
    await moveHistory("back");
    expect(window.location.hash).toBe("#equipe");
    expect(window.history.state).toMatchObject(teamState);
    expect(container.textContent).toContain("Tela equipe");
    await moveHistory("forward");
    expect(window.location.hash).toBe("#permissoes");
    expect(inbox().checked).toBe(true);
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });

  it("Forward cancelado preserva a entrada seguinte sem criar ou substituir destinos", async () => {
    await act(async () => root.render(h(Surface)));
    const futureState = { __NA: true, testEntry: "setup-futuro" };
    await hashEntry("setup", futureState);
    await moveHistory("back");
    await act(async () => inbox().click());
    const originalState = window.history.state;
    const originalLength = window.history.length;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    await moveHistory("forward");

    expect(window.location.hash).toBe("#permissoes");
    expect(window.history.state).toEqual(originalState);
    expect(window.history.length).toBe(originalLength);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(inbox().checked).toBe(false);
    discardDraft();
    await moveHistory("forward");
    expect(window.location.hash).toBe("#setup");
    expect(window.history.state).toMatchObject(futureState);
    expect(container.textContent).toContain("Tela setup");
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });

  it("Minha célula tem rótulo legível e salva o identificador de rota existente", async () => {
    mocks.savePermissions.mockImplementation(async (_token, matrix) => matrix);
    await act(async () => root.render(h(Surface)));
    const access = container.querySelector<HTMLInputElement>('input[aria-label="Pastor vê Minha célula"]');
    expect(access).not.toBeNull();
    await act(async () => access!.click());
    const save = [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent === "Salvar permissões")!;
    await act(async () => save.click());
    expect(mocks.savePermissions).toHaveBeenCalledTimes(1);
    expect(mocks.savePermissions.mock.calls[0]?.[1]?.pastor).toContain("minha-celula");
    expect(container.textContent).toContain("Permissões salvas");
  });

  it("cancelar popstate impede remount downstream e preserva URL, state e rascunho", async () => {
    // Um router em bubble pode desmontar a superfície antes do hashchange.
    // Registrar antes da tela reproduz a precedência do router do framework.
    const remount = vi.fn(() => {
      flushSync(() => root.render(h("div", null, "Restaurando superfície")));
      flushSync(() => root.render(h(Surface)));
    });
    downstream = remount;
    window.addEventListener("popstate", downstream);
    await dirtyWithPreviousEntry();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);

    await traverse();

    expect(remount).not.toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#permissoes");
    expect(window.history.state).toMatchObject(savedState);
    expect(inbox().checked).toBe(false);
    expect(mocks.fetchPermissions).toHaveBeenCalledTimes(1);
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });

  it("aceitar popstate deixa o router prosseguir sem repetir confirmação no hashchange", async () => {
    const router = vi.fn();
    downstream = router;
    window.addEventListener("popstate", downstream);
    await dirtyWithPreviousEntry();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);

    await traverse();

    expect(router).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#setup");
    expect(container.textContent).toContain("Tela setup");
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });

  it("saída apenas por hash também pede uma confirmação e mantém o rascunho ao cancelar", async () => {
    await dirtyScreen();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    await hashEntry("setup", { testEntry: "setup" });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 30)); });
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#permissoes");
    expect(window.history.state).toMatchObject(savedState);
    expect(inbox().checked).toBe(false);
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });

  it("descartar remove a proteção e permite a travessia sem confirmação", async () => {
    await dirtyWithPreviousEntry();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const discard = [...container.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent === "Descartar")!;
    await act(async () => discard.click());
    await traverse();
    expect(confirm).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Tela setup");
    expect(mocks.savePermissions).not.toHaveBeenCalled();
  });
});
