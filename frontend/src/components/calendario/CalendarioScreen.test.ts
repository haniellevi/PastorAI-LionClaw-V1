// @vitest-environment jsdom
/**
 * Wave Visual W3 — acionamento por teclado da célula/dia do calendário
 * (achado B2 da descoberta): antes só o clique do mouse abria "Novo evento"
 * com a data pré-preenchida; agora Enter/Espaço fazem o mesmo, no mesmo
 * padrão já usado pelos chips de evento (`eventActivation`).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authState = vi.hoisted(() => ({
  roles: ["pastor"] as string[],
  expireSession: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({
    token: "tok-1",
    user: { roles: authState.roles },
    expireSession: authState.expireSession,
  }),
}));

const apiMock = vi.hoisted(() => ({
  fetchEvents: vi.fn(),
}));

vi.mock("@/lib/events-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/events-api")>();
  return {
    ...actual,
    fetchEvents: apiMock.fetchEvents,
  };
});

const { CalendarioScreen } = await import("./CalendarioScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  apiMock.fetchEvents.mockReset();
  apiMock.fetchEvents.mockResolvedValue({ items: [], page: 1, pageSize: 200, total: 0 });
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
  // Resiliente a asserção que falhe no meio do teste: sempre restaura o papel
  // padrão, mesmo que o "sem canManage" nunca chegue na linha de reset.
  authState.roles = ["pastor"];
});

describe("CalendarioScreen — teclado na célula do dia (B2)", () => {
  it("Enter numa célula do grid mensal abre 'Novo evento' com a data do dia", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const cell = container.querySelector<HTMLElement>('.cal-cell[tabindex="0"]');
    expect(cell).not.toBeNull();
    expect(cell?.getAttribute("tabindex")).toBe("0");

    act(() => {
      cell!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });

    expect(container.querySelector(".ds-dialog-title")?.textContent).toBe("Novo evento");
  });

  it("Espaço numa célula do grid mensal também abre a criação", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const cell = container.querySelector<HTMLElement>('.cal-cell[tabindex="0"]');
    act(() => {
      cell!.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    });

    expect(container.querySelector(".ds-dialog-title")?.textContent).toBe("Novo evento");
  });

  it("sem canManage, nenhuma célula é focável", async () => {
    authState.roles = ["lider_g12"];
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    expect(container.querySelector('.cal-cell[tabindex="0"]')).toBeNull();
  });

  it("célula do dia não tem role=button (evita interactive-in-interactive com os chips de evento)", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const cell = container.querySelector<HTMLElement>('.cal-cell[tabindex="0"]');
    expect(cell).not.toBeNull();
    expect(cell?.getAttribute("role")).toBeNull();
  });

  it("célula do dia tem nome acessível explicando a ação de Enter/Espaço", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const cell = container.querySelector<HTMLElement>('.cal-cell[tabindex="0"]');
    const label = cell?.getAttribute("aria-label");
    expect(label).toMatch(/^Novo evento em /);
  });

  it("ativar um chip de evento não dispara também a criação de novo evento da célula-pai", async () => {
    const today = new Date();
    const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(
      today.getDate(),
    ).padStart(2, "0")}`;
    apiMock.fetchEvents.mockResolvedValue({
      items: [
        {
          id: "ev-1",
          titulo: "Reunião de líderes",
          data: iso,
          hora: null,
          descricao: null,
          googleEventId: null,
          sincronizado: true,
        },
      ],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const chip = container.querySelector<HTMLElement>(".cal-ev");
    expect(chip).not.toBeNull();

    act(() => {
      chip!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });

    // Abriu o DETALHE do evento (eventActivation), não a criação de novo
    // evento da célula-pai (dayCellActivation) — a propagação do keydown foi
    // interrompida no chip antes de alcançar o onKeyDown da célula.
    const dialogs = container.querySelectorAll('[role="dialog"]');
    expect(dialogs.length).toBe(1);
    expect(container.querySelector(".ds-dialog-title")?.textContent).toBe("Reunião de líderes");
  });
});
