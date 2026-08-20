import { spawn } from "node:child_process";

import { resolveM09Urls } from "./loopback-url.mjs";

const { api } = resolveM09Urls();
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm";
const child = spawn(npmCommand, ["run", "build"], {
  env: { ...process.env, NEXT_PUBLIC_API_URL: api.origin },
  shell: process.platform === "win32",
  stdio: "inherit",
});

child.once("error", (error) => {
  console.error(error);
  process.exitCode = 1;
});

child.once("exit", (code, signal) => {
  if (signal) {
    console.error(`Build E2E interrompido por ${signal}.`);
    process.exitCode = 1;
    return;
  }
  process.exitCode = code ?? 1;
});
