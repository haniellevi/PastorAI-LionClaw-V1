"""Autorização das tools do agente pelo PRIVILÉGIO do interlocutor (#10b Fase 2).

O privilégio do interlocutor é resolvido a partir da Pessoa e dos papéis de um
único acesso utilizável (app_users -> user_roles). Tipo ministerial e liderança
de célula são contexto, não autenticação. As 4 tools atuais são ações
ministeriais de escrita; vincular_celula exige a capacidade da Central
(admin/pastor).
A decisão é determinística e resolvida no servidor; o LLM nunca decide autoridade.
Falha fechada (nega por padrão quando não há o sinal exigido).

Sem I/O — testável. O runtime resolve os dados (papéis/células) do banco.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping

from app.domain.consolidation import CONSOLIDATION_ROLES
from app.domain.pipeline import PIPELINE_PROMOTE_ROLES

# Papéis (user_roles do painel) que contam como ministeriais para as tools.
# operador/membro NÃO são ministeriais (não lideram célula nem registram decisão).
MINISTERIAL_ROLES: frozenset[str] = frozenset(
    {"admin", "pastor", "lider_g12", "lider_consol", "lider_celula", "lider_mult"}
)

# ``vincular_celula`` espelha uma operação da Central de Células. A capacidade
# equivale a require_central: pastor ou admin implícito. Tipo da Pessoa,
# liderança de célula e outros papéis ministeriais não ampliam essa permissão.
CENTRAL_TOOL_ROLES: frozenset[str] = frozenset({"admin", "pastor"})
CONSOLIDATION_TOOL_ROLES: frozenset[str] = frozenset(
    {"admin", *CONSOLIDATION_ROLES}
)
PIPELINE_PROMOTE_TOOL_ROLES: frozenset[str] = frozenset(
    {"admin", *PIPELINE_PROMOTE_ROLES}
)


class ToolCapability(str, Enum):
    """Capacidades reconhecidas pelo gate determinístico das tools."""

    CONSOLIDATION = "consolidation"
    PIPELINE_PROMOTE = "pipeline_promote"
    CENTRAL = "central"
    DISABLED = "disabled"


# Registro explícito e imutável das capacidades. Adicionar uma função ao
# executor sem classificá-la aqui mantém a nova tool negada por padrão.
TOOL_CAPABILITIES: Final[Mapping[str, ToolCapability]] = MappingProxyType(
    {
        "registrar_decisao": ToolCapability.CONSOLIDATION,
        # O contador agregado não equivale ao fluxo humano de reuniões. Mantê-lo
        # registrado e desabilitado evita execução acidental até haver paridade.
        "marcar_presenca": ToolCapability.DISABLED,
        "avancar_trilha": ToolCapability.PIPELINE_PROMOTE,
        "vincular_celula": ToolCapability.CENTRAL,
    }
)

# Constantes derivadas preservam a API usada pelos testes e tornam impossível
# haver divergência entre os conjuntos e o registro autoritativo.
MINISTERIAL_TOOLS: frozenset[str] = frozenset(
    name
    for name, capability in TOOL_CAPABILITIES.items()
    if capability is not ToolCapability.DISABLED
)
CENTRAL_TOOLS: frozenset[str] = frozenset(
    name
    for name, capability in TOOL_CAPABILITIES.items()
    if capability is ToolCapability.CENTRAL
)


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
        """True somente com papel ministerial em acesso autenticado utilizável."""
        if self.sem_interesse:
            return False
        return bool(self.roles & MINISTERIAL_ROLES)


def tool_allowed(ctx: PrivilegeContext, tool_name: str) -> bool:
    """True se o interlocutor pode executar esta tool. Determinístico, fail-closed."""
    if ctx.sem_interesse:
        return False
    capability = TOOL_CAPABILITIES.get(tool_name)
    if capability is ToolCapability.CENTRAL:
        return bool(ctx.roles & CENTRAL_TOOL_ROLES)
    if capability is ToolCapability.CONSOLIDATION:
        return bool(ctx.roles & CONSOLIDATION_TOOL_ROLES)
    if capability is ToolCapability.PIPELINE_PROMOTE:
        return bool(ctx.roles & PIPELINE_PROMOTE_TOOL_ROLES)
    return False


def allowed_tools(ctx: PrivilegeContext) -> frozenset[str]:
    """Retorna somente as tools registradas permitidas para o contexto."""
    return frozenset(
        tool_name
        for tool_name in TOOL_CAPABILITIES
        if tool_allowed(ctx, tool_name)
    )


def tool_denial_reason(ctx: PrivilegeContext, tool_name: str) -> str:
    """Motivo estável para auditoria do executor, sem depender do LLM."""
    capability = TOOL_CAPABILITIES.get(tool_name)
    if capability is None:
        return "tool não registrada no controle de capacidades"
    if capability is ToolCapability.DISABLED:
        return "tool desabilitada até equivalência com o fluxo humano"
    if capability is ToolCapability.CENTRAL:
        return "interlocutor sem capacidade da Central de Células"
    return "interlocutor sem papel equivalente ao endpoint humano"


def has_central_tool_role(roles: Iterable[str]) -> bool:
    """True somente para a capacidade Central equivalente a admin/pastor."""
    return bool(set(roles) & CENTRAL_TOOL_ROLES)


def has_ministerial_role(roles: Iterable[str]) -> bool:
    """Helper para checar um conjunto de papéis (sem montar um contexto)."""
    return bool(set(roles) & MINISTERIAL_ROLES)
