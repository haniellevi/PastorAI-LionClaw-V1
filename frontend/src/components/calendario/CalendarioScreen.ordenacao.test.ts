// @vitest-environment jsdom
/**
 * FECH-08 — AGENDA-ORD-1: a aba "A confirmar" da Agenda renderiza os eventos
 * ordenados por data do evento em ordem ascendente (mais próximo primeiro),
 * com ordenação estável aplicada no frontend (a API continua devolvendo a
 * lista na ordem original — nada muda no backend):
 *  - lista fora de ordem sai renderizada em ordem cronológica;
 *  - empate de data preserva a ordem original da API (estabilidade);
 *  - evento sem data (recorrente, data=null) vai para o fim.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EventItem } from "@/lib/events-api";

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

/** Evento 'a_confirmar' mínimo para a fila (campos EVT-2 relevantes). */
function pending(id: string, titulo: string, data: string | null): EventItem {
  return {
    id,
    titulo,
    data,
    hora: null,
    descricao: null,
    googleEventId: null,
    sincronizado: false,
    status: "a_confirmar",
    origem: "google",
    recorrencia: data === null ? "semanal" : null,
  };
}

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  apiMock.fetchEvents.mockReset();
  apiMock.fetchEvents.mockResolvedValue({ items: [], page: 1, pageSize: 200, total: 0 });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  authState.roles = ["pastor"];
});

/** Renderiza a tela e ativa a aba "A confirmar". */
async function renderConfirmarTab(items: EventItem[]) {
  apiMock.fetchEvents.mockResolvedValue({
    items,
    page: 1,
    pageSize: 200,
    total: items.length,
  });

  await act(async () => {
    root.render(h(CalendarioScreen, {}));
  });

  const tab = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]')).find(
    (b) => b.textContent?.startsWith("A confirmar"),
  );
  expect(tab).not.toBeUndefined();

  act(() => {
    tab!.click();
  });
}

/** Títulos dos eventos da fila, na ordem em que foram renderizados. */
function renderedTitles(): string[] {
  return Array.from(container.querySelectorAll(".list-row .nm")).map((el) =>
    (el.textContent ?? "").trim(),
  );
}

describe("CalendarioScreen — aba 'A confirmar' ordenada por data (AGENDA-ORD-1)", () => {
  it("lista fora de ordem renderiza ordenada por data ascendente (mais próximo primeiro)", async () => {
    await renderConfirmarTab([
      pending("ev-3", "Conferência", "2026-09-10"),
      pending("ev-1", "Culto de jovens", "2026-07-25"),
      pending("ev-2", "Batismo", "2026-08-02"),
    ]);

    expect(renderedTitles()).toEqual(["Culto de jovens", "Batismo", "Conferência"]);
  });

  it("ordenação estável: empates de data preservam a ordem original da API", async () => {
    await renderConfirmarTab([
      pending("ev-b", "Evento B", "2026-08-02"),
      pending("ev-a", "Evento A", "2026-08-02"),
      pending("ev-c", "Evento C", "2026-07-25"),
      pending("ev-d", "Evento D", "2026-08-02"),
    ]);

    // 2026-07-25 primeiro; os três empatados em 2026-08-02 mantêm B → A → D.
    expect(renderedTitles()).toEqual(["Evento C", "Evento B", "Evento A", "Evento D"]);
  });

  it("evento sem data (recorrente) vai para o fim, sem quebrar a ordenação dos datados", async () => {
    await renderConfirmarTab([
      pending("ev-r", "Recorrente sem data", null),
      pending("ev-2", "Evento futuro", "2026-12-01"),
      pending("ev-1", "Evento próximo", "2026-07-21"),
    ]);

    expect(renderedTitles()).toEqual(["Evento próximo", "Evento futuro", "Recorrente sem data"]);
  });
});
