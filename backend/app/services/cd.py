"""CD panel domain services. Callers commit; no agent tools."""
from fastapi import HTTPException
from app.services.formation_errors import AttendanceChanged
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.cd import CurriculoCD, modulo_cumprido, evidencia_equivalencia, validar_origem_equivalencia, EXIGIR_CONFIRMACAO_MODULO, PROGRESSAO_LINEAR
from app.services.uv import actor as formation_actor, rows, require_coordination, COORDINATION_ROLES, sync_responsaveis, today_sao_paulo


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
    found = rows(db, 'select id,versao,nome,familia_id from cd_curriculos where igreja_id=:t and id=:id'
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
    source = getattr(payload, 'curriculo_anterior_id', None)
    family = catalog(db,t,source)['familia_id'] if source else payload.id
    try:
        with db.begin_nested():
            inserted=db.execute(text('''insert into cd_curriculos(id,igreja_id,versao,nome,criada_por,familia_id)
                values(:id,:t,:v,:n,:u,:f) on conflict do nothing returning id'''),
                dict(id=payload.id,t=t,v=payload.versao,n=payload.nome,u=uid,f=family)).scalar_one_or_none()
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
                raise HTTPException(409,'Versão ou identificador indisponível')
            result=catalog(db,t,payload.id,lock=True)
            actual=[(n['nome'],[m['numero'] for m in result['modulos'] if m['nivel_id']==n['id']]) for n in result['niveis']]
            expected=[(n.nome,sorted(n.modulos)) for n in payload.niveis]
            counts=[len(m['aulas']) for m in result['modulos']]
            if result['familia_id'] != family:
                raise HTTPException(409,'Identificador reutilizado com outra família')
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
    # The turma lock also serializes attendance. Never strand a recorded
    # revision behind the future-date guard, including an absence to correct.
    today = today_sao_paulo()
    for lesson in payload.aulas:
        if lesson.data > today and rows(db, """select id from cd_presencas
            where igreja_id=:t and turma_id=:tid and aula_id=:a limit 1""",
            t=t, tid=tid, a=lesson.aula_id):
            raise HTTPException(409, 'Aula com frequência registrada não pode ser movida para o futuro')
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


def module_number(db, t, current):
    return rows(db, 'select numero from cd_modulos where igreja_id=:t and id=:m',
                t=t, m=current['modulo_id'])[0]['numero']


def require_prerequisites(db, t, current, person):
    # Keep prerequisite evidence stable until the enrollment/completion commits,
    # including a concurrent privileged revocation of an equivalence source.
    rows(db,"""select id from cd_conclusoes where igreja_id=:t and pessoa_id=:p
        order by id for share""",t=t,p=person)
    if PROGRESSAO_LINEAR and rows(db, """select m.id from cd_modulos m
        where m.igreja_id=:t and m.curriculo_id=:c and m.numero<:n
        and not exists(select 1 from cd_cumprimentos f where f.igreja_id=m.igreja_id
          and f.modulo_id=m.id and f.pessoa_id=:p and f.curriculo_id=:c)""",
        t=t, c=current['curriculo_id'], n=module_number(db,t,current), p=person):
        raise HTTPException(409, 'Módulo exige pré-requisito: conclusão registrada dos módulos anteriores')


def require_unfinished(db, t, mid):
    if rows(db, 'select id from cd_conclusoes where igreja_id=:t and matricula_id=:mid', t=t,mid=mid):
        raise HTTPException(409, 'Matrícula concluída')


def list_enrollments(db, user, tid):
    t, _, _ = enrollment_scope(db, user, tid)
    result = rows(db, '''select m.id,m.pessoa_id,p.nome,(p.arquivada_em is not null) as pessoa_arquivada,m.ativa,m.origem_aptidao,
        m.criada_por,m.criada_em,m.cancelada_por,m.cancelada_em
        from cd_matriculas m join pessoas p on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
        where m.igreja_id=:t and m.turma_id=:tid
        order by p.nome,m.id''', t=t, tid=tid)
    _, _, roles = actor(db, user)
    columns = 'id,matricula_id,origem,confirmada_por,confirmada_em'
    if roles & COORDINATION_ROLES:
        columns += ',evidencia,origem_equivalencia'
    completions = {r['matricula_id']: r for r in rows(db,
        f'select {columns} from cd_conclusoes where igreja_id=:t and turma_id=:tid', t=t,tid=tid)}
    for m in result:
        m['conclusao'] = completions.get(m['id'])
    return result


def eligible(db, user, tid, *, q="", limit=100, offset=0):
    t, _, current = enrollment_scope(db, user, tid)
    if current['encerrada']:
        return []
    numero = module_number(db, t, current)
    if not 1 <= limit <= 100 or offset < 0:
        raise HTTPException(422, 'Paginação inválida')
    pattern = '%' + q.strip().replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
    return rows(db, '''select p.id,p.nome from pessoas p where p.igreja_id=:t
        and p.arquivada_em is null and p.apto_proxima_cd
        and p.nome ilike :q escape '!'
        and p.origem_aptidao_cd in ('legado','conclusao_uv')
        and not exists(select 1 from cd_cumprimentos f where f.igreja_id=p.igreja_id
            and f.pessoa_id=p.id and f.curriculo_id=:c and f.modulo_id=:mod)
        and (not :linear or not exists(select 1 from cd_modulos prior
            where prior.igreja_id=p.igreja_id and prior.curriculo_id=:c and prior.numero<:n
            and not exists(select 1 from cd_cumprimentos f where f.igreja_id=prior.igreja_id
                and f.pessoa_id=p.id and f.curriculo_id=:c and f.modulo_id=prior.id)))
        and not exists(select 1 from cd_matriculas m where m.igreja_id=p.igreja_id
            and m.pessoa_id=p.id and m.modulo_numero=:n and m.ativa and not m.concluida)
        order by p.nome,p.id limit :limit offset :offset''', t=t, n=numero, c=current['curriculo_id'], mod=current['modulo_id'], linear=PROGRESSAO_LINEAR, q=pattern, limit=limit, offset=offset)


def enroll(db, user, tid, payload):
    t, uid, current = enrollment_scope(db, user, tid, lock=True)
    if current['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    numero = module_number(db, t, current)
    people = rows(db, '''select id,apto_proxima_cd,origem_aptidao_cd from pessoas
        where igreja_id=:t and id=:p and arquivada_em is null for update''', t=t, p=payload.pessoa_id)
    if not people:
        raise HTTPException(404, 'Pessoa não encontrada')
    person = people[0]
    require_prerequisites(db,t,current,payload.pessoa_id)
    if rows(db, '''select id from cd_cumprimentos where igreja_id=:t and pessoa_id=:p
        and curriculo_id=:c and modulo_id=:m''',t=t,p=payload.pessoa_id,c=current['curriculo_id'],m=current['modulo_id']):
        raise HTTPException(409, 'Módulo já concluído neste currículo')
    if not person['apto_proxima_cd'] or person['origem_aptidao_cd'] not in {'legado','conclusao_uv'}:
        raise HTTPException(422, 'Matrícula exige aptidão à CD com origem identificada')
    params = dict(t=t, tid=tid, p=payload.pessoa_id, id=payload.id, u=uid,
                  m=current['modulo_id'], n=numero, origem=person['origem_aptidao_cd'])
    existing = rows(db, 'select id,turma_id,pessoa_id,ativa from cd_matriculas where igreja_id=:t and id=:id', **params)
    if existing and (existing[0]['turma_id'], existing[0]['pessoa_id']) != (tid, payload.pessoa_id):
        raise HTTPException(409, 'Identificador reutilizado com outros dados')
    active = rows(db, '''select id from cd_matriculas where igreja_id=:t
        and pessoa_id=:p and modulo_numero=:n and ativa and not concluida''', **params)
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
    require_unfinished(db,t,mid)
    db.execute(text('''update cd_matriculas set ativa=false,cancelada_por=:u,cancelada_em=clock_timestamp()
        where igreja_id=:t and turma_id=:tid and id=:mid and ativa'''), dict(t=t, tid=tid, mid=mid, u=uid))
    return {'status': 'cancelada'}


def attendance_history(db, user, turma_id, matricula_id, aula_id):
    t, uid, roles = actor(db, user)
    turma(db, t, turma_id)
    require_scope(db, t, uid, roles, turma_id)
    if not rows(db, '''select m.id from cd_matriculas m join pessoas p
        on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
        where m.igreja_id=:t and m.turma_id=:tid and m.id=:mid and p.arquivada_em is null''',
        t=t, tid=turma_id, mid=matricula_id):
        raise HTTPException(404, 'Matrícula não encontrada')
    return rows(db, '''select h.registro_id,h.anterior_id,h.presente,h.modalidade,h.registrada_por,h.registrada_em,
        coalesce(person.nome,u.nome,'Usuário da equipe') as registrada_por_nome
        from cd_presencas_historico h join cd_presencas p on p.igreja_id=h.igreja_id and p.id=h.presenca_id
        join app_users u on u.igreja_id=h.igreja_id and u.id=h.registrada_por
        left join pessoas person on person.igreja_id=u.igreja_id and person.id=u.pessoa_id
        where p.igreja_id=:t and p.turma_id=:tid and p.matricula_id=:mid and p.aula_id=:a
        order by h.registrada_em,h.registro_id''', t=t, tid=turma_id, mid=matricula_id, a=aula_id)


def attendance(db, user, turma_id, matricula_id, aula_id, payload):
    t, uid, current_turma = enrollment_scope(db, user, turma_id, lock=True)
    # Replayed receipts are read only and cannot restore responsibility or undo
    # corrections. The same UUID with any other intent fails closed.
    previous = rows(db, '''select p.turma_id,p.matricula_id,p.aula_id,h.registro_id,h.anterior_id,
        h.presente,h.modalidade,h.registrada_por,h.registrada_em
        from cd_presencas_historico h join cd_presencas p on p.igreja_id=h.igreja_id and p.id=h.presenca_id
        where h.igreja_id=:t and h.registro_id=:id''', t=t, id=payload.id)
    if previous:
        r = previous[0]
        if (r['turma_id'],r['matricula_id'],r['aula_id'],r['presente'],r['modalidade'],r['anterior_id'],r['registrada_por']) != (
                turma_id,matricula_id,aula_id,payload.presente,payload.modalidade,payload.anterior_id,uid):
            raise HTTPException(409, 'Identificador reutilizado com outros dados')
        return {k: r[k] for k in ('registro_id','anterior_id','presente','modalidade','registrada_por','registrada_em')}
    if current_turma['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    enrollment = rows(db, '''select m.id,m.pessoa_id from cd_matriculas m join pessoas p
        on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
        where m.igreja_id=:t and m.turma_id=:tid and m.id=:mid and m.ativa and p.arquivada_em is null
        for share of m,p''', t=t, tid=turma_id, mid=matricula_id)
    if not enrollment:
        raise HTTPException(409, 'Matrícula ativa não encontrada nesta turma')
    require_unfinished(db,t,matricula_id)
    if payload.modalidade == 'reposicao' and not payload.presente:
        raise HTTPException(422, 'Reposição exige presença')
    activity = rows(db, '''select aula_id,data from cd_calendario where igreja_id=:t and turma_id=:tid
        and aula_id=:a''', t=t, tid=turma_id, a=aula_id)
    if not activity:
        raise HTTPException(422, 'Defina o calendário da aula antes da chamada')
    if activity[0]['data'] > today_sao_paulo():
        raise HTTPException(409, 'Não é possível registrar presença em aula futura')
    current = rows(db, '''select registro_id from cd_presencas where igreja_id=:t
        and matricula_id=:mid and aula_id=:a''', t=t, mid=matricula_id, a=aula_id)
    if (current[0]['registro_id'] if current else None) != payload.anterior_id:
        raise AttendanceChanged()
    params = dict(t=t, tid=turma_id, mid=matricula_id, a=aula_id,
                  id=payload.id, anterior=payload.anterior_id, presente=payload.presente,
                  modalidade=payload.modalidade, u=uid)
    # Cross-turma key collisions are possible even while each turma is locked.
    # A savepoint preserves the request transaction and turns these into 409.
    try:
        with db.begin_nested():
            if current:
                db.execute(text('''update cd_presencas set presente=:presente,modalidade=:modalidade,
                    registro_id=:id,anterior_id=:anterior,registrada_por=:u
                    where igreja_id=:t and matricula_id=:mid and aula_id=:a'''), params)
            else:
                db.execute(text('''insert into cd_presencas(igreja_id,turma_id,matricula_id,aula_id,
                    presente,modalidade,registro_id,registrada_por)
                    values(:t,:tid,:mid,:a,:presente,:modalidade,:id,:u)'''), params)
    except IntegrityError as exc:
        raise HTTPException(409, 'Identificador de presença indisponível') from exc
    receipt = next(r for r in attendance_history(db, user, turma_id, matricula_id, aula_id)
                   if r['registro_id'] == payload.id)
    return {k: value for k, value in receipt.items() if k != 'registrada_por_nome'}


def attendance_summary(db, user, tid):
    """PR 5 input: active enrollments of visible people, fulfilled lesson IDs only.

    Regular presence and replacement count equally. This is not a completion;
    PR 5 must revalidate the complete calendar and human confirmation under lock.
    Cancelled enrollments stay in history; archived people have no history API.
    """
    t, _, _ = enrollment_scope(db, user, tid)
    return rows(db, """select m.id as matricula_id,
        coalesce(array_agg(p.aula_id order by a.numero) filter(where p.presente),array[]::uuid[]) as aulas_cumpridas
        from cd_matriculas m
        join pessoas person on person.igreja_id=m.igreja_id and person.id=m.pessoa_id
        left join cd_presencas p on p.igreja_id=m.igreja_id and p.matricula_id=m.id
        left join cd_aulas a on a.igreja_id=p.igreja_id and a.id=p.aula_id
        where m.igreja_id=:t and m.turma_id=:tid and m.ativa and person.arquivada_em is null group by m.id order by m.id""", t=t,tid=tid)



def visible_person(db, t, pid, *, lock=False, include_archived=False):
    found = rows(db, 'select id,nome from pessoas where igreja_id=:t and id=:p'
                 + ('' if include_archived else ' and arquivada_em is null')
                 + (' for update' if lock else ''),t=t,p=pid)
    if not found:
        raise HTTPException(404, 'Pessoa não encontrada')
    return found[0]


def finish(db, user, tid, mid, payload, *, equivalence=False):
    t, uid, current = enrollment_scope(db,user,tid,lock=True)
    if equivalence:
        _, _, roles = actor(db,user)
        require_coordination(roles)
        try:
            evidence = evidencia_equivalencia(payload.evidencia)
            source = validar_origem_equivalencia(getattr(payload,'origem_equivalencia',None))
        except ValueError as exc:
            raise HTTPException(422,str(exc)) from exc
    else:
        evidence = None
        source = None
    if EXIGIR_CONFIRMACAO_MODULO and payload.confirmado is not True:
        raise HTTPException(422, 'Conclusão exige confirmação humana identificada')
    found = rows(db, 'select pessoa_id,ativa from cd_matriculas where igreja_id=:t and turma_id=:tid and id=:mid', t=t,tid=tid,mid=mid)
    if not found:
        raise HTTPException(404,'Matrícula não encontrada')
    pid = found[0]['pessoa_id']
    visible_person(db,t,pid,lock=True)
    params=dict(t=t,id=payload.id,p=pid,c=current['curriculo_id'],m=current['modulo_id'],tid=tid,mid=mid,u=uid,
                origem='equivalencia' if equivalence else 'frequencia',e=evidence,source=source)
    existing = rows(db, 'select * from cd_conclusoes where igreja_id=:t and (id=:id or matricula_id=:mid)', **params)
    if existing:
        r=existing[0]
        if (r['id'],r['matricula_id'],r['confirmada_por'],r['origem'],r['evidencia'],r['origem_equivalencia']) != (payload.id,mid,uid,params['origem'],evidence,source):
            raise HTTPException(409,'Matrícula já concluída ou identificador reutilizado')
        return r
    if current['encerrada'] or not found[0]['ativa']:
        raise HTTPException(409,'Conclusão exige turma aberta e matrícula ativa')
    require_prerequisites(db,t,current,pid)
    if not equivalence:
        lessons = [r['id'] for r in rows(db,'select id from cd_aulas where igreja_id=:t and modulo_id=:m',**params)]
        calendar_ids = [r['aula_id'] for r in rows(db,'select aula_id from cd_calendario where igreja_id=:t and turma_id=:tid',**params)]
        fulfilled = [r['aula_id'] for r in rows(db,'select aula_id from cd_presencas where igreja_id=:t and matricula_id=:mid and presente',**params)]
        if not modulo_cumprido(lessons,calendar_ids,fulfilled):
            raise HTTPException(422,'Conclusão exige todas as aulas do módulo e calendário cumpridas')
    try:
        with db.begin_nested():
            return rows(db, """insert into cd_conclusoes(id,igreja_id,pessoa_id,curriculo_id,modulo_id,turma_id,matricula_id,origem,evidencia,origem_equivalencia,confirmada_por)
                values(:id,:t,:p,:c,:m,:tid,:mid,:origem,:e,:source,:u) returning *""",**params)[0]
    except IntegrityError as exc:
        raise HTTPException(409,'Conclusão ou identificador indisponível') from exc


def certificates(db,t,pid,cid):
    return rows(db, """select c.*,array(select cc.conclusao_id from cd_certificado_conclusoes cc
        where cc.igreja_id=c.igreja_id and cc.certificado_id=c.id order by cc.conclusao_id) as conclusoes_ids,
        array(select ce.equivalencia_id from cd_certificado_equivalencias ce
        where ce.igreja_id=c.igreja_id and ce.certificado_id=c.id order by ce.equivalencia_id) as equivalencias_ids
        from cd_certificados c where c.igreja_id=:t and c.pessoa_id=:p and c.curriculo_id=:c
        order by c.emitida_em,c.id""",t=t,p=pid,c=cid)


def person_progress(db,user,pid,cid):
    t,_,roles=actor(db,user); require_coordination(roles)
    visible_person(db,t,pid,include_archived=True)
    current=catalog(db,t,cid)
    completions=rows(db,'select * from cd_conclusoes where igreja_id=:t and pessoa_id=:p and curriculo_id=:c order by confirmada_em,id',t=t,p=pid,c=cid)
    fulfilled=rows(db,'select modulo_id from cd_cumprimentos where igreja_id=:t and pessoa_id=:p and curriculo_id=:c',t=t,p=pid,c=cid)
    equivalents=rows(db,'''select e.*,exists(select 1 from cd_cumprimentos f where f.igreja_id=e.igreja_id and f.id=e.id and f.tipo='equivalencia') as valida
        from cd_equivalencias_versoes e where e.igreja_id=:t and e.pessoa_id=:p and e.curriculo_id=:c order by e.registrada_em,e.id''',t=t,p=pid,c=cid)
    completed={r['modulo_id'] for r in fulfilled}
    levels=[n['id'] for n in current['niveis'] if all(m['id'] in completed for m in current['modulos'] if m['nivel_id']==n['id'])]
    return dict(modulos_cumpridos=sorted(completed),conclusoes=completions,equivalencias=equivalents,niveis_concluidos=levels,certificados=certificates(db,t,pid,cid))


def issue_certificate(db,user,pid,cid,payload):
    t,uid,roles=actor(db,user); require_coordination(roles)
    person=visible_person(db,t,pid,lock=True)
    current=catalog(db,t,cid,lock=True)
    if payload.confirmado is not True:
        raise HTTPException(422,'Emissão exige confirmação da coordenação')
    existing=rows(db,'select id,pessoa_id,curriculo_id,emitida_por,revogada from cd_certificados where igreja_id=:t and id=:id',t=t,id=payload.id)
    if existing:
        r=existing[0]
        if (r['pessoa_id'],r['curriculo_id'],r['emitida_por'],r['revogada']) != (pid,cid,uid,False):
            raise HTTPException(409,'Identificador reutilizado ou certificado revogado')
        return next(c for c in certificates(db,t,pid,cid) if c['id']==payload.id)
    if rows(db,'select id from cd_certificados where igreja_id=:t and pessoa_id=:p and curriculo_id=:c and not revogada',t=t,p=pid,c=cid):
        raise HTTPException(409,'Pessoa já possui certificado ativo neste currículo')
    # Lock source conclusions while validating/issuing, including equivalences.
    rows(db,'''select id from cd_conclusoes where igreja_id=:t and pessoa_id=:p
        order by id for share''',t=t,p=pid)
    completed=rows(db,'''select distinct on(modulo_id) id,modulo_id,tipo from cd_cumprimentos
        where igreja_id=:t and pessoa_id=:p and curriculo_id=:c
        order by modulo_id,tipo,id''',t=t,p=pid,c=cid)
    if {r['modulo_id'] for r in completed}!={m['id'] for m in current['modulos']}:
        raise HTTPException(422,'Certificação exige todos os módulos obrigatórios concluídos')
    params=dict(t=t,id=payload.id,p=pid,c=cid,u=uid,pn=person['nome'],cn=current['nome'],v=current['versao'])
    try:
        with db.begin_nested():
            db.execute(text("""insert into cd_certificados(id,igreja_id,pessoa_id,curriculo_id,nome_pessoa,nome_curriculo,versao_curriculo,emitida_por)
                values(:id,:t,:p,:c,:pn,:cn,:v,:u)"""),params)
            for r in completed:
                table, column = ('cd_certificado_conclusoes','conclusao_id') if r['tipo']=='conclusao' else ('cd_certificado_equivalencias','equivalencia_id')
                db.execute(text(f"""insert into {table}(igreja_id,certificado_id,{column},pessoa_id,curriculo_id)
                    values(:t,:id,:conclusao,:p,:c)"""),params|dict(conclusao=r['id']))
    except IntegrityError as exc:
        raise HTTPException(409,'Certificado ou identificador indisponível') from exc
    return next(c for c in certificates(db,t,pid,cid) if c['id']==payload.id)


def revoke_certificate(db,user,cert_id,payload):
    t,uid,roles=actor(db,user); require_coordination(roles)
    try:
        reason=evidencia_equivalencia(payload.motivo)
    except ValueError as exc:
        raise HTTPException(422,'Revogação exige motivo curto') from exc
    found=rows(db,'select pessoa_id,curriculo_id from cd_certificados where igreja_id=:t and id=:id',t=t,id=cert_id)
    if not found:
        raise HTTPException(404,'Certificado não encontrado')
    pid,cid=found[0]['pessoa_id'],found[0]['curriculo_id']
    visible_person(db,t,pid,lock=True,include_archived=True)
    current=next(c for c in certificates(db,t,pid,cid) if c['id']==cert_id)
    if current['revogada']:
        if (current['revogada_por'],current['motivo_revogacao']) != (uid,reason):
            raise HTTPException(409,'Certificado já revogado com outros dados')
        return current
    db.execute(text('update cd_certificados set revogada=true,revogada_por=:u,motivo_revogacao=:r where igreja_id=:t and id=:id'),dict(t=t,id=cert_id,u=uid,r=reason))
    return next(c for c in certificates(db,t,pid,cid) if c['id']==cert_id)


def equivalence_sources(db,user,pid,cid,*,include_fulfilled=False):
    t,_,roles=actor(db,user); require_coordination(roles)
    visible_person(db,t,pid)
    catalog(db,t,cid)
    return rows(db,'''select c.id,c.modulo_id,m.numero,origem.versao,c.confirmada_em,
        destino_modulo.id as modulo_destino_id from cd_conclusoes c
        join cd_curriculos origem on origem.igreja_id=c.igreja_id and origem.id=c.curriculo_id
        join cd_curriculos destino on destino.igreja_id=c.igreja_id and destino.id=:c
        join cd_modulos m on m.igreja_id=c.igreja_id and m.id=c.modulo_id
        join cd_modulos destino_modulo on destino_modulo.igreja_id=destino.igreja_id
            and destino_modulo.curriculo_id=destino.id and destino_modulo.numero=m.numero
        where c.igreja_id=:t and c.pessoa_id=:p and not c.revogada
        and origem.id<>destino.id and origem.familia_id=destino.familia_id
        and origem.ordem_versao<destino.ordem_versao
        and (:include or not exists(select 1 from cd_cumprimentos f where f.igreja_id=c.igreja_id
            and f.pessoa_id=c.pessoa_id and f.curriculo_id=destino.id and f.modulo_id=destino_modulo.id))
        order by m.numero,c.confirmada_em,c.id''',t=t,p=pid,c=cid,include=include_fulfilled)


def register_version_equivalence(db,user,pid,cid,payload):
    t,uid,roles=actor(db,user); require_coordination(roles)
    visible_person(db,t,pid,lock=True)
    if payload.confirmado is not True:
        raise HTTPException(422,'Equivalência exige confirmação da coordenação')
    try:
        evidence=evidencia_equivalencia(payload.evidencia)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    # Person lock serializes competing requests across all versions/turmas.
    # Source row lock serializes privileged revocation against this decision.
    source=rows(db,'''select id from cd_conclusoes where igreja_id=:t and pessoa_id=:p
        and id=:id and not revogada for share''',t=t,p=pid,id=payload.conclusao_origem_id)
    if not source or not any(r['id']==payload.conclusao_origem_id and r['modulo_destino_id']==payload.modulo_id
                             for r in equivalence_sources(db,user,pid,cid,include_fulfilled=True)):
        raise HTTPException(409,'Conclusão de origem incompatível ou revogada')
    params=dict(t=t,p=pid,c=cid,m=payload.modulo_id,source=payload.conclusao_origem_id,e=evidence,u=uid,id=payload.id)
    existing=rows(db,'''select * from cd_equivalencias_versoes where igreja_id=:t
        and (id=:id or (pessoa_id=:p and curriculo_id=:c and modulo_id=:m))''',**params)
    if existing:
        r=existing[0]
        if (r['id'],r['pessoa_id'],r['curriculo_id'],r['modulo_id'],r['conclusao_origem_id'],r['evidencia'],r['registrada_por']) != (payload.id,pid,cid,payload.modulo_id,payload.conclusao_origem_id,evidence,uid):
            raise HTTPException(409,'Equivalência já registrada ou identificador reutilizado')
        return r
    if rows(db,'''select m.id from cd_matriculas m
        join cd_modulos destino on destino.igreja_id=m.igreja_id and destino.id=:m
        and destino.curriculo_id=:c
        where m.igreja_id=:t and m.pessoa_id=:p and m.ativa and not m.concluida
        and m.modulo_numero=destino.numero''',**params):
        raise HTTPException(409,'Cancele a matrícula em andamento neste módulo antes de registrar a equivalência')
    if rows(db,'''select id from cd_cumprimentos where igreja_id=:t and pessoa_id=:p
        and curriculo_id=:c and modulo_id=:m''',**params):
        raise HTTPException(409,'Módulo já cumprido neste currículo')
    try:
        with db.begin_nested():
            return rows(db,'''insert into cd_equivalencias_versoes
                (id,igreja_id,pessoa_id,curriculo_id,modulo_id,conclusao_origem_id,evidencia,registrada_por)
                values(:id,:t,:p,:c,:m,:source,:e,:u) returning *''',**params)[0]
    except IntegrityError as exc:
        raise HTTPException(409,'Equivalência ou identificador indisponível') from exc


def equivalence_people(db,user,cid,*,q=''):
    t,_,roles=actor(db,user); require_coordination(roles)
    current=catalog(db,t,cid)
    pattern='%'+q.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'
    return rows(db,'''select p.id,p.nome from pessoas p where p.igreja_id=:t
        and p.arquivada_em is null and p.nome ilike :q escape '!'
        and exists(select 1 from cd_conclusoes c join cd_curriculos origem
            on origem.igreja_id=c.igreja_id and origem.id=c.curriculo_id
            join cd_curriculos destino on destino.igreja_id=c.igreja_id and destino.id=:c
            join cd_modulos om on om.igreja_id=c.igreja_id and om.id=c.modulo_id
            join cd_modulos dm on dm.igreja_id=destino.igreja_id and dm.curriculo_id=destino.id and dm.numero=om.numero
            where c.igreja_id=p.igreja_id and c.pessoa_id=p.id and not c.revogada
            and origem.ordem_versao<destino.ordem_versao and origem.familia_id=:f
            and not exists(select 1 from cd_cumprimentos f where f.igreja_id=p.igreja_id
                and f.pessoa_id=p.id and f.curriculo_id=destino.id and f.modulo_id=dm.id))
        order by p.nome,p.id limit 100''',t=t,c=cid,f=current['familia_id'],q=pattern)
