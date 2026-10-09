"""Private nominal input for a visitor expectation, without infrastructure."""

import unicodedata


class VisitorNameError(ValueError):
    """Invalid nominal input; diagnostics never include the private value."""


def canonical_visitor_name(value: object) -> str:
    """Preserve strict type, Unicode controls, trimming and length contract."""
    if type(value) is not str or any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in value
    ):
        raise VisitorNameError("nome de visitante inválido")
    name = value.strip()
    if not 1 <= len(name) <= 200:
        raise VisitorNameError("nome de visitante inválido")
    return name
