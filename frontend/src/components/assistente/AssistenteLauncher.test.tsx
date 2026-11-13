// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { AssistantError, SessionExpiredError } from "@/lib/api";

import { AssistentePainel } from "./AssistenteLauncher";

const mocks = vi.hoisted(() => ({ send: vi.fn() }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  sendAssistantMessage: mocks.send,
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let dispose = () => {};
const onExpired = vi.fn();

async function mount(canOpen: (tela: string) => boolean = () => true) {
  const el = document.createElement("div");
  document.body.append(el);
  const root = createRoot(el);
  dispose = () => {
    act(() => root.unmount());
    el.remove();
  };
  await act(async () =>
    root.render(
      <AssistentePainel
        token="sintetico"
        tenantId="igreja-1"
        canOpenScreen={canOpen}
        onExpired={onExpired}
      />,
    ),
  );
}

const dialog = () => document.querySelector<HTMLElement>('[role="dialog"]');
function button(label: string) {
  const found = [...document.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === label || b.getAttribute("aria-label") === label,
  );
  expect(found, label).toBeDefined();
  return found as HTMLButtonElement;
}
async function openDialog() {
  await act(async () => button("Abrir assistente do sistema").click());
  expect(dialog()).not.toBeNull();
}
async function type(value: string) {
  const field = document.querySelector("textarea") as HTMLTextAreaElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(
      field,
      value,
    );
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}
async function submit() {
  await act(async () => button("Enviar").click());
}

beforeEach(() => {
  mocks.send.mockReset();
  onExpired.mockReset();
});
afterEach(() => dispose());

it("abre fechado, mostra o estado vazio e o foco inicial na pergunta", async () => {
  await mount();
  expect(dialog()).toBeNull();
  await openDialog();
  expect(dialog()!.textContent).toContain("Nenhuma pergunta ainda");
  expect(document.activeElement).toBe(document.querySelector("textarea"));
  expect(button("Enviar").disabled).toBe(true);
});

it("envia a pergunta, mostra carregando e depois a resposta com telas permitidas", async () => {
  let resolve!: (v: { resposta: string; telasSugeridas: string[] }) => void;
  mocks.send.mockReturnValue(new Promise((r) => (resolve = r)));
  await mount((tela) => tela === "dashboard");
  await openDialog();
  await type("  onde ficam as pendências?  ");
  await submit();

  expect(mocks.send).toHaveBeenCalledWith(
    "sintetico",
    "igreja-1",
    "onde ficam as pendências?",
    expect.any(AbortSignal),
  );
  expect(dialog()!.textContent).toContain("O assistente está respondendo…");
  expect(button("Carregando…").disabled).toBe(true);
  expect((document.querySelector("textarea") as HTMLTextAreaElement).value).toBe("");

  await act(async () =>
    resolve({ resposta: "Veja o painel.", telasSugeridas: ["dashboard", "permissoes"] }),
  );
  const text = dialog()!.textContent ?? "";
  expect(text).toContain("onde ficam as pendências?");
  expect(text).toContain("Veja o painel.");
  expect(text).not.toContain("O assistente está respondendo…");
  const links = [...dialog()!.querySelectorAll<HTMLAnchorElement>(".assistente-telas a")];
  expect(links.map((a) => a.getAttribute("href"))).toEqual(["#dashboard"]);
});

it("serviço indisponível mostra erro e 'Tentar novamente' reenvia sem duplicar a pergunta", async () => {
  mocks.send
    .mockRejectedValueOnce(
      new AssistantError("unavailable", "O assistente está indisponível agora."),
    )
    .mockResolvedValueOnce({ resposta: "Agora foi.", telasSugeridas: [] });
  await mount();
  await openDialog();
  await type("oi");
  await submit();

  expect(dialog()!.querySelector('[role="alert"]')!.textContent).toContain("indisponível");
  await act(async () => button("Tentar novamente").click());

  expect(mocks.send).toHaveBeenCalledTimes(2);
  expect(dialog()!.querySelector('[role="alert"]')).toBeNull();
  const text = dialog()!.textContent ?? "";
  expect(text).toContain("Agora foi.");
  expect(text.match(/oi/g)?.length).toBeGreaterThan(0);
  expect(dialog()!.querySelectorAll(".assistente-msg--usuario")).toHaveLength(1);
});

it("sem permissão (403) bloqueia o campo e o envio e não oferece repetir", async () => {
  mocks.send.mockRejectedValue(
    new AssistantError("forbidden", "Seu acesso não permite usar o assistente."),
  );
  await mount();
  await openDialog();
  await type("quero tudo");
  await submit();

  expect(dialog()!.textContent).toContain("Seu acesso não permite usar o assistente.");
  expect((document.querySelector("textarea") as HTMLTextAreaElement).disabled).toBe(true);
  expect(button("Enviar").disabled).toBe(true);
  expect(
    [...document.querySelectorAll("button")].some((b) => b.textContent === "Tentar novamente"),
  ).toBe(false);
});

it("sessão expirada avisa o shell e não mostra erro na conversa", async () => {
  mocks.send.mockRejectedValue(new SessionExpiredError());
  await mount();
  await openDialog();
  await type("oi");
  await submit();
  expect(onExpired).toHaveBeenCalledTimes(1);
  expect(dialog()!.querySelector('[role="alert"]')).toBeNull();
});

it("mantém o histórico ao fechar e reabrir", async () => {
  mocks.send.mockResolvedValue({ resposta: "Resposta guardada.", telasSugeridas: [] });
  await mount();
  await openDialog();
  await type("primeira");
  await submit();
  await act(async () => button("Fechar").click());
  expect(dialog()).toBeNull();
  await openDialog();
  expect(dialog()!.textContent).toContain("Resposta guardada.");
});
