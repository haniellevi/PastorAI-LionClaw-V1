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

describe("CellFormModal: cadastro público S2b", () => {
  it.each([
    ["Qua", "Quarta-feira"],
    ["Qua-feira", "Quarta-feira"],
    ["quarta feira", "Quarta-feira"],
    ["SABADO", "Sábado"],
  ])("normaliza o dia único %s ao publicar", (dia, esperado) => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, ativo: true, bairro: "Centro", diaReuniao: dia, divulgarWhatsapp: false },
      publicDataEnabled: true, canPublish: true, onSubmit,
    });
    act(() => container.querySelector<HTMLInputElement>("#cf-divulgar")?.click());
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ diaReuniao: esperado, divulgarWhatsapp: true });
  });

  it("recusa dia composto ao publicar e anuncia o erro no campo", () => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, ativo: true, bairro: "Centro", diaReuniao: "Quarta e Sábado", divulgarWhatsapp: false },
      publicDataEnabled: true, canPublish: true, onSubmit,
    });
    act(() => container.querySelector<HTMLInputElement>("#cf-divulgar")?.click());
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(container.querySelector("#cf-dia")?.getAttribute("aria-invalid")).toBe("true");
    expect(container.querySelector("#cf-dia")?.getAttribute("aria-describedby")).toBe("cf-dia-error");
    expect(container.querySelector("#cf-dia-error")?.getAttribute("role")).toBe("alert");
    expect(container.querySelector("#cf-dia-error")?.textContent).toMatch(/dia fora do padrão/i);
  });

  it.each(["q-u-a", "q u a", "quarta_e_sabado", "quar-ta"])(
    "recusa dia fragmentado %s ao publicar",
    (dia) => {
      const onSubmit = vi.fn();
      render(true, {
        cell: { ...currentCell, ativo: true, bairro: "Centro", diaReuniao: dia, divulgarWhatsapp: false },
        publicDataEnabled: true, canPublish: true, onSubmit,
      });
      act(() => container.querySelector<HTMLInputElement>("#cf-divulgar")?.click());
      act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
      expect(onSubmit).not.toHaveBeenCalled();
      expect(container.querySelector("#cf-dia-error")?.textContent).toMatch(/dia fora do padrão/i);
    },
  );

  it("não bloqueia despublicação após alterar um dia legado inválido", () => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, ativo: true, bairro: "Centro", diaReuniao: "Quarta e Sábado", divulgarWhatsapp: true },
      publicDataEnabled: true, canPublish: true, onSubmit,
    });
    const dia = container.querySelector<HTMLSelectElement>("#cf-dia");
    act(() => {
      if (dia) {
        dia.value = "Quarta-feira";
        dia.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    act(() => {
      if (dia) {
        dia.value = "Quarta e Sábado";
        dia.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    act(() => container.querySelector<HTMLInputElement>("#cf-divulgar")?.click());
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ diaReuniao: "Quarta e Sábado", divulgarWhatsapp: false });
  });

  it("permite publicar sem dia definido", () => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, ativo: true, bairro: "Centro", diaReuniao: null, divulgarWhatsapp: false },
      publicDataEnabled: true, canPublish: true, onSubmit,
    });
    act(() => container.querySelector<HTMLInputElement>("#cf-divulgar")?.click());
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ diaReuniao: null, divulgarWhatsapp: true });
  });

  it("preserva dia legado inválido sem publicar e permite ao líder editar bairro", () => {
    const onSubmit = vi.fn();
    render(false, {
      cell: { ...currentCell, ativo: true, bairro: "Centro", diaReuniao: "Quarta e Sábado", divulgarWhatsapp: true },
      publicDataEnabled: true, canPublish: false, onSubmit,
    });
    const bairro = container.querySelector<HTMLInputElement>("#cf-bairro");
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(bairro, "Novo Centro");
      bairro?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ diaReuniao: "Quarta e Sábado", bairro: "Novo Centro" });
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty("divulgarWhatsapp");
  });

  it("edição só do nome preserva dados públicos ausentes da lista em cache", () => {
    const onSubmit = vi.fn();
    render(true, { cell: currentCell, publicDataEnabled: true, canPublish: true, onSubmit });
    const nome = container.querySelector<HTMLInputElement>('input[placeholder="Ex.: Boas Novas"]');
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(nome, "Célula Renovada");
      nome?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    const input = onSubmit.mock.calls[0]?.[0];
    expect(input?.nome).toBe("Célula Renovada");
    expect(input).not.toHaveProperty("bairro");
    expect(input).not.toHaveProperty("divulgarWhatsapp");
  });

  it("publicação desconhecida só muda após escolha explícita", () => {
    const onSubmit = vi.fn();
    render(true, { cell: currentCell, publicDataEnabled: true, canPublish: true, onSubmit });
    const publish = container.querySelector<HTMLSelectElement>("#cf-divulgar");
    expect(publish?.value).toBe("");
    expect(container.textContent).toContain("Dados ausentes desta lista serão mantidos");
    act(() => {
      if (publish) {
        publish.value = "false";
        publish.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toHaveProperty("divulgarWhatsapp", false);
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty("bairro");
  });

  it("explica no seletor por que célula inativa não pode ser divulgada", () => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, bairro: "Centro" },
      publicDataEnabled: true, canPublish: true, onSubmit,
    });
    const publish = container.querySelector<HTMLSelectElement>("#cf-divulgar");
    act(() => {
      if (publish) {
        publish.value = "true";
        publish.dispatchEvent(new Event("change", { bubbles: true }));
      }
    });
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(publish?.getAttribute("aria-invalid")).toBe("true");
    expect(publish?.getAttribute("aria-describedby")).toBe("cf-divulgar-error");
    expect(container.querySelector("#cf-divulgar-error")?.getAttribute("role")).toBe("alert");
    expect(container.querySelector("#cf-divulgar-error")?.textContent).toContain("Ative a célula");
  });

  it("sem capability oculta novos campos e preserva payload antigo", () => {
    const onSubmit = vi.fn();
    render(false, { cell: { ...currentCell, bairro: "Centro", divulgarWhatsapp: true }, onSubmit });
    expect(container.querySelector("#cf-bairro")).toBeNull();
    expect(container.querySelector("#cf-divulgar")).toBeNull();
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    const input = onSubmit.mock.calls[0]?.[0];
    expect(input).not.toHaveProperty("bairro");
    expect(input).not.toHaveProperty("divulgarWhatsapp");
  });

  it("líder edita bairro, mas não envia decisão de publicação", () => {
    const onSubmit = vi.fn();
    render(false, { cell: currentCell, publicDataEnabled: true, canPublish: false, onSubmit });
    const bairro = container.querySelector<HTMLInputElement>("#cf-bairro");
    expect(bairro).not.toBeNull();
    expect(container.querySelector("#cf-divulgar")).toBeNull();
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(bairro, "Centro");
      bairro?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toHaveProperty("bairro", "Centro");
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty("divulgarWhatsapp");
  });

  it("pastor/admin controla divulgação, default off e exige bairro para publicar", () => {
    const onSubmit = vi.fn();
    render(true, { publicDataEnabled: true, canPublish: true, onSubmit });
    const publish = container.querySelector<HTMLInputElement>("#cf-divulgar");
    expect(publish?.checked).toBe(false);
    act(() => publish?.click());
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(container.textContent).toContain("Informe o bairro antes de divulgar");
  });

  it("pastor/admin envia publicação apenas para célula ativa com bairro", () => {
    const onSubmit = vi.fn();
    render(true, {
      cell: { ...currentCell, ativo: true, bairro: "Centro", divulgarWhatsapp: false },
      publicDataEnabled: true, canPublish: true, onSubmit,
    });
    act(() => container.querySelector<HTMLInputElement>("#cf-divulgar")?.click());
    act(() => container.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({ divulgarWhatsapp: true, ativo: true });
    expect(onSubmit.mock.calls[0]?.[0]).not.toHaveProperty("bairro");
  });
});
