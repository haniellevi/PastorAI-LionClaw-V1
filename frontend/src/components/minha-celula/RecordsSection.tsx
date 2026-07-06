"use client";

/**
 * US-09 — registros da reunião (líder): decisões, orações e observações. Cada
 * registro tem um tipo (decisao/oracao/observacao), um conteúdo e, opcionalmente,
 * a pessoa relacionada (membro da célula). Lista os registros já lançados e
 * permite adicionar novos. Bloqueado após o relatório enviado (E10/E11).
 */
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { StatusPill, type PillTone } from "@/components/dashboard/StatusPill";
import { Icon } from "@/lib/icons";
import { ApiError } from "@/lib/dashboard-api";
import { addRecord } from "@/lib/cell-meetings-api";
import type { ReportRecord } from "@/lib/cell-meetings-api";
import type { CellMember } from "@/lib/cells-api";
import type { FlashToast } from "./types";

type RecordType = "decisao" | "oracao" | "observacao";

const TYPE_OPTIONS: { value: RecordType; label: string }[] = [
  { value: "decisao", label: "Decisão" },
  { value: "oracao", label: "Oração" },
  { value: "observacao", label: "Observação" },
];

function typeLabel(tipo: string): string {
  return TYPE_OPTIONS.find((t) => t.value === tipo)?.label ?? tipo;
}

function typeTone(tipo: string): PillTone {
  if (tipo === "decisao") return "ok";
  if (tipo === "oracao") return "accent";
  return "muted";
}

export function RecordsSection({
  token,
  reuniaoId,
  members,
  records,
  locked,
  onToast,
  onChanged,
}: {
  token: string;
  reuniaoId: string;
  members: CellMember[];
  records: ReportRecord[];
  locked: boolean;
  onToast: FlashToast;
  onChanged: () => void;
}) {
  const [tipo, setTipo] = useState<RecordType>("decisao");
  const [conteudo, setConteudo] = useState("");
  const [pessoaId, setPessoaId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function memberName(id: string | null): string | null {
    if (!id) return null;
    return members.find((m) => m.pessoa_id === id)?.nome ?? null;
  }

  async function add() {
    const trimmed = conteudo.trim();
    if (!trimmed) {
      setError("Descreva o registro.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addRecord(token, reuniaoId, {
        tipo,
        conteudo: trimmed,
        pessoa_id: pessoaId || null,
      });
      onToast({ kind: "ok", text: "Registro adicionado." });
      setConteudo("");
      setPessoaId("");
      onChanged();
    } catch (err) {
      const text =
        err instanceof ApiError ? err.message : "Não foi possível adicionar o registro.";
      setError(text);
      onToast({ kind: "err", text });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" aria-label="Registros">
      <div className="panel-title">
        <Icon name="document" /> Registros
        {records.length ? <span className="count">· {records.length}</span> : null}
      </div>

      {error ? (
        <div className="error-banner" role="alert">
          <Icon name="alert" />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="section-body">
        {records.length === 0 ? (
          <p className="muted-note">Nenhum registro lançado ainda.</p>
        ) : (
          <div>
            {records.map((r) => {
              const who = memberName(r.pessoa_id);
              return (
                <div className="list-row" key={r.id}>
                  <div className="grow" style={{ minWidth: 0 }}>
                    <div className="nm">{r.conteudo}</div>
                    {who ? <div className="sub">{who}</div> : null}
                  </div>
                  <StatusPill tone={typeTone(r.tipo)}>{typeLabel(r.tipo)}</StatusPill>
                </div>
              );
            })}
          </div>
        )}

        {!locked ? (
          <form
            className="inline-form"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <div className="subhead">Adicionar registro</div>
            <div className="field">
              <label htmlFor={`rec-tipo-${reuniaoId}`}>Tipo</label>
              <select
                id={`rec-tipo-${reuniaoId}`}
                value={tipo}
                onChange={(e) => setTipo(e.target.value as RecordType)}
                disabled={busy}
              >
                {TYPE_OPTIONS.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor={`rec-conteudo-${reuniaoId}`}>Descrição</label>
              <textarea
                id={`rec-conteudo-${reuniaoId}`}
                rows={2}
                value={conteudo}
                onChange={(e) => setConteudo(e.target.value)}
                disabled={busy}
                maxLength={1000}
                placeholder="Ex.: Maria entregou a vida a Jesus."
              />
            </div>
            {members.length ? (
              <div className="field">
                <label htmlFor={`rec-pessoa-${reuniaoId}`}>Pessoa (opcional)</label>
                <select
                  id={`rec-pessoa-${reuniaoId}`}
                  value={pessoaId}
                  onChange={(e) => setPessoaId(e.target.value)}
                  disabled={busy}
                >
                  <option value="">Ninguém em específico</option>
                  {members.map((m) => (
                    <option key={m.pessoa_id} value={m.pessoa_id}>
                      {m.nome}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="section-actions">
              <Button
                type="submit"
                variant="primary"
                size="sm"
                loading={busy}
                loadingText="Adicionando…"
                disabled={!conteudo.trim()}
              >
                <Icon name="plus" />
                <span>Adicionar registro</span>
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}
