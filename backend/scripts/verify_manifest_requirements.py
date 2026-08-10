"""Verify that a lock-installed environment satisfies a direct manifest.

This checker is intentionally offline.  It validates the environment produced
from a reviewed lock file; it does not resolve or update dependencies.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
import sys

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


class VerificationError(RuntimeError):
    """Raised when a manifest or installed environment violates the contract."""


@dataclass(frozen=True)
class VerificationResult:
    direct_requirements: int
    extra_requirements: int


def load_manifest(path: Path) -> list[Requirement]:
    """Load the simple direct-requirement format used by this repository."""
    requirements: list[Requirement] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.partition("#")[0].strip()
        if not line:
            continue
        if line.startswith("-") or line.endswith("\\"):
            raise VerificationError(
                f"{path}:{line_number}: unsupported manifest directive"
            )
        try:
            requirements.append(Requirement(line))
        except InvalidRequirement as exc:
            raise VerificationError(
                f"{path}:{line_number}: invalid requirement"
            ) from exc
    if not requirements:
        raise VerificationError(f"{path}: manifest has no requirements")
    return requirements


def _marker_applies(requirement: Requirement, *, extra: str = "") -> bool:
    if requirement.marker is None:
        return True
    environment = default_environment()
    environment["extra"] = extra
    return requirement.marker.evaluate(environment)


def _require_installed(requirement: Requirement) -> metadata.Distribution:
    normalized_name = canonicalize_name(requirement.name)
    try:
        distribution = metadata.distribution(normalized_name)
    except metadata.PackageNotFoundError as exc:
        raise VerificationError(f"missing distribution: {normalized_name}") from exc

    installed_version = distribution.version
    if requirement.specifier and not requirement.specifier.contains(
        installed_version, prereleases=True
    ):
        raise VerificationError(
            f"{normalized_name}=={installed_version} does not satisfy "
            f"{requirement.specifier}"
        )
    return distribution


def _verify_requested_extras(
    requirement: Requirement, distribution: metadata.Distribution
) -> int:
    declared_extras = {
        canonicalize_name(value)
        for value in distribution.metadata.get_all("Provides-Extra", failobj=[]) or []
    }
    extra_requirements = 0

    for requested_extra in sorted(requirement.extras):
        normalized_extra = canonicalize_name(requested_extra)
        if normalized_extra not in declared_extras:
            raise VerificationError(
                f"{canonicalize_name(requirement.name)} does not provide extra "
                f"{normalized_extra}"
            )

        for raw_dependency in distribution.requires or []:
            try:
                dependency = Requirement(raw_dependency)
            except InvalidRequirement as exc:
                raise VerificationError(
                    f"invalid Requires-Dist for {canonicalize_name(requirement.name)}"
                ) from exc
            if not _marker_applies(dependency, extra=normalized_extra):
                continue
            _require_installed(dependency)
            extra_requirements += 1

    return extra_requirements


def verify_manifest(path: Path) -> VerificationResult:
    direct_requirements = 0
    extra_requirements = 0

    for requirement in load_manifest(path):
        if not _marker_applies(requirement):
            continue
        distribution = _require_installed(requirement)
        direct_requirements += 1
        extra_requirements += _verify_requested_extras(requirement, distribution)

    return VerificationResult(
        direct_requirements=direct_requirements,
        extra_requirements=extra_requirements,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a lock-installed environment against a direct manifest."
    )
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)

    try:
        result = verify_manifest(args.manifest)
    except (OSError, VerificationError) as exc:
        print(f"requirement verification failed: {exc}", file=sys.stderr)
        return 1

    print(
        "requirement verification passed: "
        f"{result.direct_requirements} direct, "
        f"{result.extra_requirements} extra-activated"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
