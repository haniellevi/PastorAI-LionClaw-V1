/**
 * data-table (componente do contrato 4.3).
 * Tabela de dados semântica com estados empty/populated, portada do artifact
 * travado (.card > table + .empty-state). Genérica e tipada por coluna.
 */
import type { ReactNode } from "react";

import { Icon, type IconKey } from "@/lib/icons";

export interface Column<T> {
  /** Cabeçalho da coluna (vazio para coluna de ações). */
  header: ReactNode;
  /** Render da célula a partir da linha. */
  cell: (row: T) => ReactNode;
  /** Alinha conteúdo numérico à direita usando .num. */
  numeric?: boolean;
  /** Largura sugerida (ex.: "1px" para coluna de ação encolher). */
  width?: string;
  /** Rótulo do card mobile (data-label). Use quando o header não for string. */
  label?: string;
}

export interface DataTableProps<T> {
  columns: Array<Column<T>>;
  rows: T[];
  rowKey: (row: T) => string;
  /** Estado vazio (populated quando há linhas). */
  empty: { icon?: IconKey; title: string; hint?: string };
  /** Abre o detalhe da linha (linha vira clicável/acessível). */
  onRowClick?: (row: T) => void;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty,
  onRowClick,
}: DataTableProps<T>) {
  if (rows.length === 0) {
    return (
      <div className="empty-state" style={{ padding: "var(--s6)" }}>
        <Icon name={empty.icon ?? "user"} />
        <p>
          <strong>{empty.title}</strong>
          {empty.hint ? <> {empty.hint}</> : null}
        </p>
      </div>
    );
  }

  return (
    <table className="data-table">
      <thead>
        <tr>
          {columns.map((col, i) => (
            <th
              key={i}
              style={col.width ? { width: col.width } : undefined}
              className={col.numeric ? "num" : undefined}
            >
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const clickable = Boolean(onRowClick);
          return (
            <tr
              key={rowKey(row)}
              className={clickable ? "row-link" : undefined}
              onClick={clickable ? () => onRowClick?.(row) : undefined}
              tabIndex={clickable ? 0 : undefined}
              onKeyDown={
                clickable
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        onRowClick?.(row);
                      }
                    }
                  : undefined
              }
            >
              {columns.map((col, i) => (
                <td
                  key={i}
                  className={col.numeric ? "num" : undefined}
                  data-label={
                    col.label ?? (typeof col.header === "string" ? col.header : undefined)
                  }
                >
                  {col.cell(row)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
