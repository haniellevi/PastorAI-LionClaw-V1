// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot } from "react-dom/client";
import { expect, it } from "vitest";
import { LockedScreen } from "./LockedScreen";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

it.each(["universidade-vida", "capacitacao"] as const)("%s apresenta indisponibilidade sem progresso ou certificação simulados", (variant) => {
  const container = document.createElement("div");
  const root = createRoot(container);
  act(() => root.render(h(LockedScreen, { variant })));
  expect(container.querySelector('[role="status"]')?.textContent).toContain("Módulo indisponível");
  expect(container.querySelector("a")?.getAttribute("href")).toBe("#dashboard");
  expect(container.querySelector("button, form, .done, .cd-seal")).toBeNull();
  expect(container.textContent).not.toMatch(/Apto a Liderar|Certificado completo|onda futura/);
  act(() => root.unmount());
});
