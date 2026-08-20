import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchEvents, fetchUpcomingEvents } from "./events-api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("fetchEvents", () => {
  it("percorre todas as páginas para não esconder eventos futuros após o histórico", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({
          items: [
            {
              id: "e1",
              titulo: "Evento 1",
              data: "2026-08-10",
              hora: null,
              descricao: null,
              googleEventId: null,
              sincronizado: false,
            },
          ],
          page: 1,
          pageSize: 1,
          total: 2,
        }),
      )
      .mockResolvedValueOnce(
        Response.json({
          items: [
            {
              id: "e2",
              titulo: "Evento 2",
              data: "2026-08-12",
              hora: "20:00",
              descricao: null,
              googleEventId: null,
              sincronizado: false,
            },
          ],
          page: 2,
          pageSize: 1,
          total: 2,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchEvents("tok-1", 1);

    expect(result.items.map((item) => item.id)).toEqual(["e1", "e2"]);
    expect(result.total).toBe(2);
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/events?page=1&pageSize=1",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/events?page=2&pageSize=1",
      expect.any(Object),
    );
  });

  it("carrega o read model futuro do dashboard em uma única página", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      Response.json({
        items: [
          {
            id: "e-futuro",
            titulo: "Culto",
            data: "2026-08-12",
            hora: "20:00",
            descricao: null,
            googleEventId: null,
            sincronizado: false,
          },
        ],
        page: 1,
        pageSize: 6,
        total: 31,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchUpcomingEvents(
      "tok-dashboard",
      new Date(2026, 7, 11, 9, 0, 0),
    );

    expect(result.items.map((item) => item.id)).toEqual(["e-futuro"]);
    expect(result.total).toBe(31);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/events?page=1&pageSize=6&fromDate=2026-08-11",
      expect.any(Object),
    );
  });
});
