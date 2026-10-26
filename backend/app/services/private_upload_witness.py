"""Positive reconciliation of audio uploads whose response was lost.

Only ownership carrying an attempt token and blocking a pending cleanup task is
considered. Storage info showing that exact token at the task's path proves the
attempt committed, so it can no longer land later: ownership is released and
the existing strict cleanup DELETEs the path. Absence, errors, timeouts or
elapsed time prove nothing and keep ownership; aborted/in-flight attempts and
legacy ownership (no token) stay retained. A byte-identical duplicate of the
same POST is not distinguishable by the token (same limit as the 2xx finish).

Runs only under the dedicated login. Three steps, no transaction or lock open
during HTTP: (1) a short read reservation: it row-locks only the ownership
(schedule update) and reads task/path without locks, so it never waits while
holding another lock; (2) one bounded Storage GET; (3) a new release
transaction taking the receipt lock before the task and ownership rows (the
order of cleanup and finish), revalidating the task and path, and removing
ownership only by token CAS. A database error before COMMIT keeps ownership;
an uncertain COMMIT acknowledgement leaves it unknown, which is safe because
the release is only attempted for an attempt already proven committed.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.privacy_storage_session import scope_private_storage

logger = logging.getLogger("pastorai.private_upload_witness")

# Few Storage reads per tick so cleanup of everything else is never starved.
WITNESS_BATCH_LIMIT = 10


def _claim_read(db: Session, job: dict, current: dt.datetime) -> tuple[UUID, str] | None:
    """Reserve the next read before HTTP: a crash or a second worker waits for it."""
    token = db.execute(text("""update private_deletion_uploads
        set witness_attempts=witness_attempts+1,
            witness_check_at=:now + least(3600, 60 * 2 ^ least(witness_attempts, 6)) * interval '1 second'
        where igreja_id=:t and source_id=:source and attempt_token is not null
         and (witness_check_at is null or witness_check_at<=:now)
        returning attempt_token"""),
        dict(t=job['igreja_id'], source=job['source_id'], now=current)).scalar_one_or_none()
    if token is None:
        return None
    pending = db.execute(text("""select 1 from private_deletion_tasks where id=:id
        and igreja_id=:t and receipt_id=:r and source_id=:source and state='pendente'"""),
        dict(id=job['task_id'], t=job['igreja_id'], r=job['receipt_id'], source=job['source_id'])
    ).scalar_one_or_none()
    path = db.execute(text('select private_deletion_task_path(:id)'), dict(id=job['task_id'])).scalar_one()
    if pending is None or path is None:
        return None
    return UUID(str(token)), path


def _release(db: Session, job: dict, token: UUID, path: str) -> bool:
    db.execute(text("select pg_catalog.set_config('lock_timeout', '5s', true)"))
    db.execute(text('select pg_advisory_xact_lock(hashtextextended(:id, 0))'), dict(id=str(job['receipt_id'])))
    task = db.execute(text("""select id from private_deletion_tasks where id=:id
        and igreja_id=:t and receipt_id=:r and source_id=:source and state='pendente' for update"""),
        dict(id=job['task_id'], t=job['igreja_id'], r=job['receipt_id'], source=job['source_id'])
    ).scalar_one_or_none()
    # The task may have changed during the GET: only the consulted path is cleaned.
    if task is None or db.execute(text('select private_deletion_task_path(:id)'),
                                  dict(id=job['task_id'])).scalar_one() != path:
        return False
    released = db.execute(text("""delete from private_deletion_uploads
        where igreja_id=:t and source_id=:source and attempt_token=:token returning source_id"""),
        dict(t=job['igreja_id'], source=job['source_id'], token=token)).scalar_one_or_none()
    if released is None:
        return False
    db.execute(text("""update private_deletion_tasks set next_attempt_at=least(next_attempt_at, now())
        where id=:id and igreja_id=:t"""), dict(id=job['task_id'], t=job['igreja_id']))
    return True


def reconcile_upload_attempts(session_factory: Callable[[], Session], *, storage: object,
                              now: dt.datetime | None = None,
                              limit: int = WITNESS_BATCH_LIMIT,
                              progress: Callable[[], None] | None = None) -> int:
    """Release ownership of attempts with an exact Storage witness; returns count.

    ``session_factory`` is the dedicated private storage factory. Each job is
    isolated: a failure before the release COMMIT (database, Storage,
    unexpected shape) keeps ownership, and the next read stays scheduled by
    bounded backoff, never expiry.
    ``progress`` runs after each job (one bounded GET plus a bounded lock wait),
    so a slow Storage never looks like a stalled worker.
    """
    current = now or dt.datetime.now(dt.timezone.utc)
    with session_factory() as db:
        jobs = db.execute(text('''select task_id,igreja_id,receipt_id,source_id
            from private_storage_upload_witness_due(:now,:limit)'''),
            dict(now=current, limit=limit)).mappings().all()
    released = 0
    for job in jobs:
        try:
            with session_factory() as db:
                scope_private_storage(db, job['igreja_id'])
                attempt = _claim_read(db, job, current)
                db.commit()
            if attempt is None:
                continue
            token, path = attempt
            if storage.cell_report_audio_attempt_committed(job['igreja_id'], path, token) is not True:
                continue
            with session_factory() as db:
                scope_private_storage(db, job['igreja_id'])
                if _release(db, job, token, path):
                    db.commit()
                    released += 1
                else:
                    db.rollback()
        except Exception as exc:  # No path, token or payload in logs.
            logger.warning("Private upload witness failed: %s", type(exc).__name__,
                           extra={"event": "private_upload_witness_failed"})
        finally:
            if progress is not None:
                progress()
    return released


__all__ = ["WITNESS_BATCH_LIMIT", "reconcile_upload_attempts"]
