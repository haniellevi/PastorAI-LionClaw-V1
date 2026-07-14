// @vitest-environment jsdom
/**
 * M7B-W3.2B — arquivamento de Pessoa integrado à tela #contatos:
 *  - admin abre o preflight, confirma com motivo e a tela reflete o sucesso
 *    (toast + selo "Arquivada", sem remover a pessoa da lista — nunca um
 *    hard delete visual);
 *  - preflight bloqueado nunca deixa confirmar;
 *  - 403 no preflight e 409 (bloqueado) na confirmação aparecem como erro,
 *    sem quebrar a tela;
 *  - usuário não-admin nem vê o botão nem dispara o preflight.
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
  fetchContacts: vi.fn(),
  fetchOffboardingPreflight: vi.fn(),
  archiveContact: vi.fn(),
}));

vi.mock("@/lib/contacts-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/contacts-api")>();
  return {
    ...actual,
    fetchContacts: apiMock.fetchContacts,
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
    fetchCells: vi.fn().mockResolvedValue({ items: [], page: 1, pageSize: 100, total: 0 }),
  };
});

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
  apiMock.fetchContacts.mockResolvedValue({
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
  apiMock.fetchContacts.mockReset();
  apiMock.fetchOffboardingPreflight.mockReset();
  apiMock.archiveContact.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("ContatosScreen — arquivamento de Pessoa (M7B-W3.2B)", () => {
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
    expect(container.querySelector(".toast")?.textContent).toContain("foi arquivada");
    // Pessoa continua na lista/detalhe (nunca some) — só o selo muda.
    expect(container.textContent).toContain("Ana Souza");
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
});
