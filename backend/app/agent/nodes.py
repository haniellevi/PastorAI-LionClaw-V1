"""Orchestrator supervisor and specialised sub-agents (delta-034).

Design (SPEC 3.4): a single **Orchestrator** is the only actor that talks on the
official WhatsApp number. It receives every inbound message, routes by
intent/state to one specialised sub-agent, and consolidates a **single** reply.
Sub-agents never message the user directly — they return a partial result
(reply draft, tool calls, events, flags) to the orchestrator.

These node functions are pure and I/O-free: they read an `AgentState` snapshot
and return a partial-update dict. The runtime layer (`runtime.py`) applies the
side effects (tool execution, consent/opt-out persistence, logging) and emits
the orchestrator's single outbound message. This keeps routing and sub-agent
behaviour deterministic and unit-testable without a database or an LLM.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.domain import consent as consent_rules
from app.domain.report import looks_like_report, parse_cell_report

# Route identifiers (which sub-agent the supervisor selected).
ROUTE_HANDOFF = "handoff"
ROUTE_OPTOUT = "optout"
ROUTE_CONSENT = "consent"
ROUTE_REPORT = "report_capture"
ROUTE_ONBOARDING = "onboarding"
ROUTE_INTAKE = "intake"

# Conversation states (mirrors domain.conversations.VALID_ESTADOS).
ESTADO_HUMANO = "humano"

# Onboarding fields collected beyond the baseline (name+telefone). Collecting
# any of these requires an accepted, current consent term (delta-040).
ONBOARDING_FIELDS: tuple[str, ...] = (
    "endereco",
    "interesse",
    "oracao",
    "ja_frequenta",
)


class PessoaSnapshot(TypedDict, total=False):
    """Minimal person view the agent reasons over (no ORM dependency)."""

    id: str
    nome: str
    telefone: str
    tipo: str
    etapa: str
    origem: str
    has_endereco: bool
    primeiro_contato_set: bool


class AgentState(TypedDict, total=False):
    """LangGraph state passed between the supervisor and sub-agents."""

    igreja_id: str
    igreja_nome: str
    conversation_id: str
    pessoa_id: str
    texto: str
    estado: str
    pessoa: PessoaSnapshot
    term_accepted_version: str | None
    term_current_version: str
    # Outputs produced along the graph:
    route: str
    response: str | None
    events: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    apply_optout: bool
    apply_consent_version: str | None
    intake_update: dict[str, Any]


# ---------------------------------------------------------------------------
# Orchestrator (supervisor / entry node)
# ---------------------------------------------------------------------------
def route_intent(state: AgentState) -> str:
    """Decide which sub-agent handles this turn (pure routing).

    Priority:
      1. handoff   — a human owns the conversation (suspend auto reply).
      2. optout    — the contact asked to stop receiving messages (US-32).
      3. consent   — acceptance of a pending term, or a term must be presented
                     before collecting data beyond name+telefone (delta-040).
      4. report    — the message looks like a cell report (US-24).
      5. onboarding— default configurable data-collection / classification.
    """
    if state.get("estado") == ESTADO_HUMANO:
        return ROUTE_HANDOFF

    texto = state.get("texto") or ""
    if consent_rules.is_optout_request(texto):
        return ROUTE_OPTOUT

    needs_term = consent_rules.needs_reaccept(
        state.get("term_accepted_version"),
        state.get("term_current_version", "v1"),
    )

    # An explicit acceptance is handled by the consent sub-agent.
    if needs_term and consent_rules.is_acceptance(texto):
        return ROUTE_CONSENT

    if looks_like_report(texto):
        return ROUTE_REPORT

    # Collecting onboarding data beyond the baseline requires the term first.
    if needs_term:
        return ROUTE_CONSENT

    return ROUTE_ONBOARDING


def orchestrator_node(state: AgentState) -> AgentState:
    """Supervisor entry node: run intake then pick the route."""
    updates = intake_node(state)
    merged: AgentState = {**state, **updates}
    merged["route"] = route_intent(merged)
    return merged


# ---------------------------------------------------------------------------
# Sub-agents (never reply directly; return partial updates to the supervisor)
# ---------------------------------------------------------------------------
def intake_node(state: AgentState) -> AgentState:
    """intake (US-09/RF-12): ensure pessoa basics (origem, primeiro_contato).

    The person row already exists (created at ingestion). Here we record an
    `intake_update` describing fields the runtime should backfill — origem
    defaults to 'whatsapp' and primeiro_contato is set on first contact.
    """
    pessoa = state.get("pessoa", {})
    update: dict[str, Any] = {}
    if not pessoa.get("origem"):
        update["origem"] = "whatsapp"
    if not pessoa.get("primeiro_contato_set"):
        update["set_primeiro_contato"] = True
    events = [
        {
            "evento": "intake",
            "payload": {"pessoaId": state.get("pessoa_id"), "update": update},
        }
    ]
    return {"intake_update": update, "events": events}


def consent_node(state: AgentState) -> AgentState:
    """consent (delta-040): present the term, or record its acceptance.

    - On an affirmative reply to a pending term: flag the runtime to write a
      consent_records row at the current version (apply_consent_version) and
      acknowledge.
    - Otherwise: present the current term and collect nothing further until it
      is accepted.
    """
    texto = state.get("texto") or ""
    current = state.get("term_current_version", "v1")
    igreja_nome = state.get("igreja_nome")

    if consent_rules.needs_reaccept(
        state.get("term_accepted_version"), current
    ) and consent_rules.is_acceptance(texto):
        return {
            "route": ROUTE_CONSENT,
            "apply_consent_version": current,
            "response": (
                "Obrigado! Seu consentimento foi registrado. "
                "Como posso te ajudar hoje?"
            ),
            "events": [
                {
                    "evento": "consent_accepted",
                    "payload": {
                        "pessoaId": state.get("pessoa_id"),
                        "termoVersao": current,
                    },
                }
            ],
        }

    return {
        "route": ROUTE_CONSENT,
        "response": consent_rules.term_text(current, igreja_nome),
        "events": [
            {
                "evento": "consent_presented",
                "payload": {
                    "pessoaId": state.get("pessoa_id"),
                    "termoVersao": current,
                },
            }
        ],
    }


def optout_node(state: AgentState) -> AgentState:
    """optout (US-32/RNF-06): flag the runtime to set pessoas.optout=true."""
    return {
        "route": ROUTE_OPTOUT,
        "apply_optout": True,
        "response": (
            "Tudo certo. Você não receberá mais comunicados. "
            "Se mudar de ideia, é só nos enviar uma mensagem."
        ),
        "events": [
            {"evento": "optout", "payload": {"pessoaId": state.get("pessoa_id")}}
        ],
    }


def handoff_node(state: AgentState) -> AgentState:
    """handoff (US-12/13): a human owns the chat — suspend the auto reply.

    The orchestrator emits NO automatic message (response=None); output still
    flows exclusively through the official number when the human replies.
    """
    return {
        "route": ROUTE_HANDOFF,
        "response": None,
        "events": [
            {
                "evento": "handoff_suspended",
                "payload": {"conversationId": state.get("conversation_id")},
            }
        ],
    }


def report_capture_node(state: AgentState) -> AgentState:
    """report_capture (US-24/delta-041): parse the report; a decision opens consolidation.

    When a decisão por Jesus is reported, emit a `registrar_decisao` tool call
    (visitante vínculo) so the runtime opens the consolidation via the trigger.
    """
    texto = state.get("texto") or ""
    report = parse_cell_report(texto)
    tool_calls: list[dict[str, Any]] = []
    if report.has_decisions and state.get("pessoa_id"):
        tool_calls.append(
            {
                "ferramenta": "registrar_decisao",
                "args": {
                    "pessoa_id": state.get("pessoa_id"),
                    "vinculo": "visitante",
                    "origem": "relatorio_celula",
                },
            }
        )

    resumo = {
        "presentes": report.presentes,
        "visitantes": report.visitantes,
        "decisoes": report.decisoes,
        "oferta": report.oferta,
    }
    return {
        "route": ROUTE_REPORT,
        "tool_calls": tool_calls,
        "response": (
            "Relatório recebido! Registrei: "
            f"{report.presentes or 0} presentes, "
            f"{report.visitantes or 0} visitantes, "
            f"{report.decisoes or 0} decisões. Deus abençoe!"
        ),
        "events": [
            {"evento": "report_captured", "payload": {"relatorio": resumo}}
        ],
    }


def onboarding_node(state: AgentState) -> AgentState:
    """onboarding (US-10/RF-13): collect configurable data, classify the person.

    Reached only after consent is in place. Classifies contato vs visitante by
    a simple rule (already-attends -> contato; otherwise visitante) and asks the
    next configurable question.
    """
    pessoa = state.get("pessoa", {})
    classificacao = pessoa.get("tipo") or "visitante"
    proxima_pergunta = (
        "Que bom falar com você! Você já frequenta alguma igreja ou célula?"
        if not pessoa.get("has_endereco")
        else "Pode me contar um pouco sobre o que você está buscando?"
    )
    return {
        "route": ROUTE_ONBOARDING,
        "response": proxima_pergunta,
        "events": [
            {
                "evento": "onboarding",
                "payload": {
                    "pessoaId": state.get("pessoa_id"),
                    "classificacao": classificacao,
                },
            }
        ],
    }


# Map a route to its sub-agent node (used by the graph and the runtime).
SUBAGENTS = {
    ROUTE_HANDOFF: handoff_node,
    ROUTE_OPTOUT: optout_node,
    ROUTE_CONSENT: consent_node,
    ROUTE_REPORT: report_capture_node,
    ROUTE_ONBOARDING: onboarding_node,
    ROUTE_INTAKE: intake_node,
}
