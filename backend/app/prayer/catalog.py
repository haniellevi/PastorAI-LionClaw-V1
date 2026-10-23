"""Closed contact catalog, separate from S3's privileged AppUser capability.

No provider, Jev or model can select an identity, role, church or recipient ID.
The router reads only the persisted inbound. The sole writer is the domain service.
"""

import re
import unicodedata

# Provisional pastoral decisions are centralized in policy.py.
from app.prayer.policy import DISCLOSURE

ACTION = "registrar_pedido_oracao"
AUTHORIZATION_VERSION = "prayer-own-text-v2-20261018"
START_COMMAND = "quero iniciar pedido de oracao"
AUDIENCE_QUESTION = (
    "Com quem autoriza compartilhar? Responda SÓ PASTORES ou "
    "PASTORES E MEU LÍDER. Sem uma escolha clara, o pedido não será registrado na lista de oração."
)
COLLECT_QUESTION = (
    "A coleta protegida começou. Envie seu pedido próprio por áudio ou por texto: "
    "Peço oração por mim: ..."
)
OWN_QUESTION = (
    "Para começar a coleta protegida, envie QUERO INICIAR PEDIDO DE ORAÇÃO. "
    "Depois envie seu pedido próprio por áudio ou por texto: Peço oração por mim: ..."
)


def normalized(text: str) -> str:
    return (
        "".join(
            c
            for c in unicodedata.normalize("NFKD", text.casefold())
            if not unicodedata.combining(c)
        )
        .strip()
        .rstrip(".!")
    )


def _is_other_catalog_command(text: str) -> bool:
    """Let valid closed commands reach their own deterministic router."""
    from app.agenda_whatsapp.catalog import route as agenda_route
    from app.cell_suggest.catalog import route as cell_route
    from app.cd_whatsapp.catalog import route as cd_route
    from app.conhecimento_whatsapp.catalog import route as knowledge_route
    from app.enviar_whatsapp.catalog import route as enviar_route
    from app.private_erasure.catalog import route as erasure_route
    from app.services.private_resume import RESUME_COMMAND
    from app.uv_whatsapp.catalog import route as uv_route

    return (
        cd_route(text)[0] in {"list", "read", "attendance"}
        or uv_route(text)[0] in {"list", "read", "attendance"}
        or enviar_route(text)[0] in {"list", "history", "read", "nominate", "open"}
        or knowledge_route(text)[0] == "search"
        or agenda_route(text)[0] in {"list", "create", "update", "delete"}
        or cell_route(text)[0] in {"ask", "lookup"}
        or erasure_route(text)
        or text.strip().casefold() == RESUME_COMMAND
    )


def classify(text: str, *, pending: bool) -> str:
    value = normalized(text)
    if pending:
        if _is_other_catalog_command(text):
            return "none"
        if value == START_COMMAND:
            return "start"
        if value in {"so pastores", "somente pastores", "pastores", "equipe pastoral"}:
            return "pastoral"
        if value in {
            "pastores e meu lider",
            "pastores e lider",
            "equipe pastoral e meu lider",
        }:
            return "pastoral_lider"
        if text.strip().casefold() == "sim":
            return "confirm"
        if value in {"nao", "cancelar", "cancela"}:
            return "cancel"
        # Keep every non-command turn inside the privacy flow. "none" lets the
        # worker continue to the general agent, where private prayer text can
        # reach an external LLM.
        return "clarify"
    if re.search(r"\b(?:oracao|orar|orem|ore)\b", value):
        return "start"
    return "none"


def own_summary(text: str) -> str | None:
    # Deliberately retain the person's words instead of inventing a pastoral summary.
    text = unicodedata.normalize("NFC", text).strip()
    match = re.match(
        r"^(?:peco|quero pedir|pedido de) oracao por mim\s*:", normalized(text)
    )
    if match is None:
        return None
    body = " ".join(text[match.end() :].split())
    return body if 1 <= len(body) <= 1000 else None


def presentation(summary: str, audience: str, leader_name: str | None) -> str:
    recipients = "equipe pastoral"
    if audience == "pastoral_lider":
        if not leader_name:
            raise ValueError("líder não resolvido pelo servidor")
        recipients += f" e seu líder de célula {' '.join(leader_name.split())[:120]}"
    elif audience != "pastoral":
        raise ValueError("destinatários inválidos")
    return (
        f"Seu pedido: {summary}\nDestinatários: {recipients}.\n{DISCLOSURE}\n"
        "Autoriza registrar e compartilhar este pedido com esses destinatários? "
        "Responda SIM ou NÃO. A confirmação vale por 10 minutos."
    )


def execute(session, contact, proposal, confirmation):
    from app.prayer.service import register

    return register(
        session, contact=contact, proposal=proposal, confirmation=confirmation
    )
