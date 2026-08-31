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

from typing import Annotated, Any, TypedDict

from langgraph.channels import UntrackedValue
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


class AgentTurnEffects(TypedDict):
    """Complete, turn-local envelope of intents consumed by the runtime.

    This envelope is replaced as one value and uses an untracked LangGraph
    channel, never a reducer.  It is neither durable workflow state nor proof
    that an effect was executed.  Durable checkpointing remains blocked until
    effect idempotency and the persistence boundary are implemented.
    """

    events: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    apply_optout: bool
    apply_consent_version: str | None
    intake_update: dict[str, Any]


class AgentTurnInput(TypedDict):
    """Only caller-controlled values admitted at the graph input boundary."""

    texto: str
    pessoa: PessoaSnapshot


class AgentTurnOutput(TypedDict):
    """Only current-turn decisions returned to the effect-applying runtime."""

    route: str
    response: str | None
    turn_effects: AgentTurnEffects


class AgentState(TypedDict, total=False):
    """Internal working state, deliberately free of authority/context."""

    texto: str
    pessoa: PessoaSnapshot
    # Outputs produced along the graph:
    route: str
    response: str | None
    turn_effects: Annotated[
        AgentTurnEffects,
        UntrackedValue(AgentTurnEffects),
    ]


def empty_turn_effects() -> AgentTurnEffects:
    """Return a fresh, complete effect envelope for exactly one turn."""
    return {
        "events": [],
        "tool_calls": [],
        "apply_optout": False,
        "apply_consent_version": None,
        "intake_update": {},
    }


def _copy_turn_effects(state: AgentState) -> AgentTurnEffects:
    """Detach the current turn envelope before a node adds its own intent."""
    current = state.get("turn_effects")
    if current is None:
        return empty_turn_effects()
    return {
        "events": list(current["events"]),
        "tool_calls": list(current["tool_calls"]),
        "apply_optout": current["apply_optout"],
        "apply_consent_version": current["apply_consent_version"],
        "intake_update": dict(current["intake_update"]),
    }


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
    # A future rehydrated state may carry a completed or partially completed
    # envelope.  Reset it before any node emits this turn's intents.  The
    # graph remains stateless today, but this replacement invariant prevents
    # reducers or sticky scalar flags from becoming an accidental replay API.
    fresh_state: AgentState = {
        **state,
        "turn_effects": empty_turn_effects(),
    }
    updates = intake_node(fresh_state, runtime)
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
    effects = _copy_turn_effects(state)
    effects["intake_update"] = update
    effects["events"].append(
        {
            "evento": "intake",
            "payload": {"update": update},
        }
    )
    return {"turn_effects": effects}


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
    effects = _copy_turn_effects(state)

    if consent_rules.needs_reaccept(
        context.legacy_term.accepted_version, current
    ) and consent_rules.is_acceptance(texto):
        effects["apply_consent_version"] = current
        effects["events"].append(
            {
                "evento": "consent_accepted",
                "payload": {
                    "termoVersao": current,
                },
            }
        )
        return {
            "route": ROUTE_CONSENT,
            "response": (
                "Obrigado! Seu consentimento foi registrado. "
                "Como posso te ajudar hoje?"
            ),
            "turn_effects": effects,
        }

    effects["events"].append(
        {
            "evento": "consent_presented",
            "payload": {
                "termoVersao": current,
            },
        }
    )
    return {
        "route": ROUTE_CONSENT,
        "response": consent_rules.term_text(current, igreja_nome),
        "turn_effects": effects,
    }


def optout_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """optout (US-32/RNF-06): flag the runtime to set pessoas.optout=true."""
    _trusted(state, runtime)
    effects = _copy_turn_effects(state)
    effects["apply_optout"] = True
    effects["events"].append({"evento": "optout", "payload": {}})
    return {
        "route": ROUTE_OPTOUT,
        "response": (
            "Tudo certo. Você não receberá mais comunicados. "
            "Se mudar de ideia, é só nos enviar uma mensagem."
        ),
        "turn_effects": effects,
    }


def handoff_node(
    state: AgentState, runtime: Runtime[TrustedAgentContext]
) -> AgentState:
    """handoff (US-12/13): a human owns the chat — suspend the auto reply.

    The orchestrator emits NO automatic message (response=None); output still
    flows exclusively through the official number when the human replies.
    """
    _trusted(state, runtime)
    effects = _copy_turn_effects(state)
    effects["events"].append(
        {"evento": "handoff_suspended", "payload": {}}
    )
    return {
        "route": ROUTE_HANDOFF,
        "response": None,
        "turn_effects": effects,
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
    effects = _copy_turn_effects(state)
    effects["tool_calls"] = []
    effects["events"].append(
        {"evento": "report_captured", "payload": {"relatorio": resumo}}
    )
    return {
        "route": ROUTE_REPORT,
        "response": (
            "Relatório recebido! Resumo informado: "
            f"{report.presentes or 0} presentes, "
            f"{report.visitantes or 0} visitantes, "
            f"{report.decisoes or 0} decisões. "
            "As decisões individuais precisam de confirmação humana antes do registro."
        ),
        "turn_effects": effects,
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

    effects = _copy_turn_effects(state)

    # Mescla o CSIM no intake_update já produzido pelo intake_node
    # (origem/primeiro_contato), sem sobrescrevê-lo.
    intake = dict(effects["intake_update"])
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

    effects["intake_update"] = intake
    effects["events"].append(
        {
            "evento": "onboarding",
            "payload": {
                "classificacao": classificacao,
            },
        }
    )
    return {
        "route": ROUTE_ONBOARDING,
        "response": resposta,
        "turn_effects": effects,
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
