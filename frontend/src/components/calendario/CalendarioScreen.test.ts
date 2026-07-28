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

/**
 * PR212-CORRECTIVE-2 (finding P2 do Codex, revisão do commit cbecb490b9):
 * até 640px o grid mensal esconde o título do chip e conta com a hora como
 * rótulo — mas `hora` é nullable. Sem marcação, evento sem horário virava uma
 * barra colorida sem texto nenhum. O marcador `cal-ev-title--untimed` é o que
 * o CSS usa para preservar o título só nesse caso; aqui provamos a marcação.
 */
describe("CalendarioScreen — chip de evento sem horário (P2)", () => {
  const iso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
  };

  function evento(id: string, titulo: string, hora: string | null) {
    return {
      id,
      titulo,
      data: iso(),
      hora,
      descricao: null,
      googleEventId: null,
      sincronizado: false,
    };
  }

  it("evento com hora=null recebe o marcador de evento sem horário", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-sem-hora", "Retiro de carnaval", null)],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const titulo = container.querySelector<HTMLElement>(".cal-grid .cal-ev-title");
    expect(titulo).not.toBeNull();
    expect(titulo?.classList.contains("cal-ev-title--untimed")).toBe(true);
    // O título continua no DOM (não é só o atributo title do chip).
    expect(titulo?.textContent).toBe("Retiro de carnaval");
    // Sem hora, não há chip de horário para servir de rótulo.
    expect(container.querySelector(".cal-grid .cal-ev-time")).toBeNull();
  });

  it("evento com horário mantém o comportamento compacto (hora, sem marcador)", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-com-hora", "Culto de celebração", "19:30")],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const titulo = container.querySelector<HTMLElement>(".cal-grid .cal-ev-title");
    expect(titulo).not.toBeNull();
    expect(titulo?.classList.contains("cal-ev-title--untimed")).toBe(false);
    expect(container.querySelector(".cal-grid .cal-ev-time")?.textContent).toBe("19:30");
  });

  it("o marcador acompanha cada evento (misto sem hora + com hora)", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [
        evento("ev-a", "Retiro de carnaval", null),
        evento("ev-b", "Culto de celebração", "19:30"),
      ],
      page: 1,
      pageSize: 200,
      total: 2,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const titulos = [...container.querySelectorAll<HTMLElement>(".cal-grid .cal-ev-title")];
    expect(titulos.length).toBe(2);
    const marcados = titulos
      .filter((t) => t.classList.contains("cal-ev-title--untimed"))
      .map((t) => t.textContent);
    expect(marcados).toEqual(["Retiro de carnaval"]);
  });
});

/**
 * PR212-CORRECTIVE-3 (2º finding P2 do Codex, revisão do commit 30d0bb909e):
 * até 640px o chip do grid mensal com horário mostra só "19:30", e o chip é um
 * `role="button"` — o nome acessível virava o horário, sem identificar o
 * evento. O atributo `title` não cobre isso (só vale como fallback de conteúdo
 * vazio, e é hover de mouse). O `aria-label` do chip do MÊS é a prova aqui;
 * Semana e listas seguem sem rótulo próprio, pois já expõem o título.
 */
describe("CalendarioScreen — nome acessível do chip do mês (P2)", () => {
  const iso = () => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
  };

  function evento(id: string, titulo: string, hora: string | null) {
    return {
      id,
      titulo,
      data: iso(),
      hora,
      descricao: null,
      googleEventId: null,
      sincronizado: false,
    };
  }

  it("chip com horário tem nome acessível com título E horário", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-1", "Culto de celebração", "19:30")],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const chip = container.querySelector<HTMLElement>(".cal-grid .cal-ev");
    expect(chip?.getAttribute("aria-label")).toBe("Culto de celebração, às 19:30");
    // O visual segue compacto: o texto do chip continua sendo só o horário
    // (o título existe no DOM, mas o CSS o esconde no mês estreito).
    expect(chip?.querySelector(".cal-ev-time")?.textContent).toBe("19:30");
  });

  it("eventos no MESMO horário com títulos diferentes têm nomes acessíveis distintos", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [
        evento("ev-a", "Culto de celebração", "19:30"),
        evento("ev-b", "Ensaio do coral", "19:30"),
      ],
      page: 1,
      pageSize: 200,
      total: 2,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const nomes = [...container.querySelectorAll<HTMLElement>(".cal-grid .cal-ev")].map((c) =>
      c.getAttribute("aria-label"),
    );
    expect(nomes).toEqual(["Culto de celebração, às 19:30", "Ensaio do coral, às 19:30"]);
    expect(new Set(nomes).size).toBe(2);
  });

  it("chip sem horário tem nome acessível só com o título", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-sem-hora", "Retiro de carnaval", null)],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const chip = container.querySelector<HTMLElement>(".cal-grid .cal-ev");
    expect(chip?.getAttribute("aria-label")).toBe("Retiro de carnaval");
  });

  it("chips da visão Semana NÃO recebem aria-label (o título já está no conteúdo)", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-1", "Culto de celebração", "19:30")],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const abaSemana = [...container.querySelectorAll<HTMLElement>('[role="tab"]')].find(
      (t) => t.textContent?.trim() === "Semana",
    );
    act(() => {
      abaSemana!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const chip = container.querySelector<HTMLElement>(".agenda-week .cal-ev");
    expect(chip).not.toBeNull();
    expect(chip?.getAttribute("aria-label")).toBeNull();
    expect(chip?.textContent).toContain("Culto de celebração");
  });
});
