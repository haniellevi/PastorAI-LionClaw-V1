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
import { useCallback, useEffect, useState } from "react";

import { EditContactModal } from "@/components/contacts/EditContactModal";
import { Button } from "@/components/ui/Button";
import { SessionExpiredError } from "@/lib/api";
import {
  fetchContactDetail,
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

/** Linha rótulo/valor; mostra "—" quando vazio. */
function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="panel-row">
      <dt>{label}</dt>
      <dd>{value && value.trim() ? value : "—"}</dd>
    </div>
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

  const [detail, setDetail] = useState<ContactDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

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

  return (
    <aside className="conv-panel" aria-label="Dados do contato">
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
              {detail.tipo ? (
                <span className="panel-tipo">{tipoLabel(detail.tipo)}</span>
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

          <section className="panel-section">
            <h4>Jornada G12</h4>
            <dl>
              <Row label="Etapa" value={detail.etapa ? ETAPA_LABEL[detail.etapa] ?? detail.etapa : null} />
              <Row label="Subetapa" value={detail.subetapa} />
              <Row label="Acompanhamento" value={detail.acompanhamento} />
              <Row label="Presenças na célula" value={String(detail.presencasCelula)} />
              <Row label="Aceitou Jesus" value={detail.aceitouJesus ? "Sim" : "Não"} />
              <Row label="Célula" value={detail.celulaNome} />
              <Row label="Líder" value={detail.liderNome} />
            </dl>
          </section>

          <section className="panel-section">
            <h4>Cadastro</h4>
            <dl>
              <Row label="Tipo" value={detail.tipo ? tipoLabel(detail.tipo) : null} />
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
              <Row label="Primeiro contato" value={fmtDate(detail.primeiroContato)} />
              <Row label="Cadastrado em" value={fmtDate(detail.criadoEm)} />
            </dl>
          </section>
        </div>
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
