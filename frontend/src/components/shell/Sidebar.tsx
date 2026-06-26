"use client";

/**
 * sidebar-nav FLAT (paridade protótipo "Igreja 12").
 * Grupos planos com título (sem accordion/expand). Cada item é uma linha com
 * bloco de ícone arredondado colorido + label. A Jornada renderiza só o head
 * de cada estágio (as subs vivem no ModuleTabs/deep-link). O menu é a UNIÃO
 * dos papéis acumulados (role_permissions). Configuração só para admin.
 * Navegação por hash, sem reload. canSee/locked/deep-link preservados.
 */
import { useMemo } from "react";

import type { SessionUser } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import {
  NAV_SECTIONS,
  STAGE_ACCENT,
  type NavItem,
  type NavSection,
} from "@/lib/navigation";
import { allowedScreens } from "@/lib/permissions";
import { usePermissions } from "@/lib/permissions-context";
import { isAdmin } from "@/lib/roles";

interface SidebarProps {
  user: SessionUser;
  route: string;
  collapsed: boolean;
  mobileOpen: boolean;
  onNavigate: (target: string) => void;
  onToggleCollapse: () => void;
  onLogout: () => void;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0]!.slice(0, 2).toUpperCase();
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

export function Sidebar({
  user,
  route,
  collapsed,
  mobileOpen,
  onNavigate,
  onToggleCollapse,
  onLogout,
}: SidebarProps) {
  const admin = isAdmin(user.roles);
  const { matrix } = usePermissions();
  // O menu reage à matriz de permissões vigente (delta-010): editar em
  // #permissoes reflete aqui em tempo real, sem reload.
  const allowed = useMemo(() => {
    const s = new Set(allowedScreens(user.roles, matrix));
    // #4: só o dono (admin principal) vê a Assinatura no menu — admin não basta.
    if (!user.isOwner) s.delete("assinatura");
    return s;
  }, [user.roles, user.isOwner, matrix]);
  const visible = (target: string) => allowed.has(target);

  // Seções visíveis (Configuração apenas para admin).
  const sections = useMemo(
    () => NAV_SECTIONS.filter((s) => (s.adminOnly ? admin : true)),
    [admin],
  );

  function renderItem(item: NavItem, accent?: NavItem["accent"]) {
    const tint = item.accent ?? accent;
    const classes = [
      "nav-item",
      item.locked ? "locked" : "",
      !item.locked && route === item.target ? "active" : "",
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <button
        key={`${item.target}-${item.label}`}
        type="button"
        className={classes}
        data-tip={item.label}
        data-accent={tint}
        aria-current={!item.locked && route === item.target ? "page" : undefined}
        aria-disabled={item.locked || undefined}
        onClick={() => {
          if (!item.locked) onNavigate(item.target);
        }}
      >
        <span className="nav-ic" aria-hidden="true">
          <Icon name={item.icon} />
        </span>
        <span className="lbl">{item.label}</span>
        {item.badge ? <span className="badge">{item.badge}</span> : null}
        {item.locked ? (
          <span className="soon" title="Disponível em breve" aria-hidden="true">
            <Icon name="lock" />
          </span>
        ) : null}
      </button>
    );
  }

  function renderSection(section: NavSection) {
    // Itens diretos + heads de estágio (flat) que o usuário pode ver.
    const directItems = (section.items ?? []).filter(
      (i) => visible(i.target) || i.locked,
    );
    const stageHeads = (section.stages ?? [])
      .filter((st) => visible(st.head.target))
      .map((st) => ({ item: st.head, accent: STAGE_ACCENT[st.stage] }));

    if (directItems.length === 0 && stageHeads.length === 0) return null;

    return (
      <div className="nav-group" key={section.id}>
        <div className="nav-group-title lbl">{section.label}</div>
        {directItems.map((i) => renderItem(i))}
        {stageHeads.map(({ item, accent }) => renderItem(item, accent))}
      </div>
    );
  }

  return (
    <nav className={`sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " open" : ""}`}>
      <div className="side-top">
        <div className="side-brand">
          <span className="brand-mark" aria-hidden="true">
            12
          </span>
          <span className="lbl">Igreja 12</span>
        </div>
        <button
          type="button"
          className="collapse-btn"
          title={collapsed ? "Expandir menu" : "Recolher menu"}
          aria-label={collapsed ? "Expandir menu" : "Recolher menu"}
          onClick={onToggleCollapse}
        >
          <Icon name="chevron-left" />
        </button>
      </div>

      <div className="side-church" data-tip="Sua igreja">
        <span className="church-avatar">{initials(user.nome)}</span>
        <span className="church-meta lbl">
          <strong>
            Painel da Igreja
            {user.isOwner ? (
              <span className="owner-seal" title="Dono da conta (admin principal)">
                Dono
              </span>
            ) : null}
          </strong>
          <span>Visão G12</span>
        </span>
      </div>

      <div className="nav-scroll">{sections.map(renderSection)}</div>

      <div className="side-foot">
        <div className="side-user">
          <button
            type="button"
            className="side-user-link"
            title="Meu perfil"
            onClick={() => onNavigate("perfil")}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              flex: 1,
              minWidth: 0,
              background: "none",
              border: "none",
              padding: 0,
              font: "inherit",
              color: "inherit",
              textAlign: "left",
              cursor: "pointer",
            }}
          >
            <span className="av">{initials(user.nome)}</span>
            <span className="nm lbl">
              <strong>{user.nome}</strong>
              <span className="sub" style={{ color: "var(--sidebar-muted)" }}>
                Meu perfil
              </span>
            </span>
          </button>
          <button
            type="button"
            id="logoutBtn"
            className="btn btn-ghost btn-sm"
            style={{ color: "var(--sidebar-muted)", marginLeft: "auto" }}
            title="Sair"
            aria-label="Sair"
            onClick={onLogout}
          >
            <Icon name="logout" />
          </button>
        </div>
      </div>
    </nav>
  );
}
