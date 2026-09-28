"""EVT-7 compatibility seam no longer owns a provider transport."""

from __future__ import annotations

from types import SimpleNamespace

from app.services import event_notify


def test_legacy_evt7_entrypoint_only_delegates_to_the_durable_enqueue(monkeypatch) -> None:
    session = SimpleNamespace()
    event = SimpleNamespace()
    calls: list[tuple[object, object]] = []

    def enqueue(received_session, received_event) -> int:
        calls.append((received_session, received_event))
        return 1

    monkeypatch.setattr(event_notify, "enqueue_evt7_for_confirmed_event", enqueue)

    assert event_notify.notify_event_confirmed(
        session,
        event,
        settings=object(),
        evolution=object(),
    )
    assert calls == [(session, event)]


def test_legacy_evt7_module_has_no_evolution_transport_reference() -> None:
    source = event_notify.__file__
    assert source is not None
    contents = open(source, encoding="utf-8").read()
    assert "send_text" not in contents
    assert "EvolutionClient" not in contents
