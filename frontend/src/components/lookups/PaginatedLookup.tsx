"use client";

import { useEffect, useState } from "react";
import { SessionExpiredError } from "@/lib/api";
import { useLookupPage, type LookupLoader } from "./useLookupPage";
import { LookupPager } from "./LookupPager";

export function PaginatedLookup<T extends { id: string }>({
  loadPage, selected, onSelect, label, inputId, getLabel, getDescription, isDisabled,
  onSessionExpired, disabled = false, allowClear = false,
}: {
  loadPage: LookupLoader<T>; selected: T | null; onSelect: (value: T | null) => void;
  label: string; inputId: string; getLabel: (value: T) => string;
  getDescription?: (value: T) => string | null; isDisabled?: (value: T) => boolean;
  onSessionExpired?: () => void; disabled?: boolean; allowClear?: boolean;
}) {
  const [query, setQuery] = useState("");
  const lookup = useLookupPage(loadPage, query, !disabled);
  useEffect(() => { if (lookup.error instanceof SessionExpiredError) onSessionExpired?.(); }, [lookup.error, onSessionExpired]);
  return <div className="field">
    <label htmlFor={inputId}>{label}</label>
    <input id={inputId} type="search" value={query} onChange={(event) => setQuery(event.target.value)} disabled={disabled} placeholder="Buscar por nome…" />
    {selected ? <p role="status" className="sub">Selecionada: <strong>{getLabel(selected)}</strong></p> : null}
    {allowClear && selected ? <button type="button" className="btn btn-sm" onClick={() => onSelect(null)} disabled={disabled}>Limpar seleção</button> : null}
    {lookup.error ? <div role="alert">{lookup.error instanceof Error ? lookup.error.message : "Não foi possível carregar as opções."} <button type="button" className="btn btn-sm" onClick={lookup.retry}>Tentar novamente</button></div> : null}
    {lookup.loading ? <p role="status" className="sub">Carregando opções…</p> : <div style={{ maxHeight: 220, overflowY: "auto" }}>
      {lookup.result?.items.map((item) => <button key={item.id} type="button" className="btn" style={{ display: "block", width: "100%", textAlign: "left", marginTop: 4 }}
        disabled={disabled || isDisabled?.(item)} aria-pressed={selected?.id === item.id} onClick={() => onSelect(item)}>
        {getLabel(item)}{getDescription?.(item) ? <span className="sub"> · {getDescription(item)}</span> : null}
      </button>)}
      {lookup.result?.items.length === 0 ? <p className="sub">Nenhum resultado encontrado.</p> : null}
    </div>}
    <LookupPager result={lookup.result} loading={lookup.loading} onPage={lookup.setPage} />
  </div>;
}
