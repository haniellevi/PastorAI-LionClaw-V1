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
// O mock acima espalha o módulo real — formatLongDate é o original.
const { formatLongDate } = await import("@/lib/events-api");

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

/**
 * VIS-2-MOBILE-CALENDAR-ARCH-1: em ≤640px a grade mensal vira visão geral +
 * seletor de dia (a variante .cal-m; a .cal desktop some via CSS) e os
 * detalhes completos ficam na lista "Eventos em <dia>" abaixo. Aqui provamos o
 * CONTRATO do DOM/comportamento da variante mobile — qual das duas grades está
 * visível é decisão do CSS, coberta pelo smoke de geometria em navegador real:
 *  - cada dia é um <button> real com aria-pressed e contagem acessível;
 *  - tocar no dia seleciona (NÃO abre criação — decisão de produto);
 *  - a lista traz hora + título completos e abre o detalhe existente;
 *  - admin cria pelo botão explícito "Novo evento neste dia";
 *  - a grade mobile não rende chips hora+título (isso é só do desktop).
 */
describe("CalendarioScreen — grade mensal mobile: seletor de dia + lista (VIS-2)", () => {
  const isoOf = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
      d.getDate(),
    ).padStart(2, "0")}`;
  const todayIso = () => isoOf(new Date());
  /** Um dia do mês corrente diferente de hoje (1º, ou 2 se hoje for dia 1º). */
  const otherDayIso = () => {
    const d = new Date();
    return isoOf(new Date(d.getFullYear(), d.getMonth(), d.getDate() === 1 ? 2 : 1));
  };

  function evento(id: string, titulo: string, hora: string | null, data = todayIso()) {
    return {
      id,
      titulo,
      data,
      hora,
      descricao: null,
      googleEventId: null,
      sincronizado: false,
    };
  }

  it("cada dia é um BOTÃO real; hoje começa selecionado via aria-pressed", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const botoes = [...container.querySelectorAll<HTMLElement>(".cal-m-grid button.cal-m-cell")];
    expect(botoes.length).toBeGreaterThanOrEqual(28);

    const selecionados = botoes.filter((b) => b.getAttribute("aria-pressed") === "true");
    expect(selecionados.length).toBe(1);
    expect(selecionados[0]?.getAttribute("aria-label")).toBe(
      `${formatLongDate(todayIso())}, sem eventos`,
    );
    expect(selecionados[0]?.classList.contains("today")).toBe(true);
  });

  it("a grade mobile não rende chips hora+título; o dia mostra badge e contagem acessível", async () => {
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

    // Nenhum chip de evento dentro da grade mobile (decisão de produto).
    expect(container.querySelector(".cal-m-grid .cal-ev")).toBeNull();

    const hoje = container.querySelector<HTMLElement>('.cal-m-grid button[aria-pressed="true"]');
    expect(hoje?.getAttribute("aria-label")).toBe(`${formatLongDate(todayIso())}, 2 eventos`);
    expect(hoje?.querySelector(".cal-m-count")?.textContent).toBe("2");
  });

  it("tocar num dia SELECIONA (não abre criação) e atualiza a lista abaixo", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [evento("ev-1", "Culto de celebração", "19:30")],
      page: 1,
      pageSize: 200,
      total: 1,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const alvoLabel = `${formatLongDate(otherDayIso())}, sem eventos`;
    const alvo = container.querySelector<HTMLElement>(
      `.cal-m-grid button[aria-label="${alvoLabel}"]`,
    );
    expect(alvo).not.toBeNull();

    act(() => {
      alvo!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    // Não abriu nenhum diálogo (nem criação, nem detalhe).
    expect(container.querySelector(".ds-dialog-title")).toBeNull();
    // Seleção migrou para o dia tocado…
    expect(alvo!.getAttribute("aria-pressed")).toBe("true");
    expect(
      container.querySelectorAll('.cal-m-grid button[aria-pressed="true"]').length,
    ).toBe(1);
    // …e a lista abaixo passou a ser a do dia tocado, com estado vazio claro.
    expect(container.querySelector(".cal-m-day .panel-title")?.textContent).toContain(
      `Eventos em ${formatLongDate(otherDayIso())}`,
    );
    expect(container.querySelector(".cal-m-day-empty")?.textContent).toBe(
      "Nenhum evento neste dia.",
    );
  });

  it("lista do dia mostra hora e título COMPLETOS e abre o detalhe existente", async () => {
    apiMock.fetchEvents.mockResolvedValue({
      items: [
        evento("ev-1", "Reunião de líderes de célula do setor norte", "09:00"),
        evento("ev-2", "Retiro de carnaval", null),
      ],
      page: 1,
      pageSize: 200,
      total: 2,
    });

    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const rows = [...container.querySelectorAll<HTMLElement>(".cal-m-day .list-row")];
    expect(rows.length).toBe(2);
    // Sem hora vem primeiro (ordenação byHora do buildMonthGrid).
    expect(rows[0]?.querySelector(".nm")?.textContent).toBe("Retiro de carnaval");
    expect(rows[0]?.querySelector(".sub")).toBeNull();
    expect(rows[1]?.querySelector(".nm")?.textContent).toBe(
      "Reunião de líderes de célula do setor norte",
    );
    expect(rows[1]?.querySelector(".sub")?.textContent).toBe("09:00");

    act(() => {
      rows[1]!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelectorAll('[role="dialog"]').length).toBe(1);
    expect(container.querySelector(".ds-dialog-title")?.textContent).toBe(
      "Reunião de líderes de célula do setor norte",
    );
  });

  it("'Novo evento neste dia' abre a criação com a data selecionada pré-preenchida", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const alvo = container.querySelector<HTMLElement>(
      `.cal-m-grid button[aria-label="${formatLongDate(otherDayIso())}, sem eventos"]`,
    );
    act(() => {
      alvo!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const novo = container.querySelector<HTMLElement>(".cal-m-day .cal-m-new");
    expect(novo?.textContent).toContain("Novo evento neste dia");

    act(() => {
      novo!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(container.querySelector(".ds-dialog-title")?.textContent).toBe("Novo evento");
    // A data selecionada chegou ao form (nada é submetido neste teste).
    expect(container.querySelector<HTMLInputElement>('input[type="date"]')?.value).toBe(
      otherDayIso(),
    );
  });

  it("sem canManage: dias seguem selecionáveis, mas não há botão de criação", async () => {
    authState.roles = ["lider_g12"];
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    const alvo = container.querySelector<HTMLElement>(
      `.cal-m-grid button[aria-label="${formatLongDate(otherDayIso())}, sem eventos"]`,
    );
    expect(alvo).not.toBeNull();

    act(() => {
      alvo!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(alvo!.getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelector(".cal-m-new")).toBeNull();
    expect(container.querySelector(".ds-dialog-title")).toBeNull();
  });

  it("navegar de mês recai a seleção para o dia 1 do mês exibido", async () => {
    await act(async () => {
      root.render(h(CalendarioScreen, {}));
    });

    act(() => {
      container
        .querySelector<HTMLElement>('button[aria-label="Próximo mês"]')!
        .dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const d = new Date();
    const primeiroDoProximo = isoOf(new Date(d.getFullYear(), d.getMonth() + 1, 1));
    const selecionado = container.querySelector<HTMLElement>(
      '.cal-m-grid button[aria-pressed="true"]',
    );
    expect(selecionado?.getAttribute("aria-label")).toBe(
      `${formatLongDate(primeiroDoProximo)}, sem eventos`,
    );
    expect(container.querySelector(".cal-m-day .panel-title")?.textContent).toContain(
      `Eventos em ${formatLongDate(primeiroDoProximo)}`,
    );
  });
});
