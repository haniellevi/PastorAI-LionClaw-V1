"""Cálculo determinista da próxima reunião de célula (Células PR2 / Domínio A).

Dado o `dia_reuniao` textual e o `horario` (HH:MM) de uma célula, resolve a data
da próxima ocorrência no fuso ``America/Sao_Paulo``. Módulo puro, sem I/O: o
"agora" é injetável (parâmetro ``now``) para testes determinísticos — não há
config global nova (RNF-07).

Parser de `dia_reuniao` (allowlist FECHADA):
  - normaliza: minúsculo, sem acento, trim, remove sufixo ``-feira``;
  - casa EXATO contra nomes completos PT-BR (segunda…domingo) OU abreviações de
    3 letras (seg…dom). NÃO há match por substring nem heurística.

Qualquer valor fora da allowlist (ausente/vazio, dígitos, ruído como
``"toda quinta"``/``"quinta a noite"``, abreviações inválidas) levanta
``InvalidDiaReuniao`` — o router traduz isso em 422.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from zoneinfo import ZoneInfo

# Fuso canônico do produto (mesmo usado no sync Google Calendar).
SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")

_FEIRA_SUFFIX = "-feira"

# Índice de dia da semana idêntico a `date.weekday()`: segunda=0 … domingo=6.
_FULL_NAMES: dict[str, int] = {
    "segunda": 0,
    "terca": 1,
    "quarta": 2,
    "quinta": 3,
    "sexta": 4,
    "sabado": 5,
    "domingo": 6,
}
_ABBREVIATIONS: dict[str, int] = {
    "seg": 0,
    "ter": 1,
    "qua": 2,
    "qui": 3,
    "sex": 4,
    "sab": 5,
    "dom": 6,
}
# Allowlist FECHADA = nomes completos ∪ abreviações (14 tokens).
_WEEKDAY_BY_TOKEN: dict[str, int] = {**_FULL_NAMES, **_ABBREVIATIONS}

# HH:MM (24h) — espelha o CHECK de celulas.horario (PR1).
_HORA_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")


class InvalidDiaReuniao(ValueError):
    """`dia_reuniao` ausente/vazio ou fora da allowlist fechada (→ 422)."""


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_dia_reuniao(value: str | None) -> str:
    """Normaliza o rótulo: minúsculo, sem acento, trim, sem sufixo ``-feira``."""
    if value is None:
        return ""
    token = _strip_accents(value).strip().lower()
    if token.endswith(_FEIRA_SUFFIX):
        token = token[: -len(_FEIRA_SUFFIX)]
    return token.strip()


def parse_weekday(value: str | None) -> int:
    """Resolve `dia_reuniao` para o índice do dia da semana (segunda=0…domingo=6).

    Casamento EXATO contra a allowlist fechada — sem substring. Levanta
    ``InvalidDiaReuniao`` para vazio/ausente ou qualquer token não reconhecido.
    """
    token = normalize_dia_reuniao(value)
    if not token:
        raise InvalidDiaReuniao("dia_reuniao ausente ou vazio")
    weekday = _WEEKDAY_BY_TOKEN.get(token)
    if weekday is None:
        raise InvalidDiaReuniao(f"dia_reuniao não reconhecido: {value!r}")
    return weekday


def _parse_hora(hora: str | None) -> tuple[int, int] | None:
    """(hh, mm) de um horário HH:MM válido, ou None se ausente/malformado."""
    if hora is None:
        return None
    match = _HORA_RE.match(hora.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _now_in_sao_paulo(now: dt.datetime | None) -> dt.datetime:
    """Normaliza o relógio injetado para o fuso de São Paulo.

    - ``None``  → relógio real em São Paulo (produção);
    - naive     → interpretado como horário local de São Paulo (testes);
    - aware     → convertido para São Paulo.
    """
    if now is None:
        return dt.datetime.now(SAO_PAULO_TZ)
    if now.tzinfo is None:
        return now.replace(tzinfo=SAO_PAULO_TZ)
    return now.astimezone(SAO_PAULO_TZ)


def next_meeting_date(
    *,
    dia_reuniao: str | None,
    hora: str | None = None,
    now: dt.datetime | None = None,
) -> dt.date:
    """Data (>= hoje) da próxima ocorrência do `dia_reuniao` em São Paulo.

    Se hoje É o dia da reunião mas o `hora` já passou (comparado no mesmo fuso),
    avança para a próxima semana. ``now`` é injetável para determinismo; ``None``
    usa o relógio real. Levanta ``InvalidDiaReuniao`` se o dia não for reconhecido.
    """
    weekday = parse_weekday(dia_reuniao)
    now_local = _now_in_sao_paulo(now)
    today = now_local.date()

    days_ahead = (weekday - today.weekday()) % 7
    if days_ahead == 0:
        parsed = _parse_hora(hora)
        if parsed is not None:
            hour, minute = parsed
            meeting_dt = now_local.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if now_local > meeting_dt:
                days_ahead = 7

    return today + dt.timedelta(days=days_ahead)
