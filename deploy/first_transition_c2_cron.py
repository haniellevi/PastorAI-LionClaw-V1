"""Pure nominal cron admission; no scanning, filesystem reads or authority grant.

Only exact /etc/crontab, /etc/cron.d/<name> and Debian-style per-user spool
configuration names can be admitted. This intentionally does not discover all
schedulers or claim their absence. Fixture mapping never resolves symlinks.
"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re

from initial_transition_files import is_protected
from initial_transition_ops import Refused

CODE = "c2-cron-path-refused"
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
USER = re.compile(r"[a-z_][a-z0-9_-]{0,31}")


def need(value):
    if not value:
        raise Refused(CODE)


def normalized(value):
    need(type(value) is str and 0 < len(value) <= 4096)
    need(value.startswith("/") and not value.startswith("//"))
    need(str(PurePosixPath(value)) == value)
    need(".." not in PurePosixPath(value).parts)
    need(not any(ord(c) < 32 or ord(c) == 127 for c in value))
    need(not is_protected(PurePosixPath(value).parts))
    return value


def nominal(path):
    normalized(path)
    if path == "/etc/crontab":
        return
    parts = PurePosixPath(path).parts
    need(
        len(parts) == 4
        and parts[1:3] == ("etc", "cron.d")
        and NAME.fullmatch(parts[3])
        or len(parts) == 6
        and parts[1:5] == ("var", "spool", "cron", "crontabs")
        and USER.fullmatch(parts[5])
    )


@dataclass(frozen=True, repr=False)
class CronPathPolicy:
    """Exact ordered inventory and optional explicit fixture prefix, immutable.

    No globs, roots-only admissions, arbitrary files or path normalization is
    performed. Real inventory completeness and source ownership are separate
    operational obligations. A fixture marker is not a security boundary.
    """

    files: tuple[str, ...]
    fixture_root: str = "/"
    synthetic_only: bool = False

    def __post_init__(self):
        self.validated()

    def validated(self):
        need(
            type(self.files) is tuple
            and 0 < len(self.files) <= 64
            and all(type(p) is str for p in self.files)
            and len(set(self.files)) == len(self.files)
            and type(self.synthetic_only) is bool
        )
        for path in self.files:
            nominal(path)
        normalized(self.fixture_root)
        need(
            self.fixture_root == "/"
            or self.synthetic_only is True
            and self.fixture_root.startswith("/tmp/")
        )
        return self

    @property
    def paths(self):
        self.validated()
        prefix = "" if self.fixture_root == "/" else self.fixture_root
        return tuple(prefix + path for path in self.files)

    @property
    def digest(self):
        self.validated()
        body = json.dumps(
            [list(self.files), self.fixture_root, self.synthetic_only],
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(body).hexdigest()

    def admit(self, paths):
        self.validated()
        need(type(paths) is tuple and paths == self.paths)
        for path in paths:
            normalized(path)
        return True
