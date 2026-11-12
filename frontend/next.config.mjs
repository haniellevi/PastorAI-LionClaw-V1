import { fileURLToPath } from "node:url";

import { buildContentSecurityPolicy } from "./src/lib/csp.mjs";

const projectRoot = fileURLToPath(new URL(".", import.meta.url));

const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: "frame-ancestors 'none'",
  },
  {
    key: "Referrer-Policy",
    value: "strict-origin-when-cross-origin",
  },
  {
    key: "Permissions-Policy",
    value: "camera=(), geolocation=(), microphone=(self)",
  },
  {
    // Modo de teste: só avisa no console do navegador, não bloqueia. Ver src/lib/csp.mjs.
    key: "Content-Security-Policy-Report-Only",
    value: buildContentSecurityPolicy({
      apiUrl: process.env.NEXT_PUBLIC_API_URL,
      dev: process.env.NODE_ENV === "development",
    }),
  },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  outputFileTracingRoot: projectRoot,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

export default nextConfig;
