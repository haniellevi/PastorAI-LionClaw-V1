/** Local scenario 20: the Central reads real HTTP before and after report closure. */
import assert from "node:assert/strict";
import { mkdtemp, readFile, realpath, rename, rm, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { parseArgs } from "node:util";
import { pathToFileURL } from "node:url";

import { assertM09LoopbackUrl } from "./loopback-url.mjs";

const { values } = parseArgs({ options: {
  "frontend-root": { type: "string" },
  "bridge-dir": { type: "string" },
} });
const readTimeout = 20_000;
const cancel = new AbortController();
let stage = "setup";
let token;
let fixtureDir;
let server;
let browser;
let evidence;
let donePath;

function interrupt() {
  cancel.abort();
  void browser?.close().catch(() => {});
}
process.once("SIGINT", interrupt);
process.once("SIGTERM", interrupt);

async function absent(file) {
  try {
    await stat(file);
    return false;
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    return true;
  }
}

async function waitForConfirmation(file) {
  const deadline = Date.now() + 60_000;
  while (Date.now() < deadline) {
    cancel.signal.throwIfAborted();
    if (!(await absent(file))) {
      const marker = await stat(file);
      assert(marker.isFile() && marker.size === 0, "Invalid confirmation marker");
      return;
    }
    await delay(100, undefined, { signal: cancel.signal });
  }
  throw new Error("Backend did not confirm the report within 60 seconds");
}

try {
  assert(values["frontend-root"] && values["bridge-dir"], "Specify --frontend-root and --bridge-dir");
  const frontendRoot = await realpath(values["frontend-root"]);
  assert(frontendRoot.startsWith(`${await realpath(tmpdir())}${path.sep}`),
    "Frontend projection must be inside the temporary directory");
  const bridge = await realpath(values["bridge-dir"]);
  const bridgeStat = await stat(bridge);
  assert(bridgeStat.isDirectory() && (bridgeStat.mode & 0o077) === 0, "Bridge directory must be private");
  const pendingMarker = path.join(bridge, "browser-pending.json");
  const confirmation = path.join(bridge, "confirmed");
  donePath = path.join(bridge, "browser-done.json");
  assert(await absent(pendingMarker) && await absent(confirmation), "Bridge already contains an outcome marker");
  const ready = JSON.parse(await readFile(path.join(bridge, "ready.json"), "utf8"));
  assert(typeof ready.token === "string" && ready.token.length > 0, "Missing synthetic session");
  token = ready.token;
  assert(typeof ready.meeting_id === "string" && /^[0-9a-f-]{36}$/i.test(ready.meeting_id), "Invalid meeting ID");
  assert(typeof ready.cell_name === "string" && ready.cell_name.trim(), "Missing synthetic cell name");
  const api = assertM09LoopbackUrl("fixture API", ready.api_url);
  assert.equal(api.hostname, "127.0.0.1", "Fixture API must use 127.0.0.1");

  const requireFrontend = createRequire(path.join(frontendRoot, "package.json"));
  const requireVitest = createRequire(path.join(frontendRoot, "node_modules/vitest/package.json"));
  const { createServer } = await import(pathToFileURL(requireVitest.resolve("vite")).href);
  const { chromium, expect } = requireFrontend("@playwright/test");
  const dependencyRoot = await realpath(path.join(frontendRoot, "node_modules"));

  stage = "starting the isolated frontend";
  fixtureDir = await mkdtemp(path.join(frontendRoot, "v1a-real-central-"));
  await writeFile(path.join(fixtureDir, "index.html"), `<!doctype html>
<html lang="pt-BR"><meta charset="UTF-8"><title>Central sintética</title>
<div id="root"></div><script type="module" src="./fixture.tsx"></script></html>`);
  await writeFile(path.join(fixtureDir, "fixture.tsx"), `
import { createRoot } from "react-dom/client";
import { CentralCelulaScreen } from "@/components/central-celula/CentralCelulaScreen";
import "@/app/globals.css";
import "@/app/design-tokens.css";
import "@/app/ds.css";
import "@/app/expressive-ux-v3.css";
createRoot(document.getElementById("root")!).render(<CentralCelulaScreen />);`);
  // Inject only the session context. The Central, its fetches and responses are real.
  const auth = path.join(fixtureDir, "session.ts");
  await writeFile(auth, `
const session = {
  token: window.__v1aSyntheticToken,
  user: { roles: ["pastor"] },
  expireSession: () => { throw new Error("The synthetic session expired"); },
};
export function useAuth() { return session; }`);
  server = await createServer({
    root: frontendRoot,
    configFile: false,
    envDir: false,
    envPrefix: "__V1A_NO_ENV__",
    publicDir: false,
    cacheDir: path.join(fixtureDir, ".vite"),
    logLevel: "silent",
    define: { "process.env": JSON.stringify({ NODE_ENV: "development", NEXT_PUBLIC_API_URL: api.origin }) },
    oxc: { jsx: { runtime: "automatic" } },
    resolve: { alias: [{ find: /^@\/lib\/auth-context$/, replacement: auth },
      { find: "@", replacement: path.join(frontendRoot, "src") }] },
    server: {
      host: "127.0.0.1", port: 0, strictPort: true, hmr: false, ws: false,
      fs: { strict: true, allow: [frontendRoot, dependencyRoot] },
    },
  });
  await server.listen();
  cancel.signal.throwIfAborted();
  const address = server.httpServer.address();
  assert(address && typeof address === "object", "Vite did not bind a local port");
  const frontendOrigin = `http://127.0.0.1:${address.port}`;
  browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome", headless: true, timeout: readTimeout,
    args: ["--disable-background-networking"],
  });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 }, locale: "pt-BR", serviceWorkers: "block",
  });
  const blocked = [];
  let viteSocketsClosed = 0;
  await context.route("**/*", async (route) => {
    const request = route.request();
    const { origin, pathname } = new URL(request.url());
    const allowed = origin === frontendOrigin && ["GET", "HEAD"].includes(request.method()) ||
      origin === api.origin && ["GET", "OPTIONS"].includes(request.method());
    if (allowed) return route.continue();
    blocked.push(`${request.method()} ${origin}${pathname}`);
    await route.abort("blockedbyclient");
  });
  await context.routeWebSocket("**/*", (socket) => {
    const { origin, pathname, searchParams, username, password, hash } = new URL(socket.url());
    const viteOrigin = origin === `ws://127.0.0.1:${address.port}` || origin === "ws://127.0.0.1:0";
    if (viteOrigin && pathname === "/" && !username && !password && !hash &&
      searchParams.size === 1 && searchParams.get("token")) {
      // Vite injects its client for CSS even when HMR and the server socket are off.
      viteSocketsClosed += 1;
    } else {
      blocked.push(`WEBSOCKET ${origin}${pathname}`);
    }
    socket.close();
  });
  await context.addInitScript((value) => { window.__v1aSyntheticToken = value; }, token);
  const page = await context.newPage();
  page.setDefaultTimeout(readTimeout);
  let pageErrors = 0;
  page.on("pageerror", () => { pageErrors += 1; });
  const dashboardPath = "/cell-central/dashboard";
  const pendingPath = (size) => `/cell-central/pending-reports?page=1&page_size=${size}`;
  let dashboardReads = 0;
  let queueReads = 0;
  page.on("request", (request) => {
    if (request.method() !== "GET") return;
    if (request.url() === `${api.origin}${dashboardPath}`) dashboardReads += 1;
    if (request.url() === `${api.origin}${pendingPath(8)}`) queueReads += 1;
  });

  async function read(endpoint) {
    const response = await page.waitForResponse((candidate) =>
      candidate.url() === `${api.origin}${endpoint}` && candidate.request().method() === "GET");
    assert.equal(response.status(), 200, `Expected HTTP 200 from ${endpoint}`);
    assert((await response.request().headerValue("authorization")) === `Bearer ${token}`,
      `Missing synthetic session on ${endpoint}`);
    return response.json();
  }

  function checkReports(body, ids) {
    assert.equal(body.total, ids.length, "Unexpected number of pending reports");
    assert.deepEqual(body.items.map(({ reuniao_id }) => reuniao_id), ids, "Unexpected pending meeting IDs");
    if (ids.length) assert.equal(body.items[0].celula_nome, ready.cell_name, "Unexpected pending cell name");
  }

  const today = page.getByRole("region", { name: "Hoje na Central" });
  const refresh = today.getByRole("button", { name: "Atualizar", exact: true });
  const reportShortcut = today.getByRole("button", { name: /Ver relatórios/ });
  const reportList = page.getByRole("region", { name: "Relatórios pendentes" });
  const totals = today.getByText("Totais da igreja", { exact: true });
  const counter = today.getByRole("button", { name: /Relatórios pendentes/ }).locator(".cc-val");
  const todayTab = page.getByRole("tab", { name: "Hoje" });
  const cellsTab = page.getByRole("tab", { name: "Gerenciar células" });

  stage = "checking the initial Hoje counter";
  const [initialDashboard, initialReports] = await Promise.all([
    read(dashboardPath), read(pendingPath(8)),
    page.goto(`${frontendOrigin}/${path.basename(fixtureDir)}/index.html`, { waitUntil: "domcontentloaded" }),
  ]);
  assert.equal(initialDashboard.relatorios_pendentes, 1);
  checkReports(initialReports, [ready.meeting_id]);
  await totals.click();
  await expect(counter).toBeVisible({ timeout: readTimeout });
  await expect(counter).toHaveText("1");

  stage = "checking the pending report in Gerenciar células";
  const [listed] = await Promise.all([read(pendingPath(50)), reportShortcut.click()]);
  checkReports(listed, [ready.meeting_id]);
  await expect(reportList.getByRole("cell", { name: ready.cell_name, exact: true })).toBeVisible();

  stage = "returning to Hoje with one report pending";
  const [beforeDashboard, beforeReports] = await Promise.all([
    read(dashboardPath), read(pendingPath(8)), todayTab.click(),
  ]);
  assert.equal(beforeDashboard.relatorios_pendentes, 1);
  checkReports(beforeReports, [ready.meeting_id]);
  await totals.click();
  await expect(counter).toHaveText("1");
  await expect(refresh).toBeEnabled();
  const beforeConfirmation = dashboardReads;
  const queueBeforeConfirmation = queueReads;

  stage = "waiting for the backend to commit the report";
  const markerTemp = `${pendingMarker}.${process.pid}.tmp`;
  try {
    await writeFile(markerTemp, `${JSON.stringify({ meeting_id: ready.meeting_id })}\n`, { flag: "wx", mode: 0o600 });
    await rename(markerTemp, pendingMarker);
  } finally {
    await rm(markerTemp, { force: true });
  }
  await waitForConfirmation(confirmation);
  assert.equal(dashboardReads, beforeConfirmation, "Hoje refreshed before the Atualizar click");
  assert.equal(queueReads, queueBeforeConfirmation, "The report queue refreshed before the Atualizar click");
  await expect(counter).toHaveText("1");

  stage = "checking the Atualizar request and visible zero";
  const [afterDashboard, afterReports] = await Promise.all([
    read(dashboardPath), read(pendingPath(8)), refresh.click(),
  ]);
  assert.equal(dashboardReads, beforeConfirmation + 1, "Expected one fresh dashboard request after Atualizar");
  assert.equal(queueReads, queueBeforeConfirmation + 1, "Expected one fresh report queue request after Atualizar");
  assert.equal(afterDashboard.relatorios_pendentes, 0);
  checkReports(afterReports, []);
  await expect(counter).toBeVisible();
  await expect(counter).toHaveText("0");
  await expect(reportShortcut).toHaveCount(0);

  stage = "checking the real empty pending list";
  const [empty] = await Promise.all([read(pendingPath(50)), cellsTab.click()]);
  checkReports(empty, []);
  await expect(reportList.getByText("Nenhum relatório pendente.", { exact: true })).toBeVisible();
  assert.equal(pageErrors, 0, "Browser raised a JavaScript error");
  assert.equal(blocked.length, 0, `Browser attempted blocked traffic: ${blocked.join(", ")}`);
  evidence = { ok: true, meeting_id: ready.meeting_id,
    counter: [initialDashboard.relatorios_pendentes, afterDashboard.relatorios_pendentes],
    list_totals: [listed.total, empty.total],
    refresh: "Atualizar", backend: "authenticated loopback HTTP", blocked_requests: blocked.length,
    vite_websockets_closed: viteSocketsClosed };
} catch (error) {
  const message = String(error?.message ?? error);
  console.error(`${stage}: ${token ? message.replaceAll(token, "[redacted]") : message}`.slice(0, 2000));
  process.exitCode = 1;
} finally {
  const results = await Promise.allSettled([browser?.close(), server?.close()]);
  if (fixtureDir) results.push(...await Promise.allSettled([rm(fixtureDir, { recursive: true, force: true })]));
  process.off("SIGINT", interrupt);
  process.off("SIGTERM", interrupt);
  if (cancel.signal.aborted || results.some(({ status }) => status === "rejected")) {
    console.error("Browser verification interrupted or cleanup failed");
    process.exitCode = 1;
  }
}
if (evidence && !process.exitCode) {
  const serialized = JSON.stringify(evidence);
  await writeFile(donePath, `${serialized}\n`, { flag: "wx", mode: 0o600 });
  console.log(serialized);
}
