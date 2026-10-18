"""CD catalog and turma panel. Callers commit; no agent tools."""
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.cd import CurriculoCD
from app.services.uv import actor as formation_actor, rows, require_coordination, COORDINATION_ROLES, sync_responsaveis


def actor(db, user):
    return formation_actor(db, user, screen='capacitacao')


def require_scope(db, t, uid, roles, turma_id):
    if roles & COORDINATION_ROLES:
        return
    if not rows(db, '''select id from cd_responsaveis where igreja_id=:t
        and turma_id=:id and usuario_id=:u and ativo''', t=t,id=turma_id,u=uid):
        raise HTTPException(404, 'Turma não encontrada')


def turma(db, t, tid, lock=False):
    result = rows(db, '''select id,nome,curriculo_id,modulo_id,encerrada from cd_turmas
        where igreja_id=:t and id=:id''' + (' for update' if lock else ''), t=t,id=tid)
    if not result:
        raise HTTPException(404, 'Turma não encontrada')
    return result[0]


def catalog(db, t, cid, lock=False):
    found = rows(db, 'select id,versao,nome from cd_curriculos where igreja_id=:t and id=:id'
                 + (' for update' if lock else ''), t=t,id=cid)
    if not found:
        raise HTTPException(404, 'Currículo não encontrado')
    result = found[0]
    result['niveis'] = rows(db, 'select id,numero,nome from cd_niveis where igreja_id=:t and curriculo_id=:id order by numero', t=t,id=cid)
    result['modulos'] = rows(db, 'select id,numero,nome,nivel_id from cd_modulos where igreja_id=:t and curriculo_id=:id order by numero', t=t,id=cid)
    for m in result['modulos']:
        m['aulas'] = rows(db, 'select id,numero,nome from cd_aulas where igreja_id=:t and modulo_id=:id order by numero',t=t,id=m['id'])
    return result


def list_curriculos(db, user):
    t, _, roles = actor(db,user)
    require_coordination(roles)
    return [catalog(db,t,r['id']) for r in rows(db,'select id from cd_curriculos where igreja_id=:t order by criada_em,id',t=t)]


def create_curriculo(db,user,payload):
    t,uid,roles=actor(db,user)
    require_coordination(roles)
    # Structural edits are new versions. Labels remain editable in every version.
    CurriculoCD(payload.versao, tuple(payload.aulas_por_modulo), tuple(tuple(n.modulos) for n in payload.niveis))
    try:
        with db.begin_nested():
            inserted=db.execute(text('''insert into cd_curriculos(id,igreja_id,versao,nome,criada_por)
                values(:id,:t,:v,:n,:u) on conflict(id) do nothing returning id'''),
                dict(id=payload.id,t=t,v=payload.versao,n=payload.nome,u=uid)).scalar_one_or_none()
            if inserted is not None:
                levels={}
                for i,n in enumerate(payload.niveis,1):
                    nid=rows(db,'''insert into cd_niveis(igreja_id,curriculo_id,numero,nome)
                        values(:t,:c,:i,:n) returning id''',t=t,c=payload.id,i=i,n=n.nome)[0]['id']
                    levels.update({number:nid for number in n.modulos})
                for i,count in enumerate(payload.aulas_por_modulo,1):
                    mid=rows(db,'''insert into cd_modulos(igreja_id,curriculo_id,nivel_id,numero,nome)
                        values(:t,:c,:l,:i,:n) returning id''',t=t,c=payload.id,l=levels.get(i),i=i,n=f'Módulo {i}')[0]['id']
                    for a in range(1,count+1):
                        db.execute(text('''insert into cd_aulas(igreja_id,modulo_id,numero,nome)
                            values(:t,:m,:a,:n)'''),dict(t=t,m=mid,a=a,n=f'Aula {a}'))
            if not rows(db, 'select id from cd_curriculos where igreja_id=:t and id=:id',t=t,id=payload.id):
                raise HTTPException(409,'Identificador de currículo indisponível')
            result=catalog(db,t,payload.id,lock=True)
            actual=[(n['nome'],[m['numero'] for m in result['modulos'] if m['nivel_id']==n['id']]) for n in result['niveis']]
            expected=[(n.nome,sorted(n.modulos)) for n in payload.niveis]
            counts=[len(m['aulas']) for m in result['modulos']]
            if (result['versao'],result['nome'],actual,counts)!=(payload.versao,payload.nome,expected,payload.aulas_por_modulo):
                raise HTTPException(409,'Identificador reutilizado com outros dados')
            return result
    except IntegrityError as exc:
        raise HTTPException(409,'Versão ou identificador indisponível') from exc


def rename_catalog(db,user,cid,kind,record_id,payload):
    t,_,roles=actor(db,user); require_coordination(roles)
    current=catalog(db,t,cid,lock=True)
    targets={'curriculo':[(cid,'cd_curriculos')], 'nivel':[(r['id'],'cd_niveis') for r in current['niveis']],
             'modulo':[(r['id'],'cd_modulos') for r in current['modulos']],
             'aula':[(a['id'],'cd_aulas') for m in current['modulos'] for a in m['aulas']]}
    table=next((table for rid,table in targets.get(kind,[]) if rid==record_id),None)
    if table is None: raise HTTPException(404,'Registro não encontrado neste currículo')
    db.execute(text(f'update {table} set nome=:n where igreja_id=:t and id=:id'),dict(n=payload.nome,t=t,id=record_id))
    return catalog(db,t,cid)


def list_turmas(db,user):
    t,uid,roles=actor(db,user)
    return rows(db,'''select id,nome,curriculo_id,modulo_id,encerrada from cd_turmas t where igreja_id=:t
        and (:coord or exists(select 1 from cd_responsaveis r where r.igreja_id=t.igreja_id
        and r.turma_id=t.id and r.usuario_id=:u and r.ativo)) order by criada_em,id''',
        t=t,u=uid,coord=bool(roles & COORDINATION_ROLES))


def create_turma(db,user,payload):
    t,uid,roles=actor(db,user); require_coordination(roles)
    # Validate the module against the requested version even with BYPASSRLS.
    if not rows(db,'''select m.id from cd_modulos m join cd_curriculos c on c.igreja_id=m.igreja_id and c.id=m.curriculo_id
        where m.igreja_id=:t and m.id=:m and c.id=:c for share of c,m''',t=t,m=payload.modulo_id,c=payload.curriculo_id):
        raise HTTPException(409,'Módulo e versão do currículo divergentes')
    try:
        with db.begin_nested():
            db.execute(text('''insert into cd_turmas(id,igreja_id,curriculo_id,modulo_id,nome,criada_por)
                values(:id,:t,:c,:m,:n,:u) on conflict(id) do nothing'''),
                dict(id=payload.id,t=t,c=payload.curriculo_id,m=payload.modulo_id,n=payload.nome,u=uid))
            if not rows(db, 'select id from cd_turmas where igreja_id=:t and id=:id',t=t,id=payload.id):
                raise HTTPException(409,'Identificador de turma indisponível')
            result=turma(db,t,payload.id,True)
            if (result['curriculo_id'],result['modulo_id'],result['nome'])!=(payload.curriculo_id,payload.modulo_id,payload.nome):
                raise HTTPException(409,'Identificador reutilizado com outros dados')
            return result
    except IntegrityError as exc:
        raise HTTPException(409,'Identificador de turma indisponível') from exc


def get_turma(db,user,tid):
    t,uid,roles=actor(db,user)
    require_scope(db,t,uid,roles,tid); result=turma(db,t,tid)
    current=catalog(db,t,result['curriculo_id'])
    result['versao']=current['versao']
    result['modulo']=next(m for m in current['modulos'] if m['id']==result['modulo_id'])
    result['calendario']=rows(db,'select aula_id,data from cd_calendario where igreja_id=:t and turma_id=:id order by data,aula_id',t=t,id=tid)
    result['responsaveis']=rows(db,'''select r.usuario_id,coalesce(p.nome,u.nome,'Usuário da equipe') as nome,
        (u.status='ativo' and exists(select 1 from user_roles ur where ur.igreja_id=u.igreja_id
        and ur.user_id=u.id and ur.papel in ('admin','pastor','lider_consol'))) as elegivel
        from cd_responsaveis r join app_users u on u.igreja_id=r.igreja_id and u.id=r.usuario_id
        left join pessoas p on p.igreja_id=u.igreja_id and p.id=u.pessoa_id
        where r.igreja_id=:t and r.turma_id=:id and r.ativo order by r.id''',t=t,id=tid)
    return result


def writable(db,user,tid):
    t,uid,roles=actor(db,user); require_coordination(roles)
    current=turma(db,t,tid,True); require_scope(db,t,uid,roles,tid)
    if current['encerrada']: raise HTTPException(409,'Turma encerrada')
    return t,uid,current


def rename_turma(db,user,tid,payload):
    t,_,_=writable(db,user,tid)
    db.execute(text('update cd_turmas set nome=:n where igreja_id=:t and id=:id'),dict(t=t,id=tid,n=payload.nome))
    return get_turma(db,user,tid)


def calendar(db,user,tid,payload):
    t,uid,current=writable(db,user,tid)
    lessons=rows(db,'select id,numero from cd_aulas where igreja_id=:t and modulo_id=:m order by numero',t=t,m=current['modulo_id'])
    dates={a.aula_id:a.data for a in payload.aulas}
    if set(dates)!={a['id'] for a in lessons}: raise HTTPException(422,'Calendário exige todas as aulas deste módulo')
    ordered=[dates[a['id']] for a in lessons]
    if ordered!=sorted(ordered): raise HTTPException(422,'Datas devem seguir a ordem das aulas')
    try:
        with db.begin_nested():
            for a in payload.aulas:
                db.execute(text('''insert into cd_calendario(igreja_id,turma_id,modulo_id,aula_id,data,criada_por,atualizada_por)
                    values(:t,:id,:m,:a,:d,:u,:u) on conflict(igreja_id,turma_id,aula_id) do update
                    set data=excluded.data,atualizada_por=excluded.atualizada_por,atualizada_em=clock_timestamp()'''),
                    dict(t=t,id=tid,m=current['modulo_id'],a=a.aula_id,d=a.data,u=uid))
    except IntegrityError as exc: raise HTTPException(409,'Calendário conflitante') from exc
    return get_turma(db,user,tid)


def responsaveis(db,user,tid,payload):
    t,uid,_=writable(db,user,tid)
    # Lock both live account and matching roles, just as the actor check does.
    for target in sorted(payload.usuarios,key=str):
        if not rows(db,'''select u.id from app_users u join user_roles r on r.igreja_id=u.igreja_id and r.user_id=u.id
            where u.igreja_id=:t and u.id=:u and u.status='ativo'
            and r.papel in ('admin','pastor','lider_consol') for share of u,r''',t=t,u=target):
            raise HTTPException(422,'Responsável deve ser usuário ativo e autorizado da igreja')
    sync_responsaveis(db,t,uid,tid,payload.usuarios,table='cd_responsaveis')
    return {'status':'salvo'}


def close(db,user,tid,*,reopen=False):
    t,uid,roles=actor(db,user); require_coordination(roles)
    turma(db,t,tid,True)
    fields='reaberta_por=:u,reaberta_em=clock_timestamp()' if reopen else 'encerrada_por=:u,encerrada_em=clock_timestamp()'
    db.execute(text(f'''update cd_turmas set encerrada=:closed,{fields}
        where igreja_id=:t and id=:id and encerrada<>:closed'''),dict(t=t,id=tid,u=uid,closed=not reopen))
    return {'status':'reaberta' if reopen else 'encerrada'}


def options(db,user):
    t,_,roles=actor(db,user); require_coordination(roles)
    return rows(db,'''select u.id,coalesce(p.nome,u.nome,'Usuário da equipe') as nome from app_users u
        left join pessoas p on p.igreja_id=u.igreja_id and p.id=u.pessoa_id
        where u.igreja_id=:t and u.status='ativo' and exists(select 1 from user_roles r
        where r.igreja_id=u.igreja_id and r.user_id=u.id and r.papel in ('admin','pastor','lider_consol'))
        order by nome,u.id limit 100''',t=t)


def enrollment_scope(db, user, tid, *, lock=False):
    t, uid, roles = actor(db, user)
    # Hide existing and missing out-of-scope turmas alike before acquiring locks.
    require_scope(db, t, uid, roles, tid)
    current = turma(db, t, tid, lock)
    # Responsible edits and closure also lock the turma. Recheck after waiting.
    require_scope(db, t, uid, roles, tid)
    return t, uid, current


def require_first_module(db, t, current):
    """PR 5 extension: validate recorded prior completions in this curriculum.

    Until completions/equivalences exist, only the first ordered module is safe.
    """
    first = rows(db, '''select id,numero from cd_modulos where igreja_id=:t
        and curriculo_id=:c order by numero limit 1''', t=t, c=current['curriculo_id'])[0]
    if first['id'] != current['modulo_id']:
        raise HTTPException(409, 'Módulo exige pré-requisito: conclusão registrada dos módulos anteriores')
    return first['numero']


def list_enrollments(db, user, tid):
    t, _, _ = enrollment_scope(db, user, tid)
    return rows(db, '''select m.id,m.pessoa_id,p.nome,(p.arquivada_em is not null) as pessoa_arquivada,m.ativa,m.origem_aptidao,
        m.criada_por,m.criada_em,m.cancelada_por,m.cancelada_em
        from cd_matriculas m join pessoas p on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
        where m.igreja_id=:t and m.turma_id=:tid
        order by p.nome,m.id''', t=t, tid=tid)


def eligible(db, user, tid, *, q="", limit=100, offset=0):
    t, _, current = enrollment_scope(db, user, tid)
    if current['encerrada']:
        return []
    numero = require_first_module(db, t, current)
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, 'Paginação inválida')
    pattern = '%' + q.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
    return rows(db, '''select p.id,p.nome from pessoas p where p.igreja_id=:t
        and p.arquivada_em is null and p.apto_proxima_cd
        and p.nome ilike :q escape '!'
        and p.origem_aptidao_cd in ('legado','conclusao_uv')
        and not exists(select 1 from cd_matriculas m where m.igreja_id=p.igreja_id
            and m.pessoa_id=p.id and m.modulo_numero=:n and m.ativa)
        order by p.nome,p.id limit :limit offset :offset''', t=t, n=numero, q=pattern, limit=limit, offset=offset)


def enroll(db, user, tid, payload):
    t, uid, current = enrollment_scope(db, user, tid, lock=True)
    if current['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    numero = require_first_module(db, t, current)
    people = rows(db, '''select id,apto_proxima_cd,origem_aptidao_cd from pessoas
        where igreja_id=:t and id=:p and arquivada_em is null for update''', t=t, p=payload.pessoa_id)
    if not people:
        raise HTTPException(404, 'Pessoa não encontrada')
    person = people[0]
    if not person['apto_proxima_cd'] or person['origem_aptidao_cd'] not in {'legado','conclusao_uv'}:
        raise HTTPException(422, 'Matrícula exige aptidão à CD com origem identificada')
    params = dict(t=t, tid=tid, p=payload.pessoa_id, id=payload.id, u=uid,
                  m=current['modulo_id'], n=numero, origem=person['origem_aptidao_cd'])
    existing = rows(db, 'select id,turma_id,pessoa_id,ativa from cd_matriculas where igreja_id=:t and id=:id', **params)
    if existing and (existing[0]['turma_id'], existing[0]['pessoa_id']) != (tid, payload.pessoa_id):
        raise HTTPException(409, 'Identificador reutilizado com outros dados')
    active = rows(db, '''select id from cd_matriculas where igreja_id=:t
        and pessoa_id=:p and modulo_numero=:n and ativa''', **params)
    if active:
        if existing and active[0]['id'] == payload.id:
            return {'id': payload.id}  # Retry of the same explicit request.
        raise HTTPException(409, 'Pessoa já possui matrícula ativa neste módulo')
    previous = rows(db, '''select id from cd_matriculas where igreja_id=:t
        and turma_id=:tid and pessoa_id=:p''', **params)
    if previous and previous[0]['id'] != payload.id:
        raise HTTPException(409, 'Reativação exige o identificador da matrícula existente')
    try:
        with db.begin_nested():
            if previous:
                # Same turma retains its identity; reactivation requires current eligibility.
                params['previous'] = previous[0]['id']
                db.execute(text('''update cd_matriculas set ativa=true,origem_aptidao=:origem,
                    criada_por=:u,criada_em=clock_timestamp(),cancelada_por=null,cancelada_em=null
                    where igreja_id=:t and id=:previous'''), params)
                return {'id': previous[0]['id']}
            return rows(db, '''insert into cd_matriculas(id,igreja_id,turma_id,modulo_id,modulo_numero,
                pessoa_id,origem_aptidao,criada_por) values(:id,:t,:tid,:m,:n,:p,:origem,:u)
                returning id''', **params)[0]
    except IntegrityError as exc:
        raise HTTPException(409, 'Matrícula ou identificador indisponível') from exc


def cancel_enrollment(db, user, tid, mid):
    t, uid, current = enrollment_scope(db, user, tid, lock=True)
    if current['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    found = rows(db, 'select pessoa_id from cd_matriculas where igreja_id=:t and turma_id=:tid and id=:mid', t=t, tid=tid, mid=mid)
    if not found:
        raise HTTPException(404, 'Matrícula não encontrada')
    rows(db, 'select id from pessoas where igreja_id=:t and id=:p for update', t=t, p=found[0]['pessoa_id'])
    db.execute(text('''update cd_matriculas set ativa=false,cancelada_por=:u,cancelada_em=clock_timestamp()
        where igreja_id=:t and turma_id=:tid and id=:mid and ativa'''), dict(t=t, tid=tid, mid=mid, u=uid))
    return {'status': 'cancelada'}
