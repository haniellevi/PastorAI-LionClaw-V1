"use client";

/**
 * Aba "Gerenciar células" da Central. Além das três listas de acompanhamento
 * (saúde US-18, relatórios pendentes US-16, multiplicações US-19), é AQUI que
 * a Central cadastra célula (PRD Central §6 / onboarding PR-O1): botão "Nova
 * célula" no topo e, quando a igreja ainda não tem célula, empty state com o
 * CTA "Criar primeira célula". Reusa o CellFormModal da tela legada #celulas;
 * permissão e elegibilidade continuam no backend (403/409/422 aparecem como
 * erro inline no modal).
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { CellFormModal } from "@/components/cells/CellFormModal";
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
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

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
  // + fora do CSIM — mesma regra da tela legada #celulas (aqui só criação).
  const leaderOptions = useMemo(
    () => contacts.filter((c) => c.aptoLider && !c.liderDeCelula && !c.semInteresse),
    [contacts],
  );

  const openForm = useCallback(() => {
    setFormError(null);
    setShowForm(true);
  }, []);

  const handleSave = useCallback(
    async (input: UpsertCellInput) => {
      setSaving(true);
      setFormError(null);
      try {
        const saved = await upsertCell(token, input);
        setCells((prev) => [saved, ...prev]);
        setShowForm(false);
        onToast({ kind: "ok", text: `Célula ${saved.nome} criada.` });
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

      <CellHealthList token={token} />
      <PendingReportsList token={token} />
      <MultiplicationsList token={token} />

      {showForm ? (
        <CellFormModal
          leaders={leaderOptions}
          busy={saving}
          error={formError}
          onClose={() => {
            setShowForm(false);
            setFormError(null);
          }}
          onSubmit={(input) => void handleSave(input)}
        />
      ) : null}
    </div>
  );
}
