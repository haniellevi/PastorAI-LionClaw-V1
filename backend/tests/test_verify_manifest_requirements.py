from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import pytest

from scripts.verify_manifest_requirements import VerificationError, verify_manifest


class _Metadata(dict[str, str]):
    def __init__(self, extras: list[str] | None = None) -> None:
        super().__init__()
        self._extras = extras or []

    def get_all(self, name: str, failobj=None):  # noqa: ANN001, ANN201
        if name == "Provides-Extra":
            return self._extras
        return failobj


@dataclass
class _Distribution:
    version: str
    requires: list[str] | None = None
    extras: list[str] | None = None

    @property
    def metadata(self) -> _Metadata:
        return _Metadata(self.extras)


def _write_manifest(tmp_path: Path, content: str) -> Path:
    manifest = tmp_path / "requirements.in"
    manifest.write_text(content, encoding="utf-8")
    return manifest


def test_verifies_normalized_name_version_and_requested_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    distributions = {
        "demo-pkg": _Distribution(
            version="1.5",
            requires=["extra-child>=2; extra == 'feature_name'"],
            extras=["Feature_Name"],
        ),
        "extra-child": _Distribution(version="2.1"),
    }
    monkeypatch.setattr(
        metadata,
        "distribution",
        lambda name: distributions[name],
    )

    result = verify_manifest(
        _write_manifest(tmp_path, "Demo_Pkg[feature-name]>=1,<2  # direct\n")
    )

    assert result.direct_requirements == 1
    assert result.extra_requirements == 1


@pytest.mark.parametrize(
    ("manifest", "expected_error"),
    [
        ("missing>=1\n", "missing distribution"),
        ("demo>=2\n", "does not satisfy"),
        ("demo[unknown]>=1\n", "does not provide extra"),
    ],
)
def test_rejects_environment_that_does_not_satisfy_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    manifest: str,
    expected_error: str,
) -> None:
    demo = _Distribution(version="1.0", extras=["known"])

    def find_distribution(name: str) -> _Distribution:
        if name == "demo":
            return demo
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", find_distribution)

    with pytest.raises(VerificationError, match=expected_error):
        verify_manifest(_write_manifest(tmp_path, manifest))


def test_rejects_unsupported_manifest_directive(tmp_path: Path) -> None:
    with pytest.raises(VerificationError, match="unsupported manifest directive"):
        verify_manifest(_write_manifest(tmp_path, "-r other.txt\n"))


def test_ignores_inactive_environment_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        metadata,
        "distribution",
        lambda name: (_ for _ in ()).throw(metadata.PackageNotFoundError(name)),
    )

    result = verify_manifest(
        _write_manifest(tmp_path, "windows-only>=1; sys_platform == 'never'\n")
    )

    assert result.direct_requirements == 0


def test_rejects_missing_dependency_activated_by_extra(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = _Distribution(
        version="1.0",
        requires=["extra-child>=2; extra == 'feature'"],
        extras=["feature"],
    )

    def find_distribution(name: str) -> _Distribution:
        if name == "demo":
            return demo
        raise metadata.PackageNotFoundError(name)

    monkeypatch.setattr(metadata, "distribution", find_distribution)

    with pytest.raises(VerificationError, match="missing distribution: extra-child"):
        verify_manifest(_write_manifest(tmp_path, "demo[feature]>=1\n"))
