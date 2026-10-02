// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ login: vi.fn(), accessMessage: null as string | null }));
vi.mock("@/lib/admin-auth-context", () => ({ useAdminAuth: () => auth }));

import { AdminAuthError } from "@/lib/admin-api";
import { AdminLoginScreen } from "./AdminLoginScreen";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;

function input(label: string): HTMLInputElement {
  const node = [...container.querySelectorAll("label")].find((el) => el.textContent === label)!;
  return container.querySelector<HTMLInputElement>(`input[id="${node.htmlFor}"]`)!;
}

async function fill(label: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input(label), value);
    input(label).dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit() {
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

beforeEach(async () => {
  auth.login.mockReset();
  auth.accessMessage = null;
  window.history.replaceState(null, "", "/admin");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => { root.render(h(AdminLoginScreen)); });
});

afterEach(() => { act(() => root.unmount()); container.remove(); });

describe("AdminLoginScreen: formulário restrito", () => {
  it("validação incompleta não tenta autenticar", async () => {
    await fill("E-mail", "invalido");
    await submit();
    expect(auth.login).not.toHaveBeenCalled();
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });

  it("recusa preserva valores, libera retry e mantém a superfície do console", async () => {
    auth.login.mockRejectedValueOnce(new AdminAuthError("forbidden", "Recusa sintética."));
    await fill("E-mail", " admin@example.test ");
    await fill("Senha", "senha-sintetica");
    await submit();
    expect(auth.login).toHaveBeenCalledWith("admin@example.test", "senha-sintetica");
    expect(input("E-mail").value).toBe("admin@example.test");
    expect(input("Senha").value).toBe("senha-sintetica");
    expect(input("Senha").disabled).toBe(false);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("não tem acesso");
    expect(window.location.pathname).toBe("/admin");
    expect(window.location.hash).toBe("");
  });

  it("mostrar senha não submete e conserva valor e autocomplete", async () => {
    await fill("Senha", "senha-sintetica");
    const reveal = container.querySelector<HTMLButtonElement>('[aria-label="Mostrar senha"]')!;
    act(() => { reveal.focus(); reveal.click(); });
    expect(input("Senha").type).toBe("text");
    expect(input("Senha").value).toBe("senha-sintetica");
    expect(input("Senha").getAttribute("autocomplete")).toBe("current-password");
    expect(reveal.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(reveal);
    expect(auth.login).not.toHaveBeenCalled();
    act(() => { reveal.click(); });
    expect(input("Senha").type).toBe("password");
  });

  it("autenticação pendente bloqueia dupla submissão e preserva valores na falha", async () => {
    let reject!: (error: Error) => void;
    auth.login.mockReturnValueOnce(new Promise<void>((_, rej) => { reject = rej; }));
    await fill("E-mail", "admin@example.test");
    await fill("Senha", "senha-sintetica");
    await submit();
    await submit();
    expect(auth.login).toHaveBeenCalledTimes(1);
    expect(input("Senha").disabled).toBe(true);
    expect(container.querySelector<HTMLButtonElement>('[aria-label="Mostrar senha"]')!.disabled).toBe(true);
    await act(async () => { reject(new AdminAuthError("network", "Falha de conexão.")); });
    expect(input("Senha").disabled).toBe(false);
    expect(input("Senha").value).toBe("senha-sintetica");
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });
});
