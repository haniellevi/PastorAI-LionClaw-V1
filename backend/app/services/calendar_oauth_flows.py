"""Fluxos OAuth do Google Calendar em voo (OAUTH-CALENDAR-V1).

Helpers do estado servidor-side que substituiu o ``state`` JWT auto-contido:
geração dos dois segredos (``state`` e ``flowSecret``), seus hashes, o par PKCE
S256 e a purga dos fluxos expirados.

Os dois segredos são DISTINTOS de propósito. O ``state`` viaja para o Google e
cai no access log; o ``flowSecret`` nunca sai das origens do painel. Guardar
``sha256`` de ambos garante que um dump do banco não permita concluir nem
queimar fluxo alheio.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import secrets

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.db.models import CalendarOAuthFlow

# 32 bytes de entropia em cada segredo (256 bits), url-safe para caber em query
# string sem escaping.
_SECRET_BYTES = 32
# RFC 7636 §4.1 exige verifier entre 43 e 128 chars; 64 bytes url-safe dá 86.
_VERIFIER_BYTES = 64


def new_secret() -> str:
    """Segredo opaco de 256 bits, url-safe (``state`` ou ``flowSecret``)."""
    return secrets.token_urlsafe(_SECRET_BYTES)


def hash_secret(secret: str) -> str:
    """sha256 hex do segredo — é isto que vai para o banco, nunca o valor."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def new_pkce_pair() -> tuple[str, str]:
    """``(code_verifier, code_challenge)`` no método S256 (RFC 7636).

    O verifier fica cifrado no servidor, chaveado pelo fluxo; só o challenge
    viaja na URL de consentimento. Derivar o verifier do ``state`` (ou assiná-lo
    dentro dele) anularia a proteção: quem lesse o state calcularia o challenge
    e pré-amarraria o próprio código.
    """
    verifier = secrets.token_urlsafe(_VERIFIER_BYTES)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def purge_expired_flows(session: Session, *, now: dt.datetime) -> int:
    """Apaga fluxos OAuth expirados e devolve o rowcount.

    NÃO faz commit: a transação pertence ao chamador. Idempotente — rodar de
    novo sobre o mesmo estado remove zero linhas. O DELETE leva junto
    ``verifier_encrypted`` e ``code_encrypted``, então não há passe separado de
    anulação de segredos.
    """
    result = session.execute(
        delete(CalendarOAuthFlow).where(CalendarOAuthFlow.expires_at <= now)
    )
    return result.rowcount or 0
