// @vitest-environment jsdom
/**
 * M7B-W3.2B — arquivamento de Pessoa integrado à tela #contatos:
 *  - admin abre o preflight, confirma com motivo e a tela reflete o sucesso
 *    (toast + selo "Arquivada", sem remover a pessoa da lista — nunca um
 *    hard delete visual);
 *  - preflight bloqueado nunca deixa confirmar;
 *  - 403/404 no preflight, 403/404/409(bloqueado)/rede na confirmação
 *    aparecem como erro, sem quebrar a tela;
 *  - usuário não-admin nem vê o botão nem dispara o preflight;
 *  - RACE: preflight de A atrasado não pode sobrescrever o preflight de B
 *    (REVIEW_FAIL do PR#169 — rede não garante ordem de resposta).
 *
 * Sem JSX (createElement): o tsconfig do Next usa jsx:"preserve".
 */
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ArchiveContactResult, Contact, OffboardingPreflight } from "@/lib/contacts-api";

const authState = vi.hoisted(() => ({
  roles: ["admin"] as string[],
  // Referências ESTÁVEIS entre renders: um objeto/fn novo a cada chamada de
  // useAuth() muda a identidade de `expireSession` -> recria `handleSessionError`
  // -> recria `load` -> o useEffect([load]) refaz o fetch pra sempre (loop).
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
  fetchContactsPage: vi.fn(),
  fetchContactDetail: vi.fn(),
  fetchOffboardingPreflight: vi.fn(),
  archiveContact: vi.fn(),
}));
const dashboardMock = vi.hoisted(() => ({ fetchCells: vi.fn() }));

vi.mock("@/lib/contacts-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/contacts-api")>();
  return {
    ...actual,
    fetchContactsPage: apiMock.fetchContactsPage,
    fetchContactDetail: apiMock.fetchContactDetail,
    fetchOffboardingPreflight: apiMock.fetchOffboardingPreflight,
    archiveContact: apiMock.archiveContact,
    createContact: vi.fn(),
    linkContactCell: vi.fn(),
    updateContact: vi.fn(),
  };
});

vi.mock("@/lib/dashboard-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/dashboard-api")>();
  return {
    ...actual,
    fetchCells: dashboardMock.fetchCells,
  };
});

const realContactsApi = await vi.importActual<typeof import("@/lib/contacts-api")>(
  "@/lib/contacts-api",
);
const { ArchiveBlockedError } = await import("@/lib/contacts-api");
const { ApiError } = await import("@/lib/dashboard-api");
const { ContatosScreen } = await import("./ContatosScreen");

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const contact: Contact = {
  id: "p1",
  nome: "Ana Souza",
  telefone: "5511987654321",
  email: null,
  genero: null,
  tipo: "membro",
  etapa: "discipular",
  subetapa: null,
  acompanhamento: null,
  semInteresse: false,
  semInteresseMotivo: null,
  presencasCelula: 4,
  aceitouJesus: true,
  celulaId: null,
  liderId: null,
  aptoLider: false,
  liderDeCelula: false,
};

function preflight(over: Partial<OffboardingPreflight> = {}): OffboardingPreflight {
  return {
    pessoa_id: "p1",
    pode_arquivar: true,
    bloqueadores: [],
    automaticos: [],
    preservados: [
      {
        tipo: "conversas_mensagens",
        rotulo: "Conversas e mensagens do WhatsApp",
        recurso_id: null,
        recurso_nome: null,
        acao_recomendada: null,
      },
    ],
    ...over,
  };
}

const contactB: Contact = {
  ...contact,
  id: "p2",
  nome: "Beatriz Lima",
  telefone: "5511999998888",
};

function archiveResult(over: Partial<ArchiveContactResult> = {}): ArchiveContactResult {
  return {
    pessoa_id: "p1",
    arquivada: true,
    arquivada_em: "2026-07-14T12:00:00Z",
    arquivada_por: "admin-1",
    arquivada_motivo: "Mudou de cidade",
    ja_arquivada: false,
    ...over,
  };
}

let container: HTMLDivElement;
let root: Root;

async function flush(times = 3) {
  for (let i = 0; i < times; i++) {
    // eslint-disable-next-line no-await-in-loop
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

function findButton(label: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((b) => b.textContent!.includes(label));
}

function findRow(nameSubstring: string): HTMLTableRowElement {
  const row = [...container.querySelectorAll<HTMLTableRowElement>(".data-table tbody tr")].find(
    (r) => r.textContent!.includes(nameSubstring),
  );
  if (!row) throw new Error(`linha não encontrada na tabela: ${nameSubstring}`);
  return row;
}

function tableText(): string {
  return container.querySelector(".data-table")?.textContent ?? "";
}

function clickRow(nameSubstring: string) {
  act(() => {
    findRow(nameSubstring).dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

/** Botão de confirmar "Arquivar pessoa" DENTRO do diálogo (o 2º/último com esse texto). */
function findConfirmButton(): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")]
    .filter((b) => b.textContent!.includes("Arquivar pessoa"))
    .at(-1);
}

function setTextarea(value: string) {
  const textarea = container.querySelector("textarea")!;
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value")!
    .set!;
  act(() => {
    setter.call(textarea, value);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function renderScreenWithContact() {
  apiMock.fetchContactsPage.mockResolvedValue({
    items: [contact],
    page: 1,
    pageSize: 200,
    total: 1,
  });
  act(() => {
    root.render(h(ContatosScreen, {}));
  });
  await flush();
  const row = container.querySelector<HTMLTableRowElement>(".data-table tbody tr")!;
  act(() => {
    row.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

beforeEach(() => {
  authState.roles = ["admin"];
  authState.expireSession.mockClear();
  apiMock.fetchContactsPage.mockReset();
  apiMock.fetchContactDetail.mockReset();
  apiMock.fetchOffboardingPreflight.mockReset();
  apiMock.archiveContact.mockReset();
  dashboardMock.fetchCells.mockReset();
  dashboardMock.fetchCells.mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("ContatosScreen — arquivamento de Pessoa (M7B-W3.2B)", () => {
  it("fetchContactsPage faz exatamente uma requisição para a página solicitada", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ items: [contactB], page: 2, pageSize: 50, total: 75 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await realContactsApi.fetchContactsPage("tok-1", {
      page: 2,
      pageSize: 50,
    });

    expect(result.page).toBe(2);
    expect(result.items).toEqual([contactB]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]?.[0])).toContain(
      "/contacts?page=2&pageSize=50&view=all",
    );
  });

  it("fetchContacts preserva a compatibilidade e agrega todas as páginas", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const secondPage = String(url).includes("page=2");
      return Promise.resolve(
        new Response(
          JSON.stringify({
            items: [secondPage ? contactB : contact],
            page: secondPage ? 2 : 1,
            pageSize: 1,
            total: 2,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await realContactsApi.fetchContacts("tok-1", 1);

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(result.items).toEqual([contact, contactB]);
    expect(result.total).toBe(2);
  });

  it("não antecipa outras páginas; navegação e filtro pedem somente a página escolhida", async () => {
    apiMock.fetchContactsPage.mockImplementation(
      (_token: string, params: { page?: number }) =>
        Promise.resolve(
          params.page === 2
            ? { items: [contactB], page: 2, pageSize: 1, total: 2 }
            : { items: [contact], page: 1, pageSize: 1, total: 2 },
        ),
    );

    act(() => {
      root.render(h(ContatosScreen, {}));
    });
    await flush();

    // Mesmo sabendo que há duas páginas, a tela não busca a segunda em loop.
    expect(apiMock.fetchContactsPage).toHaveBeenCalledTimes(1);
    expect(apiMock.fetchContactsPage).toHaveBeenNthCalledWith(1, "tok-1", {
      page: 1,
      pageSize: 50,
      view: "all",
    });
    expect(container.textContent).toContain("Página 1 de 2");
    expect(tableText()).toContain("Ana Souza");

    act(() => {
      findButton("Próxima")!.click();
    });
    await flush();

    expect(apiMock.fetchContactsPage).toHaveBeenCalledTimes(2);
    expect(apiMock.fetchContactsPage).toHaveBeenNthCalledWith(2, "tok-1", {
      page: 2,
      pageSize: 50,
      view: "all",
    });
    expect(container.textContent).toContain("Página 2 de 2");
    expect(tableText()).toContain("Beatriz Lima");
    expect(tableText()).not.toContain("Ana Souza");

    const visitantesTab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(
      (button) => button.textContent!.includes("Visitantes"),
    )!;
    act(() => visitantesTab.click());
    await flush();

    expect(apiMock.fetchContactsPage).toHaveBeenCalledTimes(3);
    expect(apiMock.fetchContactsPage).toHaveBeenNthCalledWith(3, "tok-1", {
      page: 1,
      pageSize: 50,
      view: "visitante",
    });
    expect(container.textContent).toContain("Página 1 de 2");
    expect(dashboardMock.fetchCells).toHaveBeenCalledTimes(1);
  });

  it("não exibe linhas da aba anterior enquanto o novo filtro carrega ou falha", async () => {
    let rejectVisitors!: (reason: unknown) => void;
    apiMock.fetchContactsPage
      .mockResolvedValueOnce({ items: [contact], page: 1, pageSize: 50, total: 1 })
      .mockImplementationOnce(
        () =>
          new Promise((_resolve, reject) => {
            rejectVisitors = reject;
          }),
      );

    act(() => root.render(h(ContatosScreen, {})));
    await flush();
    expect(tableText()).toContain("Ana Souza");

    const visitantesTab = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find(
      (button) => button.textContent!.includes("Visitantes"),
    )!;
    act(() => visitantesTab.click());
    await act(async () => {
      await Promise.resolve();
    });

    expect(container.querySelector(".skeleton")).not.toBeNull();
    expect(container.textContent).not.toContain("Ana Souza");

    await act(async () => {
      rejectVisitors(new ApiError(503, "Serviço temporariamente indisponível"));
    });
    expect(container.querySelector("[role='alert']")?.textContent).toContain(
      "Serviço temporariamente indisponível",
    );
    expect(container.textContent).not.toContain("Ana Souza");
  });

  it("deep-link arquivado fora da página preserva o estado e não cria linha extra", async () => {
    apiMock.fetchContactsPage.mockResolvedValue({
      items: [contact],
      page: 1,
      pageSize: 50,
      total: 75,
    });
    apiMock.fetchContactDetail.mockResolvedValue({
      ...contactB,
      faixaEtaria: null,
      endereco: null,
      celulaNome: null,
      liderNome: null,
      arquivada: true,
      consentimento: true,
      optout: false,
      origem: "whatsapp",
      primeiroContato: null,
      criadoEm: null,
    });

    act(() => {
      root.render(h(ContatosScreen, { selectedId: "p2" }));
    });
    await flush(5);

    expect(apiMock.fetchContactDetail).toHaveBeenCalledTimes(1);
    expect(apiMock.fetchContactDetail).toHaveBeenCalledWith("tok-1", "p2");
    expect(container.querySelectorAll(".data-table tbody tr")).toHaveLength(1);
    expect(tableText()).toContain("Ana Souza");
    expect(tableText()).not.toContain("Beatriz Lima");
    expect(container.querySelector(".dash-side")?.textContent).toContain("Beatriz Lima");
    expect(container.querySelector(".dash-side")?.textContent).toContain("Arquivada");
    expect(container.querySelector(".dash-side")?.textContent).not.toContain("Arquivar pessoa");
  });

  it("preflight liberado: confirmar arquiva, mostra toast e substitui o botão pelo selo Arquivada", async () => {
    await renderScreenWithContact();
    expect(findButton("Arquivar pessoa")).toBeDefined();

    apiMock.fetchOffboardingPreflight.mockResolvedValue(preflight());
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();
    expect(apiMock.fetchOffboardingPreflight).toHaveBeenCalledWith("tok-1", "p1");
    expect(container.querySelector("textarea")).not.toBeNull();

    apiMock.archiveContact.mockResolvedValue(archiveResult({ arquivada_motivo: "Mudou de cidade" }));
    apiMock.fetchContactsPage.mockResolvedValue({
      items: [],
      page: 1,
      pageSize: 50,
      total: 0,
    });
    setTextarea("Mudou de cidade");
    act(() => {
      // O segundo botão "Arquivar pessoa" é o de confirmação, dentro do diálogo.
      [...container.querySelectorAll("button")]
        .filter((b) => b.textContent!.includes("Arquivar pessoa"))
        .at(-1)!
        .click();
    });
    await flush();

    expect(apiMock.archiveContact).toHaveBeenCalledWith("tok-1", "p1", "Mudou de cidade");
    expect(apiMock.fetchContactsPage).toHaveBeenCalledTimes(2);
    expect(container.querySelector(".toast")?.textContent).toContain("foi arquivada");
    // Sai da visão ativa, mas o deep-detail fica preservado fora da tabela.
    expect(tableText()).not.toContain("Ana Souza");
    expect(container.querySelector(".dash-side")?.textContent).toContain("Ana Souza");
    expect(container.querySelector(".toast")?.textContent).not.toBeUndefined();
    expect(findButton("Arquivar pessoa")).toBeUndefined();
    expect(container.textContent).toContain("Arquivada");
  });

  it("bloqueadores impedem confirmação: sem botão de confirmar, archiveContact nunca é chamado", async () => {
    await renderScreenWithContact();

    apiMock.fetchOffboardingPreflight.mockResolvedValue(
      preflight({
        pode_arquivar: false,
        bloqueadores: [
          {
            tipo: "celula_lider",
            rotulo: "Líder de célula ativa",
            recurso_id: "c1",
            recurso_nome: "Célula Central",
            acao_recomendada: "Troque o líder da célula antes de arquivar.",
          },
        ],
      }),
    );
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();

    expect(container.textContent).toContain("Não é possível arquivar agora");
    expect(container.textContent).toContain("Líder de célula ativa");
    // Dentro do diálogo só resta "Fechar" — o de confirmar nunca aparece
    // quando pode_arquivar=false (o botão da tela por trás continua existindo).
    const dialog = container.querySelector('[role="dialog"]')!;
    expect(
      [...dialog.querySelectorAll("button")].filter((b) => b.textContent === "Arquivar pessoa"),
    ).toHaveLength(0);
    expect(apiMock.archiveContact).not.toHaveBeenCalled();
  });

  it("403 no preflight aparece como erro sem quebrar a tela", async () => {
    await renderScreenWithContact();
    apiMock.fetchOffboardingPreflight.mockRejectedValue(
      new ApiError(403, "Você não tem permissão para arquivar pessoas."),
    );
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();
    expect(container.textContent).toContain("Você não tem permissão para arquivar pessoas.");
    expect(findButton("Tentar novamente")).toBeDefined();
  });

  it("409 (bloqueado) ao confirmar reexibe os bloqueadores sem fechar o diálogo", async () => {
    await renderScreenWithContact();
    apiMock.fetchOffboardingPreflight.mockResolvedValue(preflight({ pode_arquivar: true }));
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();

    const blocked = preflight({
      pode_arquivar: false,
      bloqueadores: [
        {
          tipo: "acesso_painel_ativo",
          rotulo: "Possui acesso ativo ao painel",
          recurso_id: "u1",
          recurso_nome: "ana@igreja.com",
          acao_recomendada: "Revogue o acesso ao painel (Equipe) antes de arquivar.",
        },
      ],
    });
    apiMock.archiveContact.mockRejectedValue(new ArchiveBlockedError(blocked));
    setTextarea("Mudou de cidade");
    act(() => {
      [...container.querySelectorAll("button")]
        .filter((b) => b.textContent!.includes("Arquivar pessoa"))
        .at(-1)!
        .click();
    });
    await flush();

    expect(container.textContent).toContain("Novos vínculos impedem o arquivamento agora");
    expect(container.textContent).toContain("Possui acesso ativo ao painel");
    // Diálogo segue aberto (não fechou em erro) e sem botão de confirmar.
    const dialog = container.querySelector('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(
      [...dialog!.querySelectorAll("button")].filter((b) => b.textContent === "Arquivar pessoa"),
    ).toHaveLength(0);
  });

  it("usuário não-admin: não vê o botão nem dispara o preflight", async () => {
    authState.roles = ["pastor"];
    await renderScreenWithContact();
    expect(findButton("Arquivar pessoa")).toBeUndefined();
    expect(apiMock.fetchOffboardingPreflight).not.toHaveBeenCalled();
  });

  it("404 no GET preflight aparece como erro sem quebrar a tela", async () => {
    await renderScreenWithContact();
    apiMock.fetchOffboardingPreflight.mockRejectedValue(new ApiError(404, "Pessoa não encontrada"));
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();
    expect(container.textContent).toContain("Pessoa não encontrada");
    expect(findButton("Tentar novamente")).toBeDefined();
  });

  it("403 no POST archive aparece como erro sem fechar o diálogo", async () => {
    await renderScreenWithContact();
    apiMock.fetchOffboardingPreflight.mockResolvedValue(preflight({ pode_arquivar: true }));
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();

    apiMock.archiveContact.mockRejectedValue(
      new ApiError(403, "Você não tem permissão para arquivar pessoas."),
    );
    setTextarea("Motivo qualquer");
    act(() => {
      findConfirmButton()!.click();
    });
    await flush();

    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.textContent).toContain("Você não tem permissão para arquivar pessoas.");
    expect(container.querySelector(".toast")).toBeNull();
  });

  it("404 no POST archive aparece como erro sem fechar o diálogo", async () => {
    await renderScreenWithContact();
    apiMock.fetchOffboardingPreflight.mockResolvedValue(preflight({ pode_arquivar: true }));
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();

    apiMock.archiveContact.mockRejectedValue(new ApiError(404, "Pessoa não encontrada"));
    setTextarea("Motivo qualquer");
    act(() => {
      findConfirmButton()!.click();
    });
    await flush();

    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.textContent).toContain("Pessoa não encontrada");
    expect(container.querySelector(".toast")).toBeNull();
  });

  it("erro de rede ao confirmar aparece como erro, sem fechar o diálogo nem perder o motivo digitado", async () => {
    await renderScreenWithContact();
    apiMock.fetchOffboardingPreflight.mockResolvedValue(preflight({ pode_arquivar: true }));
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();

    // Mesma ApiError(0, ...) que authedFetch lança quando o fetch() em si falha
    // (ver dashboard-api.ts) — não é um contrato inventado para o teste.
    apiMock.archiveContact.mockRejectedValue(
      new ApiError(0, "Falha de conexão. Verifique sua internet e tente novamente."),
    );
    setTextarea("Sem internet agora");
    act(() => {
      findConfirmButton()!.click();
    });
    await flush();

    expect(container.querySelector('[role="dialog"]')).not.toBeNull();
    expect(container.textContent).toContain("Falha de conexão");
    expect(container.querySelector<HTMLTextAreaElement>("textarea")?.value).toBe(
      "Sem internet agora",
    );
  });

  it("RACE: preflight de A atrasado não sobrescreve o de B (resposta de A chega depois da de B)", async () => {
    apiMock.fetchContactsPage.mockResolvedValue({
      items: [contact, contactB],
      page: 1,
      pageSize: 200,
      total: 2,
    });
    act(() => {
      root.render(h(ContatosScreen, {}));
    });
    await flush();

    let resolveA!: (v: OffboardingPreflight) => void;
    const deferredA = new Promise<OffboardingPreflight>((resolve) => {
      resolveA = resolve;
    });
    let resolveB!: (v: OffboardingPreflight) => void;
    const deferredB = new Promise<OffboardingPreflight>((resolve) => {
      resolveB = resolve;
    });
    apiMock.fetchOffboardingPreflight.mockImplementationOnce(() => deferredA);
    apiMock.fetchOffboardingPreflight.mockImplementationOnce(() => deferredB);

    // 1) abrir Pessoa A — 2) iniciar GET do preflight de A.
    clickRow("Ana Souza");
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();
    expect(apiMock.fetchOffboardingPreflight).toHaveBeenNthCalledWith(1, "tok-1", "p1");
    expect(container.querySelector("textarea")).toBeNull(); // ainda "Verificando…"

    // 3) fechar/trocar para Pessoa B (a requisição de A segue pendente).
    act(() => {
      findButton("Fechar")!.click();
    });
    await flush();
    clickRow("Beatriz Lima");

    // 4) iniciar GET do preflight de B.
    act(() => {
      findButton("Arquivar pessoa")!.click();
    });
    await flush();
    expect(apiMock.fetchOffboardingPreflight).toHaveBeenNthCalledWith(2, "tok-1", "p2");

    // 5) resposta de A chega DEPOIS da de B.
    const preflightB = preflight({ pessoa_id: "p2", pode_arquivar: true, bloqueadores: [] });
    const preflightA = preflight({
      pessoa_id: "p1",
      pode_arquivar: false,
      bloqueadores: [
        {
          tipo: "celula_lider",
          rotulo: "BLOQUEADOR-SO-DE-A",
          recurso_id: "c1",
          recurso_nome: "Célula de A",
          acao_recomendada: "Troque o líder antes de arquivar.",
        },
      ],
    });
    act(() => {
      resolveB(preflightB);
    });
    await flush();
    act(() => {
      resolveA(preflightA);
    });
    await flush();

    // O diálogo aberto é o de B: sem rastro do bloqueador de A, formulário liberado.
    expect(container.textContent).not.toContain("BLOQUEADOR-SO-DE-A");
    expect(container.textContent).not.toContain("Não é possível arquivar agora");
    const dialog = container.querySelector('[role="dialog"]')!;
    expect(dialog.textContent).toContain("Beatriz Lima");
    // Um bloqueador de A nunca pode habilitar/desabilitar o arquivamento de B:
    // aqui o botão de confirmar existe porque B (não A) está liberada.
    const confirmBtn = findConfirmButton();
    expect(confirmBtn).toBeDefined();

    apiMock.archiveContact.mockResolvedValue(
      archiveResult({ pessoa_id: "p2", arquivada_motivo: "Motivo B" }),
    );
    setTextarea("Motivo B");
    act(() => {
      confirmBtn!.click();
    });
    await flush();
    expect(apiMock.archiveContact).toHaveBeenCalledWith("tok-1", "p2", "Motivo B");
    expect(apiMock.archiveContact).not.toHaveBeenCalledWith(
      "tok-1",
      "p1",
      expect.anything(),
    );
  });
});
