import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchCells,
  fetchRemainingWorkQueuePages,
  fetchWorkQueue,
  fetchWorkQueuePage,
} from "./dashboard-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

const item = (id: string) => ({
  id,
  tipo: "visitante",
  titulo: id,
  contexto: null,
  status: "aberto",
  pessoaId: null,
  responsavelId: null,
  prioridade: 1,
  canMessage: false,
  prazo: null,
});

function queuePage(ids: string[], page: number, pageSize: number, total: number) {
  return Response.json({ items: ids.map(item), page, pageSize, total });
}

describe("fetchWorkQueue", () => {
  it("compara duas coletas integrais antes de confirmar um snapshot estável", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(queuePage(["q1"], 1, 1, 2))
      .mockResolvedValueOnce(queuePage(["q2"], 2, 1, 2))
      .mockResolvedValueOnce(queuePage(["q1"], 1, 1, 2))
      .mockResolvedValueOnce(queuePage(["q2"], 2, 1, 2));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchWorkQueue("tok-stable", 1);

    expect(result.items.map((entry) => entry.id)).toEqual(["q1", "q2"]);
    expect(result.total).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/work-queue?page=1&pageSize=1",
      expect.objectContaining({ cache: "reload" }),
    );
    expect(
      fetchMock.mock.calls
        .slice(1)
        .every(([, init]) => (init as RequestInit).cache === "reload"),
    ).toBe(true);
  });

  it("libera a página 1 antes das coletas integrais e deduplica IDs", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q2", "q3"], 2, 2, 4))
      .mockResolvedValueOnce(queuePage(["q4"], 3, 2, 4))
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q4"], 2, 2, 4));
    vi.stubGlobal("fetch", fetchMock);

    const firstPage = await fetchWorkQueuePage("tok-progressive", 1, 2);

    expect(firstPage.items.map((entry) => entry.id)).toEqual(["q1", "q2"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const remainder = await fetchRemainingWorkQueuePages(
      "tok-progressive",
      firstPage,
    );

    expect(remainder.items.map((entry) => entry.id)).toEqual(["q3", "q4"]);
    expect(remainder.firstPage?.items.map((entry) => entry.id)).toEqual([
      "q1",
      "q2",
    ]);
    expect(remainder.total).toBe(4);
    expect(fetchMock).toHaveBeenCalledTimes(5);
  });

  it("detecta troca compensada em página posterior com mesma primeira página e total", async () => {
    const fetchMock = vi
      .fn()
      // Snapshot A.
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q4"], 2, 2, 4))
      // Snapshot B: primeira página e total iguais, mas q4 foi trocado por q5.
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q5"], 2, 2, 4))
      // Nova coleta confirma B integralmente.
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q5"], 2, 2, 4));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchWorkQueue("tok-compensated", 2);

    expect(result.items.map((entry) => entry.id)).toEqual([
      "q1",
      "q2",
      "q3",
      "q5",
    ]);
    expect(result.items.map((entry) => entry.id)).not.toContain("q4");
    expect(result.total).toBe(4);
    expect(fetchMock).toHaveBeenCalledTimes(6);
  });

  it("reinicia pela coleta nova quando uma inserção desloca os offsets", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q2", "q3"], 2, 2, 5))
      .mockResolvedValueOnce(queuePage(["q4"], 3, 2, 5))
      .mockResolvedValueOnce(queuePage(["q0", "q1"], 1, 2, 5))
      .mockResolvedValueOnce(queuePage(["q2", "q3"], 2, 2, 5))
      .mockResolvedValueOnce(queuePage(["q4"], 3, 2, 5))
      .mockResolvedValueOnce(queuePage(["q0", "q1"], 1, 2, 5))
      .mockResolvedValueOnce(queuePage(["q2", "q3"], 2, 2, 5))
      .mockResolvedValueOnce(queuePage(["q4"], 3, 2, 5));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchWorkQueue("tok-insert", 2);

    expect(result.items.map((entry) => entry.id)).toEqual([
      "q0",
      "q1",
      "q2",
      "q3",
      "q4",
    ]);
    expect(result.total).toBe(5);
    expect(fetchMock).toHaveBeenCalledTimes(9);
  });

  it("reinicia pela coleta nova quando uma remoção encurta a fila", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q4"], 2, 2, 3))
      .mockResolvedValueOnce(queuePage([], 3, 2, 3))
      .mockResolvedValueOnce(queuePage(["q2", "q3"], 1, 2, 3))
      .mockResolvedValueOnce(queuePage(["q4"], 2, 2, 3))
      .mockResolvedValueOnce(queuePage(["q2", "q3"], 1, 2, 3))
      .mockResolvedValueOnce(queuePage(["q4"], 2, 2, 3));
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchWorkQueue("tok-remove", 2);

    expect(result.items.map((entry) => entry.id)).toEqual(["q2", "q3", "q4"]);
    expect(result.total).toBe(3);
    expect(fetchMock).toHaveBeenCalledTimes(7);
  });

  it("degrada após três comparações integrais persistentemente instáveis", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q4"], 2, 2, 4))
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q5"], 2, 2, 4))
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q6"], 2, 2, 4))
      .mockResolvedValueOnce(queuePage(["q1", "q2"], 1, 2, 4))
      .mockResolvedValueOnce(queuePage(["q3", "q7"], 2, 2, 4));
    vi.stubGlobal("fetch", fetchMock);

    const result = fetchWorkQueue("tok-unstable", 2);

    await expect(result).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: expect.stringContaining("A primeira página permanece disponível"),
    });
    expect(fetchMock).toHaveBeenCalledTimes(8);
  });
});

describe("fetchCells", () => {
  it("percorre todas as páginas sem truncar a lista de vínculo", async () => {
    const cell = (id: string) => ({
      id,
      nome: id,
      liderId: null,
      diaReuniao: null,
      horario: null,
      coberturaEspiritual: "Pastor",
      ativo: true,
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({ items: [cell("c1")], page: 1, pageSize: 1, total: 2 }),
      )
      .mockResolvedValueOnce(
        Response.json({ items: [cell("c2")], page: 2, pageSize: 1, total: 2 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchCells("tok-cells", 1);

    expect(result.items.map((entry) => entry.id)).toEqual(["c1", "c2"]);
    expect(result.total).toBe(2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/cells?page=2&pageSize=1",
      expect.any(Object),
    );
  });
});
