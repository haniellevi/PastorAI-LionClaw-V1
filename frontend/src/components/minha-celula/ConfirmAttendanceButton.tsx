"use client";

/**
 * US-02 — confirmação de presença em 1 toque (discípulo). Otimista: alterna o
 * estado local ANTES da resposta e faz rollback se a chamada falhar. Idempotente
 * no backend (confirmar/reverter). 409 (reunião já ocorreu) devolve o botão ao
 * estado anterior e mostra o motivo por toast.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import {
  confirmAttendance,
  revertAttendance,
  MeetingConflictError,
} from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

export function ConfirmAttendanceButton({
  token,
  reuniaoId,
  disabled = false,
  initialConfirmed = false,
  onToast,
}: {
  token: string;
  reuniaoId: string;
  disabled?: boolean;
  /** Estado inicial derivado do backend (minha_presenca === "confirmou"), para
   *  o botão já nascer verde após reload/em outro aparelho (PRD 4.4). */
  initialConfirmed?: boolean;
  onToast: FlashToast;
}) {
  const [confirmed, setConfirmed] = useState(initialConfirmed);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    if (busy || disabled) return;
    const next = !confirmed;
    // Otimista: aplica já e guarda o valor anterior para rollback.
    setConfirmed(next);
    setBusy(true);
    try {
      const result = next
        ? await confirmAttendance(token, reuniaoId)
        : await revertAttendance(token, reuniaoId);
      // Alinha ao valor autoritativo do backend (E5).
      setConfirmed(result.minha_presenca === "confirmou");
      if (next) onToast({ kind: "ok", text: "Presença confirmada." });
      else onToast({ kind: "ok", text: "Confirmação desfeita." });
    } catch (err) {
      setConfirmed(!next); // rollback
      const text =
        err instanceof MeetingConflictError
          ? err.message
          : err instanceof ApiError
            ? err.message
            : "Não foi possível atualizar sua presença.";
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    // Gate 9 (P6): a AÇÃO a tomar é a primária — azul mineral enquanto
    // pendente; confirmado vira estado quieto (check + aria-pressed).
    <Button
      variant={confirmed ? "default" : "primary"}
      onClick={() => void toggle()}
      disabled={disabled}
      loading={busy}
      loadingText={confirmed ? "Confirmando…" : "Desfazendo…"}
      aria-pressed={confirmed}
    >
      <Icon name={confirmed ? "check" : "user"} />
      <span>{confirmed ? "Presença confirmada" : "Confirmar presença"}</span>
    </Button>
  );
}
