"""Deterministic public-profile replies for the agent runtime.

This module deliberately parses only an explicit block in ``AgentConfig``.  It
does not open a database session, import domain models, call a provider, or
perform location lookups.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


_PUBLIC_BLOCK_OPEN = "[informacoes_publicas]"
_PUBLIC_BLOCK_CLOSE = "[/informacoes_publicas]"
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
    openings = [
        index
        for index, line in enumerate(lines)
        if line.strip().casefold() == _PUBLIC_BLOCK_OPEN
    ]
    closings = [
        index
        for index, line in enumerate(lines)
        if line.strip().casefold() == _PUBLIC_BLOCK_CLOSE
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
        _CELL_LOOKUP_INTENT.search(text) or _CELL_BARE_BAIRRO_REQUEST.search(text)
    ):
        bairro = _CELL_BAIRRO.search(text)
        return "celula", bairro.group("bairro").strip() if bairro else None
    if (
        re.search(r"\bhorarios?\s+(?:do|de)?\s*culto\b", text)
        or re.search(r"\bque\s+horas?\s+(?:e|eh|sera)?\s*(?:o\s+)?culto\b", text)
    ):
        return "horarios_culto", None
    if (
        re.search(r"\bendereco\s+(?:da|de)?\s*igreja\b", text)
        or re.search(r"\bonde\s+fica\s+(?:a\s+)?igreja\b", text)
    ):
        return "endereco_igreja", None
    return None


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
        return answer[:_MAX_REPLY_CHARS]
    if kind == "endereco_igreja":
        answer = (
            f"Endereço da igreja: {info.endereco_igreja}."
            if info is not None and info.endereco_igreja is not None
            else _ADDRESS_MISSING
        )
        return answer[:_MAX_REPLY_CHARS]

    if info is None or not info.celulas:
        return _CELL_MISSING
    if bairro is None:
        return _CELL_NEEDS_BAIRRO
    bairro_key = _normalized(bairro)
    match = next((cell for cell in info.celulas if cell.bairro_key == bairro_key), None)
    if match is None:
        return _CELL_MISSING
    answer = (
        f"Há uma célula com informações públicas no bairro {match.bairro}: "
        f"{match.nome}."
    )
    if match.encontro is not None:
        answer = f"{answer} Encontro: {match.encontro}."
    return answer[:_MAX_REPLY_CHARS]
