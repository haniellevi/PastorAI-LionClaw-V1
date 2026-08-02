// @vitest-environment jsdom
/**
 * OAUTH-CALENDAR-V1 + posse obrigatória do `flowSecret` + binding de identidade
 * — ciclo de vida do fluxo no card de conexão.
 *
 * O que estes testes travam:
 *  - `finish` NUNCA é chamado sem segredo válido — nem na montagem, nem no
 *    `visibilitychange`, nem no marcador `ready`;
 *  - fora do marcador `ready`, quem conclui é o CLIQUE do usuário;
 *  - `/connect` só sai com a conta Google DECLARADA, normalizada;
 *  - a conta conectada é exibida, a troca avisa antes, e o legado (sem conta
 *    registrada) continua conectado e ganha CTA de registro;
 *  - conta divergente limpa o segredo e mostra as DUAS contas, sem alterar nada;
 *  - o segredo mora no `localStorage` da origem, com o `expiresAt` do servidor;
 *  - a época de mutação impede que uma leitura de status atrasada desfaça uma
 *    conexão recém-concluída.
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
  user: { roles: ["admin"] as string[], appUserId: "app-user-1" },
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

/** Chave VERSIONADA: objeto com prazo, em localStorage. */
const FLOW_KEY_PREFIX = "gcal_flow_v3";
const CTA_FINISH = "Concluir conexão com o Google";
const CTA_CONNECT = "Conectar Google Agenda";
const CTA_RESTART = "Tentar novamente";
const CTA_SWITCH = "Trocar conta Google";
const CTA_REGISTER = "Registrar conta Google";

const EMAIL = "agenda@igreja12.com.br";
const OUTRO_EMAIL = "pessoal@gmail.com";

interface StoredFlow {
  secret: string;
  expiresAt: number;
}

function flowKey(appUserId = authValue.user.appUserId): string {
  return `${FLOW_KEY_PREFIX}:${appUserId}`;
}

function seedFlow(
  secret = "segredo",
  expiresAt = Date.now() + 3_600_000,
  appUserId = authValue.user.appUserId,
): void {
  window.localStorage.setItem(flowKey(appUserId), JSON.stringify({ secret, expiresAt }));
}

function storedFlow(appUserId = authValue.user.appUserId): StoredFlow | null {
  const raw = window.localStorage.getItem(flowKey(appUserId));
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

function emailField(): HTMLInputElement | null {
  return container.querySelector('input[type="email"]');
}

/** Input controlado do React: precisa do setter nativo para o onChange rodar. */
async function typeEmail(value: string) {
  const el = emailField();
  if (!el) throw new Error("campo de e-mail não está na tela");
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
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

const DESCONECTADO = { connected: false, calendarId: null, googleAccountEmail: null };
const CONECTADO = {
  status: "conectado",
  connected: true,
  calendarId: "cal@x",
  googleAccountEmail: EMAIL,
};
const AGUARDANDO = {
  status: "aguardando_callback",
  connected: false,
  calendarId: null,
  googleAccountEmail: null,
};
const START = {
  authUrl: "https://accounts.google/x",
  flowSecret: "novo",
  expiresAt: Date.now() + 600_000,
};

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  window.sessionStorage.clear();
  fetchCalendarStatus.mockResolvedValue(DESCONECTADO);
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
  vi.restoreAllMocks();
  container.remove();
});

describe("conta Google declarada", () => {
  it("sem e-mail válido o botão fica travado e nada é iniciado", async () => {
    setHash("#integracoes");

    await render();

    expect(emailField()).toBeTruthy();
    expect(button(CTA_CONNECT)?.disabled).toBe(true);
    await click(button(CTA_CONNECT)!);
    expect(fetchConnectUrl).not.toHaveBeenCalled();

    // E-mail malformado continua travando.
    await typeEmail("sem-arroba");
    expect(button(CTA_CONNECT)?.disabled).toBe(true);
    await click(button(CTA_CONNECT)!);
    expect(fetchConnectUrl).not.toHaveBeenCalled();
    expect(hrefWrites).toEqual([]);
  });

  it("envia a conta NORMALIZADA para o /connect", async () => {
    setHash("#integracoes");
    fetchConnectUrl.mockResolvedValue(START);

    await render();
    await typeEmail("  Agenda@Igreja12.COM.BR  ");
    await click(button(CTA_CONNECT)!);

    expect(fetchConnectUrl).toHaveBeenCalledTimes(1);
    expect(fetchConnectUrl).toHaveBeenCalledWith("tok", EMAIL);
    expect(storedFlow()).toEqual({ secret: "novo", expiresAt: START.expiresAt });
    expect(hrefWrites).toEqual(["https://accounts.google/x"]);
  });

  it("fail-closed: sem flowSecret na resposta, NÃO redireciona ao Google", async () => {
    setHash("#integracoes");
    const { ApiError } = await import("@/lib/calendar-api");
    fetchConnectUrl.mockRejectedValue(
      new ApiError(409, "Conexão indisponível no momento. Atualize a página e tente novamente."),
    );

    await render();
    await typeEmail(EMAIL);
    await click(button(CTA_CONNECT)!);

    expect(hrefWrites).toEqual([]); // nenhum consentimento iniciado
    expect(storedFlow()).toBeNull();
    expect(text()).toContain("Conexão indisponível");
  });

  it("fail-closed: armazenamento indisponível NÃO redireciona ao Google", async () => {
    setHash("#integracoes");
    fetchConnectUrl.mockResolvedValue(START);
    const setItem = vi
      .spyOn(Storage.prototype, "setItem")
      .mockImplementationOnce(() => undefined);

    await render();
    await typeEmail(EMAIL);
    await click(button(CTA_CONNECT)!);

    expect(fetchConnectUrl).toHaveBeenCalledTimes(1);
    expect(hrefWrites).toEqual([]);
    expect(storedFlow()).toBeNull();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(text()).toContain("não permitiu guardar a conexão");
    setItem.mockRestore();
  });
});

describe("identidade conectada", () => {
  it("mostra a conta Google conectada", async () => {
    setHash("#integracoes");
    fetchCalendarStatus.mockResolvedValue({
      connected: true,
      calendarId: "cal@x",
      googleAccountEmail: EMAIL,
    });

    await render();

    expect(text()).toContain("Conectado como");
    expect(text()).toContain(EMAIL);
    expect(button(CTA_SWITCH)).toBeTruthy();
    expect(emailField()).toBeNull(); // o formulário só abre no clique
  });

  it("trocar de conta avisa ANTES de redirecionar", async () => {
    setHash("#integracoes");
    fetchCalendarStatus.mockResolvedValue({
      connected: true,
      calendarId: "cal@x",
      googleAccountEmail: EMAIL,
    });
    fetchConnectUrl.mockResolvedValue(START);

    await render();
    await click(button(CTA_SWITCH)!);
    // O campo abre já preenchido com a conta atual: sem aviso enquanto for ela.
    expect(emailField()?.value).toBe(EMAIL);
    expect(text()).not.toContain("TROCA a conta conectada");

    await typeEmail(OUTRO_EMAIL);

    expect(text()).toContain("TROCA a conta conectada");
    expect(text()).toContain(EMAIL);
    expect(text()).toContain(OUTRO_EMAIL);
    expect(fetchConnectUrl).not.toHaveBeenCalled(); // só avisou

    await click(button(CTA_SWITCH)!);
    expect(fetchConnectUrl).toHaveBeenCalledWith("tok", OUTRO_EMAIL);
  });

  it("preserva e revela a troca pendente quando o status ainda mostra a conta antiga", async () => {
    setHash("#integracoes");
    fetchCalendarStatus.mockResolvedValue({
      connected: true,
      calendarId: "cal@x",
      googleAccountEmail: EMAIL,
    });
    fetchConnectUrl.mockResolvedValue(START);

    await render();
    await click(button(CTA_SWITCH)!);
    await typeEmail(OUTRO_EMAIL);
    await click(button(CTA_SWITCH)!);

    expect(storedFlow()).toEqual({ secret: "novo", expiresAt: START.expiresAt });

    // PWA volta ao primeiro plano antes do finish. O GET ainda descreve a
    // conta antiga, mas não pode apagar nem esconder o fluxo novo.
    await foreground();

    expect(storedFlow()).toEqual({ secret: "novo", expiresAt: START.expiresAt });
    expect(button(CTA_FINISH)).toBeTruthy();
    expect(text()).toContain("Conclua a conexão");
    expect(finishConnection).not.toHaveBeenCalled();
  });

  it("conexão legada continua conectada e oferece registrar a conta", async () => {
    setHash("#integracoes");
    fetchCalendarStatus.mockResolvedValue({
      connected: true,
      calendarId: "cal@x",
      googleAccountEmail: null,
    });
    fetchConnectUrl.mockResolvedValue(START);

    await render();

    expect(text()).toContain("Conta Google não registrada");
    expect(text()).toContain("Agenda sincronizada"); // segue conectada
    expect(button(CTA_REGISTER)).toBeTruthy();
    expect(button(CTA_SWITCH)).toBeUndefined();

    await click(button(CTA_REGISTER)!);
    await typeEmail(EMAIL);
    // Sem conta anterior conhecida não há o que "trocar" — nenhum aviso.
    expect(text()).not.toContain("TROCA a conta conectada");
    await click(button(CTA_REGISTER)!);

    expect(fetchConnectUrl).toHaveBeenCalledWith("tok", EMAIL);
  });
});

describe("conta divergente", () => {
  it("limpa o segredo, mostra as DUAS contas e não altera nada", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    const { GoogleAccountMismatchError } = await import("@/lib/calendar-api");
    finishConnection.mockRejectedValue(
      new GoogleAccountMismatchError(EMAIL, OUTRO_EMAIL),
    );

    await render();

    expect(storedFlow()).toBeNull();
    expect(text()).toContain(EMAIL);
    expect(text()).toContain(OUTRO_EMAIL);
    expect(text()).toContain("Nada foi alterado");
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
  });

  it("reiniciar volta ao formulário de conta, sem POST automático", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    const { GoogleAccountMismatchError } = await import("@/lib/calendar-api");
    finishConnection.mockRejectedValue(
      new GoogleAccountMismatchError(EMAIL, OUTRO_EMAIL),
    );

    await render();
    await click(button(CTA_RESTART)!);

    expect(emailField()).toBeTruthy();
    expect(fetchConnectUrl).not.toHaveBeenCalled();
    expect(finishConnection).toHaveBeenCalledTimes(1); // só a do marcador
  });

  it("falha do finish restaura a conexão anterior apesar do status inicial obsoleto", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    const { GoogleAccountMismatchError } = await import("@/lib/calendar-api");
    let resolveInitial!: (value: typeof DESCONECTADO) => void;
    fetchCalendarStatus
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveInitial = resolve;
          }),
      )
      .mockResolvedValueOnce({
        connected: true,
        calendarId: "agenda-antiga@x",
        googleAccountEmail: EMAIL,
      });
    finishConnection.mockRejectedValue(
      new GoogleAccountMismatchError(EMAIL, OUTRO_EMAIL),
    );

    await render();

    expect(fetchCalendarStatus).toHaveBeenCalledTimes(2);
    expect(text()).toContain("Nada foi alterado");
    await click(button(CTA_RESTART)!);
    expect(text()).toContain("Conectado como");
    expect(text()).toContain(EMAIL);
    expect(text()).toContain("agenda-antiga@x");

    // A resposta inicial nasceu antes do finish e continua sem autoridade.
    await act(async () => {
      resolveInitial(DESCONECTADO);
    });
    expect(text()).toContain("Conectado como");
    expect(text()).toContain("agenda-antiga@x");
  });
});

describe("marcador ready", () => {
  it("não consome o fluxo de outro usuário no mesmo navegador", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo-de-outro-admin", Date.now() + 3_600_000, "app-user-2");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow("app-user-2")?.secret).toBe("segredo-de-outro-admin");
    expect(storedFlow()).toBeNull();
    expect(text()).toContain("não foi concluída");
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
  });

  it("com segredo válido conclui e atualiza a conta exibida", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    finishConnection.mockResolvedValue(CONECTADO);

    await render();

    expect(finishConnection).toHaveBeenCalledTimes(1);
    expect(finishConnection).toHaveBeenCalledWith("tok", "segredo");
    expect(text()).toContain("Conectado como");
    expect(text()).toContain(EMAIL);
    expect(storedFlow()).toBeNull();
  });

  it("troca de identidade chega com calendarId nulo e a UI aguenta", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");
    finishConnection.mockResolvedValue({
      status: "conectado",
      connected: true,
      calendarId: null,
      googleAccountEmail: OUTRO_EMAIL,
    });

    await render();

    expect(text()).toContain(OUTRO_EMAIL);
    expect(text()).toContain("selecione abaixo"); // sem agenda herdada
  });

  it("conclusão vence leitura de status em voo — sem estado obsoleto", async () => {
    // F1: `loadStatus` sai antes do `finish`, mas resolve DEPOIS. Sem a época de
    // mutação, o snapshot velho (connected=false) reescreve por cima do sucesso.
    setHash("#integracoes/callback/ready");
    seedFlow("segredo");

    let resolveStatus!: (v: typeof DESCONECTADO) => void;
    fetchCalendarStatus.mockImplementation(
      () =>
        new Promise((res) => {
          resolveStatus = res;
        }),
    );
    finishConnection.mockResolvedValue(CONECTADO);

    await render();

    expect(text()).toContain("Agenda sincronizada");
    expect(text()).toContain("cal@x");
    expect(storedFlow()).toBeNull();

    await act(async () => {
      resolveStatus(DESCONECTADO);
    });

    expect(text()).toContain("Agenda sincronizada");
    expect(text()).toContain("cal@x");
    expect(storedFlow()).toBeNull();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(button(CTA_CONNECT)).toBeUndefined();
  });

  it("SEM segredo é fail-closed: zero POST e CTA de reinício", async () => {
    setHash("#integracoes/callback/ready");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).toContain("não foi concluída");
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
  });

  it("deixa o servidor validar o prazo mesmo se o relógio local estiver adiantado", async () => {
    setHash("#integracoes/callback/ready");
    seedFlow("segredo", Date.now() - 1_000);
    // O timestamp parece vencido apenas para o dispositivo; o servidor, cuja
    // hora criou o TTL, ainda aceita o fluxo.
    finishConnection.mockResolvedValue(CONECTADO);

    await render();

    expect(finishConnection).toHaveBeenCalledWith("tok", "segredo");
    expect(storedFlow()).toBeNull();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(text()).toContain("Agenda sincronizada");
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

  it("prazo aparentemente vencido continua disponível para validação do servidor", async () => {
    setHash("#integracoes");
    seedFlow("velho", Date.now() - 60_000);

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(storedFlow()?.secret).toBe("velho");
    expect(button(CTA_FINISH)).toBeTruthy();
    expect(button(CTA_CONNECT)).toBeUndefined();
  });

  it("armazenamento corrompido é removido e nenhum finish acontece", async () => {
    setHash("#integracoes");
    window.localStorage.setItem(flowKey(), "{isto nao e json");

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
    fetchConnectUrl.mockResolvedValue(START);

    await render();
    await typeEmail(EMAIL);
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
  it("preserva fluxo não correlacionado, mostra reinício e NÃO chama finish", async () => {
    setHash("#integracoes/callback/cancelled");
    seedFlow("segredo");

    await render();

    expect(finishConnection).not.toHaveBeenCalled();
    expect(text()).toContain("cancelada");
    expect(storedFlow()?.secret).toBe("segredo");
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(text()).not.toContain("Abrindo o Google…");
  });

  it("mostra cancelamento e reinício mesmo com a conta anterior conectada", async () => {
    setHash("#integracoes/callback/cancelled");
    seedFlow("segredo");
    fetchCalendarStatus.mockResolvedValue({
      connected: true,
      calendarId: "cal@x",
      googleAccountEmail: EMAIL,
    });

    await render();

    expect(text()).toContain("cancelada");
    expect(button(CTA_RESTART)).toBeTruthy();
    expect(button(CTA_FINISH)).toBeUndefined();
    expect(storedFlow()?.secret).toBe("segredo");
  });

  it("reiniciar depois de cancelar exige declarar a conta de novo", async () => {
    setHash("#integracoes/callback/cancelled");
    seedFlow("segredo-velho");
    fetchConnectUrl.mockResolvedValue({ ...START, flowSecret: "segredo-novo" });

    await render();
    await typeEmail(EMAIL);
    await click(button(CTA_RESTART)!);

    expect(finishConnection).not.toHaveBeenCalled();
    expect(fetchConnectUrl).toHaveBeenCalledWith("tok", EMAIL);
    expect(storedFlow()?.secret).toBe("segredo-novo"); // o velho nunca volta
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

  it.each([403, 422])(
    "%i pré-handler NÃO apaga um fluxo que o servidor ainda não consumiu",
    async (status) => {
      setHash("#integracoes");
      seedFlow("segredo");
      const { ApiError } = await import("@/lib/calendar-api");
      finishConnection.mockRejectedValue(
        new ApiError(status, "Acesso temporariamente indisponível."),
      );

      await render();
      await click(button(CTA_FINISH)!);

      expect(storedFlow()?.secret).toBe("segredo");
      expect(button(CTA_FINISH)).toBeTruthy();
    },
  );
});

describe("iniciar um fluxo novo", () => {
  it("'Começar de novo' descarta o segredo e pede a conta outra vez", async () => {
    setHash("#integracoes");
    seedFlow("segredo-velho");
    fetchConnectUrl.mockResolvedValue({ ...START, flowSecret: "segredo-novo" });

    await render();
    await click(button("Começar de novo")!);

    // O velho morreu na hora e o formulário voltou.
    expect(storedFlow()).toBeNull();
    expect(emailField()).toBeTruthy();
    expect(fetchConnectUrl).not.toHaveBeenCalled();

    await typeEmail(EMAIL);
    await click(button(CTA_CONNECT)!);

    expect(fetchConnectUrl).toHaveBeenCalledWith("tok", EMAIL);
    expect(storedFlow()?.secret).toBe("segredo-novo");
    expect(finishConnection).not.toHaveBeenCalled();
  });

  it("falha transitória do status ainda revela o fluxo salvo, sem substituí-lo", async () => {
    setHash("#integracoes");
    seedFlow("segredo");
    fetchCalendarStatus.mockRejectedValue(new Error("status indisponível"));

    await render();

    expect(storedFlow()?.secret).toBe("segredo");
    expect(button(CTA_FINISH)).toBeTruthy();
    expect(button(CTA_CONNECT)).toBeUndefined();
    expect(finishConnection).not.toHaveBeenCalled();
  });
});
