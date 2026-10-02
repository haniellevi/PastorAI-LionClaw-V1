// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { DataTable } from "./DataTable";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;
beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("ações internas funcionam uma vez sem abrir a linha nem capturar sua tecla", () => {
  const onOpen = vi.fn();
  const onAction = vi.fn();
  const row = { id: "pessoa-sintetica" };
  act(() => root.render(h(DataTable<typeof row>, {
    rows: [row], rowKey: (item: typeof row) => item.id,
    empty: { title: "Sem pessoas" }, onRowClick: onOpen,
    columns: [
      { header: "Pessoa", cell: () => "Pessoa sintética" },
      { header: "Ação", cell: () => h("button", { onClick: onAction }, "Editar pessoa") },
    ],
  })));
  const button = container.querySelector("button")!;
  act(() => button.click());
  expect(onAction).toHaveBeenCalledTimes(1);
  act(() => button.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })));
  expect(onOpen).not.toHaveBeenCalled();
  const tableRow = container.querySelector("tbody tr")!;
  act(() => tableRow.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true })));
  expect(onOpen).toHaveBeenCalledExactlyOnceWith(row);
});
