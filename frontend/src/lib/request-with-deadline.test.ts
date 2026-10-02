import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchWithDeadline, waitForRequest } from "./request-with-deadline";
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
describe("operation deadline", () => {
  it("bounds the body after fast headers", async () => {
    vi.useFakeTimers();
    const response = Response.json({});
    vi.spyOn(response, "json").mockImplementation(() => new Promise(() => {}));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const bounded = await fetchWithDeadline("http://example.test/body",undefined,100);
    const rejected = expect(bounded.json()).rejects.toMatchObject({name:"TimeoutError"});
    await vi.advanceTimersByTimeAsync(101);
    await rejected;
  });
  it("attaches a rejection handler even when a consumer is already aborted", async () => {
    const controller = new AbortController(); controller.abort();
    let reject!: (reason: Error) => void;
    const pending = new Promise<void>((_resolve, done) => { reject = done; });
    const result = waitForRequest(pending,controller.signal);
    await expect(result).rejects.toMatchObject({name:"AbortError"});
    reject(new Error("underlying read failed later"));
    await new Promise(resolve => setTimeout(resolve,0));
  });
});

it("keeps caller cancellation attached after headers and aborts the network before body consumption",async()=>{
 const caller=new AbortController();
 let network!:AbortSignal;
 vi.stubGlobal("fetch",vi.fn(async(_input:RequestInfo | URL,init?:RequestInit)=>{network=init!.signal!;return Response.json({});}));
 const response=await fetchWithDeadline("http://example.test/body",{signal:caller.signal});
 caller.abort();expect(network.aborted).toBe(true);await expect(response.json()).rejects.toMatchObject({name:"AbortError"});
});
