"use client";

/**
 * US-04 — feed de avisos que o discípulo pode ler (igreja/central + da sua
 * célula). Cor por origem: célula = azul, central/igreja = vermelho. O backend
 * já entrega do mais recente para o mais antigo. Empty: "Nenhum aviso publicado.".
 */
import { Icon } from "@/lib/icons";
import type { DiscipleNotice } from "@/lib/cell-notices-api";
import { formatPublishedAt } from "./format";

/** célula → azul; qualquer outra origem (igreja/central) → vermelho. */
function originClass(origem: string): string {
  return origem === "celula" ? "origem-celula" : "origem-central";
}

function originLabel(origem: string): string {
  return origem === "celula" ? "Célula" : "Central";
}

export function NoticesFeed({ notices }: { notices: DiscipleNotice[] }) {
  return (
    <section className="card" aria-label="Avisos">
      <div className="panel-title">
        <Icon name="bell" /> Avisos
        {notices.length ? <span className="count">· {notices.length}</span> : null}
      </div>

      {notices.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="bell" />
          <p>
            <strong>Nenhum aviso publicado.</strong>
          </p>
        </div>
      ) : (
        <div>
          {notices.map((n) => (
            <article className={`notice-item ${originClass(n.origem)}`} key={n.id}>
              <div className="notice-head">
                <span className="notice-title">{n.titulo}</span>
                <span className={`pill ${n.origem === "celula" ? "accent" : "danger"}`}>
                  {originLabel(n.origem)}
                </span>
              </div>
              <p className="notice-body">{n.conteudo}</p>
              <div className="notice-time">{formatPublishedAt(n.publicado_em)}</div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
