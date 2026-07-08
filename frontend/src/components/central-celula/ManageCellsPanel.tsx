"use client";

/**
 * Aba "Gerenciar células" da Central. Além das três listas de acompanhamento
 * (saúde US-18, relatórios pendentes US-16, multiplicações US-19), é AQUI que
 * a Central cadastra célula (PRD Central §6 / onboarding PR-O1): botão "Nova
 * célula" no topo e, quando a igreja ainda não tem célula, empty state com o
 * CTA "Criar primeira célula". Reusa o CellFormModal da tela legada #celulas;
 * permissão e elegibilidade continuam no backend (403/409/422 aparecem como
 * erro inline no modal).
 *
 * PR-A1.1: lista de células existentes p/ selecionar uma e abrir "Editar
 * célula" (CellFormModal em modo edição) ou "Convidar membro" (InviteMemberModal
 * — já reforçado pelo guard A1: líder de célula ativa nunca aparece no picker).
 * Segue o mesmo padrão da tela legada #celulas (CelulasScreen), sem o painel de
 * detalhe/membros/alertas dela — fora de escopo aqui.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { CellFormModal } from "@/components/cells/CellFormModal";
import { InviteMemberModal } from "@/components/cells/InviteMemberModal";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  fetchCellsFull,
  upsertCell,
  type CellSummary,
  type UpsertCellInput,
} from "@/lib/cells-api";
import { fetchContacts, type Contact } from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

import { CellHealthList } from "./CellHealthList";
import { PendingReportsList } from "./PendingReportsList";
import { MultiplicationsList } from "./MultiplicationsList";
import type { CentralToast } from "./types";

export function ManageCellsPanel({
  token,
  onToast,
  onChanged,
}: {
  token: string;
  onToast: (t: CentralToast) => void;
  onChanged: () => void;
}) {
  const { expireSession } = useAuth();

  const [cells, setCells] = useState<CellSummary[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<CellSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [cellPage, contactPage] = await Promise.all([
        fetchCellsFull(token),
        fetchContacts(token),
      ]);
      setCells(cellPage.items);
      setContacts(contactPage.items);
      setLoaded(true);
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setLoadError(
        err instanceof ApiError ? err.message : "Não foi possível carregar as células.",
      );
    }
  }, [token, expireSession]);

  useEffect(() => {
    void load();
  }, [load]);

  // Elegíveis a líder (regra 2026-07-06): apto (Reencontro) + sem célula própria
  // + fora do CSIM. Ao editar, o líder ATUAL entra mesmo fora do filtro
  // (grandfather — o backend aceita reenviar o mesmo líder; igual #celulas).
  const leaderOptions = useMemo(() => {
    const eligible = contacts.filter(
      (c) => c.aptoLider && !c.liderDeCelula && !c.semInteresse,
    );
    const currentId = editing?.liderId;
    if (currentId && !eligible.some((c) => c.id === currentId)) {
      const current = contacts.find((c) => c.id === currentId);
      if (current) return [current, ...eligible];
    }
    return eligible;
  }, [contacts, editing]);

  const leaderName = useCallback(
    (id: string | null) => (id ? contacts.find((c) => c.id === id)?.nome ?? "—" : "—"),
    [contacts],
  );

  const selectedCell = useMemo(
    () => cells.find((c) => c.id === selectedId) ?? null,
    [cells, selectedId],
  );

  // Sugestões de cobertura espiritual: só tipo='pastor' (decisão do dono:
  // 'lider' é legado e não volta como semântica; G12 pastoral formal fica para
  // modelagem futura). Ter célula — ativa ou não — NÃO exclui da cobertura.
  const coverageOptions = useMemo(
    () => contacts.filter((c) => c.tipo === "pastor" && !c.semInteresse),
    [contacts],
  );

  const openForm = useCallback(() => {
    setEditing(null);
    setFormError(null);
    setShowForm(true);
  }, []);

  const openEdit = useCallback((cell: CellSummary) => {
    setEditing(cell);
    setFormError(null);
    setShowForm(true);
  }, []);

  const handleSave = useCallback(
    async (input: UpsertCellInput) => {
      setSaving(true);
      setFormError(null);
      try {
        const saved = await upsertCell(token, input);
        setCells((prev) => {
          const exists = prev.some((c) => c.id === saved.id);
          return exists ? prev.map((c) => (c.id === saved.id ? saved : c)) : [saved, ...prev];
        });
        setShowForm(false);
        setEditing(null);
        onToast({
          kind: "ok",
          text: input.id ? `Célula ${saved.nome} atualizada.` : `Célula ${saved.nome} criada.`,
        });
        onChanged();
      } catch (err) {
        if (err instanceof SessionExpiredError) {
          expireSession();
          return;
        }
        // 409/422 dos guards de elegibilidade chegam como detail legível do
        // backend; só tira o prefixo técnico "liderId: " (igual à #celulas).
        setFormError(
          err instanceof ApiError
            ? err.message.replace(/^liderId:\s*/, "")
            : "Não foi possível salvar a célula.",
        );
      } finally {
        setSaving(false);
      }
    },
    [token, onToast, onChanged, expireSession],
  );

  const handleInvited = useCallback(
    (text: string) => {
      setShowInvite(false);
      onToast({ kind: "ok", text });
      // O convite vinculou a pessoa à célula: recarrega para refletir o membro.
      void load();
      onChanged();
    },
    [onToast, onChanged, load],
  );

  const showEmpty = loaded && !loadError && cells.length === 0;

  return (
    <div className="central-stack">
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button type="button" className="btn btn-primary" onClick={openForm}>
          <Icon name="plus" />
          <span>Nova célula</span>
        </button>
      </div>

      {loadError ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{loadError}</span>
          <button type="button" className="btn btn-sm" onClick={() => void load()}>
            Tentar novamente
          </button>
        </div>
      ) : null}

      {showEmpty ? (
        <div className="card">
          <div className="empty-state" style={{ padding: "var(--s6)" }}>
            <Icon name="central-celula" />
            <p>
              <strong>Nenhuma célula cadastrada.</strong>{" "}
              Crie a primeira célula para começar a organizar líderes, membros e
              relatórios.
            </p>
            <button type="button" className="btn btn-primary" onClick={openForm}>
              <Icon name="plus" />
              <span>Criar primeira célula</span>
            </button>
          </div>
        </div>
      ) : null}

      {!showEmpty ? (
        <section className="card" aria-label="Selecionar célula existente">
          <div className="panel-title">
            <Icon name="central-celula" /> Selecionar célula existente
            {cells.length ? <span className="count">· {cells.length}</span> : null}
          </div>
          <div>
            {cells.map((c) => {
              const selected = c.id === selectedId;
              return (
                <button
                  type="button"
                  key={c.id}
                  className="list-row"
                  onClick={() => setSelectedId(selected ? null : c.id)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    background: selected ? "var(--surface-2)" : "transparent",
                    border: "none",
                    borderBottom: "1px solid var(--border)",
                    cursor: "pointer",
                    font: "inherit",
                    color: "inherit",
                  }}
                >
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="nm">{c.nome}</div>
                    <div className="sub">Líder: {leaderName(c.liderId)}</div>
                  </div>
                  <StatusPill tone={c.ativo ? "ok" : "muted"}>
                    {c.ativo ? "Ativa" : "Inativa"}
                  </StatusPill>
                </button>
              );
            })}
          </div>

          {selectedCell ? (
            <div style={{ display: "flex", gap: "var(--s2)", padding: "var(--s3) var(--s4)" }}>
              <button
                type="button"
                className="btn"
                onClick={() => openEdit(selectedCell)}
                style={{ flex: 1 }}
              >
                <Icon name="document" />
                <span>Editar célula</span>
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => setShowInvite(true)}
                style={{ flex: 1 }}
              >
                <Icon name="plus" />
                <span>Convidar membro</span>
              </button>
            </div>
          ) : null}
        </section>
      ) : null}

      <CellHealthList token={token} />
      <PendingReportsList token={token} />
      <MultiplicationsList token={token} />

      {showForm ? (
        <CellFormModal
          cell={editing}
          leaders={leaderOptions}
          coverageOptions={coverageOptions}
          busy={saving}
          error={formError}
          onClose={() => {
            setShowForm(false);
            setEditing(null);
            setFormError(null);
          }}
          onSubmit={(input) => void handleSave(input)}
        />
      ) : null}

      {showInvite && selectedCell ? (
        <InviteMemberModal
          celulaId={selectedCell.id}
          celulaNome={selectedCell.nome}
          contacts={contacts}
          onClose={() => setShowInvite(false)}
          onInvited={handleInvited}
        />
      ) : null}
    </div>
  );
}
