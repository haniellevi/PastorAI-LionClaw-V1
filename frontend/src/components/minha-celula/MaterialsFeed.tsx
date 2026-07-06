"use client";

/**
 * US-21 / E14 — materiais de apoio da igreja. Discípulo tem SOMENTE leitura:
 * lista título, descrição e um link externo (abre em nova aba). Sem ações de
 * escrita. Empty: "Nenhum material publicado.".
 */
import { Icon } from "@/lib/icons";
import type { Material } from "@/lib/cell-materials-api";

export function MaterialsFeed({ materials }: { materials: Material[] }) {
  return (
    <section className="card" aria-label="Materiais">
      <div className="panel-title">
        <Icon name="document" /> Materiais
        {materials.length ? <span className="count">· {materials.length}</span> : null}
      </div>

      {materials.length === 0 ? (
        <div className="empty-state" style={{ padding: "var(--s6)" }}>
          <Icon name="document" />
          <p>
            <strong>Nenhum material publicado.</strong>
          </p>
        </div>
      ) : (
        <div>
          {materials.map((m) => (
            <div className="material-item" key={m.id}>
              <span className="avatar" aria-hidden="true">
                <Icon name="document" size={16} />
              </span>
              <div className="grow">
                <div className="nm">{m.titulo}</div>
                {m.descricao ? <div className="sub">{m.descricao}</div> : null}
              </div>
              {m.url ? (
                <a
                  className="btn btn-sm"
                  href={m.url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  <Icon name="link" size={16} />
                  <span>Abrir</span>
                </a>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
