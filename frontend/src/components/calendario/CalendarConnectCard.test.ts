// @vitest-environment jsdom
/**
 * OAUTH-CALENDAR-V1 — ciclo de vida do fluxo no card de conexão.
 *
 * O que estes testes travam:
 *  - `finish` só é chamado no marcador `.../callback/ready`, e UMA única vez;
 *  - `.../callback/cancelled` não chama `finish` e mostra CTA de recuperação;
 *  - 202 preserva o `flowSecret`, mostra CTA e NÃO vira polling;
 *  - a CTA descarta o fluxo velho e começa um NOVO `/connect`;
 *  - reload antes do callback não destrói nem consome o fluxo local;
 *  - fail-closed: sem `flowSecret` na resposta do `/connect`, não redireciona
 *    ao Google.
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const expireSession = vi.fn();
// Objeto ESTÁVEL entre renders: um novo objeto a cada chamada faz os
// useCallback/useEffect que dependem dele reexecutarem em laço.
const authValue = {
  user: { roles: ["admin"] as string[] },
  token: "tok",
  expireSession,
};

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => authValue,
}));

const fetchConnectUrl = vi.fn();
const finishConnection = vi.fn();
const fetchCalendarStatus = vi.fn();
const fetchCalendarList = vi.fn();

vi.mock("@/lib/calendar-api", async (importOriginal) => {
  // Mantém as classes de erro reais: o card faz `instanceof`.
  const actual = await importOriginal<typeof import("@/lib/calendar-api")>();
  return {
    ...actual,
    fetchConnectUrl: (...args: unknown[]) => fetchConnectUrl(...args),
    finishConnection: (...args: unknown[]) => finishConnection(...args),
    fetchCalendarStatus: (...args: unknown[]) => fetchCalendarStatus(...args),
    fetchCalendarList: (...args: unknown[]) => fetchCalendarList(...args),
    disconnectCalendar: vi.fn(),
    selectCalendar: vi.fn(),
    importEvents: vi.fn(),
  };
});

const { CalendarConnectCard } = await import("./CalendarConnectCard");

const FLOW_KEY = "gcal_flow";

let container: HTMLDivElement;
let root: Root;
let hrefWrites: string[];

function setHash(hash: string) {
  window.location.hash = hash;
}

async function render() {
  await act(async () => {
    root = createRoot(container);
    root.render(h(CalendarConnectCard, {}));
  });
}

function text(): string {
  return container.textContent ?? "";
}

function button(label: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll("button")).find((b) =>
    (b.textContent ?? "").includes(label),
  ) as HTMLButtonElement | undefined;
}

async function click(el: HTMLElement) {
  await act(async () => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.sessionStorage.clear();
  fetchCalendarStatus.mockResolvedValue({ connected: false, calendarId: null });
  fetchCalendarList.mockResolvedValue([]);
  hrefWrites = [];
  // jsdom não navega; capturamos a atribuição de href.
  Object.defineProperty(window, "location", {
    configurable: true,
    value: {
      _hash: "",
      get hash() {
        return this._hash;
      },
      set hash(v: string) {
        this._hash = v.startsWith("#") ? v : `#${v}`;
        window.dispatchEvent(new Event("hashchange"));
      },
      set href(v: string) {
        hrefWrites.push(v);
      },
      get href() {
        return hrefWrites[hrefWrites.length - 1] ?? "";
      },
    },
  });
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(async () => {
  await act(async () => {
    root?.unmount();
  });
  container.remove();
});

describe("marcador de retorno", () => {
  it("não chama finish fora do marcador ready", async () => {
    setHash("#integracoes");
    window.sessionStorage.setItem(FLOW_KEY, "segredo");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    // reload antes do callback não pode destruir o fluxo local
    expect(window.sessionStorage.getItem(FLOW_KEY)).toBe("segredo");
  });

  it("chama finish UMA vez no marcador ready e limpa no sucesso", async () => {
    setHash("#integracoes/callback/ready");
    window.sessionStorage.setItem(FLOW_KEY, "segredo");
    finishConnection.mockResolvedValue({
      status: "conectado",
      connected: true,
      calendarId: "cal@x",
    });

    await render();

    expect(finishConnection).toHaveBeenCalledTimes(1);
    expect(finishConnection).toHaveBeenCalledWith("tok", "segredo");
    expect(window.sessionStorage.getItem(FLOW_KEY)).toBeNull();
  });

  it("ready sem flowSecret local mostra estado recuperável, sem chamar finish", async () => {
    setHash("#integracoes/callback/ready");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).toContain("não foi concluída");
    expect(button("Tentar novamente")).toBeTruthy();
  });
});

describe("cancelled", () => {
  it("mostra erro recuperável com CTA e NÃO chama finish", async () => {
    setHash("#integracoes/callback/cancelled");
    window.sessionStorage.setItem(FLOW_KEY, "segredo");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).toContain("cancelada");
    expect(button("Tentar novamente")).toBeTruthy();
    // nenhum indicador de carregamento persistente
    expect(text()).not.toContain("Abrindo o Google…");
  });
});

describe("202 — aguardando callback", () => {
  it("preserva o flowSecret, mostra CTA e não faz polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setHash("#integracoes/callback/ready");
    window.sessionStorage.setItem(FLOW_KEY, "segredo");
    finishConnection.mockResolvedValue({
      status: "aguardando_callback",
      connected: false,
      calendarId: null,
    });

    await render();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(finishConnection).toHaveBeenCalledTimes(1); // nada de polling
    expect(window.sessionStorage.getItem(FLOW_KEY)).toBe("segredo"); // preservado
    expect(button("Tentar novamente")).toBeTruthy();
    vi.useRealTimers();
  });
});

describe("CTA Tentar novamente", () => {
  it("descarta o fluxo velho e começa um NOVO connect", async () => {
    setHash("#integracoes/callback/cancelled");
    window.sessionStorage.setItem(FLOW_KEY, "segredo-velho");
    fetchConnectUrl.mockResolvedValue({
      authUrl: "https://accounts.google/x",
      flowSecret: "segredo-novo",
    });

    await render();
    await click(button("Tentar novamente")!);

    expect(fetchConnectUrl).toHaveBeenCalledTimes(1);
    expect(finishConnection).not.toHaveBeenCalled();
    // o segredo guardado é o NOVO — o velho nunca é reaproveitado
    expect(window.sessionStorage.getItem(FLOW_KEY)).toBe("segredo-novo");
    expect(hrefWrites).toEqual(["https://accounts.google/x"]);
  });
});

describe("connect", () => {
  it("grava o flowSecret ANTES de redirecionar ao Google", async () => {
    setHash("#integracoes");
    fetchConnectUrl.mockImplementation(async () => {
      expect(window.sessionStorage.getItem(FLOW_KEY)).toBeNull();
      return { authUrl: "https://accounts.google/x", flowSecret: "novo" };
    });

    await render();
    await click(button("Conectar Google Agenda")!);

    expect(window.sessionStorage.getItem(FLOW_KEY)).toBe("novo");
    expect(hrefWrites).toEqual(["https://accounts.google/x"]);
  });

  it("fail-closed: sem flowSecret na resposta, NÃO redireciona ao Google", async () => {
    setHash("#integracoes");
    const { ApiError } = await import("@/lib/calendar-api");
    fetchConnectUrl.mockRejectedValue(
      new ApiError(409, "Conexão indisponível no momento. Atualize a página e tente novamente."),
    );

    await render();
    await click(button("Conectar Google Agenda")!);

    expect(hrefWrites).toEqual([]); // nenhum consentimento iniciado
    expect(window.sessionStorage.getItem(FLOW_KEY)).toBeNull();
    expect(text()).toContain("Conexão indisponível");
  });
});
