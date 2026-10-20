"""Minimal Enviar projections using the same visibility and writers as the panel."""
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy import select
from app.db.models import AppUser, UserRole, Pessoa, Celula
from app.deps import CurrentUser
from app.services import enviar_panorama
from app.prayer.catalog import normalized
from app.services.agent_privilege_catalog import _label as label


def actor(db, contact):
    users = db.scalars(select(AppUser).where(AppUser.igreja_id == contact.igreja_id,
        AppUser.pessoa_id == contact.pessoa_id, AppUser.status == 'ativo')).all()
    if len(users) != 1:
        raise HTTPException(403, 'Remetente sem usuário ativo único')
    roles = db.scalars(select(UserRole.papel).where(UserRole.igreja_id == contact.igreja_id,
        UserRole.user_id == users[0].id)).all()
    user = CurrentUser(app_user_id=str(users[0].id), igreja_id=str(contact.igreja_id),
        clerk_user_id='', email='', nome='', roles=frozenset(roles))
    enviar_panorama._scope(db, user)
    return user


def choose(items, name):
    found = [r for r in items if ' '.join(normalized(r['nome']).split()) == ' '.join(normalized(name).split())]
    if len(found) != 1:
        raise HTTPException(422, 'Nome não encontrado ou ambíguo. Consulte o painel')
    return found[0]


def person(db, user, name):
    scope, _ = enviar_panorama._scope(db, user)
    rows = db.scalars(select(Pessoa).where(*scope, Pessoa.arquivada_em.is_(None))).all()
    return choose([dict(id=r.id, nome=r.nome) for r in rows], name)


def cell(db, user, name):
    from app.deps import CENTRAL_ROLES
    _, actor_id = enviar_panorama._scope(db, user)
    stmt = select(Celula).where(Celula.igreja_id == UUID(user.igreja_id), Celula.ativo.is_(True))
    if not user.has_any_role(CENTRAL_ROLES):
        stmt = stmt.where(Celula.lider_id == actor_id)
    return choose([dict(id=r.id, nome=r.nome) for r in db.scalars(stmt)], name)


def request_visible(db, user, request_id):
    from app.routers.cell_requests import get_cell_request
    return get_cell_request(str(request_id), db=db, current_user=user)


def read(db, user, command, args):
    if command == 'history':
        result = enviar_panorama.listar_historico(db, user, page_size=25)
        notice = '\nHá mais resultados, use o painel.' if result['total'] > 25 else ''
        return 'Solicitações Enviar:\n' + ('\n'.join(f"{r['id']}: {r['tipo']} — {r['status']}" for r in result['items']) or 'Nenhuma.') + notice
    target = person(db, user, args) if command == 'read' else None
    result = enviar_panorama.listar_pessoas(db, user, q=target['nome'] if target else '', page_size=25)
    items = [r for r in result['items'] if not target or r['id'] == target['id']]
    # A targeted exact match must never silently disappear at a pagination boundary.
    if target and not items:
        raise HTTPException(422, 'Consulta ampla. Consulte o painel')
    lines = ['Enviar: pendências e estado (até 25 pessoas).']
    for r in items:
        pending = '; '.join(p['descricao'] for p in r['pendencias']) or 'evidências comprovadas'
        lines.append(f"{label(r['nome'])}: aptidão {'confirmada' if r['apto_lider'] else 'pendente'}; {pending}.")
    if result['total'] > 25:
        lines.append('Há mais resultados, use o painel.')
    lines.append('Avaliação humana e aprovação de operações exigem o painel autenticado.')
    return '\n'.join(lines)


def validate_targets(db, user, tool):
    # Resolve visibility again on SIM, independently of server-stored proposal data.
    scope, _ = enviar_panorama._scope(db, user)
    if db.scalar(select(Pessoa.id).where(*scope, Pessoa.id == tool.payload.novo_lider_id,
        Pessoa.arquivada_em.is_(None))) is None:
        raise HTTPException(403, 'Candidato indisponível')


def propose(db, user, command, args):
    from app.enviar_whatsapp.catalog import RequestTool, execute
    from app.domain.cell_requests import NomearLiderPayload, AbrirCelulaPayload
    if command == 'nominate':
        cell_name, candidate_name = args
        target = person(db, user, candidate_name)
        origin = cell(db, user, cell_name)
        tool = RequestTool(tipo='nomear_lider', celula_id=origin['id'],
            payload=NomearLiderPayload(novo_lider_id=target['id']))
        description = f"Nomeação solicitada para {label(origin['nome'])}: {label(target['nome'])}."
    else:
        name, coverage, candidate_name = args
        target = person(db, user, candidate_name)
        tool = RequestTool(tipo='abrir_celula', payload=AbrirCelulaPayload(nome=name,
            cobertura_espiritual=coverage, novo_lider_id=target['id']))
        description = f"Abertura solicitada de {label(name)}, cobertura {label(coverage)}: {label(target['nome'])}."
    proposal = tool.model_dump(mode='json')
    savepoint = db.begin_nested()
    try:
        execute(db, user, proposal)
    finally:
        savepoint.rollback()
    return (description + ' Apenas registra solicitação; aguarda pastor/admin distinto do autor e candidato no painel autenticado. '
        'Confirma registrar? Responda somente SIM ou NÃO em até 10 minutos.'), proposal
