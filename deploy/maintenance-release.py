#!/usr/bin/env python3
"""One reviewed API-only console release; no migrations or worker replacement."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import sys
import tarfile
import time
import urllib.request


LEGACY_SHA = "eb5a09b975160f993a3c31bd3c28edc89d9a38ff"
DEPENDENCY_UPDATE_SHA = "b3b93de934e515f7bdb51a5d4393611707089b10"
DEPENDENCY_UPDATE_DIGEST = "72872044003ddabf1962c017ecfb6b83ebe19b6607297419fc9d5b49dec61346"
LEGACY_DEPLOY = Path("/opt/pastorai-releases") / LEGACY_SHA / "deploy"
CURRENT_LINK = Path("/opt/pastorai-current")
RELEASE_ROOT = Path("/opt/pastorai-api-maintenance")
PROTECTED = (
    "queue-worker", "cron-worker", "broadcast-worker", "redis",
    "evolution-postgres", "evolution-api",
)
GATES = (
    "ALLOW_REAL_SENDS", "ASAAS_BILLING_ENABLED", "BREVO_SEND_MODE",
    "BROADCAST_ASYNC_ENABLED",
)
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
SOURCE = re.compile(r"app/(?:[A-Za-z0-9_]+/)*[A-Za-z0-9_]+\.py\Z")
MIGRATION = re.compile(r"migrations/[A-Za-z0-9_]+\.sql\Z")


class Refused(RuntimeError):
    """A sanitized failure, with no subprocess output or configuration values."""


def require(condition, message):
    if not condition:
        raise Refused(message)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def compose_dollars(value, *, escape):
    """Compose config output re-escapes dollars; inspect values have literal dollars."""
    if isinstance(value, str):
        return value.replace("$", "$$") if escape else value.replace("$$", "$")
    if isinstance(value, list):
        return [compose_dollars(item, escape=escape) for item in value]
    if isinstance(value, dict):
        return {key if escape else key.replace("$$", "$"): compose_dollars(item, escape=escape)
                for key, item in value.items()}
    return value


def validate_gates(environment):
    require(all(key in environment for key in GATES), "API effect gate missing")
    require(all(isinstance(environment[key], str)
                and environment[key].strip().lower() in {"true", "false"}
                for key in GATES if key != "BREVO_SEND_MODE")
            and isinstance(environment["BREVO_SEND_MODE"], str)
            and environment["BREVO_SEND_MODE"].strip().lower() in {"off", "canary", "live"},
            "API effect gate value invalid")


def validate_profile(profile):
    require(isinstance(profile, dict) and profile.get("version") == 1,
            "unsupported maintenance profile")
    require(profile.get("legacy_sha") == LEGACY_SHA, "legacy SHA mismatch")
    require(isinstance(profile.get("candidate_sha"), str)
            and SHA.fullmatch(profile["candidate_sha"]), "candidate SHA unpinned")
    require(profile["candidate_sha"] != LEGACY_SHA, "candidate is the legacy SHA")
    require(isinstance(profile.get("candidate_archive_sha256"), str)
            and DIGEST.fullmatch(profile["candidate_archive_sha256"]),
            "candidate archive digest unpinned")
    root = profile.get("archive_root", "")
    require(isinstance(root, str) and "/" not in root and root.endswith(profile["candidate_sha"])
            and re.fullmatch(r"[A-Za-z0-9_.-]+", root), "archive root unpinned")
    for name in ("legacy_manifest", "candidate_manifest"):
        manifest = profile.get(name)
        require(isinstance(manifest, dict) and "requirements.lock" in manifest
                and "app/db/models.py" in manifest and "app/routers/whatsapp.py" in manifest,
                "source manifest incomplete")
        require(all(isinstance(path, str) and (path == "requirements.lock" or SOURCE.fullmatch(path))
                    and isinstance(value, str) and DIGEST.fullmatch(value)
                    for path, value in manifest.items()), "source manifest malformed")
    old, new = profile["legacy_manifest"], profile["candidate_manifest"]
    changed = {path for path in old.keys() & new.keys() if old[path] != new[path]}
    added = new.keys() - old.keys()
    require(not old.keys() - new.keys(), "candidate removed a legacy source file")
    for key, actual in (("allowed_changed_files", changed), ("allowed_new_files", added)):
        permitted = profile.get(key)
        require(isinstance(permitted, list)
                and all(isinstance(path, str) and (SOURCE.fullmatch(path)
                        or key == "allowed_changed_files" and path == "requirements.lock") for path in permitted)
                and len(permitted) == len(set(permitted)),
                "source allowlist malformed")
        require(actual == set(permitted), "candidate source delta outside exact allowlist")
    protected = {path for path in old if path.startswith("app/workers/")} | {
        "app/db/models.py", "app/routers/whatsapp.py",
    }
    require(all(new.get(path) == old[path] for path in protected)
            and not any(path.startswith("app/workers/") for path in added),
            "candidate changed worker, model or webhook contract")
    if new["requirements.lock"] != old["requirements.lock"]:
        require(profile.get("dependency_update_source_sha") == DEPENDENCY_UPDATE_SHA
                and new["requirements.lock"] == DEPENDENCY_UPDATE_DIGEST,
                "candidate dependency update is not the reviewed lock")
    for name in ("legacy_build_manifest", "candidate_build_manifest"):
        manifest = profile.get(name)
        require(isinstance(manifest, dict) and "Dockerfile" in manifest
                and all(isinstance(path, str) and (path in {"Dockerfile", ".dockerignore"}
                        or MIGRATION.fullmatch(path)) and isinstance(value, str)
                        and DIGEST.fullmatch(value) for path, value in manifest.items()),
                "build manifest incomplete")
    require(profile["legacy_build_manifest"] == profile["candidate_build_manifest"],
            "candidate changed the build contract")


class Runner:
    def __init__(self):
        self.env = dict(os.environ)
        for key in tuple(self.env):
            if key.startswith("DOCKER_") or key.startswith("COMPOSE_"):
                del self.env[key]
        self.env["DOCKER_HOST"] = "unix:///var/run/docker.sock"

    def __call__(self, args, *, label, input=None, timeout=180):
        try:
            result = subprocess.run(args, input=input, text=True, capture_output=True,
                                    env=self.env, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise Refused(label + " unavailable") from None
        require(result.returncode == 0, label + " failed")
        return result.stdout


class Release:
    def __init__(self, profile, archive, *, runner=None, legacy_deploy=LEGACY_DEPLOY,
                 current_link=CURRENT_LINK, release_root=RELEASE_ROOT, checker=None,
                 health=None):
        self.profile = profile
        self.archive = Path(archive)
        self.runner = runner or Runner()
        self.legacy_deploy = Path(legacy_deploy)
        self.current_link = Path(current_link)
        self.release_root = Path(release_root)
        self.checker = Path(checker or Path(__file__).with_name("check_maintenance_schema.py"))
        self.health = health or self.http_health
        self.candidate = None
        self.protected = {}
        self.config_files = {}
        self.old_api = None
        self.new_image = None
        self.lock = None

    def compose(self, config, *args, label, input=None, timeout=180):
        return self.runner(["docker", "compose", "--project-name", "pastorai",
                            "--file", str(config), *args], label=label, input=input,
                           timeout=timeout)

    def service(self, name):
        identifier = self.compose(self.legacy_deploy / "docker-compose.yml", "ps", "--all",
                                  "--quiet", name, label="service identity").strip()
        require(bool(DIGEST.fullmatch(identifier)), "service identity missing or ambiguous")
        try:
            rows = json.loads(self.runner(["docker", "inspect", identifier], label="container inspection"))
            require(isinstance(rows, list) and len(rows) == 1, "container inspection ambiguous")
            row = rows[0]
            require(row["Id"] == identifier and IMAGE.fullmatch(row["Image"]),
                    "container identity unverifiable")
            entries = row["Config"]["Env"]
            environment = dict(entry.split("=", 1) for entry in entries)
            require(len(environment) == len(entries), "duplicate container environment key")
            require(row["State"]["Running"] is True and row["State"]["Status"] == "running",
                    "required service is not running")
            return {"id": identifier, "image": row["Image"], "environment": environment,
                    "started": row["State"]["StartedAt"], "restarts": row["RestartCount"],
                    "command": row["Config"].get("Cmd"),
                    "entrypoint": row["Config"].get("Entrypoint")}
        except (KeyError, TypeError, ValueError):
            raise Refused("container inspection malformed") from None

    def private_json(self, name, value):
        path = self.candidate / name
        with path.open("x", encoding="utf-8") as out:
            os.chmod(path, 0o600)
            json.dump(compose_dollars(value, escape=True), out, separators=(",", ":"))
        return path

    @staticmethod
    def proof_code(manifest):
        return """import hashlib, json, pathlib
root = pathlib.Path('/app')
expected = json.loads(MANIFEST)
actual = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
          for path in (root / 'app').rglob('*.py') if path.is_file()}
actual['requirements.lock'] = hashlib.sha256((root / 'requirements.lock').read_bytes()).hexdigest()
if actual != expected:
    raise SystemExit(1)
""".replace("MANIFEST", repr(json.dumps(manifest, separators=(",", ":"))))

    def source_proof(self, container, manifest):
        self.runner(["docker", "exec", "-i", container, "python", "-B", "-"],
                    label="runtime source proof", input=self.proof_code(manifest))

    def schema(self, container=None, config=None, manifest=None):
        source = self.checker.read_text(encoding="utf-8")
        public_profile = json.dumps(self.profile, separators=(",", ":"))
        if container:
            self.runner(["docker", "exec", "-i", "-e", "MAINTENANCE_SCHEMA_PROFILE=" + public_profile,
                         container, "python", "-B", "-"], label="read-only schema check", input=source)
        else:
            source = self.proof_code(manifest or self.profile["candidate_manifest"]) + "\nexec(compile(" + repr(source) + ", 'maintenance_schema', 'exec'))\n"
            self.compose(config, "run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                         "-e", "MAINTENANCE_SCHEMA_PROFILE=" + public_profile,
                         "backend", "-B", "-", label="image read-only schema check", input=source)

    def file_snapshot(self):
        paths = [self.legacy_deploy / ".env", self.legacy_deploy / "docker-compose.yml"]
        paths += [self.legacy_deploy / name for name in (
            "docker-compose.override.yml", "docker-compose.override.yaml",
        ) if (self.legacy_deploy / name).exists()]
        require(all(path.is_file() and not path.is_symlink() for path in paths),
                "legacy configuration missing or aliased")
        return {str(path): digest(path) for path in paths}

    def invariants(self):
        require(self.current_link.resolve() == self.legacy_deploy.parent,
                "global release pointer changed")
        require(self.file_snapshot() == self.config_files, "legacy configuration changed")
        require(all(self.service(name) == original for name, original in self.protected.items()),
                "protected service changed")

    def extract(self):
        require(self.archive.is_file() and not self.archive.is_symlink(), "archive missing or aliased")
        require(digest(self.archive) == self.profile["candidate_archive_sha256"], "archive digest mismatch")
        self.release_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        require(not self.release_root.is_symlink(), "maintenance root aliased")
        self.candidate = self.release_root / self.profile["candidate_sha"]
        require(not self.candidate.exists() and not self.candidate.is_symlink(), "candidate already exists")
        self.candidate.mkdir(mode=0o700)
        prefix = self.profile["archive_root"]
        seen = set()
        extracted = {}
        with tarfile.open(self.archive, "r:gz") as archive:
            for member in archive:
                parts = PurePosixPath(member.name).parts
                require(parts and parts[0] == prefix and not member.name.startswith("/")
                        and ".." not in parts and "\\" not in member.name
                        and (member.isdir() or member.isfile()), "unsafe archive member")
                require(member.name not in seen, "duplicate archive member")
                seen.add(member.name)
                if member.isdir() or len(parts) < 3 or parts[1] != "backend":
                    continue
                relative = "/".join(parts[2:])
                allowed = (relative in self.profile["candidate_manifest"]
                           or relative in self.profile["candidate_build_manifest"])
                if not allowed:
                    require(not relative.startswith("app/")
                            and (not relative.startswith("migrations/") or relative == "migrations/README.md")
                            and relative not in {"Dockerfile", ".dockerignore"},
                            "unmanifested candidate build or application source")
                    continue
                require(member.size <= 16 * 1024 * 1024, "candidate source file too large")
                target = self.candidate / "backend" / relative
                target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as out:
                    os.chmod(target, 0o600)
                    out.write(source.read())
                extracted[relative] = digest(target)
        expected = self.profile["candidate_manifest"] | self.profile["candidate_build_manifest"]
        require(extracted == expected,
                "candidate archive source proof failed")

    def api_config(self, resolved, image, *, build=False):
        config = copy.deepcopy(resolved)
        backend = config["services"]["backend"]
        backend.pop("build", None)
        backend.pop("env_file", None)
        backend.pop("depends_on", None)
        backend["image"] = image
        backend["pull_policy"] = "never"
        backend["environment"] = dict(self.old_api["environment"])
        backend["command"] = self.old_api["command"]
        backend["entrypoint"] = self.old_api["entrypoint"]
        if build:
            backend["build"] = {"context": str(self.candidate / "backend")}
            backend["environment"]["PASTORAI_RELEASE_SHA"] = self.profile["candidate_sha"]
        return config

    def capabilities(self):
        version = self.runner(["docker", "compose", "version", "--short"], label="Compose version").strip()
        match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", version)
        require(match is not None and tuple(map(int, match.groups())) >= (5, 0, 0),
                "Compose 5.0.0 or newer required")
        help_text = self.runner(["docker", "compose", "start", "--help"], label="Compose start capabilities")
        require(re.search(r"(?:^|\s)--wait(?:\s|$)", help_text)
                and re.search(r"(?:^|\s)--wait-timeout(?:\s|$)", help_text), "Compose wait unavailable")

    def stopped_api(self, config, expected_image):
        identifier = self.compose(config, "ps", "--all", "--quiet", "backend",
                                  label="stopped API identity").strip()
        require(bool(DIGEST.fullmatch(identifier)), "stopped API identity ambiguous")
        try:
            rows = json.loads(self.runner(["docker", "inspect", identifier], label="stopped API inspection"))
            require(len(rows) == 1 and rows[0]["Id"] == identifier
                    and rows[0]["Image"] == expected_image
                    and rows[0]["State"]["Running"] is False,
                    "stopped API image or state mismatch")
            entries = rows[0]["Config"]["Env"]
            environment = dict(entry.split("=", 1) for entry in entries)
            expected_environment = dict(self.old_api["environment"])
            if expected_image == self.new_image:
                expected_environment["PASTORAI_RELEASE_SHA"] = self.profile["candidate_sha"]
            require(len(environment) == len(entries) and environment == expected_environment,
                    "API environment changed beyond release provenance")
        except (KeyError, TypeError, ValueError):
            raise Refused("stopped API inspection malformed") from None
        return identifier

    def create_api(self, config, expected_image, manifest):
        self.compose(config, "up", "--no-start", "--no-build", "--no-deps", "--pull", "never",
                     "--force-recreate", "backend", label="create stopped API")
        identifier = self.stopped_api(config, expected_image)
        self.compose(config, "start", "--wait", "--wait-timeout", "180", "backend", label="API start", timeout=200)
        api = self.service("backend")
        require(api["id"] == identifier and api["image"] == expected_image, "running API identity mismatch")
        require(all(api["environment"].get(key) == self.old_api["environment"].get(key) for key in GATES),
                "running API effect gates changed")
        self.source_proof(identifier, manifest)
        self.schema(identifier)
        self.health(self.profile["candidate_sha"] if expected_image == self.new_image else None)

    def rollback(self, candidate_file, rollback_file):
        # Repeated console signals must not interrupt the bounded containment/recovery.
        handlers = {number: signal.signal(number, signal.SIG_IGN)
                    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        try:
            self.compose(candidate_file, "stop", "--timeout", "30", "backend",
                         label="candidate API containment")
            self.invariants()
            self.schema(config=rollback_file, manifest=self.profile["legacy_manifest"])
            self.create_api(rollback_file, self.old_api["image"], self.profile["legacy_manifest"])
            self.invariants()
            self.receipt("failed_rollback_verified")
        finally:
            for number, handler in handlers.items():
                signal.signal(number, handler)

    @staticmethod
    def http_health(expected_sha):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for route in ("health", "ready"):
            try:
                with opener.open("http://127.0.0.1:8000/" + route, timeout=10) as response:
                    payload = json.load(response)
                    expected_status = {"ok"} if route == "health" else {"ready", "degraded"}
                    require(response.status == 200 and isinstance(payload, dict)
                            and payload.get("status") in expected_status,
                            "API health unavailable")
                    if route == "ready":
                        require(payload.get("required") == {"database": "ok", "redis": "ok"},
                                "API required dependencies unavailable")
                    if expected_sha:
                        require(response.headers.get("X-Backend-Release") == expected_sha,
                                "API release header mismatch")
            except (OSError, ValueError):
                raise Refused("API health unavailable") from None

    def receipt(self, status):
        value = {"status": status, "candidate_sha": self.profile["candidate_sha"],
                 "legacy_sha": LEGACY_SHA, "api_only": True,
                 "old_api_image": self.old_api["image"] if self.old_api else None,
                 "new_api_image": self.new_image,
                 "candidate_archive_sha256": self.profile["candidate_archive_sha256"],
                 "profile_sha256": hashlib.sha256(json.dumps(self.profile, sort_keys=True,
                                                separators=(",", ":")).encode()).hexdigest(),
                 "preserved_services": {name: {key: state[key] for key in ("id", "image", "started", "restarts")}
                                        for name, state in self.protected.items()},
                 "observed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        if self.candidate:
            path = self.candidate / "receipt.json"
            temporary = self.candidate / "receipt.next"
            with temporary.open("w", encoding="utf-8") as out:
                os.chmod(temporary, 0o600)
                json.dump(value, out, separators=(",", ":"))
            temporary.replace(path)

    def run(self):
        validate_profile(self.profile)
        require(self.current_link.resolve() == self.legacy_deploy.parent, "unexpected legacy release pointer")
        require(self.checker.is_file() and not self.checker.is_symlink(), "schema checker unavailable")
        require(not self.release_root.is_symlink(), "maintenance root aliased")
        self.release_root.mkdir(mode=0o700, parents=False, exist_ok=True)
        root_stat = self.release_root.stat()
        require(root_stat.st_uid == os.geteuid() and not root_stat.st_mode & 0o077,
                "maintenance root permissions unsafe")
        lock_path = self.release_root / "release.lock"
        require(not lock_path.is_symlink(), "release lock aliased")
        with lock_path.open("a") as self.lock:
            os.chmod(lock_path, 0o600)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise Refused("another maintenance release holds the lock") from None
            return self._run()

    def _run(self):
        self.capabilities()
        self.config_files = self.file_snapshot()
        self.old_api = self.service("backend")
        validate_gates(self.old_api["environment"])
        self.protected = {name: self.service(name) for name in PROTECTED}
        for container in [self.old_api, *(self.protected[name] for name in PROTECTED[:3])]:
            self.source_proof(container["id"], self.profile["legacy_manifest"])
        build_root = self.legacy_deploy.parent / "backend"
        actual_build = {"Dockerfile"} | {str(path.relative_to(build_root))
                                      for path in (build_root / "migrations").glob("*.sql")}
        if (build_root / ".dockerignore").exists():
            actual_build.add(".dockerignore")
        require(actual_build == self.profile["legacy_build_manifest"].keys(),
                "legacy build source set mismatch")
        for path, expected in self.profile["legacy_build_manifest"].items():
            source = build_root / path
            require(source.is_file() and not source.is_symlink() and digest(source) == expected,
                    "legacy build source mismatch")
        self.schema(self.old_api["id"])
        self.health(None)
        self.extract()
        resolved = compose_dollars(json.loads(self.compose(self.legacy_deploy / "docker-compose.yml", "config", "--format", "json",
                                                          label="private resolved Compose")), escape=False)
        require(isinstance(resolved, dict) and isinstance(resolved.get("services"), dict)
                and "backend" in resolved["services"], "resolved Compose malformed")
        rollback_file = self.private_json("rollback-compose.json", self.api_config(resolved, self.old_api["image"]))
        tag = "pastorai-backend:maintenance-" + self.profile["candidate_sha"]
        existing = self.runner(["docker", "image", "ls", "--quiet", "--no-trunc", tag], label="candidate tag check").strip()
        require(not existing, "candidate image tag already exists")
        candidate_config = self.api_config(resolved, tag, build=True)
        candidate_file = self.private_json("candidate-compose.json", candidate_config)
        self.invariants()
        self.compose(candidate_file, "build", "backend", label="candidate API image build", timeout=900)
        self.new_image = self.runner(["docker", "image", "inspect", "--format", "{{.Id}}", tag],
                                     label="candidate image identity").strip()
        require(bool(IMAGE.fullmatch(self.new_image)) and self.new_image != self.old_api["image"],
                "candidate image unverifiable")
        candidate_config["services"]["backend"]["image"] = self.new_image
        candidate_config["services"]["backend"].pop("build", None)
        candidate_file = self.private_json("candidate-pinned-compose.json", candidate_config)
        self.schema(config=candidate_file)
        self.invariants()
        require(self.service("backend") == self.old_api, "API changed before replacement")
        try:
            self.compose(candidate_file, "stop", "--timeout", "30", "backend", label="graceful API stop")
            self.create_api(candidate_file, self.new_image, self.profile["candidate_manifest"])
            self.invariants()
            self.receipt("complete")
            return "complete"
        except BaseException:
            try:
                self.rollback(candidate_file, rollback_file)
            except BaseException:
                self.receipt("failed_rollback_incomplete")
                raise Refused("API maintenance failed; rollback requires console recovery") from None
            raise Refused("API maintenance failed; immutable legacy rollback verified") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=Path(__file__).with_name("maintenance-profile.json"))
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)

    def interrupted(_signum, _frame):
        raise Refused("maintenance interrupted")

    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupted)
    try:
        require(os.geteuid() == 0, "authenticated root console required")
        profile = json.loads(args.profile.read_text(encoding="utf-8"))
        release = Release(profile, args.archive)
        status = release.run()
        print("maintenance API release " + status + ": " + profile["candidate_sha"])
        return 0
    except Refused as error:
        print(str(error), file=sys.stderr)
        return 1
    except BaseException as error:
        print("maintenance refused: " + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
