"use client";

/**
 * Configuração do AGENTE de IA de uma igreja, feita pelo MASTER (cross-tenant).
 * Decisão de produto: o comportamento do agente é responsabilidade da plataforma
 * (provedor), não do dono da igreja — o dono só vê (read-only) no painel dele. A
 * chave de LLM segue sendo do dono; aqui o master só configura comportamento e
 * liga/desliga (ligar exige que a igreja tenha uma credencial ativa → 409).
 */
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import {
  AdminSessionExpiredError,
  fetchIgrejaAgente,
  saveIgrejaAgente,
  type AdminIgreja,
} from "@/lib/admin-api";

const CRED_LABEL: Record<string, string> = {
  active: "Credencial de IA ativa (chave do dono)",
  invalid: "A igreja tem uma chave inválida — não dá pra ligar o agente",
  none: "A igreja ainda não cadastrou a chave de LLM — não dá pra ligar o agente",
};

export interface IgrejaAgenteModalProps {
  igreja: AdminIgreja;
  token: string;
  onClose: () => void;
  onExpired: () => void;
  onSaved?: () => void;
}

export function IgrejaAgenteModal({
  igreja,
  token,
  onClose,
  onExpired,
  onSaved,
}: IgrejaAgenteModalProps) {
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [nome, setNome] = useState("");
  const [tom, setTom] = useState("");
  const [comportamento, setComportamento] = useState("");
  const [ativo, setAtivo] = useState(false);
  const [credStatus, setCredStatus] = useState<"active" | "invalid" | "none">("none");

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

  useEffect(() => {
    let alive = true;
    fetchIgrejaAgente(token, igreja.id)
      .then((a) => {
        if (!alive) return;
        setNome(a.nome ?? "");
        setTom(a.tom ?? "");
        setComportamento(a.comportamento ?? "");
        setAtivo(a.ativo);
        setCredStatus(a.credencialStatus);
        setLoaded(true);
      })
      .catch((err) => {
        if (!alive) return;
        const m = handleErr(err, "Não foi possível carregar o agente.");
        if (m) {
          setError(m);
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [token, igreja.id, handleErr]);

  const save = async () => {
    if (!comportamento.trim()) {
      setError("Descreva o comportamento do agente.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await saveIgrejaAgente(token, igreja.id, {
        comportamento: comportamento.trim(),
        nome: nome.trim() || null,
        tom: tom.trim() || null,
        ativo,
      });
      onSaved?.();
      onClose();
    } catch (err) {
      const m = handleErr(err, "Não foi possível salvar o agente.");
      if (m) {
        setError(m);
        setAtivo(false); // 409: reverte o "ligar" se faltou credencial
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Agente de ${igreja.nome}`}
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 600 }}
      >
        <div className="modal-head">
          <strong>Agente de IA · {igreja.nome}</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <form
          className="modal-form"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          {error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
            </div>
          ) : null}

          {!loaded ? (
            <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
              <span className="spinner" aria-hidden="true" />
              <div className="sub" style={{ marginTop: "var(--s2)" }}>
                Carregando o agente…
              </div>
            </div>
          ) : (
            <>
              <div className="field">
                <label htmlFor="ag-nome">Nome do agente</label>
                <input
                  id="ag-nome"
                  value={nome}
                  onChange={(e) => setNome(e.target.value)}
                  placeholder="Ex.: Pastora Ana"
                />
              </div>
              <div className="field">
                <label htmlFor="ag-tom">Tom de voz</label>
                <input
                  id="ag-tom"
                  value={tom}
                  onChange={(e) => setTom(e.target.value)}
                  placeholder="Ex.: acolhedor e pastoral"
                />
              </div>
              <div className="field">
                <label htmlFor="ag-comp">Comportamento e instruções</label>
                <textarea
                  id="ag-comp"
                  rows={7}
                  value={comportamento}
                  onChange={(e) => setComportamento(e.target.value)}
                  placeholder="Descreva como o agente orquestrador deve se comunicar, o que pode e o que não pode fazer…"
                />
              </div>

              <label
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--s2)",
                  cursor: credStatus === "active" ? "pointer" : "not-allowed",
                  opacity: credStatus === "active" ? 1 : 0.6,
                }}
              >
                <input
                  type="checkbox"
                  checked={ativo}
                  disabled={credStatus !== "active"}
                  onChange={(e) => setAtivo(e.target.checked)}
                />
                <span>Agente ativo</span>
              </label>
              <p className="sub" style={{ color: "var(--muted)", marginTop: "var(--s1)" }}>
                {CRED_LABEL[credStatus]}
              </p>

              <div className="modal-foot">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={onClose}
                  disabled={busy}
                >
                  Cancelar
                </button>
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  loading={busy}
                  loadingText="Salvando…"
                >
                  Salvar agente
                </Button>
              </div>
            </>
          )}
        </form>
      </div>
    </div>
  );
}
