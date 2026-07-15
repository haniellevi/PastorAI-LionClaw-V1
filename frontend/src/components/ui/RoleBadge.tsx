/**
 * role-badge — pílula compartilhada para papéis acumulados (user_roles).
 * Consolida .rchip (Topbar) e .rt (RolePick/RoleTags — telas #equipe), que
 * divergiam em cor (teal legado --accent) e tamanho de fonte (11px). Fonte
 * única de verdade visual pro papel de usuário (Wave Visual W2).
 */
import { ROLE_DEFS, sortedRoles, type Role } from "@/lib/roles";

export function RoleBadge({ role }: { role: Role }) {
  const def = ROLE_DEFS[role];
  return <span className={`role-chip${def.lead ? " lead" : ""}`}>{def.label}</span>;
}

export function RoleBadgeList({ roles }: { roles: Role[] }) {
  return (
    <div className="role-chip-row">
      {sortedRoles(roles).map((r) => (
        <RoleBadge role={r} key={r} />
      ))}
    </div>
  );
}
