"""Self request is never self deletion. IDs-only audit; caller owns commit."""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.services.private_deletion import receipt

APPROVED_RELEASE_ID: str | None = None
APPROVED_IGREJA_IDS: frozenset[str] = frozenset()
COMMAND = 'QUERO SOLICITAR EXCLUSAO DO MEU CONTEUDO PRIVADO'
PRIVATE_ERASURE_SLA_POLICY_VERSION = 'v1'
PRIVATE_ERASURE_SLA_DAYS_V1 = 15
RESPONSE = (
    'Pedido de exclusão registrado e pendente de decisão do administrador no painel. '
    'O uso da sua memória está suspenso. Nenhum conteúdo foi apagado por este pedido.'
)


def released(tenant: UUID) -> bool:
    return bool(APPROVED_RELEASE_ID and str(tenant) in APPROVED_IGREJA_IDS)


def enabled(db, tenant: UUID) -> bool:
    return released(tenant) and bool(db.execute(
        text('select enabled from private_erasure_request_settings where igreja_id=:t'),
        dict(t=tenant),
    ).scalar_one_or_none())


def detail(db, tenant: UUID, request_id: UUID, *, include_sla: bool = False) -> dict:
    projection = '''select * from private_erasure_requests where igreja_id=:t and id=:r'''
    params = dict(t=tenant, r=request_id)
    if include_sla:
        projection = '''select r.*,
            greatest(0,floor(extract(epoch from now()-r.created_at)))::bigint as idade_segundos,
            (r.state='pendente' and r.created_at<=now()-make_interval(days=>:sla_days)) as vencido
            from private_erasure_requests r where r.igreja_id=:t and r.id=:r'''
        params['sla_days'] = PRIVATE_ERASURE_SLA_DAYS_V1
    row = db.execute(
        text(projection), params,
    ).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, 'Pedido indisponível')
    result = dict(row)
    if include_sla:
        result['prazo_dias'] = PRIVATE_ERASURE_SLA_DAYS_V1
        result['prazo_versao'] = PRIVATE_ERASURE_SLA_POLICY_VERSION
    result['receipt'] = receipt(db, tenant, row['receipt_id']) if row['receipt_id'] else None
    return result


def register(db, *, tenant: UUID, person: UUID, conversation: UUID, inbound: UUID) -> dict:
    if not enabled(db, tenant):
        raise HTTPException(409, 'Pedido de exclusão desativado')
    try:
        rid = db.execute(
            text('select private_erasure_request(:t,:p,:c,:m)'),
            dict(t=tenant, p=person, c=conversation, m=inbound),
        ).scalar_one()
    except DBAPIError as exc:
        if getattr(exc.orig, 'pgcode', None) == '42501':
            raise HTTPException(403, 'Identidade do pedido indisponível') from None
        raise
    return detail(db, tenant, rid)


def decide(db, tenant: UUID, request_id: UUID, decision: str) -> dict:
    # Decisions remain available when request admission is closed. A closed gate
    # must not strand an existing pending request/suspension.
    try:
        rid = db.execute(
            text('select private_erasure_decide(:r,:d)'),
            dict(r=request_id, d=decision),
        ).scalar_one_or_none()
    except DBAPIError as exc:
        code = getattr(exc.orig, 'pgcode', None)
        if code in ('42501', '22023'):
            raise HTTPException(
                403 if code == '42501' else 409, 'Decisão indisponível ou já encerrada',
            ) from None
        raise
    if rid is None:
        raise HTTPException(404, 'Pedido indisponível')
    result = detail(db, tenant, rid)
    db.commit()
    return result
