"""Canonical states for the durable agent-reply delivery ledger.

Message authorship is an external contract restricted to ``contato``, ``ia``
and ``humano``. These values describe the internal lifecycle of an outbound
agent reply and therefore live in ``messages.agent_reply_state`` instead.
"""

from __future__ import annotations

AGENT_REPLY_RESERVED = "ia_reservada"
AGENT_REPLY_EXECUTING = "ia_executando"
AGENT_REPLY_PENDING = "ia_pendente"
AGENT_REPLY_IN_FLIGHT = "ia_em_transporte"
AGENT_REPLY_CONFIRMED = "ia"
AGENT_REPLY_AMBIGUOUS = "ia_ambigua"
AGENT_REPLY_EXECUTION_AMBIGUOUS = "ia_execucao_ambigua"
AGENT_REPLY_FAILED = "ia_falhou"
AGENT_REPLY_SUPPRESSED = "ia_suprimida"
AGENT_REPLY_NO_RESPONSE = "ia_sem_resposta"

AGENT_REPLY_STATES = (
    AGENT_REPLY_RESERVED,
    AGENT_REPLY_EXECUTING,
    AGENT_REPLY_PENDING,
    AGENT_REPLY_IN_FLIGHT,
    AGENT_REPLY_CONFIRMED,
    AGENT_REPLY_AMBIGUOUS,
    AGENT_REPLY_EXECUTION_AMBIGUOUS,
    AGENT_REPLY_FAILED,
    AGENT_REPLY_SUPPRESSED,
    AGENT_REPLY_NO_RESPONSE,
)
