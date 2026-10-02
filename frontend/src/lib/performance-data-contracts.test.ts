import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchCellsFull, getLedCellsTodayContext } from "./cells-api";
import { clearAuthedResponseCache } from "./dashboard-api";

afterEach(() => { vi.unstubAllGlobals(); clearAuthedResponseCache(); });

describe("performance read contracts", () => {
  it("preserves cells beyond the legacy first 200", async () => {
    const first = Array.from({ length: 200 }, (_, i) => ({ id: `cell-${i}`, nome: `Célula ${i}` }));
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json({items:first,total:201,page:1,pageSize:200})).mockResolvedValueOnce(Response.json({items:[{id:"cell-200",nome:"Última"}],total:201,page:2,pageSize:200}));
    vi.stubGlobal("fetch", fetchMock);
    const result = await fetchCellsFull("cells-complete");
    expect(result.items).toHaveLength(201);
    expect(result.items.at(-1)?.id).toBe("cell-200");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("uses authoritative leader-today once without downloading meeting history", async () => {
    const context = {cells:[{id:"cell-a",nome:"A"}],meeting:null};
    const fetchMock = vi.fn().mockResolvedValue(Response.json(context));
    vi.stubGlobal("fetch", fetchMock);
    expect(await getLedCellsTodayContext("led-server-clock")).toEqual(context);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toContain("/cells/me/led-today");
  });
  it("never falls back from a refused leader-today read", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null,{status:403}));
    vi.stubGlobal("fetch", fetchMock);
    await expect(getLedCellsTodayContext("led-refused")).rejects.toMatchObject({status:403});
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0]?.[0]).toContain("/cells/me/led-today");
  });
});
