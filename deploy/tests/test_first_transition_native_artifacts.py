"""Native local file/pipe custody with synthetic bytes only; no DB/Docker/source."""
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import sys
import threading

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_window_backup as backup
from initial_transition_ops import Refused
from test_first_transition_orchestrator import no_real_processes_or_network  # noqa: F401

DUMP = b'PGDMP' + b'SYNTHETIC-PRIVATE-DUMP'
COMPANION = b'{"synthetic":"PRIVATE-NOT-A-PROOF"}'
REQUEST = 'a' * 64


@contextmanager
def pipe(data=None):
    read, write = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        if data is not None:
            assert os.write(write, data) == len(data)
            os.close(write)
            write = None
        yield read, write
    finally:
        os.close(read)
        if write is not None:
            os.close(write)


@pytest.fixture
def custody(tmp_path):
    root = tmp_path / 'private'
    root.mkdir(mode=0o700)
    store = backup.NativeWindowArtifacts(str(root), REQUEST, owner=os.geteuid())
    with store:
        yield store, root, root / REQUEST


def capture(store, kind, data):
    with pipe(data) as (source, _):
        store.capture(kind, source, timeout=1)


def pair(store):
    capture(store, 'dump', DUMP)
    capture(store, 'companion', COMPANION)


def test_request_bound_private_pair_and_verified_restore_stream(custody):
    store, root, run = custody
    pair(store)
    metadata = store.metadata()
    assert metadata == dict(request_digest=REQUEST, artifacts={
        'dump': dict(sha256=hashlib.sha256(DUMP).hexdigest(), size=len(DUMP)),
        'companion': dict(sha256=hashlib.sha256(COMPANION).hexdigest(), size=len(COMPANION))})
    assert (run.stat().st_mode & 0o777) == 0o700
    assert set(p.name for p in run.iterdir()) == {'window.dump', 'companion.json'}
    for kind, data in (('dump', DUMP), ('companion', COMPANION)):
        fd = store._artifacts[kind]['fd']
        original_offset = os.lseek(fd, 0, os.SEEK_CUR)
        with pipe() as (read, target):
            assert store.copy_verified(kind, target, timeout=1) == len(data)
            assert os.read(read, 1024) == data
        assert os.lseek(fd, 0, os.SEEK_CUR) == original_offset
    assert 'PRIVATE' not in repr(metadata) and str(root) not in repr(metadata)
    assert not any(key in metadata for key in ('restore_verified', 'origin_window', 'production_ready'))


@pytest.mark.parametrize('where', ['root', 'ancestor'])
def test_symlink_in_root_traversal_is_refused_without_following(tmp_path, where):
    real = tmp_path / 'real'
    real.mkdir(mode=0o700)
    target = real if where == 'root' else real / 'nested'
    if where == 'ancestor':
        target.mkdir(mode=0o700)
    link = tmp_path / 'link'
    link.symlink_to(real, target_is_directory=True)
    root = link if where == 'root' else link / 'nested'
    store = backup.NativeWindowArtifacts(str(root), REQUEST, owner=os.geteuid())
    with pytest.raises(Refused, match='artifact-failed'):
        with store:
            pytest.fail('symlink accepted')
    assert not (target / REQUEST).exists() and store._root_fd is None


@pytest.mark.parametrize('mode', [0o755, 0o777, 0o750])
def test_root_must_be_preprovisioned_private(tmp_path, mode):
    tmp_path.chmod(mode)
    with pytest.raises(Refused, match='artifact-failed'):
        with backup.NativeWindowArtifacts(str(tmp_path), REQUEST, owner=os.geteuid()):
            pytest.fail('permissive root accepted')
    assert not (tmp_path / REQUEST).exists()


def test_owner_mismatch_refuses_before_request_directory(tmp_path):
    tmp_path.chmod(0o700)
    with pytest.raises(Refused, match='artifact-failed'):
        with backup.NativeWindowArtifacts(str(tmp_path), REQUEST, owner=os.geteuid() + 1):
            pytest.fail('wrong owner accepted')
    assert not (tmp_path / REQUEST).exists()


def test_second_instance_or_second_capture_never_overwrites(custody):
    store, root, run = custody
    capture(store, 'dump', DUMP)
    with pytest.raises(Refused, match='artifact-failed'):
        with backup.NativeWindowArtifacts(str(root), REQUEST, owner=os.geteuid()):
            pytest.fail('same request reused')
    with pytest.raises(Refused, match='artifact-failed'):
        capture(store, 'dump', b'PGDMPother')
    assert (run / 'window.dump').read_bytes() == DUMP


@pytest.mark.parametrize('data', [b'', b'PGDMP', b'WRONG-HEADER'])
def test_invalid_or_empty_dump_cannot_be_sealed(custody, data):
    store, _, _ = custody
    with pytest.raises(Refused, match='artifact-failed'):
        capture(store, 'dump', data)
    with pytest.raises(Refused):
        capture(store, 'companion', COMPANION)


@pytest.mark.parametrize('kind', ['dump', 'companion'])
@pytest.mark.parametrize('extra', [0, 1])
def test_exact_size_bound_is_allowed_and_plus_one_refused(custody, monkeypatch, kind, extra):
    store, _, _ = custody
    monkeypatch.setattr(store, 'FILES', {key: (name, 16) for key, (name, _) in store.FILES.items()})
    data = ((b'PGDMP' + b'x' * 12) if kind == 'dump' else b'c' * 17)[:16 + extra]
    if extra:
        with pytest.raises(Refused, match='artifact-failed'):
            capture(store, kind, data)
    else:
        capture(store, kind, data)
        assert store._artifacts[kind]['size'] == 16


def test_empty_companion_and_incomplete_pair_refuse(custody):
    store, _, _ = custody
    capture(store, 'dump', DUMP)
    with pytest.raises(Refused, match='artifact-failed'):
        store.metadata()
    with pytest.raises(Refused):
        capture(store, 'companion', COMPANION)


def test_pipe_timeout_is_bounded_and_failure_does_not_retry(custody):
    store, _, run = custody
    with pipe() as (source, _):
        with pytest.raises(Refused, match='artifact-failed'):
            store.capture('dump', source, timeout=.02)
    assert (run / 'window.dump').stat().st_size == 0
    with pytest.raises(Refused):
        capture(store, 'dump', DUMP)


@pytest.mark.parametrize('kind', ['blocking', 'regular', 'closed'])
def test_only_nonblocking_pipe_input_is_admitted(custody, tmp_path, kind):
    store, _, _ = custody
    with pipe(DUMP) as (source, _):
        if kind == 'blocking':
            os.set_blocking(source, True)
        elif kind == 'regular':
            path = tmp_path / 'input'
            path.write_bytes(DUMP)
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                with pytest.raises(Refused):
                    store.capture('dump', fd, timeout=1)
            finally:
                os.close(fd)
            return
        else:
            source = 9999999
        with pytest.raises(Refused):
            store.capture('dump', source, timeout=1)


@pytest.mark.parametrize('mutation', ['symlink', 'replace', 'unlink', 'hardlink', 'mode', 'rewrite',
                                    'truncate', 'grow', 'run-rename', 'root-rename', 'run-mode', 'root-mode'])
def test_nominal_links_metadata_and_bytes_drift_all_refuse_before_output(custody, mutation):
    store, root, run = custody
    pair(store)
    artifact = run / 'window.dump'
    if mutation == 'symlink':
        artifact.rename(run / 'old')
        artifact.symlink_to(run / 'old')
    elif mutation == 'replace':
        artifact.rename(run / 'old')
        artifact.write_bytes(DUMP)
        artifact.chmod(0o600)
    elif mutation == 'unlink':
        artifact.unlink()
    elif mutation == 'hardlink':
        os.link(artifact, run / 'alias')
    elif mutation == 'mode':
        artifact.chmod(0o644)
    elif mutation == 'rewrite':
        stamp = artifact.stat()
        artifact.write_bytes(b'PGDMP' + b'x' * (len(DUMP) - 5))
        os.utime(artifact, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif mutation == 'truncate':
        artifact.write_bytes(b'PGDMPx')
    elif mutation == 'grow':
        with artifact.open('ab') as output:
            output.write(b'x')
    elif mutation == 'run-rename':
        run.rename(root / ('b' * 64))
        run.mkdir(mode=0o700)
    elif mutation == 'root-rename':
        root.rename(root.parent / 'old-root')
        root.mkdir(mode=0o700)
    elif mutation == 'run-mode':
        run.chmod(0o755)
    else:
        root.chmod(0o755)
    with pipe() as (read, target):
        with pytest.raises(Refused, match='artifact-failed') as error:
            store.copy_verified('dump', target, timeout=1)
        with pytest.raises(BlockingIOError):
            os.read(read, 1024)
    assert 'PRIVATE' not in str(error.value) and str(root) not in str(error.value)


def test_staging_is_fully_sealed_before_first_consumer_byte(custody, monkeypatch):
    store, _, _ = custody
    pair(store)
    write = backup.os.write
    staged = []
    create = backup.os.memfd_create

    def record(*args):
        fd = create(*args)
        staged.append(fd)
        return fd

    monkeypatch.setattr(backup.os, 'memfd_create', record)
    with pipe() as (read, target):
        def inspect_seals(fd, chunk):
            if fd == target:
                seals = fcntl.fcntl(staged[0], backup.MEMFD_GET_SEALS)
                assert seals & backup.MEMFD_SEALS == backup.MEMFD_SEALS
                with pytest.raises(PermissionError):
                    write(staged[0], b'altered')
                assert os.pread(staged[0], len(DUMP), 0) == DUMP
            return write(fd, chunk)

        monkeypatch.setattr(backup.os, 'write', inspect_seals)
        assert store.copy_verified('dump', target, timeout=1) == len(DUMP)
        assert os.read(read, 1024) == DUMP
    with pytest.raises(OSError):
        os.fstat(staged[0])


def test_mutation_while_building_staging_never_reaches_consumer(custody, monkeypatch):
    store, _, run = custody
    pair(store)
    create = backup.os.memfd_create

    def mutate(*args):
        fd = create(*args)
        (run / 'window.dump').write_bytes(b'PGDMPcorrupted')
        return fd

    monkeypatch.setattr(backup.os, 'memfd_create', mutate)
    with pipe() as (read, target):
        with pytest.raises(Refused):
            store.copy_verified('dump', target, timeout=1)
        with pytest.raises(BlockingIOError):
            os.read(read, 1024)


def test_close_releases_all_owned_descriptors_and_retains_files(custody):
    store, _, run = custody
    pair(store)
    fds = [store._root_fd, store._run_fd, *(item['fd'] for item in store._artifacts.values())]
    store.close()
    store.close()
    for fd in fds:
        with pytest.raises(OSError):
            os.fstat(fd)
    assert (run / 'window.dump').read_bytes() == DUMP
    with pytest.raises(Refused):
        store.metadata()


@pytest.mark.parametrize('kind', ['dump', 'companion'])
@pytest.mark.parametrize('existing', ['symlink', 'fifo', 'directory', 'file'])
def test_capture_never_follows_or_overwrites_existing_artifact(custody, kind, existing):
    store, _, run = custody
    target = run / store.FILES[kind][0]
    untouched = run / 'untouched'
    untouched.write_bytes(b'UNCHANGED-SYNTHETIC')
    if existing == 'symlink':
        target.symlink_to(untouched)
    elif existing == 'fifo':
        os.mkfifo(target, 0o600)
    elif existing == 'directory':
        target.mkdir()
    else:
        target.write_bytes(b'UNCHANGED-SYNTHETIC')
    with pytest.raises(Refused):
        capture(store, kind, DUMP if kind == 'dump' else COMPANION)
    assert untouched.read_bytes() == b'UNCHANGED-SYNTHETIC'
    if existing == 'file':
        assert target.read_bytes() == b'UNCHANGED-SYNTHETIC'


def test_empty_companion_is_refused(custody):
    store, _, _ = custody
    with pytest.raises(Refused):
        capture(store, 'companion', b'')


def test_backpressure_timeout_never_bypasses_nonblocking_output(custody):
    store, _, _ = custody
    pair(store)
    with pipe() as (_, target):
        while True:
            try:
                os.write(target, b'x' * 4096)
            except BlockingIOError:
                break
        with pytest.raises(Refused):
            store.copy_verified('dump', target, timeout=.02)
    with pytest.raises(Refused):
        store.metadata()


def test_short_consumer_writes_are_completed_without_duplicate_bytes(custody, monkeypatch):
    store, _, _ = custody
    pair(store)
    write = os.write
    with pipe() as (read, target):
        def short(fd, data):
            return write(fd, data[:3] if fd == target else data)
        monkeypatch.setattr(backup.os, 'write', short)
        assert store.copy_verified('dump', target, timeout=1) == len(DUMP)
        assert os.read(read, 1024) == DUMP


def test_zero_write_or_closed_consumer_refuses_and_sanitizes(custody, monkeypatch):
    store, _, _ = custody
    pair(store)
    write = os.write
    with pipe() as (_, target):
        def zero(fd, data):
            return 0 if fd == target else write(fd, data)
        monkeypatch.setattr(backup.os, 'write', zero)
        with pytest.raises(Refused, match='^window-origin-artifact-failed$'):
            store.copy_verified('dump', target, timeout=1)


def test_memfd_without_confirmed_seals_never_emits_bytes(custody, monkeypatch):
    store, _, _ = custody
    pair(store)
    call = fcntl.fcntl
    def missing(fd, operation, *args):
        return 0 if operation == backup.MEMFD_GET_SEALS else call(fd, operation, *args)
    monkeypatch.setattr(backup.fcntl, 'fcntl', missing)
    with pipe() as (read, target):
        with pytest.raises(Refused):
            store.copy_verified('dump', target, timeout=1)
        with pytest.raises(BlockingIOError):
            os.read(read, 1024)


def test_mutation_during_consumer_delivery_cannot_change_sealed_bytes(custody, monkeypatch):
    store, _, run = custody
    pair(store)
    write = os.write
    with pipe() as (read, target):
        def mutate(fd, chunk):
            if fd == target:
                (run / 'window.dump').write_bytes(b'PGDMPaltered')
            return write(fd, chunk)
        monkeypatch.setattr(backup.os, 'write', mutate)
        with pytest.raises(Refused):
            store.copy_verified('dump', target, timeout=1)
        assert os.read(read, 1024) == DUMP
    with pytest.raises(Refused):
        store.metadata()


def test_read_error_and_interrupt_are_sanitized_and_close_on_exit(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    store = backup.NativeWindowArtifacts(str(tmp_path), REQUEST, owner=os.geteuid())
    descriptors = []
    with pytest.raises(KeyboardInterrupt) as error:
        with store:
            pair(store)
            descriptors = [store._root_fd, store._run_fd, *(a['fd'] for a in store._artifacts.values())]
            def interrupted(*_args):
                raise KeyboardInterrupt('SYNTHETIC-PRIVATE-DO-NOT-LOG')
            monkeypatch.setattr(backup.os, 'pread', interrupted)
            store.metadata()
    assert str(error.value) == ''
    for fd in descriptors:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_artifact_change_during_hashing_is_detected_before_output(custody, monkeypatch):
    store, _, run = custody
    pair(store)
    pread = os.pread
    fired = False
    def change(fd, size, offset):
        nonlocal fired
        chunk = pread(fd, size, offset)
        if fd == store._artifacts['dump']['fd'] and not fired:
            fired = True
            (run / 'window.dump').write_bytes(b'PGDMPchanged')
        return chunk
    monkeypatch.setattr(backup.os, 'pread', change)
    with pipe() as (read, target):
        with pytest.raises(Refused):
            store.copy_verified('dump', target, timeout=1)
        with pytest.raises(BlockingIOError):
            os.read(read, 1024)


def test_final_directory_check_cannot_return_success_after_deadline(custody, monkeypatch):
    store, _, _ = custody
    pair(store)
    now, calls = [1000.0], []
    store.clock = lambda: now[0]
    links = store._links
    def slow_final():
        links()
        calls.append(True)
        if len(calls) == 4:  # final link check of the second artifact
            now[0] += 2
    monkeypatch.setattr(store, '_links', slow_final)
    with pytest.raises(Refused):
        store.metadata(timeout=1)
    assert len(calls) == 4


def test_seal_failure_closes_staging_and_exposes_no_prefix(custody, monkeypatch):
    store, _, _ = custody
    pair(store)
    call, create = fcntl.fcntl, os.memfd_create
    descriptors = []
    def record(*args):
        fd = create(*args)
        descriptors.append(fd)
        return fd
    def fail(fd, operation, *args):
        if operation == backup.MEMFD_ADD_SEALS:
            raise OSError('SYNTHETIC-PRIVATE-SEAL-FAILURE')
        return call(fd, operation, *args)
    monkeypatch.setattr(backup.os, 'memfd_create', record)
    monkeypatch.setattr(backup.fcntl, 'fcntl', fail)
    with pipe() as (read, target):
        with pytest.raises(Refused, match='^window-origin-artifact-failed$'):
            store.copy_verified('dump', target, timeout=1)
        with pytest.raises(BlockingIOError):
            os.read(read, 1024)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_broken_restore_pipe_fails_without_issuing_metadata(custody):
    store, _, _ = custody
    pair(store)
    read, target = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    os.close(read)
    try:
        with pytest.raises(Refused):
            store.copy_verified('dump', target, timeout=1)
    finally:
        os.close(target)
    with pytest.raises(Refused):
        store.metadata()


def test_native_multiblock_capture_and_restore_with_backpressure(custody):
    store, _, _ = custody
    data = b'PGDMP' + b'synthetic' * 32768
    source, producer = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    os.set_blocking(producer, True)
    errors = []
    def emit():
        try:
            offset = 0
            while offset < len(data):
                offset += os.write(producer, data[offset:offset + 32768])
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            os.close(producer)
    emitter = threading.Thread(target=emit, daemon=True)
    emitter.start()
    try:
        store.capture('dump', source, timeout=3)
    finally:
        os.close(source)
        emitter.join(timeout=3)
    assert not emitter.is_alive() and not errors
    capture(store, 'companion', COMPANION)
    read, target = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    os.set_blocking(read, True)
    received = bytearray()
    def consume():
        try:
            while True:
                chunk = os.read(read, 4096)
                if not chunk:
                    break
                received.extend(chunk)
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            os.close(read)
    consumer = threading.Thread(target=consume, daemon=True)
    consumer.start()
    try:
        assert store.copy_verified('dump', target, timeout=3) == len(data)
    finally:
        os.close(target)
        consumer.join(timeout=3)
    assert not consumer.is_alive() and not errors
    assert received == data
    assert store.metadata()['artifacts']['dump']['sha256'] == hashlib.sha256(data).hexdigest()
