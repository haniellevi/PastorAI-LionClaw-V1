import { describe, expect, it } from "vitest";

import nextConfig from "./next.config.mjs";
import { buildContentSecurityPolicy } from "./src/lib/csp.mjs";

async function configuredHeaders() {
  expect(nextConfig.headers).toBeTypeOf("function");
  return nextConfig.headers();
}

describe("Next security headers", () => {
  it("targets every response resolved through the configured route matcher", async () => {
    const routes = await configuredHeaders();

    expect(routes).toHaveLength(1);
    expect(routes[0]?.source).toBe("/:path*");
  });

  it("hardens browser boundaries without restricting Next resources", async () => {
    const [route] = await configuredHeaders();
    const headers = Object.fromEntries(
      route.headers.map(({ key, value }) => [key, value]),
    );

    expect(headers).toEqual({
      "Content-Security-Policy": "frame-ancestors 'none'",
      "Referrer-Policy": "strict-origin-when-cross-origin",
      "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
      "Content-Security-Policy-Report-Only": buildContentSecurityPolicy({
        apiUrl: process.env.NEXT_PUBLIC_API_URL,
      }),
    });
  });

  it("keeps the full CSP in report-only mode, never blocking yet", async () => {
    const [route] = await configuredHeaders();
    const enforced = route.headers.find(({ key }) => key === "Content-Security-Policy");

    // O cabeçalho que bloqueia continua só com frame-ancestors.
    expect(enforced?.value).toBe("frame-ancestors 'none'");
  });
});
