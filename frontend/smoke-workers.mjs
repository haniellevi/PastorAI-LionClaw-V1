import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { assertPublicPage, freePort, request } from "./smoke-http.mjs";

const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
const wranglerBin = join(frontendRoot, "node_modules/wrangler/bin/wrangler.js");
const port = await freePort();
const scratch = await mkdtemp(join(tmpdir(), "igreja12-workers-smoke-"));

// O runner usa apenas dados fictícios e o runtime local do lockfile.
// Não herda credenciais nem reutiliza o HOME ou estado do operador.
const child = spawn(
  process.execPath,
  [
    wranglerBin,
    "dev",
    "--local",
    "--ip",
    "127.0.0.1",
    "--port",
    String(port),
    "--inspector-port",
    "0",
    "--persist-to",
    join(scratch, "state"),
    "--show-interactive-dev-session=false",
  ],
  {
    cwd: frontendRoot,
    env: {
      PATH: process.env.PATH,
      HOME: scratch,
      TMPDIR: scratch,
      CI: "true",
      NEXT_PUBLIC_API_URL: "https://synthetic-api.example.test",
      NEXT_TELEMETRY_DISABLED: "1",
      WRANGLER_SEND_METRICS: "false",
      // Miniflare usa os metadados locais padrão, sem buscar cf.json.
      // https://developers.cloudflare.com/workers/testing/miniflare/get-started/#requestcf-object
      CLOUDFLARE_CF_FETCH_ENABLED: "false",
      CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV: "false",
    },
    detached: true,
    stdio: ["ignore", "inherit", "inherit"],
  },
);
let spawnError;
child.once("error", (error) => (spawnError = error));
const closed = new Promise((resolve) => child.once("close", resolve));

// Wrangler e workerd compartilham um grupo de processos próprio no runner Linux.
function stop(signal) {
  if (!child.pid) return;
  try {
    process.kill(-child.pid, signal);
  } catch (error) {
    if (error.code !== "ESRCH") throw error;
  }
}
const terminate = () => stop("SIGTERM");
process.once("SIGTERM", terminate);
process.once("SIGINT", terminate);

try {
  const deadline = Date.now() + 60_000;
  let ready = false;
  while (Date.now() < deadline) {
    if (spawnError) throw spawnError;
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new Error("Wrangler encerrou antes do smoke");
    }
    try {
      ready = (await request(port, "/")).status === 200;
      if (ready) break;
    } catch {
      // O servidor local ainda pode estar inicializando.
    }
    await delay(250);
  }
  assert(ready, "Wrangler não ficou pronto em 60s");

  for (const path of ["/", "/privacidade", "/termos"]) {
    const page = await assertPublicPage((path) => request(port, path), path);
    assert.match(page.headers["content-type"], /^text\/html\b/, `${path}: HTML`);
    assert.match(page.body, /<html\b/i, `${path}: documento renderizado`);
  }
  console.log("WORKERS_PUBLIC_PAGES_OK pages=3");
} finally {
  terminate();
  await Promise.race([closed, delay(5_000, undefined, { ref: false })]);
  stop("SIGKILL");
  await closed;
  await rm(scratch, { recursive: true, force: true });
  process.removeListener("SIGTERM", terminate);
  process.removeListener("SIGINT", terminate);
}
