import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import http from "node:http";
import net from "node:net";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const nextBin = fileURLToPath(new URL("./node_modules/next/dist/bin/next", import.meta.url));
const expectedHeaders = {
  "content-security-policy": "frame-ancestors 'none'",
  "referrer-policy": "strict-origin-when-cross-origin",
  "permissions-policy": "camera=(), geolocation=(), microphone=(self)",
};
// O valor da CSP em modo de teste depende da URL da API fixada no build; o
// smoke exige o cabeçalho, as diretivas que fecham o painel e o mesmo valor
// em todas as respostas, sem recalcular a partir do ambiente deste passo.
const REPORT_ONLY = "content-security-policy-report-only";
const requiredReportOnlyDirectives = [
  "default-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
];
const policyHeaderNames = [...Object.keys(expectedHeaders), REPORT_ONLY];
let reportOnlyValue = null;

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
  const reportOnly = response.headers[REPORT_ONLY];
  assert.equal(typeof reportOnly, "string", `${label}: header ${REPORT_ONLY}`);
  const directives = reportOnly.split(";").map((part) => part.trim());
  for (const directive of requiredReportOnlyDirectives) {
    assert(directives.includes(directive), `${label}: ${REPORT_ONLY} sem ${directive}`);
  }
  reportOnlyValue ??= reportOnly;
  assert.equal(reportOnly, reportOnlyValue, `${label}: ${REPORT_ONLY} diferente`);
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
const child = spawn(process.execPath, [nextBin, "start", "-H", "127.0.0.1", "-p", String(port)], {
  cwd: frontendRoot,
  env: { ...process.env, NEXT_TELEMETRY_DISABLED: "1" },
  stdio: ["ignore", "pipe", "pipe"],
});
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
  const redirectHeaderCount = policyHeaderNames.filter(
    (name) => redirect.headers[name] !== undefined,
  ).length;
  assert(
    redirectHeaderCount === 0 || redirectHeaderCount === policyHeaderNames.length,
    "normalization redirect não pode receber apenas parte da política",
  );
  if (redirectHeaderCount === policyHeaderNames.length) {
    assertSecurityHeaders(redirect, "normalization redirect");
  }

  console.log(
    `SECURITY_HEADERS_RUNTIME_OK pages=3 asset=1 chunk=1 redirect=308 ` +
      `redirect_headers=${redirectHeaderCount === policyHeaderNames.length ? "presentes" : "fora_da_cobertura"}`,
  );
} finally {
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}
