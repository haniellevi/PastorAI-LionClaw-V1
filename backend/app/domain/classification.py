"""Heuristic CSIM detection for a WhatsApp contact (#1).

Pure, deterministic and I/O-free — same style as ``domain.consent`` and
``domain.report``. Flags a contact with **no ministerial link** (an explicit
sales/advertising offer, someone from another city) as **CSIM** so the pastoral
funnel skips them.

The ``contato → visitante`` transition is **not** decided here. A contact only
becomes a *visitante* through a real event — a leader registering the person,
the consolidation team handing them to a leader, or a church **check-in** — not
from a self-declared "I went to church" in chat. So this module only answers
"is this contact outside the ministry's interest?".

This is a bounded keyword heuristic, not semantic understanding: an unlisted
offer is simply not flagged (false negative), which only keeps the person in
the normal funnel. An LLM refinement can be layered on later
without changing the call sites. ``sem_interesse=None`` means "no signal — leave
the person as-is", so a neutral message never clears a previously set CSIM flag.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Commercial CSIM (B5): an explicit offer, not a subject. Each rule pairs offer
# verbs with the commercial objects they must govern; the object has to follow
# the verb within ``_OFFER_WINDOW`` words of the same clause. Whole words only,
# accents folded. Mentioning a job, a company, a bill or marketing as a topic
# ("trabalho numa empresa", "paguei o boleto") is NOT a signal.
_COMMERCIAL_OFFER_RULES: tuple[
    tuple[frozenset[str], tuple[tuple[str, ...], ...]], ...
] = (
    (
        frozenset({"vender", "vendemos"}),
        (
            ("servico",),
            ("servicos",),
            ("produto",),
            ("produtos",),
            ("publicidade",),
            ("marketing",),
        ),
    ),
    (
        frozenset({"oferecer", "oferecemos", "ofereco", "ofertar", "apresentar"}),
        (
            ("publicidade",),
            ("marketing",),
            ("proposta", "comercial"),
            ("parceria", "comercial"),
        ),
    ),
    (
        frozenset({"enviar", "mandar"}),
        (("cobranca",),),
    ),
)
_OFFER_WINDOW = 4
# The offer must be the contact's own: the verb is already first person, or it
# directly follows a first-person auxiliary (optionally via "de": "gostaria de
# oferecer"). "meu filho quer vender", "como vender ...?" are not offers.
_FIRST_PERSON_VERBS = frozenset({"vendemos", "oferecemos", "ofereco"})
_FIRST_PERSON_AUX = frozenset(
    {
        "quero",
        "queremos",
        "gostariamos",
        "posso",
        "podemos",
        "vou",
        "vamos",
        "preciso",
        "precisamos",
    }
)
# "gostaria" is also third person ("meu filho gostaria de"): own intent only
# when it opens the clause or follows "eu".
_AMBIGUOUS_AUX = frozenset({"gostaria"})
# A negation before the verb in the same clause cancels it ("não quero vender").
_NEGATIONS = frozenset({"nao", "nem", "nunca"})
_CLAUSE_SPLIT = re.compile(r"[.,;:!?\n]+")
# Quoted speech is someone else's words, not the contact's own offer. An open
# double quote without its closing mark runs to the end of the message, so
# each unclosed opening is not rescanned to the end (linear).
_QUOTED = re.compile(r'"[^"]*(?:"|\Z)|“[^”]*(?:”|\Z)|\'[^\']*\'')
_WORD = re.compile(r"[a-z0-9]+")
_COMMERCIAL_MOTIVO = "comercial/empresa"

# Location CSIM rule: ordered (keywords, motivo), substring match, unchanged.
CSIM_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        (
            "outra cidade",
            "outro estado",
            "nao sou daqui",
            "não sou daqui",
            "nao sou dessa cidade",
            "não sou dessa cidade",
            "moro longe",
        ),
        "fora da cidade",
    ),
)


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one inbound turn. ``None`` = no change."""

    sem_interesse: bool | None = None
    motivo: str | None = None


def _norm(texto: str | None) -> str:
    return (texto or "").strip().lower()


def _fold(texto: str) -> str:
    decomposed = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _is_own_aux(words: list[str], j: int) -> bool:
    if words[j] in _FIRST_PERSON_AUX:
        return True
    return words[j] in _AMBIGUOUS_AUX and (j == 0 or words[j - 1] == "eu")


def _is_own_intent(words: list[str], i: int) -> bool:
    # Looks at most two words back from the verb.
    if words[i] in _FIRST_PERSON_VERBS:
        return True
    if i >= 1 and _is_own_aux(words, i - 1):
        return True
    return i >= 2 and words[i - 1] == "de" and _is_own_aux(words, i - 2)


def _clause_offers(words: list[str]) -> bool:
    # Only verbs before the clause's first negation count; found once, so the
    # scan stays linear. Objects may still follow anywhere in the clause.
    first_negation = next(
        (j for j, word in enumerate(words) if word in _NEGATIONS), len(words)
    )
    for i in range(first_negation):
        word = words[i]
        for verbs, objects in _COMMERCIAL_OFFER_RULES:
            if word not in verbs or not _is_own_intent(words, i):
                continue
            for obj in objects:
                for start in range(i + 1, i + 1 + _OFFER_WINDOW):
                    if tuple(words[start : start + len(obj)]) == obj:
                        return True
    return False


def _is_commercial_offer(t: str) -> bool:
    unquoted = _QUOTED.sub(" ", _fold(t))
    return any(
        _clause_offers(_WORD.findall(clause))
        for clause in _CLAUSE_SPLIT.split(unquoted)
    )


def classify_contact(texto: str | None) -> Classification:
    """Flag CSIM from the latest message, or return an empty Classification."""
    t = _norm(texto)
    if _is_commercial_offer(t):
        return Classification(sem_interesse=True, motivo=_COMMERCIAL_MOTIVO)
    for keywords, motivo in CSIM_RULES:
        if any(k in t for k in keywords):
            return Classification(sem_interesse=True, motivo=motivo)
    return Classification()
