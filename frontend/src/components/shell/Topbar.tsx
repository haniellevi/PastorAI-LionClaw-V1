"use client";

/**
 * Topbar do app shell: título/crumb da rota ativa, busca e chips de papéis
 * (papéis detectados no cadastro — união acumulada).
 */
import { InfoTip } from "@/components/ui/InfoTip";
import type { SessionUser } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { SCREEN_META, groupLabelForScreen } from "@/lib/navigation";
import { ROLE_DEFS, sortedRoles } from "@/lib/roles";

import { SHELL_DRAWER_ID } from "./useDrawerA11y";

interface TopbarProps {
  user: SessionUser;
  route: string;
  onMenuToggle: () => void;
  /** Renderiza o hambúrguer (≤860px). No app o "Mais" da bottom-nav é a
   *  entrada única do drawer (decisão F4); a superfície admin não tem
   *  bottom-nav, então precisa deste gatilho (Gate 6). */
  menuButton?: boolean;
  /** Estado do drawer (aria-expanded do hambúrguer — Gate 6.1). */
  menuOpen?: boolean;
}

export function Topbar({
  user,
  route,
  onMenuToggle,
  menuButton = false,
  menuOpen = false,
}: TopbarProps) {
  const meta = SCREEN_META[route] ?? { title: "Igreja 12", crumb: "" };
  const group = groupLabelForScreen(route);
  const roles = sortedRoles(user.roles);

  return (
    <header className="topbar">
      {menuButton ? (
        <button
          type="button"
          className="menu-toggle"
          aria-label="Abrir menu"
          aria-expanded={menuOpen}
          aria-controls={SHELL_DRAWER_ID}
          onClick={onMenuToggle}
        >
          <Icon name="menu" />
        </button>
      ) : null}
      <div className="tb-titles">
        {group ? <span className="tb-eyebrow">{group}</span> : null}
        <div className="tb-title-row">
          <h1>{meta.title}</h1>
          {meta.info ? <InfoTip text={meta.info} /> : null}
        </div>
      </div>
      <div className="search">
        <Icon name="search" />
        <input type="search" placeholder="Buscar contato, célula, conversa…" aria-label="Buscar" />
      </div>
      <div className="who" title="Papéis detectados no seu cadastro">
        {roles.map((r) => (
          <span className={`rchip${ROLE_DEFS[r].lead ? " lead" : ""}`} key={r}>
            {ROLE_DEFS[r].label}
          </span>
        ))}
      </div>
    </header>
  );
}
