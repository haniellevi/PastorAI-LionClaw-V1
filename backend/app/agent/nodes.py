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

import operator
from typing import Annotated, Any, TypedDict

from langgraph.runtime import Runtime

from app.agent.context import (
    TrustedAgentContext,
    context_from_runtime,
    validate_agent_node_state,
)
from app.domain import consent as consent_rules
from app.domain.classification import classify_contact
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

    nome: str
    subetapa: str
    origem: str
    has_endereco: bool
    primeiro_contato_set: bool


class AgentState(TypedDict, total=False):
    """Mutable LangGraph state, deliberately free of authority/context."""

    texto: str
    pessoa: PessoaSnapshot
    # Outputs produced along the graph:
    route: str
    response: str | None
    events: Annotated[list[dict[str, Any]], operator.add]
    tool_calls: Annotated[list[dict[str, Any]], operator.add]
    apply_optout: bool
    apply_consent_version: str | None
    intake_update: dict[str, Any]


# ---------------------------------------------------------------------------
# Orchestrator (supervisor / entry node)
# ---------------------------------------------------------------------------
def _trusted(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> TrustedAgentContext:
    validate_agent_node_state(state)
    return context_from_runtime(runtime)


def route_intent(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> str:
    """Decide which sub-agent handles this turn (pure routing).

    Priority:
      1. handoff   — a human owns the conversation (suspend auto reply).
      2. optout    — the contact asked to stop receiving messages (US-32).
      3. consent   — acceptance of a pending term, or a term must be presented
                     before collecting data beyond name+telefone (delta-040).
      4. report    — a MINISTERIAL interlocutor sent a cell report (US-24).
      5. onboarding— default configurable data-collection / classification.
    """
    context = _trusted(state, runtime)
    if context.conversation_state == ESTADO_HUMANO:
        return ROUTE_HANDOFF

    texto = state.get("texto") or ""
    if consent_rules.is_optout_request(texto):
        return ROUTE_OPTOUT

    needs_term = consent_rules.needs_reaccept(
        context.legacy_term.accepted_version,
        context.legacy_term.current_version,
    )

    # An explicit acceptance is handled by the consent sub-agent.
    if needs_term and consent_rules.is_acceptance(texto):
        return ROUTE_CONSENT

    # Report capture is a ministerial action (#10b Fase 2): only a leader/pastor
    # files cell reports/decisions. A non-ministerial contact whose message just
    # "looks like" a report falls through to onboarding (no false confirmation,
    # no self-registered decision). Defense-in-depth: the tool executor also
    # gates the call.
    if context.privilege.is_ministerial and looks_like_report(texto):
        return ROUTE_REPORT

    # Collecting onboarding data beyond the baseline requires the term first.
    if needs_term:
        return ROUTE_CONSENT

    return ROUTE_ONBOARDING


def orchestrator_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """Supervisor entry node: run intake then pick the route."""
    _trusted(state, runtime)
    updates = intake_node(state, runtime)
    return {**updates, "route": route_intent(state, runtime)}


# ---------------------------------------------------------------------------
# Sub-agents (never reply directly; return partial updates to the supervisor)
# ---------------------------------------------------------------------------
def intake_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """intake (US-09/RF-12): ensure pessoa basics (origem, primeiro_contato).

    The person row already exists (created at ingestion). Here we record an
    `intake_update` describing fields the runtime should backfill — origem
    defaults to 'whatsapp' and primeiro_contato is set on first contact.
    """
    _trusted(state, runtime)
    pessoa = state.get("pessoa", {})
    update: dict[str, Any] = {}
    if not pessoa.get("origem"):
        update["origem"] = "whatsapp"
    if not pessoa.get("primeiro_contato_set"):
        update["set_primeiro_contato"] = True
    events = [
        {
            "evento": "intake",
            "payload": {"update": update},
        }
    ]
    return {"intake_update": update, "events": events}


def consent_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """consent (delta-040): present the term, or record its acceptance.

    - On an affirmative reply to a pending term: flag the runtime to write a
      consent_records row at the current version (apply_consent_version) and
      acknowledge.
    - Otherwise: present the current term and collect nothing further until it
      is accepted.
    """
    context = _trusted(state, runtime)
    texto = state.get("texto") or ""
    current = context.legacy_term.current_version
    igreja_nome = context.igreja_nome

    if consent_rules.needs_reaccept(
        context.legacy_term.accepted_version, current
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
                    "termoVersao": current,
                },
            }
        ],
    }


def optout_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """optout (US-32/RNF-06): flag the runtime to set pessoas.optout=true."""
    _trusted(state, runtime)
    return {
        "route": ROUTE_OPTOUT,
        "apply_optout": True,
        "response": (
            "Tudo certo. Você não receberá mais comunicados. "
            "Se mudar de ideia, é só nos enviar uma mensagem."
        ),
        "events": [{"evento": "optout", "payload": {}}],
    }


def handoff_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """handoff (US-12/13): a human owns the chat — suspend the auto reply.

    The orchestrator emits NO automatic message (response=None); output still
    flows exclusively through the official number when the human replies.
    """
    _trusted(state, runtime)
    return {
        "route": ROUTE_HANDOFF,
        "response": None,
        "events": [{"evento": "handoff_suspended", "payload": {}}],
    }


def report_capture_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """report_capture (US-24/delta-041): parse an aggregate cell report.

    Aggregate decision counts do not identify the people who made each
    decision. Persisting one against the report sender would corrupt pastoral
    data, so this node records only the summary event and asks for human
    confirmation of individual decisions.
    """
    _trusted(state, runtime)
    texto = state.get("texto") or ""
    report = parse_cell_report(texto)

    resumo = {
        "presentes": report.presentes,
        "visitantes": report.visitantes,
        "decisoes": report.decisoes,
        "oferta": report.oferta,
    }
    return {
        "route": ROUTE_REPORT,
        "tool_calls": [],
        "response": (
            "Relatório recebido! Resumo informado: "
            f"{report.presentes or 0} presentes, "
            f"{report.visitantes or 0} visitantes, "
            f"{report.decisoes or 0} decisões. "
            "As decisões individuais precisam de confirmação humana antes do registro."
        ),
        "events": [
            {"evento": "report_captured", "payload": {"relatorio": resumo}}
        ],
    }


def first_name_for_greeting(nome: str | None) -> str | None:
    """Primeiro nome CONFIÁVEL pra saudar, ou ``None`` pra manter a resposta
    genérica (Missão M7B-W1).

    Confiável = tem letra e não é apenas o telefone. Um contato novo nasce com
    ``nome = push_name or telefone_raw`` (queue_worker); sem push_name, o "nome"
    é a própria string do telefone — saudar por ele soaria como robô. O teste de
    "tem letra" cobre tanto sequência numérica pura quanto o telefone
    formatado (dígitos, ``+``, ``-`` e espaços não têm letra).
    """
    if not nome:
        return None
    tokens = nome.split()
    if not tokens:
        return None
    first = tokens[0]
    if not any(c.isalpha() for c in first):
        return None
    return first


def onboarding_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """onboarding (US-10/RF-13/#1): flag CSIM, then drive the turn.

    Reached only after consent is in place. Detects CSIM (a contact with no
    ministerial link) and records it in ``intake_update`` for the runtime to
    persist; a CSIM contact gets a polite close and leaves the funnel. The
    ``contato → visitante`` transition is NOT decided here — it happens through a
    real event (leader cadastro, consolidation handoff, church check-in), never
    from a self-declared "I went to church" in chat.
    """
    _trusted(state, runtime)
    pessoa = state.get("pessoa", {})
    texto = state.get("texto") or ""
    cls = classify_contact(texto)

    # Mescla o CSIM no intake_update já produzido pelo intake_node
    # (origem/primeiro_contato), sem sobrescrevê-lo.
    intake = dict(state.get("intake_update") or {})
    if cls.sem_interesse is not None:
        intake["sem_interesse"] = cls.sem_interesse
        intake["sem_interesse_motivo"] = cls.motivo

    if cls.sem_interesse:
        classificacao = "csim"
        resposta = (
            "Obrigado pelo contato! No momento não conseguimos seguir o "
            "atendimento por aqui, mas agradecemos a sua mensagem. 🙏"
        )
    else:
        classificacao = pessoa.get("subetapa") or "novo_contato"
        base = (
            "Que bom falar com você! Como posso te ajudar?"
            if not pessoa.get("has_endereco")
            else "Pode me contar um pouco sobre o que você está buscando?"
        )
        # Saudação nominal quando a pessoa reconhecida tem nome confiável
        # (usa a Pessoa já carregada — nunca o push_name — e o 1º nome).
        primeiro_nome = first_name_for_greeting(pessoa.get("nome"))
        resposta = f"Olá, {primeiro_nome}! {base}" if primeiro_nome else base

    return {
        "route": ROUTE_ONBOARDING,
        "intake_update": intake,
        "response": resposta,
        "events": [
            {
                "evento": "onboarding",
                "payload": {
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
