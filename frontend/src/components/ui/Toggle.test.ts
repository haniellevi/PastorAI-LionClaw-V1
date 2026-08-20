// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toggle } from "./Toggle";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function renderToggle(props: Partial<Parameters<typeof Toggle>[0]> = {}) {
  act(() => {
    root.render(
      h(Toggle, {
        checked: false,
        onChange: vi.fn(),
        label: "Presença de Ana",
        ...props,
      }),
    );
  });
}

describe("Toggle", () => {
  it("associa o nome acessível ao checkbox pelo label clicável", () => {
    renderToggle();

    const input = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    const label = input.closest("label");

    expect(label).not.toBeNull();
    expect(label?.classList.contains("switch")).toBe(true);
    expect(input.labels?.[0]).toBe(label);
    expect(label?.textContent).toContain("Presença de Ana");
    expect(label?.querySelector(".sr-only")?.textContent).toBe("Presença de Ana");
    expect(label?.querySelector(".sw-track")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("mantém interação e estado desabilitado no input nativo", () => {
    const onChange = vi.fn();
    renderToggle({ onChange });

    const label = container.querySelector("label.switch") as HTMLLabelElement;
    act(() => label.click());
    expect(onChange).toHaveBeenCalledWith(true);

    renderToggle({ disabled: true, onChange });
    const disabledInput = container.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(disabledInput.disabled).toBe(true);
    act(() => label.click());
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("preserva o trilho visual e amplia o alvo para 44 por 44 pixels", () => {
    const css = readFileSync(join(__dirname, "../../app/globals.css"), "utf8");
    const targetRule = css.match(/\.switch\s*\{([\s\S]*?)\}/)?.[1] ?? "";
    const inputRule = css.match(/\.switch input\s*\{([\s\S]*?)\}/)?.[1] ?? "";
    const trackRule = css.match(/\.switch \.sw-track\s*\{([\s\S]*?)\}/)?.[1] ?? "";

    expect(targetRule).toMatch(/width:\s*44px/);
    expect(targetRule).toMatch(/height:\s*44px/);
    expect(inputRule).toMatch(/width:\s*100%/);
    expect(inputRule).toMatch(/height:\s*100%/);
    expect(trackRule).toMatch(/width:\s*40px/);
    expect(trackRule).toMatch(/height:\s*22px/);
  });
});
