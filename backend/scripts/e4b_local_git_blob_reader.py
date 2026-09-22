"""Descriptor-bound, source-only local Git-object reader for E4b.

This module has no repository-path or descriptor constructor. A future trusted
snapshot must provide a private immutable ``LocalGitRepositoryHandle``; this
candidate exposes no operational handle construction.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import re
import selectors
import signal
import stat
import subprocess
import threading
import time
from types import MappingProxyType
from typing import Mapping

if __package__:
    from .e4b_authenticated_operational_projection import (
        FIXED_GIT_ENV,
        ProjectionSourceError,
        RepositoryFacts,
        TreeEntry,
    )
else:
    from e4b_authenticated_operational_projection import (  # type: ignore[no-redef]
        FIXED_GIT_ENV,
        ProjectionSourceError,
        RepositoryFacts,
        TreeEntry,
    )


GIT_TIMEOUT_SECONDS = 5.0
MAX_METADATA_BYTES = 4_096
MAX_ANCESTRY_BYTES = 1_048_576
MAX_TREE_BYTES = 4_194_304
MAX_BLOB_BYTES = 4_194_304
LOCAL_GIT_ENV = MappingProxyType(
    {
        "GIT_ALLOW_PROTOCOL": "none",
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_COUNT": "0",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_WORK_TREE": "/nonexistent",
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "TZ": "UTC",
    }
)

_ANCESTRY_DOMAIN = b"E4B-LOCAL-GIT-ANCESTRY-V1\x00"
_GIT_ARGUMENT_PREFIX = ("--no-pager", "--no-replace-objects")
_HEX40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX40_BYTES = re.compile(rb"[0-9a-f]{40}\Z")
_DECIMAL_BYTES = re.compile(rb"(?:0|[1-9][0-9]*)\Z")
_FD_ROOT = "/proc/self/fd"
_CHILD_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_LOCK_TYPE = type(threading.Lock())


@dataclass(frozen=True)
class _GitCommandResult:
    returncode: int
    stdout: bytes


@dataclass(frozen=True)
class _DescriptorIdentity:
    device: int
    inode: int
    file_type: int


class _GitExecutionContext:
    """One internal descriptor lease for exactly one Git invocation."""

    __slots__ = (
        "_active_commands",
        "_closed",
        "_closing",
        "_condition",
        "_control_fd",
        "_executable_fd",
        "_objects_fd",
    )

    def __init__(self, *, executable_fd: int, objects_fd: int, control_fd: int) -> None:
        if not all(type(descriptor) is int for descriptor in (executable_fd, objects_fd, control_fd)):
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")
        self._executable_fd: int | None = executable_fd
        self._objects_fd: int | None = objects_fd
        self._control_fd: int | None = control_fd
        self._condition = threading.Condition()
        self._active_commands = 0
        self._closing = False
        self._closed = False

    def begin_command(self) -> tuple[str, str, Mapping[str, str], tuple[int, int, int]]:
        """Retain descriptors until ``finish_command`` releases this lease."""

        with self._condition:
            if self._closing or self._closed:
                raise ProjectionSourceError("LOCAL_GIT_CONTEXT_CLOSED")
            executable_fd = self._executable_fd
            objects_fd = self._objects_fd
            control_fd = self._control_fd
            if not all(type(descriptor) is int for descriptor in (executable_fd, objects_fd, control_fd)):
                raise ProjectionSourceError("LOCAL_GIT_CONTEXT_CLOSED")
            self._active_commands += 1
            return (
                _fd_path(executable_fd),
                _fd_path(control_fd),
                MappingProxyType(
                    {
                        **LOCAL_GIT_ENV,
                        "GIT_DIR": _fd_path(control_fd),
                        "GIT_OBJECT_DIRECTORY": _fd_path(objects_fd),
                    }
                ),
                (executable_fd, objects_fd, control_fd),
            )

    def finish_command(self) -> None:
        with self._condition:
            if self._active_commands <= 0:
                raise ProjectionSourceError("LOCAL_GIT_CONTEXT_INVALID")
            self._active_commands -= 1
            if self._active_commands == 0:
                self._condition.notify_all()

    def close(self) -> None:
        with self._condition:
            if self._closed:
                return
            if self._closing:
                while not self._closed:
                    self._condition.wait()
                return
            self._closing = True
            while self._active_commands:
                self._condition.wait()
            descriptors = (self._executable_fd, self._objects_fd, self._control_fd)
            self._executable_fd = None
            self._objects_fd = None
            self._control_fd = None
            for descriptor in descriptors:
                if type(descriptor) is int:
                    _close_fd(descriptor)
            self._closed = True
            self._condition.notify_all()


class _LocalGitCommandFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _close_fd(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _safe_close(resource: object | None) -> None:
    if resource is None:
        return
    try:
        resource.close()  # type: ignore[attr-defined]
    except Exception:
        pass


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if getattr(process, "returncode", None) is None:
        process_id = getattr(process, "pid", None)
        if type(process_id) is int and process_id > 0:
            try:
                os.killpg(process_id, signal.SIGKILL)
            except (OSError, ValueError):
                pass
    try:
        running = process.poll() is None
    except Exception:
        running = True
    if running:
        try:
            process.kill()
        except Exception:
            pass
    try:
        process.wait(timeout=1)
    except Exception:
        pass


def _run_git_command(
    argv: tuple[str, ...],
    *,
    cwd: str,
    environment: Mapping[str, str],
    timeout_seconds: float,
    max_stdout_bytes: int,
    pass_fds: tuple[int, ...],
) -> _GitCommandResult:
    """Run one descriptor-pinned Git argv and always reap its child."""

    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            close_fds=True,
            pass_fds=pass_fds,
            start_new_session=True,
        )
    except (OSError, ValueError):
        raise _LocalGitCommandFailure("LOCAL_GIT_COMMAND_FAILED") from None

    selector: object | None = None
    stream: object | None = None
    try:
        stream = process.stdout
        if stream is None:
            raise _LocalGitCommandFailure("LOCAL_GIT_COMMAND_FAILED")
        selector = selectors.DefaultSelector()
        selector.register(stream, selectors.EVENT_READ)  # type: ignore[attr-defined]
        collected = bytearray()
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _LocalGitCommandFailure("LOCAL_GIT_TIMEOUT")
            events = selector.select(remaining)  # type: ignore[attr-defined]
            if not events:
                continue
            chunk = os.read(stream.fileno(), max_stdout_bytes + 1 - len(collected))  # type: ignore[attr-defined]
            if not chunk:
                break
            collected.extend(chunk)
            if len(collected) > max_stdout_bytes:
                raise _LocalGitCommandFailure("LOCAL_GIT_OUTPUT_LIMIT")
        try:
            returncode = process.wait(timeout=max(0.0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise _LocalGitCommandFailure("LOCAL_GIT_TIMEOUT") from None
        return _GitCommandResult(returncode=returncode, stdout=bytes(collected))
    except _LocalGitCommandFailure:
        raise
    except Exception:
        raise _LocalGitCommandFailure("LOCAL_GIT_COMMAND_FAILED") from None
    finally:
        _stop_process(process)
        _safe_close(selector)
        _safe_close(stream)


def _fd_path(descriptor: int) -> str:
    return _FD_ROOT + "/" + str(descriptor)


def _valid_object_id(value: object) -> bool:
    return type(value) is str and _HEX40.fullmatch(value) is not None


def _directory_identity(descriptor: int) -> _DescriptorIdentity:
    try:
        details = os.fstat(descriptor)
    except OSError:
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
    if not stat.S_ISDIR(details.st_mode):
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")
    return _DescriptorIdentity(details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode))


def _executable_identity(descriptor: int) -> _DescriptorIdentity:
    try:
        details = os.fstat(descriptor)
    except OSError:
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
    if not stat.S_ISREG(details.st_mode) or not details.st_mode & 0o111:
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")
    return _DescriptorIdentity(details.st_dev, details.st_ino, stat.S_IFMT(details.st_mode))


def _assert_same_directory(descriptor: int, expected: _DescriptorIdentity) -> None:
    if _directory_identity(descriptor) != expected:
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")


def _assert_same_executable(descriptor: int, expected: _DescriptorIdentity) -> None:
    if _executable_identity(descriptor) != expected:
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")


def _valid_identity(value: object) -> bool:
    return (
        type(value) is _DescriptorIdentity
        and type(value.device) is int
        and type(value.inode) is int
        and type(value.file_type) is int
    )


def _open_directory_at(parent_fd: int, name: str) -> int:
    try:
        return os.open(name, _CHILD_DIRECTORY_FLAGS, dir_fd=parent_fd)
    except (OSError, ValueError):
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None


def _assert_private_control_directory(control_fd: int) -> None:
    try:
        if tuple(sorted(os.listdir(control_fd))) != ("HEAD", "objects", "refs"):
            raise ProjectionSourceError("LOCAL_GIT_CONTROL_METADATA_INVALID")
        head = os.stat("HEAD", dir_fd=control_fd, follow_symlinks=False)
        if not stat.S_ISREG(head.st_mode):
            raise ProjectionSourceError("LOCAL_GIT_CONTROL_METADATA_INVALID")
        for name in ("objects", "refs"):
            descriptor = _open_directory_at(control_fd, name)
            _close_fd(descriptor)
    except ProjectionSourceError:
        raise
    except (OSError, ValueError):
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None


def _assert_no_alternates(objects_fd: int) -> None:
    info_fd: int | None = None
    try:
        try:
            info_fd = _open_directory_at(objects_fd, "info")
        except ProjectionSourceError:
            try:
                os.stat("info", dir_fd=objects_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            except (OSError, ValueError):
                raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")
        try:
            os.stat("alternates", dir_fd=info_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
        raise ProjectionSourceError("LOCAL_GIT_ALTERNATES_PRESENT")
    finally:
        if info_fd is not None:
            _close_fd(info_fd)


class LocalGitRepositoryHandle:
    """Opaque descriptor capability reserved for a future trusted snapshot."""

    __slots__ = (
        "_control_fd",
        "_control_identity",
        "_executable_fd",
        "_executable_identity",
        "_lock",
        "_objects_fd",
        "_objects_identity",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise ProjectionSourceError("LOCAL_GIT_HANDLE_UNAVAILABLE")

    def close(self) -> None:
        lock = self._validated_lock()
        with lock:
            descriptors = (self._executable_fd, self._objects_fd, self._control_fd)
            self._executable_fd = None
            self._objects_fd = None
            self._control_fd = None
        for descriptor in descriptors:
            if type(descriptor) is int:
                _close_fd(descriptor)

    def _execution_context(self) -> _GitExecutionContext:
        lock = self._validated_lock()
        with lock:
            executable_fd = self._executable_fd
            objects_fd = self._objects_fd
            control_fd = self._control_fd
            if not all(type(descriptor) is int for descriptor in (executable_fd, objects_fd, control_fd)):
                raise ProjectionSourceError("LOCAL_GIT_HANDLE_CLOSED")
            if not all(
                _valid_identity(identity)
                for identity in (
                    self._executable_identity,
                    self._objects_identity,
                    self._control_identity,
                )
            ):
                raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")
            _assert_same_executable(executable_fd, self._executable_identity)
            _assert_same_directory(objects_fd, self._objects_identity)
            _assert_same_directory(control_fd, self._control_identity)
            _assert_private_control_directory(control_fd)
            _assert_no_alternates(objects_fd)
            duplicates: list[int] = []
            try:
                for descriptor in (executable_fd, objects_fd, control_fd):
                    duplicates.append(os.dup(descriptor))
            except OSError:
                for duplicate in duplicates:
                    _close_fd(duplicate)
                raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
        try:
            return _GitExecutionContext(
                executable_fd=duplicates[0], objects_fd=duplicates[1], control_fd=duplicates[2]
            )
        except ProjectionSourceError:
            for duplicate in duplicates:
                _close_fd(duplicate)
            raise

    def _validated_lock(self):
        try:
            lock = self._lock
        except AttributeError:
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
        if type(lock) is not _LOCK_TYPE:
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID")
        return lock

def _single_object_id(raw: bytes) -> str:
    if (
        type(raw) is not bytes
        or len(raw) != 41
        or raw[-1:] != b"\n"
        or _HEX40_BYTES.fullmatch(raw[:-1]) is None
    ):
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    return raw[:-1].decode("ascii")


def _parent_ids(raw: bytes) -> tuple[str, ...]:
    if type(raw) is not bytes or not raw.endswith(b"\n") or raw.count(b"\n") != 1:
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    payload = raw[:-1]
    if not payload:
        return ()
    values = payload.split(b" ")
    if any(_HEX40_BYTES.fullmatch(value) is None for value in values):
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    return tuple(value.decode("ascii") for value in values)


def _ancestry_ids(raw: bytes) -> tuple[str, ...]:
    if type(raw) is not bytes:
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    if not raw:
        return ()
    if not raw.endswith(b"\n"):
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    values = raw[:-1].split(b"\n")
    if not values or any(_HEX40_BYTES.fullmatch(value) is None for value in values):
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    decoded = tuple(value.decode("ascii") for value in values)
    if len(decoded) != len(set(decoded)):
        raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
    return tuple(sorted(decoded))


def _canonical_ancestry_digest(
    base_sha: str, commit_sha: str, ancestry_ids: tuple[str, ...]
) -> str:
    payload = (
        _ANCESTRY_DOMAIN
        + base_sha.encode("ascii")
        + b"\x00"
        + commit_sha.encode("ascii")
        + b"\x00"
        + b"\x00".join(item.encode("ascii") for item in ancestry_ids)
    )
    return hashlib.sha256(payload).hexdigest()


class LocalGitBlobReader:
    """Finite local-object reader requiring a descriptor-bound handle."""

    def __init__(self, handle: LocalGitRepositoryHandle) -> None:
        if type(handle) is not LocalGitRepositoryHandle:
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_REQUIRED")
        self._handle = handle

    def close(self) -> None:
        try:
            self._handle.close()
        except ProjectionSourceError:
            raise
        except Exception:
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None

    def inspect_commit(
        self,
        commit_sha: str,
        expected_base_sha: str,
        environment: Mapping[str, str],
    ) -> RepositoryFacts:
        self._require_environment(environment)
        commit = self._require_object_id(commit_sha)
        base = self._require_object_id(expected_base_sha)
        actual_commit = self._resolve_typed_object(commit, "commit")
        if actual_commit != commit:
            raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
        tree = self._resolve_typed_object(commit, "tree")
        parents = _parent_ids(
            self._invoke(("show", "-s", "--format=%P", commit), MAX_METADATA_BYTES).stdout
        )
        if len(parents) != 1:
            raise ProjectionSourceError("LOCAL_GIT_PARENT_COUNT_INVALID")
        actual_base = self._resolve_typed_object(base, "commit")
        if actual_base != base:
            raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
        ancestry_check = self._invoke(
            ("merge-base", "--is-ancestor", base, commit),
            MAX_METADATA_BYTES,
            allowed_returncodes=(0, 1),
        )
        if ancestry_check.returncode == 1:
            raise ProjectionSourceError("LOCAL_GIT_BASE_NOT_ANCESTOR")
        if ancestry_check.stdout:
            raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
        ancestry = _ancestry_ids(
            self._invoke(("rev-list", "--ancestry-path", base + ".." + commit), MAX_ANCESTRY_BYTES).stdout
        )
        if base != commit and commit not in ancestry:
            raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
        return RepositoryFacts(
            commit_sha=commit,
            tree_sha=tree,
            parent_sha=parents[0],
            base_sha=base,
            ancestry_digest_sha256=_canonical_ancestry_digest(base, commit, ancestry),
        )

    def list_tree(
        self, tree_sha: str, environment: Mapping[str, str]
    ) -> tuple[TreeEntry, ...]:
        self._require_environment(environment)
        tree = self._require_object_id(tree_sha)
        if self._resolve_typed_object(tree, "tree") != tree:
            raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
        raw = self._invoke(("ls-tree", "-r", "-z", "-l", tree), MAX_TREE_BYTES).stdout
        if not raw or not raw.endswith(b"\x00"):
            raise ProjectionSourceError("LOCAL_GIT_TREE_FORMAT_INVALID")
        entries: list[TreeEntry] = []
        previous: bytes | None = None
        for record in raw[:-1].split(b"\x00"):
            metadata, separator, path = record.partition(b"\t")
            fields = metadata.split()
            if not separator or not path or len(fields) != 4:
                raise ProjectionSourceError("LOCAL_GIT_TREE_FORMAT_INVALID")
            mode, kind, object_id, size_bytes = fields
            if kind != b"blob":
                raise ProjectionSourceError("LOCAL_GIT_TREE_OBJECT_NOT_BLOB")
            if mode not in {b"100644", b"100755"} or _HEX40_BYTES.fullmatch(object_id) is None:
                raise ProjectionSourceError("LOCAL_GIT_TREE_FORMAT_INVALID")
            if _DECIMAL_BYTES.fullmatch(size_bytes) is None or len(size_bytes) > 19:
                raise ProjectionSourceError("LOCAL_GIT_TREE_FORMAT_INVALID")
            size = int(size_bytes)
            if size > 9_223_372_036_854_775_807:
                raise ProjectionSourceError("LOCAL_GIT_TREE_FORMAT_INVALID")
            if previous is not None and path <= previous:
                raise ProjectionSourceError("LOCAL_GIT_TREE_ORDER_INVALID")
            entries.append(
                TreeEntry(
                    path=path,
                    object_id=object_id.decode("ascii"),
                    kind="blob",
                    mode=mode.decode("ascii"),
                    size=size,
                )
            )
            previous = path
        return tuple(entries)

    def read_blob(self, object_id: str, environment: Mapping[str, str]) -> bytes:
        self._require_environment(environment)
        object_identifier = self._require_object_id(object_id)
        object_type = self._invoke(("cat-file", "-t", object_identifier), MAX_METADATA_BYTES).stdout
        if object_type != b"blob\n":
            raise ProjectionSourceError("LOCAL_GIT_OBJECT_TYPE_INVALID")
        size_raw = self._invoke(("cat-file", "-s", object_identifier), MAX_METADATA_BYTES).stdout
        if (
            not size_raw.endswith(b"\n")
            or _DECIMAL_BYTES.fullmatch(size_raw[:-1]) is None
            or len(size_raw[:-1]) > 19
        ):
            raise ProjectionSourceError("LOCAL_GIT_METADATA_INVALID")
        size = int(size_raw[:-1])
        if size > MAX_BLOB_BYTES:
            raise ProjectionSourceError("LOCAL_GIT_BLOB_TOO_LARGE")
        blob = self._invoke(("cat-file", "blob", object_identifier), MAX_BLOB_BYTES).stdout
        if len(blob) != size:
            raise ProjectionSourceError("LOCAL_GIT_BLOB_SIZE_INVALID")
        return blob

    def _require_environment(self, environment: object) -> None:
        if environment is not FIXED_GIT_ENV:
            raise ProjectionSourceError("LOCAL_GIT_ENV_INVALID")

    def _require_object_id(self, object_id: object) -> str:
        if not _valid_object_id(object_id):
            raise ProjectionSourceError("LOCAL_GIT_OBJECT_ID_INVALID")
        return object_id

    def _resolve_typed_object(self, object_id: str, object_type: str) -> str:
        return _single_object_id(
            self._invoke(
                ("rev-parse", "--verify", object_id + "^{" + object_type + "}"),
                MAX_METADATA_BYTES,
            ).stdout
        )

    def _invoke(
        self,
        command: tuple[str, ...],
        max_stdout_bytes: int,
        *,
        allowed_returncodes: tuple[int, ...] = (0,),
    ) -> _GitCommandResult:
        try:
            context = self._handle._execution_context()
        except ProjectionSourceError:
            raise
        except Exception:
            raise ProjectionSourceError("LOCAL_GIT_HANDLE_INVALID") from None
        try:
            executable_path, cwd, environment, pass_fds = context.begin_command()
            try:
                try:
                    result = _run_git_command(
                        (executable_path, *_GIT_ARGUMENT_PREFIX, *command),
                        cwd=cwd,
                        environment=environment,
                        timeout_seconds=GIT_TIMEOUT_SECONDS,
                        max_stdout_bytes=max_stdout_bytes,
                        pass_fds=pass_fds,
                    )
                except _LocalGitCommandFailure as raised:
                    raise ProjectionSourceError(raised.code) from None
                except TimeoutError:
                    raise ProjectionSourceError("LOCAL_GIT_TIMEOUT") from None
                except Exception:
                    raise ProjectionSourceError("LOCAL_GIT_COMMAND_FAILED") from None
                if (
                    type(result) is not _GitCommandResult
                    or type(result.returncode) is not int
                    or type(result.stdout) is not bytes
                ):
                    raise ProjectionSourceError("LOCAL_GIT_COMMAND_FAILED")
                if len(result.stdout) > max_stdout_bytes:
                    raise ProjectionSourceError("LOCAL_GIT_OUTPUT_LIMIT")
                if result.returncode not in allowed_returncodes:
                    raise ProjectionSourceError("LOCAL_GIT_COMMAND_FAILED")
                return result
            finally:
                context.finish_command()
        finally:
            context.close()
