"""A data civil muda à meia-noite de São Paulo, não à meia-noite UTC."""
from datetime import date, datetime, timezone

import pytest

from app import datas


@pytest.mark.parametrize(('hour', 'expected'), [(2, date(2026, 10, 8)), (3, date(2026, 10, 9))])
def test_hoje_da_igreja_at_utc_boundary(monkeypatch, hour, expected):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 9, hour, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(datas, 'datetime', Clock)
    assert datas.hoje_da_igreja() == expected
