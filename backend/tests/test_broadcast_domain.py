"""Unit tests for broadcast segmentation and opt-out filtering (RF-38)."""

from __future__ import annotations

from app.domain.broadcast import (
    RecipientCandidate,
    matches_segments,
    normalize_segments,
    resolve_audience,
)


def _c(telefone="11999990000", tipo="membro", optout=False, consent=True):
    return RecipientCandidate(
        telefone=telefone, tipo=tipo, optout=optout, consentimento=consent
    )


def test_normalize_segments_dedupes_and_lowercases() -> None:
    assert normalize_segments([" Membro ", "membro", "TODOS"]) == ["membro", "todos"]


def test_segment_todos_matches_everyone() -> None:
    assert matches_segments(_c(tipo="visitante"), ["todos"]) is True


def test_segment_matches_by_tipo() -> None:
    assert matches_segments(_c(tipo="lider"), ["lider"]) is True
    assert matches_segments(_c(tipo="membro"), ["lider"]) is False


def test_unknown_segment_matches_nobody() -> None:
    assert matches_segments(_c(tipo="membro"), ["anjos"]) is False


def test_resolve_audience_excludes_optout_and_no_consent() -> None:
    candidates = [
        _c(telefone="111", optout=False, consent=True),
        _c(telefone="222", optout=True, consent=True),  # opted out
        _c(telefone="333", optout=False, consent=False),  # no consent
    ]
    audience = resolve_audience(candidates, ["todos"])
    assert audience.recipients == ["111"]
    assert audience.reach == 1
    assert audience.ignored_optout == 2


def test_resolve_audience_all_optout_blocks() -> None:
    candidates = [
        _c(telefone="111", optout=True),
        _c(telefone="222", consent=False),
    ]
    audience = resolve_audience(candidates, ["todos"])
    assert audience.reach == 0
    assert audience.ignored_optout == 2


def test_recipient_without_phone_is_skipped_not_counted() -> None:
    candidates = [_c(telefone=None, optout=False, consent=True)]
    audience = resolve_audience(candidates, ["todos"])
    assert audience.reach == 0
    assert audience.ignored_optout == 0
