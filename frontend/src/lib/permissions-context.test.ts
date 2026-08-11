// @vitest-environment jsdom

import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "./api";
import {
  canSee,
  DEFAULT_PERMISSIONS,
  type PermissionMatrix,
} from "./permissions";

const authMock = vi.hoisted(() => ({
  value: {
    status: "unauthenticated",
    token: null as string | null,
    expireSession: vi.fn(),
  },
}));

const rolesApiMock = vi.hoisted(() => ({
  fetchPermissions: vi.fn(),
}));

vi.mock("./auth-context", () => ({
  useOptionalAuth: () => authMock.value,
}));

vi.mock("./roles-api", () => ({
  fetchPermissions: rolesApiMock.fetchPermissions,
}));

const { PermissionsProvider, usePermissions } = await import("./permissions-context");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let current: ReturnType<typeof usePermissions> | null;

function Consumer() {
  current = usePermissions();
  return h("span", { "data-testid": "consumer" }, current.source);
}

function render() {
  act(() => {
    root.render(h(PermissionsProvider, null, h(Consumer)));
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
    await Promise.resolve();
    await Promise.resolve();
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  authMock.value = {
    status: "unauthenticated",
    token: null,
    expireSession: vi.fn(),
  };
  rolesApiMock.fetchPermissions.mockReset();
  current = null;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.useRealTimers();
});

describe("PermissionsProvider — matriz efetiva da sessão", () => {
  it("carrega automaticamente após autenticação e só libera os filhos com a matriz remota", async () => {
    const pending = deferred<PermissionMatrix>();
    rolesApiMock.fetchPermissions.mockReturnValueOnce(pending.promise);
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };

    render();

    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledWith("token-a");
    expect(container.textContent).toContain("Carregando permissões…");
    expect(container.querySelector('[data-testid="consumer"]')).toBeNull();

    pending.resolve({ membro: ["dashboard"] });
    await flush();

    expect(current?.source).toBe("remote");
    expect(current?.loading).toBe(false);
    expect(current?.matrix.membro).toEqual(["dashboard"]);
  });

  it("falha fechada sem restaurar calendário revogado e preserva operador", async () => {
    rolesApiMock.fetchPermissions.mockRejectedValueOnce(new Error("offline"));
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };

    render();
    await flush();

    expect(current?.source).toBe("fail-closed");
    expect(current?.matrix.membro).toEqual(["dashboard"]);
    expect(current?.matrix.membro).not.toContain("calendario");
    expect(current?.matrix.operador).toEqual(["dashboard"]);
    expect(canSee("dashboard", ["membro"], current!.matrix)).toBe(true);
    expect(canSee("dashboard", ["operador"], current!.matrix)).toBe(true);
    expect(canSee("calendario", ["membro"], current!.matrix)).toBe(false);
    expect(canSee("calendario", ["admin"], current!.matrix)).toBe(true);
  });

  it("recupera a matriz remota em background sem bloquear o dashboard mínimo", async () => {
    vi.useFakeTimers();
    rolesApiMock.fetchPermissions
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        membro: ["dashboard", "calendario"],
        operador: ["dashboard", "inbox"],
      });
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };

    render();
    await flush();

    expect(current?.source).toBe("fail-closed");
    expect(current?.loading).toBe(false);
    expect(current?.matrix.membro).toEqual(["dashboard"]);
    expect(container.querySelector('[data-testid="consumer"]')).not.toBeNull();

    await advance(4_999);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledOnce();
    await advance(1);

    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(2);
    expect(current?.source).toBe("remote");
    expect(current?.matrix.membro).toEqual(["dashboard", "calendario"]);
    expect(current?.matrix.operador).toEqual(["dashboard", "inbox"]);
  });

  it("encadeia falhas repetidas sem criar timers de retry concorrentes", async () => {
    vi.useFakeTimers();
    rolesApiMock.fetchPermissions.mockRejectedValue(new Error("offline"));
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };

    render();
    await flush();
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledOnce();

    await advance(5_000);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(2);

    // O segundo erro agenda só o próximo degrau (10 s). Se houvesse outro
    // timer de 5 s concorrente, uma terceira leitura apareceria aqui.
    await advance(9_999);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(3);
    expect(current?.source).toBe("fail-closed");
    expect(current?.matrix.operador).toEqual(["dashboard"]);
  });

  it("cancela o retry agendado quando o token muda", async () => {
    vi.useFakeTimers();
    rolesApiMock.fetchPermissions
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ membro: ["dashboard", "minha-celula"] });
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };
    render();
    await flush();
    expect(current?.source).toBe("fail-closed");

    authMock.value = { ...authMock.value, token: "token-b" };
    render();
    await flush();
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(2);
    expect(rolesApiMock.fetchPermissions).toHaveBeenLastCalledWith("token-b");
    expect(current?.source).toBe("remote");

    await advance(5_000);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(2);
    expect(current?.matrix.membro).toEqual(["dashboard", "minha-celula"]);
  });

  it("cancela o retry agendado ao desmontar o provider", async () => {
    vi.useFakeTimers();
    rolesApiMock.fetchPermissions.mockRejectedValue(new Error("offline"));
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };
    const localContainer = document.createElement("div");
    const localRoot = createRoot(localContainer);

    act(() => {
      localRoot.render(h(PermissionsProvider, null, h(Consumer)));
    });
    await flush();
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledOnce();

    act(() => localRoot.unmount());
    await advance(5_000);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledOnce();
  });

  it("mantém a revogação remota verificada quando uma atualização do mesmo token falha", async () => {
    rolesApiMock.fetchPermissions
      .mockResolvedValueOnce({ membro: ["dashboard"], operador: ["dashboard", "inbox"] })
      .mockRejectedValueOnce(new Error("offline"));
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };

    render();
    await flush();
    expect(current?.source).toBe("remote");
    expect(current?.matrix.membro).not.toContain("calendario");

    // A identidade da ação muda após uma reidratação do AuthProvider, mas o
    // token permanece o mesmo e pode reutilizar somente seu snapshot verificado.
    authMock.value = { ...authMock.value, expireSession: vi.fn() };
    render();
    await flush();

    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledTimes(2);
    expect(current?.source).toBe("cached");
    expect(current?.matrix.membro).toEqual(["dashboard"]);
    expect(current?.matrix.membro).not.toContain("calendario");
    expect(current?.matrix.operador).toEqual(["dashboard", "inbox"]);
  });

  it("encerra a sessão em 401 em vez de liberar uma matriz provisória", async () => {
    vi.useFakeTimers();
    const expireSession = vi.fn();
    rolesApiMock.fetchPermissions.mockRejectedValueOnce(new SessionExpiredError());
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession,
    };

    render();
    await flush();

    expect(expireSession).toHaveBeenCalledOnce();
    expect(container.querySelector('[data-testid="consumer"]')).toBeNull();
    await advance(60_000);
    expect(rolesApiMock.fetchPermissions).toHaveBeenCalledOnce();
  });

  it("não deixa uma resposta antiga sobrescrever a matriz de outra sessão", async () => {
    const first = deferred<PermissionMatrix>();
    const second = deferred<PermissionMatrix>();
    rolesApiMock.fetchPermissions
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };
    render();

    authMock.value = { ...authMock.value, token: "token-b" };
    render();
    second.resolve({ membro: ["dashboard", "calendario"] });
    await flush();
    first.resolve({ membro: ["dashboard", "minha-celula"] });
    await flush();

    expect(current?.matrix.membro).toEqual(["dashboard", "calendario"]);
  });

  it("não deixa matriz verificada de token antigo vazar para novo token em falha", async () => {
    rolesApiMock.fetchPermissions
      .mockResolvedValueOnce({
        membro: ["dashboard", "calendario"],
        operador: ["dashboard", "inbox", "ganhar"],
      })
      .mockRejectedValueOnce(new Error("offline"));
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };
    render();
    await flush();
    expect(current?.source).toBe("remote");

    authMock.value = { ...authMock.value, token: "token-b" };
    render();
    expect(container.textContent).toContain("Carregando permissões…");
    await flush();

    expect(current?.source).toBe("fail-closed");
    expect(current?.matrix.membro).toEqual(["dashboard"]);
    expect(current?.matrix.membro).not.toContain("calendario");
    expect(current?.matrix.operador).toEqual(["dashboard"]);
  });

  it("descarta a matriz remota ao encerrar a sessão", async () => {
    rolesApiMock.fetchPermissions.mockResolvedValueOnce({
      membro: ["dashboard"],
    });
    authMock.value = {
      status: "authenticated",
      token: "token-a",
      expireSession: vi.fn(),
    };
    render();
    await flush();

    authMock.value = { ...authMock.value, status: "unauthenticated", token: null };
    render();
    await flush();

    expect(current?.source).toBe("default");
    expect(current?.matrix.membro).toEqual(DEFAULT_PERMISSIONS.membro);
  });
});
