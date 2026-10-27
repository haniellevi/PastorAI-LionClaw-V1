"""Private operational summaries, deliberately absent from agent prompts.

No free-form conversation text is sent externally. SQL validates the WHOLE
conversation before projection into a closed operational vocabulary. Durable
jobs reserve worst-case cost before one bounded call, without locks over HTTP.
Ambiguous provider outcomes keep their reservation and are not retried.
The cron cycle runs only on the dedicated ``private_summary_runtime`` login,
through typed projections for central tables and the budget; web enqueue,
correction and reading keep the main login.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from app.db.private_summary_session import (
    PrivateSummaryUnavailable,
    get_private_summary_session_factory,
    require_private_summary_session,
    scope_private_summary,
)
from app.services.private_deletion import acquire_ingestion_barrier

logger = logging.getLogger(__name__)

APPROVED_RELEASE_ID: str | None = None
APPROVED_IGREJA_IDS: frozenset[str] = frozenset()
# Conservative upper bound: <= 2,048 input bytes + 512 output tokens for the
# fixed allowlisted models. No refunds/retries after crossing provider boundary.
RESERVATION_MICROUSD = 100_000
MODEL_ALLOWLIST = frozenset({"gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"})
TOPIC_TEXT = {
    "uv": "Assunto operacional: Universidade da Vida. Dúvida em aberto: obter informações sobre a formação.",
    "cd": "Assunto operacional: Capacitação Destino. Dúvida em aberto: obter informações sobre a formação.",
    "cultos": "Assunto operacional: horários dos cultos. Dúvida em aberto: qual o horário do culto.",
}


def released(tenant: UUID) -> bool:
    return bool(APPROVED_RELEASE_ID and str(tenant) in APPROVED_IGREJA_IDS)


def _enabled(db, tenant):
    return released(tenant) and bool(
        db.execute(
            text("""select enabled and monthly_limit_microusd>0
        from private_summary_settings where igreja_id=:t"""),
            dict(t=tenant),
        ).scalar_one_or_none()
    )


def _snapshot(db, tenant, conversation):
    # Reuses the exclusion lock ordering. Caller commits BEFORE any HTTP.
    acquire_ingestion_barrier(db, tenant)
    row = (
        db.execute(
            text("""select id,pessoa_id,private_summary_revision,deletion_generation
        from conversations where igreja_id=:t and id=:c for update"""),
            dict(t=tenant, c=conversation),
        )
        .mappings()
        .one_or_none()
    )
    if (
        row is None
        or not db.execute(
            text("select private_summary_origin_valid(:t,:c,:p)"),
            dict(t=tenant, c=conversation, p=row["pessoa_id"]),
        ).scalar_one()
    ):
        return None
    return dict(row)


def enqueue(db, tenant: UUID, conversation: UUID):
    """Trusted backend or authenticated API caller; records IDs only, no prompt."""
    if not _enabled(db, tenant):
        return None
    snapshot = _snapshot(db, tenant, conversation)
    if snapshot is None:
        return None
    # Only explicit requests retry failures that never crossed the provider.
    return db.execute(
        text("""insert into private_summary_tasks
        (igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation)
        values(:t,:c,:p,:r,:g) on conflict(igreja_id,conversation_id,source_revision)
        do update set state=case when private_summary_tasks.state='refused' and private_summary_tasks.error_code='budget_or_credential' then 'queued' else private_summary_tasks.state end,
        started_at=case when private_summary_tasks.state='refused' and private_summary_tasks.error_code='budget_or_credential' then null else private_summary_tasks.started_at end,
        error_code=case when private_summary_tasks.state='refused' and private_summary_tasks.error_code='budget_or_credential' then null else private_summary_tasks.error_code end returning id"""),
        dict(
            t=tenant,
            c=conversation,
            p=snapshot["pessoa_id"],
            r=snapshot["private_summary_revision"],
            g=snapshot["deletion_generation"],
        ),
    ).scalar_one()


def reserve_budget(db, tenant: UUID) -> bool:
    """One atomic upsert caps *all* attempts, including failures and crashes."""
    reserved = db.execute(
        text("""insert into private_summary_budget(igreja_id,month,reserved_microusd)
        select :t,date_trunc('month',now())::date,:cost from private_summary_settings
        where igreja_id=:t and enabled and monthly_limit_microusd>=:cost
        on conflict(igreja_id,month) do update set reserved_microusd=private_summary_budget.reserved_microusd+:cost
        where private_summary_budget.reserved_microusd+:cost <=
          (select monthly_limit_microusd from private_summary_settings where igreja_id=:t and enabled)
        returning reserved_microusd"""),
        dict(t=tenant, cost=RESERVATION_MICROUSD),
    ).scalar_one_or_none()
    return reserved is not None


@dataclass(frozen=True)
class Credential:
    id: UUID
    igreja_id: UUID
    model: str
    ciphertext: str


def _runtime_snapshot(db, tenant, conversation):
    # Shared barrier, conversation lock and full origin validation in one typed
    # projection; both locks stay held until this transaction commits.
    row = (
        db.execute(
            text("""select id,pessoa_id,private_summary_revision,deletion_generation
        from private_summary_runtime_snapshot(:t,:c)"""),
            dict(t=tenant, c=conversation),
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else dict(row)


def _runtime_sources(db, tenant, conversation):
    # Message ids and closed operational codes only; never message text.
    return (
        db.execute(
            text("select message_id,topic from private_summary_runtime_sources(:t,:c)"),
            dict(t=tenant, c=conversation),
        )
        .mappings()
        .all()
    )


def _runtime_reserve(db, tenant) -> bool:
    # Same atomic upsert as reserve_budget, fixed cost in SQL, no direct grant.
    return bool(
        db.execute(
            text("select private_summary_runtime_reserve(:t)"), dict(t=tenant)
        ).scalar_one()
    )


def _credential(db, tenant):
    row = (
        db.execute(
            text("""select id,igreja_id,modelo,api_key_encrypted
        from private_summary_runtime_credential(:t)"""),
            dict(t=tenant),
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["modelo"] not in MODEL_ALLOWLIST:
        return None
    return Credential(
        row["id"], row["igreja_id"], row["modelo"], row["api_key_encrypted"]
    )


def openai_provider(*, credential: Credential, topics: tuple[str, ...]):
    """Single bounded OpenAI BYO call. Existing global send gate still applies."""
    from app.services.outbound_guard import external_sends_allowed
    from app.services.crypto import decrypt_secret

    if not external_sends_allowed():
        raise ValueError("external_gate_closed")
    from openai import AsyncOpenAI

    async def call():
        async with asyncio.timeout(20):
            async with AsyncOpenAI(
                api_key=decrypt_secret(credential.ciphertext), max_retries=0, timeout=20
            ) as client:
                return await client.chat.completions.create(
                    model=credential.model,
                    max_completion_tokens=512,
                    messages=[
                        {
                            "role": "system",
                            "content": "Selecione o último assunto operacional informado, em português do Brasil. Retorne somente o JSON do schema. Não atribua identidade nem infira fatos.",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"assuntos_operacionais": topics}, ensure_ascii=False
                            ),
                        },
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "private_operational_summary_v1",
                            "strict": True,
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "topic": {
                                        "type": "string",
                                        "enum": list(dict.fromkeys(topics)),
                                    }
                                },
                                "required": ["topic"],
                                "additionalProperties": False,
                            },
                        },
                    },
                )

    response = asyncio.run(call())
    if len(response.choices) != 1 or response.choices[0].finish_reason != "stop":
        raise ValueError("invalid_output")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("invalid_output")
            result[k] = v
        return result

    return json.loads(response.choices[0].message.content, object_pairs_hook=unique)


def _publish(db, tenant, conversation, snapshot, summary):
    # Preserve the CURRENT correction under the conversation lock; never replay
    # a correction/authorization snapshot captured before HTTP.
    existing = (
        db.execute(
            text("""select state,human_correction from private_conversation_summaries
        where igreja_id=:t and conversation_id=:c"""),
            dict(t=tenant, c=conversation),
        )
        .mappings()
        .one_or_none()
    )
    state = "available"
    correction = None
    if existing:
        if existing["state"] == "incorrect":
            summary = None
            state = "incorrect"
        elif existing["human_correction"]:
            summary = existing["human_correction"]
            state = "corrected"
            correction = summary
    db.execute(
        text("""insert into private_conversation_summaries
        (igreja_id,conversation_id,pessoa_id,source_revision,deletion_generation,state,summary,human_correction)
        values(:t,:c,:p,:r,:g,:state,:summary,:correction)
        on conflict(igreja_id,conversation_id) do update set source_revision=excluded.source_revision,
        deletion_generation=excluded.deletion_generation,state=excluded.state,summary=excluded.summary,
        version=private_conversation_summaries.version+1,updated_at=now()"""),
        dict(
            t=tenant,
            c=conversation,
            p=snapshot["pessoa_id"],
            r=snapshot["private_summary_revision"],
            g=snapshot["deletion_generation"],
            state=state,
            summary=summary,
            correction=correction,
        ),
    )
    # Every message of the conversation, read under the same lock.
    sources = [str(r["message_id"]) for r in _runtime_sources(db, tenant, conversation)]
    db.execute(
        text(
            "delete from private_summary_sources where igreja_id=:t and conversation_id=:c"
        ),
        dict(t=tenant, c=conversation),
    )
    db.execute(
        text(
            """insert into private_summary_sources(igreja_id,conversation_id,message_id)
        select :t,:c,unnest(cast(:ids as uuid[]))"""
        ),
        dict(t=tenant, c=conversation, ids=sources),
    )


def _requester_authorized(db, tenant, requester):
    # NULL is the trusted scheduled backend, never a caller-supplied ID; the
    # SQL projection transcribes the same admin/pastor inbox rule.
    return bool(
        db.execute(
            text("select private_summary_runtime_requester(:t,:u)"),
            dict(t=tenant, u=requester),
        ).scalar_one()
    )


def _run_task(factory, job, provider):
    tenant = job["igreja_id"]
    conversation = job["conversation_id"]
    params = dict(t=tenant, id=job["id"])
    with factory() as db:
        scope_private_summary(db, tenant)
        snapshot = _runtime_snapshot(db, tenant, conversation)
        task = (
            db.execute(
                text(
                    "select state,source_revision,deletion_generation,pessoa_id,requester_id,started_at<now()-interval '2 minutes' abandoned from private_summary_tasks where igreja_id=:t and id=:id for update"
                ),
                params,
            )
            .mappings()
            .one_or_none()
        )
        if task is not None and task["state"] == "running" and task["abandoned"]:
            db.execute(
                text(
                    "update private_summary_tasks set state='refused',error_code='provider_outcome_unknown' where igreja_id=:t and id=:id"
                ),
                params,
            )
            db.commit()
            return False
        if task is None or task["state"] != "queued":
            return False
        if (
            not _enabled(db, tenant)
            or not _requester_authorized(db, tenant, task["requester_id"])
            or snapshot is None
            or (task["source_revision"], task["deletion_generation"], task["pessoa_id"])
            != (
                snapshot["private_summary_revision"],
                snapshot["deletion_generation"],
                snapshot["pessoa_id"],
            )
        ):
            db.execute(
                text(
                    "update private_summary_tasks set state='refused',error_code='origin_invalid' where igreja_id=:t and id=:id"
                ),
                params,
            )
            db.commit()
            return False
        current = (
            db.execute(
                text(
                    "select state,human_correction from private_conversation_summaries where igreja_id=:t and conversation_id=:c"
                ),
                dict(t=tenant, c=conversation),
            )
            .mappings()
            .one_or_none()
        )
        if current and (current["human_correction"] or current["state"] == "incorrect"):
            _publish(db, tenant, conversation, snapshot, None)
            db.execute(
                text(
                    "update private_summary_tasks set state='done' where igreja_id=:t and id=:id"
                ),
                params,
            )
            db.commit()
            return True
        requester = task["requester_id"]
        credential = _credential(db, tenant)
        if credential is None or not _runtime_reserve(db, tenant):
            db.execute(
                text(
                    "update private_summary_tasks set state='refused',error_code='budget_or_credential' where igreja_id=:t and id=:id"
                ),
                params,
            )
            db.commit()
            return False
        topics = tuple(r["topic"] for r in _runtime_sources(db, tenant, conversation))
        db.execute(
            text(
                "update private_summary_tasks set state='running',started_at=now() where igreja_id=:t and id=:id"
            ),
            params,
        )
        db.commit()
    # No DB session, lock or open transaction survives into this boundary.
    failure = None
    summary = None
    try:
        output = provider(credential=credential, topics=topics)
        if (
            type(output) is not dict
            or set(output) != {"topic"}
            or type(output["topic"]) is not str
            or output["topic"] not in topics
        ):
            raise ValueError("invalid_output")
        summary = TOPIC_TEXT[output["topic"]]
        if not 1 <= len(summary) <= 1000:
            raise ValueError("invalid_output")
    except Exception:
        failure = "provider_or_output_refused"
    with factory() as db:
        scope_private_summary(db, tenant)
        latest = _runtime_snapshot(db, tenant, conversation)
        task = db.execute(
            text(
                "select state from private_summary_tasks where igreja_id=:t and id=:id for update"
            ),
            params,
        ).scalar_one_or_none()
        if task != "running":
            return False
        if failure is None and (
            not _enabled(db, tenant)
            or latest != snapshot
            or not _requester_authorized(db, tenant, requester)
            or _credential(db, tenant) != credential
        ):
            failure = "origin_changed"
        if failure is None:
            _publish(db, tenant, conversation, snapshot, summary)
        db.execute(
            text(
                "update private_summary_tasks set state=:state,error_code=:error where igreja_id=:t and id=:id"
            ),
            dict(params, state="refused" if failure else "done", error=failure),
        )
        db.commit()
        return failure is None


def process_tasks(factory=None, *, provider=None, limit=20):
    # Release default returns before discovery, no new migration dependency/cost.
    if not APPROVED_RELEASE_ID or not APPROVED_IGREJA_IDS:
        return 0
    if provider is None:
        from app.services.outbound_guard import external_sends_allowed

        if not external_sends_allowed():
            return 0
    done = 0
    try:
        # Only the dedicated login; an injected main-login factory is refused
        # before any query and there is never a fallback.
        if factory is None:
            factory = get_private_summary_session_factory()
        with factory() as db:
            require_private_summary_session(db)
            jobs = (
                db.execute(
                    text(
                        "select igreja_id,id,conversation_id from private_summary_runtime_due_tasks(:tenants,:n)"
                    ),
                    dict(n=limit, tenants=sorted(APPROVED_IGREJA_IDS)),
                )
                .mappings()
                .all()
            )
        for job in jobs:
            done += _run_task(factory, job, provider or openai_provider)
    except PrivateSummaryUnavailable as exc:
        # Missing/unsafe login or identity changed between transactions: a
        # running task stays running and is later refused as abandoned.
        logger.warning(
            "Private summary runtime unavailable",
            extra={"event": "private_summary_runtime_unavailable", "error_type": type(exc).__name__},
        )
    return done


def read_summary(db, tenant, conversation):
    # Reader and origin are revalidated by FORCE RLS and explicitly for backend
    # calls too. The view is never assembled across conversations or people.
    if not db.execute(
        text("select private_summary_reader(:t,:c)"), dict(t=tenant, c=conversation)
    ).scalar_one():
        raise HTTPException(404, "Resumo indisponível")
    row = (
        db.execute(
            text(
                "select * from private_conversation_summaries where igreja_id=:t and conversation_id=:c and state<>'suspended'"
            ),
            dict(t=tenant, c=conversation),
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(404, "Resumo indisponível")
    sources = (
        db.execute(
            text(
                """select s.message_id,m.criado_em from private_summary_sources s join messages m
        on m.igreja_id=s.igreja_id and m.conversation_id=s.conversation_id and m.id=s.message_id
        where s.igreja_id=:t and s.conversation_id=:c order by m.criado_em,m.id"""
            ),
            dict(t=tenant, c=conversation),
        )
        .mappings()
        .all()
    )
    return dict(
        conversation_id=str(conversation),
        pessoa_id=str(row["pessoa_id"]),
        summary=row["summary"],
        state=row["state"],
        version=row["version"],
        label="derivado, pode errar",
        updated_at=row["updated_at"],
        sources=[
            dict(message_id=str(r["message_id"]), date=r["criado_em"]) for r in sources
        ],
    )


def correct_summary(db, tenant, conversation, version, correction, incorrect):
    accepted = db.execute(
        text("select private_summary_correct(:c,:v,:txt,:bad)"),
        dict(c=conversation, v=version, txt=correction, bad=incorrect),
    ).scalar_one()
    if not accepted:
        raise HTTPException(409, "Origem ou versão mudou; releia a conversa")
    result = read_summary(db, tenant, conversation)
    db.commit()
    return result
