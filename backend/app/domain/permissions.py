"""Matriz de telas por papel (delta-010 / M0c) — espelho do frontend.

A matriz ``role_permissions`` que o admin edita em #permissoes é a fonte de
verdade do ACESSO ÀS TELAS. Este módulo espelha os defaults do frontend
(``frontend/src/lib/permissions.ts``) para o backend poder autorizar pela MESMA
matriz que o admin edita — não por listas de papéis hard-coded. A dependency
``require_screen`` (app/deps.py) usa estes helpers.

O ``admin`` tem acesso implícito a tudo e nunca aparece na matriz.
"""

from __future__ import annotations

# Tela sempre liberada a qualquer papel (delta-010) — não pode ser removida.
DASHBOARD = "dashboard"

# Default papel -> telas (ESPELHO de DEFAULT_PERMISSIONS em permissions.ts).
# Vale quando o tenant NUNCA customizou a matriz (sem linhas em role_permissions);
# ao salvar #permissoes o tenant passa a ter a própria matriz e estes defaults
# deixam de valer para ele.
DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "pastor": frozenset(
        {
            "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
            "universidade-vida", "capacitacao", "g12", "central-celula", "enviar",
            "calendario", "comunicados", "contatos", "celulas", "relatorios",
        }
    ),
    "lider_g12": frozenset(
        {
            "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
            "universidade-vida", "capacitacao", "g12", "central-celula", "enviar",
            "calendario", "comunicados", "contatos", "celulas", "relatorios",
        }
    ),
    "lider_consol": frozenset(
        {
            "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
            "universidade-vida", "calendario", "comunicados", "contatos",
        }
    ),
    "lider_celula": frozenset(
        {
            "dashboard", "ganhar", "central-celula", "capacitacao", "calendario",
            "celulas", "relatorios",
        }
    ),
    "lider_mult": frozenset(
        {
            "dashboard", "g12", "central-celula", "enviar", "calendario", "celulas",
            "relatorios",
        }
    ),
    "operador": frozenset(
        {"dashboard", "inbox", "contatos", "ganhar", "celulas", "relatorios"}
    ),
    "membro": frozenset({"dashboard", "calendario"}),
}


def screens_for_role(role: str, tenant_matrix: dict[str, set[str]]) -> frozenset[str]:
    """Telas que um papel enxerga: a matriz do tenant se ele a configurou para
    esse papel; senão, o default. ``dashboard`` está sempre incluído.
    """
    if role in tenant_matrix:
        return frozenset(tenant_matrix[role]) | {DASHBOARD}
    return DEFAULT_PERMISSIONS.get(role, frozenset()) | {DASHBOARD}


def can_access_screen(
    roles: frozenset[str], screen: str, tenant_matrix: dict[str, set[str]]
) -> bool:
    """True se ALGUM papel do usuário concede ``screen`` (o admin é tratado fora
    daqui, com acesso implícito). ``dashboard`` é liberado a todos.
    """
    if screen == DASHBOARD:
        return True
    return any(
        screen in screens_for_role(role, tenant_matrix) for role in roles
    )
