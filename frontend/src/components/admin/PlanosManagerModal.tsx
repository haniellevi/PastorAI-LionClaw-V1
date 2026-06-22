"use client";

/**
 * Gestão de planos do console master ("o master define os planos"): lista o
 * catálogo (tabela `planos`, migration 0012), cria/edita/exclui. O código é a
 * chave estável (igrejas.plano referencia) — imutável após criado. Excluir só é
 * permitido quando nenhuma igreja usa o plano (senão o backend devolve 409 e a
 * orientação é desativar). Alimenta também os seletores de plano dos modais de
 * provisionar/editar igreja (via onChanged → recarrega).
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import {
  AdminSessionExpiredError,
  createPlano,
  deletePlano,
  listPlanos,
  updatePlano,
  type AdminPlano,
} from "@/lib/admin-api";

const brl = (v: number) =>
  v.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

interface FormState {
  codigo: string;
  nome: string;
  limite: string; // "" => ilimitado
  preco: string;
  ordem: string;
  ativo: boolean;
}

const EMPTY: FormState = {
  codigo: "",
  nome: "",
  limite: "",
  preco: "",
  ordem: "0",
  ativo: true,
};

function toForm(p: AdminPlano): FormState {
  return {
    codigo: p.codigo,
    nome: p.nome,
    limite: p.limitePessoas == null ? "" : String(p.limitePessoas),
    preco: String(p.precoMensal),
    ordem: String(p.ordem),
    ativo: p.ativo,
  };
}

export interface PlanosManagerModalProps {
  token: string;
  onClose: () => void;
  onExpired: () => void;
  /** Chamado após criar/editar/excluir, para os modais de igreja recarregarem. */
  onChanged?: () => void;
}

export function PlanosManagerModal({
  token,
  onClose,
  onExpired,
  onChanged,
}: PlanosManagerModalProps) {
  const [planos, setPlanos] = useState<AdminPlano[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // null = listando; "new" = criando; AdminPlano = editando aquele plano.
  const [editing, setEditing] = useState<AdminPlano | "new" | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const handleErr = useCallback(
    (err: unknown, fallback: string): string | null => {
      if (err instanceof AdminSessionExpiredError) {
        onExpired();
        return null;
      }
      return err instanceof Error ? err.message : fallback;
    },
    [onExpired],
  );

  const load = useCallback(async () => {
    setError(null);
    try {
      setPlanos(await listPlanos(token));
    } catch (err) {
      const m = handleErr(err, "Não foi possível carregar os planos.");
      if (m) setError(m);
    }
  }, [token, handleErr]);

  useEffect(() => {
    void load();
  }, [load]);

  const startNew = () => {
    setForm(EMPTY);
    setFormError(null);
    setEditing("new");
  };
  const startEdit = (p: AdminPlano) => {
    setForm(toForm(p));
    setFormError(null);
    setEditing(p);
  };
  const cancel = () => {
    setEditing(null);
    setFormError(null);
  };

  const save = async () => {
    const codigo = form.codigo.trim().toLowerCase();
    const nome = form.nome.trim();
    const preco = Number(form.preco);
    const ordem = Number(form.ordem || "0");
    const limite = form.limite.trim() === "" ? null : Number(form.limite);

    if (!nome) {
      setFormError("Informe o nome do plano.");
      return;
    }
    if (!Number.isFinite(preco) || preco < 0) {
      setFormError("Preço mensal inválido.");
      return;
    }
    if (limite != null && (!Number.isInteger(limite) || limite < 1)) {
      setFormError("Limite de pessoas inválido (use um inteiro ≥ 1 ou deixe vazio).");
      return;
    }
    if (editing === "new" && !/^[a-z0-9_]+$/.test(codigo)) {
      setFormError("Código: só letras minúsculas, números e _ (ex.: premium).");
      return;
    }

    setBusy(true);
    setFormError(null);
    try {
      if (editing === "new") {
        await createPlano(token, {
          codigo,
          nome,
          limitePessoas: limite,
          precoMensal: preco,
          ordem,
        });
      } else if (editing) {
        await updatePlano(token, editing.id, {
          nome,
          limitePessoas: limite,
          precoMensal: preco,
          ordem,
          ativo: form.ativo,
        });
      }
      setEditing(null);
      await load();
      onChanged?.();
    } catch (err) {
      const m = handleErr(err, "Não foi possível salvar o plano.");
      if (m) setFormError(m);
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: AdminPlano) => {
    if (
      !window.confirm(
        `Excluir o plano "${p.nome}"? Esta ação é irreversível.`,
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deletePlano(token, p.id);
      await load();
      onChanged?.();
    } catch (err) {
      const m = handleErr(err, "Não foi possível excluir o plano.");
      if (m) setError(m); // o 409 (plano em uso) chega aqui
    } finally {
      setBusy(false);
    }
  };

  const isForm = editing !== null;

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="Gestão de planos"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 640 }}
      >
        <div className="modal-head">
          <strong>{isForm ? (editing === "new" ? "Novo plano" : "Editar plano") : "Planos"}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        {isForm ? (
          <form
            className="modal-form"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            {formError ? (
              <div className="error-banner" role="alert">
                <span>{formError}</span>
              </div>
            ) : null}

            <Field
              label="Código"
              value={form.codigo}
              onChange={(e) => setForm({ ...form, codigo: e.target.value })}
              placeholder="ex.: premium"
              helper={
                editing === "new"
                  ? "Identificador estável do plano (não muda depois)."
                  : "O código não pode ser alterado."
              }
              disabled={editing !== "new"}
            />
            <Field
              label="Nome"
              value={form.nome}
              onChange={(e) => setForm({ ...form, nome: e.target.value })}
              placeholder="Ex.: Até 100 pessoas"
              autoFocus={editing !== "new"}
            />
            <Field
              label="Preço mensal (R$)"
              type="number"
              min={0}
              step="0.01"
              value={form.preco}
              onChange={(e) => setForm({ ...form, preco: e.target.value })}
              placeholder="199"
            />
            <Field
              label="Limite de pessoas"
              type="number"
              min={1}
              value={form.limite}
              onChange={(e) => setForm({ ...form, limite: e.target.value })}
              placeholder="Deixe vazio para ilimitado"
              helper="Vazio = ilimitado."
            />
            <Field
              label="Ordem de exibição"
              type="number"
              min={0}
              value={form.ordem}
              onChange={(e) => setForm({ ...form, ordem: e.target.value })}
            />
            {editing !== "new" ? (
              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--s2)",
                  cursor: "pointer",
                }}
              >
                <input
                  type="checkbox"
                  checked={form.ativo}
                  onChange={(e) => setForm({ ...form, ativo: e.target.checked })}
                />
                <span>Plano ativo (visível para as igrejas)</span>
              </label>
            ) : null}

            <div className="modal-foot">
              <button
                type="button"
                className="btn btn-sm"
                onClick={cancel}
                disabled={busy}
              >
                Voltar
              </button>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                loading={busy}
                loadingText="Salvando…"
              >
                Salvar plano
              </Button>
            </div>
          </form>
        ) : (
          <div className="modal-form">
            {error ? (
              <div className="error-banner" role="alert">
                <span>{error}</span>
              </div>
            ) : null}

            {planos === null ? (
              <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
                <span className="spinner" aria-hidden="true" />
                <div className="sub" style={{ marginTop: "var(--s2)" }}>
                  Carregando os planos…
                </div>
              </div>
            ) : planos.length === 0 ? (
              <p className="sub" style={{ color: "var(--muted)" }}>
                Nenhum plano cadastrado.
              </p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Plano</th>
                    <th className="num">Limite</th>
                    <th className="num">Mensalidade</th>
                    <th className="num">Em uso</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {planos.map((p) => (
                    <tr key={p.id} style={{ opacity: p.ativo ? 1 : 0.55 }}>
                      <td className="nm">
                        {p.nome}
                        <div className="sub" style={{ color: "var(--muted)" }}>
                          {p.codigo}
                          {p.ativo ? "" : " · inativo"}
                        </div>
                      </td>
                      <td className="num">
                        {p.limitePessoas == null ? "Ilimitado" : p.limitePessoas}
                      </td>
                      <td className="num">{brl(p.precoMensal)}</td>
                      <td className="num">{p.emUso}</td>
                      <td>
                        <div style={{ display: "flex", gap: "var(--s2)", justifyContent: "flex-end" }}>
                          <button
                            type="button"
                            className="btn btn-sm btn-ghost"
                            onClick={() => startEdit(p)}
                            disabled={busy}
                          >
                            Editar
                          </button>
                          <button
                            type="button"
                            className="btn btn-sm btn-danger"
                            onClick={() => void remove(p)}
                            disabled={busy || p.emUso > 0}
                            title={
                              p.emUso > 0
                                ? "Há igrejas neste plano — desative em vez de excluir."
                                : undefined
                            }
                          >
                            Excluir
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="modal-foot">
              <button type="button" className="btn btn-sm" onClick={onClose}>
                Fechar
              </button>
              <Button variant="primary" size="sm" onClick={startNew} disabled={busy}>
                Novo plano
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
