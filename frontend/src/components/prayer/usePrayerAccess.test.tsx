// @vitest-environment jsdom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { usePrayerAccess } from "./usePrayerAccess";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
it("never keeps a prior account capability while the next account loads", async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(
      new Response(JSON.stringify({ allowed: true }), { status: 200 }),
    );
  vi.stubGlobal("fetch", fetch);
  const element = document.createElement("div");
  document.body.appendChild(element);
  const root = createRoot(element);
  function Probe({ token }: { token: string }) {
    const access = usePrayerAccess(token);
    return (
      <p>
        {access === true ? "allowed" : access === false ? "denied" : "loading"}
      </p>
    );
  }
  try {
    await act(async () => root.render(<Probe token="account-a" />));
    expect(element.textContent).toBe("allowed");
    let resolve!: (value: Response) => void;
    fetch.mockReturnValueOnce(
      new Promise<Response>((r) => {
        resolve = r;
      }),
    );
    await act(async () => root.render(<Probe token="account-b" />));
    expect(element.textContent).toBe("loading");
    await act(async () =>
      resolve(
        new Response(JSON.stringify({ allowed: false }), { status: 200 }),
      ),
    );
    expect(element.textContent).toBe("denied");
  } finally {
    await act(async () => root.unmount());
    element.remove();
    vi.unstubAllGlobals();
  }
});
