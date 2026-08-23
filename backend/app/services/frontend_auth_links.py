"""Links públicos de ativação e recuperação servidos pelo frontend.

Tokens em fragmentos (``#...``) não chegam ao servidor intermediário e podem
ser descartados por redirecionadores de e-mail. Os links enviados usam um
caminho real no domínio da aplicação; o frontend converte esse caminho para o
fragmento legado somente depois que o navegador já chegou ao domínio próprio.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

FrontendAuthFlow = Literal["ativar", "redefinir-senha"]


def build_frontend_auth_link(
    frontend_url: str,
    flow: FrontendAuthFlow,
    token: str,
) -> str:
    """Return a tracker-safe, same-origin entry URL for a sensitive token."""

    base = frontend_url.rstrip("/")
    encoded_token = quote(token, safe="")
    return f"{base}/{flow}/{encoded_token}"
