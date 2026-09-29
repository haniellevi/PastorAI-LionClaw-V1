"""Compatibility entry point for retired synchronous EVT-7 delivery.

EVT-7 used to call Evolution directly after an event confirmation commit. The
public name remains for callers that have not yet moved, but it now only adds a
durable V2b outbox intention in the caller's open transaction.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.notification_outbox import enqueue_evt7_for_confirmed_event


def notify_event_confirmed(
    db: Session,
    event: object,
    **_legacy_dependencies: object,
) -> bool:
    """Queue EVT-7 without HTTP, commit, or a legacy delivery marker.

    ``settings`` and ``evolution`` remain accepted only for source-compatible
    callers. They have no effect and cannot reopen the old transport path.
    """

    return enqueue_evt7_for_confirmed_event(db, event) > 0


__all__ = ["notify_event_confirmed"]
