"use client";

/**
 * Orquestrador padrão (modelo do master) — Fatia 3. Define UM comportamento base
 * ("começa igual a todas as igrejas"); ao aprovar uma igreja, esse modelo é
 * copiado para o agente dela. Aqui o master só edita o modelo; o ajuste por
 * igreja é na página da igreja (aba Agente). Não toca no runtime do agente.
 *
 * Wave Visual W4B: migração para o DsDialog (Esc/trap/backdrop/scroll-lock/
 * retorno de foco do primitive; fechar bloqueado em busy) — mesmos campos,
 * callbacks e textos. Enquanto os dados não carregam, o corpo mostra o spinner
 * e o rodapé de ações só aparece depois. O rodapé fica fora do <form>, então o
 * botão primário usa form="orquestrador-form" para preservar o submit por Enter.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Dialog as DsDialog } from "@/components/ds/Dialog";
import { Button } from "@/components/ui/Button";
import {
  AdminSessionExpiredError,
  fetchOrquestrador,
  saveOrquestrador,
} from "@/lib/admin-api";

export interface OrquestradorModalProps {
  token: string;
  onClose: () => void;
  onExpired: () => void;
}

export function OrquestradorModal({ token, onClose, onExpired }: OrquestradorModalProps) {
  const [loaded, setLoaded] = useState(false);
  const [nome, setNome] = useState("");
  const [tom, setTom] = useState("");
  const [comportamento, setComportamento] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const nomeRef = useRef<HTMLInputElement>(null);

  // Foco inicial correto: o Dialog monta em loading, então o efeito de foco do
  // primitive roda antes de o campo "Nome do agente" existir (cai no botão
  // Fechar). Quando os dados chegam, movemos o foco para o campo — solução
  // local ao modal, sem nova API no ds/Dialog.
  useEffect(() => {
    if (loaded) nomeRef.current?.focus();
  }, [loaded]);

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
    fetchOrquestrador(token)
      .then((o) => {
        if (!alive) return;
        setNome(o.nome ?? "");
        setTom(o.tom ?? "");
        setComportamento(o.comportamento ?? "");
        setLoaded(true);
      })
      .catch((err) => {
        if (!alive) return;
        const m = handleErr(err, "Não foi possível carregar o orquestrador.");
        if (m) {
          setError(m);
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, [token, handleErr]);

  const save = async () => {
    if (!comportamento.trim()) {
      setError("Descreva o comportamento do orquestrador.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await saveOrquestrador(token, {
        comportamento: comportamento.trim(),
        nome: nome.trim() || null,
        tom: tom.trim() || null,
      });
      setNotice("Modelo do orquestrador salvo.");
    } catch (err) {
      const m = handleErr(err, "Não foi possível salvar.");
      if (m) setError(m);
    } finally {
      setBusy(false);
    }
  };

  return (
    <DsDialog
      open
      onClose={() => {
        if (!busy) onClose();
      }}
      title="Orquestrador padrão"
      footer={
        loaded ? (
          <>
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Fechar
            </button>
            <Button
              type="submit"
              form="orquestrador-form"
              variant="primary"
              size="sm"
              loading={busy}
              loadingText="Salvando…"
            >
              Salvar modelo
            </Button>
          </>
        ) : undefined
      }
    >
      <form
        id="orquestrador-form"
        className="modal-form"
        onSubmit={(e) => {
          e.preventDefault();
          void save();
        }}
      >
        <p className="sub" style={{ color: "var(--muted)", marginBottom: "var(--s2)" }}>
          Este é o modelo base do agente. Toda igreja aprovada começa com ele;
          depois você pode ajustar por igreja na aba <strong>Agente</strong> da
          página dela.
        </p>

        {error ? (
          <div className="error-banner" role="alert">
            <span>{error}</span>
          </div>
        ) : null}
        {notice ? (
          <div
            className="error-banner"
            role="status"
            style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
          >
            <span>{notice}</span>
          </div>
        ) : null}

        {!loaded ? (
          <div style={{ padding: "var(--s5)", textAlign: "center", color: "var(--muted)" }}>
            <span className="spinner" aria-hidden="true" />
            <div className="sub" style={{ marginTop: "var(--s2)" }}>
              Carregando…
            </div>
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="orq-nome">Nome do agente</label>
              <input
                ref={nomeRef}
                id="orq-nome"
                value={nome}
                onChange={(e) => setNome(e.target.value)}
                placeholder="Ex.: Assistente da Igreja"
              />
            </div>
            <div className="field">
              <label htmlFor="orq-tom">Tom de voz</label>
              <input
                id="orq-tom"
                value={tom}
                onChange={(e) => setTom(e.target.value)}
                placeholder="Ex.: acolhedor e pastoral"
              />
            </div>
            <div className="field">
              <label htmlFor="orq-comp">Comportamento e instruções</label>
              <textarea
                id="orq-comp"
                rows={9}
                value={comportamento}
                onChange={(e) => setComportamento(e.target.value)}
                placeholder="Como o agente deve se comunicar, o que pode e não pode fazer…"
              />
            </div>
          </>
        )}
      </form>
    </DsDialog>
  );
}
