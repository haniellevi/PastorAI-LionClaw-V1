import { afterEach, describe, expect, it, vi } from "vitest";

import { getLedCellsTodayContext } from "./cells-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getLedCellsTodayContext", () => {
  it("agrega todas as células lideradas e escolhe a próxima reunião real", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json([
          { id: "cell-b", nome: "Célula B" },
          { id: "cell-a", nome: "Célula A" },
        ]),
      )
      .mockResolvedValueOnce(
        Response.json([
          {
            id: "meeting-a",
            celulaId: "cell-a",
            data: "2026-08-13",
            hora: "20:00",
            tema: "Tema A",
            status: "planejada",
          },
        ]),
      )
      .mockResolvedValueOnce(
        Response.json([
          {
            id: "meeting-b-past",
            celulaId: "cell-b",
            data: "2026-08-10",
            hora: "19:30",
            tema: "Tema passado",
            status: "planejada",
          },
          {
            id: "meeting-b-next",
            celulaId: "cell-b",
            data: "2026-08-12",
            hora: "19:30",
            tema: "Tema B",
            status: "planejada",
          },
        ]),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await getLedCellsTodayContext(
      "tok-led-multiple",
      new Date("2026-08-11T12:00:00"),
    );

    expect(result.cells.map((cell) => cell.id)).toEqual(["cell-a", "cell-b"]);
    expect(result.meeting).toMatchObject({
      id: "meeting-b-next",
      celula_id: "cell-b",
      tema: "Célula B: Tema B",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/cells/cell-a/reunioes",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/cells/cell-b/reunioes",
      expect.any(Object),
    );
  });

  it("mantém desempate determinístico pela célula quando os horários coincidem", async () => {
    const sameSlot = (id: string, cellId: string, tema: string) => ({
      id,
      celulaId: cellId,
      data: "2026-08-12",
      hora: "19:30",
      tema,
      status: "planejada",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json([
          { id: "cell-b", nome: "Célula B" },
          { id: "cell-a", nome: "Célula A" },
        ]),
      )
      .mockResolvedValueOnce(Response.json([sameSlot("meeting-a", "cell-a", "A")]))
      .mockResolvedValueOnce(Response.json([sameSlot("meeting-b", "cell-b", "B")]));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getLedCellsTodayContext(
      "tok-led-tie",
      new Date("2026-08-11T12:00:00"),
    );

    expect(result.meeting?.id).toBe("meeting-a");
    expect(result.meeting?.celula_id).toBe("cell-a");
  });
});
