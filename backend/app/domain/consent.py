"""Consent term and opt-out rules for the WhatsApp agent (delta-040 / US-31/32).

Pure, I/O-free helpers used by the `consent` sub-agent and the orchestrator:

- The agent may always handle name + telefone (granted implicitly when the
  person initiates contact — trg_consent_on_inbound). Collecting ANY field
  beyond those requires an accepted LGPD term of the *current* version.
- A new term version (delta-040) invalidates a prior acceptance: the person
  must re-accept before further data collection.
- Opt-out (US-32 / RNF-06): a person can ask, by WhatsApp, to stop receiving
  communications; this sets pessoas.optout=true and records the withdrawal,
  excluding them from broadcasts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# Fields the agent can collect WITHOUT an accepted term (LGPD minimisation).
BASELINE_FIELDS: frozenset[str] = frozenset({"nome", "telefone"})

# Affirmative replies accepted as a term acceptance.
_ACCEPT_TOKENS: frozenset[str] = frozenset(
    {
        "aceito",
        "aceitar",
        "concordo",
        "sim",
        "autorizo",
        "ok",
        "de acordo",
        "pode sim",
    }
)

# Opt-out request phrases (US-32). Matched case-insensitively as whole words.
_OPTOUT_PATTERNS: tuple[str, ...] = (
    r"\bsair\b",
    r"\bparar\b",
    r"\bpare\b",
    r"\bcancelar\b",
    r"\bdescadastrar\b",
    r"\bremover\b",
    r"\bopt[\s-]?out\b",
    r"\bn[ãa]o quero (mais )?receber\b",
    r"\bn[ãa]o desejo receber\b",
    r"\bn[ãa]o me envie\b",
)
_OPTOUT_REGEX = re.compile("|".join(_OPTOUT_PATTERNS), re.IGNORECASE)


def requires_term(fields: Iterable[str]) -> bool:
    """True when collecting any of `fields` goes beyond the baseline (term needed)."""
    return any(f not in BASELINE_FIELDS for f in fields)


def needs_reaccept(accepted_version: str | None, current_version: str) -> bool:
    """True when no term is accepted, or the accepted version is outdated.

    Backs delta-040: bumping the term version forces a re-accept before the
    agent may resume collecting data beyond name + telefone.
    """
    if not accepted_version:
        return True
    return accepted_version != current_version


def can_collect_beyond_baseline(
    *, accepted_version: str | None, current_version: str
) -> bool:
    """The agent may collect extra data only with the current term accepted."""
    return not needs_reaccept(accepted_version, current_version)


def is_acceptance(text: str | None) -> bool:
    """Detect an affirmative acceptance of the presented term."""
    if not text:
        return False
    normalized = text.strip().lower()
    if normalized in _ACCEPT_TOKENS:
        return True
    # Allow short phrases that clearly start with an affirmative token, ignoring
    # surrounding punctuation (e.g. "sim, concordo" -> first token "sim").
    tokens = [t.strip(".,!;:()\"'") for t in normalized.split()]
    return bool(tokens) and tokens[0] in _ACCEPT_TOKENS


def is_optout_request(text: str | None) -> bool:
    """Detect an opt-out request in an inbound message (US-32)."""
    if not text:
        return False
    return bool(_OPTOUT_REGEX.search(text))


def term_text(current_version: str, igreja_nome: str | None = None) -> str:
    """Render the consent term message presented before extra data collection."""
    quem = igreja_nome or "nossa igreja"
    return (
        f"Antes de continuar, precisamos do seu consentimento (LGPD). Para "
        f"oferecer um acompanhamento pastoral em {quem}, gostaríamos de coletar "
        f"alguns dados além do seu nome e telefone. Você autoriza? "
        f"Responda 'Aceito' para concordar. (Termo {current_version})"
    )
