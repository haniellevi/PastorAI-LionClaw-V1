"""Effective role matrix filtering at the router boundary, without HTTP I/O."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

from app.db.models import RolePermission
from app.routers.roles import PermissionsMatrix, get_permissions, update_permissions


IGREJA_ID = "00000000-0000-0000-0000-000000000001"


class _Rows:
    def __init__(self, rows: list[RolePermission]) -> None:
        self._rows = rows

    def scalars(self) -> _Rows:
        return self

    def all(self) -> list[RolePermission]:
        return list(self._rows)


class _Session:
    def __init__(self, existing: list[RolePermission] | None = None) -> None:
        self.existing = existing or []
        self.added: list[RolePermission] = []
        self.deleted: list[RolePermission] = []
        self.flushes = 0
        self.commits = 0

    def execute(self, _statement) -> _Rows:
        return _Rows(self.existing)

    def add(self, row: RolePermission) -> None:
        self.added.append(row)

    def delete(self, row: RolePermission) -> None:
        self.deleted.append(row)

    def flush(self) -> None:
        self.flushes += 1

    def commit(self) -> None:
        self.commits += 1


def _row(role: str, screen: str) -> RolePermission:
    return RolePermission(
        igreja_id=UUID(IGREJA_ID),
        papel=role,
        tela=screen,
    )


def test_get_returns_effective_matrix_without_legacy_central_grant() -> None:
    session = _Session(
        [
            _row("lider_celula", "dashboard"),
            _row("lider_celula", "minha-celula"),
            _row("lider_celula", "central-celula"),
        ]
    )

    result = get_permissions(
        db=session,  # type: ignore[arg-type]
        current_user=SimpleNamespace(igreja_id=IGREJA_ID),  # type: ignore[arg-type]
    )

    assert result.matriz["lider_celula"] == ["dashboard", "minha-celula"]


def test_put_filters_central_grant_before_persisting() -> None:
    session = _Session()
    payload = PermissionsMatrix(
        matriz={
            "lider_celula": [
                "dashboard",
                "minha-celula",
                "central-celula",
            ]
        }
    )

    result = update_permissions(
        payload,
        db=session,  # type: ignore[arg-type]
        current_user=SimpleNamespace(igreja_id=IGREJA_ID),  # type: ignore[arg-type]
    )

    assert result.matriz["lider_celula"] == ["dashboard", "minha-celula"]
    persisted = {(row.papel, row.tela) for row in session.added}
    assert ("lider_celula", "central-celula") not in persisted
    assert ("lider_celula", "minha-celula") in persisted
    assert session.flushes == 1
    assert session.commits == 1
