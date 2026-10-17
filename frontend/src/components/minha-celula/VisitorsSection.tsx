"use client";

/**
 * US-08 — visitantes da reunião (líder). Dois caminhos:
 *   1) Confirmar um visitante ESPERADO (expectativa indicada por um membro),
 *      vinculando expectativa_id ao registro de presença;
 *   2) Registrar presença vinculada à Pessoa selecionada por ID.
 * Lista os visitantes já registrados. Bloqueado após o relatório enviado.
 */
import { useCallback, useEffect, useState } from "react";

import { DsButton } from "@/components/ds/Button";
import { PaginatedLookup } from "@/components/lookups/PaginatedLookup";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { registerVisitor, lookupVisitorPeople, type VisitPerson } from "@/lib/cell-meetings-api";
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
  const [person, setPerson] = useState<VisitPerson | null>(null);
  const loadPeople = useCallback((q: string, page: number, signal: AbortSignal) => lookupVisitorPeople(token,reuniaoId,{q,page,signal}),[token,reuniaoId]);
  useEffect(() => setPerson(null), [token,reuniaoId]);
  const [obs, setObs] = useState("");
  const [busy, setBusy] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const confirmedExpectationIds = new Set(
    visitors.map((v) => v.expectativa_id).filter(Boolean) as string[],
  );

  async function confirmExpected(exp: VisitorExpectationItem) {
    if (locked || busy || pendingId || !person) return;
    setPendingId(exp.id);
    setError(null);
    try {
      await registerVisitor(token, reuniaoId, {
        pessoa_id: person.id,
        nome_visitante: person.nome,
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
    const trimmed = person?.nome ?? "";
    if (!trimmed) {
      setError("Selecione a pessoa e confira o telefone antes de registrar.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await registerVisitor(token, reuniaoId, {
        pessoa_id: person!.id,
        nome_visitante: trimmed,
        observacao: obs.trim() || null,
      });
      onToast({ kind: "ok", text: `Visitante registrado: ${trimmed}.` });
      setPerson(null);
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
    <div className="mc-report-section-content">
      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="section-body">
        {!locked ? <>
          <PaginatedLookup<VisitPerson> loadPage={loadPeople} selected={person} onSelect={setPerson}
            label="Buscar pessoa por nome ou telefone (mínimo 3 caracteres)" inputId={`visit-person-${reuniaoId}`}
            getLabel={p=>p.nome} getDescription={p=>p.telefone} disabled={busy || pendingId !== null} allowClear />
          <p className="muted-note">Confira o final do telefone. Nomes iguais não são associados automaticamente; esta seleção também vale para confirmar um esperado.</p>
        </> : null}
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
                  <DsButton
                    variant="secondary"
                    onClick={() => void confirmExpected(e)}
                    loading={pendingId === e.id}
                    disabled={!person || busy || (pendingId !== null && pendingId !== e.id)}
                  >
                    <Icon name="check" />
                    <span>{pendingId === e.id ? "Confirmando…" : "Confirmar presente"}</span>
                  </DsButton>
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
                  {v.origem ? <div className="sub">Visita de célula · responsável: {v.responsavel_nome ?? "Equipe"}</div> : null}
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
              <DsButton
                type="submit"
                variant="primary"
                loading={busy}
                disabled={!person}
              >
                <Icon name="plus" />
                <span>{busy ? "Registrando visitante…" : "Registrar visitante"}</span>
              </DsButton>
            </div>
          </form>
        ) : null}
      </div>
    </div>
  );
}
