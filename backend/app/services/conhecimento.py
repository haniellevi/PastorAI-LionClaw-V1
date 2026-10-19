"""Autorização de conhecimento oficial, compartilhada por futuros callers.

Visitante recebe igreja resolvida pelo servidor; nunca aceitar tenant do modelo.
Públicos pertencem ao snapshot, não a claims/cache. Sem busca nesta fatia.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text

from app.deps import CurrentUser
from app.domain.conhecimento import PUBLICO_VISITANTE, REVISORES, TIPO_PESSOA_MEMBRO


@dataclass(frozen=True)
class Visitante:
    igreja_id: UUID


def rows(db, sql, **params):
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def actor(db, user):
    """Revalida acesso e papéis; claims do CurrentUser não concedem privilégios."""
    t, uid = UUID(user.igreja_id), UUID(user.app_user_id)
    found = rows(db, """select u.id from app_users u
        where u.igreja_id=:t and u.id=:u and (u.status is null or u.status='ativo') for share""", t=t,u=uid)
    if not found:
        raise HTTPException(403, 'Acesso indisponível')
    roles = {r['papel'] for r in rows(db, '''select papel from user_roles
        where igreja_id=:t and user_id=:u for share''', t=t,u=uid)}
    return t, uid, roles


def pode_ler(db, usuario: CurrentUser | Visitante, versao: UUID) -> bool:
    """Negação padrão; reconsultar imediatamente antes de cada entrega."""
    t = UUID(str(usuario.igreja_id))
    versao = UUID(str(versao))
    found = rows(db, '''select v.estado,v.publicos,d.vigente_id,d.responsavel_id
        from conhecimento_versoes v join conhecimento_documentos d
        on d.igreja_id=v.igreja_id and d.id=v.documento_id
        where v.igreja_id=:t and v.id=:v''', t=t,v=versao)
    if not found:
        return False
    version = found[0]
    if isinstance(usuario, Visitante):
        return (version['estado']=='publicada' and version['vigente_id']==versao
                and PUBLICO_VISITANTE in version['publicos'])
    try:
        _, uid, roles = actor(db, usuario)
    except HTTPException:
        return False
    if version['estado'] in {'rascunho', 'em_revisao'}:
        return ('admin' in roles or (version['estado']=='em_revisao'
            and bool(roles & REVISORES) and uid==version['responsavel_id']))
    if version['estado']!='publicada' or version['vigente_id']!=versao:
        return False
    audience = set(version['publicos'])
    # Pessoa, acesso e papel são distintos. Público membros exige vínculo vivo,
    # não a mera atribuição do papel "membro" ao usuário do painel.
    member = bool('membros' in audience and rows(db, """select p.id
        from app_users u join pessoas p on p.igreja_id=u.igreja_id and p.id=u.pessoa_id
        where u.igreja_id=:t and u.id=:u and p.tipo=:tipo
          and p.arquivada_em is null for share of u,p""",
        t=t,u=uid,tipo=TIPO_PESSOA_MEMBRO))
    return (PUBLICO_VISITANTE in audience
            or member
            or any('papel:'+role in audience for role in roles))
