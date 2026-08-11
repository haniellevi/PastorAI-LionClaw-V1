"""Autorização das tools do agente pelo PRIVILÉGIO do interlocutor (#10b Fase 2).

O privilégio do interlocutor é resolvido a partir da Pessoa: papéis de um acesso
utilizável (app_users → user_roles), células ativas que ela lidera ou um tipo
ministerial. As 4 tools atuais são ações ministeriais de escrita e
``vincular_celula`` exige, adicionalmente, a capacidade da Central (admin/pastor).
A decisão é determinística e resolvida no servidor; o LLM nunca decide autoridade.
Falha fechada (nega por padrão quando não há o sinal exigido).

Sem I/O — testável. O runtime resolve os dados (papéis/células) do banco.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# Papéis (user_roles do painel) que contam como ministeriais para as tools.
# operador/membro NÃO são ministeriais (não lideram célula nem registram decisão).
MINISTERIAL_ROLES: frozenset[str] = frozenset(
    {"admin", "pastor", "lider_g12", "lider_consol", "lider_celula", "lider_mult"}
)

# Valores de Pessoa.tipo que já são ministeriais por si.
MINISTERIAL_TIPOS: frozenset[str] = frozenset({"lider", "pastor"})

# Tools que exigem privilégio ministerial (todas as atuais). Uma tool fora deste
# conjunto (ex.: futura tool pública de leitura) é liberada por padrão.
MINISTERIAL_TOOLS: frozenset[str] = frozenset(
    {"registrar_decisao", "marcar_presenca", "vincular_celula", "avancar_trilha"}
)

# ``vincular_celula`` espelha uma operação da Central de Células. A capacidade
# equivale a require_central: pastor ou admin implícito. Tipo da Pessoa,
# liderança de célula e outros papéis ministeriais não ampliam essa permissão.
CENTRAL_TOOL_ROLES: frozenset[str] = frozenset({"admin", "pastor"})
CENTRAL_TOOLS: frozenset[str] = frozenset({"vincular_celula"})


@dataclass(frozen=True)
class PrivilegeContext:
    """Privilégio do interlocutor, resolvido do telefone verificado (não do texto)."""

    pessoa_id: str
    tipo: str
    sem_interesse: bool = False
    roles: frozenset[str] = frozenset()
    leads_cells: bool = False

    @property
    def is_ministerial(self) -> bool:
        """True se o interlocutor pode disparar ações ministeriais do agente."""
        if self.sem_interesse:
            return False  # CSIM está fora do funil — nunca ministerial
        if self.roles & MINISTERIAL_ROLES:
            return True
        if self.leads_cells:
            return True
        return self.tipo in MINISTERIAL_TIPOS


def tool_allowed(ctx: PrivilegeContext, tool_name: str) -> bool:
    """True se o interlocutor pode executar esta tool. Determinístico, fail-closed."""
    if tool_name in CENTRAL_TOOLS:
        return not ctx.sem_interesse and has_central_tool_role(ctx.roles)
    if tool_name in MINISTERIAL_TOOLS:
        return ctx.is_ministerial
    return True


def tool_denial_reason(ctx: PrivilegeContext, tool_name: str) -> str:
    """Motivo estável para auditoria do executor, sem depender do LLM."""
    if tool_name in CENTRAL_TOOLS:
        return "interlocutor sem capacidade da Central de Células"
    return "interlocutor sem privilégio ministerial"


def has_central_tool_role(roles: Iterable[str]) -> bool:
    """True somente para a capacidade Central equivalente a admin/pastor."""
    return bool(set(roles) & CENTRAL_TOOL_ROLES)


def has_ministerial_role(roles: Iterable[str]) -> bool:
    """Helper para checar um conjunto de papéis (sem montar um contexto)."""
    return bool(set(roles) & MINISTERIAL_ROLES)
