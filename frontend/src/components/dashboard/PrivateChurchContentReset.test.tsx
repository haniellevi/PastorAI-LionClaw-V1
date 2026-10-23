// @vitest-environment jsdom
import { act, createElement as h } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PrivateChurchContentReset } from "./PrivateChurchContentReset";

const api = vi.hoisted(() => ({ fetch: vi.fn(), clear: vi.fn() }));
vi.mock("@/lib/dashboard-api", async original => ({
  ...await original<typeof import("@/lib/dashboard-api")>(),
  authedFetch: api.fetch,
  clearAuthedResponseCache: api.clear,
}));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
const close = vi.fn();
const erased = vi.fn();
const sessionError = vi.fn();
const receipt = {
  id: "receipt-church-1", estado: "pendente", escopo: "igreja",
  camadas: { mensagens: { encontradas: 4, apagadas: 4, pendentes: 0, falhas: 0 } },
};

beforeEach(() => {
  vi.resetAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

async function render(open = true) {
  await act(async () => root.render(h(PrivateChurchContentReset, {
    open, token: "synthetic", churchName: "Igreja sintética", onClose: close,
    onErased: erased, onSessionError: sessionError,
  })));
}

function button(label: string) {
  return [...container.querySelectorAll("button")].find(item => item.textContent?.includes(label))!;
}

async function setInput(index: number, value: string) {
  const input = container.querySelectorAll("input")[index]!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

it("requires exact church name and phrase, then uses the private deletion receipt", async () => {
  await render();
  expect(button("Confirmar reset privado").disabled).toBe(true);
  await setInput(0, "igreja sintética");
  await setInput(1, "EXCLUIR CONTEUDO PRIVADO DA IGREJA");
  expect(button("Confirmar reset privado").disabled).toBe(true);
  await setInput(0, "Igreja sintética");
  expect(button("Confirmar reset privado").disabled).toBe(false);
  api.fetch.mockResolvedValueOnce(Response.json(receipt));
  await act(async () => button("Confirmar reset privado").click());
  expect(api.fetch).toHaveBeenCalledWith("synthetic", "/igreja/private-content", {
    method: "DELETE",
    body: expect.any(String),
  });
  const payload = JSON.parse(api.fetch.mock.calls[0]![2].body);
  expect(payload).toMatchObject({
    nome_igreja: "Igreja sintética",
    confirmacao: "EXCLUIR CONTEUDO PRIVADO DA IGREJA",
  });
  expect(payload.operation_id).toMatch(/^[0-9a-f-]{36}$/i);
  expect(container.textContent).toContain("Recibo cumulativo: receipt-church-1");
  expect(erased).toHaveBeenCalledTimes(1);
  expect(api.clear).toHaveBeenCalledTimes(1);
});

it("reuses the operation after an ambiguous failure and starts a distinct deliberate operation", async () => {
  await render();
  await setInput(0, "Igreja sintética");
  await setInput(1, "EXCLUIR CONTEUDO PRIVADO DA IGREJA");
  api.fetch.mockRejectedValueOnce(new Error("network"));
  await act(async () => button("Confirmar reset privado").click());
  const firstId = JSON.parse(api.fetch.mock.calls[0]![2].body).operation_id as string;
  expect(container.querySelector('[role="alert"]')?.textContent).toContain("repetição é segura");

  api.fetch.mockResolvedValueOnce(Response.json(receipt));
  await act(async () => button("Confirmar reset privado").click());
  expect(JSON.parse(api.fetch.mock.calls[1]![2].body).operation_id).toBe(firstId);

  await act(async () => button("Atualizar recibo").click());
  expect(api.fetch.mock.calls[2]![1]).toBe("/igreja/private-deletions/receipt-church-1");

  await act(async () => button("Iniciar novo reset").click());
  const operationLine = [...container.querySelectorAll("p")].find(item => item.textContent?.startsWith("Operação:"));
  expect(operationLine?.textContent).not.toContain(firstId);
  expect(button("Confirmar reset privado").disabled).toBe(true);
});
