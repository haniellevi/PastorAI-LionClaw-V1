from __future__ import annotations

from dataclasses import replace
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
from typing import Callable

import pytest

from scripts import trusted_repository_snapshot as snapshot_tool


PLAIN_CONTENT = b"plain source\n"
RUNNER_CONTENT = b"#!/usr/bin/env python3\nprint('safe')\n"
NESTED_CONTENT = b"nested source\n"


def _git(repository: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": os.defpath,
        },
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    return completed.stdout


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "--all")
    _git(
        repository,
        "-c",
        "user.name=Snapshot Test",
        "-c",
        "user.email=snapshot-test@invalid.example",
        "commit",
        "--quiet",
        "-m",
        message,
    )
    return _git(repository, "rev-parse", "HEAD").decode("ascii").strip()


@pytest.fixture
def local_repository(tmp_path: Path) -> tuple[Path, str]:
    repository = tmp_path / "source"
    repository.mkdir(mode=0o700)
    _git(repository, "init", "--quiet")
    (repository / "plain.txt").write_bytes(PLAIN_CONTENT)
    runner = repository / "runner.py"
    runner.write_bytes(RUNNER_CONTENT)
    runner.chmod(0o755)
    nested = repository / "nested"
    nested.mkdir()
    (nested / "data.txt").write_bytes(NESTED_CONTENT)
    return repository, _commit(repository, "initial")


def _real_archive(repository: Path, git_sha: str) -> bytes:
    return _git(repository, "-c", "tar.umask=0022", "archive", "--format=tar", git_sha)


def _write_archive_bytes(content: bytes) -> snapshot_tool.ArchiveWriter:
    def writer(_repository: Path, _git_sha: str, descriptor: int) -> None:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            assert written > 0
            offset += written

    return writer


def _synthetic_archive(
    *,
    plain_content: bytes = PLAIN_CONTENT,
    plain_type: bytes = tarfile.REGTYPE,
    plain_linkname: str = "",
    plain_mode: int = 0o644,
    include_plain: bool = True,
    extra: tarfile.TarInfo | None = None,
) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        directory = tarfile.TarInfo("nested")
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)

        files = {
            "runner.py": (RUNNER_CONTENT, 0o755),
            "nested/data.txt": (NESTED_CONTENT, 0o644),
        }
        for name, (content, mode) in files.items():
            member = tarfile.TarInfo(name)
            member.type = tarfile.REGTYPE
            member.mode = mode
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))

        if include_plain:
            member = tarfile.TarInfo("plain.txt")
            member.type = plain_type
            member.mode = plain_mode
            member.linkname = plain_linkname
            if plain_type == tarfile.REGTYPE:
                member.size = len(plain_content)
                archive.addfile(member, io.BytesIO(plain_content))
            else:
                member.size = 0
                if plain_type in {tarfile.CHRTYPE, tarfile.BLKTYPE}:
                    member.devmajor = 1
                    member.devminor = 3
                archive.addfile(member)
        if extra is not None:
            archive.addfile(extra, io.BytesIO(b"x") if extra.size else None)
    return output.getvalue()


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_happy_path_uses_exact_commit_and_normalizes_private_modes(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    previous_umask = os.umask(0o002)
    created: snapshot_tool.RepositorySnapshot | None = None
    try:
        created = snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
        )
    finally:
        os.umask(previous_umask)

    try:
        assert created.root.parent == Path("/tmp")
        assert created.repository == created.root / "repo"
        assert created.git_sha == git_sha
        assert created.file_count == 3
        assert created.tree_count == 1
        assert _mode(created.root) == 0o700
        assert _mode(created.repository) == 0o700
        assert _mode(created.repository / "nested") == 0o700
        for relative, expected in {
            "plain.txt": PLAIN_CONTENT,
            "runner.py": RUNNER_CONTENT,
            "nested/data.txt": NESTED_CONTENT,
        }.items():
            materialized = created.repository / relative
            metadata = materialized.lstat()
            assert stat.S_ISREG(metadata.st_mode)
            assert stat.S_IMODE(metadata.st_mode) == 0o600
            assert metadata.st_nlink == 1
            assert metadata.st_uid == os.geteuid()
            assert metadata.st_gid == os.getegid()
            assert materialized.read_bytes() == expected
        assert not (created.repository / ".git").exists()
    finally:
        created.cleanup()
    assert not created.root.exists()
    created.cleanup()


def test_two_snapshots_have_distinct_random_roots(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    first = snapshot_tool.create_trusted_repository_snapshot(
        repository_root=repository,
        git_sha=git_sha,
    )
    second = snapshot_tool.create_trusted_repository_snapshot(
        repository_root=repository,
        git_sha=git_sha,
    )
    try:
        assert first.root != second.root
        assert first.root.parent == second.root.parent == Path("/tmp")
    finally:
        first.cleanup()
        second.cleanup()


@pytest.mark.parametrize(
    "invalid",
    [
        "HEAD",
        "main",
        "a" * 7,
        "A" * 40,
        "0" * 40,
        "a" * 39,
        "a" * 41,
        "a" * 64 + "^{}",
        "a" * 40 + " --remote=origin",
        None,
    ],
)
def test_sha_must_be_explicit_full_lowercase_object_id(invalid: object) -> None:
    with pytest.raises(snapshot_tool.UsageError):
        snapshot_tool._validated_sha(invalid)


def test_commit_manifest_and_extracted_blob_must_match(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    tampered = bytearray(PLAIN_CONTENT)
    tampered[-2] ^= 1
    with pytest.raises(snapshot_tool.ArchiveError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            archive_writer=_write_archive_bytes(
                _synthetic_archive(plain_content=bytes(tampered))
            ),
        )


def test_manifest_root_tree_id_is_recomputed(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    manifest = snapshot_tool._load_manifest(
        repository,
        git_sha,
        snapshot_tool._run_git_control,
    )
    corrupted = replace(manifest, root_tree_id="f" * len(manifest.root_tree_id))
    with pytest.raises(snapshot_tool.GitEvidenceError):
        snapshot_tool._validate_tree_ids(corrupted)


def test_git_replace_cannot_redirect_explicit_commit(
    local_repository: tuple[Path, str],
) -> None:
    repository, commit_a = local_repository
    (repository / "plain.txt").write_bytes(b"replacement content\n")
    commit_b = _commit(repository, "replacement")
    _git(repository, "replace", commit_a, commit_b)

    created = snapshot_tool.create_trusted_repository_snapshot(
        repository_root=repository,
        git_sha=commit_a,
    )
    try:
        assert created.git_sha == commit_a
        assert (created.repository / "plain.txt").read_bytes() == PLAIN_CONTENT
        assert (created.repository / "plain.txt").read_bytes() != (
            repository / "plain.txt"
        ).read_bytes()
    finally:
        created.cleanup()


def test_raw_commit_hash_is_recomputed_before_tree_use(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository

    def tampered_control(
        root: Path,
        args: tuple[str, ...],
        maximum: int,
    ) -> bytes:
        content = snapshot_tool._run_git_control(root, args, maximum)
        if args == ("cat-file", "commit", git_sha):
            return content + b"tampered"
        return content

    with pytest.raises(snapshot_tool.GitEvidenceError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            git_control=tampered_control,
        )


def test_authenticated_commit_tree_must_match_resolved_tree(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository

    def mismatched_tree_control(
        root: Path,
        args: tuple[str, ...],
        maximum: int,
    ) -> bytes:
        if args == ("rev-parse", "--verify", f"{git_sha}^{{tree}}"):
            return ("f" * len(git_sha) + "\n").encode("ascii")
        return snapshot_tool._run_git_control(root, args, maximum)

    with pytest.raises(snapshot_tool.GitEvidenceError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            git_control=mismatched_tree_control,
        )


@pytest.mark.parametrize(
    "headers",
    [
        lambda tree: b"author Nobody <nobody@invalid> 0 +0000\n" + b"tree " + tree,
        lambda tree: b"tree " + tree + b"\ntree " + tree,
        lambda tree: b"tree short",
    ],
    ids=["tree-not-first", "duplicate-tree", "malformed-tree"],
)
def test_commit_tree_header_is_strict(
    headers: Callable[[bytes], bytes],
) -> None:
    tree_id = b"1" * 40
    content = headers(tree_id) + b"\n\nmessage\n"
    commit_id = snapshot_tool._hash_git_object("sha1", "commit", content)
    with pytest.raises(snapshot_tool.GitEvidenceError):
        snapshot_tool._validated_commit_tree(
            object_format="sha1",
            expected_commit_id=commit_id,
            content=content,
        )


def test_archive_traversal_is_rejected_and_failure_cleans_only_its_root(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    traversal = tarfile.TarInfo("../outside-snapshot-test")
    traversal.type = tarfile.REGTYPE
    traversal.mode = 0o644
    traversal.size = 1
    created_root: list[Path] = []
    content = _synthetic_archive(extra=traversal)

    def writer(source: Path, sha: str, descriptor: int) -> None:
        created_root.append(Path(os.readlink(f"/proc/self/fd/{descriptor}")).parent)
        _write_archive_bytes(content)(source, sha, descriptor)

    outside = Path("/tmp/outside-snapshot-test")
    assert not outside.exists()
    with pytest.raises(snapshot_tool.ArchiveError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            archive_writer=writer,
        )
    assert len(created_root) == 1
    assert not created_root[0].exists()
    assert not outside.exists()


@pytest.mark.parametrize(
    ("member_type", "linkname"),
    [
        (tarfile.SYMTYPE, "nested/data.txt"),
        (tarfile.LNKTYPE, "nested/data.txt"),
        (tarfile.FIFOTYPE, ""),
        (tarfile.CHRTYPE, ""),
        (tarfile.BLKTYPE, ""),
    ],
)
def test_archive_links_fifo_and_devices_are_rejected(
    local_repository: tuple[Path, str],
    member_type: bytes,
    linkname: str,
) -> None:
    repository, git_sha = local_repository
    with pytest.raises(snapshot_tool.ArchiveError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            archive_writer=_write_archive_bytes(
                _synthetic_archive(
                    plain_type=member_type,
                    plain_linkname=linkname,
                )
            ),
        )


@pytest.mark.parametrize(
    "archive",
    [
        _synthetic_archive(include_plain=False),
        _synthetic_archive(plain_mode=0o666),
    ],
    ids=["missing-entry", "wrong-git-mode"],
)
def test_archive_missing_entry_or_mode_drift_is_rejected(
    local_repository: tuple[Path, str],
    archive: bytes,
) -> None:
    repository, git_sha = local_repository
    with pytest.raises(snapshot_tool.ArchiveError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            archive_writer=_write_archive_bytes(archive),
        )


def test_git_symlink_is_rejected_before_archive(
    local_repository: tuple[Path, str],
) -> None:
    repository, _ = local_repository
    os.symlink("plain.txt", repository / "linked.txt")
    git_sha = _commit(repository, "symlink")
    archive_called = False

    def archive_writer(_source: Path, _sha: str, _fd: int) -> None:
        nonlocal archive_called
        archive_called = True

    with pytest.raises(snapshot_tool.GitEvidenceError):
        snapshot_tool.create_trusted_repository_snapshot(
            repository_root=repository,
            git_sha=git_sha,
            archive_writer=archive_writer,
        )
    assert archive_called is False


def test_protected_environment_file_is_rejected_without_reading_blob(
    local_repository: tuple[Path, str],
) -> None:
    repository, _ = local_repository
    protected = repository / ".env.production"
    protected.write_text("must-not-be-archived", encoding="utf-8")
    git_sha = _commit(repository, "protected path")
    protected.chmod(0)
    archive_called = False

    def archive_writer(_source: Path, _sha: str, _fd: int) -> None:
        nonlocal archive_called
        archive_called = True

    try:
        with pytest.raises(snapshot_tool.GitEvidenceError):
            snapshot_tool.create_trusted_repository_snapshot(
                repository_root=repository,
                git_sha=git_sha,
                archive_writer=archive_writer,
            )
        assert archive_called is False
    finally:
        protected.chmod(0o600)


def test_source_identity_mutation_fails_and_cleans_created_root(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    content = _real_archive(repository, git_sha)
    original_mode = _mode(repository)
    changed_mode = 0o700 if original_mode != 0o700 else 0o750
    created_root: list[Path] = []

    def writer(source: Path, sha: str, descriptor: int) -> None:
        created_root.append(Path(os.readlink(f"/proc/self/fd/{descriptor}")).parent)
        _write_archive_bytes(content)(source, sha, descriptor)
        repository.chmod(changed_mode)

    try:
        with pytest.raises(snapshot_tool.GitEvidenceError):
            snapshot_tool.create_trusted_repository_snapshot(
                repository_root=repository,
                git_sha=git_sha,
                archive_writer=writer,
            )
    finally:
        repository.chmod(original_mode)
    assert len(created_root) == 1
    assert not created_root[0].exists()


def test_cleanup_refuses_replaced_root_and_preserves_both_trees(
    local_repository: tuple[Path, str],
) -> None:
    repository, git_sha = local_repository
    created = snapshot_tool.create_trusted_repository_snapshot(
        repository_root=repository,
        git_sha=git_sha,
    )
    moved = created.root.with_name(f"{created.root.name}-moved")
    created.root.rename(moved)
    created.root.mkdir(mode=0o700)
    marker = created.root / "do-not-delete"
    marker.write_text("replacement", encoding="utf-8")
    try:
        with pytest.raises(snapshot_tool.CleanupError):
            created.cleanup()
        assert marker.read_text(encoding="utf-8") == "replacement"
        assert (moved / "repo" / "plain.txt").read_bytes() == PLAIN_CONTENT
    finally:
        shutil.rmtree(created.root)
        shutil.rmtree(moved)


def test_tmp_contract_is_real_sticky_and_not_owned_by_caller() -> None:
    descriptor = snapshot_tool._open_trusted_temp_root()
    try:
        metadata = os.fstat(descriptor)
        assert stat.S_ISDIR(metadata.st_mode)
        assert stat.S_IMODE(metadata.st_mode) == 0o1777
        assert metadata.st_uid == 0 or metadata.st_uid != os.geteuid()
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("failure_phase", ["open", "fstat"])
def test_private_root_creation_fault_is_cleaned_by_captured_inode(
    monkeypatch: pytest.MonkeyPatch,
    failure_phase: str,
) -> None:
    random_bytes = b"\xab" * 16
    basename = f"{snapshot_tool.SNAPSHOT_PREFIX}{random_bytes.hex()}"
    root = Path("/tmp") / basename
    assert not root.exists()
    real_open_directory_at = snapshot_tool._open_directory_at

    def fail_after_mkdir(parent_fd: int, name: str) -> int:
        if name != basename:
            return real_open_directory_at(parent_fd, name)
        if failure_phase == "fstat":
            descriptor = os.open(
                name,
                snapshot_tool._directory_flags(),
                dir_fd=parent_fd,
            )
            os.close(descriptor)
        raise snapshot_tool.FilesystemError

    monkeypatch.setattr(snapshot_tool.os, "urandom", lambda size: random_bytes)
    monkeypatch.setattr(snapshot_tool, "_open_directory_at", fail_after_mkdir)

    with pytest.raises(snapshot_tool.FilesystemError):
        snapshot_tool._create_private_root()
    assert not root.exists()


def test_git_subprocess_is_shell_free_and_does_not_inherit_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setenv("SNAPSHOT_SECRET_SENTINEL", "must-not-propagate")

    def fake_run(command: list[str], **kwargs: object) -> object:
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, stdout=b"sha1\n")

    monkeypatch.setattr(snapshot_tool.subprocess, "run", fake_run)
    assert snapshot_tool._run_git_control(
        tmp_path,
        ("rev-parse", "--show-object-format"),
        32,
    ) == b"sha1\n"
    assert "shell" not in observed or observed["shell"] is False
    assert "SNAPSHOT_SECRET_SENTINEL" not in observed["env"]
    assert observed["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
    command = observed["command"]
    assert isinstance(command, list)
    assert command[1] == "--no-replace-objects"
    assert not any(
        token in command
        for token in ("fetch", "pull", "push", "--remote", "http://", "https://")
    )


def test_cli_uses_implicit_repository_and_emits_only_sanitized_blocked_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    git_sha = "a" * 40
    fake = snapshot_tool.RepositorySnapshot(
        root=Path("/tmp/pastorai-trusted-repository-fixed"),
        repository=Path("/tmp/pastorai-trusted-repository-fixed/repo"),
        git_sha=git_sha,
        file_count=3,
        tree_count=1,
        _root_identity=snapshot_tool.ObjectIdentity(1, 2, os.geteuid(), os.getegid()),
    )
    received: list[object] = []

    def create(**kwargs: object) -> snapshot_tool.RepositorySnapshot:
        received.append(kwargs)
        return fake

    monkeypatch.setattr(snapshot_tool, "create_trusted_repository_snapshot", create)
    assert snapshot_tool.main(["--git-sha", git_sha]) == 0
    assert received == [{"git_sha": git_sha}]
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out.splitlines() == [
        snapshot_tool.RESULT_CREATED,
        f"SOURCE_GIT_SHA={git_sha}",
        f"SNAPSHOT_ROOT={fake.root}",
        f"SNAPSHOT_REPOSITORY={fake.repository}",
        "REGULAR_FILE_COUNT=3",
        "TREE_COUNT=1",
        "OPERATIONAL_AUTHORIZATION=false",
        "NEXT_STAGE_AUTHORIZED=false",
    ]


def test_cli_failure_does_not_echo_untrusted_input(
    capsys: pytest.CaptureFixture[str],
) -> None:
    untrusted = "secret-looking-ref"
    assert snapshot_tool.main(["--git-sha", untrusted]) == 2
    output = capsys.readouterr()
    assert output.err == ""
    assert untrusted not in output.out
    assert output.out.splitlines() == [
        "RESULT=BLOCKED_TRUSTED_REPOSITORY_SNAPSHOT:USAGE",
        "OPERATIONAL_AUTHORIZATION=false",
        "NEXT_STAGE_AUTHORIZED=false",
    ]
