"use client";

/**
 * contact-panel — 3ª coluna do inbox (Parte B). Mostra os dados da pessoa
 * vinculada à conversa (contato, jornada G12, cadastro) e, para admin, permite
 * editar reaproveitando o EditContactModal (PATCH /contacts/{id}).
 *
 * Busca o detalhe via GET /contacts/{id} ao trocar de conversa. Conversas sem
 * pessoa vinculada (pessoaId null) exibem um aviso amigável — não há cadastro
 * ainda para aquele número.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { EditContactModal } from "@/components/contacts/EditContactModal";
import { Dialog } from "@/components/ds/Dialog";
import { getFocusable, trapNextIndex } from "@/components/ds/a11y";
import { Button } from "@/components/ui/Button";
import { SessionExpiredError } from "@/lib/api";
import {
  fetchContactDetail,
  reactivateCommunications,
  tipoLabel,
  updateContact,
  type Contact,
  type ContactDetail,
  type UpdateContactInput,
} from "@/lib/contacts-api";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import { isAdmin } from "@/lib/roles";
import { useAuth } from "@/lib/auth-context";

const GENERO_LABEL: Record<string, string> = { m: "Masculino", f: "Feminino" };
const ETAPA_LABEL: Record<string, string> = {
  ganhar: "Ganhar",
  consolidar: "Consolidar",
  discipular: "Discipular",
  enviar: "Enviar",
};

function fmtDate(iso: string | null): string | null {
  if (!iso) return null;
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;
  return new Date(ts).toLocaleDateString("pt-BR", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function initials(nome: string): string {
  const parts = nome.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : "";
  return (first + last).toUpperCase() || "?";
}

/** Linha rótulo/valor; some quando vazio (painel mostra só o que está preenchido). */
function Row({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value || !value.trim()) return null;
  return (
    <div className="panel-row">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

/** Há algum dado de jornada G12 preenchido? (senão, esconde a seção inteira) */
function hasJornadaData(d: ContactDetail): boolean {
  return Boolean(
    d.etapa ||
      d.subetapa ||
      d.acompanhamento ||
      d.presencasCelula > 0 ||
      d.aceitouJesus ||
      d.celulaNome ||
      d.liderNome,
  );
}

/** Constrói um `Contact` (forma do EditContactModal) a partir do detalhe. */
function toContact(d: ContactDetail): Contact {
  return {
    id: d.id,
    nome: d.nome,
    telefone: d.telefone,
    email: d.email,
    genero: d.genero,
    tipo: d.tipo,
    etapa: d.etapa,
    subetapa: d.subetapa,
    acompanhamento: d.acompanhamento,
    semInteresse: d.semInteresse,
    semInteresseMotivo: d.semInteresseMotivo,
    presencasCelula: d.presencasCelula,
    aceitouJesus: d.aceitouJesus,
    celulaId: d.celulaId,
    liderId: d.liderId,
    aptoLider: d.aptoLider,
    liderDeCelula: d.liderDeCelula,
  };
}

export function ContactPanel({
  pessoaId,
  telefone,
  avatarUrl,
  onClose,
}: {
  pessoaId: string | null;
  telefone: string;
  avatarUrl?: string | null;
  onClose: () => void;
}) {
  const { token, user, expireSession } = useAuth();
  const canEdit = user ? isAdmin(user.roles) : false;
  // FECH-05/OPTIN-1: espelha o guard do backend (require_role admin/pastor).
  // RBAC real é do servidor — aqui é só visibilidade do botão.
  const canReactivate = user
    ? user.roles.includes("admin") || user.roles.includes("pastor")
    : false;

  // Gate 8: o painel é um DRAWER sob demanda — acessível como o ds/Dialog
  // (mesma lógica de foco de ds/a11y): foco inicial no primeiro focável,
  // Tab/Shift+Tab contidos, Esc fecha, foco retorna a quem abriu.
  const rootRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  useEffect(() => {
    const panel = rootRef.current;
    if (!panel) return;
    const opener = document.activeElement as HTMLElement | null;
    const focusables = getFocusable(panel);
    (focusables[0] ?? panel).focus();
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape" || e.key === "Tab") {
        // Diálogo modal interno aberto (ds/Dialog só existe no DOM enquanto
        // `open`): TODO o teclado pertence a ELE — o Escape fecha o diálogo
        // (respeitando o guard `busy` do onClose dele) e o focus-trap de
        // Tab/Shift+Tab é o do Dialog. Este listener capture roda ANTES do
        // listener do Dialog; consumir aqui fecharia o painel por cima do
        // diálogo ou moveria o foco para controles do drawer. Detecção no
        // PRÓPRIO painel (não global) e via DOM: o effect tem deps vazias e
        // um state capturado aqui estaria stale. Cobre o diálogo de
        // reativação e o EditContactModal.
        if (panel!.querySelector('[role="dialog"][aria-modal="true"]')) return;
      }
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== "Tab") return;
      // Foco fora do drawer (ex.: outro overlay da página): não interferir.
      if (!panel!.contains(document.activeElement)) return;
      const items = getFocusable(panel!);
      const current = items.indexOf(document.activeElement as HTMLElement);
      const next = trapNextIndex(current, items.length, e.shiftKey);
      e.preventDefault();
      if (next >= 0) items[next]?.focus();
      else panel!.focus();
    }
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      opener?.focus();
    };
  }, []);

  const [detail, setDetail] = useState<ContactDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  // Reativação de comunicações (FECH-05/OPTIN-1) — confirmação via ds/Dialog.
  const [reactivateOpen, setReactivateOpen] = useState(false);
  const [reactivateBusy, setReactivateBusy] = useState(false);
  const [reactivateError, setReactivateError] = useState<string | null>(null);
  const [reactivateSuccess, setReactivateSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !pessoaId) return;
    setLoading(true);
    setError(null);
    try {
      const d = await fetchContactDetail(token, pessoaId);
      setDetail(d);
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setError(
        err instanceof ApiError ? err.message : "Não foi possível carregar os dados.",
      );
    } finally {
      setLoading(false);
    }
  }, [token, pessoaId, expireSession]);

  useEffect(() => {
    setDetail(null);
    setEditing(false);
    setError(null);
    setReactivateOpen(false);
    setReactivateError(null);
    setReactivateSuccess(null);
    if (pessoaId) void load();
  }, [pessoaId, load]);

  const handleEditSubmit = useCallback(
    async (input: UpdateContactInput) => {
      if (!token || !detail) return;
      setSaving(true);
      setEditError(null);
      try {
        await updateContact(token, detail.id, input);
        setEditing(false);
        await load(); // re-busca o detalhe já atualizado
      } catch (err) {
        if (err instanceof SessionExpiredError) {
          expireSession();
          return;
        }
        setEditError(
          err instanceof ApiError ? err.message : "Não foi possível salvar as alterações.",
        );
      } finally {
        setSaving(false);
      }
    },
    [token, detail, load, expireSession],
  );

  const handleReactivate = useCallback(async () => {
    if (!token || !detail) return;
    setReactivateBusy(true);
    setReactivateError(null);
    try {
      await reactivateCommunications(token, detail.id);
      setReactivateOpen(false);
      setReactivateSuccess("Comunicações reativadas com sucesso.");
      await load(); // re-busca o detalhe: optout=false some com o botão
    } catch (err) {
      if (err instanceof SessionExpiredError) {
        expireSession();
        return;
      }
      setReactivateError(
        err instanceof ApiError
          ? err.message
          : "Não foi possível reativar as comunicações.",
      );
    } finally {
      setReactivateBusy(false);
    }
  }, [token, detail, load, expireSession]);

  return (
    // W5A: painel lateral (drawer), não é modal — sem role de dialog nem
    // aria-modal. O aria-label permanece nomeando a landmark <aside>; o
    // tabIndex sustenta o fallback de foco da lógica de teclado acima.
    <aside
      ref={rootRef}
      className="conv-panel"
      aria-label="Dados do contato"
      tabIndex={-1}
    >
      <div className="panel-head">
        <strong>Dados do contato</strong>
        <button
          type="button"
          className="btn btn-icon"
          onClick={onClose}
          aria-label="Fechar painel de dados"
          title="Fechar"
        >
          <Icon name="close" />
        </button>
      </div>

      {!pessoaId ? (
        <div className="panel-empty">
          <Icon name="user" />
          <p>
            <strong>Contato ainda não cadastrado.</strong>
          </p>
          <p className="sub">
            Este número ({telefone}) não está vinculado a uma pessoa na base. Cadastre
            o contato em <em>Ganhar</em> para acompanhar a jornada dele.
          </p>
        </div>
      ) : loading && !detail ? (
        <p className="panel-loading">Carregando dados…</p>
      ) : error ? (
        <div className="panel-body">
          <div className="error-banner" role="alert">
            <Icon name="alert" />
            <span>{error}</span>
          </div>
          <Button size="sm" onClick={() => void load()}>
            Tentar novamente
          </Button>
        </div>
      ) : detail ? (
        <div className="panel-body">
          <div className="panel-id">
            <span className="panel-av">
              {avatarUrl ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={avatarUrl} alt="" className="av-img" />
              ) : (
                initials(detail.nome)
              )}
            </span>
            <div className="panel-id-main">
              <strong>{detail.nome}</strong>
              {detail.semInteresse || detail.tipo ? (
                <span className={`panel-tipo${detail.semInteresse ? " csim" : ""}`}>
                  {detail.semInteresse ? "Fora da igreja" : tipoLabel(detail.tipo)}
                </span>
              ) : null}
            </div>
          </div>

          {canEdit ? (
            <Button size="sm" block onClick={() => setEditing(true)}>
              <Icon name="user" />
              <span>Editar dados</span>
            </Button>
          ) : null}

          <section className="panel-section">
            <h4>Contato</h4>
            <dl>
              <Row label="Telefone" value={detail.telefone} />
              <Row label="E-mail" value={detail.email} />
              <Row label="Endereço" value={detail.endereco} />
            </dl>
          </section>

          {/* CSIM está fora da Visão G12 — esconde a seção de jornada inteira. */}
          {!detail.semInteresse && hasJornadaData(detail) ? (
            <section className="panel-section">
              <h4>Jornada G12</h4>
              <dl>
                <Row label="Etapa" value={detail.etapa ? ETAPA_LABEL[detail.etapa] ?? detail.etapa : null} />
                <Row label="Subetapa" value={detail.subetapa} />
                <Row label="Acompanhamento" value={detail.acompanhamento} />
                <Row
                  label="Presenças na célula"
                  value={detail.presencasCelula > 0 ? String(detail.presencasCelula) : null}
                />
                <Row label="Aceitou Jesus" value={detail.aceitouJesus ? "Sim" : null} />
                <Row label="Célula" value={detail.celulaNome} />
                <Row label="Líder" value={detail.liderNome} />
              </dl>
            </section>
          ) : null}

          <section className="panel-section">
            <h4>Cadastro</h4>
            <dl>
              <Row
                label="Tipo"
                value={
                  detail.semInteresse
                    ? "Fora da igreja"
                    : detail.tipo
                      ? tipoLabel(detail.tipo)
                      : null
                }
              />
              <Row
                label="Motivo (Fora da igreja)"
                value={detail.semInteresse ? detail.semInteresseMotivo : null}
              />
              <Row
                label="Gênero"
                value={detail.genero ? GENERO_LABEL[detail.genero] ?? detail.genero : null}
              />
              <Row label="Faixa etária" value={detail.faixaEtaria} />
              <Row label="Origem" value={detail.origem} />
              <Row
                label="Consentimento (LGPD)"
                value={detail.consentimento ? "Concedido" : "Pendente"}
              />
              <Row
                label="Comunicações"
                value={detail.optout ? "Opt-out (pausadas)" : null}
              />
              <Row label="Primeiro contato" value={fmtDate(detail.primeiroContato)} />
              <Row label="Cadastrado em" value={fmtDate(detail.criadoEm)} />
            </dl>
          </section>

          {/* FECH-05/OPTIN-1: feedback de sucesso persiste após o reload do
              detalhe (quando optout=false o botão abaixo já sumiu). */}
          {reactivateSuccess ? (
            <p className="panel-reactivate-success" role="status">
              {reactivateSuccess}
            </p>
          ) : null}

          {/* Botão só existe quando a pessoa está em opt-out (e para papéis
              que o backend aceita — admin/pastor). Confirmação via ds/Dialog. */}
          {detail.optout && canReactivate ? (
            <Button size="sm" block onClick={() => setReactivateOpen(true)}>
              <Icon name="chat" />
              <span>Reativar comunicações</span>
            </Button>
          ) : null}
        </div>
      ) : null}

      {detail ? (
        <Dialog
          open={reactivateOpen}
          onClose={() => {
            if (reactivateBusy) return;
            setReactivateOpen(false);
            setReactivateError(null);
          }}
          title="Reativar comunicações"
          description={`${detail.nome} voltará a receber mensagens da igreja pelo WhatsApp.`}
          footer={
            <>
              <Button
                onClick={() => {
                  setReactivateOpen(false);
                  setReactivateError(null);
                }}
                disabled={reactivateBusy}
              >
                Cancelar
              </Button>
              <Button
                variant="primary"
                loading={reactivateBusy}
                loadingText="Reativando…"
                onClick={() => void handleReactivate()}
              >
                Reativar comunicações
              </Button>
            </>
          }
        >
          <p>
            Esta pessoa pediu para não receber comunicações (opt-out). Ao
            confirmar, o opt-out é removido e um novo registro de consentimento
            de reativação é gravado — a retirada anterior permanece no
            histórico (LGPD).
          </p>
          {reactivateError ? (
            <div className="error-banner" role="alert">
              <Icon name="alert" />
              <span>{reactivateError}</span>
            </div>
          ) : null}
        </Dialog>
      ) : null}

      {editing && detail ? (
        <EditContactModal
          contact={toContact(detail)}
          busy={saving}
          error={editError}
          onClose={() => {
            setEditing(false);
            setEditError(null);
          }}
          onSubmit={handleEditSubmit}
        />
      ) : null}
    </aside>
  );
}
