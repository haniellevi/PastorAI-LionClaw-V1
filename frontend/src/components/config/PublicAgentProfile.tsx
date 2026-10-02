"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { SessionExpiredError } from "@/lib/api";
import {
  fetchPublicAgentProfile,
  savePublicAgentProfile,
  type PublicAgentProfileFacts,
} from "@/lib/agent-api";
import { ApiError } from "@/lib/dashboard-api";

type Cell = PublicAgentProfileFacts["celulas"][number] & { id: number };
const EMPTY: PublicAgentProfileFacts = { enderecoIgreja: null, horariosCulto: null, celulas: [] };
const optional = (text: string) => text.trim() || null;

export function PublicAgentProfile({ token, expireSession }: { token: string; expireSession: () => void }) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [facts, setFacts] = useState<PublicAgentProfileFacts>(EMPTY);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [reload, setReload] = useState(0);
  const nextId = useRef(0);
  const scope = useMemo(() => ({ token, reload }), [token, reload]);
  const currentScope = useRef(scope);
  currentScope.current = scope;
  const [viewScope, setViewScope] = useState<typeof scope | null>(null);
  const scoped = viewScope === scope;
  const visibleFacts = scoped ? facts : EMPTY;
  const visibleCells = scoped ? cells : [];
  const busy = !scoped || loading;
  const canEdit = scoped && !loading && !saving && configured === true;

  useEffect(() => {
    let alive = true;
    setViewScope(scope);
    setConfigured(null);
    setFacts(EMPTY);
    setCells([]);
    setSuccess(false);
    setError(null);
    setSaving(false);
    setLoading(true);
    void fetchPublicAgentProfile(token).then(
      (result) => {
        if (!alive || currentScope.current !== scope) return;
        setConfigured(result.configured);
        setFacts(result.informacoesPublicas);
        setCells(result.informacoesPublicas.celulas.map((cell) => ({ ...cell, id: nextId.current++ })));
        setError(null);
        setLoading(false);
      },
      (reason: unknown) => {
        if (!alive || currentScope.current !== scope) return;
        if (reason instanceof SessionExpiredError) expireSession();
        else setError("Não foi possível carregar as informações públicas.");
        setLoading(false);
      },
    );
    return () => { alive = false; };
  }, [token, expireSession, scope]);

  const updateCell = (id: number, field: "bairro" | "nome" | "encontro", value: string) => {
    setCells((current) => current.map((cell) => cell.id === id ? { ...cell, [field]: value } : cell));
    setSuccess(false);
  };

  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canEdit || currentScope.current !== scope) return;
    const cleaned: PublicAgentProfileFacts = {
      enderecoIgreja: optional(facts.enderecoIgreja ?? ""),
      horariosCulto: optional(facts.horariosCulto ?? ""),
      celulas: cells.map(({ bairro, nome, encontro }) => ({
        bairro: bairro.trim(), nome: nome.trim(), encontro: optional(encontro ?? ""),
      })),
    };
    if (cleaned.celulas.some((cell) => !cell.bairro || !cell.nome)) {
      setError("Preencha bairro e nome em cada célula pública.");
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const result = await savePublicAgentProfile(token, cleaned);
      if (currentScope.current !== scope) return;
      setConfigured(result.configured);
      setFacts(result.informacoesPublicas);
      setCells(result.informacoesPublicas.celulas.map((cell) => ({ ...cell, id: nextId.current++ })));
      setSuccess(true);
    } catch (reason) {
      if (currentScope.current !== scope) return;
      if (reason instanceof SessionExpiredError) expireSession();
      else if (reason instanceof ApiError && reason.status === 409) {
        setConfigured(false);
        setError("Aguarde a configuração do agente pela plataforma antes de salvar.");
      } else {
        setError(reason instanceof ApiError ? reason.message : "Não foi possível salvar as informações públicas.");
      }
    } finally {
      if (currentScope.current === scope) setSaving(false);
    }
  };

  return (
    <form className="card card-pad" style={{ marginTop: "var(--s4)" }} onSubmit={(event) => { void submit(event); }}>
      <div className="panel-title">Informações públicas da igreja</div>
      <p className="sub">Publique somente dados institucionais aprovados. Não inclua telefone, líder ou endereço residencial. Salvar não ativa o agente.</p>
      {busy ? <p role="status">Carregando informações públicas…</p> : null}
      {scoped && !loading && configured === false ? <p role="status">Aguarde a configuração do agente pela plataforma para editar estas informações.</p> : null}
      {scoped && error ? <div className="error-banner" role="alert">{error}</div> : null}
      {scoped && !loading && configured === null ? <button type="button" className="btn" onClick={() => setReload((value) => value + 1)}>Tentar novamente</button> : null}
      <fieldset disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
        <div className="field">
          <label htmlFor="publicEndereco">Endereço institucional da igreja</label>
          <input id="publicEndereco" maxLength={400} value={visibleFacts.enderecoIgreja ?? ""} onChange={(event) => { setFacts((current) => ({ ...current, enderecoIgreja: event.target.value })); setSuccess(false); }} />
        </div>
        <div className="field">
          <label htmlFor="publicHorarios">Horários dos cultos</label>
          <textarea id="publicHorarios" rows={2} maxLength={400} value={visibleFacts.horariosCulto ?? ""} onChange={(event) => { setFacts((current) => ({ ...current, horariosCulto: event.target.value })); setSuccess(false); }} />
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>
          <legend className="panel-title">Células públicas por bairro</legend>
          {visibleCells.length === 0 ? <p className="sub">Nenhuma célula publicada. Adicione uma se a igreja quiser indicar uma por bairro.</p> : null}
          {visibleCells.map((cell, index) => (
            <div key={cell.id} className="admin-inline-section" style={{ marginBottom: "var(--s3)" }}>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <div className="field" style={{ minWidth: "min(100%, 12rem)" }}>
                  <label htmlFor={`publicBairro${index}`}>Bairro da célula {index + 1}</label>
                  <input id={`publicBairro${index}`} maxLength={400} value={cell.bairro} onChange={(event) => updateCell(cell.id, "bairro", event.target.value)} />
                </div>
                <div className="field" style={{ minWidth: "min(100%, 12rem)" }}>
                  <label htmlFor={`publicNome${index}`}>Nome da célula {index + 1}</label>
                  <input id={`publicNome${index}`} maxLength={400} value={cell.nome} onChange={(event) => updateCell(cell.id, "nome", event.target.value)} />
                </div>
                <div className="field" style={{ minWidth: "min(100%, 12rem)" }}>
                  <label htmlFor={`publicEncontro${index}`}>Dia e horário do encontro {index + 1} (opcional)</label>
                  <input id={`publicEncontro${index}`} maxLength={400} placeholder="terça, 19h" value={cell.encontro ?? ""} onChange={(event) => updateCell(cell.id, "encontro", event.target.value)} />
                </div>
              </div>
              <button type="button" className="btn" onClick={() => { setCells((current) => current.filter((item) => item.id !== cell.id)); setSuccess(false); }}>Remover célula {index + 1}</button>
            </div>
          ))}
          <button type="button" className="btn" disabled={visibleCells.length >= 5} onClick={() => { setCells((current) => [...current, { id: nextId.current++, bairro: "", nome: "", encontro: null }]); setSuccess(false); }}>Adicionar célula</button>
        </fieldset>
        <div style={{ marginTop: "var(--s4)" }}>
          <button type="submit" className="btn btn-primary" disabled={!canEdit} aria-busy={saving || undefined}>{saving ? "Salvando…" : "Salvar informações públicas"}</button>
        </div>
      </fieldset>
      {scoped && success ? <p role="status">Informações públicas salvas.</p> : null}
    </form>
  );
}
