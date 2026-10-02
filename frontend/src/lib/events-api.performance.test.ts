import {afterEach,expect,it,vi} from "vitest";
import {eventWindow,fetchEvents,fetchUpcomingEvents} from "./events-api";
import {clearAuthedResponseCache} from "./dashboard-api";
afterEach(()=>{vi.unstubAllGlobals();clearAuthedResponseCache();});
const recurring={id:"recurring",titulo:"Culto semanal sintético",data:null,recorrencia:"semanal"};
it("Calendar keeps undated recurrence when the server explicitly supports its window",async()=>{
 const fetchMock=vi.fn().mockResolvedValue(Response.json({items:[recurring],total:1,page:1,pageSize:200,includeUndatedSupported:true}));vi.stubGlobal("fetch",fetchMock);
 const result=await fetchEvents("new-calendar",200,{...eventWindow("mes",new Date(2026,9,2)),includeUndated:true});
 expect(result.items).toEqual([recurring]);expect(fetchMock).toHaveBeenCalledTimes(1);
 expect(fetchMock.mock.calls[0]?.[0]).toContain("fromDate=2026-10-01&toDate=2026-10-31&includeUndated=true");
});
it("old Calendar fallback reads every legacy page without fromDate and preserves recurrence after row200",async()=>{
 const rows=Array.from({length:200},(_,index)=>({id:`event-${index}`,data:"2026-10-02",titulo:"Evento sintético"}));
 const fetchMock=vi.fn().mockResolvedValueOnce(Response.json({items:[],total:0,page:1,pageSize:200})).mockResolvedValueOnce(Response.json({items:rows,total:201,page:1,pageSize:200})).mockResolvedValueOnce(Response.json({items:[recurring],total:201,page:2,pageSize:200}));vi.stubGlobal("fetch",fetchMock);
 const result=await fetchEvents("old-calendar",200,{fromDate:"2026-10-01",toDate:"2026-10-31",includeUndated:true});
 expect(result.items).toHaveLength(201);expect(result.items.at(-1)).toEqual(recurring);
 expect(fetchMock.mock.calls.slice(1).every(([input])=>!String(input).includes("fromDate"))).toBe(true);
 expect(fetchMock.mock.calls[2]?.[0]).toContain("page=2&pageSize=200");
});
it("Today remains a single dated page of six without Calendar's undated option",async()=>{
 const fetchMock=vi.fn().mockResolvedValue(Response.json({items:[],total:0,page:1,pageSize:6}));vi.stubGlobal("fetch",fetchMock);
 await fetchUpcomingEvents("today",new Date(2026,9,2));
 expect(fetchMock).toHaveBeenCalledTimes(1);expect(fetchMock.mock.calls[0]?.[0]).toContain("pageSize=6&fromDate=2026-10-02");expect(fetchMock.mock.calls[0]?.[0]).not.toContain("includeUndated");
});
