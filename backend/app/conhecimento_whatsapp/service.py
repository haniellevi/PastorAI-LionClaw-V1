"""Resolve trusted contact, then reuse human live audience/role authorization."""
import re
from sqlalchemy import select
from fastapi import HTTPException
from pydantic import ValidationError
from app.db.models import AppUser
from app.deps import CurrentUser
from app.services import conhecimento
from app.conhecimento_whatsapp import catalog

GAP='Não encontrei informação oficial vigente e autorizada para esta consulta. Vou encaminhar a conversa para atendimento humano.'
DENIED='Sem permissão para consultar o conhecimento oficial com este acesso. Procure a equipe pelo painel ou atendimento humano.'


def citation_text(value):
    # Keep each untrusted field on one line and reserve the source label.
    return re.sub(r'fonte\s*:', 'Fonte (citada):', ' '.join(value.split()), flags=re.IGNORECASE)


def source_versions(db, usuario, results):
    context = conhecimento.contexto_leitura(db, usuario)
    return {str(r['id']): r for r in conhecimento.rows(db, f"""
        with legiveis as (
            select v.id,v.documento_id,
                row_number() over (partition by v.documento_id order by v.criada_em,v.id) as numero
            from conhecimento_versoes v join conhecimento_documentos d
                on d.igreja_id=v.igreja_id and d.id=v.documento_id
            where v.igreja_id=:t and {conhecimento.LEITURA_SQL}
        ) select * from legiveis where id=any(cast(:ids as uuid[]))
        """, **context, ids=[str(r['versao_id']) for r in results])}


def actor(db,contact):
    users=db.scalars(select(AppUser).where(AppUser.igreja_id==contact.igreja_id,
        AppUser.pessoa_id==contact.pessoa_id).with_for_update(of=AppUser)).all()
    if not users:
        return conhecimento.Visitante(contact.igreja_id)
    if len(users)!=1 or users[0].status not in {None,'ativo'}:
        raise HTTPException(403,'Acesso indisponível')
    user=CurrentUser(app_user_id=str(users[0].id),igreja_id=str(contact.igreja_id),
        clerk_user_id='',email='',nome='',roles=frozenset())
    conhecimento.actor(db,user)
    return user


def resolve(db,contact,source):
    from app.agent.nodes import route_conhecimento_intent
    command,query=route_conhecimento_intent(source.texto or '')
    try:
        usuario=actor(db,contact)
        identity=usuario.app_user_id if isinstance(usuario,CurrentUser) else None
        if command!='search': return catalog.HELP,dict(stage='help',actor_id=identity)
        tool=catalog.SearchTool(consulta=query)
        results=catalog.execute(db,usuario,tool)
        if not results: return GAP,dict(stage='handoff',actor_id=identity)
        versions=source_versions(db,usuario,results)
        results=[r for r in results if str(r['versao_id']) in versions]
        if not results: return GAP,dict(stage='handoff',actor_id=identity)
        sources=[dict(documento_id=str(versions[str(r['versao_id'])]['documento_id']),
                      versao_id=str(r['versao_id'])) for r in results]
        # Bounded quotations with normalized whitespace/source labels. Never send retrieved text to an LLM,
        # never interpret it as instruction or promote conversations to sources.
        response='Trechos oficiais vigentes:\n\n'+'\n\n'.join(
            f'“{citation_text(r["trecho"])}”\nFonte: {citation_text(r["titulo"])} · versão {versions[str(r["versao_id"])]["numero"]} · {citation_text(r["secao"])}' for r in results)
        return response,dict(stage='result',actor_id=identity,fontes=sources)
    except ValidationError:
        return 'Consulta inválida. Informe de 1 a 200 caracteres sem controles.',dict(stage='invalid',actor_id=None)
    except HTTPException as exc:
        if exc.status_code in {403,404}: return DENIED,dict(stage='denied',actor_id=None)
        raise
