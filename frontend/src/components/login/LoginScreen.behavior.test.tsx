// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({
  login: vi.fn(),
  logout: vi.fn(),
  consumeReturnTo: vi.fn(),
  accessMessage: null as string | null,
}));
const api = vi.hoisted(() => ({
  activateInvite: vi.fn(),
  fetchInvite: vi.fn(),
  requestPasswordReset: vi.fn(),
  resetPassword: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({ useAuth: () => auth }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  ...api,
}));

import { LoginError, type InviteInfo } from "@/lib/api";
import { LoginScreen } from "./LoginScreen";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function deferred() {
  let resolve!: () => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<void>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function input(label: string): HTMLInputElement {
  const node = [...container.querySelectorAll("label")].find((el) => el.textContent === label);
  expect(node, `campo ${label}`).toBeDefined();
  return container.querySelector<HTMLInputElement>(`input[id="${node!.htmlFor}"]`)!;
}

async function fill(label: string, value: string) {
  await act(async () => {
    const field = input(label);
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function button(text: string) {
  const node = [...container.querySelectorAll<HTMLButtonElement>("button")]
    .find((el) => el.textContent?.trim() === text || el.getAttribute("aria-label") === text);
  expect(node, `botão ${text}`).toBeDefined();
  return node!;
}

async function submit() {
  await act(async () => {
    container.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

async function navigate(route: string) {
  await act(async () => {
    window.location.hash = route;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

async function render(route: string) {
  window.history.replaceState(null, "", `/#${route}`);
  await act(async () => { root.render(h(LoginScreen)); });
}

async function returnToLogin() {
  const control = container.querySelector<HTMLAnchorElement>('a[href="#login"]')
    ?? button("Ir para o login");
  await act(async () => {
    control.click();
    await vi.waitFor(() => expect(window.location.hash).toBe("#login"));
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

function invite(token: string): InviteInfo {
  return { nome: `Pessoa ${token}`, email: "pessoa@example.test", igreja: "Igreja Laboratório", precisaCadastro: false };
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.login.mockReset();
  auth.logout.mockReset();
  auth.consumeReturnTo.mockReset();
  auth.accessMessage = null;
  api.activateInvite.mockReset().mockResolvedValue(undefined);
  api.fetchInvite.mockReset().mockImplementation(async (token: string) => invite(token));
  api.requestPasswordReset.mockReset().mockResolvedValue(undefined);
  api.resetPassword.mockReset().mockResolvedValue(undefined);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  window.history.replaceState(null, "", "/");
  vi.restoreAllMocks();
});

describe("LoginScreen: formulário e retorno", () => {
  it("sucesso restaura o destino mesmo quando a autenticação já desmontou o login", async () => {
    auth.consumeReturnTo.mockReturnValue("inbox");
    auth.login.mockImplementationOnce(async () => {
      await Promise.resolve();
      flushSync(() => { root.render(h("main", { "aria-label": "Aplicativo autenticado" })); });
    });
    await render("login");
    await fill("E-mail", "pessoa@example.test");
    await fill("Senha", "senha-sintetica");
    await submit();
    expect(container.querySelector('main[aria-label="Aplicativo autenticado"]')).not.toBeNull();
    expect(auth.login).toHaveBeenCalledTimes(1);
    expect(auth.consumeReturnTo).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#inbox");
  });

  it("valida antes de autenticar e associa erros aos campos", async () => {
    await render("login");
    await fill("E-mail", "invalido");
    await submit();
    expect(auth.login).not.toHaveBeenCalled();
    for (const label of ["E-mail", "Senha"]) {
      const field = input(label);
      expect(field.getAttribute("aria-invalid")).toBe("true");
      const error = document.getElementById(field.getAttribute("aria-describedby")!);
      expect(error?.getAttribute("role")).toBe("alert");
    }
  });

  it("falha preserva valores e destino; sucesso consome o retorno uma única vez", async () => {
    auth.login.mockRejectedValueOnce(new LoginError("invalid", "Credenciais inválidas."))
      .mockResolvedValueOnce(undefined);
    auth.consumeReturnTo.mockReturnValue("inbox");
    await render("login");
    await fill("E-mail", " pessoa@example.test ");
    await fill("Senha", "senha-sintetica");
    await submit();
    expect(input("E-mail").value).toBe("pessoa@example.test");
    expect(input("Senha").value).toBe("senha-sintetica");
    expect(input("Senha").disabled).toBe(false);
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Credenciais inválidas.");
    expect(auth.consumeReturnTo).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("#login");
    await submit();
    expect(auth.login).toHaveBeenLastCalledWith("pessoa@example.test", "senha-sintetica");
    expect(auth.consumeReturnTo).toHaveBeenCalledTimes(1);
    expect(window.location.hash).toBe("#inbox");
  });

  it("mostrar senha conserva valor e não submete o formulário", async () => {
    await render("login");
    await fill("Senha", "senha-sintetica");
    const reveal = button("Mostrar senha");
    act(() => { reveal.focus(); reveal.click(); });
    expect(input("Senha").type).toBe("text");
    expect(input("Senha").value).toBe("senha-sintetica");
    expect(input("Senha").getAttribute("autocomplete")).toBe("current-password");
    expect(reveal.getAttribute("aria-pressed")).toBe("true");
    expect(document.activeElement).toBe(reveal);
    expect(auth.login).not.toHaveBeenCalled();
    act(() => { button("Ocultar senha").click(); });
    expect(input("Senha").type).toBe("password");
    expect(input("Senha").value).toBe("senha-sintetica");
  });

  it("login pendente bloqueia dupla submissão e o botão de revelar senha", async () => {
    const pending = deferred();
    auth.login.mockReturnValueOnce(pending.promise);
    await render("login");
    await fill("E-mail", "pessoa@example.test");
    await fill("Senha", "senha-sintetica");
    await submit();
    await submit();
    expect(auth.login).toHaveBeenCalledTimes(1);
    expect(input("Senha").disabled).toBe(true);
    expect(button("Mostrar senha").disabled).toBe(true);
    await act(async () => { pending.reject(new LoginError("network", "Tente novamente.")); });
    expect(input("Senha").disabled).toBe(false);
    expect(input("Senha").value).toBe("senha-sintetica");
  });

  it("recuperação inválida não solicita envio e permite voltar ao login", async () => {
    await render("esqueci-senha");
    await fill("E-mail", "invalido");
    await submit();
    expect(api.requestPasswordReset).not.toHaveBeenCalled();
    expect(input("E-mail").getAttribute("aria-invalid")).toBe("true");
    await returnToLogin();
    expect(window.location.hash).toBe("#login");
    expect(input("Senha")).not.toBeNull();
  });

  it.each(["200", "404", "rede"])("recuperação mantém resposta neutra em %s", async (outcome) => {
    const original = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
    api.requestPasswordReset.mockImplementation(original.requestPasswordReset);
    const fetch = vi.spyOn(globalThis, "fetch");
    if (outcome === "rede") fetch.mockRejectedValue(new Error("NOT-EXPOSED"));
    else fetch.mockResolvedValue(new Response('{"detail":"NOT-EXPOSED"}', { status: Number(outcome) }));
    await render("esqueci-senha");
    await fill("E-mail", "pessoa@example.test");
    await submit();
    const status = container.querySelector('[role="status"]');
    expect(status?.textContent).toMatch(/Se (?:existir|houver).*conta/i);
    expect(container.textContent).not.toContain("NOT-EXPOSED");
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, options] = fetch.mock.calls[0]!;
    expect(String(url)).toMatch(/\/auth\/forgot-password$/);
    expect(JSON.parse(options!.body as string)).toEqual({ email: "pessoa@example.test" });
  });
});

describe("LoginScreen: redefinição e ativação", () => {
  it("reset valida comprimento e confirmação, preserva entradas após falha e retorna ao login", async () => {
    await render("redefinir-senha/token-reset");
    await fill("Nova senha", "curta");
    await fill("Confirmar nova senha", "curta");
    await submit();
    expect(api.resetPassword).not.toHaveBeenCalled();
    await fill("Nova senha", "senha-sintetica");
    await fill("Confirmar nova senha", "senha-diferente");
    await submit();
    expect(api.resetPassword).not.toHaveBeenCalled();
    await fill("Confirmar nova senha", "senha-sintetica");
    api.resetPassword.mockRejectedValueOnce(new LoginError("network", "Falha de conexão."));
    await submit();
    expect(input("Nova senha").value).toBe("senha-sintetica");
    expect(input("Confirmar nova senha").value).toBe("senha-sintetica");
    expect(auth.logout).not.toHaveBeenCalled();
    await submit();
    expect(api.resetPassword).toHaveBeenLastCalledWith("token-reset", "senha-sintetica");
    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect(auth.login).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(container.querySelector("h1"));
    await returnToLogin();
    expect(window.location.hash).toBe("#login");
  });

  it("reset sem token e convite expirado não oferecem submissão", async () => {
    await render("redefinir-senha");
    expect(container.querySelector('button[type="submit"]')).toBeNull();
    expect(api.resetPassword).not.toHaveBeenCalled();
    api.fetchInvite.mockRejectedValueOnce(new LoginError("invalid", "Convite expirado."));
    await navigate("ativar/token-expirado");
    expect(container.querySelector('[role="alert"]')?.textContent).toContain("Convite expirado.");
    expect(container.querySelector('button[type="submit"]')).toBeNull();
    expect(api.activateInvite).not.toHaveBeenCalled();
  });

  it("ativação pede telefone somente quando necessário e preserva dados após falha", async () => {
    api.fetchInvite.mockResolvedValueOnce({ ...invite("cadastro"), precisaCadastro: true });
    await render("ativar/token-cadastro");
    await fill("Senha", "senha-sintetica");
    await fill("Confirmar senha", "senha-diferente");
    await submit();
    expect(api.activateInvite).not.toHaveBeenCalled();
    await fill("Confirmar senha", "senha-sintetica");
    await submit();
    expect(api.activateInvite).not.toHaveBeenCalled();
    await fill("Telefone / WhatsApp", "5500000000000");
    api.activateInvite.mockRejectedValueOnce(new LoginError("network", "Falha de conexão."));
    await submit();
    expect(input("Senha").value).toBe("senha-sintetica");
    expect(input("Confirmar senha").value).toBe("senha-sintetica");
    expect(input("Telefone / WhatsApp").value).toBe("5500000000000");
    expect(auth.logout).not.toHaveBeenCalled();
    await submit();
    expect(api.activateInvite).toHaveBeenLastCalledWith("token-cadastro", "senha-sintetica", "5500000000000");
    expect(auth.logout).toHaveBeenCalledTimes(1);
    expect(auth.login).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(container.querySelector("h1"));
  });
});

describe("LoginScreen: isolamento por token", () => {
  it("busca tardia do convite A não substitui os dados do convite B", async () => {
    let resolve!: (value: InviteInfo) => void;
    api.fetchInvite.mockReturnValueOnce(new Promise<InviteInfo>((res) => { resolve = res; }));
    await render("ativar/token-a");
    await navigate("ativar/token-b");
    expect(container.textContent).toContain("Pessoa token-b");
    await act(async () => { resolve(invite("token-a")); });
    expect(container.textContent).toContain("Pessoa token-b");
    expect(container.textContent).not.toContain("Pessoa token-a");
    expect(input("Senha").disabled).toBe(false);
  });

  it.each(["reset", "ativação"])("erro tardio da %s A não contamina o link B", async (flow) => {
    const pending = deferred();
    const reset = flow === "reset";
    (reset ? api.resetPassword : api.activateInvite).mockReturnValueOnce(pending.promise);
    const route = reset ? "redefinir-senha" : "ativar";
    const password = reset ? "Nova senha" : "Senha";
    const confirmation = reset ? "Confirmar nova senha" : "Confirmar senha";
    await render(`${route}/token-a`);
    await fill(password, "senha-primeira");
    await fill(confirmation, "senha-primeira");
    await submit();
    await navigate(`${route}/token-b`);
    await fill(password, "senha-segunda");
    await act(async () => { pending.reject(new LoginError("invalid", "Erro exclusivo do token A.")); });
    expect(container.textContent).not.toContain("Erro exclusivo do token A.");
    expect(input(password).value).toBe("senha-segunda");
    expect(input(password).disabled).toBe(false);
    expect(auth.logout).not.toHaveBeenCalled();
  });

  it("reset concluído de A não aparece como sucesso de B", async () => {
    await render("redefinir-senha/token-a");
    await fill("Nova senha", "senha-sintetica");
    await fill("Confirmar nova senha", "senha-sintetica");
    await submit();
    expect(api.resetPassword).toHaveBeenCalledWith("token-a", "senha-sintetica");
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    await navigate("redefinir-senha/token-b");
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(input("Nova senha").value).toBe("");
  });

  it("conclusão tardia do reset A não encerra nem apaga campos de B", async () => {
    const pending = deferred();
    api.resetPassword.mockReturnValueOnce(pending.promise);
    await render("redefinir-senha/token-a");
    await fill("Nova senha", "senha-primeira");
    await fill("Confirmar nova senha", "senha-primeira");
    await submit();
    await navigate("redefinir-senha/token-b");
    await fill("Nova senha", "senha-segunda");
    await fill("Confirmar nova senha", "senha-segunda");
    await act(async () => { pending.resolve(); });
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(input("Nova senha").value).toBe("senha-segunda");
    expect(auth.logout).not.toHaveBeenCalled();
  });

  it("ativação concluída de A não aparece como sucesso de B", async () => {
    await render("ativar/token-a");
    await fill("Senha", "senha-sintetica");
    await fill("Confirmar senha", "senha-sintetica");
    await submit();
    expect(api.activateInvite).toHaveBeenCalledWith("token-a", "senha-sintetica", undefined);
    expect(container.querySelector('[role="status"]')).not.toBeNull();
    await navigate("ativar/token-b");
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(input("Senha").value).toBe("");
    expect(container.textContent).toContain("Pessoa token-b");
  });

  it("conclusão tardia da ativação A não encerra o convite B", async () => {
    const pending = deferred();
    api.activateInvite.mockReturnValueOnce(pending.promise);
    await render("ativar/token-a");
    await fill("Senha", "senha-primeira");
    await fill("Confirmar senha", "senha-primeira");
    await submit();
    await navigate("ativar/token-b");
    await fill("Senha", "senha-segunda");
    await fill("Confirmar senha", "senha-segunda");
    await act(async () => { pending.resolve(); });
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(input("Senha").value).toBe("senha-segunda");
    expect(container.textContent).toContain("Pessoa token-b");
    expect(auth.logout).not.toHaveBeenCalled();
  });
});
