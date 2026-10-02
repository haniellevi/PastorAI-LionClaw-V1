"""API maintenance orchestration, using synthetic files and a fake Docker engine."""

from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
import copy
import fcntl
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


MODULE = Path(__file__).resolve().parents[1] / "maintenance-release.py"
SPEC = importlib.util.spec_from_file_location("maintenance_release", MODULE)
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)
CANDIDATE_SHA = "a" * 40
OLD_IMAGE = "sha256:" + "1" * 64
NEW_IMAGE = "sha256:" + "2" * 64
PRIVATE_SENTINEL = "synthetic-private-value-never-print"


def sha(content):
    return hashlib.sha256(content).hexdigest()


def proof_manifest(source):
    tree = ast.parse(source)
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == "expected"
                              for target in node.targets))
    return json.loads(ast.literal_eval(assignment.value.args[0]))


class FakeDocker:
    """The fake mutates only its API record, never runs a command or opens a socket."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.events = []
        self.counts = {}
        self.hooks = {}
        self.created = 0
        self.states = {}
        for number, name in enumerate(("backend", *driver.PROTECTED), 3):
            self.states[name] = {
                "Id": f"{number:064x}", "Image": OLD_IMAGE,
                "Config": {"Env": [f"{key}={value}" for key, value in fixture.environment.items()],
                           "Cmd": ["uvicorn", "app.main:app"], "Entrypoint": None},
                "State": {"Running": True, "Status": "running", "StartedAt": "synthetic-original"},
                "RestartCount": 0,
                "manifest": copy.deepcopy(fixture.profile["legacy_manifest"]),
            }
        self.protected_before = copy.deepcopy({name: self.states[name] for name in driver.PROTECTED})
        self.resolved = {
            "name": "pastorai", "services": {
                name: {"image": "pastorai-backend:latest", "environment": dict(fixture.environment),
                       "build": {"context": str(fixture.legacy.parent / "backend")},
                       "ports": ["127.0.0.1:8000:8000"] if name == "backend" else []}
                for name in ("backend", *driver.PROTECTED)
            },
        }
        self.resolved["services"]["backend"]["depends_on"] = {"redis": {"condition": "service_started", "required": True}}

    def __call__(self, args, *, label, input=None, timeout=180):
        self.events.append({"args": list(args), "label": label, "input": input, "timeout": timeout})
        self.counts[label] = self.counts.get(label, 0) + 1
        if label in self.hooks:
            self.hooks[label](self, self.counts[label])
        if args == ["docker", "compose", "version", "--short"]:
            return "5.0.0\n"
        if args == ["docker", "compose", "start", "--help"]:
            return " --wait Wait for healthy services\n --wait-timeout integer\n"
        if args[:2] == ["docker", "inspect"]:
            row = next(state for state in self.states.values() if state["Id"] == args[2])
            return json.dumps([{key: value for key, value in row.items() if key != "manifest"}])
        if args[:3] == ["docker", "image", "ls"]:
            return ""
        if args[:3] == ["docker", "image", "inspect"]:
            return NEW_IMAGE + "\n"
        if args[:2] == ["docker", "exec"]:
            if label == "runtime source proof":
                row = next(state for state in self.states.values() if state["Id"] == args[3])
                driver.require(row["manifest"] == proof_manifest(input), "runtime source proof failed")
            return "aggregate PASS\n"
        if args[:2] != ["docker", "compose"] or "--file" not in args:
            raise AssertionError("unexpected fake command")
        index = args.index("--file")
        config_path = Path(args[index + 1])
        command = args[index + 2:]
        action = command[0]
        if action == "ps":
            return self.states[command[-1]]["Id"] + "\n"
        if action == "config":
            return json.dumps(driver.compose_dollars(self.resolved, escape=True))
        if action == "build":
            self.assert_api_only(command)
            return "synthetic build\n"
        if action == "run":
            config = driver.compose_dollars(json.loads(config_path.read_text()), escape=False)
            image = config["services"]["backend"]["image"]
            expected = (self.fixture.profile["candidate_manifest"] if image == NEW_IMAGE
                        else self.fixture.profile["legacy_manifest"])
            driver.require(proof_manifest(input) == expected, "image read-only schema check failed")
            assert "--rm" in command and "--no-deps" in command and "--entrypoint" in command
            assert command[command.index("--entrypoint") + 1] == "python"
            return "aggregate PASS\n"
        if action == "stop":
            self.assert_api_only(command)
            self.states["backend"]["State"].update(Running=False, Status="exited")
            return ""
        if action == "up":
            self.assert_api_only(command)
            assert "--no-start" in command and "--no-build" in command and "--no-deps" in command
            assert command[command.index("--pull") + 1] == "never"
            backend = driver.compose_dollars(json.loads(config_path.read_text()), escape=False)["services"]["backend"]
            self.created += 1
            self.states["backend"] = {
                "Id": f"{100 + self.created:064x}", "Image": backend["image"],
                "Config": {"Env": [f"{key}={value}" for key, value in backend["environment"].items()],
                           "Cmd": backend["command"], "Entrypoint": backend["entrypoint"]},
                "State": {"Running": False, "Status": "created", "StartedAt": "synthetic-created"},
                "RestartCount": 0,
                "manifest": copy.deepcopy(self.fixture.profile["candidate_manifest"]
                                          if backend["image"] == NEW_IMAGE
                                          else self.fixture.profile["legacy_manifest"]),
            }
            return ""
        if action == "start":
            self.assert_api_only(command)
            assert "--wait" in command and "--wait-timeout" in command
            assert "depends_on" not in json.loads(config_path.read_text())["services"]["backend"]
            self.states["backend"]["State"].update(Running=True, Status="running", StartedAt="synthetic-new")
            return ""
        raise AssertionError("unexpected fake Compose action")

    @staticmethod
    def assert_api_only(command):
        assert command[-1] == "backend"


class Fixture:
    def __init__(self, root):
        self.root = root
        self.legacy = root / "releases" / driver.LEGACY_SHA / "deploy"
        self.legacy.mkdir(parents=True)
        self.current = root / "current"
        self.current.symlink_to(self.legacy.parent)
        self.release_root = root / "maintenance"
        self.checker = root / "checker.fixture.py"
        self.checker.write_text("# SYNTHETIC READ ONLY CHECKER\n")
        self.config_fixture = self.legacy / "configuration.fixture"
        self.config_fixture.write_text("synthetic configuration, no credentials\n")
        self.environment = {
            "DATABASE_URL": PRIVATE_SENTINEL, "ALLOW_REAL_SENDS": "true",
            "ASAAS_BILLING_ENABLED": "false", "BREVO_SEND_MODE": "off",
            "BROADCAST_ASYNC_ENABLED": "false", "PATH": "/synthetic/bin",
            "SYNTHETIC_DOLLARS": "literal$var/${TOKEN}/double$$/triple$$$",
        }
        self.files = {
            "app/db/models.py": b"# synthetic models\n",
            "app/routers/whatsapp.py": b"# synthetic queue protocol\n",
            "app/workers/queue_worker.py": b"# synthetic queue worker\n",
            "app/workers/cron_worker.py": b"# synthetic cron worker\n",
            "app/workers/broadcast_worker.py": b"# synthetic broadcast worker\n",
            "app/main.py": b"# synthetic old API\n",
            "requirements.lock": b"# synthetic locked dependencies\n",
        }
        self.build = {"Dockerfile": b"# synthetic Dockerfile\n",
                      ".dockerignore": b"# synthetic ignore\n",
                      "migrations/0001_fixture.sql": b"-- synthetic migration, never executed\n",
                      "migrations/private_runtime/20260905_035815_load_private_runtime_turn_context.sql":
                          b"-- synthetic nested migration, never executed\n"}
        for path, content in self.build.items():
            target = self.legacy.parent / "backend" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        self.candidate_files = dict(self.files, **{"app/main.py": b"# synthetic optimized API\n"})
        self.profile = {
            "version": 1, "legacy_sha": driver.LEGACY_SHA, "candidate_sha": CANDIDATE_SHA,
            "candidate_archive_sha256": "0" * 64, "archive_root": "fixture-" + CANDIDATE_SHA,
            "legacy_manifest": {path: sha(content) for path, content in self.files.items()},
            "candidate_manifest": {path: sha(content) for path, content in self.candidate_files.items()},
            "allowed_changed_files": ["app/main.py"], "allowed_new_files": [],
            "legacy_build_manifest": {path: sha(content) for path, content in self.build.items()},
            "candidate_build_manifest": {path: sha(content) for path, content in self.build.items()},
            "schema": {"synthetic": True},
        }
        self.archive = root / "candidate.tar.gz"
        self.write_archive()
        self.runner = FakeDocker(self)
        self.health_calls = []
        self.health_hook = None
        self.release = driver.Release(self.profile, self.archive, runner=self.runner,
                                      legacy_deploy=self.legacy, current_link=self.current,
                                      release_root=self.release_root, checker=self.checker, health=self.health)
        # Protected runtime .env is never opened in these tests; only this public fixture is hashed.
        self.release.file_snapshot = lambda: {str(self.config_fixture): driver.digest(self.config_fixture)}

    def health(self, expected):
        self.health_calls.append(expected)
        if self.health_hook:
            self.health_hook(expected)

    def write_archive(self, extras=()):
        with tarfile.open(self.archive, "w:gz") as archive:
            for path, content in (self.candidate_files | self.build).items():
                member = tarfile.TarInfo(self.profile["archive_root"] + "/backend/" + path)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
            readme = tarfile.TarInfo(self.profile["archive_root"] + "/backend/migrations/README.md")
            archive.addfile(readme, io.BytesIO(b""))
            for name, content, kind in extras:
                member = tarfile.TarInfo(name)
                member.size = len(content)
                member.type = kind
                member.linkname = "/synthetic/unsafe"
                archive.addfile(member, io.BytesIO(content) if kind == tarfile.REGTYPE else None)
        self.profile["candidate_archive_sha256"] = driver.digest(self.archive)

    def labels(self):
        return [event["label"] for event in self.runner.events]

    def receipt(self):
        return json.loads((self.release.candidate / "receipt.json").read_text())


class MaintenanceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="maintenance-synthetic-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture(Path(self.temp.name))
        self.release = self.fixture.release

    def assert_preserved(self):
        fixture = self.fixture
        self.assertEqual({name: fixture.runner.states[name] for name in driver.PROTECTED},
                         fixture.runner.protected_before)
        self.assertEqual(fixture.current.resolve(), fixture.legacy.parent)
        self.assertEqual(fixture.config_fixture.read_text(), "synthetic configuration, no credentials\n")
        for event in fixture.runner.events:
            if event["label"] in {"create stopped API", "API start", "graceful API stop",
                                   "candidate API containment", "candidate API image build"}:
                self.assertEqual(event["args"][-1], "backend")
            self.assertNotIn("pastorai-backend:latest", event["args"])
            self.assertNotIn("apply_migrations.py", " ".join(event["args"]))

    def test_placeholder_profile_fails_before_any_command(self):
        self.fixture.profile["candidate_sha"] = None
        with self.assertRaisesRegex(driver.Refused, "SHA unpinned"):
            self.release.run()
        self.assertEqual(self.fixture.runner.events, [])
        self.assertFalse(self.fixture.release_root.exists())

    def test_missing_or_invalid_effect_gates_refuse_before_build_or_stop(self):
        original = self.fixture.runner.states["backend"]["Config"]["Env"]
        for key in driver.GATES:
            with self.subTest(key=key):
                self.fixture.runner.states["backend"]["Config"]["Env"] = [entry for entry in original if not entry.startswith(key + "=")]
                with self.assertRaisesRegex(driver.Refused, "effect gate missing"):
                    self.release.run()
        self.fixture.runner.states["backend"]["Config"]["Env"] = original
        for key, invalid in (("ALLOW_REAL_SENDS", "unexpected"), ("ASAAS_BILLING_ENABLED", ""),
                             ("BROADCAST_ASYNC_ENABLED", "1"), ("BREVO_SEND_MODE", "disabled")):
            with self.subTest(key=key):
                self.fixture.runner.states["backend"]["Config"]["Env"] = [entry if not entry.startswith(key + "=") else key + "=" + invalid for entry in original]
                with self.assertRaisesRegex(driver.Refused, "effect gate value invalid"):
                    self.release.run()
        self.assertNotIn("candidate API image build", self.fixture.labels())
        self.assertNotIn("graceful API stop", self.fixture.labels())

    def test_worker_model_webhook_and_build_changes_are_rejected(self):
        fixture = self.fixture
        for path in ("app/db/models.py", "app/routers/whatsapp.py", "app/workers/queue_worker.py"):
            with self.subTest(path=path):
                profile = copy.deepcopy(fixture.profile)
                profile["candidate_manifest"][path] = "f" * 64
                if path.endswith(".py"):
                    profile["allowed_changed_files"].append(path)
                with self.assertRaises(driver.Refused):
                    driver.validate_profile(profile)
        profile = copy.deepcopy(fixture.profile)
        profile["candidate_build_manifest"]["migrations/0001_fixture.sql"] = "f" * 64
        with self.assertRaisesRegex(driver.Refused, "build contract"):
            driver.validate_profile(profile)
        self.assertEqual(fixture.runner.events, [])

    def test_dependency_delta_accepts_only_exact_reviewed_main_lock_and_source_sha(self):
        profile = copy.deepcopy(self.fixture.profile)
        profile["allowed_changed_files"].append("requirements.lock")
        profile["candidate_manifest"]["requirements.lock"] = driver.DEPENDENCY_UPDATE_DIGEST
        profile["dependency_update_source_sha"] = driver.DEPENDENCY_UPDATE_SHA
        driver.validate_profile(profile)
        for key, wrong in (("dependency_update_source_sha", "f" * 40),
                           ("candidate_manifest", profile["candidate_manifest"] | {"requirements.lock": "f" * 64})):
            with self.subTest(key=key):
                mutated = copy.deepcopy(profile)
                mutated[key] = wrong
                with self.assertRaisesRegex(driver.Refused, "reviewed lock"):
                    driver.validate_profile(mutated)

    def test_unused_allowlist_permission_is_rejected(self):
        self.fixture.profile["allowed_changed_files"].append("app/unused.py")
        with self.assertRaisesRegex(driver.Refused, "exact allowlist"):
            self.release.run()
        self.assertEqual(self.fixture.runner.events, [])

    def test_manifest_and_allowlist_malformed_input_fails_closed(self):
        for key, value in (("allowed_new_files", [{}]), ("candidate_manifest", {}),
                           ("candidate_build_manifest", {"../Dockerfile": "f" * 64})):
            with self.subTest(key=key):
                profile = copy.deepcopy(self.fixture.profile)
                profile[key] = value
                with self.assertRaises(driver.Refused):
                    driver.validate_profile(profile)

    def test_success_updates_only_api_by_immutable_image_and_records_no_secrets(self):
        self.assertEqual(self.release.run(), "complete")
        fixture = self.fixture
        self.assertEqual(fixture.runner.states["backend"]["Image"], NEW_IMAGE)
        self.assertEqual(fixture.runner.states["backend"]["Config"]["Env"],
                         [f"{key}={value}" for key, value in (fixture.environment | {"PASTORAI_RELEASE_SHA": CANDIDATE_SHA}).items()])
        self.assert_preserved()
        labels = fixture.labels()
        self.assertLess(labels.index("image read-only schema check"), labels.index("graceful API stop"))
        self.assertEqual(labels.count("runtime source proof"), 5)
        self.assertEqual(fixture.health_calls, [None, CANDIDATE_SHA])
        receipt = fixture.receipt()
        self.assertEqual(receipt["status"], "complete")
        self.assertEqual(receipt["old_api_image"], OLD_IMAGE)
        self.assertEqual(receipt["new_api_image"], NEW_IMAGE)
        self.assertEqual(set(receipt["preserved_services"]), set(driver.PROTECTED))
        self.assertNotIn(PRIVATE_SENTINEL, json.dumps(receipt))
        for path in fixture.release_root.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o077, 0, str(path))

    def test_real_compose_config_preserves_literal_dollars_in_environment_and_commands(self):
        fixture = self.fixture
        fixture.release_root.mkdir(mode=0o700)
        self.release.candidate = fixture.release_root
        command = ["synthetic", "$var", "${TOKEN}", "double$$", "triple$$$"]
        config = {"services": {"backend": {"image": "synthetic:unused", "environment": dict(fixture.environment),
                                             "command": command, "entrypoint": ["$literal"]}}}
        path = self.release.private_json("dollars-compose.json", config)
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("COMPOSE_", "DOCKER_"))}
        environment.update(TOKEN="must-never-replace", var="must-never-replace")
        docker_config = fixture.root / "docker-configuration.fixture"
        docker_config.mkdir(mode=0o700)
        environment["DOCKER_CONFIG"] = str(docker_config)
        try:
            result = subprocess.run(["docker", "compose", "--env-file", "/dev/null", "--project-directory",
                                     str(fixture.root), "--file", str(path), "config", "--format", "json"],
                                    capture_output=True, text=True, check=False, cwd=fixture.root,
                                    env=environment, timeout=15)
        except FileNotFoundError:
            self.skipTest("local Docker Compose CLI unavailable; no daemon required")
        self.assertEqual(result.returncode, 0, "synthetic Compose config validation failed")
        resolved = driver.compose_dollars(json.loads(result.stdout), escape=False)["services"]["backend"]
        self.assertEqual(resolved["environment"], fixture.environment)
        self.assertEqual(resolved["command"], command)
        self.assertEqual(resolved["entrypoint"], ["$literal"])
        self.assertNotIn("must-never-replace", result.stdout)

    def test_bad_archive_digest_keeps_old_api_running(self):
        self.fixture.profile["candidate_archive_sha256"] = "f" * 64
        with self.assertRaisesRegex(driver.Refused, "archive digest mismatch"):
            self.release.run()
        self.assertNotIn("candidate API image build", self.fixture.labels())
        self.assertNotIn("graceful API stop", self.fixture.labels())
        self.assert_preserved()

    def test_unsafe_extra_duplicate_and_symlink_tar_members_rejected_before_build(self):
        fixture = self.fixture
        prefix = fixture.profile["archive_root"]
        scenarios = [
            (prefix + "/backend/../../escape", b"x", tarfile.REGTYPE),
            (prefix + "/backend/app/extra.py", b"x", tarfile.REGTYPE),
            (prefix + "/backend/migrations/0002_unreviewed.sql", b"x", tarfile.REGTYPE),
            (prefix + "/backend/migrations/private_runtime/0002_unreviewed.sql", b"x", tarfile.REGTYPE),
            (prefix + "/backend/migrations/private_runtime/../escape.sql", b"x", tarfile.REGTYPE),
            (prefix + "/backend/app/main.py", b"duplicate", tarfile.REGTYPE),
            (prefix + "/unrelated-link", b"", tarfile.SYMTYPE),
        ]
        for number, extra in enumerate(scenarios):
            with self.subTest(extra=extra[0]):
                fixture.write_archive([extra])
                release = driver.Release(fixture.profile, fixture.archive,
                                         release_root=fixture.root / ("extract-" + str(number)))
                with self.assertRaises(driver.Refused):
                    release.extract()

    def test_candidate_source_bytes_and_legacy_migration_set_are_checked(self):
        self.fixture.candidate_files["app/main.py"] = b"# changed after review\n"
        self.fixture.write_archive()
        with self.assertRaisesRegex(driver.Refused, "archive source proof"):
            self.release.run()
        self.assertNotIn("graceful API stop", self.fixture.labels())
        self.assert_preserved()

    def test_nested_migration_payload_is_preserved(self):
        try:
            result = self.release.run()
        except driver.Refused as error:
            self.fail("reviewed nested migration refused: " + str(error))
        self.assertEqual(result, "complete")
        path = "migrations/private_runtime/20260905_035815_load_private_runtime_turn_context.sql"
        extracted = self.release.candidate / "backend" / path
        self.assertEqual(extracted.read_bytes(), self.fixture.build[path])
        self.assertEqual(driver.digest(extracted), self.fixture.profile["candidate_build_manifest"][path])
        self.assert_preserved()

    def test_unsafe_nested_manifest_paths_are_rejected(self):
        for path in ("migrations/private_runtime/../escape.sql", "migrations//extra.sql",
                     "migrations/private_runtime/.hidden.sql", "migrations/private_runtime/link\\extra.sql"):
            with self.subTest(path=path):
                profile = copy.deepcopy(self.fixture.profile)
                profile["legacy_build_manifest"][path] = "f" * 64
                profile["candidate_build_manifest"][path] = "f" * 64
                with self.assertRaisesRegex(driver.Refused, "build manifest incomplete"):
                    driver.validate_profile(profile)

    def test_extra_legacy_migration_refuses_before_build_or_stop(self):
        for path in ("migrations/0002_unreviewed.sql", "migrations/private_runtime/0002_unreviewed.sql"):
            with self.subTest(path=path):
                extra = self.fixture.legacy.parent / "backend" / path
                extra.write_text("-- synthetic unreviewed\n")
                with self.assertRaisesRegex(driver.Refused, "build source set mismatch"):
                    self.release.run()
                extra.unlink()
        self.assertNotIn("candidate API image build", self.fixture.labels())
        self.assertNotIn("graceful API stop", self.fixture.labels())

    def test_runtime_source_drift_fails_before_restart(self):
        self.fixture.runner.states["queue-worker"]["manifest"]["app/main.py"] = "f" * 64
        with self.assertRaisesRegex(driver.Refused, "runtime source proof failed"):
            self.release.run()
        self.assertNotIn("graceful API stop", self.fixture.labels())

    def test_build_and_candidate_schema_failures_leave_api_active(self):
        for label in ("candidate API image build", "image read-only schema check"):
            with self.subTest(label=label), tempfile.TemporaryDirectory(prefix="maintenance-failure-") as root:
                fixture = Fixture(Path(root))
                def fail(_runner, _count):
                    raise driver.Refused("synthetic preflight failure")
                fixture.runner.hooks[label] = fail
                with self.assertRaisesRegex(driver.Refused, "synthetic preflight failure"):
                    fixture.release.run()
                self.assertNotIn("graceful API stop", fixture.labels())
                self.assertTrue(fixture.runner.states["backend"]["State"]["Running"])
                self.assertEqual(fixture.runner.states["backend"]["Image"], OLD_IMAGE)

    def test_failed_candidate_health_prechecks_and_restores_immutable_old_api(self):
        fixture = self.fixture
        def health(expected):
            if expected:
                raise driver.Refused("synthetic candidate health failure")
        fixture.health_hook = health
        with self.assertRaisesRegex(driver.Refused, "immutable legacy rollback verified"):
            self.release.run()
        self.assert_preserved()
        self.assertEqual(fixture.runner.states["backend"]["Image"], OLD_IMAGE)
        self.assertTrue(fixture.runner.states["backend"]["State"]["Running"])
        self.assertEqual(fixture.runner.states["backend"]["Config"]["Env"],
                         [f"{key}={value}" for key, value in fixture.environment.items()])
        self.assertEqual(fixture.labels().count("candidate API image build"), 1)
        containment = fixture.labels().index("candidate API containment")
        rollback_precheck = fixture.labels().index("image read-only schema check", containment)
        rollback_create = fixture.labels().index("create stopped API", rollback_precheck)
        self.assertLess(rollback_precheck, rollback_create)
        self.assertEqual(fixture.receipt()["status"], "failed_rollback_verified")

    def test_rollback_schema_failure_keeps_api_contained(self):
        fixture = self.fixture
        fixture.health_hook = lambda expected: (_ for _ in ()).throw(driver.Refused("synthetic health failure")) if expected else None
        def image_check(_runner, count):
            if count == 2:
                raise driver.Refused("synthetic rollback schema drift")
        fixture.runner.hooks["image read-only schema check"] = image_check
        with self.assertRaisesRegex(driver.Refused, "requires console recovery"):
            self.release.run()
        self.assertFalse(fixture.runner.states["backend"]["State"]["Running"])
        self.assertEqual(fixture.labels().count("create stopped API"), 1)
        self.assertEqual(fixture.receipt()["status"], "failed_rollback_incomplete")
        self.assert_preserved()

    def test_stopped_candidate_environment_drift_never_starts_candidate(self):
        fixture = self.fixture
        def inspect(runner, count):
            if count == 1:
                runner.states["backend"]["Config"]["Env"].append("UNREVIEWED_CONFIG=synthetic")
        fixture.runner.hooks["stopped API inspection"] = inspect
        with self.assertRaisesRegex(driver.Refused, "immutable legacy rollback verified"):
            self.release.run()
        self.assertEqual(fixture.labels().count("API start"), 1)
        self.assertEqual(fixture.runner.states["backend"]["Image"], OLD_IMAGE)
        self.assert_preserved()

    def test_configuration_or_worker_drift_blocks_restart(self):
        for kind in ("config", "worker"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(prefix="maintenance-drift-") as root:
                fixture = Fixture(Path(root))
                def drift(runner, _count):
                    if kind == "config":
                        fixture.config_fixture.write_text("synthetic changed configuration")
                    else:
                        runner.states["cron-worker"]["RestartCount"] += 1
                fixture.runner.hooks["image read-only schema check"] = drift
                with self.assertRaisesRegex(driver.Refused, "configuration changed|protected service changed"):
                    fixture.release.run()
                self.assertNotIn("graceful API stop", fixture.labels())
                self.assertTrue(fixture.runner.states["backend"]["State"]["Running"])

    def test_interruption_recovers_and_ignores_repeated_signals_during_rollback(self):
        fixture = self.fixture
        original = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        def fail_start(_runner, count):
            if count == 1:
                raise driver.Refused("synthetic SIGTERM")
        def contained(_runner, _count):
            self.assertTrue(all(signal.getsignal(number) == signal.SIG_IGN for number in original))
        fixture.runner.hooks["API start"] = fail_start
        fixture.runner.hooks["candidate API containment"] = contained
        with self.assertRaisesRegex(driver.Refused, "immutable legacy rollback verified"):
            self.release.run()
        self.assertTrue(all(signal.getsignal(number) == handler for number, handler in original.items()))
        self.assertEqual(fixture.runner.states["backend"]["Image"], OLD_IMAGE)
        self.assert_preserved()

    def test_containment_failure_does_not_start_old_api(self):
        fixture = self.fixture
        fixture.health_hook = lambda expected: (_ for _ in ()).throw(driver.Refused("synthetic health failure")) if expected else None
        def fail(_runner, _count):
            raise driver.Refused("synthetic stop unavailable")
        fixture.runner.hooks["candidate API containment"] = fail
        with self.assertRaisesRegex(driver.Refused, "requires console recovery"):
            self.release.run()
        self.assertEqual(fixture.labels().count("create stopped API"), 1)
        self.assertEqual(fixture.receipt()["status"], "failed_rollback_incomplete")

    def test_compose_version_and_wait_capabilities_fail_before_build(self):
        for response, expected in (("4.9.0", "5.0.0"), ("5.0.0", "wait unavailable")):
            with self.subTest(response=response), tempfile.TemporaryDirectory(prefix="maintenance-compose-") as root:
                fixture = Fixture(Path(root))
                base = fixture.runner
                def runner(args, **kwargs):
                    if kwargs["label"] == "Compose version":
                        return response
                    if kwargs["label"] == "Compose start capabilities":
                        return " --wait-timeout integer\n"
                    return base(args, **kwargs)
                fixture.release.runner = runner
                with self.assertRaisesRegex(driver.Refused, expected):
                    fixture.release.run()
                self.assertNotIn("candidate API image build", fixture.labels())

    def test_exclusive_lock_rejects_concurrent_release_without_commands(self):
        root = self.fixture.release_root
        root.mkdir(mode=0o700)
        with (root / "release.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(driver.Refused, "holds the lock"):
                self.release.run()
        self.assertEqual(self.fixture.runner.events, [])

    def test_runner_never_exposes_private_subprocess_output_or_error(self):
        fake = subprocess.CompletedProcess(["synthetic"], 1, PRIVATE_SENTINEL, PRIVATE_SENTINEL)
        runner = driver.Runner()
        with patch.object(driver.subprocess, "run", return_value=fake):
            with self.assertRaises(driver.Refused) as raised:
                runner(["synthetic"], label="sanitized operation")
        self.assertEqual(str(raised.exception), "sanitized operation failed")
        with patch.object(driver.subprocess, "run", side_effect=subprocess.TimeoutExpired("synthetic", 1, PRIVATE_SENTINEL)):
            with self.assertRaises(driver.Refused) as raised:
                runner(["synthetic"], label="sanitized operation")
        self.assertNotIn(PRIVATE_SENTINEL, str(raised.exception))

    def test_cli_unknown_failure_prints_only_type(self):
        profile = self.fixture.root / "profile.fixture.json"
        profile.write_text(json.dumps(self.fixture.profile))
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(driver.sys, "argv", [str(MODULE), "--profile", str(profile), "--archive", str(self.fixture.archive)]), \
             patch.object(driver.os, "geteuid", return_value=0), \
             patch.object(driver.signal, "signal"), \
             patch.object(driver.Release, "run", side_effect=ValueError(PRIVATE_SENTINEL)), \
             redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(driver.main(), 1)
        self.assertEqual(stderr.getvalue(), "maintenance refused: ValueError\n")
        self.assertEqual(stdout.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
