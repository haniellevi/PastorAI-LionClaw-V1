"""Human Enviar decisions. Caller owns commit; every writer locks Pessoa first."""
from dataclasses import asdict
from uuid import UUID, uuid4
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.db.models import AppUser, CelulaSolicitacao, EnviarAvaliacao, Pessoa
from app.deps import CENTRAL_ROLES, CurrentUser
from app.domain.enviar import CRITERIOS_PROVISORIOS, EstadoEvidencia, SituacaoEnviar, VERSAO_REGRAS
from app.services.enviar_read import ler_pendencias_pessoa


def _coord(db, user):
    if not user.has_any_role(CENTRAL_ROLES):
        raise HTTPException(403, 'Ação restrita à Central de Células')
    # Revalidate identity/link from server state, including direct service callers.
    actor = db.execute(select(AppUser).where(AppUser.id == UUID(user.app_user_id),
        AppUser.igreja_id == UUID(user.igreja_id)).execution_options(populate_existing=True)).scalar_one_or_none()
    if actor is None or actor.status not in (None, 'ativo') or not any(r.papel in (*CENTRAL_ROLES, 'admin') for r in actor.roles):
        raise HTTPException(403, 'Acesso à coordenação indisponível')
    return actor


def _pessoa(db, user, pessoa_id, *, lock=False):
    stmt = select(Pessoa).where(Pessoa.id == pessoa_id, Pessoa.igreja_id == UUID(user.igreja_id))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    pessoa = db.execute(stmt).scalar_one_or_none()
    if pessoa is None:
        raise HTTPException(404, 'Pessoa não encontrada')
    return pessoa


def _latest(db, pessoa):
    return db.execute(select(EnviarAvaliacao).where(EnviarAvaliacao.igreja_id == pessoa.igreja_id,
        EnviarAvaliacao.pessoa_id == pessoa.id).order_by(EnviarAvaliacao.criada_em.desc(), EnviarAvaliacao.id.desc()).limit(1)).scalar_one_or_none()


def _snapshot(pessoa):
    result = ler_pendencias_pessoa(pessoa, igreja_id=pessoa.igreja_id)
    states = {p.criterio: p.estado for p in result.pendencias}
    return result, {c: {'estado': states.get(c, EstadoEvidencia.COMPROVADA), 'referencia': None} for c in CRITERIOS_PROVISORIOS}


def _append(db, pessoa, *, id, decisao, origem, motivo, autor_id, solicitacao_id=None, solicitante_id=None):
    _, evidencias = _snapshot(pessoa)
    row = EnviarAvaliacao(id=id, igreja_id=pessoa.igreja_id, pessoa_id=pessoa.id,
        decisao=decisao, origem=origem, motivo=motivo, autor_id=autor_id,
        solicitacao_id=solicitacao_id, solicitante_id=solicitante_id,
        evidencias=evidencias, versao_regras=VERSAO_REGRAS)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as exc:
        raise HTTPException(409, 'ID de decisão já utilizado ou referência indisponível') from exc
    pessoa.apto_lider = decisao == 'apto'
    db.flush()
    return row


def registrar_avaliacao(db: Session, user: CurrentUser, pessoa_id: UUID, payload) -> EnviarAvaliacao:
    actor = _coord(db, user)
    pessoa = _pessoa(db, user, pessoa_id, lock=True)
    if actor.pessoa_id == pessoa.id:
        raise HTTPException(403, 'Não é permitido avaliar a própria aptidão')
    # Do not let omitting the request id bypass segregation. Pending requests
    # targeting this person are discovered from domain records, never client claims.
    own_request = db.execute(select(CelulaSolicitacao.id).where(
        CelulaSolicitacao.igreja_id == pessoa.igreja_id,
        CelulaSolicitacao.status.in_(['aguardando', 'ajuste_solicitado']),
        CelulaSolicitacao.solicitante_id == actor.pessoa_id,
        or_(CelulaSolicitacao.pessoa_id == pessoa.id,
            CelulaSolicitacao.payload_proposto['novo_lider_id'].astext == str(pessoa.id)),
    ).limit(1)).scalar_one_or_none() if actor.pessoa_id else None
    if own_request is not None:
        raise HTTPException(403, 'Autor da solicitação não pode decidir')
    solicitante = None
    if payload.solicitacao_id is not None:
        request = db.execute(select(CelulaSolicitacao).where(CelulaSolicitacao.id == payload.solicitacao_id,
            CelulaSolicitacao.igreja_id == pessoa.igreja_id)).scalar_one_or_none()
        if request is None:
            raise HTTPException(404, 'Solicitação não encontrada')
        solicitante = request.solicitante_id
        if solicitante is not None and actor.pessoa_id == solicitante:
            raise HTTPException(403, 'Autor da solicitação não pode decidir')
        if request.pessoa_id != pessoa.id and request.payload_proposto.get('novo_lider_id') != str(pessoa.id):
            raise HTTPException(422, 'Solicitação não corresponde à pessoa avaliada')
    existing = db.execute(select(EnviarAvaliacao).where(EnviarAvaliacao.igreja_id == pessoa.igreja_id,
        EnviarAvaliacao.id == payload.id)).scalar_one_or_none()
    if existing is not None:
        if any((existing.pessoa_id != pessoa.id, existing.autor_id != actor.id,
            existing.decisao != payload.decisao, existing.origem != payload.origem,
            existing.motivo != payload.motivo, existing.solicitacao_id != payload.solicitacao_id)):
            raise HTTPException(409, 'ID de decisão já utilizado com outro conteúdo')
        return existing  # Never replay a historical projection.
    result, _ = _snapshot(pessoa)
    if pessoa.arquivada_em is not None or pessoa.sem_interesse:
        raise HTTPException(422, 'Pessoa arquivada ou CSIM não pode receber avaliação')
    latest = _latest(db, pessoa)
    legado = pessoa.apto_lider and (latest is None or latest.origem == 'legado')
    if payload.origem == 'legado' and not legado:
        raise HTTPException(422, 'Não há aptidão legada vigente para reconhecer')
    if payload.decisao == 'apto' and result.situacao != SituacaoEnviar.APTO_PARA_AVALIACAO and payload.origem != 'legado':
        raise HTTPException(422, 'Formação pendente: exige evidências oficiais ou reconhecimento motivado do legado')
    return _append(db, pessoa, id=payload.id, decisao=payload.decisao, origem=payload.origem,
        motivo=payload.motivo, autor_id=actor.id, solicitacao_id=payload.solicitacao_id, solicitante_id=solicitante)


def registrar_csim(db, pessoa, user):
    """System consequence of the existing admin PATCH, under its Pessoa lock."""
    return _append(db, pessoa, id=uuid4(), decisao='nao_apto', origem='csim',
        motivo='Aptidão encerrada ao marcar CSIM', autor_id=UUID(user.app_user_id))


def historico_pessoa(db, user, pessoa_id):
    _coord(db, user)
    pessoa = _pessoa(db, user, pessoa_id)
    rows = db.execute(select(EnviarAvaliacao).where(EnviarAvaliacao.igreja_id == pessoa.igreja_id,
        EnviarAvaliacao.pessoa_id == pessoa.id).order_by(EnviarAvaliacao.criada_em.desc(), EnviarAvaliacao.id.desc())).scalars().all()
    pendencias = asdict(ler_pendencias_pessoa(pessoa, igreja_id=pessoa.igreja_id))
    origem = rows[0].origem if rows else 'legado' if pessoa.apto_lider else None
    if origem != 'legado':
        pendencias['aviso_legado'] = None
    return dict(pessoa_id=pessoa.id, nome=pessoa.nome, apto_lider=pessoa.apto_lider,
        origem=origem, pendencias=pendencias, avaliacoes=[avaliacao_out(r) for r in rows])


def avaliacao_out(row):
    return {k: getattr(row,k) for k in ('id','pessoa_id','decisao','origem','motivo','autor_id',
        'solicitacao_id','solicitante_id','evidencias','versao_regras','criada_em')}
