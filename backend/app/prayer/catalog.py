"""Closed contact catalog, separate from S3's privileged AppUser capability.

No provider, Jev or model can select an identity, role, church or recipient ID.
The router reads only the persisted inbound. The sole writer is the domain service.
"""

import re
import unicodedata

ACTION = "registrar_pedido_oracao"
AUTHORIZATION_VERSION = "prayer-own-text-v1-20261016"
DISCLOSURE = "A equipe que atende o WhatsApp da igreja pode ver esta conversa."
AUDIENCE_QUESTION = (
    "Com quem autoriza compartilhar? Responda SÓ PASTORES ou "
    "PASTORES E MEU LÍDER. Sem uma escolha clara, o pedido não será registrado na lista de oração."
)
OWN_QUESTION = (
    "Nesta versão, envie seu pedido próprio por texto: Peço oração por mim: ..."
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
    return "clarify" if pending else "none"


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
