"""Ciclo editorial transacional; caller confirma commit antes de responder.

Edição sempre cria snapshot, inclusive de rascunho. Locks por operação e documento
serializam retries, edição, publicação e revogação. Não executa texto nem URLs.
"""
import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.conhecimento import PUBLICADORES, REVISORES
from app.services.conhecimento import (actor, pode_ler, rows, contexto_leitura,
                                       versoes_legiveis, LEITURA_SQL)


def require(roles,allowed):
    if not roles & allowed:
        raise HTTPException(403,'Sem permissão editorial')


def document(db,t,did):
    found=rows(db,'''select * from conhecimento_documentos
        where igreja_id=:t and id=:d for update''',t=t,d=did)
    if not found:
        raise HTTPException(404,'Documento não encontrado')
    return found[0]


def version(db,t,did,vid):
    found=rows(db,'''select * from conhecimento_versoes
        where igreja_id=:t and documento_id=:d and id=:v for update''',t=t,d=did,v=vid)
    if not found:
        raise HTTPException(404,'Versão não encontrada')
    return found[0]


def require_area(doc,uid):
    if doc['responsavel_id']!=uid:
        raise HTTPException(403,'Operação editorial fora da sua área')


def ack(operation):
    return dict(operacao_id=operation['id'],documento_id=operation['documento_id'],
                versao_id=operation['versao_id'],acao=operation['tipo'])


def executar(db,user,kind,did,payload):
    """Uma operação atômica, com recibo sem conteúdo e sem commit interno."""
    t,uid,roles=actor(db,user)
    require(roles,PUBLICADORES if kind in {'publicar','revogar'} else REVISORES)
    did=UUID(str(did))
    fingerprint=hashlib.sha256(json.dumps(
        dict(acao=kind,documento_id=str(did),payload=payload.model_dump(mode='json')),
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    # Stable integer in PG, scoped by tenant; no document text in locks/logs.
    db.execute(text('select pg_advisory_xact_lock(hashtextextended(:key,0))'),
               dict(key=f'conhecimento:{t}:{payload.operacao_id}'))
    prior=rows(db,'''select * from conhecimento_operacoes
        where igreja_id=:t and id=:id''',t=t,id=payload.operacao_id)
    if prior:
        receipt=prior[0]
        if (receipt['ator_id'],receipt['fingerprint'])!=(uid,fingerprint):
            raise HTTPException(409,'Operação reutilizada com outros dados')
        if not roles & PUBLICADORES:
            require_area(document(db,t,did),uid)
        return ack(receipt)
    try:
        with db.begin_nested():
            if kind=='criar':
                if not roles & PUBLICADORES and payload.responsavel_id!=uid:
                    raise HTTPException(403,'Proposta fora da sua área')
                responsible=rows(db,'''select u.id from app_users u join user_roles r
                    on r.igreja_id=u.igreja_id and r.user_id=u.id
                    where u.igreja_id=:t and u.id=:u and (u.status is null or u.status='ativo')
                    and r.papel::text=any(:roles) for share of u,r''',
                    t=t,u=payload.responsavel_id,roles=sorted(REVISORES))
                if not responsible:
                    raise HTTPException(422,'Responsável editorial indisponível')
                db.execute(text('''insert into conhecimento_documentos
                    (id,igreja_id,titulo,assunto,responsavel_id,autor_id)
                    values(:d,:t,:title,:subject,:r,:u)'''),dict(d=did,t=t,
                    title=payload.titulo,subject=payload.assunto,r=payload.responsavel_id,u=uid))
                doc=document(db,t,did)
                insert_snapshot(db,t,uid,did,payload,None)
            else:
                doc=document(db,t,did)
                if not roles & PUBLICADORES:
                    require_area(doc,uid)
                if kind=='editar':
                    expected=doc['rascunho_id'] or doc['vigente_id']
                    if expected is not None and expected!=payload.anterior_id:
                        raise HTTPException(409,'A versão mudou; atualize o documento')
                    old=version(db,t,did,payload.anterior_id)
                    if expected is not None and old['estado'] not in {'rascunho','em_revisao','publicada'}:
                        raise HTTPException(409,'Versão indisponível para edição')
                    insert_snapshot(db,t,uid,did,payload,payload.anterior_id)
                    if old['estado'] in {'rascunho','em_revisao'}:
                        db.execute(text("""update conhecimento_versoes set estado='substituida'
                            where igreja_id=:t and id=:v"""),dict(t=t,v=old['id']))
                else:
                    current=version(db,t,did,payload.versao_id)
                    apply_action(db,t,uid,roles,kind,doc,current,payload)
            receipt=dict(t=t,id=payload.operacao_id,d=did,v=payload.versao_id,u=uid,k=kind,h=fingerprint)
            db.execute(text('''insert into conhecimento_operacoes
                (igreja_id,id,documento_id,versao_id,ator_id,tipo,fingerprint)
                values(:t,:id,:d,:v,:u,:k,:h)'''),receipt)
            return dict(operacao_id=payload.operacao_id,documento_id=did,versao_id=payload.versao_id,acao=kind)
    except IntegrityError as exc:
        # Avoid leaking conflicting IDs, FK metadata or document text.
        raise HTTPException(409,'Conflito editorial; atualize o documento') from exc


def insert_snapshot(db,t,uid,did,payload,previous):
    db.execute(text('''insert into conhecimento_versoes
        (id,igreja_id,documento_id,anterior_id,conteudo,origem,autor_id,publicos)
        values(:v,:t,:d,:previous,:content,:origin,:u,:audience)'''),
        dict(v=payload.versao_id,t=t,d=did,previous=previous,content=payload.conteudo,
             origin=payload.origem,u=uid,audience=payload.publicos))
    db.execute(text('''update conhecimento_documentos set rascunho_id=:v
        where igreja_id=:t and id=:d'''),dict(t=t,d=did,v=payload.versao_id))


def apply_action(db,t,uid,roles,kind,doc,current,payload):
    vid=current['id']; did=doc['id']
    params=dict(t=t,d=did,v=vid,u=uid)
    if kind=='revogar':
        if current['estado']!='revogada':
            db.execute(text("""update conhecimento_versoes set estado='revogada',
                revogador_id=:u,revogada_em=clock_timestamp() where igreja_id=:t and id=:v"""),params)
        db.execute(text('''update conhecimento_documentos
            set vigente_id=case when vigente_id=:v then null else vigente_id end,
                rascunho_id=case when rascunho_id=:v then null else rascunho_id end
            where igreja_id=:t and id=:d'''),params)
        return
    if doc['rascunho_id']!=vid:
        raise HTTPException(409,'Rascunho mudou; atualize o documento')
    if kind=='enviar-revisao':
        if current['estado'] not in {'rascunho','em_revisao'}:
            raise HTTPException(409,'Versão não pode entrar em revisão')
        db.execute(text("""update conhecimento_versoes set estado='em_revisao'
            where igreja_id=:t and id=:v"""),params)
    elif kind=='revisar':
        if not roles & PUBLICADORES and doc['responsavel_id']!=uid:
            raise HTTPException(403,'Revisão fora da sua área')
        if current['estado']!='em_revisao':
            raise HTTPException(409,'Envie o snapshot para revisão')
        if current['revisada_por'] is None:
            db.execute(text('''update conhecimento_versoes set revisada_por=:u,
                revisada_em=clock_timestamp() where igreja_id=:t and id=:v'''),params)
    elif kind=='publicar':
        if (current['estado']!='em_revisao'
            or sorted(current['publicos'])!=payload.publicos
            or doc['vigente_id']!=payload.vigente_esperada_id):
            raise HTTPException(409,'Aprovação exige snapshot, público e vigência atuais')
        # Retire old version first to satisfy one-publication unique index.
        if doc['vigente_id'] is not None:
            db.execute(text("""update conhecimento_versoes set estado='substituida'
                where igreja_id=:t and documento_id=:d and id=:old"""),
                dict(t=t,d=did,old=doc['vigente_id']))
        db.execute(text("""update conhecimento_versoes set estado='publicada',
            aprovador_id=:u,aprovada_em=clock_timestamp(),publicada_em=clock_timestamp()
            where igreja_id=:t and id=:v"""),params)
        db.execute(text('''update conhecimento_documentos set vigente_id=:v,rascunho_id=null
            where igreja_id=:t and id=:d'''),params)
    else:
        raise HTTPException(422,'Ação editorial desconhecida')


def ler(db,user,vid):
    # No unauthorized title, snippet or count leaves the service.
    if not pode_ler(db,user,vid):
        raise HTTPException(404,'Versão não encontrada')
    t=UUID(user.igreja_id)
    result=rows(db,'''select v.id,v.documento_id,v.conteudo,v.hash,v.origem,v.autor_id,
        v.estado,v.publicos,v.criada_em,v.aprovador_id,v.aprovada_em,v.publicada_em,
        v.revisada_por,v.revisada_em,d.titulo,d.assunto
        from conhecimento_versoes v join conhecimento_documentos d
        on d.igreja_id=v.igreja_id and d.id=v.documento_id
        where v.igreja_id=:t and v.id=:v''',t=t,v=vid)
    # A concurrent revoke between permission and hydration cannot expose content.
    if not result or not pode_ler(db,user,vid):
        raise HTTPException(404,'Versão não encontrada')
    return result[0]


def painel(db, user, pagina=1):
    """Página de metadados autorizados, sem conteúdo e sem consultas por versão.

    Rascunho do pastor só oferece um identificador opaco para envio; título,
    públicos e conteúdo continuam restritos ao admin até entrar em revisão.
    """
    context = contexto_leitura(db, user)
    admin, editor = context['admin'], context['revisor']
    page_size = 20
    candidates = rows(db, f"""with numeradas as (
        select id,igreja_id,documento_id,estado,publicos,criada_em,publicada_em,revisada_em,
            row_number() over (partition by documento_id order by criada_em,id) as numero
        from conhecimento_versoes where igreja_id=:t
        ) select v.*,d.responsavel_id,d.vigente_id,d.rascunho_id,
            vigente.numero as vigente_numero
        from numeradas v join conhecimento_documentos d
            on d.igreja_id=v.igreja_id and d.id=v.documento_id
        left join numeradas vigente on vigente.id=d.vigente_id
        where {LEITURA_SQL} or :admin or
            (:revisor and d.responsavel_id=:uid and
                (v.id=d.rascunho_id or v.publicada_em is not null or v.revisada_em is not null))
        order by v.criada_em desc,v.id desc limit :limite offset :offset""",
        **context, limite=page_size+1, offset=(pagina-1)*page_size)
    more = len(candidates) > page_size
    candidates = candidates[:page_size]
    readable = versoes_legiveis(db, user, [v['id'] for v in candidates])
    documents, pending = {}, []
    for version_row in candidates:
        own = editor and version_row['responsavel_id'] == context['uid']
        editorial = admin or own
        if own and not admin and version_row['estado'] == 'rascunho':
            pending.append(dict(documento_id=version_row['documento_id'], versao_id=version_row['id']))
            continue
        can_read = version_row['id'] in readable
        if not editorial and not can_read:
            continue
        actions = []
        if editorial:
            if version_row['id'] == version_row['rascunho_id']:
                if can_read:
                    actions.append('editar')
                if version_row['estado'] == 'rascunho':
                    actions.append('enviar-revisao')
                if version_row['estado'] == 'em_revisao':
                    if version_row['revisada_em'] is None:
                        actions.append('revisar')
                    if admin:
                        actions.append('publicar')
            elif version_row['id'] == version_row['vigente_id'] and version_row['rascunho_id'] is None:
                actions.append('editar')
            if admin and version_row['estado'] not in {'revogada','substituida'}:
                actions.append('revogar')
        doc = documents.setdefault(version_row['documento_id'], dict(
            id=version_row['documento_id'], vigente_id=version_row['vigente_id'] if editorial else None,
            vigente_numero=version_row['vigente_numero'], versoes=[]))
        fields = ('id','numero','estado','publicos','criada_em','publicada_em','revisada_em')
        doc['versoes'].append(dict({k: version_row[k] for k in fields}, pode_ler=can_read,
            acoes=actions, vigente=version_row['id'] == version_row['vigente_id']))
    # Hydrate labels only after authorization, in one bounded query.
    if documents:
        labels = rows(db, """select id,titulo,assunto from conhecimento_documentos
            where igreja_id=:t and id=any(cast(:ids as uuid[]))""",
            t=context['t'], ids=list(documents))
        for label in labels:
            documents[label['id']].update(titulo=label['titulo'], assunto=label['assunto'])
    for doc in documents.values():
        doc['versoes'].sort(key=lambda v: v['numero'])
    return dict(pode_criar=editor, responsavel_id=context['uid'] if editor else None,
        documentos=list(documents.values()), pendentes=pending, pagina=pagina, tem_mais=more)
