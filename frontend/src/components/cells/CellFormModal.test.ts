// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CellSummary } from "@/lib/cells-api";

import { CellFormModal } from "./CellFormModal";
import type { CellLeaderOption } from "./cell-leadership";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

const leaders: CellLeaderOption[] = [
  {
    id: "p-ready",
    nome: "Ana Ativa",
    selectable: true,
    current: false,
    blocksSave: false,
    reason: null,
  },
  {
    id: "p-invited",
    nome: "Bia Convidada",
    selectable: false,
    current: false,
    blocksSave: false,
    reason: "Acesso ainda não ativado",
  },
];

const currentCell: CellSummary = {
  id: "cell-1",
  nome: "Célula Vida",
  liderId: "p-current",
  diaReuniao: "Quarta-feira",
  horario: "20:00",
  coberturaEspiritual: "Pr. João",
  ativo: false,
};

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

function render(
  canManageLeadership: boolean,
  props: Partial<Parameters<typeof CellFormModal>[0]> = {},
) {
  act(() => {
    root.render(
      h(CellFormModal, {
        cell: null,
        leaders,
        coverageOptions: [],
        canManageLeadership,
        busy: false,
        error: null,
        onClose: vi.fn(),
        onSubmit: vi.fn(),
        ...props,
      }),
    );
  });
}

describe("CellFormModal: liderança e ativação", () => {
  it("fora da Central deixa líder e status somente leitura com orientação", () => {
    render(false);

    expect((container.querySelector("#cf-lider") as HTMLSelectElement).disabled).toBe(true);
    expect((container.querySelector('input[type="checkbox"]') as HTMLInputElement).disabled).toBe(true);
    expect(container.textContent).toContain("Liderança é gerida exclusivamente na Central de Células");
    expect(container.textContent).toContain("Ativação e desativação são geridas exclusivamente na Central de Células");
  });

  it("na Central habilita os controles e mostra por que um candidato está bloqueado", () => {
    render(true);

    const select = container.querySelector("#cf-lider") as HTMLSelectElement;
    const blocked = select.querySelector('option[value="p-invited"]') as HTMLOptionElement;
    expect(select.disabled).toBe(false);
    expect(blocked.disabled).toBe(true);
    expect(container.textContent).toContain("Bia Convidada: Acesso ainda não ativado");
    expect((container.querySelector('input[type="checkbox"]') as HTMLInputElement).disabled).toBe(false);
  });

  it("salvar fora da Central preserva líder e status atuais", () => {
    const onSubmit = vi.fn();
    render(false, {
      cell: currentCell,
      leaders: [
        {
          id: "p-current",
          nome: "Líder Atual",
          selectable: true,
          current: true,
          blocksSave: false,
          reason: "Líder atual",
        },
      ],
      onSubmit,
    });

    const form = container.querySelector("form") as HTMLFormElement;
    act(() => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ liderId: "p-current", ativo: false }),
    );
  });

  it("bloqueia salvar enquanto o líder atual estiver irregular", () => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, ativo: true },
      leaders: [
        {
          id: "p-current",
          nome: "Líder Atual",
          selectable: false,
          current: true,
          blocksSave: true,
          reason:
            "Pendência bloqueante no acesso do líder atual: acesso revogado. Regularize o acesso ou escolha outro líder antes de salvar",
        },
      ],
      onSubmit,
    });

    const save = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent === "Salvar alterações",
    ) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    expect(save.getAttribute("aria-describedby")).toBe("cf-leader-status");
    expect(container.querySelector("#cf-leader-status")?.getAttribute("role")).toBe(
      "alert",
    );
    expect(container.textContent).toContain(
      "Regularize o acesso ou escolha outro líder",
    );

    const form = container.querySelector("form") as HTMLFormElement;
    act(() =>
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
    );
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
