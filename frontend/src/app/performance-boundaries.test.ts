import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const read = (...parts: string[]) => readFileSync(join(__dirname, ...parts), "utf8");

describe("fronteiras de carregamento do frontend", () => {
  const layout = read("layout.tsx");
  const home = read("page.tsx");
  const gestao = read("gestao", "page.tsx");
  const providers = read("..", "components", "providers", "AppProviders.tsx");
  const authContext = read("..", "lib", "auth-context.tsx");
  const screenView = read("..", "components", "shell", "ScreenView.tsx");

  it("mantém o Clerk e o mesmo limite global de autenticação", () => {
    expect(layout).toContain("AppProviders");
    expect(layout).not.toContain('dynamic = "force-dynamic"');
    expect(home).not.toContain("<AppProviders>");
    expect(gestao).not.toContain("<AppProviders>");
    expect(providers).toContain("ClerkProvider");
  });

  it("carrega shell, login e dashboard sob demanda com fallback acessível", () => {
    expect(home).toContain('import("@/components/shell/AppShell")');
    expect(home).toContain('import("@/components/login/LoginScreen")');
    expect(home).toContain("loading: PageLoading");
    expect(screenView).toContain("loadDashboardScreen");
    expect(screenView).toContain("loading: ScreenLoading");
    expect(home).toContain('role="status"');
  });

  it("antecipa somente a superfície e a rota autenticada enquanto /auth/me carrega", () => {
    expect(authContext.match(/preloadAuthenticatedSurface\(\);/g)).toHaveLength(2);
    expect(authContext).toContain('import("@/components/shell/AppShell")');
    expect(authContext).toContain('preloadRoute(requestedAuthenticatedRoute("dashboard"))');
    expect(authContext).not.toContain("Promise.all(Object.values");
  });
});
