"""Panel assistant routing rules (api-assistant — O5).

Pure, I/O-free helpers for the **web panel assistant**, a channel distinct from
the WhatsApp Orchestrator (different actor, audience and entry point). The
assistant never talks on WhatsApp; it answers a logged-in panel user and, from
the message intent, suggests panel screens — **only** screens the user's role is
allowed to open (`role_permissions` is the source of truth; the caller passes
the already-resolved allowed set so this module stays free of DB access).

Keeping intent→screen mapping and role filtering here makes the behaviour
deterministic and unit-testable without a database or an LLM.
"""

from __future__ import annotations

from collections.abc import Iterable

# admin holds implicit access to every screen (mirrors deps.require_role).
ADMIN_ROLE = "admin"

# Every known panel screen (mirrors the frontend navigation SCREEN_META). The
# assistant never suggests a screen outside this catalogue.
KNOWN_SCREENS: frozenset[str] = frozenset(
    {
        "dashboard",
        "inbox",
        "calendario",
        "comunicados",
        "equipe",
        "ganhar",
        "consolidar",
        "consol-individual",
        "g12",
        "central-celula",
        "enviar",
        "contatos",
        "celulas",
        "relatorios",
        "whatsapp",
        "agente",
        "assinatura",
        "permissoes",
    }
)

# Screens locked in the MVP — never suggested even when the role could see them.
LOCKED_SCREENS: frozenset[str] = frozenset({"universidade-vida", "capacitacao"})

# Intent keywords mapped to the screen they best resolve. Ordered by screen so
# the suggestion list is stable; matching is accent-insensitive and lowercased.
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "inbox": ("chat", "conversa", "mensagem", "whatsapp do contato", "atendimento"),
    "ganhar": ("visitante", "novo contato", "ganhar", "captar", "primeiro contato"),
    "consolidar": ("consolidar", "consolidacao", "consolidação", "decisao", "decisão"),
    "consol-individual": ("acompanhamento", "1:1", "individual", "fonovisita"),
    "central-celula": ("celula", "célula", "relatorio da celula", "lider de celula"),
    "g12": ("g12", "descendencia", "descendência", "organograma", "discipulado"),
    "enviar": ("multiplicacao", "multiplicação", "enviar", "multiplicar celula"),
    "relatorios": ("relatorio", "relatório", "relatorios", "relatórios", "indicadores"),
    "comunicados": ("comunicado", "broadcast", "aviso", "disparo", "comunicacao"),
    "calendario": ("agenda", "evento", "calendario", "calendário", "culto"),
    "equipe": ("equipe", "lideranca", "liderança", "lider", "líder", "papeis", "papéis"),
    "contatos": ("contato", "cadastro de pessoa", "telefone", "pessoas"),
    "celulas": ("cadastro de celula", "criar celula", "celulas", "células"),
    "dashboard": ("pendencia", "pendência", "hoje", "resumo", "visao geral", "dashboard"),
    "whatsapp": ("conexao", "conexão", "qr code", "numero oficial", "número oficial"),
    "agente": ("agente", "ia", "credencial", "modelo de ia", "openai"),
    "assinatura": ("assinatura", "plano", "cobranca", "cobrança", "pagamento"),
    "permissoes": ("permissao", "permissão", "permissoes", "matriz de acesso"),
}

# Cap suggestions so the assistant answer stays focused.
MAX_SUGGESTIONS = 4


def allowed_screens_for_roles(
    role_to_screens: dict[str, Iterable[str]], roles: Iterable[str]
) -> set[str]:
    """Resolve the union of screens the given roles may open.

    `role_to_screens` is the igreja's role_permissions projection
    (papel -> telas). An `admin` role grants every known, non-locked screen
    (implicit access). The result excludes locked screens.
    """
    role_set = set(roles)
    if ADMIN_ROLE in role_set:
        return set(KNOWN_SCREENS) - LOCKED_SCREENS

    allowed: set[str] = set()
    for role in role_set:
        for tela in role_to_screens.get(role, ()):  # type: ignore[arg-type]
            if tela in KNOWN_SCREENS:
                allowed.add(tela)
    # dashboard is available to any authenticated panel user (delta-010).
    allowed.add("dashboard")
    return allowed - LOCKED_SCREENS


def suggest_screens(texto: str, allowed: Iterable[str]) -> list[str]:
    """Suggest panel screens matching the message intent, filtered by access.

    Returns at most MAX_SUGGESTIONS screens, in a stable order, restricted to
    `allowed` (so the assistant never points to a screen the role cannot open).
    Falls back to `dashboard` when nothing matches but it is allowed.
    """
    allowed_set = set(allowed)
    text = (texto or "").lower()

    suggestions: list[str] = []
    for screen, keywords in _INTENT_KEYWORDS.items():
        if screen not in allowed_set or screen in LOCKED_SCREENS:
            continue
        if any(kw in text for kw in keywords):
            suggestions.append(screen)
        if len(suggestions) >= MAX_SUGGESTIONS:
            break

    if not suggestions and "dashboard" in allowed_set:
        suggestions.append("dashboard")
    return suggestions
