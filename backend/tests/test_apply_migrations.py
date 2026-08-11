from __future__ import annotations

import builtins

import pytest

from scripts import apply_migrations


def test_missing_psycopg2_points_to_hashed_runtime_lock(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = builtins.__import__

    def import_without_psycopg2(name: str, *args, **kwargs):  # noqa: ANN002, ANN003
        if name == "psycopg2":
            raise ImportError("simulated missing driver")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_psycopg2)

    with pytest.raises(SystemExit) as exc_info:
        apply_migrations._connect("postgresql://unused")

    assert exc_info.value.code == 3
    message = capsys.readouterr().err
    assert "python -m pip install --require-hashes -r requirements.lock" in message
    assert "pip install -r requirements.txt" not in message
    assert "requirements.txt" not in message
    assert not any(
        forbidden in message.lower()
        for forbidden in ("compile", "upgrade", "update", "atualiz", "regener", "uvx")
    )
