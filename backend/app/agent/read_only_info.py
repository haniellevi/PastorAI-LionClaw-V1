"""Deterministic public-profile replies for the agent runtime.

This module deliberately parses only an explicit block in ``AgentConfig``.  It
does not open a database session, import domain models, call a provider, or
perform location lookups.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_MARKER_CLOSERS = {"[": "]", "{": "}", "(": ")"}
_MAX_PROFILE_CHARS = 4_000
_MAX_VALUE_CHARS = 400
_MAX_CELLS = 5
_MAX_REPLY_CHARS = 1_600
_ADDRESS_WORD = re.compile(
    r"\b(?:rua|avenida|av\.?|travessa|alameda|estrada|rodovia|quadra|lote|cep)\b"
    r"|\br\.(?=\s)|\b\d{5}-?\d{3}\b"
)
# Este filtro aplica apenas o contrato de célula pública para telefone e
# marcador de liderança. Não é um detector geral de dados pessoais.
_CELL_FORBIDDEN_MARKER = re.compile(
    r"\b(?:lider(?:a|es|as)?|anfitri(?:a|ao))\b"
    r"|(?<!\d)(?:\+?55[\s-]*)?(?:\(?\d{2}\)?[\s-]*)?"
    r"9?\d{4,5}[\s-]?\d{4}(?!\d)"
)
_WEEKDAY_MEETING = re.compile(
    r"^(?:segunda|terca|quarta|quinta|sexta|sabado|domingo)(?:-feira)?"
    r"(?:\s*(?:,|as)?\s*(?:[01]?\d|2[0-3])(?::[0-5]\d)?h?)?$"
)
_CELL_BAIRRO = re.compile(
    r"\b(?:no|na|em|do|da)\s+(?:bairro\s+)?"
    r"(?P<bairro>[a-z0-9][a-z0-9 .'-]*?)\s*[?!.;,;:]*$"
)
_CELL_LOOKUP_INTENT = re.compile(
    r"\b(?:qual|que|onde|perto|proxim\w*|indique|indica|encontre|"
    r"encontrar|mostre|mostrar)\b"
)
_CELL_BARE_BAIRRO_REQUEST = re.compile(
    r"^celula(?:s)?\s+(?:no|na|em|do|da)\s+(?:bairro\s+)?"
)
_CELL_QUESTION_BAIRRO_REQUEST = re.compile(
    r"^(?:tem|existe|existem|ha)\s+(?:uma\s+)?celula(?:s)?\s+"
    r"(?:no|na|em|do|da)\s+(?:bairro\s+)?[a-z0-9].*\?\s*$"
)

_HOURS_MISSING = (
    "Não encontrei o horário de culto nas informações públicas configuradas "
    "pela igreja."
)
_ADDRESS_MISSING = (
    "Não encontrei o endereço da igreja nas informações públicas configuradas "
    "pela igreja."
)
_CELL_MISSING = (
    "Não encontrei uma célula com informações públicas nesse bairro. "
    "Não calculo distância."
)
_CELL_NEEDS_BAIRRO = (
    "Para indicar uma célula com informações públicas, pergunte: célula no "
    "bairro Centro. Não calculo distância."
)


@dataclass(frozen=True)
class _PublicCell:
    bairro: str
    bairro_key: str
    nome: str
    encontro: str | None


@dataclass(frozen=True)
class _PublicInfo:
    endereco_igreja: str | None
    horarios_culto: str | None
    celulas: tuple[_PublicCell, ...]


@dataclass(frozen=True)
class _PublicInfoMarker:
    closing: bool
    complete: bool


def _recognize_public_info_marker(value: object) -> _PublicInfoMarker | None:
    """Classify one public-info marker using one normalized grammar.

    A marker can use ``[``, ``{`` or ``(``, and accepts accent, case and
    ``_``/``-``/space spelling variants. Incomplete markers are still returned
    so the style scrubber can discard their remainder fail-closed; the public
    parser accepts only complete markers.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or candidate[0] not in _MARKER_CLOSERS:
        return None

    expected_closer = _MARKER_CLOSERS[candidate[0]]
    complete = candidate.endswith(expected_closer)
    label = candidate[1:-1] if complete else candidate[1:]
    label = label.strip()
    closing = label.startswith("/")
    if closing:
        label = label[1:].lstrip()

    normalized = unicodedata.normalize("NFKD", label.casefold())
    normalized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    )
    words = [word for word in re.split(r"[_\-\s]+", normalized) if word]
    if words[:2] != ["informacoes", "publicas"]:
        return None
    return _PublicInfoMarker(closing=closing, complete=complete and len(words) == 2)


def _public_info_marker_spans(value: str):
    """Yield marker candidates found in style text through the shared grammar."""

    index = 0
    while index < len(value):
        opening_index = next(
            (
                position
                for position in range(index, len(value))
                if value[position] in _MARKER_CLOSERS
            ),
            None,
        )
        if opening_index is None:
            return
        expected_closer = _MARKER_CLOSERS[value[opening_index]]
        closing_index = value.find(expected_closer, opening_index + 1)
        line_end = value.find("\n", opening_index + 1)
        if closing_index < 0 or (line_end >= 0 and line_end < closing_index):
            end = line_end if line_end >= 0 else len(value)
        else:
            end = closing_index + 1
        marker = _recognize_public_info_marker(value[opening_index:end])
        if marker is None:
            index = opening_index + 1
            continue
        yield opening_index, end, marker
        index = max(end, opening_index + 1)


def _display_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned or len(cleaned) > _MAX_VALUE_CHARS:
        return None
    if any(ord(character) < 32 for character in cleaned):
        return None
    return cleaned


def _normalized(value: object) -> str:
    if not isinstance(value, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(
        character
        for character in decomposed
        if not unicodedata.combining(character)
    )
    return " ".join(without_accents.split())


def style_profile_without_public_info(comportamento: object) -> str:
    """Keep only style text that is outside every public-info marker span.

    A malformed or orphan marker starts a fail-closed span through the end of
    the profile, so rejected public data never becomes the LLM fallback.
    """

    if not isinstance(comportamento, str):
        return ""
    parts: list[str] = []
    cursor = 0
    depth = 0
    for start, end, marker in _public_info_marker_spans(comportamento):
        if depth == 0:
            parts.append(comportamento[cursor:start])
        if marker.closing and marker.complete:
            if depth == 0:
                depth = 1
            else:
                depth -= 1
                if depth == 0:
                    cursor = end
        else:
            depth += 1
    if depth == 0:
        parts.append(comportamento[cursor:])
    return "".join(parts).strip()


def _parse_cell(value: str) -> _PublicCell | None:
    if value.count("|") != 2:
        return None
    bairro_raw, nome_raw, encontro_raw = value.split("|")
    bairro = _display_text(bairro_raw)
    nome = _display_text(nome_raw)
    encontro = _display_text(encontro_raw) if encontro_raw.strip() else None
    if bairro is None or nome is None:
        return None
    normalized_value = _normalized(value)
    if _ADDRESS_WORD.search(normalized_value) or _CELL_FORBIDDEN_MARKER.search(
        normalized_value
    ):
        return None
    bairro_key = _normalized(bairro)
    if not bairro_key:
        return None
    if encontro is not None and not _WEEKDAY_MEETING.fullmatch(_normalized(encontro)):
        return None
    return _PublicCell(
        bairro=bairro,
        bairro_key=bairro_key,
        nome=nome,
        encontro=encontro,
    )


def _parse_public_info(comportamento: object) -> _PublicInfo | None:
    if not isinstance(comportamento, str) or len(comportamento) > _MAX_PROFILE_CHARS:
        return None
    lines = comportamento.splitlines()
    markers = [
        _recognize_public_info_marker(line)
        for line in lines
    ]
    openings = [
        index
        for index, marker in enumerate(markers)
        if marker is not None and marker.complete and not marker.closing
    ]
    closings = [
        index
        for index, marker in enumerate(markers)
        if marker is not None and marker.complete and marker.closing
    ]
    if len(openings) != 1 or len(closings) != 1 or openings[0] >= closings[0]:
        return None

    fields: dict[str, str] = {}
    cells: list[_PublicCell] = []
    bairro_keys: set[str] = set()
    for line in lines[openings[0] + 1 : closings[0]]:
        if not line.strip():
            continue
        key, separator, raw_value = line.partition("=")
        if not separator:
            return None
        key = key.strip().casefold()
        value = _display_text(raw_value)
        if value is None:
            return None
        if key in {"endereco_igreja", "horarios_culto"}:
            if key in fields:
                return None
            fields[key] = value
            continue
        if key != "celula":
            return None
        cell = _parse_cell(value)
        if cell is None or cell.bairro_key in bairro_keys or len(cells) >= _MAX_CELLS:
            return None
        bairro_keys.add(cell.bairro_key)
        cells.append(cell)

    return _PublicInfo(
        endereco_igreja=fields.get("endereco_igreja"),
        horarios_culto=fields.get("horarios_culto"),
        celulas=tuple(cells),
    )


def _request(value: object) -> tuple[str, str | None] | None:
    text = _normalized(value)
    if not text:
        return None
    if re.search(r"\bcelula(?:s)?\b", text) and (
        _CELL_LOOKUP_INTENT.search(text)
        or _CELL_BARE_BAIRRO_REQUEST.search(text)
        or _CELL_QUESTION_BAIRRO_REQUEST.search(text)
    ):
        bairro = _CELL_BAIRRO.search(text)
        return "celula", bairro.group("bairro").strip() if bairro else None
    if (
        re.search(r"\bhorarios?\s+(?:do|de)?\s*culto\b", text)
        or re.search(r"\bque\s+horas?\s+(?:e|eh|sera)?\s*(?:o\s+)?culto\b", text)
        or re.search(r"\ba\s+que\s+horas?\s+comeca\s+(?:o\s+)?culto\b", text)
    ):
        return "horarios_culto", None
    if (
        re.search(r"\bendereco\s+(?:da|de)?\s*igreja\b", text)
        or re.search(r"\bonde\s+fica\s+(?:a\s+)?igreja\b", text)
    ):
        return "endereco_igreja", None
    return None


def _public_reply(value: str) -> str:
    return value.replace("<", "[").replace(">", "]")[:_MAX_REPLY_CHARS]


def resolve_public_info_reply(
    current_text: object,
    comportamento: object,
) -> str | None:
    """Return a bounded answer from explicit public profile data, if requested.

    ``None`` means that this message is not a supported deterministic lookup.
    A supported request whose block is absent or invalid receives an honest
    absence reply and cannot fall through to an inferred data source.
    """

    request = _request(current_text)
    if request is None:
        return None
    info = _parse_public_info(comportamento)
    kind, bairro = request
    if kind == "horarios_culto":
        answer = (
            f"Horário de culto: {info.horarios_culto}."
            if info is not None and info.horarios_culto is not None
            else _HOURS_MISSING
        )
        return _public_reply(answer)
    if kind == "endereco_igreja":
        answer = (
            f"Endereço da igreja: {info.endereco_igreja}."
            if info is not None and info.endereco_igreja is not None
            else _ADDRESS_MISSING
        )
        return _public_reply(answer)

    if info is None or not info.celulas:
        return _public_reply(_CELL_MISSING)
    if bairro is None:
        return _public_reply(_CELL_NEEDS_BAIRRO)
    bairro_key = _normalized(bairro)
    match = next((cell for cell in info.celulas if cell.bairro_key == bairro_key), None)
    if match is None:
        return _public_reply(_CELL_MISSING)
    answer = (
        f"Há uma célula com informações públicas no bairro {match.bairro}: "
        f"{match.nome}."
    )
    if match.encontro is not None:
        answer = f"{answer} Encontro: {match.encontro}."
    return _public_reply(answer)
