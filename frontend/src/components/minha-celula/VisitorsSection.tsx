"use client";

/**
 * US-08 — visitantes da reunião (líder). Dois caminhos:
 *   1) Confirmar um visitante ESPERADO (expectativa indicada por um membro),
 *      vinculando expectativa_id ao registro de presença;
 *   2) Registrar um visitante presente ad-hoc (nome + observação opcional).
 * Lista os visitantes já registrados. Bloqueado após o relatório enviado.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { registerVisitor } from "@/lib/cell-meetings-api";
import type {
  ReportVisitante,
  VisitorExpectationItem,
} from "@/lib/cell-meetings-api";
import type { FlashToast } from "./types";

export function VisitorsSection({
  token,
  reuniaoId,
  expectations,
  visitors,
  locked,
  onToast,
  onChanged,
}: {
  token: string;
  reuniaoId: string;
  expectations: VisitorExpectationItem[];
  visitors: ReportVisitante[];
  locked: boolean;
  onToast: FlashToast;
  onChanged: () => void;
}) {
  const [nome, setNome] = useState("");
  const [obs, setObs] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const confirmedExpectationIds = new Set(
    visitors.map((v) => v.expectativa_id).filter(Boolean) as string[],
  );

  async function confirmExpected(exp: VisitorExpectationItem) {
    if (locked || busy || pendingId) return;
    setPendingId(exp.id);
    setError(null);
    try {
      await registerVisitor(token, reuniaoId, {
        nome_visitante: exp.nome_visitante,
        expectativa_id: exp.id,
      });
      onToast({ kind: "ok", text: `Visitante confirmado: ${exp.nome_visitante}.` });
      onChanged();
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível confirmar o visitante.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setPendingId(null);
    }
  }

  async function registerNew() {
    const trimmed = nome.trim();
    if (!trimmed) {
      setError("Informe o nome do visitante.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerVisitor(token, reuniaoId, {
        nome_visitante: trimmed,
        observacao: obs.trim() || null,
      });
      onToast({ kind: "ok", text: `Visitante registrado: ${trimmed}.` });
      setNome("");
      setObs("");
      onChanged();
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível registrar o visitante.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  const pendingExpectations = expectations.filter(
    (e) => !e.compareceu && !confirmedExpectationIds.has(e.id),
  );

  return (
    <section className="card" aria-label="Visitantes">
      <div className="panel-title">
        <Icon name="user" /> Visitantes
        {visitors.length ? <span className="count">· {visitors.length}</span> : null}
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="section-body">
        {/* Esperados a confirmar */}
        <div className="subhead">Esperados</div>
        {pendingExpectations.length === 0 ? (
          <p className="muted-note">Nenhum visitante esperado pendente.</p>
        ) : (
          <div>
            {pendingExpectations.map((e) => (
              <div className="list-row" key={e.id}>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="nm">{e.nome_visitante}</div>
                </div>
                {!locked ? (
                  <Button
                    variant="default"
                    size="sm"
                    onClick={() => void confirmExpected(e)}
                    loading={pendingId === e.id}
                    loadingText="Confirmando…"
                    disabled={busy || (pendingId !== null && pendingId !== e.id)}
                  >
                    <Icon name="check" />
                    <span>Confirmar presente</span>
                  </Button>
                ) : null}
              </div>
            ))}
          </div>
        )}

        {/* Registrados */}
        <div className="subhead">Registrados</div>
        {visitors.length === 0 ? (
          <p className="muted-note">Nenhum visitante registrado ainda.</p>
        ) : (
          <div>
            {visitors.map((v) => (
              <div className="list-row" key={v.id}>
                <div className="grow" style={{ minWidth: 0 }}>
                  <div className="nm">{v.nome_visitante}</div>
                  {v.observacao ? <div className="sub">{v.observacao}</div> : null}
                </div>
                {v.expectativa_id ? (
                  <StatusPill tone="accent">Esperado</StatusPill>
                ) : (
                  <StatusPill tone="muted">Ad-hoc</StatusPill>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Registrar novo */}
        {!locked ? (
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              void registerNew();
            }}
          >
            <div className="subhead">Registrar visitante presente</div>
            <Field
              label="Nome do visitante"
              placeholder="Ex.: João Pereira"
              value={nome}
              onChange={(e) => setNome(e.target.value)}
              disabled={busy}
              maxLength={120}
            />
            <div className="field">
              <label htmlFor={`vis-obs-${reuniaoId}`}>Observação (opcional)</label>
              <textarea
                id={`vis-obs-${reuniaoId}`}
                rows={2}
                value={obs}
                onChange={(e) => setObs(e.target.value)}
                disabled={busy}
                maxLength={500}
                placeholder="Algo relevante sobre a visita"
              />
            </div>
            <div className="section-actions">
              <Button
                type="submit"
                variant="default"
                size="sm"
                loading={busy}
                loadingText="Registrando…"
                disabled={!nome.trim()}
              >
                <Icon name="plus" />
                <span>Registrar visitante</span>
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}
