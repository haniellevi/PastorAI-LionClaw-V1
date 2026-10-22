"use client";

import { useCallback, useEffect, useState } from "react";
import { Dialog } from "@/components/ds/Dialog";
import { LookupPager } from "@/components/lookups/LookupPager";
import { useLookupPage } from "@/components/lookups/useLookupPage";
import { fetchContactLookupPage, type ContactLookup } from "@/lib/lookup-api";
import { linkPessoa } from "@/lib/team-api";
import type { TeamMember } from "@/lib/dashboard-api";

export function TeamPessoaDialog({ member, token, onClose, onSaved, onSessionError }: {
  member: TeamMember; token: string; onClose: () => void;
  onSaved: () => void; onSessionError: (error: unknown) => boolean;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<ContactLookup | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const loader = useCallback((q: string, page: number, signal: AbortSignal) =>
    fetchContactLookupPage(token, { q, page, signal }), [token]);
  const lookup = useLookupPage(loader, query, true);
  useEffect(() => {
    if (lookup.error) onSessionError(lookup.error);
  }, [lookup.error, onSessionError]);

  async function save(pessoaId: string | null) {
    if (saving) return;
    setSaving(true); setError(null);
    try {
      await linkPessoa(token, member.usuarioId, pessoaId);
      onSaved();
    } catch (err) {
      if (!onSessionError(err)) setError(err instanceof Error ? err.message : "Não foi possível salvar o vínculo.");
    } finally { setSaving(false); }
  }

  return <Dialog open title={`Vincular Pessoa · ${member.nome}`}
    description="O vínculo dá ao telefone cadastrado nesta Pessoa a identidade deste usuário no WhatsApp. Confira a quem pertence o número antes de salvar."
    onClose={() => { if (!saving) onClose(); }}>
    <p>Associe esta conta a uma Pessoa ativa. Os papéis e o acesso ao painel permanecem iguais.</p>
    <p>{member.pessoaId ? "Esta conta possui Pessoa vinculada." : "Esta conta ainda não possui Pessoa vinculada."}</p>
    <label htmlFor="team-pessoa-query">Buscar Pessoa</label>
    <input id="team-pessoa-query" value={query} disabled={saving}
      onChange={(e) => { setQuery(e.target.value); setSelected(null); }} />
    {lookup.loading ? <p role="status">Carregando Pessoas…</p> : null}
    {lookup.error ? <div role="alert">Não foi possível buscar Pessoas. <button type="button" onClick={lookup.retry}>Tentar novamente</button></div> : null}
    {!lookup.loading && !lookup.error && !lookup.result?.items.length ? <p>Nenhuma Pessoa encontrada.</p> : null}
    <div aria-label="Pessoas encontradas">
      {!lookup.loading && !lookup.error ? lookup.result?.items.map((person) =>
        <button key={person.id} type="button" className="btn btn-sm" disabled={saving || person.arquivada || person.semInteresse}
          aria-pressed={selected?.id === person.id} onClick={() => setSelected(person)}>{person.nome}</button>) : null}
    </div>
    <LookupPager result={lookup.result} loading={lookup.loading || saving} onPage={(page) => { setSelected(null); lookup.setPage(page); }} />
    {selected ? <p role="status">Pessoa selecionada: {selected.nome}</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    <div className="modal-foot">
      <button type="button" className="btn" disabled={saving} onClick={onClose}>Cancelar</button>
      {member.pessoaId ? <button type="button" className="btn" disabled={saving} onClick={() => void save(null)}>Desvincular Pessoa</button> : null}
      <button type="button" className="btn btn-primary" disabled={saving || !selected || lookup.loading || !!lookup.error}
        aria-busy={saving} onClick={() => { if (selected) void save(selected.id); }}>{saving ? "Salvando…" : "Salvar vínculo"}</button>
    </div>
  </Dialog>;
}
