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
 * PR212-CORRECTIVE-2/6 (findings P2 do Codex): o chip do grid mensal precisa
 * de hora E título no DOM. A primeira rodada provou que evento sem horário
 * virava barra sem texto; a revisão de CORRECTIVE-6 derrubou o esconder-título
 * do evento COM hora — no mobile o CSS empilha hora + título truncado (chip em
 * duas linhas), sem marcador condicional. Aqui provamos o contrato do DOM:
 * ambos os fragmentos sempre presentes (visibilidade/empilhamento é CSS,
 * coberto pelo smoke em navegador real).
 */
describe("CalendarioScreen — chip do mês tem hora e título no DOM (P2)", () => {
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

  it("evento sem horário rende só o título (sem span de hora)", async () => {
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
    expect(titulo?.textContent).toBe("Retiro de carnaval");
    // Sem hora, não há span de horário.
    expect(container.querySelector(".cal-grid .cal-ev-time")).toBeNull();
  });

  it("evento com horário rende HORA e TÍTULO — nenhum dos dois some do DOM", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-com-hora", "Culto de celebração", "19:30")],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    expect(container.querySelector(".cal-grid .cal-ev-time")?.textContent).toBe("19:30");
    expect(container.querySelector(".cal-grid .cal-ev-title")?.textContent).toBe(
      "Culto de celebração",
    );
  });

  it("dois eventos no MESMO horário têm títulos visuais distintos no chip", async () => {
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

    const chips = [...container.querySelectorAll<HTMLElement>(".cal-grid .cal-ev")];
    expect(chips.length).toBe(2);
    const fragmentos = chips.map((c) => ({
      hora: c.querySelector(".cal-ev-time")?.textContent,
      titulo: c.querySelector(".cal-ev-title")?.textContent,
    }));
    expect(fragmentos).toEqual([
      { hora: "19:30", titulo: "Culto de celebração" },
      { hora: "19:30", titulo: "Ensaio do coral" },
    ]);
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
    // O aria-label é a frase única para o leitor de tela; visualmente o chip
    // empilha hora + título truncado (CORRECTIVE-6), então o rótulo garante o
    // título COMPLETO mesmo quando o visual corta.
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
