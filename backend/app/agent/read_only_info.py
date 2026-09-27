"""Deterministic public-profile replies for the agent runtime.

This module validates the JSONB public profile without opening a database
session, importing domain models, calling a provider, or locating anyone.
Legacy blocks in ``AgentConfig.comportamento`` are stripped from LLM style only;
they are never a source of public facts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.domain.cell_meetings_schedule import (
    InvalidDiaReuniao,
    canonical_weekday_label,
)


_MARKER_CLOSERS = {"[": "]", "{": "}", "(": ")"}
_MAX_VALUE_CHARS = 400
_MAX_CELLS = 5
_MAX_REPLY_CHARS = 1_600
_ADDRESS_WORD = re.compile(
    r"\b(?:rua|avenida|av\.?|travessa|alameda|estrada|rodovia|quadra|lote|cep)\b"
    r"|\br\.(?=\s)|\b\d{5}-?\d{3}\b"
)
# Este filtro aplica apenas o contrato do perfil público para telefone e
# marcador de liderança. Não é um detector geral de dados pessoais.
_PUBLIC_FORBIDDEN_MARKER = re.compile(
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
_HOURS_CULTO_REQUEST = re.compile(
    r"\b(?:"
    r"horarios?\s+(?:do|de)?\s*culto"
    r"|(?:a\s+)?que\s+horas?\s+(?:(?:e|eh|sera|comeca)\s+)?(?:o\s+)?culto"
    r"|quando\s+(?:e|eh|sera|comeca)\s+(?:o\s+)?culto"
    r")\b"
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


@dataclass(frozen=True)
class CanonicalPublicCell:
    """Whitelisted cell fields read from the canonical domain tables."""

    bairro: str
    nome: str
    dia_reuniao: str | None
    horario: str | None


@dataclass(frozen=True)
class CanonicalPublicChurchInfo:
    """Whitelisted church facts supplied by the tenant-scoped read service."""

    endereco_institucional: str | None
    horarios_culto: str | None
    celulas: tuple[CanonicalPublicCell, ...]


@dataclass(frozen=True)
class PublicInfoResolution:
    """A deterministic public reply plus the narrow secretary-offer signal."""

    resposta: str
    oferece_secretaria: bool = False


def _recognize_public_info_marker(value: object) -> _PublicInfoMarker | None:
    """Classify one public-info marker using one normalized grammar.

    A marker can use ``[``, ``{`` or ``(``, and accepts accent, case and
    ``_``/``-``/space spelling variants. Incomplete markers are still returned
    so the style scrubber can discard their remainder fail-closed.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or candidate[0] not in _MARKER_CLOSERS:
        return None

    expected_closer = _MARKER_CLOSERS[candidate[0]]
    complete = candidate.endswith(expected_closer)
    label = candidate[1:-1] if complete else candidate[1:]
    normalized = _normalized(label)
    closing = normalized.startswith("/")
    if closing:
        normalized = normalized[1:].lstrip()

    name = re.match(r"informacoes(?:[_\-\s]+)publicas\b", normalized)
    if name is None:
        return None
    return _PublicInfoMarker(
        closing=closing,
        complete=complete and not normalized[name.end() :].strip(),
    )


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
    cleaned = "".join(
        character
        for character in " ".join(value.split())
        if unicodedata.category(character) != "Cf"
    )
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
        and unicodedata.category(character) != "Cf"
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


def _optional_public_text(value: object) -> tuple[bool, str | None]:
    if value is None:
        return True, None
    text = _display_text(value)
    if text is None or _PUBLIC_FORBIDDEN_MARKER.search(_normalized(text)):
        return False, None
    return True, text


def _project_public_cell(value: object) -> _PublicCell | None:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ) or not set(value).issubset({"bairro", "nome", "encontro"}):
        return None
    if "bairro" not in value or "nome" not in value:
        return None
    bairro = _display_text(value["bairro"])
    nome = _display_text(value["nome"])
    valid_encontro, encontro = _optional_public_text(value.get("encontro"))
    if bairro is None or nome is None or not valid_encontro:
        return None
    normalized_value = _normalized(" ".join(part for part in (bairro, nome, encontro) if part))
    if _ADDRESS_WORD.search(normalized_value) or _PUBLIC_FORBIDDEN_MARKER.search(
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


def project_public_info(value: object) -> _PublicInfo | None:
    """Validate untrusted JSONB and return the only public-info projection.

    ``None`` means malformed or unsafe data. An empty object is valid and
    projects to empty facts, which lets callers distinguish it from a malformed
    object without falling through to legacy free text.
    """

    if not isinstance(value, dict) or any(
        not isinstance(key, str) for key in value
    ) or not set(value).issubset({"endereco_igreja", "horarios_culto", "celulas"}):
        return None
    valid_address, endereco_igreja = _optional_public_text(
        value.get("endereco_igreja")
    )
    valid_hours, horarios_culto = _optional_public_text(value.get("horarios_culto"))
    cells_raw = value.get("celulas", [])
    if not valid_address or not valid_hours or not isinstance(cells_raw, list):
        return None
    if len(cells_raw) > _MAX_CELLS:
        return None
    cells: list[_PublicCell] = []
    bairro_keys: set[str] = set()
    for cell_raw in cells_raw:
        cell = _project_public_cell(cell_raw)
        if cell is None or cell.bairro_key in bairro_keys:
            return None
        bairro_keys.add(cell.bairro_key)
        cells.append(cell)
    return _PublicInfo(
        endereco_igreja=endereco_igreja,
        horarios_culto=horarios_culto,
        celulas=tuple(cells),
    )


def canonical_public_info(value: object) -> dict[str, object] | None:
    """Return canonical snake-case JSONB storage, or ``None`` when invalid."""

    info = project_public_info(value)
    if info is None:
        return None
    return {
        "endereco_igreja": info.endereco_igreja,
        "horarios_culto": info.horarios_culto,
        "celulas": [
            {
                "bairro": cell.bairro,
                "nome": cell.nome,
                "encontro": cell.encontro,
            }
            for cell in info.celulas
        ],
    }


def canonical_public_info_request(value: object) -> tuple[str, str | None] | None:
    """Classify a deterministic public lookup without touching domain data.

    The service uses the returned normalized-neighborhood key to bound its
    cell projection before the five-row limit.  Keeping the parser here means
    the SQL boundary and response resolver share the exact same normalization.
    """
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
    if _HOURS_CULTO_REQUEST.search(text):
        return "horarios_culto", None
    if (
        re.search(r"\bendereco\s+(?:da|de)?\s*igreja\b", text)
        or re.search(r"\bonde\s+fica\s+(?:a\s+)?igreja\b", text)
    ):
        return "endereco_igreja", None
    return None


def canonical_public_bairro_key(value: object) -> str:
    """Return the bounded comparison key used for public cell neighborhoods."""

    return _normalized(value).strip()


def _public_reply(value: str) -> str:
    return value.replace("<", "[").replace(">", "]")[:_MAX_REPLY_CHARS]


_CANONICAL_HOURS = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
_CANONICAL_MISSING = (
    "Não tenho essa informação cadastrada. Quer falar com a secretaria da igreja?"
)
_CELL_SECRETARY_OFFER = (
    "Quer falar com a secretaria da igreja para entrar em contato com o líder da célula?"
)


def _canonical_cell_for_reply(value: CanonicalPublicCell) -> CanonicalPublicCell | None:
    """Validate a domain projection again before it reaches a response."""

    bairro = _display_text(value.bairro)
    nome = _display_text(value.nome)
    dia = _display_text(value.dia_reuniao) if value.dia_reuniao is not None else None
    horario = _display_text(value.horario) if value.horario is not None else None
    if bairro is None or nome is None:
        return None
    normalized = _normalized(" ".join((bairro, nome)))
    if _ADDRESS_WORD.search(normalized) or _PUBLIC_FORBIDDEN_MARKER.search(normalized):
        return None
    if dia is not None:
        try:
            dia = canonical_weekday_label(dia)
        except InvalidDiaReuniao:
            dia = None
    if horario is not None and not _CANONICAL_HOURS.fullmatch(horario):
        return None
    return CanonicalPublicCell(
        bairro=bairro,
        nome=nome,
        dia_reuniao=dia,
        horario=horario,
    )


def _canonical_meeting(cell: CanonicalPublicCell) -> str | None:
    parts = [part for part in (cell.dia_reuniao, cell.horario) if part is not None]
    return ", ".join(parts) if parts else None


def resolve_canonical_public_info(
    current_text: object,
    info: CanonicalPublicChurchInfo | None,
) -> PublicInfoResolution | None:
    """Resolve a supported lookup from canonical Igreja/Celula fields only.

    A missing or unsafe fact remains a deterministic absence. It never falls
    through to the profile JSON, free-text behaviour, an LLM, or a contact
    lookup. The offer flag is metadata for the delivery seam and does not make
    a human handoff by itself.
    """

    request = canonical_public_info_request(current_text)
    if request is None:
        return None
    kind, bairro = request
    if kind == "horarios_culto":
        value = _display_text(info.horarios_culto) if info is not None else None
        return PublicInfoResolution(
            resposta=_public_reply(f"Horário de culto: {value}." if value else _CANONICAL_MISSING),
            oferece_secretaria=not bool(value),
        )
    if kind == "endereco_igreja":
        value = _display_text(info.endereco_institucional) if info is not None else None
        return PublicInfoResolution(
            resposta=_public_reply(f"Endereço da igreja: {value}." if value else _CANONICAL_MISSING),
            oferece_secretaria=not bool(value),
        )
    if info is None or bairro is None:
        return PublicInfoResolution(
            resposta=_public_reply(_CANONICAL_MISSING),
            oferece_secretaria=True,
        )
    bairro_key = canonical_public_bairro_key(bairro)
    cell = next(
        (
            candidate
            for raw in info.celulas
            if (candidate := _canonical_cell_for_reply(raw)) is not None
            and _normalized(candidate.bairro) == bairro_key
        ),
        None,
    )
    if cell is None:
        return PublicInfoResolution(
            resposta=_public_reply(_CANONICAL_MISSING),
            oferece_secretaria=True,
        )
    reply = (
        f"Há uma célula com informações públicas no bairro {cell.bairro}: {cell.nome}."
    )
    meeting = _canonical_meeting(cell)
    if meeting is not None:
        reply = f"{reply} Encontro: {meeting}."
    return PublicInfoResolution(
        resposta=_public_reply(f"{reply} {_CELL_SECRETARY_OFFER}"),
        oferece_secretaria=True,
    )


def resolve_public_info_reply(
    current_text: object,
    public_info: object,
) -> str | None:
    """Return a bounded answer from explicit JSONB public profile data.

    ``None`` means that this message is not a supported deterministic lookup.
    A supported request whose profile is absent or invalid receives an honest
    absence reply and cannot fall through to an inferred data source.
    """

    request = canonical_public_info_request(current_text)
    if request is None:
        return None
    info = project_public_info(public_info)
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
