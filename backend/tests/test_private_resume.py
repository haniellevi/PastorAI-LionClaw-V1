"""The release defaults must not query memory or cross a provider boundary."""
from types import SimpleNamespace
from uuid import uuid4

from app.services import private_resume as resume


def test_default_release_never_reads_memory():
    class NoDatabase:
        def execute(self, *args, **kwargs):
            raise AssertionError('Default release must not read memory')

    context = SimpleNamespace(igreja_id=uuid4())
    assert not resume.released(context.igreja_id)
    assert resume.load(NoDatabase(), context) is None
    assert not resume.still_current(NoDatabase(), context, {})


def test_forged_actor_does_not_read_memory(monkeypatch):
    tenant = uuid4()
    monkeypatch.setattr(resume, 'PRIVATE_RESUME_APPROVED_RELEASE_ID', 'synthetic')
    monkeypatch.setattr(resume, 'PRIVATE_RESUME_APPROVED_IGREJA_IDS', frozenset({str(tenant)}))
    assert resume.load(None, SimpleNamespace(igreja_id=tenant)) is None
    assert not resume.still_current(None, SimpleNamespace(igreja_id=tenant), dict(version=1, source_revision=1, deletion_generation=1))
