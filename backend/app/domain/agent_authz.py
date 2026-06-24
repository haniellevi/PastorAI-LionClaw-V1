"""Autorização das tools do agente pelo PRIVILÉGIO do interlocutor (#10b Fase 2).

A pessoa que conversa no WhatsApp não tem login Clerk, então o privilégio dela é
resolvido a partir da própria Pessoa: papel ministerial (via app_users → user_roles),
células que ela lidera (celulas.lider_id) ou um tipo ministerial. As 4 tools do
agente (registrar decisão, marcar presença, vincular célula, avançar trilha) são
**ações ministeriais de escrita** — um contato/visitante/membro JAMAIS pode
dispará-las (ex.: registrar uma decisão por Jesus para si mesmo via um "relatório"
falso). A decisão é determinística e resolvida no servidor; o LLM nunca decide
autoridade. Falha fechada (nega por padrão quando não há sinal ministerial).

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
    if tool_name in MINISTERIAL_TOOLS:
        return ctx.is_ministerial
    return True


def has_ministerial_role(roles: Iterable[str]) -> bool:
    """Helper para checar um conjunto de papéis (sem montar um contexto)."""
    return bool(set(roles) & MINISTERIAL_ROLES)
