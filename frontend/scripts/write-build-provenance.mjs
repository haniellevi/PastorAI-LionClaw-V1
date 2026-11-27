import { writeFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";

const kind = process.argv[2];
const { PASTORAI_RELEASE_SHA: sha, RUNNER_TEMP: directory } = process.env;

if (!sha || sha.length !== 40 || !/^[0-9a-f]{40}$/.test(sha)) {
  throw new Error("source revision must be a full Git SHA");
}
if (!["next", "workers"].includes(kind) || !directory || !isAbsolute(directory)) {
  throw new Error("expected a build kind and an absolute runner temporary directory");
}

// The caller runs this only after a successful build. This file stays outside
// the frontend's output directories and is not a runtime installation receipt.
writeFileSync(
  join(directory, `frontend-${kind}-build.json`),
  JSON.stringify({ build: kind, source_revision: sha }) + "\n",
  { flag: "wx", mode: 0o600 },
);
