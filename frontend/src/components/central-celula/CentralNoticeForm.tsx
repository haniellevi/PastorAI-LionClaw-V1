"use client";

/**
 * US-20 — CentralNoticeForm. A Central publica um aviso para UMA célula específica
 * OU para a igreja inteira (vermelho). Escopo `igreja` (celula_id nulo) ou `celula`
 * (com celula_id). Valida título/conteúdo e, no modo célula, exige a célula alvo.
 * Toast "Aviso publicado." (E17). Sem edição no MVP: corrigir = inativar e criar novo.
 */
import { useState } from "react";

import { DsButton } from "@/components/ds/Button";
import { DsField } from "@/components/ds/Field";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { createNotice, type Notice } from "@/lib/cell-notices-api";
import type { CellSummary } from "@/lib/cells-api";
import type { FlashToast } from "./types";

type Target = "igreja" | "celula";

export function CentralNoticeForm({
  token,
  cells,
  onToast,
  onPublished,
}: {
  token: string;
  cells: CellSummary[];
  onToast: FlashToast;
  onPublished: (notice: Notice) => void;
}) {
  const [target, setTarget] = useState<Target>("igreja");
  const [cellId, setCellId] = useState<string>("");
  const [titulo, setTitulo] = useState("");
  const [conteudo, setConteudo] = useState("");
  const [errors, setErrors] = useState<{ titulo?: string; conteudo?: string; cell?: string }>({});
  const [busy, setBusy] = useState(false);

  function validate(): boolean {
    const next: typeof errors = {};
    if (!titulo.trim()) next.titulo = "Informe um título.";
    if (!conteudo.trim()) next.conteudo = "Escreva o conteúdo do aviso.";
    if (target === "celula" && !cellId) next.cell = "Escolha a célula de destino.";
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit() {
    if (busy) return;
    if (!validate()) return;
    setBusy(true);
    try {
      const notice = await createNotice(token, {
        titulo: titulo.trim(),
        conteudo: conteudo.trim(),
        escopo: target,
        celula_id: target === "celula" ? cellId : null,
      });
      onToast({ kind: "ok", text: "Aviso publicado." });
      setTitulo("");
      setConteudo("");
      setCellId("");
      setTarget("igreja");
      setErrors({});
      onPublished(notice);
    } catch (err) {
      onToast({
        kind: "err",
        text: err instanceof ApiError ? err.message : "Não foi possível publicar o aviso.",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-label="Publicar aviso">
      <div className="panel-title">
        <Icon name="broadcast" /> Publicar aviso
      </div>

      <div className="section-body" style={{ display: "grid", gap: "var(--s3)" }}>
        <DsField
          label="Destino"
          as="select"
          value={target}
          onChange={(e) => {
            setTarget(e.target.value as Target);
            setErrors((p) => ({ ...p, cell: undefined }));
          }}
        >
          <option value="igreja">Igreja inteira</option>
          <option value="celula">Célula específica</option>
        </DsField>

        {target === "celula" ? (
          <DsField
            label="Célula"
            as="select"
            value={cellId}
            onChange={(e) => {
              setCellId(e.target.value);
              if (errors.cell) setErrors((p) => ({ ...p, cell: undefined }));
            }}
            error={errors.cell}
          >
            <option value="">Selecione…</option>
            {cells.map((c) => (
              <option key={c.id} value={c.id}>
                {c.nome}
              </option>
            ))}
          </DsField>
        ) : null}

        <DsField
          label="Título"
          value={titulo}
          maxLength={120}
          onChange={(e) => {
            setTitulo(e.target.value);
            if (errors.titulo) setErrors((p) => ({ ...p, titulo: undefined }));
          }}
          error={errors.titulo}
          placeholder="Ex.: Reunião de líderes no sábado"
        />

        <DsField
          label="Conteúdo"
          as="textarea"
          value={conteudo}
          rows={3}
          maxLength={2000}
          onChange={(e) => {
            setConteudo(e.target.value);
            if (errors.conteudo) setErrors((p) => ({ ...p, conteudo: undefined }));
          }}
          error={errors.conteudo}
          placeholder="Escreva a mensagem para os destinatários."
        />

        <div>
          <DsButton variant="primary" onClick={() => void submit()} loading={busy}>
            <Icon name="send" />
            <span>Publicar aviso</span>
          </DsButton>
        </div>
      </div>
    </section>
  );
}
