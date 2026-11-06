"""Read-only source identity check; never import or execute candidate code.

The externally admitted contract digest is an integrity assertion, not authority
for host access, execution, recovery, deployment or production readiness. A match
covers only these named source bytes during this observation, not behaviour.
"""

import argparse
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys

CODE = "c2-integration-refused"
SCHEMA = "igreja12-c2-source-contract/v1"
CONTRACT_NAME = "c2-candidate-interface.json"
HEX = re.compile(r"[0-9a-f]{64}")
GIT_SHA = re.compile(r"[0-9a-f]{40}")
PROTECTED = re.compile(
    r"(?:\.env.*|secrets?|.*\.pem|.*\.key|id_rsa.*|id_ed25519.*|target_users.*|"
    r".*\.dump|dumps?|backups?|exports?|media|migrate_clerk_production.*|clerk_.*)",
    re.IGNORECASE,
)
C2 = ("adapter", "containment", "cron", "guards", "lifecycle", "native", "systemctl")
SHARED = (
    "first_transition_adapter",
    "first_transition_database",
    "first_transition_host_contract",
    "first_transition_host_driver",
    "first_transition_host_transport",
    "first_transition_local_backup",
    "first_transition_window_bindings",
    "initial_transition_files",
    "initial_transition_ops",
    "release_topology",
)
TESTS = (
    "containment",
    "cron",
    "guards",
    "lifecycle",
    "lifecycle_vertical",
    "native",
    "native_integration",
    "schedule_integration",
    "systemctl",
)
SOURCE_PATHS = tuple(
    sorted(
        ["deploy/first_transition_c2_" + name + ".py" for name in C2]
        + ["deploy/" + name + ".py" for name in SHARED]
        + [
            "deploy/check_c2_integration.py",
            "deploy/tests/c2_lifecycle_fixture.py",
            "deploy/tests/test_check_c2_integration.py",
        ]
        + ["deploy/tests/test_first_transition_c2_" + name + ".py" for name in TESTS]
    )
)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC | os.O_NOATIME


class IntegrationRefused(ValueError):
    def __init__(self, paths=()):
        super().__init__(CODE)
        self.paths = tuple(p for p in paths if p in SOURCE_PATHS)


def need(value):
    if not value:
        raise IntegrationRefused()


def absolute(value):
    value = os.fspath(value)
    need(type(value) is str and 0 < len(value) <= 4096)
    path = PurePosixPath(value)
    need(value.startswith("/") and not value.startswith("//") and str(path) == value)
    need(".." not in path.parts and not any(PROTECTED.fullmatch(p) for p in path.parts))
    need(not any(ord(c) < 32 or ord(c) == 127 for c in value))
    return path


def fingerprint(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def binding(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


class _Reader:
    def __init__(self, root):
        self.fds, self.links = [], []
        try:
            fd = os.open("/", DIR_FLAGS)
            self.fds.append(fd)
            for part in root.parts[1:]:
                child = os.open(part, DIR_FLAGS, dir_fd=fd)
                self.fds.append(child)
                self.links.append((fd, part, child))
                fd = child
            self.fd = fd
            self.check()
        except BaseException as original:
            try:
                self.close()
            except Exception:
                pass
            except BaseException:
                if isinstance(original, Exception):
                    raise
            raise original

    def check(self):
        for parent, name, child in self.links:
            need(
                binding(os.stat(name, dir_fd=parent, follow_symlinks=False))
                == binding(os.fstat(child))
            )

    def read(self, name, cap):
        self.check()
        parts = PurePosixPath(name).parts
        need(parts and not PurePosixPath(name).is_absolute() and ".." not in parts)
        opened, links = [], []
        try:
            parent = self.fd
            for part in parts[:-1]:
                child = os.open(part, DIR_FLAGS, dir_fd=parent)
                opened.append(child)
                links.append((parent, part, child))
                parent = child
            before = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            need(
                stat.S_ISREG(before.st_mode)
                and before.st_nlink == 1
                and 0 <= before.st_size <= cap
            )
            fd = os.open(parts[-1], FILE_FLAGS, dir_fd=parent)
            opened.append(fd)
            need(fingerprint(before) == fingerprint(os.fstat(fd)))
            body = bytearray()
            while len(body) < before.st_size:
                chunk = os.read(fd, min(65536, before.st_size - len(body)))
                need(bool(chunk))
                body.extend(chunk)
            need(not os.read(fd, 1))
            need(
                fingerprint(before)
                == fingerprint(os.fstat(fd))
                == fingerprint(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False))
            )
            for ancestor, part, child in links:
                need(
                    binding(os.stat(part, dir_fd=ancestor, follow_symlinks=False))
                    == binding(os.fstat(child))
                )
            self.check()
            return bytes(body), fingerprint(before)
        finally:
            active_error = sys.exc_info()[1]
            failed, interrupted = False, None
            for fd in reversed(opened):
                try:
                    os.close(fd)
                except Exception:
                    failed = True
                except BaseException as exc:
                    interrupted = interrupted or exc
            if active_error is None or isinstance(active_error, Exception):
                if interrupted is not None:
                    raise interrupted
                need(not failed)

    def close(self):
        failed, interrupted = False, None
        while self.fds:
            try:
                os.close(self.fds.pop())
            except Exception:
                failed = True
            except BaseException as exc:
                interrupted = interrupted or exc
        if interrupted is not None:
            raise interrupted
        need(not failed)


def _contract(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            need(key not in result)
            result[key] = value
        return result

    def constant(_value):
        raise IntegrationRefused()

    doc = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    need(
        type(doc) is dict
        and set(doc)
        == {
            "schema",
            "reference_base",
            "files",
            "production_ready",
            "operational_dispatch_enabled",
        }
    )
    need(
        doc["schema"] == SCHEMA
        and type(doc["reference_base"]) is str
        and GIT_SHA.fullmatch(doc["reference_base"])
        and doc["production_ready"] is False
        and doc["operational_dispatch_enabled"] is False
    )
    files = doc["files"]
    need(
        type(files) is dict
        and set(files) == set(SOURCE_PATHS)
        and all(type(h) is str and HEX.fullmatch(h) for h in files.values())
    )
    return doc


def verify_candidate(source_root, contract_path, expect_contract_sha256):
    """Check only admitted source bytes twice, without importing their Python."""
    readers = []
    failed, interrupted, result, mismatches = False, None, None, ()
    try:
        root, contract = absolute(source_root), absolute(contract_path)
        need(
            contract.name == CONTRACT_NAME
            and type(expect_contract_sha256) is str
            and HEX.fullmatch(expect_contract_sha256)
        )
        reader = _Reader(contract.parent)
        readers.append(reader)
        raw, original = reader.read(CONTRACT_NAME, 65536)
        need(hashlib.sha256(raw).hexdigest() == expect_contract_sha256)
        doc = _contract(raw)  # Validate all names BEFORE opening candidate root.
        candidate = _Reader(root)
        readers.append(candidate)
        observed = {}
        for relative in SOURCE_PATHS:
            data, identity = candidate.read(relative, 1024 * 1024)
            observed[relative] = identity
            if hashlib.sha256(data).hexdigest() != doc["files"][relative]:
                mismatches += (relative,)
        need(not mismatches)
        for relative in SOURCE_PATHS:
            data, identity = candidate.read(relative, 1024 * 1024)
            need(identity == observed[relative])
            if hashlib.sha256(data).hexdigest() != doc["files"][relative]:
                mismatches += (relative,)
        need(not mismatches)
        again, identity = reader.read(CONTRACT_NAME, 65536)
        need(identity == original and again == raw)
        result = dict(
            status="source-contract-match",
            source_contract_match=True,
            behaviour_verified=False,
            production_ready=False,
            operational_dispatch_enabled=False,
            source_files=len(SOURCE_PATHS),
            reference_base=doc["reference_base"],
            contract_sha256=expect_contract_sha256,
        )
    except Exception:
        failed = True
    except BaseException as exc:
        interrupted = exc
    finally:
        for reader in reversed(readers):
            try:
                reader.close()
            except Exception:
                failed = True
            except BaseException as exc:
                interrupted = interrupted or exc
    if interrupted is not None:
        raise interrupted
    if failed:
        raise IntegrationRefused(mismatches)
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise IntegrationRefused()


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--expect-contract-sha256", required=True)
    try:
        args = parser.parse_args(argv)
        result = verify_candidate(
            args.source_root, args.contract, args.expect_contract_sha256
        )
    except IntegrationRefused as error:
        result = dict(
            status="refused",
            code=CODE,
            paths=list(error.paths),
            source_contract_match=False,
            behaviour_verified=False,
            production_ready=False,
            operational_dispatch_enabled=False,
        )
        print(json.dumps(result, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
