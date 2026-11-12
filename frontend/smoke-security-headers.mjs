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
// A CSP em modo de teste sai do middleware, com nonce novo por documento.
// O smoke exige nas páginas as diretivas que fecham o painel, um nonce no
// script-src (sem 'unsafe-inline'), nonces diferentes entre acessos e o mesmo
// nonce em todas as tags <script> do HTML. Assets e chunks não passam pelo
// middleware: recebem só os três cabeçalhos fixos.
const REPORT_ONLY = "content-security-policy-report-only";
const requiredReportOnlyDirectives = [
  "default-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
];
const fixedHeaderNames = Object.keys(expectedHeaders);
const seenNonces = new Set();

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

function assertFixedHeaders(response, label) {
  for (const [name, value] of Object.entries(expectedHeaders)) {
    assert.equal(response.headers[name], value, `${label}: header ${name}`);
  }
}

function assertDocumentHeaders(response, label) {
  assertFixedHeaders(response, label);
  const reportOnly = response.headers[REPORT_ONLY];
  assert.equal(typeof reportOnly, "string", `${label}: header ${REPORT_ONLY}`);
  const directives = reportOnly.split(";").map((part) => part.trim());
  for (const directive of requiredReportOnlyDirectives) {
    assert(directives.includes(directive), `${label}: ${REPORT_ONLY} sem ${directive}`);
  }
  const scriptSrc = directives.find((directive) => directive.startsWith("script-src "));
  assert(scriptSrc, `${label}: ${REPORT_ONLY} sem script-src`);
  const nonce = scriptSrc.match(/'nonce-([^']+)'/)?.[1];
  assert(nonce, `${label}: script-src sem nonce`);
  assert(scriptSrc.includes("'strict-dynamic'"), `${label}: script-src sem 'strict-dynamic'`);
  assert(!scriptSrc.includes("'unsafe-inline'"), `${label}: script-src ainda com 'unsafe-inline'`);
  const styleSrcElem = directives.find((directive) => directive.startsWith("style-src-elem "));
  assert(styleSrcElem?.includes(`'nonce-${nonce}'`), `${label}: style-src-elem sem o nonce`);
  assert(!styleSrcElem.includes("'unsafe-inline'"), `${label}: style-src-elem com 'unsafe-inline'`);
  assert(
    directives.includes("style-src-attr 'unsafe-inline'"),
    `${label}: sem style-src-attr 'unsafe-inline'`,
  );
  assert(!seenNonces.has(nonce), `${label}: nonce repetido entre documentos`);
  seenNonces.add(nonce);

  const scripts = [...response.body.matchAll(/<script\b[^>]*>/g)].map(([tag]) => tag);
  assert(scripts.length > 0, `${label}: HTML sem <script>`);
  for (const tag of scripts) {
    assert(
      tag.includes(`nonce="${nonce}"`),
      `${label}: <script> sem o nonce do header: ${tag.slice(0, 80)}`,
    );
  }
  for (const [tag] of response.body.matchAll(/<style\b[^>]*>/g)) {
    assert(
      tag.includes(`nonce="${nonce}"`),
      `${label}: <style> inline sem o nonce: ${tag.slice(0, 80)}`,
    );
  }
  return scripts.length;
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
  let scripts = assertDocumentHeaders(appPage, "app page");

  const again = await request(port, "/");
  scripts += assertDocumentHeaders(again, "app page (2º acesso)");

  for (const host of ["admin.igreja12.com.br", "painel.igreja12.com.br"]) {
    const surface = await request(port, "/", host);
    assert.equal(surface.status, 200, `${host}: status`);
    scripts += assertDocumentHeaders(surface, host);
  }

  const asset = await request(port, "/icon.svg");
  assert.equal(asset.status, 200, "public asset: status");
  assertFixedHeaders(asset, "public asset");

  const chunkPath = appPage.body.match(
    /(?:src|href)="([^"?]*\/_next\/static\/[^"?]+\.(?:js|css))(?:\?[^" ]*)?"/,
  )?.[1];
  assert(chunkPath, "a página precisa referenciar ao menos um chunk Next");
  const chunk = await request(port, chunkPath);
  assert.equal(chunk.status, 200, "Next chunk: status");
  assertFixedHeaders(chunk, "Next chunk");

  // O redirect de normalização é gerado pelo Next antes dos headers de rota.
  // Não prometemos cobertura nele; apenas garantimos status/localização e que
  // uma futura mudança nunca deixe uma política parcial entre os headers fixos.
  const redirect = await request(port, "/privacidade/");
  assert.equal(redirect.status, 308, "normalization redirect: status");
  assert.equal(redirect.headers.location, "/privacidade");
  const redirectHeaderCount = fixedHeaderNames.filter(
    (name) => redirect.headers[name] !== undefined,
  ).length;
  assert(
    redirectHeaderCount === 0 || redirectHeaderCount === fixedHeaderNames.length,
    "normalization redirect não pode receber apenas parte da política",
  );
  if (redirectHeaderCount === fixedHeaderNames.length) {
    assertFixedHeaders(redirect, "normalization redirect");
  }

  console.log(
    `SECURITY_HEADERS_RUNTIME_OK pages=4 nonces=${seenNonces.size} scripts=${scripts} ` +
      `asset=1 chunk=1 redirect=308 ` +
      `redirect_headers=${redirectHeaderCount === fixedHeaderNames.length ? "presentes" : "fora_da_cobertura"}`,
  );
} finally {
  child.kill("SIGTERM");
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    new Promise((resolve) => setTimeout(resolve, 5_000)),
  ]);
  if (child.exitCode === null) child.kill("SIGKILL");
}
