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


# Decisão B4 (12/11/2026): indicação de visitante para reunião que JÁ aconteceu
# é aceita no painel (registro retroativo pelo próprio membro, autenticado) e
# recusada pelo WhatsApp (o agente só oferece a próxima reunião). Uma única
# regra, parametrizada pelo canal, para que painel e agente não divirjam.
CANAL_PAINEL = "painel"
CANAL_WHATSAPP = "whatsapp"
VISITOR_REFERRAL_CHANNELS = frozenset({CANAL_PAINEL, CANAL_WHATSAPP})

PAST_MEETING_WHATSAPP_TEXT = (
    "Pelo WhatsApp só dá para indicar visitante para a próxima reunião da sua "
    "célula. Para uma reunião que já aconteceu, registre a indicação pelo painel."
)


def visitor_referral_meeting_allowed(*, canal: str, meeting_passed: bool) -> bool:
    """True quando o canal pode indicar visitante para esta reunião.

    ``meeting_passed`` vem de ``cell_meetings_schedule.meeting_has_passed``
    (fuso de São Paulo, regra E4). Canal desconhecido falha fechado.
    """
    if canal not in VISITOR_REFERRAL_CHANNELS or type(meeting_passed) is not bool:
        return False
    return canal == CANAL_PAINEL or not meeting_passed
