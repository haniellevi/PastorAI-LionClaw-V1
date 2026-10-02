/** Deadline covers headers and body. A cancellation never retries a write. */
export const REQUEST_TIMEOUT_MS = 20_000;

export function waitForRequest<T>(request: Promise<T>, signal?: AbortSignal | null): Promise<T> {
  if (!signal) return request;
  return new Promise<T>((resolve, reject) => {
    const abort = () => reject(signal.reason ?? new DOMException("Requisição cancelada.", "AbortError"));
    // Always handle source rejection, including a consumer that already left.
    request.then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
  });
}

const timeoutReason = () => new DOMException("A requisição demorou demais. Tente novamente.", "TimeoutError");

function protectBody(response: Response, controller: AbortController, deadline: number, cleanup: () => void): Response {
  const methods = new Set(["json", "text", "blob", "arrayBuffer", "formData", "bytes"]);
  return new Proxy(response, {
    get(target, key) {
      if (key === "clone") return () => protectBody(target.clone(), controller, deadline, cleanup);
      const value = Reflect.get(target, key, target);
      if (typeof key === "string" && methods.has(key) && typeof value === "function") {
        return async () => {
          if (Date.now() >= deadline && !controller.signal.aborted) controller.abort(timeoutReason());
          if (controller.signal.aborted) { cleanup(); throw controller.signal.reason; }
          // A clone may consume after another clone finished. Its body still has
          // the absolute operation budget, even when all network bytes arrived.
          const timer = setTimeout(() => controller.abort(timeoutReason()), Math.max(0,deadline-Date.now()));
          try { return await waitForRequest(value.call(target), controller.signal); }
          finally { clearTimeout(timer); cleanup(); }
        };
      }
      return typeof value === "function" ? value.bind(target) : value;
    },
  });
}

export async function fetchWithDeadline(input: RequestInfo | URL, init?: RequestInit, timeoutMs = REQUEST_TIMEOUT_MS): Promise<Response> {
  const deadline = Date.now() + timeoutMs;
  const controller = new AbortController();
  const caller = init?.signal;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cleanup = () => { if (timer !== undefined) clearTimeout(timer); caller?.removeEventListener("abort", abort); };
  const abort = () => { controller.abort(caller?.reason); cleanup(); };
  if (caller?.aborted) abort();
  else caller?.addEventListener("abort", abort, { once: true });
  timer = setTimeout(() => { controller.abort(timeoutReason()); cleanup(); }, timeoutMs);
  try {
    if (controller.signal.aborted) throw controller.signal.reason;
    const response = await waitForRequest(fetch(input, { ...init, signal: controller.signal }), controller.signal);
    if (!response.body) cleanup();
    return protectBody(response, controller, deadline, cleanup);
  } catch (error) { cleanup(); throw error; }
}
