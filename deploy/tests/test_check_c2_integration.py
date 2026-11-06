"""Source-contract verification against synthetic trees, with no candidate imports."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_c2_integration as checker

PRIVATE = "CANDIDATE-PRIVATE-FIXTURE-SENTINEL"


@pytest.fixture(autouse=True)
def no_process_or_socket(monkeypatch):
    def deny(*_args, **_kwargs):
        pytest.fail("native process or socket attempted")

    monkeypatch.setattr(subprocess, "Popen", deny)
    monkeypatch.setattr(socket, "socket", deny)


class World:
    def __init__(self, tmp_path):
        self.root = tmp_path / "source"
        self.root.mkdir(mode=0o700)
        self.contract = tmp_path / "contract" / checker.CONTRACT_NAME
        self.contract.parent.mkdir(mode=0o700)
        self.body = ("raise AssertionError(" + repr(PRIVATE) + ")\n").encode()
        self.files = {}
        for name in checker.SOURCE_PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.body)
            self.files[name] = hashlib.sha256(self.body).hexdigest()
        self.doc = dict(
            schema=checker.SCHEMA,
            reference_base="a" * 40,
            files=self.files,
            production_ready=False,
            operational_dispatch_enabled=False,
        )
        self.write()

    def write(self, *, raw=None):
        raw = (
            json.dumps(self.doc, sort_keys=True, separators=(",", ":")).encode()
            if raw is None
            else raw
        )
        self.contract.write_bytes(raw)
        self.sha = hashlib.sha256(raw).hexdigest()

    def verify(self, **kwargs):
        args = dict(
            source_root=self.root,
            contract_path=self.contract,
            expect_contract_sha256=self.sha,
        )
        args.update(kwargs)
        return checker.verify_candidate(**args)


def refused(call):
    with pytest.raises(checker.IntegrationRefused) as error:
        call()
    assert str(error.value) == checker.CODE
    assert error.value.__context__ is None
    assert PRIVATE not in repr(error.value)
    assert all(p in checker.SOURCE_PATHS for p in error.value.paths)
    return error.value


def test_valid_source_bytes_checked_without_execution(tmp_path):
    w = World(tmp_path)
    assert len(checker.SOURCE_PATHS) == 29 and len(set(checker.SOURCE_PATHS)) == 29
    result = w.verify()
    assert result == dict(
        status="source-contract-match",
        source_contract_match=True,
        behaviour_verified=False,
        production_ready=False,
        operational_dispatch_enabled=False,
        source_files=29,
        reference_base="a" * 40,
        contract_sha256=w.sha,
    )
    assert PRIVATE not in json.dumps(result)
    assert all((w.root / n).read_bytes() == w.body for n in checker.SOURCE_PATHS)


def test_hash_mismatch_reports_only_allowlisted_name(tmp_path):
    w = World(tmp_path)
    name = checker.SOURCE_PATHS[0]
    (w.root / name).write_bytes(b"different-public-fixture\n")
    error = refused(w.verify)
    assert error.paths == (name,)


@pytest.mark.parametrize(
    "kind", ["missing", "symlink", "hardlink", "fifo", "directory", "oversize"]
)
def test_unsafe_source_objects_refuse_before_opening_contents(
    tmp_path, monkeypatch, kind
):
    w = World(tmp_path)
    name = checker.SOURCE_PATHS[0]
    path = w.root / name
    path.unlink()
    if kind == "symlink":
        target = tmp_path / "outside-private-fixture"
        target.write_bytes(PRIVATE.encode())
        path.symlink_to(target)
    elif kind == "hardlink":
        target = tmp_path / "outside-private-fixture"
        target.write_bytes(PRIVATE.encode())
        os.link(target, path)
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    elif kind == "oversize":
        with path.open("wb") as stream:
            stream.truncate(1024 * 1024 + 1)
    real_open = os.open
    attempted = []

    def observe(value, *args, **kwargs):
        if value == path.name:
            attempted.append(value)
        return real_open(value, *args, **kwargs)

    monkeypatch.setattr(os, "open", observe)
    refused(w.verify)
    assert not attempted


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "other"),
        ("reference_base", "a" * 64),
        ("reference_base", 1),
        ("production_ready", True),
        ("production_ready", 0),
        ("operational_dispatch_enabled", True),
        ("operational_dispatch_enabled", 0),
        ("files", []),
    ],
)
def test_invalid_contract_fields_refuse_before_candidate_root(
    tmp_path, monkeypatch, field, value
):
    w = World(tmp_path)
    w.doc[field] = value
    w.write()
    real_open = os.open
    touched = []

    def observe(path, *args, **kwargs):
        if path == w.root.name:
            touched.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", observe)
    refused(w.verify)
    assert not touched


@pytest.mark.parametrize(
    "change", ["unknown", "missing", "bad-hash", "traversal", "private"]
)
def test_contract_inventory_is_exact_and_public(tmp_path, monkeypatch, change):
    w = World(tmp_path)
    if change == "missing":
        w.doc["files"].pop(checker.SOURCE_PATHS[0])
    elif change == "bad-hash":
        w.doc["files"][checker.SOURCE_PATHS[0]] = PRIVATE
    else:
        key = {
            "unknown": "deploy/unknown.py",
            "traversal": "deploy/../outside.py",
            "private": "deploy/.env",
        }[change]
        w.doc["files"][key] = "a" * 64
    w.write()
    real = checker._Reader
    roots = []

    def reader(root):
        roots.append(root)
        return real(root)

    monkeypatch.setattr(checker, "_Reader", reader)
    refused(w.verify)
    assert w.root not in roots


@pytest.mark.parametrize(
    "kind", ["duplicate", "nan", "invalid-json", "extra-key", "oversize"]
)
def test_bad_contract_encoding_and_schema_refuse(tmp_path, kind):
    w = World(tmp_path)
    if kind == "duplicate":
        raw = b'{"schema":"one","schema":"two"}'
    elif kind == "nan":
        raw = b'{"schema":NaN}'
    elif kind == "invalid-json":
        raw = PRIVATE.encode()
    elif kind == "oversize":
        raw = b" " * 65537
    else:
        w.doc["unexpected"] = PRIVATE
        raw = json.dumps(w.doc).encode()
    w.write(raw=raw)
    refused(w.verify)


@pytest.mark.parametrize("sha", [None, True, "a" * 63, "z" * 64, "a" * 64])
def test_wrong_expected_contract_digest_refuses(tmp_path, sha):
    w = World(tmp_path)
    refused(lambda: w.verify(expect_contract_sha256=sha))


@pytest.mark.parametrize(
    "root",
    [
        "relative",
        "/tmp/../source",
        "//tmp/source",
        "/tmp/source/",
        "/tmp/.env/source",
        "/tmp/secrets/source",
        "/tmp/source\n",
    ],
)
def test_bad_root_refuses_before_any_open(tmp_path, monkeypatch, root):
    w = World(tmp_path)
    monkeypatch.setattr(os, "open", lambda *_a, **_k: pytest.fail("unexpected IO"))
    refused(lambda: w.verify(source_root=root))


def test_contract_name_and_symlink_refuse(tmp_path):
    w = World(tmp_path)
    alias = w.contract.parent / "different.json"
    alias.write_bytes(w.contract.read_bytes())
    refused(lambda: w.verify(contract_path=alias))
    target = w.contract.parent / "original"
    w.contract.rename(target)
    w.contract.symlink_to(target)
    refused(w.verify)


def test_source_ancestor_symlink_refuses(tmp_path):
    w = World(tmp_path)
    directory = w.root / "deploy"
    renamed = w.root / "original-deploy"
    directory.rename(renamed)
    directory.symlink_to(renamed, target_is_directory=True)
    refused(w.verify)


@pytest.mark.parametrize("change", ["bytes", "replace", "aba", "contract"])
def test_change_between_passes_refuses(tmp_path, monkeypatch, change):
    w = World(tmp_path)
    name = checker.SOURCE_PATHS[0]
    path = w.root / name
    old = path.stat()
    original = checker._Reader.read
    changed = []

    def racing(reader, relative, cap):
        result = original(reader, relative, cap)
        if relative == name and not changed:
            changed.append(True)
            if change == "bytes":
                path.write_bytes(w.body + b"changed")
            elif change == "replace":
                temporary = path.with_suffix(".tmp")
                temporary.write_bytes(w.body)
                os.replace(temporary, path)
            elif change == "aba":
                path.write_bytes(w.body + b"changed")
                path.write_bytes(w.body)
                os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
            else:
                info = w.contract.stat()
                os.utime(w.contract, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        return result

    monkeypatch.setattr(checker._Reader, "read", racing)
    refused(w.verify)
    assert changed


def test_read_error_is_sanitized_and_descriptors_close(tmp_path, monkeypatch):
    w = World(tmp_path)
    original = checker._Reader.close
    closed = []

    def close(reader):
        original(reader)
        closed.append(not reader.fds)

    monkeypatch.setattr(checker._Reader, "close", close)
    monkeypatch.setattr(
        os, "read", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(PRIVATE))
    )
    refused(w.verify)
    assert closed and all(closed)


def test_cancellation_preserved_and_owned_readers_close(tmp_path, monkeypatch):
    w = World(tmp_path)
    original = checker._Reader.close
    closed = []
    cancelled = KeyboardInterrupt("fixture cancellation")

    def close(reader):
        original(reader)
        closed.append(not reader.fds)

    monkeypatch.setattr(checker._Reader, "close", close)
    monkeypatch.setattr(os, "read", lambda *_a, **_k: (_ for _ in ()).throw(cancelled))
    with pytest.raises(KeyboardInterrupt) as caught:
        w.verify()
    assert caught.value is cancelled and closed and all(closed)


def test_cli_success_and_refusal_are_safe_json(tmp_path, capsys):
    w = World(tmp_path)
    argv = [
        "--source-root",
        str(w.root),
        "--contract",
        str(w.contract),
        "--expect-contract-sha256",
        w.sha,
    ]
    assert checker.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["behaviour_verified"] is False
    (w.root / checker.SOURCE_PATHS[0]).unlink()
    assert checker.main(argv) == 1
    output = capsys.readouterr().out
    doc = json.loads(output)
    assert doc["production_ready"] is doc["source_contract_match"] is False
    assert PRIVATE not in output


@pytest.mark.parametrize("argv", [[], ["--" + PRIVATE]])
def test_cli_parse_refusal_is_fixed_json_without_echoing_inputs(capsys, argv):
    assert checker.main(argv) == 1
    captured = capsys.readouterr()
    assert not captured.err and PRIVATE not in captured.out
    assert json.loads(captured.out)["code"] == checker.CODE


def test_primary_cancellation_survives_reader_close_failure(tmp_path, monkeypatch):
    w = World(tmp_path)
    original_close = os.close
    cancelled = KeyboardInterrupt("fixture primary cancellation")

    def close(fd):
        original_close(fd)
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(os, "read", lambda *_a, **_k: (_ for _ in ()).throw(cancelled))
    monkeypatch.setattr(os, "close", close)
    with pytest.raises(KeyboardInterrupt) as caught:
        w.verify()
    assert caught.value is cancelled


def test_primary_cancellation_during_reader_initialization_survives_cleanup(
    tmp_path, monkeypatch
):
    w = World(tmp_path)
    original_open, original_close = os.open, os.close
    cancelled = KeyboardInterrupt("fixture primary cancellation")
    calls = []

    def open_file(path, *args, **kwargs):
        calls.append(path)
        if len(calls) == 2:
            raise cancelled
        return original_open(path, *args, **kwargs)

    def close(fd):
        original_close(fd)
        raise RuntimeError(PRIVATE)

    monkeypatch.setattr(os, "open", open_file)
    monkeypatch.setattr(os, "close", close)
    with pytest.raises(KeyboardInterrupt) as caught:
        w.verify()
    assert caught.value is cancelled
