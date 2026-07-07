"use client";

/**
 * sidebar-nav FLAT (paridade protótipo "Igreja 12").
 * Grupos planos com título (sem accordion/expand). Cada item é uma linha com
 * bloco de ícone arredondado colorido + label. A Jornada renderiza só o head
 * de cada estágio (as subs vivem no ModuleTabs/deep-link). O menu é a UNIÃO
 * dos papéis acumulados (role_permissions). Configuração só para admin.
 * Navegação por hash, sem reload. canSee/locked/deep-link preservados.
 */
import { useEffect, useMemo, useState } from "react";

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
  /** Fonte das seções de navegação. Default = NAV_SECTIONS (painel operacional);
   *  a superfície admin passa ADMIN_NAV_SECTIONS. */
  sections?: NavSection[];
  /** Link para trocar de superfície (app↔admin). null oculta o item. */
  crossSurface?: { href: string; label: string } | null;
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
  sections = NAV_SECTIONS,
  crossSurface = null,
  collapsed,
  mobileOpen,
  onNavigate,
  onToggleCollapse,
  onLogout,
}: SidebarProps) {
  const admin = isAdmin(user.roles);
  // Branding do tenant (Missão 4): nome + logo da igreja no card "Sua igreja".
  // A marca do produto "Igreja 12" (topo) é outra coisa e não muda.
  const igrejaNome = user.igrejaNome?.trim() || "Igreja";
  const igrejaLogo = user.igrejaLogoUrl ?? null;
  const [logoFailed, setLogoFailed] = useState(false);
  // Se a igreja trocar/limpar a logo, re-tenta carregar (reseta o onError).
  useEffect(() => setLogoFailed(false), [igrejaLogo]);
  const showLogo = Boolean(igrejaLogo) && !logoFailed;
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

  // Seções visíveis (grupos adminOnly só para admin).
  const visibleSections = useMemo(
    () => sections.filter((s) => (s.adminOnly ? admin : true)),
    [sections, admin],
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

      <div
        className={`side-church${showLogo ? " has-logo" : ""}`}
        data-tip={igrejaNome}
      >
        {showLogo ? (
          // Com logo: só a logo horizontal da igreja, sem nome e sem subtítulo.
          <span className="church-logo">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={igrejaLogo!}
              alt={`Logo de ${igrejaNome}`}
              onError={() => setLogoFailed(true)}
            />
          </span>
        ) : (
          // Sem logo (ou falhou): nome da igreja. Iniciais só no menu colapsado.
          <>
            <span className="church-initials" aria-hidden="true">
              {initials(igrejaNome)}
            </span>
            <span className="church-name lbl" title={igrejaNome}>
              {igrejaNome}
              {user.isOwner ? (
                <span className="owner-seal" title="Dono da conta (admin principal)">
                  Dono
                </span>
              ) : null}
            </span>
          </>
        )}
      </div>

      <div className="nav-scroll">
        {crossSurface ? (
          <div className="nav-group">
            <a
              className="nav-item"
              href={crossSurface.href}
              data-tip={crossSurface.label}
              data-accent="whats"
            >
              <span className="nav-ic" aria-hidden="true">
                <Icon name="lock" />
              </span>
              <span className="lbl">{crossSurface.label}</span>
            </a>
          </div>
        ) : null}
        {visibleSections.map(renderSection)}
      </div>

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
