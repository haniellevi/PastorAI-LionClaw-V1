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

# Telas que só a superfície administrativa opera (espelho de ADMIN_ONLY em
# permissions.ts). Um papel não-admin NUNCA acessa, mesmo que uma linha
# antiga em role_permissions (customização de tenant salva antes desta regra)
# ainda conceda a tela — checado antes da matriz, não depois.
ADMIN_ONLY = frozenset({"comunicados", "contatos"})

# Telas CENTRAL-ONLY: só `pastor` (e o `admin`, implícito) — NUNCA outro papel,
# mesmo que uma linha em role_permissions conceda. Igual ao ADMIN_ONLY, a regra
# é checada ANTES da matriz, não depois: um tenant que já salvou
# `operador -> relatorios` não reabre a tela. As linhas salvas NÃO são apagadas;
# a concessão incompatível é apenas ignorada para estas telas.
#
# `relatorios` lista relatórios de TODAS as células com oferta e observações; o
# gate real do dado é `require_central` em GET /reports (REPORT-SOT-1) e esta
# regra impede que a navegação ofereça uma tela que responderia 403.
# 'pastor' espelha CENTRAL_ROLES de app/deps.py (importar de lá seria circular).
CENTRAL_ROLE = "pastor"
CENTRAL_ONLY = frozenset({"relatorios"})

# Default papel -> telas (ESPELHO de DEFAULT_PERMISSIONS em permissions.ts).
# Vale quando o tenant NUNCA customizou a matriz (sem linhas em role_permissions);
# ao salvar #permissoes o tenant passa a ter a própria matriz e estes defaults
# deixam de valer para ele.
DEFAULT_PERMISSIONS: dict[str, frozenset[str]] = {
    "pastor": frozenset(
        {
            "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
            "universidade-vida", "capacitacao", "g12", "central-celula", "enviar",
            "calendario", "celulas", "relatorios",
        }
    ),
    # Central de Célula = pastor/admin no MVP (decisão 3.1). Os papéis de líder
    # NÃO veem 'central-celula'; gerem sua célula por 'minha-celula'.
    # 'relatorios' também é pastor/admin: a listagem é tenant-wide e expõe oferta
    # e observações de TODAS as células (GET /reports usa require_central). O
    # líder lê o relatório da própria célula por 'minha-celula'.
    "lider_g12": frozenset(
        {
            "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
            "universidade-vida", "capacitacao", "g12", "minha-celula", "enviar",
            "calendario", "celulas",
        }
    ),
    "lider_consol": frozenset(
        {
            "dashboard", "inbox", "ganhar", "consolidar", "consol-individual",
            "universidade-vida", "calendario",
        }
    ),
    "lider_celula": frozenset(
        {
            "dashboard", "inbox", "ganhar", "minha-celula", "capacitacao",
            "calendario", "celulas",
        }
    ),
    "lider_mult": frozenset(
        {
            "dashboard", "g12", "minha-celula", "enviar", "calendario", "celulas",
        }
    ),
    "operador": frozenset(
        {"dashboard", "inbox", "ganhar", "celulas"}
    ),
    "membro": frozenset({"dashboard", "minha-celula", "calendario"}),
}


def screens_for_role(role: str, tenant_matrix: dict[str, set[str]]) -> frozenset[str]:
    """Telas que um papel enxerga: a matriz do tenant se ele a configurou para
    esse papel; senão, o default. ``dashboard`` está sempre incluído.

    ``CENTRAL_ONLY`` é subtraído de qualquer papel que não seja ``pastor`` —
    inclusive quando a concessão vem da matriz PERSISTIDA do tenant (fail-closed,
    igual ao tratamento de ``ADMIN_ONLY`` em ``can_access_screen``). O ``admin``
    não passa por aqui: tem acesso implícito resolvido antes.
    """
    if role in tenant_matrix:
        screens = frozenset(tenant_matrix[role]) | {DASHBOARD}
    else:
        screens = DEFAULT_PERMISSIONS.get(role, frozenset()) | {DASHBOARD}
    if role != CENTRAL_ROLE:
        screens -= CENTRAL_ONLY
    return screens


def can_access_screen(
    roles: frozenset[str], screen: str, tenant_matrix: dict[str, set[str]]
) -> bool:
    """True se ALGUM papel do usuário concede ``screen`` (o admin é tratado fora
    daqui, com acesso implícito). ``dashboard`` é liberado a todos.
    """
    if screen == DASHBOARD:
        return True
    if screen in ADMIN_ONLY:
        return False
    return any(
        screen in screens_for_role(role, tenant_matrix) for role in roles
    )
