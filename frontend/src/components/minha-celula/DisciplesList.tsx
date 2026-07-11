"use client";

/**
 * US-12 — discípulos da célula (líder), estritamente LEITURA. Lista os membros
 * com estado (ativo/inativo). A gestão de membros (entrada, transferência, saída)
 * é atribuição da Central de Célula (Jornada G12 → Discipular), não desta tela
 * (M7B-W1.3). Empty: "Nenhum discípulo na célula ainda.".
 */
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import type { CellMember } from "@/lib/cells-api";

export function DisciplesList({ members }: { members: CellMember[] }) {
  return (
    <section className="card" aria-label="Discípulos">
      <div className="panel-title">
        <Icon name="team" /> Discípulos
        {members.length ? <span className="count">· {members.length}</span> : null}
      </div>

      {members.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="team" />
          <p>
            <strong>Nenhum discípulo na célula ainda.</strong>
          </p>
        </div>
      ) : (
        <div>
          {members.map((m) => (
            <div className="list-row" key={m.pessoa_id}>
              <div className="grow" style={{ minWidth: 0 }}>
                <div className="nm">{m.nome}</div>
              </div>
              {m.ativo ? (
                <StatusPill tone="ok">Ativo</StatusPill>
              ) : (
                <StatusPill tone="muted">Inativo</StatusPill>
              )}
            </div>
          ))}
        </div>
      )}

      {members.length ? (
        <div className="section-foot muted-note">
          A gestão de membros é feita pela Central de Célula.
        </div>
      ) : null}
    </section>
  );
}
