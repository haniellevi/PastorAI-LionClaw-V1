import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const script = fileURLToPath(new URL("./write-build-provenance.mjs", import.meta.url));
const revision = "0123456789abcdef".repeat(2) + "01234567";

function run(t, kind, sha) {
  const directory = mkdtempSync(join(tmpdir(), "frontend-provenance-"));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const env = { RUNNER_TEMP: directory };
  if (sha !== undefined) env.PASTORAI_RELEASE_SHA = sha;
  const result = spawnSync(process.execPath, [script, kind], { env, encoding: "utf8" });
  return { directory, result };
}

for (const kind of ["next", "workers"]) {
  test(`records the exact source revision for the ${kind} build privately`, (t) => {
    const { directory, result } = run(t, kind, revision);
    assert.equal(result.status, 0, result.stderr);
    const name = `frontend-${kind}-build.json`;
    assert.deepEqual(readdirSync(directory), [name]);
    assert.deepEqual(JSON.parse(readFileSync(join(directory, name), "utf8")), {
      build: kind,
      source_revision: revision,
    });
    assert.equal(statSync(join(directory, name)).mode & 0o777, 0o600);
    assert.equal(result.stdout, "");
  });
}

for (const sha of [undefined, "", "unknown", revision.slice(0, 12), "z".repeat(40)]) {
  test(`does not record absent or invalid source revision: ${sha}`, (t) => {
    const { directory, result } = run(t, "next", sha);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /source revision must be a full Git SHA/);
    assert.deepEqual(readdirSync(directory), []);
  });
}
