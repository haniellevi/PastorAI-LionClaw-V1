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
import { Dialog } from "@/components/ds/Dialog";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  archiveContact,
  ArchiveBlockedError,
  createContact,
  fetchContactDetail,
  fetchContactsPage,
  fetchOffboardingPreflight,
  followStatus,
  linkContactCell,
  tipoLabel,
  tipoTone,
  unarchiveContact,
  updateContact,
  type ArchiveContactResult,
  type Contact,
  type ContactView,
  type CreateContactInput,
  type OffboardingPreflight,
  type UpdateContactInput,
} from "@/lib/contacts-api";
import { ApiError, fetchCells, type Cell } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

import { ArchiveContactModal } from "./ArchiveContactModal";
import { EditContactModal } from "./EditContactModal";
import { LinkCellModal } from "./LinkCellModal";
import { NewContactModal } from "./NewContactModal";

type Filter = Exclude<ContactView, "membro">;

interface Toast {
  kind: "ok" | "err";
  text: string;
}

// "Líderes de célula" é DERIVADO do vínculo real (liderDeCelula), não do tipo;
// "Aptos sem célula" = fez o Reencontro e ainda não lidera (regra 2026-07-06).
const FILTERS: Array<{ id: Filter; label: string; warn?: boolean }> = [
  { id: "all", label: "Todos" },
  { id: "pending", label: "Sem acompanhamento", warn: true },
  { id: "contato", label: "Contatos" },
  { id: "visitante", label: "Visitantes" },
  { id: "discipulo", label: "Discípulos" },
  { id: "lideres_celula", label: "Líderes de célula" },
  { id: "aptos", label: "Aptos sem célula" },
  { id: "pastor", label: "Pastores" },
  { id: "csim", label: "Fora da igreja", warn: true },
  // FECH-06/REATIVAR-1: pessoas arquivadas ficam FORA das listas normais e
  // só aparecem aqui, com ação "Reativar" (admin/pastor).
  { id: "arquivadas", label: "Arquivadas" },
];

// Mantém o DOM e o custo de reconciliação limitados mesmo em igrejas grandes.
const CONTACTS_PAGE_SIZE = 50;

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

export function ContatosScreen({ selectedId }: { selectedId?: string | null }) {
  const { token, user, expireSession } = useAuth();
  const roles = user?.roles ?? [];
  const canEdit = roles.includes("admin");
  // FECH-06/REATIVAR-1: o backend aceita admin/pastor no unarchive.
  const canReactivate = canEdit || roles.includes("pastor");

  const [contacts, setContacts] = useState<Contact[]>([]);
  const [cells, setCells] = useState<Cell[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const currentDataKey = `${filter}:${currentPage}`;
  const hasCurrentData = loadedKey === currentDataKey;
  const [pagination, setPagination] = useState({
    page: 1,
    pageSize: CONTACTS_PAGE_SIZE,
    total: 0,
  });
  const [selected, setSelected] = useState<string | null>(selectedId ?? null);
  // Um deep-link pode apontar para alguém que não está nas 50 linhas atuais.
  // Esse registro alimenta somente o painel lateral; nunca entra na tabela.
  const [detachedSelected, setDetachedSelected] = useState<Contact | null>(null);
  const [selectedDetailLoading, setSelectedDetailLoading] = useState(false);
  const [selectedDetailError, setSelectedDetailError] = useState<string | null>(null);

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

  // Arquivamento de Pessoa (M7B-W3.2B, admin-only) — nunca hard delete.
  const [archiveTarget, setArchiveTarget] = useState<Contact | null>(null);
  const [archivePreflight, setArchivePreflight] = useState<OffboardingPreflight | null>(null);
  const [archivePreflightLoading, setArchivePreflightLoading] = useState(false);
  const [archivePreflightError, setArchivePreflightError] = useState<string | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [archiveError, setArchiveError] = useState<string | null>(null);
  // O estado arquivado PERSISTE após reload: GET /contacts expõe o booleano
  // `arquivada` (FECH-06) e é ele quem manda no selo/ações do detalhe. Este
  // registro de sessão guarda apenas os METADADOS do arquivamento que a
  // própria sessão acabou de fazer (arquivada_em/por/motivo do resultado do
  // POST), que o GET de lista não traz.
  const [archivedInfo, setArchivedInfo] = useState<Record<string, ArchiveContactResult>>({});

  // Reativação (desarquivamento) de Pessoa — FECH-06/REATIVAR-1.
  const [unarchiveTarget, setUnarchiveTarget] = useState<Contact | null>(null);
  const [unarchiveBusy, setUnarchiveBusy] = useState(false);
  const [unarchiveError, setUnarchiveError] = useState<string | null>(null);

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

  // Uma troca rápida de página pode inverter a ordem das respostas. Só a
  // requisição mais recente pode atualizar a tabela.
  const loadRequestRef = useRef(0);
  // Células mudam muito menos que a página/filtro de contatos. Reaproveite a
  // mesma promessa por sessão para que paginar não repita esse request.
  const cellsRequestRef = useRef<{
    token: string;
    request: ReturnType<typeof fetchCells>;
  } | null>(null);
  const fetchCellsOnce = useCallback(() => {
    if (!token) throw new Error("Sessão indisponível");
    const cached = cellsRequestRef.current;
    if (cached?.token === token) return cached.request;

    const entry = { token, request: fetchCells(token) };
    cellsRequestRef.current = entry;
    void entry.request.catch(() => {
      // Uma falha pode ser tentada novamente na próxima carga.
      if (cellsRequestRef.current === entry) cellsRequestRef.current = null;
    });
    return entry.request;
  }, [token]);
  const loadPage = useCallback(
    async (requestedPage: number) => {
      if (!token) return;
      const requestId = ++loadRequestRef.current;
      const dataKey = `${filter}:${requestedPage}`;
      setLoading(true);
      setError(null);
      try {
        const [page, cellPage] = await Promise.all([
          fetchContactsPage(token, {
            page: requestedPage,
            pageSize: CONTACTS_PAGE_SIZE,
            view: filter,
          }),
          fetchCellsOnce(),
        ]);
        if (loadRequestRef.current !== requestId) return;
        // Defesa adicional contra um backend/mocked response fora do contrato:
        // nunca renderize mais linhas do que o orçamento desta tela.
        setContacts(page.items.slice(0, CONTACTS_PAGE_SIZE));
        setPagination({
          page: page.page,
          pageSize: Math.min(page.pageSize, CONTACTS_PAGE_SIZE),
          total: page.total,
        });
        setCells(cellPage.items);
        setLoadedKey(dataKey);
      } catch (err) {
        if (loadRequestRef.current !== requestId) return;
        if (handleSessionError(err)) return;
        // Nunca mantenha linhas/total de outra aba sob o filtro atual.
        setContacts([]);
        setPagination({ page: requestedPage, pageSize: CONTACTS_PAGE_SIZE, total: 0 });
        setLoadedKey(dataKey);
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar os contatos.",
        );
      } finally {
        if (loadRequestRef.current === requestId) setLoading(false);
      }
    },
    [token, filter, handleSessionError, fetchCellsOnce],
  );

  useEffect(() => {
    void loadPage(currentPage);
  }, [currentPage, loadPage]);

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

  const selectedPageContact = useMemo(
    () => contacts.find((c) => c.id === selected) ?? null,
    [contacts, selected],
  );
  const selectedContact =
    selectedPageContact ?? (detachedSelected?.id === selected ? detachedSelected : null);
  const hasDetachedSelection = detachedSelected?.id === selected;

  // Busca pontual para deep-link fora da página. A geração impede que uma
  // resposta atrasada do contato A substitua o contato B selecionado depois.
  const selectedDetailRequestRef = useRef(0);
  useEffect(() => {
    const requestId = ++selectedDetailRequestRef.current;

    if (!token || !hasCurrentData || !selected) {
      setDetachedSelected(null);
      setSelectedDetailLoading(false);
      setSelectedDetailError(null);
      return;
    }
    if (selectedPageContact) {
      setDetachedSelected(null);
      setSelectedDetailLoading(false);
      setSelectedDetailError(null);
      return;
    }
    if (hasDetachedSelection) {
      setSelectedDetailLoading(false);
      setSelectedDetailError(null);
      return;
    }

    setDetachedSelected(null);
    setSelectedDetailLoading(true);
    setSelectedDetailError(null);
    void fetchContactDetail(token, selected)
      .then((detail) => {
        if (selectedDetailRequestRef.current !== requestId) return;
        setDetachedSelected(detail);
      })
      .catch((err: unknown) => {
        if (selectedDetailRequestRef.current !== requestId) return;
        if (handleSessionError(err)) return;
        setSelectedDetailError(
          err instanceof ApiError ? err.message : "Não foi possível carregar este contato.",
        );
      })
      .finally(() => {
        if (selectedDetailRequestRef.current === requestId) {
          setSelectedDetailLoading(false);
        }
      });
  }, [
    token,
    hasCurrentData,
    selected,
    selectedPageContact,
    hasDetachedSelection,
    handleSessionError,
  ]);

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
        // Novo contato pode não pertencer ao filtro atual. Volte à visão
        // canônica e revalide no servidor, preservando o detalhe no intervalo.
        setDetachedSelected(result.contact);
        setSelected(result.contact.id);
        const alreadyOnFirstAllPage = filter === "all" && currentPage === 1;
        setFilter("all");
        setCurrentPage(1);
        if (alreadyOnFirstAllPage) await loadPage(1);
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
    [token, filter, currentPage, loadPage, flashToast, handleSessionError],
  );

  const handleLink = useCallback(
    async (celulaId: string) => {
      if (!token || !linkTarget) return;
      setBusyId(linkTarget.id);
      setLinkError(null);
      try {
        const updated = await linkContactCell(token, linkTarget.id, celulaId);
        setContacts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
        setDetachedSelected((prev) =>
          prev?.id === updated.id ? { ...prev, ...updated } : prev,
        );
        if (selected === updated.id) setDetachedSelected(updated);
        await loadPage(currentPage);
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
    [token, linkTarget, selected, currentPage, loadPage, flashToast, handleSessionError],
  );

  const handleUpdate = useCallback(
    async (input: UpdateContactInput) => {
      if (!token || !editTarget) return;
      setEditSaving(true);
      setEditError(null);
      try {
        const updated = await updateContact(token, editTarget.id, input);
        setContacts((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
        setDetachedSelected((prev) =>
          prev?.id === updated.id ? { ...prev, ...updated } : prev,
        );
        if (selected === updated.id) setDetachedSelected(updated);
        await loadPage(currentPage);
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
    [token, editTarget, selected, currentPage, loadPage, flashToast, handleSessionError],
  );

  // Geração da requisição de preflight: A pode ser aberto, o usuário trocar
  // para B antes de A responder, e a resposta de A chegar DEPOIS da de B
  // (rede não garante ordem). Sem essa guarda, a resposta tardia de A
  // sobrescreveria o preflight/erro/loading que a tela já mostra para B.
  // Cada chamada real de loadArchivePreflight reserva o próximo número; só a
  // MAIS RECENTE tem permissão de gravar estado — qualquer uma que resolva
  // depois de já ter sido superada por uma chamada mais nova é descartada.
  const archivePreflightRequestRef = useRef(0);

  const loadArchivePreflight = useCallback(
    async (target: Contact) => {
      if (!token) return;
      const requestId = ++archivePreflightRequestRef.current;
      setArchivePreflightLoading(true);
      setArchivePreflightError(null);
      try {
        const result = await fetchOffboardingPreflight(token, target.id);
        if (archivePreflightRequestRef.current !== requestId) return; // resposta obsoleta
        setArchivePreflight(result);
      } catch (err) {
        if (archivePreflightRequestRef.current !== requestId) return; // resposta obsoleta
        if (handleSessionError(err)) return;
        setArchivePreflightError(
          err instanceof ApiError
            ? err.message
            : "Não foi possível verificar se esta pessoa pode ser arquivada.",
        );
      } finally {
        if (archivePreflightRequestRef.current === requestId) {
          setArchivePreflightLoading(false);
        }
      }
    },
    [token, handleSessionError],
  );

  useEffect(() => {
    if (archiveTarget) void loadArchivePreflight(archiveTarget);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [archiveTarget]);

  const handleArchiveConfirm = useCallback(
    async (motivo: string) => {
      if (!token || !archiveTarget) return;
      setArchiveBusy(true);
      setArchiveError(null);
      try {
        const result = await archiveContact(token, archiveTarget.id, motivo);
        const nextTotal = Math.max(0, pagination.total - 1);
        const lastPage = Math.max(1, Math.ceil(nextTotal / pagination.pageSize));
        const targetPage = Math.min(currentPage, lastPage);
        if (selected === result.pessoa_id) {
          setDetachedSelected({ ...archiveTarget, arquivada: true });
        }
        setArchivedInfo((prev) => ({ ...prev, [result.pessoa_id]: result }));
        flashToast({
          kind: "ok",
          text: result.ja_arquivada
            ? `${archiveTarget.nome} já estava arquivada.`
            : `${archiveTarget.nome} foi arquivada.`,
        });
        setArchiveTarget(null);
        setArchivePreflight(null);
        if (targetPage !== currentPage) setCurrentPage(targetPage);
        // Offset pagination shifts the next row into this page after removal.
        // Reload every time so no contact is skipped on the following page.
        await loadPage(targetPage);
      } catch (err) {
        if (handleSessionError(err)) return;
        if (err instanceof ArchiveBlockedError) {
          // Bloqueadores surgiram entre o GET de preflight e a confirmação
          // (TOCTOU): reexibe a lista revalidada pelo backend, sem fechar.
          setArchivePreflight(err.preflight);
          setArchiveError("Novos vínculos impedem o arquivamento agora. Revise a lista abaixo.");
          return;
        }
        setArchiveError(
          err instanceof ApiError ? err.message : "Não foi possível arquivar esta pessoa.",
        );
      } finally {
        setArchiveBusy(false);
      }
    },
    [
      token,
      archiveTarget,
      selected,
      pagination,
      currentPage,
      loadPage,
      flashToast,
      handleSessionError,
    ],
  );

  const handleUnarchiveConfirm = useCallback(async () => {
    if (!token || !unarchiveTarget) return;
    setUnarchiveBusy(true);
    setUnarchiveError(null);
    try {
      const result = await unarchiveContact(token, unarchiveTarget.id);
      const nextTotal = Math.max(0, pagination.total - 1);
      const lastPage = Math.max(1, Math.ceil(nextTotal / pagination.pageSize));
      const targetPage = Math.min(currentPage, lastPage);
      if (selected === result.pessoa_id) {
        setDetachedSelected({ ...unarchiveTarget, arquivada: false });
      }
      // O selo de sessão do fluxo de arquivar (se houver) também deixa de valer.
      setArchivedInfo((prev) => {
        if (!(result.pessoa_id in prev)) return prev;
        const next = { ...prev };
        delete next[result.pessoa_id];
        return next;
      });
      flashToast({ kind: "ok", text: `${unarchiveTarget.nome} foi reativada.` });
      setUnarchiveTarget(null);
      if (targetPage !== currentPage) setCurrentPage(targetPage);
      await loadPage(targetPage);
    } catch (err) {
      if (handleSessionError(err)) return;
      setUnarchiveError(
        err instanceof ApiError ? err.message : "Não foi possível reativar esta pessoa.",
      );
    } finally {
      setUnarchiveBusy(false);
    }
  }, [
    token,
    unarchiveTarget,
    selected,
    pagination,
    currentPage,
    loadPage,
    flashToast,
    handleSessionError,
  ]);

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
            <StatusPill tone="danger">Fora da igreja</StatusPill>
          ) : (
            <>
              <StatusPill tone={tipoTone(c.tipo)}>{tipoLabel(c.tipo)}</StatusPill>
              {c.liderDeCelula ? (
                <StatusPill tone="ok">Líder de célula</StatusPill>
              ) : c.aptoLider ? (
                <StatusPill tone="accent">Apto</StatusPill>
              ) : null}
            </>
          ),
      },
      {
        header: "Célula",
        cell: (c) => <span className="sub">{cellName(c.celulaId)}</span>,
      },
      {
        header: "Estágio na Visão",
        cell: (c) =>
          c.semInteresse ? (
            // CSIM está fora da Visão G12 — sem chip de etapa.
            <span className="sub">Fora da visão</span>
          ) : c.etapa ? (
            <StatusPill tone={etapaTone(c.etapa)}>
              {ETAPA_LABEL[c.etapa] ?? c.etapa}
            </StatusPill>
          ) : (
            <span className="sub">—</span>
          ),
      },
      // FECH-06/REATIVAR-1: só a aba "Arquivadas" ganha a coluna de ação, e
      // apenas para papéis que o backend aceita no unarchive (admin/pastor).
      ...(filter === "arquivadas" && canReactivate
        ? [
            {
              header: "Ações",
              cell: (c: Contact) => (
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={(e) => {
                    // Não abrir o painel de detalhe ao clicar na ação da linha.
                    e.stopPropagation();
                    setUnarchiveError(null);
                    setUnarchiveTarget(c);
                  }}
                >
                  Reativar
                </button>
              ),
            } satisfies Column<Contact>,
          ]
        : []),
    ],
    [cellName, filter, canReactivate],
  );

  const showSkeleton = !hasCurrentData;
  const totalPages = Math.max(1, Math.ceil(pagination.total / pagination.pageSize));
  const pageStart = pagination.total === 0 ? 0 : (pagination.page - 1) * pagination.pageSize + 1;
  const pageEnd =
    pagination.total === 0
      ? 0
      : Math.min(pageStart + contacts.length - 1, pagination.total);

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
            onClick={() => void loadPage(currentPage)}
            disabled={loading}
          >
            Tentar novamente
          </button>
        </div>
      ) : null}

      <div className="tabs filter-tabs" role="tablist">
        {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={filter === f.id}
              className={`tab${filter === f.id ? " active" : ""}`}
              style={f.warn ? { color: "var(--warn)" } : undefined}
              onClick={() => {
                setFilter(f.id);
                setSelected(null);
                setCurrentPage(1);
              }}
            >
              {f.label}
              {filter === f.id ? (
                <span className="num" title="Total neste filtro">
                  {pagination.total}
                </span>
              ) : null}
            </button>
          ))}
      </div>
      <p className="sub" style={{ marginTop: "var(--s2)" }}>
        O número da aba ativa é o total global do filtro; a tabela mostra uma página por vez.
      </p>

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
            <>
              <DataTable
                className="people-cards"
                columns={columns}
                rows={contacts}
                rowKey={(c) => c.id}
                empty={{
                  icon: "user",
                  title:
                    filter === "all" && pagination.total === 0
                      ? "Nenhum contato ainda."
                      : "Nenhum contato neste filtro.",
                  hint:
                    filter === "all" && pagination.total === 0
                      ? "Crie um contato ou aguarde o agente registrar as conversas."
                      : undefined,
                }}
                onRowClick={(c) => setSelected(c.id)}
              />

              {hasCurrentData ? (
                <nav
                  aria-label="Paginação de contatos"
                  aria-busy={loading}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "var(--s2)",
                    flexWrap: "wrap",
                    padding: "var(--s3)",
                    borderTop: "1px solid var(--border)",
                  }}
                >
                  <span className="sub" role="status" aria-live="polite">
                    Mostrando {pageStart}–{pageEnd} de {pagination.total}. Página{" "}
                    {pagination.page} de {totalPages}.
                  </span>
                  <span style={{ display: "flex", gap: "var(--s2)" }}>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={loading || currentPage <= 1}
                      onClick={() => {
                        setSelected(null);
                        setCurrentPage((page) => Math.max(1, page - 1));
                      }}
                    >
                      Anterior
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      disabled={loading || currentPage >= totalPages}
                      onClick={() => {
                        setSelected(null);
                        setCurrentPage((page) => Math.min(totalPages, page + 1));
                      }}
                    >
                      Próxima
                    </button>
                  </span>
                </nav>
              ) : null}
            </>
          )}
        </div>

        <div className="dash-side">
          {selected && !selectedContact && selectedDetailLoading ? (
            <div className="card card-pad" role="status">
              Carregando detalhes do contato…
            </div>
          ) : selected && !selectedContact && selectedDetailError ? (
            <div className="error-banner" role="alert">
              <Icon name="alert" />
              <span>{selectedDetailError}</span>
            </div>
          ) : (
            <ContactDetail
              contact={selectedContact}
              cellName={cellName(selectedContact?.celulaId ?? null)}
              busy={busyId === selectedContact?.id}
              canEdit={canEdit}
              archived={selectedContact ? archivedInfo[selectedContact.id] : undefined}
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
              onArchive={() => {
                if (!selectedContact) return;
                setArchivePreflight(null);
                setArchivePreflightError(null);
                setArchiveError(null);
                setArchiveTarget(selectedContact);
              }}
            />
          )}
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

      {archiveTarget ? (
        <ArchiveContactModal
          contact={archiveTarget}
          preflight={archivePreflight}
          preflightLoading={archivePreflightLoading}
          preflightError={archivePreflightError}
          busy={archiveBusy}
          error={archiveError}
          onRetryPreflight={() => void loadArchivePreflight(archiveTarget)}
          onClose={() => {
            setArchiveTarget(null);
            setArchivePreflight(null);
            setArchivePreflightError(null);
            setArchiveError(null);
          }}
          onConfirm={(motivo) => void handleArchiveConfirm(motivo)}
        />
      ) : null}

      {/* Confirmação de reativação — FECH-06/REATIVAR-1 (ds/Dialog, nunca window.confirm). */}
      <Dialog
        open={unarchiveTarget !== null}
        onClose={() => {
          if (unarchiveBusy) return;
          setUnarchiveTarget(null);
          setUnarchiveError(null);
        }}
        title="Reativar pessoa"
        description={
          unarchiveTarget
            ? `${unarchiveTarget.nome} voltará às listas normais e sairá de "Arquivadas".`
            : undefined
        }
        footer={
          <>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setUnarchiveTarget(null);
                setUnarchiveError(null);
              }}
              disabled={unarchiveBusy}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleUnarchiveConfirm()}
              disabled={unarchiveBusy}
            >
              {unarchiveBusy ? "Reativando…" : "Reativar"}
            </button>
          </>
        }
      >
        {unarchiveError ? (
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{unarchiveError}</span>
          </div>
        ) : null}
      </Dialog>

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
  archived,
  onEdit,
  onLink,
  onArchive,
}: {
  contact: Contact | null;
  cellName: string;
  busy: boolean;
  canEdit: boolean;
  /** Metadados de um arquivamento feito NESTA sessão (o estado arquivado em
   * si persiste via `contact.arquivada`, que o backend expõe no GET). */
  archived?: ArchiveContactResult;
  onEdit: () => void;
  onLink: () => void;
  onArchive: () => void;
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
  // Persistente (backend) OU recém-arquivada nesta sessão (metadados locais).
  const isArquivada = contact.arquivada === true || archived !== undefined;

  return (
    <div className="card card-pad">
      <div className="detail-head">
        <div>
          <h3>{contact.nome}</h3>
          <div className="sub mono">{contact.telefone}</div>
        </div>
        {isArquivada ? (
          <StatusPill tone="muted">Arquivada</StatusPill>
        ) : contact.semInteresse ? (
          <StatusPill tone="danger">Fora da igreja</StatusPill>
        ) : (
          <StatusPill tone={tipoTone(contact.tipo)}>{tipoLabel(contact.tipo)}</StatusPill>
        )}
      </div>

      <dl className="detail-list">
        {contact.semInteresse ? (
          <div>
            <dt>Motivo (Fora da igreja)</dt>
            <dd>{contact.semInteresseMotivo?.trim() || "—"}</dd>
          </div>
        ) : null}
        <div>
          <dt>Acompanhamento</dt>
          <dd>
            <StatusPill tone={status.tone}>{status.label}</StatusPill>
          </dd>
        </div>
        {!contact.semInteresse ? (
          <div>
            <dt>Liderança</dt>
            <dd>
              {contact.liderDeCelula
                ? "Líder de célula"
                : contact.aptoLider
                  ? "Apto a liderar (sem célula)"
                  : "—"}
            </dd>
          </div>
        ) : null}
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

      {!isArquivada && !contact.celulaId ? (
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

      {canEdit && !isArquivada ? (
        <button
          type="button"
          className="btn btn-block"
          onClick={onEdit}
          style={{ marginTop: !contact.celulaId ? "var(--s2)" : 0 }}
        >
          Editar dados
        </button>
      ) : null}

      {canEdit && !isArquivada ? (
        <button
          type="button"
          className="btn btn-danger btn-block"
          onClick={onArchive}
          disabled={busy}
          style={{ marginTop: "var(--s2)" }}
        >
          <Icon name="lock" />
          <span>Arquivar pessoa</span>
        </button>
      ) : null}
    </div>
  );
}
