"use client";

/**
 * App shell autenticado: sidebar-nav + topbar + tela roteada por hash.
 * Resolve a rota ativa contra role_permissions (canSee) e telas bloqueadas;
 * rotas inválidas/sem acesso caem para #dashboard.
 */
import { useEffect, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { SCREEN_META } from "@/lib/navigation";
import { canSee } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { useHashRoute } from "@/lib/use-hash-route";

import { BottomNav } from "./BottomNav";
import { JourneyStepper } from "./JourneyStepper";
import { ScreenView } from "./ScreenView";
import { Sidebar } from "./Sidebar";
import { Topbar } from "./Topbar";

/** Telas bloqueadas no MVP (locked-em-breve): não renderizam conteúdo. */
const LOCKED_SCREENS = new Set(["universidade-vida", "capacitacao"]);

/** Telas acessíveis a qualquer usuário, fora da matriz de permissões (ex.: o
 *  próprio perfil — todo mundo edita os próprios dados). */
const ALWAYS_ALLOWED = new Set(["perfil"]);

/** Telas restritas ao DONO (admin principal) da igreja — admin não basta (#4). */
const OWNER_ONLY = new Set(["assinatura"]);

export function AppShell() {
  const { user, logout } = useAuth();
  const { matrix } = usePermissions();
  const [route, navigate] = useHashRoute();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

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
    (ALWAYS_ALLOWED.has(base) || (user ? canSee(base, user.roles, matrix) : false));
  const allowed = known && permitted && !LOCKED_SCREENS.has(base);
  const resolvedBase = allowed ? base : "dashboard";
  const resolvedRoute = allowed ? route : "dashboard";
  const resolvedParam = allowed ? param : null;

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

  if (!user) return null;

  return (
    <div className="app">
      <Sidebar
        user={user}
        route={resolvedBase}
        collapsed={collapsed}
        mobileOpen={mobileOpen}
        onNavigate={navigate}
        onToggleCollapse={() => setCollapsed((v) => !v)}
        onLogout={() => {
          logout();
          navigate("login");
        }}
      />
      <div className="main">
        <Topbar user={user} route={resolvedBase} onMenuToggle={() => setMobileOpen((v) => !v)} />
        <JourneyStepper />
        <ScreenView route={resolvedBase} param={resolvedParam} />
      </div>
      <BottomNav onMore={() => setMobileOpen((v) => !v)} />
    </div>
  );
}
