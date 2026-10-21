"""Composição de Hoje: responsabilidade vigente restringe, nunca concede acesso.

Sem Pessoa ativa ou atribuição vigente, não há pendências setoriais. Pastor e
admin mantêm a visão existente. Contexto pessoal/agenda/avisos não é alterado.
"""
from dataclasses import replace
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from app import datas
from app.services.responsabilidades import vigentes_em

TIPO_SETOR = {
    'atendimento': 'atendimento',
    'visitante': 'consolidacao',
    'fonovisita': 'consolidacao',
    'conectar_celula': 'consolidacao',
    'relatorio': 'central_celulas',
}


def escopo_vigente(db, user):
    """Revalida identidade, papéis e Pessoa no tenant a cada leitura, sem cache."""
    tenant, uid = UUID(user.igreja_id), UUID(user.app_user_id)
    actor = db.execute(text('''select u.pessoa_id, p.id as pessoa_ativa
        from app_users u left join pessoas p on p.id=u.pessoa_id
        and p.igreja_id=u.igreja_id and p.arquivada_em is null
        where u.id=:u and u.igreja_id=:t and (u.status is null or u.status='ativo') '''),dict(t=tenant,u=uid)).mappings().first()
    if actor is None:
        raise HTTPException(403, 'Acesso inativo')
    roles = frozenset(db.execute(text('select papel from user_roles where igreja_id=:t and user_id=:u'),dict(t=tenant,u=uid)).scalars())
    fresh = replace(user, roles=roles)
    if roles & {'admin', 'pastor'}:
        return fresh, None
    if actor['pessoa_ativa'] is None:
        return fresh, set()
    sectors = {r['setor'] for r in vigentes_em(db, igreja_id=tenant, em=datas.hoje_da_igreja())
               if r['pessoa_id'] == actor['pessoa_id']}
    return fresh, sectors


def tipos_vigentes(db, user):
    from app.domain.work_queue import resolvable_tipos
    fresh, sectors = escopo_vigente(db, user)
    tipos = resolvable_tipos(fresh.roles)
    if sectors is not None:
        tipos = {tipo for tipo in tipos if TIPO_SETOR.get(tipo) in sectors}
    return fresh, tipos
