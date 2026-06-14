"""SLA policy + breach classification (SLA engine — O5).

Pure, I/O-free rules the SLA engine uses to decide, for a tracked item, whether
its deadline is approaching/blown and which action to take:

  - `ok`            — still within the deadline, nothing to do.
  - `cobranca`      — the deadline elapsed: charge the responsible leader.
  - `escalonamento` — the leader did not respond within the escalation grace:
                      escalate to coordination (US — líder sem resposta).

Deadlines (SPEC): cell report 2h, connection 12h, fonovisita 24h. Each policy
also carries an escalation grace counted *after* the deadline. The service layer
(`services/sla_engine.py`) reads prazos from work_queue/consolidacao and applies
these rules; keeping the math here makes it deterministic and unit-testable.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum

# Canonical SLA kinds detected by the engine.
SLA_REPORT = "relatorio"
SLA_CONNECTION = "conexao"
SLA_FONOVISITA = "fonovisita"


class SlaStatus(str, Enum):
    """Outcome of classifying one tracked item against its SLA policy."""

    OK = "ok"
    COBRANCA = "cobranca"
    ESCALONAMENTO = "escalonamento"


@dataclass(frozen=True)
class SlaPolicy:
    """An SLA threshold plus the grace before escalating an unanswered charge."""

    kind: str
    deadline_hours: float
    escalate_after_hours: float

    def deadline_from(self, started_at: dt.datetime) -> dt.datetime:
        """Absolute charge deadline computed from a start instant."""
        return started_at + dt.timedelta(hours=self.deadline_hours)

    def escalation_deadline_from(self, started_at: dt.datetime) -> dt.datetime:
        """Absolute escalation instant (deadline + escalation grace)."""
        return started_at + dt.timedelta(
            hours=self.deadline_hours + self.escalate_after_hours
        )


# SPEC deadlines. Escalation grace is deliberately conservative so a leader has
# time to act before coordination is pulled in.
SLA_POLICIES: dict[str, SlaPolicy] = {
    SLA_REPORT: SlaPolicy(SLA_REPORT, deadline_hours=2, escalate_after_hours=2),
    SLA_CONNECTION: SlaPolicy(SLA_CONNECTION, deadline_hours=12, escalate_after_hours=12),
    SLA_FONOVISITA: SlaPolicy(SLA_FONOVISITA, deadline_hours=24, escalate_after_hours=24),
}

# Map a work_queue_items.tipo to its SLA kind (only timed types are tracked).
WORK_QUEUE_TIPO_TO_SLA: dict[str, str] = {
    "relatorio": SLA_REPORT,
    "conectar_celula": SLA_CONNECTION,
    "fonovisita": SLA_FONOVISITA,
}


def _as_aware(value: dt.datetime) -> dt.datetime:
    """Normalize a possibly-naive datetime to UTC-aware for safe comparison."""
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


def classify(
    *,
    policy: SlaPolicy,
    deadline: dt.datetime,
    now: dt.datetime,
) -> SlaStatus:
    """Classify an item given its absolute charge `deadline`.

    The escalation instant is the deadline plus the policy's escalation grace.
    """
    deadline = _as_aware(deadline)
    now = _as_aware(now)
    escalate_at = deadline + dt.timedelta(hours=policy.escalate_after_hours)

    if now >= escalate_at:
        return SlaStatus.ESCALONAMENTO
    if now >= deadline:
        return SlaStatus.COBRANCA
    return SlaStatus.OK


def classify_from_start(
    *,
    policy: SlaPolicy,
    started_at: dt.datetime,
    now: dt.datetime,
) -> SlaStatus:
    """Classify when only the start instant is known (deadline derived)."""
    return classify(policy=policy, deadline=policy.deadline_from(started_at), now=now)


def resolve_deadline(
    *,
    policy: SlaPolicy,
    prazo: dt.datetime | None,
    created_at: dt.datetime | None,
    now: dt.datetime,
) -> dt.datetime:
    """Pick the effective charge deadline for an item.

    Prefers an explicit `prazo` (set by triggers/routers); otherwise derives it
    from `created_at`. Falls back to `now` so a row missing both timestamps is
    treated as immediately due rather than silently ignored.
    """
    if prazo is not None:
        return _as_aware(prazo)
    if created_at is not None:
        return policy.deadline_from(_as_aware(created_at))
    return _as_aware(now)
