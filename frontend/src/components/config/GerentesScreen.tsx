"use client";

/**
 * Tela #gerentes — operadores do sistema (papéis OPERACIONAIS, não ministeriais).
 * Consome api-system-managers (GET/POST/DELETE /system-managers).
 *
 * Regras refletidas na UI (garantidas no backend):
 *  - telas de Configuração são admin-only (delta-005);
 *  - e-mail duplicado é rejeitado (409) com erro inline no formulário;
 *  - o próprio usuário não pode se remover (evita igreja sem administrador).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/dashboard/StatusPill";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { SessionExpiredError } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/dashboard-api";
import { Icon } from "@/lib/icons";
import {
  createManager,
  deleteManager,
  fetchManagers,
  ManagerConflictError,
  OPERATIONAL_ROLE_LABEL,
  type OperationalRole,
  type SystemManager,
} from "@/lib/system-managers-api";

interface Toast {
  kind: "ok" | "err";
  text: string;
}

const ROLE_OPTIONS: OperationalRole[] = ["admin_sistema", "operador"];

function roleTone(role: OperationalRole | null) {
  return role === "admin_sistema" ? "accent" : "muted";
}

export function GerentesScreen() {
  const { token, user, expireSession } = useAuth();

  const [managers, setManagers] = useState<SystemManager[]>([]);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // formulário de novo gerente
  const [formOpen, setFormOpen] = useState(false);
  const [nome, setNome] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<OperationalRole>("operador");
  const [formError, setFormError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [removingId, setRemovingId] = useState<string | null>(null);

  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | null>(null);
  const flashToast = useCallback((t: Toast) => {
    setToast(t);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3600);
  }, []);
  useEffect(
    () => () => {
      if (toastTimer.current) window.clearTimeout(toastTimer.current);
    },
    [],
  );

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
        const list = await fetchManagers(token);
        setManagers(list);
        setLoaded(true);
      } catch (err) {
        if (handleSessionError(err)) return;
        setError(
          err instanceof ApiError ? err.message : "Não foi possível carregar os gerentes.",
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

  const resetForm = useCallback(() => {
    setFormOpen(false);
    setNome("");
    setEmail("");
    setRole("operador");
    setFormError(null);
  }, []);

  const emailValid = (value: string) => /\S+@\S+\.\S+/.test(value.trim());
  const formReady = nome.trim().length > 0 && emailValid(email);

  const submit = useCallback(async () => {
    if (!token || !formReady) return;
    setCreating(true);
    setFormError(null);
    try {
      await createManager(token, {
        nome: nome.trim(),
        email: email.trim().toLowerCase(),
        papelOperacional: role,
      });
      flashToast({ kind: "ok", text: `${nome.trim()} adicionado como gerente.` });
      resetForm();
      await load("retry");
    } catch (err) {
      if (handleSessionError(err)) return;
      if (err instanceof ManagerConflictError) {
        setFormError(err.message);
      } else {
        setFormError(err instanceof ApiError ? err.message : "Não foi possível adicionar o gerente.");
      }
    } finally {
      setCreating(false);
    }
  }, [token, formReady, nome, email, role, flashToast, resetForm, load, handleSessionError]);

  const remove = useCallback(
    async (manager: SystemManager) => {
      if (!token) return;
      setRemovingId(manager.id);
      try {
        await deleteManager(token, manager.id);
        flashToast({ kind: "ok", text: `${manager.nome} removido.` });
        await load("retry");
      } catch (err) {
        if (handleSessionError(err)) return;
        flashToast({
          kind: "err",
          text: err instanceof ApiError ? err.message : "Não foi possível remover o gerente.",
        });
      } finally {
        setRemovingId(null);
      }
    },
    [token, flashToast, load, handleSessionError],
  );

  const isSelf = useCallback(
    (manager: SystemManager) =>
      user != null && manager.email.toLowerCase() === user.email.toLowerCase(),
    [user],
  );

  const columns: Array<Column<SystemManager>> = useMemo(
    () => [
      {
        header: "Pessoa",
        cell: (m) => (
          <div>
            <div className="nm">{m.nome}</div>
            <div className="sub mono">{m.email}</div>
          </div>
        ),
      },
      {
        header: "Acesso de sistema",
        cell: (m) => (
          <StatusPill tone={roleTone(m.papelOperacional)}>
            {m.papelOperacional ? OPERATIONAL_ROLE_LABEL[m.papelOperacional] : "—"}
          </StatusPill>
        ),
      },
      {
        header: "",
        width: "1px",
        cell: (m) =>
          isSelf(m) ? (
            <StatusPill tone="muted">Você</StatusPill>
          ) : (
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={() => void remove(m)}
              disabled={removingId === m.id}
              aria-busy={removingId === m.id || undefined}
            >
              {removingId === m.id ? "Removendo…" : "Remover"}
            </button>
          ),
      },
    ],
    [isSelf, remove, removingId],
  );

  const showSkeleton = loading && !loaded;

  return (
    <div className="screen" key="gerentes">
      <div className="screen-head">
        <div className="titles">
          <h2>Gerentes de Sistema</h2>
          <p>
            Papéis de operação do sistema (não confundir com cargos ministeriais).
            Gerentes administram a configuração da igreja como cliente do PastorAI.
          </p>
        </div>
        <div className="actions">
          <button type="button" className="btn btn-primary" onClick={() => setFormOpen((v) => !v)}>
            <Icon name="plus" />
            <span>Adicionar gerente</span>
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

      {formOpen ? (
        <form
          className="card card-pad"
          style={{ marginBottom: "var(--s4)" }}
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {formError ? (
            <div className="error-banner" role="alert" style={{ marginBottom: "var(--s3)" }}>
              <Icon name="alert" />
              <span>{formError}</span>
            </div>
          ) : null}
          <div className="row" style={{ marginBottom: "var(--s3)" }}>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="mgrName">Nome</label>
              <input
                id="mgrName"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Nome completo"
                autoFocus
              />
            </div>
            <div className="field" style={{ margin: 0 }}>
              <label htmlFor="mgrEmail">E-mail</label>
              <input
                id="mgrEmail"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="operador@igreja.com.br"
              />
            </div>
          </div>
          <div className="field" style={{ marginBottom: "var(--s3)" }}>
            <label htmlFor="mgrRole">Acesso de sistema</label>
            <select
              id="mgrRole"
              value={role}
              onChange={(e) => setRole(e.target.value as OperationalRole)}
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {OPERATIONAL_ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!formReady || creating}
              aria-busy={creating || undefined}
            >
              {creating ? "Adicionando…" : "Adicionar gerente"}
            </button>
            <button type="button" className="btn" onClick={resetForm} disabled={creating}>
              Cancelar
            </button>
          </div>
        </form>
      ) : null}

      <div className="card" style={{ marginBottom: "var(--s4)" }}>
        <div className="panel-title">
          <Icon name="agent" />
          <span>Operadores do sistema desta igreja</span>
        </div>
        {showSkeleton ? (
          <div className="queue" style={{ padding: "var(--s4)" }}>
            {Array.from({ length: 3 }).map((_, i) => (
              <div className="qitem skeleton" key={i}>
                <div className="qbody">
                  <div className="sk-line sk-md" />
                  <div className="sk-line sk-sm" />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <DataTable
            columns={columns}
            rows={managers}
            rowKey={(m) => m.id}
            empty={{
              icon: "shield",
              title: "Nenhum gerente de sistema ainda.",
              hint: "Adicione um operador para apoiar a administração.",
            }}
          />
        )}
      </div>

      <div className="card card-pad">
        <div className="panel-title" style={{ padding: "0 0 var(--s3)" }}>
          Níveis de acesso de sistema
        </div>
        <div className="config-row">
          <span>
            <strong>Administrador</strong>{" "}
            <span className="sub" style={{ color: "var(--muted)" }}>
              · acesso total + Configuração da igreja
            </span>
          </span>
          <StatusPill tone="accent">Gerencia o SaaS</StatusPill>
        </div>
        <div className="config-row">
          <span>
            <strong>Operador</strong>{" "}
            <span className="sub" style={{ color: "var(--muted)" }}>
              · atendimento humano e cadastros, sem faturamento
            </span>
          </span>
          <StatusPill tone="muted">Operação</StatusPill>
        </div>
        <p className="lock-note" style={{ marginTop: "var(--s3)" }}>
          Cargos ministeriais (Pastor, Líder G12, Líder de Célula…) são
          atualizados automaticamente pela trilha em Pessoas. Aqui
          ficam apenas os papéis de operação do sistema.
        </p>
      </div>

      {toast ? (
        <div className={`toast ${toast.kind}`} role="status">
          <Icon name={toast.kind === "ok" ? "check" : "alert"} />
          <span>{toast.text}</span>
        </div>
      ) : null}
    </div>
  );
}
