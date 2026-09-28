"""Bounded cron liveness for a fake provider that outlives its deadline."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, enumerate as threads
import time

import pytest

from app.services.cell_report_audio_service import _run_audio_boundary
from app.services import cell_report_audio_service as service


def test_audio_heartbeat_stops_at_deadline_while_provider_remains_blocked():
    started, release = Event(), Event()
    progress = []
    def operation():
        started.set()
        assert release.wait(3)
        return 'synthetic result'
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run_audio_boundary, operation,
            deadline_at=time.monotonic() + .08,
            progress_callback=lambda: progress.append(time.monotonic()))
        try:
            assert started.wait(1)
            time.sleep(.15)
            at_deadline = len(progress)
            assert at_deadline > 0 and not future.done()
            time.sleep(.1)
            assert len(progress) == at_deadline
        finally:
            release.set()
        with pytest.raises(service.CellReportAudioServiceError):
            future.result(timeout=2)
    assert not any(t.name == 'cell-report-audio-boundary' for t in threads())


def test_audio_heartbeat_is_joined_when_provider_raises():
    progress = []
    def fail():
        raise TimeoutError('synthetic provider timeout')
    with pytest.raises(TimeoutError, match='synthetic'):
        _run_audio_boundary(fail, deadline_at=time.monotonic() + 1,
            progress_callback=lambda: progress.append(True))
    assert progress
    assert not any(t.name == 'cell-report-audio-boundary' for t in threads())


@pytest.mark.parametrize('with_progress', (False, True))
def test_audio_boundary_rejects_late_success_even_without_progress(monkeypatch, with_progress):
    clock = [10.0]
    monkeypatch.setattr(service.time, 'monotonic', lambda: clock[0])
    def late():
        clock[0] = 12.0
        return 'late synthetic result'
    with pytest.raises(service.CellReportAudioServiceError):
        _run_audio_boundary(late, deadline_at=11.0,
            progress_callback=(lambda: None) if with_progress else None)
