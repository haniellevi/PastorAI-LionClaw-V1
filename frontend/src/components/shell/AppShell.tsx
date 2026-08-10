"use client";

/**
 * App shell autenticado: sidebar-nav + topbar + tela roteada por hash.
 * Resolve a rota ativa contra role_permissions (canSee) e telas bloqueadas;
 * rotas inválidas/sem acesso caem para #dashboard.
 */
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { clearAuthedResponseCache } from "@/lib/dashboard-api";
import { SCREEN_META } from "@/lib/navigation";
import { ADMIN_ONLY, canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { isAdmin } from "@/lib/roles";
import { preloadRouteData } from "@/lib/route-data-preload";
import { adminSurfaceHref } from "@/lib/surface";
import { useHashRoute } from "@/lib/use-hash-route";

import { BottomNav } from "./BottomNav";
import { JourneyStepper } from "./JourneyStepper";
import { preloadScreenModule } from "./screen-loaders";
import { ScreenView } from "./ScreenView";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useDrawerA11y } from "./useDrawerA11y";

/** Telas bloqueadas no MVP (locked-em-breve): não renderizam conteúdo. */
const LOCKED_SCREENS = new Set(["universidade-vida", "capacitacao"]);

/** Telas acessíveis a qualquer usuário, fora da matriz de permissões (ex.: o
 *  próprio perfil — todo mundo edita os próprios dados). */
const ALWAYS_ALLOWED = new Set(["perfil"]);

/** Telas restritas ao DONO (admin principal) da igreja — admin não basta (#4). */
const OWNER_ONLY = new Set(["assinatura"]);

/** Telas administrativas — vivem na superfície admin (admin.<domínio> → /gestao),
 *  fora do painel operacional. Bloqueadas por URL aqui, inclusive para admin. */
const ADMIN_ONLY_SET = new Set<string>(ADMIN_ONLY);

export function AppShell() {
  const { user, token, logout } = useAuth();
  const { matrix } = usePermissions();
  const [route, navigate] = useHashRoute();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [adminHref, setAdminHref] = useState<string | null>(null);

  // Botão "Admin" (troca para a superfície admin.) só para o papel admin.
  useEffect(() => {
    setAdminHref(user && isAdmin(user.roles) ? adminSurfaceHref() : null);
  }, [user]);

  // Deep-link: a rota pode carregar um parâmetro (ex.: "contatos/<id>").
  const slash = route.indexOf("/");
  const base = slash === -1 ? route : route.slice(0, slash);
  const param = slash === -1 ? null : route.slice(slash + 1);

  // Resolve a rota: a base precisa existir, ser permitida e não estar bloqueada.
  const known = base in SCREEN_META;
  // #4: telas OWNER_ONLY exigem ser o dono (admin não basta).
  const ownerOk = !OWNER_ONLY.has(base) || (user?.isOwner ?? false);
  const permitted =
    ownerOk &&
    !ADMIN_ONLY_SET.has(base) &&
    (ALWAYS_ALLOWED.has(base) || (user ? canSee(base, user.roles, matrix) : false));
  const allowed = known && permitted && !LOCKED_SCREENS.has(base);
  const resolvedBase = allowed ? base : "dashboard";
  const resolvedRoute = allowed ? route : "dashboard";
  const resolvedParam = allowed ? param : null;

  const warmRoute = useCallback(
    (target: string) => {
      if (!user) return;
      const targetBase = target.split("/", 1)[0] ?? target;
      const targetOwnerOk =
        !OWNER_ONLY.has(targetBase) || (user.isOwner ?? false);
      const targetPermitted =
        targetOwnerOk &&
        !ADMIN_ONLY_SET.has(targetBase) &&
        (ALWAYS_ALLOWED.has(targetBase) || canSee(targetBase, user.roles, matrix));
      if (
        !(targetBase in SCREEN_META) ||
        !targetPermitted ||
        LOCKED_SCREENS.has(targetBase)
      ) {
        return;
      }

      preloadScreenModule(targetBase);
      if (token) void preloadRouteData(token, targetBase);
    },
    [user, token, matrix],
  );

  // Depois da tela inicial estabilizar, aquece gradualmente os três destinos
  // mais usados. O escalonamento evita disputar rede/CPU com o primeiro paint.
  useEffect(() => {
    if (!user || !token) return;
    const commonRoutes = ["inbox", "calendario", "ganhar"];
    const timers = commonRoutes.map((target, index) =>
      window.setTimeout(() => warmRoute(target), 3_500 + index * 1_500),
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [user, token, warmRoute]);

  // A troca/encerramento da sessão remove imediatamente snapshots que ainda
  // estejam na memória, mesmo que o TTL curto não tenha vencido.
  useEffect(
    () => () => {
      if (token) clearAuthedResponseCache(token);
    },
    [token],
  );

  // Normaliza o hash quando a rota pedida é inválida/sem acesso.
  useEffect(() => {
    if (route !== resolvedRoute) {
      navigate(resolvedRoute);
    }
  }, [route, resolvedRoute, navigate]);

  // Fecha o drawer mobile a cada troca de rota.
  useEffect(() => {
    setMobileOpen(false);
  }, [resolvedBase]);

  // Drawer mobile: Esc fecha, scroll lock, foco retorna ao gatilho (Gate 6).
  useDrawerA11y(mobileOpen, () => setMobileOpen(false));

  if (!user) return null;

  return (
    <div className="app">
      {mobileOpen ? (
        // Botão semântico (não div aria-hidden clicável); fora do tab order —
        // Esc e o trap do drawer cobrem o teclado (useDrawerA11y).
        <button
          type="button"
          className="drawer-backdrop"
          aria-label="Fechar menu"
          tabIndex={-1}
          onClick={() => setMobileOpen(false)}
        />
      ) : null}
      <Sidebar
        user={user}
        route={resolvedBase}
        crossSurface={adminHref ? { href: adminHref, label: "Admin" } : null}
        crossSurfacePlacement="after"
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onNavigate={navigate}
        onPreload={warmRoute}
        onToggleCollapse={() => setCollapsed((v) => !v)}
        onLogout={() => {
          logout();
          navigate("login");
        }}
      />
      <main className="main">
        <Topbar
          user={user}
          route={resolvedBase}
          menuOpen={mobileOpen}
          onMenuToggle={() => setMobileOpen((v) => !v)}
        />
        <JourneyStepper />
        <ScreenView route={resolvedBase} param={resolvedParam} />
      </main>
      <BottomNav
        route={resolvedBase}
        menuOpen={mobileOpen}
        onPreload={warmRoute}
        onMore={() => setMobileOpen((v) => !v)}
      />
    </div>
  );
}
