"use client";

/**
 * Aba "Gerenciar células" da Central. Além das três listas de acompanhamento
 * (saúde US-18, relatórios pendentes US-16, multiplicações US-19), é AQUI que
 * a Central cadastra célula (PRD Central §6 / onboarding PR-O1): botão "Nova
 * célula" no topo e, quando a igreja ainda não tem célula, empty state com o
 * CTA "Criar primeira célula". Reusa o CellFormModal compartilhado;
 * permissão e elegibilidade continuam no backend (403/409/422 aparecem como
 * erro inline no modal).
 *
 * PR-A1.1: lista de células existentes p/ selecionar uma e abrir "Editar
 * célula" (CellFormModal em modo edição) ou "Adicionar à célula"
 * (AddCellMemberModal). Acesso ao painel permanece separado em Equipe.
 * Segue o mesmo padrão da tela legada #celulas (CelulasScreen), sem o painel de
 * detalhe/membros/alertas dela — fora de escopo aqui.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { DsBanner } from "@/components/ds/Banner";
import { DsButton } from "@/components/ds/Button";
import { DsEmptyState } from "@/components/ds/EmptyState";
import { StatusPill } from "@/components/dashboard/StatusPill";
import { CellFormModal } from "@/components/cells/CellFormModal";
import { AddCellMemberModal } from "@/components/cells/InviteMemberModal";
import { buildCellLeaderOptions } from "@/components/cells/cell-leadership";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import {
  fetchCellMembros,
  fetchCellsFull,
  upsertCell,
  type CellMembro,
  type CellSummary,
  type UpsertCellInput,
} from "@/lib/cells-api";
import { fetchContacts, type Contact } from "@/lib/contacts-api";
import { ApiError, fetchTeam, type TeamMember } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";

import { CellHealthList } from "./CellHealthList";
import { PendingReportsList } from "./PendingReportsList";
import { MultiplicationsList } from "./MultiplicationsList";
import type { CentralToast } from "./types";

export function cellMemberAddBlockReason(
  cell: Pick<CellSummary, "ativo" | "liderId">,
): string | null {
  if (!cell.ativo) return "Ative a célula antes de adicionar pessoas.";
  if (!cell.liderId) return "Defina um líder antes de adicionar pessoas à célula.";
  return null;
}

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
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<CellSummary | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showInvite, setShowInvite] = useState(false);

  // Discípulos vinculados (celula_membro) da célula selecionada — leitura.
  const [membros, setMembros] = useState<CellMembro[]>([]);
  const [membrosLoading, setMembrosLoading] = useState(false);
  const [membrosError, setMembrosError] = useState<string | null>(null);
  // Bump para reexecutar o fetch dos membros (retry manual e após vínculo).
  const [membrosNonce, setMembrosNonce] = useState(0);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [cellPage, contactPage, teamPage] = await Promise.all([
        fetchCellsFull(token),
        fetchContacts(token),
        fetchTeam(token),
      ]);
      setCells(cellPage.items);
      setContacts(contactPage.items);
      setTeam(teamPage.items);
      setLoaded(true);
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setLoadError(
        err instanceof ApiError
          ? err.message
          : "Não foi possível carregar células, Pessoas e acessos.",
      );
    }
  }, [token, expireSession]);

  useEffect(() => {
    void load();
  }, [load]);

  // A Central cruza Pessoa + Equipe completa. Convites pendentes, acessos
  // revogados, ausentes ou duplicados ficam visíveis com o motivo, sem poderem
  // ser escolhidos. O líder atual continua visível; pendência bloqueia salvar.
  const leaderOptions = useMemo(
    () => buildCellLeaderOptions(contacts, team, editing?.liderId),
    [contacts, team, editing],
  );

  const leaderName = useCallback(
    (id: string | null) => (id ? contacts.find((c) => c.id === id)?.nome ?? "—" : "—"),
    [contacts],
  );

  const selectedCell = useMemo(
    () => cells.find((c) => c.id === selectedId) ?? null,
    [cells, selectedId],
  );
  const addMemberBlockReason = selectedCell
    ? cellMemberAddBlockReason(selectedCell)
    : null;

  // Nome do vínculo resolvido pelos contatos já carregados (membros só têm id).
  const membroNome = useCallback(
    (pessoaId: string) => contacts.find((c) => c.id === pessoaId)?.nome ?? "—",
    [contacts],
  );

  // Carrega os discípulos vinculados ao selecionar a célula. O flag `cancelled`
  // descarta resposta de uma seleção anterior (trocar célula não mistura listas).
  useEffect(() => {
    if (!selectedId) {
      setMembros([]);
      setMembrosError(null);
      setMembrosLoading(false);
      return;
    }
    let cancelled = false;
    setMembrosLoading(true);
    setMembrosError(null);
    fetchCellMembros(token, selectedId)
      .then((rows) => {
        if (!cancelled) setMembros(rows);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof SessionExpiredError) {
          expireSession();
          return;
        }
        setMembrosError(
          err instanceof ApiError ? err.message : "Não foi possível carregar os discípulos.",
        );
      })
      .finally(() => {
        if (!cancelled) setMembrosLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, token, expireSession, membrosNonce]);

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

  const handleMemberAdded = useCallback(
    () => {
      // O modal mantém o sucesso visível; aqui apenas sincronizamos as leituras.
      void load();
      setMembrosNonce((n) => n + 1);
      onChanged();
    },
    [onChanged, load],
  );

  const showEmpty = loaded && !loadError && cells.length === 0;

  return (
    <div className="central-stack">
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <DsButton variant="primary" onClick={openForm} disabled={!loaded}>
          <Icon name="plus" />
          <span>Nova célula</span>
        </DsButton>
      </div>

      {!loaded && !loadError ? (
        <div className="card card-pad sub" role="status" aria-live="polite">
          Carregando células, Pessoas e acessos…
        </div>
      ) : null}

      {loadError ? (
        <DsBanner
          kind="error"
          action={
            <DsButton variant="secondary" onClick={() => void load()}>
              Tentar novamente
            </DsButton>
          }
        >
          {loadError}
        </DsBanner>
      ) : null}

      {showEmpty ? (
        <div className="card">
          <DsEmptyState
            illustration={<Icon name="central-celula" />}
            title="Nenhuma célula cadastrada."
            hint="Crie a primeira célula para começar a organizar líderes, membros e relatórios."
            action={
              <DsButton variant="primary" onClick={openForm}>
                <Icon name="plus" />
                <span>Criar primeira célula</span>
              </DsButton>
            }
          />
        </div>
      ) : null}

      {loaded && !showEmpty ? (
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
                  className={`cc-cell-row${selected ? " cc-cell-row--active" : ""}`}
                  onClick={() => setSelectedId(selected ? null : c.id)}
                  aria-pressed={selected}
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
            <>
              <div className="cell-detail-actions" style={{ padding: "var(--s3) var(--s4)", marginBottom: 0 }}>
                <DsButton variant="secondary" onClick={() => openEdit(selectedCell)} block>
                  <Icon name="document" />
                  <span>Editar célula</span>
                </DsButton>
                <DsButton
                  variant="primary"
                  onClick={() => setShowInvite(true)}
                  block
                  disabled={addMemberBlockReason !== null}
                  aria-describedby={
                    addMemberBlockReason ? "central-add-member-block-reason" : undefined
                  }
                  title={addMemberBlockReason ?? undefined}
                >
                  <Icon name="plus" />
                  <span>Adicionar à célula</span>
                </DsButton>
              </div>

              {addMemberBlockReason ? (
                <p
                  id="central-add-member-block-reason"
                  className="sub"
                  role="status"
                  aria-live="polite"
                  style={{ padding: "0 var(--s4) var(--s3)", color: "var(--muted)" }}
                >
                  {addMemberBlockReason}
                </p>
              ) : null}

              <div style={{ borderTop: "1px solid var(--border)" }}>
                <div className="panel-title" style={{ padding: "var(--s3) var(--s4)" }}>
                  Discípulos vinculados
                  {membros.length ? <span className="count">· {membros.length}</span> : null}
                </div>

                {membrosLoading ? (
                  <div className="sub" style={{ padding: "0 var(--s4) var(--s3)" }}>
                    Carregando…
                  </div>
                ) : membrosError ? (
                  <div style={{ margin: "0 var(--s4) var(--s3)" }}>
                    <DsBanner
                      kind="error"
                      action={
                        <DsButton variant="secondary" onClick={() => setMembrosNonce((n) => n + 1)}>
                          Tentar novamente
                        </DsButton>
                      }
                    >
                      {membrosError}
                    </DsBanner>
                  </div>
                ) : membros.length === 0 ? (
                  <div className="sub" style={{ padding: "0 var(--s4) var(--s3)" }}>
                    Nenhum discípulo vinculado a esta célula ainda.
                  </div>
                ) : (
                  <div>
                    {membros.map((m) => (
                      <div
                        key={m.id}
                        className="list-row"
                        style={{ borderTop: "1px solid var(--border)" }}
                      >
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div className="nm">{membroNome(m.pessoaId)}</div>
                        </div>
                        <StatusPill tone="ok">Ativo</StatusPill>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </>
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
          canManageLeadership
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
        <AddCellMemberModal
          celulaId={selectedCell.id}
          celulaNome={selectedCell.nome}
          contacts={contacts}
          onClose={() => setShowInvite(false)}
          onAdded={handleMemberAdded}
        />
      ) : null}
    </div>
  );
}
