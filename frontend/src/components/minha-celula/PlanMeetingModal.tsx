"use client";

/**
 * US-06 — planejar uma reunião PONTUAL da célula (data/hora/tema). Deixa claro
 * que isto NÃO altera o dia/horário PADRÃO da célula (esse é campo sensível e
 * muda por Solicitação — RF-14). Formulário controlado à mão: data obrigatória,
 * hora opcional (HH:MM) e tema opcional. Envia via planMeeting (snake_case).
 */
import { useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { planMeeting, type LeaderMeetingOut } from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

const HORA_RE = /^([01][0-9]|2[0-3]):[0-5][0-9]$/;

export function PlanMeetingModal({
  token,
  cellId,
  onClose,
  onToast,
  onPlanned,
}: {
  token: string;
  cellId: string;
  onClose: () => void;
  onToast: FlashToast;
  onPlanned: (meeting: LeaderMeetingOut) => void;
}) {
  const [data, setData] = useState("");
  const [hora, setHora] = useState("");
  const [tema, setTema] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);

  const dataError = touched && !data ? "Informe a data da reunião." : undefined;
  const horaError =
    hora.trim() && !HORA_RE.test(hora.trim())
      ? "Use o formato 24h HH:MM (ex.: 20:00)."
      : undefined;

  async function submit() {
    setTouched(true);
    if (!data) return;
    if (hora.trim() && !HORA_RE.test(hora.trim())) return;
    setBusy(true);
    setError(null);
    try {
      const created = await planMeeting(token, {
        celula_id: cellId,
        data,
        hora: hora.trim() || null,
        tema: tema.trim() || null,
      });
      onToast({ kind: "ok", text: "Reunião planejada." });
      onPlanned(created);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Não foi possível planejar a reunião.",
      );
    } finally {
      setBusy(false);
    }
  }

  const title = "Planejar reunião";

  return (
    // Gate 9: shell migrado mecanicamente para o DsDialog (Esc/trap/
    // backdrop/retorno de foco do primitive; fechar bloqueado em busy).
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title={title}
      description="Cria uma reunião pontual. Não altera o dia e o horário padrão da célula — para mudar o padrão, use “Solicitar alteração”."
    >
      <>


      {error ? <DsBanner kind="error">{error}</DsBanner> : null}

        <form
          className="modal-form"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="row">
            <Field
              label="Data"
              type="date"
              value={data}
              onChange={(e) => setData(e.target.value)}
              error={dataError}
              disabled={busy}
              data-autofocus=""
            />
            <Field
              label="Horário (opcional)"
              placeholder="Ex.: 20:00"
              value={hora}
              onChange={(e) => setHora(e.target.value)}
              error={horaError}
              disabled={busy}
              maxLength={5}
              inputMode="numeric"
            />
          </div>

          <Field
            label="Tema (opcional)"
            placeholder="Ex.: A parábola do semeador"
            value={tema}
            onChange={(e) => setTema(e.target.value)}
            disabled={busy}
            maxLength={200}
          />

          <div className="modal-foot">
            <DsButton variant="tertiary" onClick={onClose} disabled={busy}>
              Cancelar
            </DsButton>
            <DsButton type="submit" loading={busy} disabled={!data}>
              <Icon name="calendar" />
              <span>{busy ? "Planejando…" : "Planejar reunião"}</span>
            </DsButton>
          </div>
        </form>
      </>
    </DsDialog>
  );
}
