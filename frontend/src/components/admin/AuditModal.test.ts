// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditModal } from "./AuditModal";

const { fetchAudit } = vi.hoisted(() => ({ fetchAudit: vi.fn() }));

vi.mock("@/lib/admin-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/admin-api")>();
  return { ...actual, fetchAudit };
});

declare global {
  // eslint-disable-next-line no-var
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function render() {
  act(() => {
    root.render(
      h(AuditModal, {
        token: "master-token",
        onClose: () => {},
        onExpired: () => {},
      }),
    );
  });
}

beforeEach(() => {
  Object.defineProperty(HTMLElement.prototype, "offsetParent", {
    configurable: true,
    get() {
      return (this as HTMLElement).parentElement;
    },
  });
  fetchAudit.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("AuditModal — responsividade e espera", () => {
  it("mostra a ampulheta acessível enquanto carrega", () => {
    fetchAudit.mockReturnValue(new Promise(() => {}));
    render();

    const loading = container.querySelector<HTMLElement>('[role="status"]')!;
    expect(loading.textContent).toContain("Carregando a auditoria…");
    expect(loading.querySelector(".spinner")).not.toBeNull();
  });

  it("usa o diálogo largo e fornece rótulos para os cartões no celular", async () => {
    fetchAudit.mockResolvedValue([
      {
        id: "audit-1",
        createdAt: "2026-08-07T18:00:00Z",
        acao: "editar",
        alvoNome: "Igreja Fortaleza",
        detalhe: { status: "ativa" },
        actorEmail: "admin@igreja12.com.br",
      },
    ]);

    render();
    await flush();

    expect(container.querySelector(".ds-dialog")?.classList.contains("admin-audit-dialog")).toBe(true);
    expect(container.querySelector(".ds-dialog-desc")?.textContent).toContain("Últimas 100 ações");
    expect(
      [...container.querySelectorAll("tbody td")].map((cell) => cell.getAttribute("data-label")),
    ).toEqual(["Quando", "Ação", "Alvo", "Por"]);
    expect(container.textContent).toContain("Editou igreja");
    expect(container.textContent).toContain("admin@igreja12.com.br");
  });

  it("mantém os dados visíveis e sinaliza a atualização no botão", async () => {
    fetchAudit.mockResolvedValueOnce([]);
    const refresh = deferred<never[]>();
    fetchAudit.mockReturnValueOnce(refresh.promise);

    render();
    await flush();

    const update = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Atualizar"),
    )!;
    act(() => update.click());
    await flush();

    expect(container.textContent).toContain("Nenhuma ação registrada ainda.");
    expect(update.textContent).toContain("Atualizando…");
    expect(update.disabled).toBe(true);

    refresh.resolve([]);
    await flush();
  });
});
