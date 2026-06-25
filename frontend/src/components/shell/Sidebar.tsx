"use client";

/**
 * sidebar-nav (contrato 4.3 / seção 4.2).
 * Monta o menu pela UNIÃO dos papéis acumulados, usando role_permissions
 * (permissions.ts) como fonte de verdade. Grupo Configuração só aparece para
 * admin. Estados default/active; navegação por hash sem reload.
 */
import { useEffect, useMemo, useState } from "react";

import type { SessionUser } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { NAV_SECTIONS, type NavItem, type NavSection } from "@/lib/navigation";
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

  // Seções visíveis (Configuração apenas para admin + telas liberadas).
  const sections = useMemo(
    () => NAV_SECTIONS.filter((s) => (s.adminOnly ? admin : true)),
    [admin],
  );

  const [openSections, setOpenSections] = useState<Set<string>>(
    () => new Set(NAV_SECTIONS.filter((s) => s.defaultOpen).map((s) => s.id)),
  );
  const [openStages, setOpenStages] = useState<Set<string>>(() => new Set());

  // Auto-expande a seção/estágio que contém a rota ativa.
  useEffect(() => {
    for (const section of NAV_SECTIONS) {
      const inItems = section.items?.some((i) => i.target === route);
      const stage = section.stages?.find(
        (st) => st.head.target === route || st.subs?.some((sub) => sub.target === route),
      );
      if (inItems || stage) {
        setOpenSections((prev) => (prev.has(section.id) ? prev : new Set(prev).add(section.id)));
      }
      if (stage) {
        setOpenStages((prev) =>
          prev.has(stage.stage) ? prev : new Set(prev).add(stage.stage),
        );
      }
    }
  }, [route]);

  function toggleSection(id: string) {
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleStage(id: string) {
    setOpenStages((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function renderItem(item: NavItem, kind: "item" | "sub") {
    const classes = [
      "nav-item",
      kind === "sub" ? "nav-sub" : "",
      item.locked ? "locked" : "",
      !item.locked && route === item.target ? "active" : "",
    ]
      .filter(Boolean)
      .join(" ");

    return (
      <button
        key={`${kind}-${item.target}-${item.label}`}
        type="button"
        className={classes}
        data-tip={item.label}
        aria-current={!item.locked && route === item.target ? "page" : undefined}
        aria-disabled={item.locked || undefined}
        onClick={() => {
          if (!item.locked) onNavigate(item.target);
        }}
      >
        <Icon name={item.icon} />
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

  function renderSectionBody(section: NavSection) {
    const items = (section.items ?? []).filter((i) => visible(i.target) || i.locked);
    const stages = (section.stages ?? []).filter((st) => {
      const headVisible = visible(st.head.target);
      const anySub = st.subs?.some((sub) => visible(sub.target) || sub.locked);
      return headVisible || anySub;
    });

    return (
      <>
        {items.map((i) => renderItem(i, "item"))}
        {stages.map((st) => {
          const headActive = route === st.head.target;
          const stageOpen = openStages.has(st.stage);
          const hasSubs = (st.subs ?? []).length > 0;
          const subs = (st.subs ?? []).filter((sub) => visible(sub.target) || sub.locked);
          return (
            <div
              key={st.stage}
              className={`stage${stageOpen ? " open" : ""}`}
              data-stage={st.stage}
            >
              <button
                type="button"
                className={`nav-stage${headActive ? " active" : ""}`}
                data-tip={st.head.label}
                aria-current={headActive ? "page" : undefined}
                onClick={() => {
                  if (hasSubs) toggleStage(st.stage);
                  onNavigate(st.head.target);
                }}
              >
                <span className="st-bar" aria-hidden="true" />
                <Icon name={st.head.icon} className="st-ic" />
                <span className="lbl">{st.head.label}</span>
                {hasSubs ? <Icon name="caret" className="st-caret" /> : null}
              </button>
              {subs.map((sub) => renderItem(sub, "sub"))}
            </div>
          );
        })}
      </>
    );
  }

  function isSectionVisible(section: NavSection): boolean {
    const anyItem = section.items?.some((i) => visible(i.target) || i.locked);
    const anyStage = section.stages?.some(
      (st) => visible(st.head.target) || st.subs?.some((sub) => visible(sub.target) || sub.locked),
    );
    return Boolean(anyItem || anyStage);
  }

  return (
    <nav className={`sidebar${collapsed ? " collapsed" : ""}${mobileOpen ? " open" : ""}`}>
      <div className="side-top">
        <div className="side-brand">
          <span className="brand-mark">
            <Icon name="brand" />
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

      <div className="nav-scroll">
        {sections
          .filter((s) => !s.adminOnly && isSectionVisible(s))
          .map((section) => {
            const open = openSections.has(section.id);
            return (
              <section key={section.id} className={`navsec${open ? " open" : ""}`}>
                <button
                  type="button"
                  className="navsec-head"
                  aria-expanded={open}
                  onClick={() => toggleSection(section.id)}
                >
                  <span className="lbl">{section.label}</span>
                  <Icon name="caret" className="sec-caret" />
                </button>
                <div className="navsec-body">{renderSectionBody(section)}</div>
              </section>
            );
          })}
      </div>

      {admin
        ? sections
            .filter((s) => s.adminOnly && isSectionVisible(s))
            .map((section) => {
              const open = openSections.has(section.id);
              return (
                <div className="nav-config" key={section.id}>
                  <section className={`navsec${open ? " open" : ""}`}>
                    <button
                      type="button"
                      className="navsec-head"
                      aria-expanded={open}
                      onClick={() => toggleSection(section.id)}
                    >
                      <span className="lbl">{section.label}</span>
                      <Icon name="caret" className="sec-caret" />
                    </button>
                    <div className="navsec-body">{renderSectionBody(section)}</div>
                  </section>
                </div>
              );
            })
        : null}

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
