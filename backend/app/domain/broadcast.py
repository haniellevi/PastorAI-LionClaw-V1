"""Broadcast segmentation and opt-out filtering (RF-38 / US-32).

Pure, side-effect-free helpers used by the broadcasts router so the
opt-out/consent rules are deterministic and unit-testable without a database.

A person is a valid recipient only when they:
  - match at least one requested segment, AND
  - have NOT opted out (`optout=false`), AND
  - have granted consent (`consentimento=true`).

The "todos" segment matches everyone in the tenant. Other segments match the
person's `tipo` (e.g. "membro", "lider", "visitante"). Unknown segments simply
match nobody, so a typo never silently broadcasts to the whole church.
"""

from __future__ import annotations

from dataclasses import dataclass

# Segment that targets the entire tenant regardless of tipo.
SEGMENT_ALL = "todos"

# Recognized segment tokens beyond "todos"; matched against pessoa.tipo.
KNOWN_TIPO_SEGMENTS: frozenset[str] = frozenset(
    {"visitante", "membro", "lider", "pastor", "discipulo"}
)


@dataclass(frozen=True)
class RecipientCandidate:
    """Minimal projection of a person needed to decide broadcast eligibility."""

    telefone: str | None
    tipo: str | None
    optout: bool
    consentimento: bool


@dataclass(frozen=True)
class BroadcastAudience:
    """Result of resolving an audience against segments and opt-out rules."""

    recipients: list[str]  # phone numbers cleared to receive
    ignored_optout: int  # matched-but-excluded (opt-out / no consent)

    @property
    def reach(self) -> int:
        return len(self.recipients)


def normalize_segments(segmentos: list[str]) -> list[str]:
    """Lowercase, strip and de-duplicate segment tokens, preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for raw in segmentos:
        token = (raw or "").strip().lower()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def matches_segments(candidate: RecipientCandidate, segments: list[str]) -> bool:
    """True if the candidate belongs to any of the requested segments."""
    if SEGMENT_ALL in segments:
        return True
    tipo = (candidate.tipo or "").strip().lower()
    return tipo in {s for s in segments if s in KNOWN_TIPO_SEGMENTS} and bool(tipo)


def resolve_audience(
    candidates: list[RecipientCandidate], segmentos: list[str]
) -> BroadcastAudience:
    """Split matched people into deliverable recipients and opt-out-ignored.

    Honors RF-38: anyone who opted out or has not consented is counted in
    `ignored_optout` and never receives the message, even if they match a
    segment. People without a phone number cannot be delivered to and are not
    counted as opt-out (they are simply skipped).
    """
    segments = normalize_segments(segmentos)
    recipients: list[str] = []
    ignored = 0
    for c in candidates:
        if not matches_segments(c, segments):
            continue
        if c.optout or not c.consentimento:
            ignored += 1
            continue
        if c.telefone and c.telefone.strip():
            recipients.append(c.telefone.strip())
    return BroadcastAudience(recipients=recipients, ignored_optout=ignored)
