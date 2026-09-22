"""Synthetic, offline tests for the descriptor-bound E4b local Git reader."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = BACKEND_ROOT / "scripts" / "e4b_authenticated_operational_projection.py"
ADAPTER_PATH = BACKEND_ROOT / "scripts" / "e4b_local_git_blob_reader.py"
CORE_MODULE_NAME = "e4b_authenticated_operational_projection"
ADAPTER_MODULE_NAME = "e4b_local_git_blob_reader"

_TEST_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "HOME": "/nonexistent",
    "LANG": "C",
    "LC_ALL": "C",
    "PATH": "/usr/bin:/bin",
    "TZ": "UTC",
}
_TEST_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_TEST_EXECUTABLE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def load_module(name: str, path: Path):
    sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("candidate module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def run_test_git(repository: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repository,
        env=_TEST_GIT_ENV,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        shell=False,
    )
    return completed.stdout


def git_output(repository: Path, *arguments: str) -> str:
    return run_test_git(repository, *arguments).decode("ascii").strip()


class ScriptedRunner:
    def __init__(self, adapter, outcomes) -> None:
        self._adapter = adapter
        self._outcomes = list(outcomes)
        self.calls: list[tuple[tuple[str, ...], str, object, float, int, tuple[int, ...]]] = []

    def __call__(
        self,
        argv: tuple[str, ...],
        *,
        cwd: str,
        environment: object,
        timeout_seconds: float,
        max_stdout_bytes: int,
        pass_fds: tuple[int, ...],
    ):
        self.calls.append((argv, cwd, environment, timeout_seconds, max_stdout_bytes, pass_fds))
        if not self._outcomes:
            raise AssertionError("unexpected local Git command")
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if type(outcome) is bytes:
            return self._adapter._GitCommandResult(returncode=0, stdout=outcome)
        return outcome


class FakeProcess:
    def __init__(self, stream) -> None:
        self.stdout = stream
        self.returncode = None
        self.kill_calls = 0
        self.wait_calls = 0
        self._alive = True

    def poll(self):
        return None if self._alive else self.returncode

    def kill(self) -> None:
        self.kill_calls += 1
        self._alive = False
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls += 1
        self._alive = False
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class PlainStream:
    def close(self) -> None:
        return None


class LocalGitBlobReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        executable = shutil.which("git")
        if executable is None:
            raise unittest.SkipTest("local Git executable unavailable")
        cls.git_executable = os.path.realpath(executable)
        cls.core = load_module(CORE_MODULE_NAME, CORE_PATH)
        cls.adapter = load_module(ADAPTER_MODULE_NAME, ADAPTER_PATH)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir="/tmp")
        self.parent = Path(self.temporary.name) / "parent"
        self.parent.mkdir(mode=0o700)
        self.repository = self.parent / "repository"
        self.repository.mkdir(mode=0o700)
        self.control = self.parent / "control"
        self.control.mkdir(mode=0o700)
        (self.control / "HEAD").write_text("ref: refs/heads/none\n", encoding="ascii")
        (self.control / "objects").mkdir(mode=0o700)
        (self.control / "refs").mkdir(mode=0o700)
        self.handles = []
        run_test_git(self.repository, "init", "--quiet")
        self._write_and_commit("backend/scripts/example.py", b"alpha\n", "initial")
        self.base = git_output(self.repository, "rev-parse", "HEAD")
        self._write_and_commit("backend/scripts/run.py", b"beta\n", "candidate")
        self.candidate = git_output(self.repository, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        for handle in self.handles:
            handle.close()
        self.temporary.cleanup()

    def _write_and_commit(self, relative_path: str, content: bytes, subject: str) -> None:
        target = self.repository / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        run_test_git(self.repository, "add", "--", relative_path)
        run_test_git(
            self.repository,
            "-c",
            "user.name=synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "--quiet",
            "-m",
            subject,
        )

    def _handle(self, *, executable: str | None = None):
        """Build a white-box capability for this test process only.

        ``object.__new__`` here is equivalent to arbitrary in-process code and
        is intentionally outside the runtime adapter threat model. No runtime
        API accepts these paths or descriptors to construct a handle.
        """

        git_fd: int | None = None
        objects_fd: int | None = None
        control_fd: int | None = None
        executable_fd: int | None = None
        try:
            git_fd = os.open(self.repository / ".git", _TEST_DIRECTORY_FLAGS)
            objects_fd = os.open("objects", _TEST_DIRECTORY_FLAGS, dir_fd=git_fd)
            control_fd = os.open(self.control, _TEST_DIRECTORY_FLAGS)
            executable_fd = os.open(
                self.git_executable if executable is None else executable,
                _TEST_EXECUTABLE_FLAGS,
            )
            self.adapter._assert_no_alternates(objects_fd)
            self.adapter._assert_private_control_directory(control_fd)
            handle = object.__new__(self.adapter.LocalGitRepositoryHandle)
            handle._objects_fd = objects_fd
            handle._objects_identity = self.adapter._directory_identity(objects_fd)
            handle._control_fd = control_fd
            handle._control_identity = self.adapter._directory_identity(control_fd)
            handle._executable_fd = executable_fd
            handle._executable_identity = self.adapter._executable_identity(executable_fd)
            handle._lock = threading.Lock()
            objects_fd = None
            control_fd = None
            executable_fd = None
            self.handles.append(handle)
            return handle
        finally:
            if git_fd is not None:
                os.close(git_fd)
            for descriptor in (objects_fd, control_fd, executable_fd):
                if descriptor is not None:
                    os.close(descriptor)

    def _reader(self, *, executable: str | None = None):
        return self.adapter.LocalGitBlobReader(self._handle(executable=executable))

    def _assert_error(self, code: str, callback) -> None:
        with self.assertRaises(self.core.ProjectionSourceError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def _poison_source_config(self) -> None:
        included = Path(self.temporary.name) / "included-config"
        included.write_text("[core\n", encoding="utf-8")
        source_config = self.repository / ".git" / "config"
        source_config.write_text(
            "[include]\n"
            f"\tpath = {included}\n"
            "[includeIf \"gitdir:**\"]\n"
            f"\tpath = {included}\n"
            "[extensions]\n"
            "\tworktreeConfig = true\n",
            encoding="utf-8",
        )
        (self.repository / ".git" / "config.worktree").write_text(
            "[core\n", encoding="utf-8"
        )

    def _wrapper(self, name: str, prelude: str = "") -> Path:
        executable = Path(self.temporary.name) / name
        executable.write_text(
            "#!/bin/sh\n" + prelude + "\nexec " + self.git_executable + ' "$@"\n',
            encoding="utf-8",
        )
        executable.chmod(0o700)
        return executable

    def test_import_is_inert_and_reader_requires_typed_handle(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("def _make_synthetic_handle_for_tests", source)
        self.assertNotIn("object.__new__(LocalGitRepositoryHandle)", source)
        self.assertNotIn("def _open_directory_path", source)
        self.assertNotIn("def _open_executable_path", source)
        module = types.ModuleType("e4b_local_git_blob_reader_inert")
        module.__file__ = str(ADAPTER_PATH)
        calls: list[object] = []

        def reject(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("import must not create a process")

        sys.modules[module.__name__] = module
        try:
            with patch("subprocess.Popen", reject):
                exec(compile(source, str(ADAPTER_PATH), "exec"), module.__dict__)
        finally:
            sys.modules.pop(module.__name__, None)
        self.assertEqual(calls, [])

        with patch.object(self.adapter.subprocess, "Popen", reject):
            for value in (str(self.repository), str(self.repository) + "\x00bad", object()):
                self._assert_error(
                    "LOCAL_GIT_HANDLE_REQUIRED",
                    lambda value=value: self.adapter.LocalGitBlobReader(value),
                )
            for arguments in ((), (str(self.repository),), (7, 8, 9)):
                self._assert_error(
                    "LOCAL_GIT_HANDLE_UNAVAILABLE",
                    lambda arguments=arguments: self.adapter.LocalGitRepositoryHandle(*arguments),
                )
            forged = object.__new__(self.adapter.LocalGitRepositoryHandle)
            reader = self.adapter.LocalGitBlobReader(forged)
            self._assert_error(
                "LOCAL_GIT_HANDLE_INVALID",
                lambda: reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV),
            )
        self.assertEqual(calls, [])

    def test_happy_path_is_descriptor_bound_and_derives_facts(self) -> None:
        reader = self._reader()
        facts = reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV)
        expected_digest = hashlib.sha256(
            b"E4B-LOCAL-GIT-ANCESTRY-V1\x00"
            + self.base.encode("ascii")
            + b"\x00"
            + self.candidate.encode("ascii")
            + b"\x00"
            + self.candidate.encode("ascii")
        ).hexdigest()
        self.assertEqual(facts.commit_sha, self.candidate)
        self.assertEqual(facts.tree_sha, git_output(self.repository, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(facts.parent_sha, self.base)
        self.assertEqual(facts.base_sha, self.base)
        self.assertEqual(facts.ancestry_digest_sha256, expected_digest)
        entries = reader.list_tree(facts.tree_sha, self.core.FIXED_GIT_ENV)
        selected = next(entry for entry in entries if entry.path == b"backend/scripts/run.py")
        self.assertEqual(reader.read_blob(selected.object_id, self.core.FIXED_GIT_ENV), b"beta\n")

    def test_parent_swap_repository_rename_and_git_symlink_after_handle_do_not_redirect(self) -> None:
        reader = self._reader()
        source_git = self.repository / ".git"
        held_git = self.repository / ".git-held"
        os.rename(source_git, held_git)
        outside = Path(self.temporary.name) / "outside"
        outside.mkdir(mode=0o700)
        os.symlink(outside, source_git)
        moved_parent = Path(self.temporary.name) / "moved-parent"
        os.rename(self.parent, moved_parent)
        os.symlink(outside, self.parent)
        self.assertEqual(
            reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV).commit_sha,
            self.candidate,
        )

    def test_runtime_exposes_no_path_or_descriptor_handle_constructor(self) -> None:
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                root = Path(self.temporary.name) / ("bad-" + kind)
                root.mkdir(mode=0o700)
                control = Path(self.temporary.name) / ("control-" + kind)
                control.mkdir(mode=0o700)
                if kind == "file":
                    (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
                else:
                    os.symlink(self.repository / ".git", root / ".git")
                with patch.object(self.adapter.subprocess, "Popen") as popen:
                    self._assert_error(
                        "LOCAL_GIT_HANDLE_UNAVAILABLE",
                        lambda: self.adapter.LocalGitRepositoryHandle(
                            str(root), str(control), self.git_executable
                        ),
                    )
                popen.assert_not_called()
        with patch.object(self.adapter.subprocess, "Popen") as popen:
            self._assert_error(
                "LOCAL_GIT_HANDLE_UNAVAILABLE",
                lambda: self.adapter.LocalGitRepositoryHandle(
                    str(self.repository) + "\x00bad", str(self.control), self.git_executable
                ),
            )
        popen.assert_not_called()

    def test_alternates_file_and_environment_are_rejected_or_absent_before_process(self) -> None:
        info = self.repository / ".git" / "objects" / "info"
        info.mkdir(exist_ok=True)
        alternates = info / "alternates"
        alternates.write_text("/outside\n", encoding="utf-8")
        with patch.object(self.adapter.subprocess, "Popen") as popen:
            self._assert_error("LOCAL_GIT_ALTERNATES_PRESENT", self._handle)
        popen.assert_not_called()

        alternates.unlink()
        reader = self._reader()
        alternates.write_text("/outside\n", encoding="utf-8")
        with patch.object(self.adapter, "_run_git_command") as runner:
            self._assert_error(
                "LOCAL_GIT_ALTERNATES_PRESENT",
                lambda: reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV),
            )
        runner.assert_not_called()

        alternates.unlink()
        tree = "b" * 40
        runner = ScriptedRunner(
            self.adapter,
            [
                tree.encode("ascii") + b"\n",
                b"100644 blob " + b"1" * 40 + b" 1\tbackend/scripts/a.py\x00",
            ],
        )
        with patch.dict(os.environ, {"GIT_ALTERNATE_OBJECT_DIRECTORIES": "/outside"}):
            with patch.object(self.adapter, "_run_git_command", runner):
                self._reader().list_tree(tree, self.core.FIXED_GIT_ENV)
        self.assertNotIn("GIT_ALTERNATE_OBJECT_DIRECTORIES", dict(runner.calls[0][2]))

    def test_source_local_include_conditional_worktree_and_runtime_config_swap_are_ignored(self) -> None:
        self._poison_source_config()
        source_config = self.repository / ".git" / "config"
        wrapper = self._wrapper(
            "config-swap-git",
            "printf '[core\\n' > '" + str(source_config) + "'",
        )
        reader = self._reader(executable=str(wrapper))
        self.assertEqual(
            reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV).commit_sha,
            self.candidate,
        )

    def test_private_control_config_drift_and_closed_handle_block_before_runner(self) -> None:
        reader = self._reader()
        (self.control / "config").write_text("[core]\n", encoding="utf-8")
        with patch.object(self.adapter, "_run_git_command") as runner:
            self._assert_error(
                "LOCAL_GIT_CONTROL_METADATA_INVALID",
                lambda: reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV),
            )
        runner.assert_not_called()
        (self.control / "config").unlink()
        reader.close()
        self._assert_error(
            "LOCAL_GIT_HANDLE_CLOSED",
            lambda: reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV),
        )

    def test_executable_descriptor_survives_path_replacement(self) -> None:
        wrapper = self._wrapper("stable-git")
        reader = self._reader(executable=str(wrapper))
        replacement = Path(self.temporary.name) / "replacement-git"
        replacement.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
        replacement.chmod(0o700)
        os.replace(replacement, wrapper)
        self.assertEqual(
            reader.inspect_commit(self.candidate, self.base, self.core.FIXED_GIT_ENV).commit_sha,
            self.candidate,
        )

    def test_topology_tree_blob_and_reader_failures_remain_closed(self) -> None:
        reader = self._reader()
        self._assert_error(
            "LOCAL_GIT_PARENT_COUNT_INVALID",
            lambda: reader.inspect_commit(self.base, self.base, self.core.FIXED_GIT_ENV),
        )
        run_test_git(self.repository, "checkout", "--quiet", "-b", "sibling", self.base)
        self._write_and_commit("backend/scripts/sibling.py", b"sibling\n", "sibling")
        sibling = git_output(self.repository, "rev-parse", "HEAD")
        self._assert_error(
            "LOCAL_GIT_BASE_NOT_ANCESTOR",
            lambda: reader.inspect_commit(self.candidate, sibling, self.core.FIXED_GIT_ENV),
        )

        tree = "b" * 40
        cases = (
            (b"malformed", "LOCAL_GIT_TREE_FORMAT_INVALID"),
            (b"100644 tree " + b"1" * 40 + b" 1\tbackend/scripts/a.py\x00", "LOCAL_GIT_TREE_OBJECT_NOT_BLOB"),
        )
        for raw, code in cases:
            with self.subTest(code=code):
                runner = ScriptedRunner(self.adapter, [tree.encode("ascii") + b"\n", raw])
                with patch.object(self.adapter, "_run_git_command", runner):
                    self._assert_error(code, lambda: self._reader().list_tree(tree, self.core.FIXED_GIT_ENV))

        object_id = "1" * 40
        runner = ScriptedRunner(self.adapter, [])
        with patch.object(self.adapter, "_run_git_command", runner):
            self._assert_error(
                "LOCAL_GIT_OBJECT_ID_INVALID",
                lambda: self._reader().read_blob("G" * 40, self.core.FIXED_GIT_ENV),
            )
        self.assertEqual(runner.calls, [])

        for outcomes, code in (
            ([b"tree\n"], "LOCAL_GIT_OBJECT_TYPE_INVALID"),
            ([b"blob\n", str(self.adapter.MAX_BLOB_BYTES + 1).encode("ascii") + b"\n"], "LOCAL_GIT_BLOB_TOO_LARGE"),
            ([RuntimeError("private runner text")], "LOCAL_GIT_COMMAND_FAILED"),
            ([TimeoutError("private timeout")], "LOCAL_GIT_TIMEOUT"),
        ):
            with self.subTest(code=code):
                runner = ScriptedRunner(self.adapter, outcomes)
                with patch.object(self.adapter, "_run_git_command", runner):
                    with self.assertRaises(self.core.ProjectionSourceError) as raised:
                        self._reader().read_blob(object_id, self.core.FIXED_GIT_ENV)
                self.assertEqual(raised.exception.code, code)
                self.assertNotIn("private", str(raised.exception))

    def test_fixed_argv_closed_environment_and_descriptor_pass_fds(self) -> None:
        tree = "b" * 40
        reader = self._reader()
        runner = ScriptedRunner(
            self.adapter,
            [
                tree.encode("ascii") + b"\n",
                b"100644 blob " + b"1" * 40 + b" 1\tbackend/scripts/a.py\x00",
            ],
        )
        with patch.object(self.adapter, "_run_git_command", runner):
            reader.list_tree(tree, self.core.FIXED_GIT_ENV)
        for argv, cwd, environment, timeout_seconds, _limit, pass_fds in runner.calls:
            self.assertTrue(argv[0].startswith("/proc/self/fd/"))
            self.assertEqual(argv[1:3], ("--no-pager", "--no-replace-objects"))
            self.assertTrue(cwd.startswith("/proc/self/fd/"))
            self.assertEqual(timeout_seconds, self.adapter.GIT_TIMEOUT_SECONDS)
            self.assertEqual(len(pass_fds), 3)
            self.assertNotIn("GIT_ALTERNATE_OBJECT_DIRECTORIES", dict(environment))
            self.assertNotIn("GIT_CONFIG", dict(environment))
            self.assertIn("GIT_DIR", dict(environment))
            self.assertIn("GIT_OBJECT_DIRECTORY", dict(environment))

    def test_selector_register_close_and_stream_close_failures_reap_child(self) -> None:
        process = FakeProcess(PlainStream())
        with patch.object(self.adapter.subprocess, "Popen", return_value=process) as popen, patch.object(
            self.adapter.selectors, "DefaultSelector", side_effect=RuntimeError("selector")
        ):
            with self.assertRaises(self.adapter._LocalGitCommandFailure) as raised:
                self.adapter._run_git_command(
                    ("/proc/self/fd/1", "rev-parse"),
                    cwd="/proc/self/fd/1",
                    environment={},
                    timeout_seconds=1.0,
                    max_stdout_bytes=32,
                    pass_fds=(7, 8),
                )
        self.assertEqual(raised.exception.code, "LOCAL_GIT_COMMAND_FAILED")
        self.assertGreaterEqual(process.kill_calls, 1)
        self.assertGreaterEqual(process.wait_calls, 1)
        arguments, keywords = popen.call_args
        self.assertEqual(arguments[0], ("/proc/self/fd/1", "rev-parse"))
        self.assertEqual(keywords["cwd"], "/proc/self/fd/1")
        self.assertEqual(keywords["env"], {})
        self.assertIs(keywords["stdin"], subprocess.DEVNULL)
        self.assertIs(keywords["stdout"], subprocess.PIPE)
        self.assertIs(keywords["stderr"], subprocess.DEVNULL)
        self.assertFalse(keywords["shell"])
        self.assertTrue(keywords["close_fds"])
        self.assertEqual(keywords["pass_fds"], (7, 8))
        self.assertTrue(keywords["start_new_session"])

        class RegisterFailure:
            def register(self, *_args):
                raise RuntimeError("register")

            def close(self):
                return None

        process = FakeProcess(PlainStream())
        with patch.object(self.adapter.subprocess, "Popen", return_value=process), patch.object(
            self.adapter.selectors, "DefaultSelector", return_value=RegisterFailure()
        ):
            with self.assertRaises(self.adapter._LocalGitCommandFailure) as raised:
                self.adapter._run_git_command(
                    ("/proc/self/fd/1", "rev-parse"),
                    cwd="/proc/self/fd/1",
                    environment={},
                    timeout_seconds=1.0,
                    max_stdout_bytes=32,
                    pass_fds=(),
                )
        self.assertEqual(raised.exception.code, "LOCAL_GIT_COMMAND_FAILED")
        self.assertGreaterEqual(process.kill_calls, 1)
        self.assertGreaterEqual(process.wait_calls, 1)

        read_descriptor, write_descriptor = os.pipe()
        os.write(write_descriptor, b"ok\n")
        os.close(write_descriptor)

        class BadCloseStream:
            def fileno(self):
                return read_descriptor

            def close(self):
                os.close(read_descriptor)
                raise RuntimeError("stream close")

        class ClosingSelector:
            def register(self, *_args):
                return None

            def select(self, _timeout):
                return [(None, None)]

            def close(self):
                raise RuntimeError("selector close")

        process = FakeProcess(BadCloseStream())
        process.pid = 12345
        with patch.object(self.adapter.subprocess, "Popen", return_value=process), patch.object(
            self.adapter.selectors, "DefaultSelector", return_value=ClosingSelector()
        ), patch.object(self.adapter.os, "killpg") as kill_group:
            result = self.adapter._run_git_command(
                ("/proc/self/fd/1", "rev-parse"),
                cwd="/proc/self/fd/1",
                environment={},
                timeout_seconds=1.0,
                max_stdout_bytes=32,
                pass_fds=(),
            )
        self.assertEqual(result.stdout, b"ok\n")
        self.assertGreaterEqual(process.wait_calls, 1)
        kill_group.assert_not_called()

    def test_no_event_after_parent_exit_times_out_without_read(self) -> None:
        class NoEventSelector:
            def register(self, *_args):
                return None

            def select(self, _timeout):
                return []

            def close(self):
                return None

        process = FakeProcess(PlainStream())
        process._alive = False
        with patch.object(
            self.adapter.subprocess, "Popen", return_value=process
        ), patch.object(
            self.adapter.selectors, "DefaultSelector", return_value=NoEventSelector()
        ), patch.object(
            self.adapter.time, "monotonic", side_effect=(0.0, 0.0, 0.2)
        ), patch.object(
            self.adapter.os,
            "read",
            side_effect=AssertionError("read must follow a selector event"),
        ):
            with self.assertRaises(self.adapter._LocalGitCommandFailure) as raised:
                self.adapter._run_git_command(
                    ("/proc/self/fd/1", "rev-parse"),
                    cwd="/proc/self/fd/1",
                    environment={},
                    timeout_seconds=0.1,
                    max_stdout_bytes=32,
                    pass_fds=(),
                )
        self.assertEqual(raised.exception.code, "LOCAL_GIT_TIMEOUT")
        self.assertGreaterEqual(process.wait_calls, 1)

    def test_descendant_inherited_stdout_cannot_extend_timeout(self) -> None:
        script = (
            "import subprocess,sys; "
            "subprocess.Popen([sys.executable,'-c','import time; time.sleep(2)'])"
        )
        started = time.monotonic()
        with self.assertRaises(self.adapter._LocalGitCommandFailure) as raised:
            self.adapter._run_git_command(
                (sys.executable, "-c", script),
                cwd=self.temporary.name,
                environment={"PATH": "/usr/bin:/bin"},
                timeout_seconds=0.1,
                max_stdout_bytes=32,
                pass_fds=(),
            )
        elapsed = time.monotonic() - started
        self.assertEqual(raised.exception.code, "LOCAL_GIT_TIMEOUT")
        self.assertLess(elapsed, 1.0)

        def new_context():
            descriptors = [os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC) for _ in range(3)]
            try:
                return self.adapter._GitExecutionContext(
                    executable_fd=descriptors[0],
                    objects_fd=descriptors[1],
                    control_fd=descriptors[2],
                )
            except BaseException:
                for descriptor in descriptors:
                    os.close(descriptor)
                raise

        context = new_context()
        original_descriptors = (
            context._executable_fd,
            context._objects_fd,
            context._control_fd,
        )
        context.close()
        context.close()
        reused_descriptors = [os.open("/dev/null", os.O_RDONLY | os.O_CLOEXEC) for _ in range(3)]
        try:
            self.assertTrue(set(original_descriptors).intersection(reused_descriptors))
            context.close()
            for descriptor in reused_descriptors:
                os.fstat(descriptor)
            self._assert_error("LOCAL_GIT_CONTEXT_CLOSED", context.begin_command)
        finally:
            for descriptor in reused_descriptors:
                os.close(descriptor)

        context = new_context()
        close_barrier = threading.Barrier(5)
        close_errors: list[BaseException] = []

        def concurrent_close() -> None:
            try:
                close_barrier.wait(timeout=2)
                context.close()
            except BaseException as raised:
                close_errors.append(raised)

        close_threads = [threading.Thread(target=concurrent_close) for _ in range(4)]
        for thread in close_threads:
            thread.start()
        close_barrier.wait(timeout=2)
        for thread in close_threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(close_errors, [])
        self._assert_error("LOCAL_GIT_CONTEXT_CLOSED", context.begin_command)

        context = new_context()
        leased_descriptors = (
            context._executable_fd,
            context._objects_fd,
            context._control_fd,
        )
        context.begin_command()
        wait_entered = threading.Event()
        original_wait = context._condition.wait

        def signal_wait(*args, **kwargs):
            wait_entered.set()
            return original_wait(*args, **kwargs)

        close_errors = []

        def close_while_leased() -> None:
            try:
                context.close()
            except BaseException as raised:
                close_errors.append(raised)

        with patch.object(context._condition, "wait", side_effect=signal_wait):
            closing_thread = threading.Thread(target=close_while_leased)
            closing_thread.start()
            self.assertTrue(wait_entered.wait(timeout=2))
            for descriptor in leased_descriptors:
                os.fstat(descriptor)
            context.finish_command()
            closing_thread.join(timeout=2)
        self.assertFalse(closing_thread.is_alive())
        self.assertEqual(close_errors, [])
        for descriptor in leased_descriptors:
            with self.assertRaises(OSError):
                os.fstat(descriptor)


if __name__ == "__main__":
    unittest.main()
