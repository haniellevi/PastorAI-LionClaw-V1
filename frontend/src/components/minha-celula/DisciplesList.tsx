"use client";

/**
 * US-12 — discípulos da célula (líder). Lista os membros com estado (ativo/inativo).
 * Campos SENSÍVEIS (transferir/remover membro, anfitrião/auxiliar) NÃO são editados
 * direto: abrem a Solicitação de alteração (RF-14) via onRequestSensitive. Empty:
 * "Nenhum discípulo na célula ainda.".
 */
import { Button } from "@/components/ui/Button";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import type { CellMember } from "@/lib/cells-api";
import type { CellRequestType } from "@/lib/cell-requests-api";

export function DisciplesList({
  members,
  onRequestSensitive,
}: {
  members: CellMember[];
  onRequestSensitive: (tipo: CellRequestType, member: CellMember) => void;
}) {
  const active = members.filter((m) => m.ativo);

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
              {m.ativo ? (
                <div className="row-actions">
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => onRequestSensitive("transferir_membro", m)}
                    title="Solicitar transferência (campo sensível)"
                  >
                    <Icon name="transfer" />
                    <span>Transferir</span>
                  </Button>
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => onRequestSensitive("remover_membro", m)}
                    title="Solicitar remoção (campo sensível)"
                  >
                    <Icon name="trash" />
                    <span>Remover</span>
                  </Button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}

      {active.length ? (
        <div className="section-foot muted-note">
          Alterações de membros passam por aprovação da Central.
        </div>
      ) : null}
    </section>
  );
}
