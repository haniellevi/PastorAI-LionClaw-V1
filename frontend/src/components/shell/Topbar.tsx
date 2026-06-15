"use client";

/**
 * Topbar do app shell: título/crumb da rota ativa, busca e chips de papéis
 * (papéis detectados no cadastro — união acumulada).
 */
import { InfoTip } from "@/components/ui/InfoTip";
import type { SessionUser } from "@/lib/auth-context";
import { Icon } from "@/lib/icons";
import { SCREEN_META } from "@/lib/navigation";
import { ROLE_DEFS, sortedRoles } from "@/lib/roles";

interface TopbarProps {
  user: SessionUser;
  route: string;
  onMenuToggle: () => void;
}

export function Topbar({ user, route, onMenuToggle }: TopbarProps) {
  const meta = SCREEN_META[route] ?? { title: "Igreja 12", crumb: "" };
  const roles = sortedRoles(user.roles);

  return (
    <header className="topbar">
      <button type="button" className="menu-toggle" aria-label="Abrir menu" onClick={onMenuToggle}>
        <Icon name="menu" />
      </button>
      <h1>{meta.title}</h1>
      {meta.crumb ? <span className="crumb">{meta.crumb}</span> : null}
      {meta.info ? <InfoTip text={meta.info} /> : null}
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
