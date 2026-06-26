"use client";

/**
 * Tela #contatos (legada, deep-link fora do menu — delta-012).
 *
 * Lista (data-table) + detalhe (painel lateral) das pessoas da igreja
 * (api-contacts). Filtra por tipo/acompanhamento via tabs, cria contato
 * (api-create-contact, com dedupe por telefone) e vincula célula (api-link-cell,
 * bloqueando célula inativa/sem líder). empty-state quando vazio; falha ao
 * salvar mantém o formulário preenchido com erro inline.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  createContact,
  fetchContacts,
  followStatus,
  linkContactCell,
  tipoLabel,
  tipoTone,
  updateContact,
  type Contact,
  type CreateContactInput,
  type UpdateContactInput,
} from "@/lib/contacts-api";
import { ApiError, fetchCells, type Cell } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

import { EditContactModal } from "./EditContactModal";
import { LinkCellModal } from "./LinkCellModal";
import { NewContactModal } from "./NewContactModal";

type Filter =
  | "all"
  | "pending"
  | "contato"
  | "visitante"
  | "discipulo"
  | "lider"
  | "pastor"
  | "csim";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const FILTERS: Array<{ id: Filter; label: string; warn?: boolean }> = [
  { id: "all", label: "Todos" },
  { id: "pending", label: "Sem acompanhamento", warn: true },
  { id: "contato", label: "Contatos" },
  { id: "visitante", label: "Visitantes" },
  { id: "discipulo", label: "Discípulos" },
  { id: "lider", label: "Líderes" },
  { id: "pastor", label: "Pastores" },
  { id: "csim", label: "Sem interesse (CSIM)", warn: true },
];

const ETAPA_LABEL: Record<string, string> = {
  ganhar: "Ganhar",
  consolidar: "Consolidar",
  discipular: "Discipular",
  enviar: "Enviar",
};

function etapaTone(etapa: string | null): "ok" | "warn" | "accent" | "muted" {
  switch (etapa) {
    case "ganhar":
      return "accent";
    case "consolidar":
      return "warn";
    case "discipular":
      return "ok";
    default:
      return "muted";
  }
}

function initials(nome: string): string {
  const parts = nome.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? "" : "";
  return (first + last).toUpperCase();
}

function maskPhone(phone: string): string {
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 6) return phone;
  const tail = digits.slice(-4);
  const head = digits.slice(0, digits.length - 6);
  return `+${head} •••• ${tail}`;
}

function matchesFilter(c: Contact, f: Filter): boolean {
  if (f === "all") return true;
  if (f === "pending") return followStatus(c).label === "Sem acompanhamento";
  if (f === "csim") return c.semInteresse === true;
  return c.tipo === f;
}

export function ContatosScreen({ selectedId }: { selectedId?: string | null }) {
  const { token, user, expireSession } = useAuth();
  const canEdit = (user?.roles ?? []).includes("admin");

  const [contacts, setContacts] = useState<Contact[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<string | null>(selectedId ?? null);

  const [showNew, setShowNew] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [linkTarget, setLinkTarget] = useState<Contact | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);
  const [editTarget, setEditTarget] = useState<Contact | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [editSaving, setEditSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  const handleSessionError = useCallback(
    (err: unknown): boolean => {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return true;
      }
      return false;
    },
    [expireSession],
  );

  const load = useCallback(
    async (mode: "initial" | "retry") => {
      if (!token) return;
      if (mode === "initial") setLoading(true);
      setError(null);
      try {
        const [page, cellPage] = await Promise.all([
          fetchContacts(token),
          fetchCells(token),
        ]);
        setContacts(page.items);
        setCells(cellPage.items);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar os contatos.",
        );
      } finally {
        setLoading(false);
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    void load("initial");
  }, [load]);

  // Deep-link: sincroniza seleção quando o id do hash muda.
  useEffect(() => {
    if (selectedId) setSelected(selectedId);
  }, [selectedId]);

  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const filtered = useMemo(
    () => contacts.filter((c) => matchesFilter(c, filter)),
    [contacts, filter],
  );

  const selectedContact = useMemo(
    () => contacts.find((c) => c.id === selected) ?? null,
    [contacts, selected],
  );

  const cellName = useCallback(
    (id: string | null) => (id ? cells.find((c) => c.id === id)?.nome ?? "—" : "—"),
    [cells],
  );

  const handleCreate = useCallback(
    async (input: CreateContactInput) => {
      if (!token) return;
      setSaving(true);
      setFormError(null);
      try {
        const result = await createContact(token, input);
        setContacts((prev) => {
          const exists = prev.some((c) => c.id === result.contact.id);
          return exists
            ? prev.map((c) => (c.id === result.contact.id ? result.contact : c))
            : [result.contact, ...prev];
        });
        setSelected(result.contact.id);
        setShowNew(false);
        flashToast({
          kind: "ok",
          text: result.deduped
            ? "Já existe um contato com esse telefone — abrindo o existente."
            : `Contato ${result.contact.nome} criado.`,
        });
      } catch (err) {
        if (handleSessionError(err)) return;
        // Mantém o formulário preenchido; erro inline no modal.
        setFormError(
          err instanceof ApiError ? err.message : "Não foi possível salvar o contato.",
        );
      } finally {
        setSaving(false);
      }
    },
    [token, flashToast, handleSessionError],
  );

  const handleLink = useCallback(
    async (celulaId: string) => {
      if (!token || !linkTarget) return;
      setBusyId(linkTarget.id);
      setLinkError(null);
      try {
        const updated = await linkContactCell(token, linkTarget.id, celulaId);
        setContacts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
        flashToast({ kind: "ok", text: `${updated.nome} conectado à célula.` });
        setLinkTarget(null);
      } catch (err) {
        if (handleSessionError(err)) return;
        setLinkError(
          err instanceof ApiError ? err.message : "Não foi possível conectar à célula.",
        );
      } finally {
        setBusyId(null);
      }
    },
    [token, linkTarget, flashToast, handleSessionError],
  );

  const handleUpdate = useCallback(
    async (input: UpdateContactInput) => {
      if (!token || !editTarget) return;
      setEditSaving(true);
      setEditError(null);
      try {
        const updated = await updateContact(token, editTarget.id, input);
        setContacts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
        flashToast({ kind: "ok", text: `${updated.nome} atualizado.` });
        setEditTarget(null);
      } catch (err) {
        if (handleSessionError(err)) return;
        setEditError(
          err instanceof ApiError ? err.message : "Não foi possível salvar as alterações.",
        );
      } finally {
        setEditSaving(false);
      }
    },
    [token, editTarget, flashToast, handleSessionError],
  );

  const columns: Array<Column<Contact>> = useMemo(
    () => [
      {
        header: "Contato",
        cell: (c) => (
          <>
            {/* Avatar só aparece no card mobile (oculto na tabela desktop). */}
            <span className="avatar" aria-hidden="true">
              {initials(c.nome)}
            </span>
            <div className="person-id">
              <div className="nm">{c.nome}</div>
              <div className="sub mono">{maskPhone(c.telefone)}</div>
            </div>
          </>
        ),
      },
      {
        header: "Tipo",
        cell: (c) =>
          c.semInteresse ? (
            <StatusPill tone="danger">Sem interesse</StatusPill>
          ) : (
            <StatusPill tone={tipoTone(c.tipo)}>{tipoLabel(c.tipo)}</StatusPill>
          ),
      },
      {
        header: "Célula",
        cell: (c) => <span className="sub">{cellName(c.celulaId)}</span>,
      },
      {
        header: "Estágio na Visão",
        cell: (c) =>
          c.etapa ? (
            <StatusPill tone={etapaTone(c.etapa)}>
              {ETAPA_LABEL[c.etapa] ?? c.etapa}
            </StatusPill>
          ) : (
            <span className="sub">—</span>
          ),
      },
    ],
    [cellName],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="contatos">
      <div className="screen-head">
        <div className="actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => {
              setFormError(null);
              setShowNew(true);
            }}
          >
            <Icon name="ganhar" />
            <span>Novo contato</span>
          </button>
        </div>
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => void load("retry")}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      <div className="tabs filter-tabs" role="tablist">
        {FILTERS.map((f) => {
          const count = contacts.filter((c) => matchesFilter(c, f.id)).length;
          return (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={filter === f.id}
              className={`tab${filter === f.id ? " active" : ""}`}
              style={f.warn ? { color: "var(--warn)" } : undefined}
              onClick={() => setFilter(f.id)}
            >
              {f.label} <span className="num">{count}</span>
            </button>
          );
        })}
      </div>

      <div className="dash-grid">
        <div className="card">
          {showSkeleton ? (
            <div className="queue">
              {Array.from({ length: 5 }).map((_, i) => (
                <div className="qitem skeleton" key={i}>
                  <span className="qicon sk-icon" />
                  <div className="qbody">
                    <div className="sk-line sk-md" />
                    <div className="sk-line sk-sm" />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <DataTable
              className="people-cards"
              columns={columns}
              rows={filtered}
              rowKey={(c) => c.id}
              empty={{
                icon: "user",
                title:
                  contacts.length === 0
                    ? "Nenhum contato ainda."
                    : "Nenhum contato neste filtro.",
                hint:
                  contacts.length === 0
                    ? "Crie um contato ou aguarde o agente registrar as conversas."
                    : undefined,
              }}
              onRowClick={(c) => {
                setSelected(c.id);
                // Admin: clicar na linha já abre a edição. Demais papéis só
                // selecionam (painel lateral à direita).
                if (canEdit) {
                  setEditError(null);
                  setEditTarget(c);
                }
              }}
            />
          )}
        </div>

        <div className="dash-side">
          <ContactDetail
            contact={selectedContact}
            cellName={cellName(selectedContact?.celulaId ?? null)}
            busy={busyId === selectedContact?.id}
            canEdit={canEdit}
            onEdit={() => {
              if (!selectedContact) return;
              setEditError(null);
              setEditTarget(selectedContact);
            }}
            onLink={() => {
              if (!selectedContact) return;
              setLinkError(null);
              setLinkTarget(selectedContact);
            }}
          />
        </div>
      </div>

      {showNew ? (
        <NewContactModal
          busy={saving}
          error={formError}
          onClose={() => setShowNew(false)}
          onSubmit={(input) => void handleCreate(input)}
        />
      ) : null}

      {linkTarget ? (
        <LinkCellModal
          cells={cells}
          contactName={linkTarget.nome}
          busy={busyId === linkTarget.id}
          error={linkError}
          onClose={() => {
            setLinkTarget(null);
            setLinkError(null);
          }}
          onLink={(celulaId) => void handleLink(celulaId)}
        />
      ) : null}

      {editTarget ? (
        <EditContactModal
          contact={editTarget}
          busy={editSaving}
          error={editError}
          onClose={() => {
            setEditTarget(null);
            setEditError(null);
          }}
          onSubmit={(input) => void handleUpdate(input)}
        />
      ) : null}

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Painel de detalhe do contato
// ---------------------------------------------------------------------------
function ContactDetail({
  contact,
  cellName,
  busy,
  canEdit,
  onEdit,
  onLink,
}: {
  contact: Contact | null;
  cellName: string;
  busy: boolean;
  canEdit: boolean;
  onEdit: () => void;
  onLink: () => void;
}) {
  if (!contact) {
    return (
      <div className="card card-pad">
        <div className="empty-state" style={{ padding: "var(--s5)" }}>
          <Icon name="user" />
          <p>
            <strong>Selecione um contato</strong> para ver os detalhes e conectá-lo a
            uma célula.
          </p>
        </div>
      </div>
    );
  }

  const status = followStatus(contact);

  return (
    <div className="card card-pad">
      <div className="detail-head">
        <div>
          <h3>{contact.nome}</h3>
          <div className="sub mono">{contact.telefone}</div>
        </div>
        {contact.semInteresse ? (
          <StatusPill tone="danger">Sem interesse</StatusPill>
        ) : (
          <StatusPill tone={tipoTone(contact.tipo)}>{tipoLabel(contact.tipo)}</StatusPill>
        )}
      </div>

      <dl className="detail-list">
        {contact.semInteresse ? (
          <div>
            <dt>Motivo (CSIM)</dt>
            <dd>{contact.semInteresseMotivo?.trim() || "—"}</dd>
          </div>
        ) : null}
        <div>
          <dt>Acompanhamento</dt>
          <dd>
            <StatusPill tone={status.tone}>{status.label}</StatusPill>
          </dd>
        </div>
        <div>
          <dt>Célula</dt>
          <dd>{cellName}</dd>
        </div>
        <div>
          <dt>Presenças em célula</dt>
          <dd className="num">{contact.presencasCelula}</dd>
        </div>
        <div>
          <dt>Decisão por Jesus</dt>
          <dd>{contact.aceitouJesus ? "Sim" : "Não"}</dd>
        </div>
        {contact.email ? (
          <div>
            <dt>E-mail</dt>
            <dd>{contact.email}</dd>
          </div>
        ) : null}
      </dl>

      {!contact.celulaId ? (
        <button
          type="button"
          className="btn btn-primary btn-block"
          onClick={onLink}
          disabled={busy}
        >
          <Icon name="link" />
          <span>Vincular célula</span>
        </button>
      ) : null}

      {canEdit ? (
        <button
          type="button"
          className="btn btn-block"
          onClick={onEdit}
          style={{ marginTop: !contact.celulaId ? "var(--s2)" : 0 }}
        >
          Editar dados
        </button>
      ) : null}
    </div>
  );
}
