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


def classify(text: str, *, pending: bool) -> str:
    value = normalized(text)
    if pending:
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
    if re.search(r"\b(?:oracao|orar|orem|ore)\b", value):
        return "start"
    if pending:
        if value in {"sim", "confirmo"}:
            return "clarify"
        # Audience-only phrases stay in this flow without swallowing another
        # catalog's command (including searches that mention pastors/leaders).
        words = set(value.split())
        if (
            words & {"todos", "pastor", "pastores", "pastoral", "lider", "lideres"}
            and words <= {
                "talvez", "com", "todos", "so", "somente", "apenas", "a", "o",
                "os", "e", "ou", "meu", "minha", "equipe", "pastor", "pastores",
                "pastoral", "lider", "lideres",
            }
        ):
            return "clarify"
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
