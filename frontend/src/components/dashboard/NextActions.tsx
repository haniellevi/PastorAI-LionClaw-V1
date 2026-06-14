/**
 * data-next-actions — próximas ações por responsável.
 * Agrupa os itens da fila pelo responsável atual e mostra a contagem de
 * pendências por pessoa (itens sem responsável caem em "Não atribuídos").
 */
import type { TeamMember, WorkItem } from "@/lib/dashboard-api";
import { normalizeRoles, primaryRoleLabel } from "@/lib/roles";

import { StatusPill, type PillTone } from "./StatusPill";

function initials(nome: string): string {
  const parts = nome.trim().split(/\s+/).filter(Boolean);
  const first = parts[0];
  if (!first) return "?";
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  const last = parts[parts.length - 1] ?? first;
  return ((first[0] ?? "") + (last[0] ?? "")).toUpperCase();
}

function countTone(n: number): PillTone {
  if (n >= 5) return "warn";
  if (n >= 2) return "accent";
  return "muted";
}

interface Group {
  key: string;
  nome: string;
  papelLabel: string;
  count: number;
}

export function NextActions({
  items,
  members,
}: {
  items: WorkItem[];
  members: TeamMember[];
}) {
  const byId = new Map<string, TeamMember>(members.map((m) => [m.usuarioId, m]));

  const counts = new Map<string, number>();
  for (const item of items) {
    const key = item.responsavelId ?? "__unassigned__";
    counts.set(key, (counts.get(key) ?? 0) + 1);
  }

  const groups: Group[] = [];
  for (const [key, count] of counts) {
    if (key === "__unassigned__") {
      groups.push({ key, nome: "Não atribuídos", papelLabel: "Fila aberta", count });
      continue;
    }
    const member = byId.get(key);
    groups.push({
      key,
      nome: member?.nome ?? "Responsável",
      papelLabel: member ? primaryRoleLabel(normalizeRoles(member.papeis)) : "—",
      count,
    });
  }

  // Mais pendências primeiro; "Não atribuídos" sempre por último.
  groups.sort((a, b) => {
    if (a.key === "__unassigned__") return 1;
    if (b.key === "__unassigned__") return -1;
    return b.count - a.count;
  });

  return (
    <div className="card">
      <div className="panel-title">Próximas ações por responsável</div>
      {groups.length === 0 ? (
        <div className="list-row">
          <span className="sub">Nenhuma pendência atribuída.</span>
        </div>
      ) : (
        <div>
          {groups.map((g) => (
            <div className="list-row" key={g.key}>
              <span className="avatar">{g.key === "__unassigned__" ? "—" : initials(g.nome)}</span>
              <div style={{ flex: 1 }}>
                <div className="nm">{g.nome}</div>
                <div className="sub">{g.papelLabel}</div>
              </div>
              <StatusPill tone={countTone(g.count)}>
                {g.count} {g.count === 1 ? "aberta" : "abertas"}
              </StatusPill>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
