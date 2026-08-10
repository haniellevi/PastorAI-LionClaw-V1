import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const nextBin = fileURLToPath(
  new URL("./node_modules/next/dist/bin/next", import.meta.url),
);
const expectedHeaders = {
  "content-security-policy": "frame-ancestors 'none'",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), geolocation=(), microphone=(self)",
};

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      assert(address && typeof address === "object");
      const { port } = address;
      server.close((error) => (error ? reject(error) : resolve(port)));
    });
  });
}

function request(port, path, host = "app.igreja12.com.br") {
  return new Promise((resolve, reject) => {
    const req = http.request(
      {
        hostname: "127.0.0.1",
        port,
        path,
        method: "GET",
        headers: { Host: host, Connection: "close" },
      },
      (res) => {
        const chunks = [];
        res.on("data", (chunk) => chunks.push(chunk));
        res.on("end", () => {
          resolve({
            status: res.statusCode,
            headers: res.headers,
            body: Buffer.concat(chunks).toString("utf8"),
          });
        });
      },
    );
    req.setTimeout(5_000, () => req.destroy(new Error("HTTP timeout")));
    req.once("error", reject);
    req.end();
  });
}

function assertSecurityHeaders(response, label) {
  for (const [name, value] of Object.entries(expectedHeaders)) {
    assert.equal(response.headers[name], value, `${label}: header ${name}`);
  }
}

async function waitUntilReady(child, port, logs) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`Next encerrou antes do smoke:\n${logs.join("")}`);
    }
    try {
      const response = await request(port, "/");
      if (response.status === 200) return response;
    } catch {
      // O socket ainda não está pronto; nova tentativa curta abaixo.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Next não ficou pronto em 60s:\n${logs.join("")}`);
}

const port = await freePort();
const logs = [];
const child = spawn(
  process.execPath,
  [nextBin, "start", "-H", "127.0.0.1", "-p", String(port)],
  {
    cwd: frontendRoot,
    env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
child.stdout.on("data", (chunk) => logs.push(chunk.toString()));
child.stderr.on("data", (chunk) => logs.push(chunk.toString()));

try {
  const appPage = await waitUntilReady(child, port, logs);
  assertSecurityHeaders(appPage, "app page");

  for (const host of ["admin.igreja12.com.br", "painel.igreja12.com.br"]) {
    const surface = await request(port, "/", host);
    assert.equal(surface.status, 200, `${host}: status`);
    assertSecurityHeaders(surface, host);
  }

  const asset = await request(port, "/icon.svg");
  assert.equal(asset.status, 200, "public asset: status");
  assertSecurityHeaders(asset, "public asset");

  const chunkPath = appPage.body.match(
    /(?:src|href)="([^"?]*\/_next\/static\/[^"?]+\.(?:js|css))(?:\?[^" ]*)?"/,
  )?.[1];
  assert(chunkPath, "a página precisa referenciar ao menos um chunk Next");
  const chunk = await request(port, chunkPath);
  assert.equal(chunk.status, 200, "Next chunk: status");
  assertSecurityHeaders(chunk, "Next chunk");

  // O redirect de normalização é gerado pelo Next antes dos headers de rota.
  // Não prometemos cobertura nele; apenas garantimos status/localização e que
  // uma futura mudança nunca deixe uma política parcial entre os três headers.
  const redirect = await request(port, "/privacidade/");
  assert.equal(redirect.status, 308, "normalization redirect: status");
  assert.equal(redirect.headers.location, "/privacidade");
  const redirectHeaderCount = Object.keys(expectedHeaders).filter(
    (name) => redirect.headers[name] !== undefined,
  ).length;
  assert(
    redirectHeaderCount === 0 || redirectHeaderCount === 3,
    "normalization redirect não pode receber apenas parte da política",
  );
  if (redirectHeaderCount === 3) {
    assertSecurityHeaders(redirect, "normalization redirect");
  }

  console.log(
    `SECURITY_HEADERS_RUNTIME_OK pages=3 asset=1 chunk=1 redirect=308 ` +
      `redirect_headers=${redirectHeaderCount === 3 ? "presentes" : "fora_da_cobertura"}`,
  );
} finally {
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}
