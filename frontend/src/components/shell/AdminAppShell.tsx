"use client";

/**
 * Shell da superfície administrativa da igreja (admin.<domínio> → /gestao).
 * Reusa Sidebar/Topbar/ScreenView do painel operacional, mas com um menu
 * PRÓPRIO (ADMIN_NAV_SECTIONS) e SEM Jornada G12/BottomNav. O allow-list de
 * rota vem das seções admin — não da matriz operacional — para que deep-links
 * operacionais (#dashboard/#inbox) não vazem para dentro do admin. 'assinatura'
 * segue OWNER_ONLY (admin não basta — só o dono).
 */
import { useEffect, useMemo, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { ADMIN_NAV_SECTIONS, SCREEN_META } from "@/lib/navigation";
import { appSurfaceHref } from "@/lib/surface";
import { useHashRoute } from "@/lib/use-hash-route";

import { ScreenView } from "./ScreenView";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";
import { useDrawerA11y } from "./useDrawerA11y";

/** Telas acessíveis fora do menu (o próprio perfil). */
const ALWAYS_ALLOWED = new Set(["perfil"]);

/** Assinatura é OWNER_ONLY (admin não basta — só o dono da igreja). */
const OWNER_ONLY = new Set(["assinatura"]);

/** Telas do menu administrativo (derivadas de ADMIN_NAV_SECTIONS). */
const ADMIN_SCREENS = new Set(
  ADMIN_NAV_SECTIONS.flatMap((s) => (s.items ?? []).map((i) => i.target)),
);

/** Landing padrão do admin (primeira tela administrativa). */
const ADMIN_HOME = ADMIN_NAV_SECTIONS[0]?.items?.[0]?.target ?? "whatsapp";

export function AdminAppShell() {
  const { user, logout } = useAuth();
  const [route, navigate] = useHashRoute();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [appHref, setAppHref] = useState<string | null>(null);

  useEffect(() => {
    setAppHref(appSurfaceHref());
  }, []);

  const slash = route.indexOf("/");
  const base = slash === -1 ? route : route.slice(0, slash);

  const known = base in SCREEN_META;
  const ownerOk = !OWNER_ONLY.has(base) || (user?.isOwner ?? false);
  const permitted = ownerOk && (ALWAYS_ALLOWED.has(base) || ADMIN_SCREENS.has(base));
  const allowed = known && permitted;
  const resolvedBase = allowed ? base : ADMIN_HOME;
  const resolvedRoute = allowed ? route : ADMIN_HOME;

  useEffect(() => {
    if (route !== resolvedRoute) navigate(resolvedRoute);
  }, [route, resolvedRoute, navigate]);

  useEffect(() => {
    setMobileOpen(false);
  }, [resolvedBase]);

  // Drawer mobile: Esc fecha, scroll lock, foco retorna ao gatilho (Gate 6).
  useDrawerA11y(mobileOpen, () => setMobileOpen(false));

  const crossSurface = useMemo(
    () => (appHref ? { href: appHref, label: "Voltar ao app" } : null),
    [appHref],
  );

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
        label="Menu administrativo"
        sections={ADMIN_NAV_SECTIONS}
        crossSurface={crossSurface}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onNavigate={navigate}
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
          menuButton
          menuOpen={mobileOpen}
          onMenuToggle={() => setMobileOpen((v) => !v)}
        />
        <ScreenView route={resolvedBase} param={null} />
      </main>
    </div>
  );
}
