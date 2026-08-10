// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  fetchMe: vi.fn(),
  login: vi.fn(),
}));
const adminApiMocks = vi.hoisted(() => ({
  fetchAdminMe: vi.fn(),
  adminLogin: vi.fn(),
}));

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return { ...actual, fetchMe: apiMocks.fetchMe, login: apiMocks.login };
});
vi.mock("./admin-api", async () => {
  const actual = await vi.importActual<typeof import("./admin-api")>("./admin-api");
  return {
    ...actual,
    fetchAdminMe: adminApiMocks.fetchAdminMe,
    adminLogin: adminApiMocks.adminLogin,
  };
});
vi.mock("@/components/shell/AppShell", () => ({ AppShell: () => null }));
vi.mock("@/components/dashboard/DashboardScreen", () => ({
  DashboardScreen: () => null,
}));
vi.mock("@/components/admin/AdminConsole", () => ({ AdminConsole: () => null }));

import {
  AdminAuthError,
  AdminSessionExpiredError,
  type AdminMe,
} from "./admin-api";
import {
  AdminAuthProvider,
  useAdminAuth,
  type AdminAuthStatus,
} from "./admin-auth-context";
import {
  SessionAccessDeniedError,
  SessionExpiredError,
  type MeResult,
} from "./api";
import { AuthProvider, useAuth, type AuthStatus } from "./auth-context";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  window.localStorage.clear();
  document.cookie = "pastorai_token=; max-age=0; path=/";
  apiMocks.fetchMe.mockReset();
  apiMocks.login.mockReset();
  adminApiMocks.fetchAdminMe.mockReset();
  adminApiMocks.adminLogin.mockReset();
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function renderProvider(children: ReactNode): Promise<void> {
  await act(async () => {
    root.render(children);
  });
}

async function waitForState(assertion: () => void): Promise<void> {
  await act(async () => {
    await vi.waitFor(assertion);
  });
}

const me: MeResult = {
  appUserId: "user-1",
  churchId: "church-1",
  email: "pessoa@example.com",
  nome: "Pessoa",
  chatNome: null,
  roles: ["pastor"],
  isOwner: false,
  igrejaNome: "Igreja",
  igrejaLogoUrl: null,
};

const adminMe: AdminMe = {
  appUserId: "admin-1",
  email: "admin@example.com",
  nome: "Admin",
};

describe("AuthProvider — restauração de sessão", () => {
  let latest: ReturnType<typeof useAuth> | null;

  function Probe() {
    latest = useAuth();
    return null;
  }

  beforeEach(() => {
    latest = null;
    window.localStorage.setItem("pastorai:token", "tenant-token");
  });

  it("encerra 403, apaga o token e preserva a mensagem para o fluxo de acesso", async () => {
    apiMocks.fetchMe.mockRejectedValue(
      new SessionAccessDeniedError("Seu acesso a esta igreja foi revogado."),
    );

    await renderProvider(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitForState(() => expect(latest?.status).toBe("unauthenticated"));

    expect(window.localStorage.getItem("pastorai:token")).toBeNull();
    expect(latest?.accessMessage).toBe("Seu acesso a esta igreja foi revogado.");
  });

  it("encerra 401 e apaga o token", async () => {
    apiMocks.fetchMe.mockRejectedValue(new SessionExpiredError());

    await renderProvider(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitForState(() => expect(latest?.status).toBe("unauthenticated"));

    expect(window.localStorage.getItem("pastorai:token")).toBeNull();
    expect(latest?.accessMessage).toBeNull();
  });

  it("mantém token em falha transitória e recupera pelo retry", async () => {
    apiMocks.fetchMe
      .mockRejectedValueOnce(new Error("rede indisponível"))
      .mockResolvedValueOnce(me);

    await renderProvider(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    await waitForState(() => expect(latest?.status).toBe("unavailable"));
    expect(window.localStorage.getItem("pastorai:token")).toBe("tenant-token");

    await act(async () => {
      latest?.retrySession();
    });
    await waitForState(() => expect(latest?.status).toBe("authenticated"));
    expect(latest?.user?.appUserId).toBe("user-1");
    expect(window.localStorage.getItem("pastorai:token")).toBe("tenant-token");
  });
});

describe("AdminAuthProvider — restauração de sessão", () => {
  let latest: ReturnType<typeof useAdminAuth> | null;

  function Probe() {
    latest = useAdminAuth();
    return null;
  }

  beforeEach(() => {
    latest = null;
    window.localStorage.setItem("pastorai:admin-token", "admin-token");
  });

  it("encerra 403, apaga o token e preserva a mensagem do gate", async () => {
    adminApiMocks.fetchAdminMe.mockRejectedValue(
      new AdminAuthError("forbidden", "Acesso administrativo revogado."),
    );

    await renderProvider(
      <AdminAuthProvider>
        <Probe />
      </AdminAuthProvider>,
    );
    await waitForState(() => expect(latest?.status).toBe("unauthenticated"));

    expect(window.localStorage.getItem("pastorai:admin-token")).toBeNull();
    expect(latest?.accessMessage).toBe("Acesso administrativo revogado.");
  });

  it("encerra 401 e apaga o token", async () => {
    adminApiMocks.fetchAdminMe.mockRejectedValue(new AdminSessionExpiredError());

    await renderProvider(
      <AdminAuthProvider>
        <Probe />
      </AdminAuthProvider>,
    );
    await waitForState(() => expect(latest?.status).toBe("unauthenticated"));

    expect(window.localStorage.getItem("pastorai:admin-token")).toBeNull();
    expect(latest?.accessMessage).toBeNull();
  });

  it("mantém token em falha transitória e recupera pelo retry", async () => {
    adminApiMocks.fetchAdminMe
      .mockRejectedValueOnce(new AdminAuthError("network", "Falha de conexão."))
      .mockResolvedValueOnce(adminMe);

    await renderProvider(
      <AdminAuthProvider>
        <Probe />
      </AdminAuthProvider>,
    );
    await waitForState(() => expect(latest?.status).toBe("unavailable"));
    expect(window.localStorage.getItem("pastorai:admin-token")).toBe("admin-token");

    await act(async () => {
      latest?.retrySession();
    });
    await waitForState(() => expect(latest?.status).toBe("authenticated"));
    expect(latest?.admin?.appUserId).toBe("admin-1");
    expect(window.localStorage.getItem("pastorai:admin-token")).toBe("admin-token");
  });
});

// Garante que os status públicos continuam restritos aos estados esperados.
const _authStatusContract: AuthStatus = "unavailable";
const _adminAuthStatusContract: AdminAuthStatus = "unavailable";
void _authStatusContract;
void _adminAuthStatusContract;
