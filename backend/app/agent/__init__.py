"""Agent orchestration package (LangGraph multi-agent — delta-034).

The Orchestrator is the single entry/exit on the official WhatsApp number; the
specialised sub-agents (intake, onboarding, report_capture, handoff, consent)
return results to it. Public entry point: `process_inbound_message`.
"""

from app.agent.runtime import AgentTurnResult, process_inbound_message

__all__ = ["AgentTurnResult", "process_inbound_message"]
