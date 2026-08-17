"use client";

/**
 * US-07 — presença REAL da reunião (líder). Um toggle de comparecimento por
 * membro ativo da célula; salva tudo de uma vez via setRealAttendance (upsert
 * idempotente). Prefill a partir das presenças consolidadas (estado 'compareceu').
 * Bloqueado quando o relatório já foi enviado (E10/E11).
 */
import { useMemo, useState } from "react";

import { DsButton } from "@/components/ds/Button";
import { Toggle } from "@/components/ui/Toggle";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { setRealAttendance } from "@/lib/cell-meetings-api";
import type { CellMember } from "@/lib/cells-api";
import type { ReportPresenca } from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

function personLabel(name: string): { primary: string; secondary: string | null; initials: string } {
  const trimmed = name.trim();
  if (/^\+?[\d\s().-]{8,}$/.test(trimmed)) {
    return { primary: "Contato sem nome", secondary: trimmed, initials: "?" };
  }
  const parts = trimmed.split(/\s+/).filter(Boolean);
  const initials = parts.length > 1
    ? `${parts[0]![0] ?? ""}${parts.at(-1)?.[0] ?? ""}`
    : trimmed.slice(0, 2);
  return { primary: trimmed || "Pessoa sem nome", secondary: null, initials: initials.toUpperCase() || "?" };
}

export function AttendanceSection({
  token,
  reuniaoId,
  members,
  presencas,
  locked,
  onToast,
  onChanged,
}: {
  token: string;
  reuniaoId: string;
  members: CellMember[];
  presencas: ReportPresenca[];
  locked: boolean;
  onToast: FlashToast;
  onChanged: () => void;
}) {
  const initial = useMemo(() => {
    const map: Record<string, boolean> = {};
    for (const m of members) {
      const p = presencas.find((x) => x.pessoa_id === m.pessoa_id);
      map[m.pessoa_id] = p?.estado === "compareceu";
    }
    return map;
  }, [members, presencas]);

  const [state, setState] = useState<Record<string, boolean>>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await setRealAttendance(
        token,
        reuniaoId,
        members.map((m) => ({ pessoa_id: m.pessoa_id, compareceu: !!state[m.pessoa_id] })),
      );
      onToast({ kind: "ok", text: "Presença salva." });
      onChanged();
    } catch (err) {
      const text = err instanceof ApiError ? err.message : "Não foi possível salvar a presença.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mc-report-section-content">
      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      {members.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="team" />
          <p>
            <strong>Nenhum membro na célula ainda.</strong>
          </p>
        </div>
      ) : (
        <>
          <div className="mc-attendance-grid">
            {members.map((m, index) => {
              const label = personLabel(m.nome);
              return (
                <div className="list-row" key={m.pessoa_id}>
                  <span className={`mc-person-avatar tone-${index % 4}`} aria-hidden="true">
                    {label.initials}
                  </span>
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div className="nm">{label.primary}</div>
                    {label.secondary ? <div className="sub">{label.secondary}</div> : null}
                  </div>
                  <Toggle
                    checked={!!state[m.pessoa_id]}
                    onChange={(v) => setState((s) => ({ ...s, [m.pessoa_id]: v }))}
                    label={`Presença de ${label.primary}${label.secondary ? `, telefone ${label.secondary}` : ""}`}
                    disabled={locked || busy}
                  />
                </div>
              );
            })}
          </div>
          {!locked ? (
            <div className="section-actions">
              <DsButton
                variant="primary"
                onClick={() => void save()}
                loading={busy}
              >
                <Icon name="check" />
                <span>{busy ? "Salvando presença…" : "Salvar presença"}</span>
              </DsButton>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
