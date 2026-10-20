// @vitest-environment jsdom

import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it } from "vitest";

import { CentralTabs } from "./CentralTabs";
import type { CentralTab } from "./types";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement;
let root: Root;

function Fixture() {
  const [active, setActive] = useState<CentralTab>("dashboard");
  return <CentralTabs active={active} onChange={setActive}><p>Conteúdo de {active}</p></CentralTabs>;
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  act(() => root.render(<Fixture />));
});
afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

it("oferece um painel focalizável e nomeado pela aba selecionada", () => {
  const panel = container.querySelector<HTMLElement>('[role="tabpanel"]')!;
  const selected = container.querySelector('[aria-selected="true"]')!;
  expect(panel.tabIndex).toBe(0);
  expect(panel.getAttribute("aria-labelledby")).toBe(selected.id);
  expect(selected.getAttribute("aria-controls")).toBe(panel.id);
  panel.focus();
  expect(document.activeElement).toBe(panel);
});

it("troca a aba por teclado mantendo foco e vínculo com o conteúdo atual", () => {
  const first = container.querySelector<HTMLElement>('[role="tab"]')!;
  first.focus();
  act(() => first.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
  const selected = container.querySelector<HTMLElement>('[aria-selected="true"]')!;
  const panel = container.querySelector<HTMLElement>('[role="tabpanel"]')!;
  expect(selected.textContent).toBe("Materiais");
  expect(document.activeElement).toBe(selected);
  expect(panel.textContent).toContain("Conteúdo de materials");
  expect(panel.tabIndex).toBe(0);
  expect(panel.getAttribute("aria-labelledby")).toBe(selected.id);
  expect(selected.getAttribute("aria-controls")).toBe(panel.id);
  expect(container.querySelectorAll('[role="tab"][tabindex="0"]')).toHaveLength(1);
});
