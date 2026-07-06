"""Unit tests for broadcast segmentation and opt-out filtering (RF-38)."""

from __future__ import annotations

from app.domain.broadcast import (
    RecipientCandidate,
    matches_segments,
    normalize_segments,
    resolve_audience,
)


def _c(
    telefone="11999990000",
    tipo="membro",
    optout=False,
    consent=True,
    lidera_celula=False,
):
    return RecipientCandidate(
        telefone=telefone,
        tipo=tipo,
        optout=optout,
        consentimento=consent,
        lidera_celula=lidera_celula,
    )


def test_normalize_segments_dedupes_and_lowercases() -> None:
    assert normalize_segments([" Membro ", "membro", "TODOS"]) == ["membro", "todos"]


def test_segment_todos_matches_everyone() -> None:
    assert matches_segments(_c(tipo="visitante"), ["todos"]) is True


def test_segment_matches_by_tipo() -> None:
    # tipo legado 'lider' ainda casa (dados pré-migração não somem do alcance)…
    assert matches_segments(_c(tipo="lider"), ["lider"]) is True
    assert matches_segments(_c(tipo="membro"), ["lider"]) is False


def test_segment_lider_derives_from_active_cell_leadership() -> None:
    # …mas o caminho canônico é o vínculo real: lidera célula ativa (2026-07-06).
    assert matches_segments(_c(tipo="membro", lidera_celula=True), ["lider"]) is True
    assert matches_segments(_c(tipo="membro", lidera_celula=False), ["lider"]) is False
    # Pastor que lidera célula casa nos DOIS segmentos (derivação não apaga o tipo).
    pastor = _c(tipo="pastor", lidera_celula=True)
    assert matches_segments(pastor, ["lider"]) is True
    assert matches_segments(pastor, ["pastor"]) is True
    # lidera_celula não vaza para outros segmentos.
    assert matches_segments(_c(tipo="membro", lidera_celula=True), ["pastor"]) is False


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
