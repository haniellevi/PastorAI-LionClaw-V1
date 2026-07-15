"use client";

/**
 * role-pick — seleção múltipla de papéis ministeriais acumulados (telas #equipe).
 * Portado do artifact travado (.role-pick). Cada papel marca/desmarca de forma
 * independente, refletindo a UNIÃO de user_roles (F3).
 */
import { RoleBadgeList } from "@/components/ui/RoleBadge";
import { ROLE_DEFS, type Role } from "@/lib/roles";

export interface RolePickProps {
  /** Papéis disponíveis para seleção (ordem de exibição). */
  options: Role[];
  /** Papéis atualmente selecionados. */
  selected: Set<Role>;
  onToggle: (role: Role, on: boolean) => void;
  disabled?: boolean;
}

export function RolePick({ options, selected, onToggle, disabled }: RolePickProps) {
  return (
    <div className="role-pick">
      {options.map((role) => {
        const on = selected.has(role);
        const def = ROLE_DEFS[role];
        return (
          <label key={role} className={on ? "on" : ""}>
            <input
              type="checkbox"
              value={role}
              checked={on}
              disabled={disabled}
              onChange={(e) => onToggle(role, e.target.checked)}
            />
            <span>{def.label}</span>
            <span className="rk">{def.lead ? "liderança" : "membro"}</span>
          </label>
        );
      })}
    </div>
  );
}

/** role-tags — papéis acumulados exibidos como pílulas (ordenados). */
export function RoleTags({ roles }: { roles: Role[] }) {
  return <RoleBadgeList roles={roles} />;
}
