// @vitest-environment jsdom
/**
 * OAUTH-CALENDAR-V1 + PR222-OPTIONAL-SECRET-SECURITY-FIX-1 — ciclo de vida do
 * fluxo no card de conexão.
 *
 * O que estes testes travam:
 *  - `finish` NUNCA é chamado sem segredo válido — nem na montagem, nem no
 *    `visibilitychange`, nem no marcador `ready`;
 *  - fora do marcador `ready`, quem conclui é o CLIQUE do usuário na CTA
 *    "Concluir conexão com o Google";
 *  - o segredo mora no `localStorage` da origem, com o `expiresAt` do servidor,
 *    e some ao expirar, concluir, cancelar ou levar rejeição terminal;
 *  - 202 preserva o segredo e mantém a ação explícita disponível;
 *  - fail-closed: sem `flowSecret`/`expiresAt` no `/connect`, não redireciona.
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

/** Chave VERSIONADA: o formato passou a ser objeto com prazo, em localStorage. */
const FLOW_KEY = "gcal_flow_v2";
const CTA_FINISH = "Concluir conexão com o Google";
const CTA_CONNECT = "Conectar Google Agenda";
const CTA_RESTART = "Tentar novamente";

interface StoredFlow {
  secret: string;
  expiresAt: number;
}

function seedFlow(secret = "segredo", expiresAt = Date.now() + 3_600_000): void {
  window.localStorage.setItem(FLOW_KEY, JSON.stringify({ secret, expiresAt }));
}

function storedFlow(): StoredFlow | null {
  const raw = window.localStorage.getItem(FLOW_KEY);
  return raw ? (JSON.parse(raw) as StoredFlow) : null;
}

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

async function foreground() {
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
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

const CONECTADO = { status: "conectado", connected: true, calendarId: "cal@x" };
const AGUARDANDO = {
  status: "aguardando_callback",
  connected: false,
  calendarId: null,
};

describe("marcador ready", () => {
  it("com segredo válido conclui usando exatamente aquele segredo", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    finishConnection.mockResolvedValue(CONECTADO);

    await render();

    expect(finishConnection).toHaveBeenCalledTimes(1);
    expect(finishConnection).toHaveBeenCalledWith("tok", "segredo");
    expect(text()).toContain("Agenda sincronizada");
    expect(storedFlow()).toBeNull(); // conclusão limpa o armazenamento
  });

  it("SEM segredo é fail-closed: zero POST e CTA de reinício", async () => {
    setHash("#integracoes/callback/ready");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).toContain("não foi concluída");
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
  });

  it("com segredo EXPIRADO não conclui e apaga o armazenamento", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo", Date.now() - 1_000);

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow()).toBeNull();
    expect(button(CTA_FINISH)).toBeUndefined();
  });
});

describe("fora do marcador ready — conclusão é do usuário", () => {
  it("segredo válido NÃO dispara finish na montagem; mostra a CTA", async () => {
    setHash("#integracoes");
    seedFlow("segredo");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(button(CTA_FINISH)).toBeTruthy();
    expect(button(CTA_CONNECT)).toBeUndefined();
    expect(storedFlow()?.secret).toBe("segredo"); // preservado
  });

  it("o CLIQUE na CTA é que chama finish, com o segredo guardado", async () => {
    setHash("#integracoes");
    seedFlow("segredo");
    finishConnection.mockResolvedValue(CONECTADO);

    await render();
    await click(button(CTA_FINISH)!);

    expect(finishConnection).toHaveBeenCalledTimes(1);
    expect(finishConnection).toHaveBeenCalledWith("tok", "segredo");
    expect(text()).toContain("Agenda sincronizada");
    expect(storedFlow()).toBeNull();
  });

  it("PWA relançada com localStorage válido mostra a CTA, sem POST", async () => {
    // Relançamento: nenhuma rota de retorno, storage veio do disco.
    setHash("#dashboard");
    seedFlow("segredo-da-pwa");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(button(CTA_FINISH)).toBeTruthy();
    expect(storedFlow()?.secret).toBe("segredo-da-pwa");
  });

  it("armazenamento expirado é removido e nenhum finish acontece", async () => {
    setHash("#integracoes");
    seedFlow("velho", Date.now() - 60_000);

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow()).toBeNull();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(button(CTA_CONNECT)).toBeTruthy();
  });

  it("armazenamento corrompido é removido e nenhum finish acontece", async () => {
    setHash("#integracoes");
    window.localStorage.setItem(FLOW_KEY, "{isto nao e json");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow()).toBeNull();
    expect(button(CTA_CONNECT)).toBeTruthy();
  });
});

/**
 * REGRESSÃO DE SEGURANÇA — sem segredo, o painel não fala com o `finish`.
 * Era por aqui que um `state` vazado virava vinculação de conta silenciosa.
 */
describe("sem segredo — zero POST de finish", () => {
  it("montagem e visibilitychange não produzem nenhuma chamada", async () => {
    setHash("#integracoes");

    await render();
    await foreground();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(button(CTA_CONNECT)).toBeTruthy();
  });

  it("visibilitychange após redirect real destrava a UI, mas não conclui", async () => {
    setHash("#integracoes");
    fetchConnectUrl.mockResolvedValue({
      authUrl: "https://accounts.google/x",
      flowSecret: "novo",
      expiresAt: Date.now() + 3_600_000,
    });

    await render();
    await click(button(CTA_CONNECT)!);
    // iOS: a PWA não navegou — segue viva, com o botão preso em "Abrindo…".
    expect(text()).toContain("Abrindo o Google…");

    await foreground();

    // Destravou e revelou a CTA. NADA foi concluído sozinho.
    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).not.toContain("Abrindo o Google…");
    expect(button(CTA_FINISH)).toBeTruthy();
  });

  it("nenhuma chamada de finish recebe null, undefined ou vazio", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    finishConnection.mockResolvedValue(CONECTADO);

    await render();
    await foreground();

    for (const call of finishConnection.mock.calls) {
      expect(typeof call[1]).toBe("string");
      expect(call[1]).toBeTruthy();
    }
  });
});

describe("cancelled", () => {
  it("limpa o segredo, mostra CTA de reinício e NÃO chama finish", async () => {
    setHash("#integracoes/callback/cancelled");
    seedFlow("segredo");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).toContain("cancelada");
    expect(storedFlow()).toBeNull();
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(text()).not.toContain("Abrindo o Google…");
  });
});

describe("202 — aguardando callback", () => {
  it("preserva o segredo, mantém a ação explícita e não faz polling", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    finishConnection.mockResolvedValue(AGUARDANDO);

    await render();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });

    expect(finishConnection).toHaveBeenCalledTimes(1); // nada de polling
    expect(storedFlow()?.secret).toBe("segredo"); // preservado até o TTL
    expect(button(CTA_FINISH)).toBeTruthy(); // ação explícita segue à mão
    vi.useRealTimers();
  });

  it("o segundo clique reusa o MESMO segredo", async () => {
    setHash("#integracoes");
    seedFlow("segredo");
    finishConnection.mockResolvedValue(AGUARDANDO);

    await render();
    await click(button(CTA_FINISH)!);
    await click(button(CTA_FINISH)!);

    expect(finishConnection).toHaveBeenCalledTimes(2);
    expect(finishConnection).toHaveBeenNthCalledWith(2, "tok", "segredo");
    expect(storedFlow()?.secret).toBe("segredo");
  });
});

describe("rejeição terminal", () => {
  it("409 limpa o segredo e oferece reinício", async () => {
    setHash("#integracoes");
    seedFlow("segredo");
    const { ApiError } = await import("@/lib/calendar-api");
    finishConnection.mockRejectedValue(new ApiError(409, "Não foi possível concluir."));

    await render();
    await click(button(CTA_FINISH)!);

    expect(storedFlow()).toBeNull();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(button(CTA_RESTART)).toBeTruthy();
  });

  it("5xx NÃO é terminal: o segredo sobrevive para o usuário tentar de novo", async () => {
    setHash("#integracoes");
    seedFlow("segredo");
    const { ApiError } = await import("@/lib/calendar-api");
    finishConnection.mockRejectedValue(new ApiError(502, "Google fora do ar."));

    await render();
    await click(button(CTA_FINISH)!);

    expect(storedFlow()?.secret).toBe("segredo");
    expect(button(CTA_FINISH)).toBeTruthy();
  });
});

describe("connect", () => {
  it("grava segredo + expiresAt do servidor ANTES de redirecionar", async () => {
    setHash("#integracoes");
    const expiresAt = Date.now() + 600_000;
    fetchConnectUrl.mockImplementation(async () => {
      expect(storedFlow()).toBeNull();
      return { authUrl: "https://accounts.google/x", flowSecret: "novo", expiresAt };
    });

    await render();
    await click(button(CTA_CONNECT)!);

    expect(storedFlow()).toEqual({ secret: "novo", expiresAt });
    expect(hrefWrites).toEqual(["https://accounts.google/x"]);
  });

  it("iniciar um fluxo novo descarta deliberadamente o anterior", async () => {
    setHash("#integracoes");
    seedFlow("segredo-velho");
    fetchConnectUrl.mockResolvedValue({
      authUrl: "https://accounts.google/x",
      flowSecret: "segredo-novo",
      expiresAt: Date.now() + 600_000,
    });

    await render();
    await click(button("Começar de novo")!);

    expect(fetchConnectUrl).toHaveBeenCalledTimes(1);
    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow()?.secret).toBe("segredo-novo"); // o velho nunca volta
    expect(hrefWrites).toEqual(["https://accounts.google/x"]);
  });

  it("CTA de reinício depois de cancelar começa um fluxo novo", async () => {
    setHash("#integracoes/callback/cancelled");
    seedFlow("segredo-velho");
    fetchConnectUrl.mockResolvedValue({
      authUrl: "https://accounts.google/x",
      flowSecret: "segredo-novo",
      expiresAt: Date.now() + 600_000,
    });

    await render();
    await click(button(CTA_RESTART)!);

    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow()?.secret).toBe("segredo-novo");
  });

  it("fail-closed: sem flowSecret na resposta, NÃO redireciona ao Google", async () => {
    setHash("#integracoes");
    const { ApiError } = await import("@/lib/calendar-api");
    fetchConnectUrl.mockRejectedValue(
      new ApiError(409, "Conexão indisponível no momento. Atualize a página e tente novamente."),
    );

    await render();
    await click(button(CTA_CONNECT)!);

    expect(hrefWrites).toEqual([]); // nenhum consentimento iniciado
    expect(storedFlow()).toBeNull();
    expect(text()).toContain("Conexão indisponível");
  });
});
