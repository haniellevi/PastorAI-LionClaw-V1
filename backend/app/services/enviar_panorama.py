"""Read-only Enviar projection; domain payloads and evaluation motives stay private."""
from dataclasses import asdict, replace
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import case, func, or_, select, text
from app.db.models import AppUser, Celula, CelulaSolicitacao, EnviarAvaliacao, Pessoa, UserRole
from app.deps import CENTRAL_ROLES, resolve_actor_pessoa_id
from app.services.enviar_avaliacoes import _coord
from app.services.enviar_read import ler_pendencias_oficiais


def _scope(db, user):
    tenant = UUID(user.igreja_id)
    if user.has_any_role(CENTRAL_ROLES):
        _coord(db, user)
        return (Pessoa.igreja_id == tenant,), None
    if 'lider_celula' not in user.roles:
        raise HTTPException(403, 'Enviar exige coordenação ou liderança de célula')
    actor = db.execute(select(AppUser).where(AppUser.id == UUID(user.app_user_id),
        AppUser.igreja_id == tenant, or_(AppUser.status == 'ativo', AppUser.status.is_(None)))).scalar_one_or_none()
    role = db.scalar(select(UserRole.id).where(UserRole.user_id == UUID(user.app_user_id),
        UserRole.igreja_id == tenant, UserRole.papel == 'lider_celula').limit(1))
    if actor is None or actor.pessoa_id is None or role is None:
        raise HTTPException(403, 'Acesso à liderança indisponível')
    # Reuse the canonical human visibility (no assigned inbox exception and no
    # expansion from another accumulated role such as formation/consolidation).
    from app.routers.contacts import _contact_scope_conditions
    restricted = replace(user, roles=frozenset({'lider_celula'}))
    person = resolve_actor_pessoa_id(db, restricted)
    return _contact_scope_conditions(db, restricted), UUID(person) if person else None


def _page(db, statement, *, page, page_size):
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery()))
    rows = db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all()
    return rows, dict(page=page, page_size=page_size, total=total)


def listar_pessoas(db, user, *, q='', page=1, page_size=25, grupo='todos'):
    scope, _ = _scope(db, user)
    coordinator = user.has_any_role(CENTRAL_ROLES)
    latest_decision = select(EnviarAvaliacao.decisao).where(
        EnviarAvaliacao.igreja_id == UUID(user.igreja_id), EnviarAvaliacao.pessoa_id == Pessoa.id
    ).order_by(EnviarAvaliacao.criada_em.desc(), EnviarAvaliacao.id.desc()).limit(1).scalar_subquery()
    # Same revocation semantics as the official reader, before pagination/count.
    unrevoked = text("""not (
        exists(select 1 from uv_marcos m where m.igreja_id=pessoas.igreja_id
          and m.pessoa_id=pessoas.id and m.tipo='reencontro' and m.revogada)
        or (exists(select 1 from cd_certificados c where c.igreja_id=pessoas.igreja_id
          and c.pessoa_id=pessoas.id and c.revogada)
          and not exists(select 1 from cd_certificados c where c.igreja_id=pessoas.igreja_id
          and c.pessoa_id=pessoas.id and not c.revogada)))""")
    apt = (Pessoa.apto_lider.is_(True) & Pessoa.sem_interesse.is_(False)
        & unrevoked & Pessoa.arquivada_em.is_(None) & (func.coalesce(latest_decision, '') == 'apto'))
    statement = select(Pessoa).where(*scope, Pessoa.arquivada_em.is_(None))
    if q.strip():
        statement = statement.where(Pessoa.nome.icontains(q.strip(), autoescape=True))
    if grupo == 'aptos':
        statement = statement.where(apt)
    elif grupo == 'pendentes':
        statement = statement.where(~apt)
    people, result = _page(db, statement.order_by(Pessoa.nome, Pessoa.id), page=page, page_size=page_size)
    ids = [p.id for p in people]
    evaluations = db.scalars(select(EnviarAvaliacao).where(
        EnviarAvaliacao.igreja_id == UUID(user.igreja_id), EnviarAvaliacao.pessoa_id.in_(ids)
    ).distinct(EnviarAvaliacao.pessoa_id).order_by(EnviarAvaliacao.pessoa_id,
        EnviarAvaliacao.criada_em.desc(), EnviarAvaliacao.id.desc())).all() if ids else []
    latest = {e.pessoa_id: e for e in evaluations}
    items = []
    for person in people:
        state = ler_pendencias_oficiais(db, person, igreja_id=UUID(user.igreja_id))
        evaluation = latest.get(person.id)
        items.append(dict(id=person.id, nome=person.nome, situacao=state.situacao,
            origem=(evaluation.origem if evaluation else 'legado' if person.apto_lider else None) if coordinator else None,
            apto_lider=bool(person.apto_lider and evaluation and evaluation.decisao == 'apto' and not state.motivo),
            pendencias=[asdict(p) for p in state.pendencias],
            ultima_avaliacao={k:getattr(evaluation,k) for k in ('id','decisao','criada_em','versao_regras')} if coordinator and evaluation else None))
    return result | dict(items=items)


def listar_historico(db, user, *, q='', page=1, page_size=25):
    _, actor = _scope(db, user)
    tenant = UUID(user.igreja_id)
    statement = select(CelulaSolicitacao).where(CelulaSolicitacao.igreja_id == tenant,
        CelulaSolicitacao.tipo.in_(['nomear_lider','abrir_celula','multiplicacao']))
    if not user.has_any_role(CENTRAL_ROLES):
        # Match the existing list/detail authorization for human requests:
        # leaders may read their own requests, never another author's payload/history.
        statement = statement.where(CelulaSolicitacao.solicitante_id == actor)
    if q.strip():
        # Search only public operation type / scoped cell name, never payloads.
        cells = select(Celula.id).where(Celula.igreja_id == tenant,
            Celula.nome.icontains(q.strip(), autoescape=True))
        label = case((CelulaSolicitacao.tipo == 'nomear_lider', 'Nomeação'),
            (CelulaSolicitacao.tipo == 'abrir_celula', 'Abertura'), else_='Multiplicação')
        statement = statement.where(or_(CelulaSolicitacao.tipo.icontains(q.strip(), autoescape=True),
            label.icontains(q.strip(), autoescape=True), CelulaSolicitacao.celula_id.in_(cells)))
    rows, result = _page(db, statement.order_by(CelulaSolicitacao.created_at.desc(), CelulaSolicitacao.id.desc()),
        page=page, page_size=page_size)
    return result | dict(items=[dict(id=r.id,tipo=r.tipo,status=r.status,
        criada_em=r.created_at,decidido_em=r.decidido_em,celula_id=r.celula_id) for r in rows])
