/** Local synthetic proof: the real leader panel reads the real test backend. */
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import http from "node:http";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";

import { assertM09LoopbackUrl } from "./loopback-url.mjs";

const { values } = parseArgs({
  options: {
    "frontend-root": { type: "string" },
    "bridge-dir": { type: "string" },
    "api-url": { type: "string" },
    "api-socket": { type: "string" },
    "output-dir": { type: "string" },
  },
  strict: true,
});
for (const key of ["frontend-root", "bridge-dir", "output-dir"]) {
  assert(values[key], `Missing --${key}`);
}
assert(
  Boolean(values["api-url"]) !== Boolean(values["api-socket"]),
  "Provide exactly one of --api-url or --api-socket",
);

const bridgeDir = path.resolve(values["bridge-dir"]);
const outputDir = path.resolve(values["output-dir"]);
const sentinelName = "Membro Sintético Não Exibir";
let browser;
let server;
let relay;
let fixtureDir;
let token = "";
let stage = "setup";
let outcome = { ok: false, error: "Verification did not complete" };
const cancellation = new AbortController();
const signalHandlers = new Map(
  ["SIGINT", "SIGTERM"].map((signal) => [
    signal,
    () => {
      cancellation.abort(new Error(`Interrupted by ${signal}`));
      // Closing only our browser interrupts pending Playwright waits into finally.
      void browser?.close().catch(() => {});
    },
  ]),
);
for (const [signal, handler] of signalHandlers) process.on(signal, handler);

async function writeJson(file, value) {
  const temporary = `${file}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await rename(temporary, file);
}

async function waitForReady() {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    cancellation.signal.throwIfAborted();
    try {
      const ready = JSON.parse(await readFile(path.join(bridgeDir, "ready.json"), "utf8"));
      assert(typeof ready.token === "string" && ready.token.length > 0, "Invalid synthetic token");
      assert(
        typeof ready.meeting_id === "string" && /^[a-f0-9-]{36}$/i.test(ready.meeting_id),
        "Invalid synthetic meeting ID",
      );
      return ready;
    } catch (error) {
      if (error.code !== "ENOENT" && !(error instanceof SyntaxError)) throw error;
    }
    await delay(200, undefined, { signal: cancellation.signal });
  }
  throw new Error("Backend did not publish ready.json within 60 seconds");
}

try {
  await mkdir(outputDir, { recursive: true });
  const frontendRoot = await realpath(values["frontend-root"]);
  const temporaryRoot = await realpath(tmpdir());
  assert(
    frontendRoot.startsWith(`${temporaryRoot}${path.sep}`),
    "--frontend-root must be an isolated projection inside the temporary directory",
  );
  let api;
  if (values["api-url"]) {
    api = assertM09LoopbackUrl("--api-url", values["api-url"]);
    assert(api.hostname === "127.0.0.1", "The test API must bind to 127.0.0.1");
  }

  // Resolve only cached dependencies supplied with the isolated projection.
  const requireFrontend = createRequire(path.join(frontendRoot, "package.json"));
  const requireVitest = createRequire(path.join(frontendRoot, "node_modules/vitest/package.json"));
  const { createServer } = await import(pathToFileURL(requireVitest.resolve("vite")).href);
  const { chromium, expect } = requireFrontend("@playwright/test");
  const dependencyRoot = await realpath(path.join(frontendRoot, "node_modules"));

  stage = "waiting for synthetic backend";
  const ready = await waitForReady();
  token = ready.token;
  if (values["api-socket"]) {
    stage = "connecting the synthetic backend socket";
    const bridgeRoot = await realpath(bridgeDir);
    const socketPath = await realpath(values["api-socket"]);
    assert(
      socketPath.startsWith(`${bridgeRoot}${path.sep}`),
      "The API socket must be inside --bridge-dir",
    );
    assert((await stat(socketPath)).isSocket(), "--api-socket must identify a Unix socket");
    // Transport only: status, headers and bytes come from the actual Uvicorn API.
    relay = http.createServer((incoming, outgoing) => {
      const upstream = http.request(
        {
          socketPath,
          method: incoming.method,
          path: incoming.url,
          headers: incoming.headers,
          agent: false,
          timeout: 20_000,
        },
        (response) => {
          outgoing.writeHead(response.statusCode, response.headers);
          response.on("error", () => outgoing.destroy());
          response.pipe(outgoing);
        },
      );
      upstream.on("timeout", () => upstream.destroy(new Error("Synthetic API socket timed out")));
      upstream.on("error", () => {
        if (outgoing.headersSent) outgoing.destroy();
        else {
          outgoing.writeHead(502, { "Content-Type": "text/plain; charset=utf-8" });
          outgoing.end("Synthetic API socket unavailable");
        }
      });
      incoming.on("aborted", () => upstream.destroy());
      incoming.on("error", () => upstream.destroy());
      outgoing.on("close", () => upstream.destroy());
      incoming.pipe(upstream);
    });
    await new Promise((resolve, reject) => {
      relay.once("error", reject);
      relay.listen(0, "127.0.0.1", resolve);
    });
    const relayAddress = relay.address();
    assert(relayAddress && typeof relayAddress === "object", "Relay did not bind a local port");
    api = { origin: `http://127.0.0.1:${relayAddress.port}` };
  }
  cancellation.signal.throwIfAborted();
  fixtureDir = await mkdtemp(path.join(frontendRoot, "v1a-real-panel-"));
  await writeFile(
    path.join(fixtureDir, "index.html"),
    `<!doctype html>
<html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relatório V1a sintético</title></head><body><div id="root"></div>
<script type="module" src="./fixture.tsx"></script></body></html>\n`,
  );
  await writeFile(
    path.join(fixtureDir, "fixture.tsx"),
    `
import { createRoot } from "react-dom/client";
import { MeetingReportForm } from "@/components/minha-celula/MeetingReportForm";
import "@fontsource/plus-jakarta-sans/400.css";
import "@fontsource/plus-jakarta-sans/600.css";
import "@fontsource/sora/600.css";
import "@/app/globals.css";
import "@/app/design-tokens.css";
import "@/app/ds.css";
import "@/app/expressive-ux-v3.css";
createRoot(document.getElementById("root")!).render(
  <main className="mc mc--leader" style={{ padding: 16 }}>
    <MeetingReportForm token={${JSON.stringify(token)}} reuniaoId={${JSON.stringify(ready.meeting_id)}}
      members={[{ pessoa_id: "00000000-0000-4000-8000-000000000099", nome: ${JSON.stringify(sentinelName)}, ativo: true }]}
      onToast={() => {}} />
  </main>
);\n`,
    { mode: 0o600 },
  );

  stage = "starting isolated frontend";
  server = await createServer({
    root: frontendRoot,
    configFile: false,
    envDir: false,
    envPrefix: "__V1A_NO_ENV__",
    publicDir: false,
    cacheDir: path.join(fixtureDir, ".vite"),
    logLevel: "silent",
    define: {
      "process.env": JSON.stringify({ NODE_ENV: "development", NEXT_PUBLIC_API_URL: api.origin }),
    },
    oxc: { jsx: { runtime: "automatic" } },
    resolve: { alias: { "@": path.join(frontendRoot, "src") } },
    server: {
      host: "127.0.0.1",
      port: 0,
      strictPort: true,
      hmr: false,
      fs: { strict: true, allow: [frontendRoot, dependencyRoot] },
    },
  });
  await server.listen();
  cancellation.signal.throwIfAborted();
  const address = server.httpServer.address();
  assert(address && typeof address === "object", "Vite did not bind a local port");
  const frontendOrigin = `http://127.0.0.1:${address.port}`;
  const fixtureUrl = `${frontendOrigin}/${path.basename(fixtureDir)}/index.html`;
  const reportUrl = `${api.origin}/cell-meetings/${ready.meeting_id}/report`;
  const expectationsUrl = `${api.origin}/cell-meetings/${ready.meeting_id}/visitor-expectations`;
  browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true });
  const viewports = [];

  for (const viewport of [
    { width: 390, height: 844 },
    { width: 1280, height: 900 },
  ]) {
    stage = `checking ${viewport.width}px`;
    const context = await browser.newContext({
      viewport,
      locale: "pt-BR",
      serviceWorkers: "block",
    });
    const blockedRequests = [];
    const apiRequests = [];
    let pageErrors = 0;
    try {
      await context.route("**/*", async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        if (![frontendOrigin, api.origin].includes(url.origin)) {
          blockedRequests.push(url.origin);
          await route.abort("blockedbyclient");
          return;
        }
        if (url.origin === api.origin) {
          apiRequests.push({ method: request.method(), path: url.pathname });
          if (!["GET", "OPTIONS"].includes(request.method())) {
            await route.abort("blockedbyclient");
            return;
          }
        }
        await route.continue();
      });
      // No websocket is needed for this fixed fixture (Vite HMR is disabled).
      await context.routeWebSocket("**/*", (socket) => socket.close());
      const page = await context.newPage();
      page.setDefaultTimeout(20_000);
      page.on("pageerror", () => {
        pageErrors += 1;
      });
      const [reportResponse, expectationsResponse] = await Promise.all([
        page.waitForResponse(
          (response) => response.url() === reportUrl && response.request().method() === "GET",
        ),
        page.waitForResponse(
          (response) => response.url() === expectationsUrl && response.request().method() === "GET",
        ),
        page.goto(fixtureUrl, { waitUntil: "domcontentloaded", timeout: 30_000 }),
      ]);
      assert.equal(reportResponse.status(), 200, "Real report endpoint did not return HTTP 200");
      assert.equal(
        expectationsResponse.status(),
        200,
        "Real expectations endpoint did not return HTTP 200",
      );
      assert(
        reportResponse.request().headers().authorization === `Bearer ${token}`,
        "The real report request did not carry the synthetic session token",
      );
      const report = await reportResponse.json();
      const expectations = await expectationsResponse.json();
      assert.equal(report.schema, "cell-report/v2", "Unexpected report schema");
      assert.equal(report.relatorio_status, "enviado", "Report was not finalized");
      assert.deepEqual(
        report.totals,
        { presentes: 12, visitantes: 2, decisoes: 1 },
        "Unexpected official totals",
      );
      assert.equal(report.oferta_valor, 35.5, "Unexpected official offering");
      for (const field of ["presencas", "visitantes", "records"]) {
        assert(
          Array.isArray(report[field]) && report[field].length === 0,
          `Unexpected individual ${field}`,
        );
      }
      assert(
        Array.isArray(expectations.expectations) && expectations.expectations.length === 0,
        "Unexpected individual visitor expectations",
      );

      const summary = page.getByRole("region", { name: "Resumo do relatório" });
      await expect(summary).toBeVisible();
      for (const text of ["12 presentes", "2 visitantes", "1 decisão"]) {
        await expect(summary.getByText(text, { exact: true })).toBeVisible();
      }
      await expect(summary.getByText(/R\$\s*35,50/)).toBeVisible();
      await expect(page.getByText("Enviado", { exact: true })).toBeVisible();
      await expect(page.getByRole("status")).toHaveText(
        "Relatório enviado e bloqueado para edição.",
      );
      await expect(page.getByText(sentinelName, { exact: true })).toHaveCount(0);
      await expect(page.locator(".mc-report")).toHaveCount(1);
      await expect(
        page.locator(".mc-report input, .mc-report select, .mc-report textarea, .mc-report button"),
      ).toHaveCount(0);
      await expect(
        page.getByRole("button", { name: /Enviar relatório|Adicionar|Registrar|Salvar/i }),
      ).toHaveCount(0);
      await page.evaluate(async () => {
        await document.fonts.ready;
      });
      const dimensions = await page.evaluate(() => ({
        viewport: window.innerWidth,
        content: document.documentElement.scrollWidth,
      }));
      assert(
        dimensions.content <= dimensions.viewport + 1,
        "Panel overflows the viewport horizontally",
      );
      assert.equal(pageErrors, 0, "Browser raised a JavaScript error");
      assert.equal(blockedRequests.length, 0, "The fixture attempted an external request");
      assert(
        apiRequests.every(({ method }) => ["GET", "OPTIONS"].includes(method)),
        "Panel attempted an API mutation",
      );
      const screenshot = `v1a-real-report-${viewport.width}.png`;
      await page.screenshot({
        path: path.join(outputDir, screenshot),
        fullPage: true,
        animations: "disabled",
      });
      viewports.push({
        width: viewport.width,
        report_http_status: reportResponse.status(),
        expectations_http_status: expectationsResponse.status(),
        schema: report.schema,
        status: report.relatorio_status,
        totals: report.totals,
        oferta_valor: report.oferta_valor,
        individual_controls: 0,
        sentinel_names: 0,
        blocked_external_requests: blockedRequests.length,
        api_requests: apiRequests,
        horizontal_overflow: false,
        screenshot,
      });
    } finally {
      await context.close();
    }
  }
  outcome = {
    ok: true,
    backend: "real synthetic HTTP",
    component: "MeetingReportForm",
    transport: values["api-socket"] ? "Unix socket relay" : "loopback HTTP",
    viewports,
  };
} catch (error) {
  const message = String(error?.message ?? error);
  outcome = {
    ok: false,
    error: `${stage}: ${token ? message.replaceAll(token, "[redacted]") : message}`.slice(0, 2000),
  };
  process.exitCode = 1;
} finally {
  if (cancellation.signal.aborted) {
    outcome = { ok: false, error: "Verification was interrupted" };
    process.exitCode = 1;
  }
  const relayClosed = relay?.listening
    ? new Promise((resolve, reject) => {
        relay.close((error) => (error ? reject(error) : resolve()));
        relay.closeAllConnections();
      })
    : undefined;
  const cleanup = await Promise.allSettled([browser?.close(), server?.close(), relayClosed]);
  if (cleanup.some((result) => result.status === "rejected")) {
    outcome = { ok: false, error: "Failed to close an owned browser, Vite server or socket relay" };
    process.exitCode = 1;
  }
  try {
    if (fixtureDir) await rm(fixtureDir, { recursive: true });
    await writeJson(path.join(outputDir, "browser-result.json"), outcome);
  } catch {
    outcome = { ok: false, error: "Failed to remove the owned fixture or save browser evidence" };
    process.exitCode = 1;
  }
  // Publish even after evidence/fixture failure, so the backend does not hang.
  await writeJson(path.join(bridgeDir, "browser-done.json"), outcome);
  for (const [signal, handler] of signalHandlers) process.off(signal, handler);
  console.log(
    JSON.stringify({ ok: outcome.ok, evidence: path.join(outputDir, "browser-result.json") }),
  );
}
