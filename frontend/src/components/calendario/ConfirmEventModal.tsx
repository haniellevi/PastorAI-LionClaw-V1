"use client";

/**
 * Modal de confirmação de evento (EVT-8b / spec §5.4). Abre ANTES de chamar
 * POST /events/{id}/confirm e coleta a intenção de comunicação:
 *   - público-alvo (multi-seleção, allowlist fechada);
 *   - antecedência do aviso (escolha única);
 *   - mensagem de confirmação (opcional, máx 2000).
 *
 * Tudo é opcional: confirmar sem tocar em nada envia um body mínimo e o backend
 * (EVT-8a) apenas PERSISTE a intenção — nada é enviado agora. O disparo real
 * (WhatsApp/e-mail aos públicos) é do EVT-9; o aviso no rodapé deixa isso claro
 * para não prometer envio que ainda não existe.
 *
 * Reusa o sistema de modais (.modal-overlay/.modal) e o Button; sem CSS novo.
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { formatLongDate, type ConfirmEventInput, type EventItem, type PublicoAlvo } from "@/lib/events-api";
import { Icon } from "@/lib/icons";

const MENSAGEM_MAX = 2000;

/** Públicos (§5.4) — slugs espelham o backend (EVT-8a). */
const PUBLICO_OPTIONS: { slug: PublicoAlvo; label: string }[] = [
  { slug: "toda_igreja", label: "Toda a igreja" },
  { slug: "lideres", label: "Líderes" },
  { slug: "discipulos", label: "Discípulos" },
  { slug: "visitantes", label: "Visitantes" },
  { slug: "casais", label: "Casais" },
  { slug: "jovens", label: "Jovens" },
  { slug: "criancas", label: "Crianças" },
];

/** Antecedência (§5.4) — escolha única; horas batem o contrato do backend (>=0). */
const ANTECEDENCIA_OPTIONS: { hours: number; label: string }[] = [
  { hours: 0, label: "No dia" },
  { hours: 72, label: "3 dias antes" },
  { hours: 168, label: "7 dias antes" },
];

export function ConfirmEventModal({
  event,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  event: EventItem;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onSubmit: (input: ConfirmEventInput) => void;
}) {
  const [publicos, setPublicos] = useState<PublicoAlvo[]>([]);
  const [antecedencia, setAntecedencia] = useState<number>(0);
  const [mensagem, setMensagem] = useState("");

  const togglePublico = (slug: PublicoAlvo) =>
    setPublicos((prev) =>
      prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug],
    );

  const submit = () => {
    const msg = mensagem.trim();
    // Só inclui os campos preenchidos — o backend trata ausência como null.
    // Antecedência é sempre enviada (escolha única com default "No dia").
    onSubmit({
      ...(publicos.length ? { publicoAlvo: publicos } : {}),
      antecedenciaHoras: antecedencia,
      ...(msg ? { mensagemConfirmacao: msg } : {}),
    });
  };

  const when = event.data
    ? `${formatLongDate(event.data)}${event.hora ? ` · ${event.hora}` : ""}`
    : `Recorrente${event.recorrencia === "semanal" ? " · semanal" : ""}${
        event.hora ? ` · ${event.hora}` : ""
      }`;

  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Confirmar evento ${event.titulo}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <strong>Confirmar evento</strong>
          <button type="button" className="btn btn-sm btn-ghost" onClick={onClose}>
            Fechar
          </button>
        </div>

        <form
          className="modal-form"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          {error ? (
            <div className="error-banner" role="alert">
              <Icon name="alert" />
              <span>{error}</span>
            </div>
          ) : null}

          <p className="sub" style={{ margin: 0 }}>
            <strong style={{ color: "var(--fg)" }}>{event.titulo}</strong> · {when}
          </p>

          <div className="field">
            <label>Público-alvo</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 14px" }}>
              {PUBLICO_OPTIONS.map((o) => (
                <label
                  key={o.slug}
                  style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", cursor: "pointer" }}
                >
                  <input
                    type="checkbox"
                    checked={publicos.includes(o.slug)}
                    onChange={() => togglePublico(o.slug)}
                    disabled={busy}
                  />
                  <span>{o.label}</span>
                </label>
              ))}
            </div>
            <p className="sub" style={{ margin: "var(--s1) 0 0" }}>
              Opcional. Sem seleção, nenhum público é segmentado.
            </p>
          </div>

          <div className="field">
            <label>Antecedência do aviso</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 14px" }}>
              {ANTECEDENCIA_OPTIONS.map((o) => (
                <label
                  key={o.hours}
                  style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "13px", cursor: "pointer" }}
                >
                  <input
                    type="radio"
                    name="antecedencia"
                    checked={antecedencia === o.hours}
                    onChange={() => setAntecedencia(o.hours)}
                    disabled={busy}
                  />
                  <span>{o.label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="field" style={{ marginBottom: 0 }}>
            <label htmlFor="confirm-msg">Mensagem de confirmação</label>
            <textarea
              id="confirm-msg"
              rows={3}
              maxLength={MENSAGEM_MAX}
              value={mensagem}
              onChange={(e) => setMensagem(e.target.value)}
              placeholder="Mensagem enviada aos públicos (opcional)"
            />
            <p className="sub" style={{ margin: "var(--s1) 0 0" }}>
              {mensagem.length}/{MENSAGEM_MAX}
            </p>
          </div>

          <p className="sub" style={{ margin: 0 }}>
            O envio automático ainda não está ativo — a confirmação registra estas
            preferências para uso futuro.
          </p>

          <div className="modal-foot">
            <button type="button" className="btn btn-sm" onClick={onClose} disabled={busy}>
              Cancelar
            </button>
            <Button type="submit" variant="primary" size="sm" loading={busy} loadingText="Confirmando…">
              <Icon name="check" /> Confirmar e agendar
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
