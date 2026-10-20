"""Shared privacy boundary for conversation, person and tenant content erasure.

Receipts contain IDs/counts only. Object paths exist solely in pending tasks and
are erased on success. Backups/provider copies are outside this receipt's scope;
a restore must reapply these tombstones before starting consumers.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Conversation
from app.db.tenant_session import mark_cross_tenant, mark_tenant_scoped

DeletionScope = Literal['conversa', 'pessoa', 'igreja', 'reset']
LAYERS = ('mensagens', 'midias', 'transcricoes', 'resumos', 'checkpoints', 'vetores',
          'logs_agente', 'envios', 'entradas_audio', 'logs_sem_ancora',
          'agent_identity_challenges', 'agent_identity_proofs', 'agent_action_proposals',
          'agent_action_receipts', 'cell_report_drafts', 'cell_report_audio_notices',
          'cell_report_audio_consent_events', 'pedido_oracao', 'pedido_oracao_proposta', 'pedido_oracao_mensagem')


def acquire_ingestion_barrier(db: Session, igreja_id: UUID, *, exclusive: bool = False) -> None:
    """Before any domain row lock: erase vs ingest serialize only within tenant."""
    function = 'pg_advisory_xact_lock' if exclusive else 'pg_advisory_xact_lock_shared'
    db.execute(text(f"select {function}(hashtextextended('private-content:'||:tenant,0))"),
               dict(tenant=str(igreja_id)))


def receipt(db: Session, igreja_id: UUID, receipt_id: UUID) -> dict:
    row = db.execute(text('select * from private_deletion_receipts where igreja_id=:t and id=:id'),
                     dict(t=igreja_id, id=receipt_id)).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, 'Recibo não encontrado')
    receipt_ids = [receipt_id, *db.execute(text('''select dependency_id from private_deletion_dependencies
        where igreja_id=:t and receipt_id=:id'''), dict(t=igreja_id, id=receipt_id)).scalars().all()]
    counts = db.execute(text('''select counts from private_deletion_receipts
        where igreja_id=:t and id=any(:ids)'''), dict(t=igreja_id, ids=receipt_ids)).scalars().all()
    totals = {layer: sum(c.get(layer, 0) for c in counts) for layer in LAYERS}
    tasks = db.execute(text("""select count(*) filter(where state='pendente') pending,
        count(*) filter(where state='pendente' and error_code is not null) failed,
        count(*) filter(where state='concluida') done
        from private_deletion_tasks where igreja_id=:t and receipt_id=any(:ids)"""),
        dict(t=igreja_id, ids=receipt_ids)).mappings().one()
    sends = db.execute(text('''select count(*) from private_deletion_sends s where s.igreja_id=:t
        and exists(select 1 from private_deletion_members m where m.igreja_id=s.igreja_id
         and m.receipt_id=any(:ids) and m.conversation_id=s.conversation_id)'''),
        dict(t=igreja_id, ids=receipt_ids)).scalar_one()
    layers = {layer: dict(encontradas=totals[layer],
                         apagadas=totals[layer], pendentes=0, falhas=0) for layer in LAYERS}
    layers['midias'].update(apagadas=tasks['done'], pendentes=tasks['pending'], falhas=tasks['failed'])
    layers['envios'].update(apagadas=totals['envios'] - sends, pendentes=sends)
    return dict(id=str(row['id']), igreja_id=str(igreja_id), escopo=row['scope'],
                alvo_id=str(row['target_id']), geracao=row['generation'],
                fora_do_alcance='backups, cópias de provedor e texto já enviado ao provedor',
                estado='pendente_envio' if sends else ('pendente' if tasks['pending'] else 'concluido'), camadas=layers)


def delete_private(db: Session, *, scope: DeletionScope, igreja_id: UUID, target_id: UUID,
                   operation_id: UUID | None = None) -> dict:
    if scope not in ('conversa', 'pessoa', 'igreja'):
        raise ValueError('Reset global usa o runbook de tenant, nunca o endpoint web')
    if scope != 'conversa' and operation_id is None:
        raise ValueError('Escopo coletivo exige identificador idempotente da operação')
    rid = db.execute(text('select private_delete_scope(:t,:scope,:target,:operation)'),
                     dict(t=igreja_id, scope=scope, target=target_id,
                          operation=operation_id or target_id)).scalar_one_or_none()
    if rid is None:
        raise HTTPException(404, 'Alvo não encontrado')
    result = receipt(db, igreja_id, rid)
    db.commit()
    return result


def lock_generation(db: Session, igreja_id: UUID, conversation_id: UUID, generation: int) -> bool:
    """Recheck under the same row lock as deletion, retained through commit."""
    current = db.execute(select(Conversation).where(
        Conversation.igreja_id == igreja_id, Conversation.id == conversation_id,
    ).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    return current is not None and current.deletion_generation == generation


def reopen_late_audio_upload(db: Session, *, igreja_id: UUID, conversation_id: UUID,
                            source_id: UUID, storage_path: str) -> bool:
    """A late upload reopens cleanup even if an earlier DELETE saw no object.

    The worker holds this receipt lock before the task lock, as does cleanup.
    Pending work and its path survive process/tenant loss; no audio is recreated.
    """
    rid = db.execute(text("""select receipt_id from private_deletion_tasks
        where igreja_id=:t and source_id=:source limit 1"""),
        dict(t=igreja_id, source=source_id)).scalar_one_or_none()
    if rid is None:
        return False
    db.execute(text('select pg_advisory_xact_lock(hashtextextended(:id, 0))'), dict(id=str(rid)))
    result = db.execute(text("""update private_deletion_tasks set state='pendente', storage_path=:path,
        error_code=null, next_attempt_at=now() where igreja_id=:t and receipt_id=:r and source_id=:source"""),
        dict(t=igreja_id, r=rid, source=source_id, path=storage_path))
    return result.rowcount > 0


def process_storage_tasks(session_factory: Callable[[], Session], *, storage: object,
                          now: dt.datetime | None = None, limit: int = 100) -> int:
    """Bounded maintenance, independent of send gates; strict Storage DELETE.

    Named discovery reads IDs only. Tenant-scoped processing uses NOBYPASSRLS.
    Row locks serialize duplicate workers and late-upload reopening; failures
    retain their path and exponential backoff, including after a process crash.
    """
    current = now or dt.datetime.now(dt.timezone.utc)
    with session_factory() as db:
        mark_cross_tenant(db, source='private_deletion_cleanup_discovery')
        jobs = db.execute(text("""select id,igreja_id,receipt_id from private_deletion_tasks
            where state='pendente' and next_attempt_at<=:now and not exists(
             select 1 from private_deletion_uploads u where u.igreja_id=private_deletion_tasks.igreja_id
              and u.source_id=private_deletion_tasks.source_id)
            order by next_attempt_at,id limit :limit"""),
            dict(now=current, limit=limit)).mappings().all()
    done = 0
    for job in jobs:
        with session_factory() as db:
            mark_tenant_scoped(db, job['igreja_id'], source='private_deletion_cleanup')
            acquired = db.execute(text('select pg_try_advisory_xact_lock(hashtextextended(:id, 0))'),
                                  dict(id=str(job['receipt_id']))).scalar_one()
            if not acquired:
                db.rollback()
                continue
            task = db.execute(text("""select id,attempts from private_deletion_tasks where id=:id
                and igreja_id=:t and state='pendente' and next_attempt_at<=:now and not exists(
                 select 1 from private_deletion_uploads u where u.igreja_id=:t and u.source_id=private_deletion_tasks.source_id)
                for update skip locked"""),
                dict(id=job['id'], t=job['igreja_id'], now=current)).mappings().one_or_none()
            if task is None:
                db.commit()
                continue
            path = db.execute(text('select private_deletion_task_path(:id)'), dict(id=job['id'])).scalar_one()
            try:
                storage.remove_tenant_media(job['igreja_id'], [path])
            except Exception:  # No provider payload/PII in error state or logs.
                delay = min(3600, 30 * 2 ** min(task['attempts'], 7))
                db.execute(text("""update private_deletion_tasks set attempts=attempts+1,
                    error_code='storage_unavailable',next_attempt_at=:retry where id=:id and igreja_id=:t"""),
                    dict(id=job['id'], t=job['igreja_id'], retry=current + dt.timedelta(seconds=delay)))
            else:
                db.execute(text("""update private_deletion_tasks set attempts=attempts+1,
                    state='concluida',storage_path=null,error_code=null where id=:id and igreja_id=:t"""),
                    dict(id=job['id'], t=job['igreja_id']))
                done += 1
            db.commit()
    return done


def event_was_deleted(db: Session, igreja_id: UUID, provider_message_id: str) -> bool:
    digest = hashlib.sha256(provider_message_id.encode()).hexdigest()
    token = UUID(hashlib.md5(f'{igreja_id}:{digest}'.encode(), usedforsecurity=False).hexdigest())
    return db.execute(text('select event_token from private_deletion_event_fences '
                           'where igreja_id=:t and event_token=:token'),
                      dict(t=igreja_id, token=token)).scalar_one_or_none() is not None


def begin_audio_upload(session_factory: Callable[[], Session], claim: object) -> bool:
    """Commit ownership before any upload. Deletion takes the same generation lock."""
    with session_factory() as db:
        mark_tenant_scoped(db, claim.igreja_id, source='private_audio_upload_begin')
        if not lock_generation(db, claim.igreja_id, claim.conversation_id, claim.deletion_generation):
            db.rollback()
            return False
        result = db.execute(text("""insert into private_deletion_uploads
            (igreja_id,source_id,conversation_id,generation) values(:t,:source,:c,:g)
            on conflict(igreja_id,source_id) do nothing returning source_id"""),
            dict(t=claim.igreja_id, source=claim.input_id, c=claim.conversation_id, g=claim.deletion_generation))
        accepted = result.scalar_one_or_none() is not None
        db.commit()
        return accepted


def finish_audio_upload(session_factory: Callable[[], Session], claim: object) -> None:
    """Resolve upload + reopen deletion atomically. DB failure retains ownership.

    A crashed/ambiguous uploader stays pending until explicit reconciliation;
    expiry alone is never evidence that the external write has stopped.
    """
    from app.services.storage import cell_report_audio_storage_path

    with session_factory() as db:
        mark_tenant_scoped(db, claim.igreja_id, source='private_audio_upload_finish')
        path = claim.storage_path or cell_report_audio_storage_path(
            claim.igreja_id, claim.provider_message_sha256, claim.declared_mime)
        reopen_late_audio_upload(db, igreja_id=claim.igreja_id, conversation_id=claim.conversation_id,
                                source_id=claim.input_id, storage_path=path)
        db.execute(text('delete from private_deletion_uploads where igreja_id=:t and source_id=:source'),
                   dict(t=claim.igreja_id, source=claim.input_id))
        db.commit()


def send_generation_is_current(db: Session, igreja_id: UUID, conversation_id: UUID,
                               source_id: UUID, generation: int) -> bool:
    """Caller holds the conversation lock; no HTTP occurs in this transaction."""
    from app.db.models import PrivateDeletionSend
    return db.execute(select(PrivateDeletionSend.source_id).where(
        PrivateDeletionSend.igreja_id == igreja_id, PrivateDeletionSend.source_id == source_id,
        PrivateDeletionSend.conversation_id == conversation_id,
        PrivateDeletionSend.generation == generation,
        PrivateDeletionSend.expires_at > text("clock_timestamp()"),
    )).scalar_one_or_none() is not None


def finish_agent_send(session_factory: Callable[[], Session], igreja_id: UUID, source_id: UUID) -> None:
    """Release only after the external boundary returns; failure stays pending."""
    from sqlalchemy import delete
    from app.db.models import PrivateDeletionSend
    with session_factory() as db:
        mark_tenant_scoped(db, igreja_id, source='private_agent_send_finish')
        db.execute(delete(PrivateDeletionSend).where(
            PrivateDeletionSend.igreja_id == igreja_id, PrivateDeletionSend.source_id == source_id))
        db.commit()


def renew_agent_send(db: Session, igreja_id: UUID, conversation_id: UUID,
                     source_id: UUID, generation: int) -> bool:
    """Renew the full boundary window under the deletion lock, just before HTTP.

    An already expired owner cannot start another transport. Connectivity probes
    must not consume the window reserved for the actual POST.
    """
    from sqlalchemy import update, func
    from app.db.models import PrivateDeletionSend
    return db.execute(update(PrivateDeletionSend).where(
        PrivateDeletionSend.igreja_id == igreja_id, PrivateDeletionSend.source_id == source_id,
        PrivateDeletionSend.conversation_id == conversation_id,
        PrivateDeletionSend.generation == generation,
        PrivateDeletionSend.expires_at > func.clock_timestamp(),
    ).values(expires_at=func.clock_timestamp() + text("interval '60 seconds'"))
      .returning(PrivateDeletionSend.source_id)).scalar_one_or_none() is not None
