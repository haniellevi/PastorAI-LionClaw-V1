import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const read = (...parts: string[]) => readFileSync(join(__dirname, ...parts), "utf8");

const layout = read("layout.tsx");
const home = read("page.tsx");
const gestao = read("gestao", "page.tsx");
const admin = read("admin", "page.tsx");
const providers = read("..", "components", "providers", "AppProviders.tsx");
const authContext = read("..", "lib", "auth-context.tsx");
const adminAuthContext = read("..", "lib", "admin-auth-context.tsx");
const screenView = read("..", "components", "shell", "ScreenView.tsx");
const packageJson = JSON.parse(read("..", "..", "package.json")) as {
  dependencies: Record<string, string>;
};
const packageLock = read("..", "..", "package-lock.json");

const SCREEN_MODULES = [
  "@/components/calendario/CalendarioScreen",
  "@/components/cells/CelulasScreen",
  "@/components/central-celula/CentralCelulaScreen",
  "@/components/comunicados/ComunicadosScreen",
  "@/components/config/AgenteScreen",
  "@/components/config/AssinaturaScreen",
  "@/components/config/EquipeScreen",
  "@/components/config/IdentidadeVisualScreen",
  "@/components/config/IntegracoesScreen",
  "@/components/config/PermissoesScreen",
  "@/components/config/SetupChecklistScreen",
  "@/components/consolidacao/ConsolIndividualScreen",
  "@/components/consolidacao/ConsolidarScreen",
  "@/components/consolidacao/LockedScreen",
  "@/components/contacts/ContatosScreen",
  "@/components/contacts/GanharScreen",
  "@/components/dashboard/DashboardScreen",
  "@/components/enviar/EnviarScreen",
  "@/components/g12/G12Screen",
  "@/components/inbox/InboxScreen",
  "@/components/minha-celula/MinhaCelulaEntry",
  "@/components/profile/PerfilScreen",
  "@/components/reports/RelatoriosScreen",
  "@/components/whatsapp/WhatsappScreen",
].sort();

describe("fronteiras de carregamento do frontend", () => {
  it("mantém o root layout estático e escopa os providers às superfícies da igreja", () => {
    expect(layout).not.toContain("AppProviders");
    expect(layout).not.toContain('dynamic = "force-dynamic"');
    expect(home).toContain("<AppProviders>");
    expect(gestao).toContain("<AppProviders>");
    expect(admin).not.toContain("AppProviders");
    expect(providers).toContain("<AuthProvider>");
    expect(providers).toContain("<PermissionsProvider>");
  });

  it("carrega os três shells pesados por next/dynamic com fallback acessível", () => {
    expect(home).toContain('import("@/components/shell/AppShell")');
    expect(gestao).toContain('import("@/components/shell/AdminAppShell")');
    expect(admin).toContain('import("@/components/admin/AdminConsole")');

    for (const source of [home, gestao, admin]) {
      expect(source).toContain("loading: PageLoading");
      expect(source).toContain('role="status"');
      expect(source).toContain('aria-live="polite"');
      expect(source).toContain('className="sr-only"');
    }
  });

  it("divide as 24 telas do ScreenView em chunks com fallback acessível", () => {
    const dynamicModules = [...screenView.matchAll(/import\("([^"]+)"\)/g)]
      .map((match) => match[1]!)
      .sort();
    const staticModules = new Set(
      [...screenView.matchAll(/from\s+"([^"]+)"/g)].map((match) => match[1]!),
    );

    expect(dynamicModules).toEqual(SCREEN_MODULES);
    expect(SCREEN_MODULES.every((module) => !staticModules.has(module))).toBe(true);
    expect(screenView.match(/loading:\s*ScreenLoading/g)).toHaveLength(24);
    expect(screenView).toContain('role="status"');
    expect(screenView).toContain('aria-live="polite"');
    expect(screenView).toContain('className="sr-only"');
  });

  it("remove o SDK Clerk não consumido sem remover os providers próprios", () => {
    expect(providers).not.toContain("Clerk");
    expect(packageJson.dependencies).not.toHaveProperty("@clerk/nextjs");
    expect(packageLock).not.toContain("node_modules/@clerk/");
  });

  it("precarrega shell e somente a tela relevante antes de validar a sessão", () => {
    expect(authContext.match(/preloadAuthenticatedSurface\(\);/g)).toHaveLength(2);
    expect(authContext).toContain('import("@/components/shell/AppShell")');
    expect(authContext).toContain('import("@/components/shell/AdminAppShell")');
    expect(authContext).toContain('import("@/components/dashboard/DashboardScreen")');
    expect(authContext).toContain('import("@/components/inbox/InboxScreen")');
    expect(authContext).toContain('preloadRoute(requestedAuthenticatedRoute("setup"))');
    expect(authContext).toContain('preloadRoute(requestedAuthenticatedRoute("dashboard"))');

    const loginFlow = authContext.slice(
      authContext.indexOf("const login = useCallback"),
      authContext.indexOf("const logout = useCallback"),
    );
    expect(loginFlow.indexOf("await apiLogin")).toBeLessThan(
      loginFlow.indexOf("preloadAuthenticatedSurface();"),
    );
    expect(loginFlow.indexOf("preloadAuthenticatedSurface();")).toBeLessThan(
      loginFlow.indexOf("await fetchMe(token)"),
    );
    expect(authContext).not.toContain("Promise.all(Object.values");
  });

  it("precarrega o console admin no bootstrap e no login antes de /admin/me", () => {
    expect(adminAuthContext).toContain('import("@/components/admin/AdminConsole")');
    expect(adminAuthContext.match(/preloadAdminConsole\(\);/g)).toHaveLength(2);

    const bootstrap = adminAuthContext.slice(
      adminAuthContext.indexOf("useEffect(() =>"),
      adminAuthContext.indexOf("const login = useCallback"),
    );
    expect(bootstrap.indexOf("preloadAdminConsole();")).toBeLessThan(
      bootstrap.indexOf("fetchAdminMe(token)"),
    );

    const loginFlow = adminAuthContext.slice(
      adminAuthContext.indexOf("const login = useCallback"),
      adminAuthContext.indexOf("const logout = useCallback"),
    );
    expect(loginFlow.indexOf("await adminLogin")).toBeLessThan(
      loginFlow.indexOf("preloadAdminConsole();"),
    );
    expect(loginFlow.indexOf("preloadAdminConsole();")).toBeLessThan(
      loginFlow.indexOf("await fetchAdminMe(token)"),
    );
  });
});
