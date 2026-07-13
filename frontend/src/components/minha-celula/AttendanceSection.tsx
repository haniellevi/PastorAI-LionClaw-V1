"use client";

/**
 * US-07 — presença REAL da reunião (líder). Um toggle de comparecimento por
 * membro ativo da célula; salva tudo de uma vez via setRealAttendance (upsert
 * idempotente). Prefill a partir das presenças consolidadas (estado 'compareceu').
 * Bloqueado quando o relatório já foi enviado (E10/E11).
 */
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Toggle } from "@/components/ui/Toggle";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { setRealAttendance } from "@/lib/cell-meetings-api";
import type { CellMember } from "@/lib/cells-api";
import type { ReportPresenca } from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

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

  const present = Object.values(state).filter(Boolean).length;

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
    <section className="card" aria-label="Presença">
      <div className="panel-title">
        <Icon name="team" /> Presença
        {members.length ? (
          <span className="count">· {present}/{members.length}</span>
        ) : null}
      </div>

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
          <div>
            {members.map((m) => (
              <div className="list-row" key={m.pessoa_id}>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="nm">{m.nome}</div>
                </div>
                <Toggle
                  checked={!!state[m.pessoa_id]}
                  onChange={(v) => setState((s) => ({ ...s, [m.pessoa_id]: v }))}
                  label={`Presença de ${m.nome}`}
                  disabled={locked || busy}
                />
              </div>
            ))}
          </div>
          {!locked ? (
            <div className="section-actions">
              <Button
                variant="default"
                size="sm"
                onClick={() => void save()}
                loading={busy}
                loadingText="Salvando…"
              >
                <Icon name="check" />
                <span>Salvar presença</span>
              </Button>
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
