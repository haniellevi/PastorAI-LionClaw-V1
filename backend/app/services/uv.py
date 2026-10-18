"""UV panel service. Tenant/role checks are live; callers own the transaction.

Turma locks serialize calendar, responsible changes, closure and enrollment.
Only explicit DTO fields leave this service; no conversation or pastoral notes.
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import CurrentUser
from app.domain.uv import AulaConcluida, ModalidadeAula, SituacaoUV, avaliar_uv
from app.domain.permissions import can_access_screen
from app.domain.work_queue import can_resolve, TIPO_RESOLVER_ROLES

UV_ROLES = {'admin', 'pastor', 'lider_consol'}
COORDINATION_ROLES = {'admin', 'pastor'}


def rows(db, sql, **params):
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def actor(db: Session, user: CurrentUser) -> tuple[UUID, UUID, set[str]]:
    tenant, uid = UUID(user.igreja_id), UUID(user.app_user_id)
    result = rows(db, """select r.papel from app_users u join user_roles r
        on r.igreja_id=u.igreja_id and r.user_id=u.id
        where u.igreja_id=:t and u.id=:u and u.status='ativo' for share of u,r""", t=tenant, u=uid)
    roles = {r['papel'] for r in result} & UV_ROLES
    if not roles:
        raise HTTPException(403, 'Sem permissão para Universidade da Vida')
    if 'admin' not in roles:
        permissions = rows(db, 'select papel,tela from role_permissions where igreja_id=:t', t=tenant)
        matrix: dict[str, set[str]] = {}
        for permission in permissions:
            matrix.setdefault(permission['papel'], set()).add(permission['tela'])
        if not can_access_screen(frozenset(roles), 'universidade-vida', matrix):
            raise HTTPException(403, 'Você não tem acesso a esta tela')
    return tenant, uid, roles


def turma(db, t, turma_id, *, lock=False):
    result = rows(db, 'select id,nome,encerrada from uv_turmas where igreja_id=:t and id=:id'
                  + (' for update' if lock else ''), t=t, id=turma_id)
    if not result:
        raise HTTPException(404, 'Turma não encontrada')
    return result[0]


def require_scope(db, t, uid, roles, turma_id):
    if roles & COORDINATION_ROLES:
        return
    found = rows(db, """select id from uv_responsaveis where igreja_id=:t
        and turma_id=:id and usuario_id=:u and ativo""", t=t, id=turma_id, u=uid)
    if not found:
        raise HTTPException(403, 'Turma fora da sua responsabilidade')


def list_turmas(db, user):
    t, uid, roles = actor(db, user)
    return rows(db, """select id,nome,encerrada from uv_turmas t where igreja_id=:t
        and (:coordenacao or exists (select 1 from uv_responsaveis r
        where r.igreja_id=t.igreja_id and r.turma_id=t.id and r.usuario_id=:u and r.ativo))
        order by criada_em,id""", t=t, u=uid, coordenacao=bool(roles & COORDINATION_ROLES))


def create_turma(db, user, payload):
    t, uid, roles = actor(db, user)
    # Request UUID is an opaque idempotency key; conflicts never overwrite intent.
    inserted = db.execute(text('''insert into uv_turmas(id,igreja_id,nome,criada_por) values(:id,:t,:nome,:autor)
        on conflict (id) do nothing returning id'''), dict(id=payload.id, t=t, nome=payload.nome, autor=uid)).scalar_one_or_none()
    row = turma(db, t, payload.id, lock=True)
    if row['nome'] != payload.nome:
        raise HTTPException(409, 'Identificador reutilizado com outros dados')
    if inserted is None:
        require_scope(db, t, uid, roles, payload.id)
    else:
        # Only the first creation grants the link. A retry cannot restore removal.
        db.execute(text('''insert into uv_responsaveis(igreja_id,turma_id,usuario_id,atribuido_por)
            values(:t,:id,:u,:autor)'''), dict(t=t, id=payload.id, u=uid, autor=uid))
    return row


def get_turma(db, user, turma_id):
    t, uid, roles = actor(db, user)
    row = turma(db, t, turma_id)
    require_scope(db, t, uid, roles, turma_id)
    row['atividades'] = rows(db, '''select ordem,tipo,aula,data from uv_atividades
        where igreja_id=:t and turma_id=:id order by ordem''', t=t, id=turma_id)
    row['responsaveis'] = rows(db, '''select r.usuario_id, p.nome,
        (u.status='ativo' and exists(select 1 from user_roles ur where
        ur.igreja_id=u.igreja_id and ur.user_id=u.id and ur.papel in
        ('admin','pastor','lider_consol'))) as elegivel
        from uv_responsaveis r join app_users u on u.igreja_id=r.igreja_id and u.id=r.usuario_id
        left join pessoas p on p.igreja_id=u.igreja_id and p.id=u.pessoa_id
        where r.igreja_id=:t and r.turma_id=:id and r.ativo order by r.id''', t=t, id=turma_id)
    row['matriculas'] = rows(db, '''select m.id,m.pessoa_id,p.nome,
        (p.celula_id is null) as conexao_celula_pendente
        from uv_matriculas m join pessoas p on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
        where m.igreja_id=:t and m.turma_id=:id and m.ativa and p.arquivada_em is null order by m.criada_em,m.id''', t=t, id=turma_id)
    attendance_rows = rows(db, '''select matricula_id,aula,presente,modalidade,registro_id,registrada_por,registrada_em
        from uv_presencas where igreja_id=:t and turma_id=:id order by aula''', t=t, id=turma_id)
    for enrollment in row['matriculas']:
        records = [p for p in attendance_rows if p['matricula_id'] == enrollment['id']]
        result = avaliar_uv(SituacaoUV(aulas=tuple(AulaConcluida(p['aula'], ModalidadeAula(p['modalidade']))
            for p in records if p['presente'])))
        enrollment['aulas_pendentes'] = list(result.aulas_pendentes)
        enrollment['aulas_cumpridas'] = [n for n in range(1,9) if n not in result.aulas_pendentes]
        enrollment['presencas'] = [{k: value for k, value in p.items() if k != 'matricula_id'} for p in records]
    return row


def writable(db, user, turma_id):
    t, uid, roles = actor(db, user)
    row = turma(db, t, turma_id, lock=True)
    require_scope(db, t, uid, roles, turma_id)
    if row['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    return t


def calendar(db, user, turma_id, payload):
    t = writable(db, user, turma_id)
    # Fixed positions keep activity identity stable when dates change.
    for a in payload.atividades:
        db.execute(text('''insert into uv_atividades(igreja_id,turma_id,ordem,tipo,aula,data,criada_por)
            values(:t,:id,:ordem,:tipo,:aula,:data,:autor)
            on conflict (igreja_id,turma_id,ordem) do update set data=excluded.data'''),
            dict(t=t, id=turma_id, autor=UUID(user.app_user_id), **a.model_dump()))
    return get_turma(db, user, turma_id)


def require_coordination(roles):
    if not roles & COORDINATION_ROLES:
        raise HTTPException(403, 'Ação restrita à coordenação')


def responsaveis(db, user, turma_id, payload):
    _, autor, roles = actor(db, user)
    require_coordination(roles)
    t = writable(db, user, turma_id)
    # Lock live accounts/roles before granting links. No stale CurrentUser roles.
    for uid in sorted(payload.usuarios, key=str):
        eligible = rows(db, '''select u.id from app_users u where u.igreja_id=:t and u.id=:u
            and u.status='ativo' and exists(select 1 from user_roles r where
            r.igreja_id=u.igreja_id and r.user_id=u.id and r.papel in ('admin','pastor','lider_consol'))
            for share''', t=t, u=uid)
        if not eligible:
            raise HTTPException(422, 'Responsável deve ser usuário ativo e autorizado da igreja')
    db.execute(text('''update uv_responsaveis set ativo=false,removido_por=:autor,removida_em=clock_timestamp()
        where igreja_id=:t and turma_id=:id and ativo and not (usuario_id=any(cast(:usuarios as uuid[])))'''),
        dict(t=t, id=turma_id, autor=autor, usuarios=payload.usuarios))
    for uid in payload.usuarios:
        db.execute(text('''insert into uv_responsaveis(igreja_id,turma_id,usuario_id,atribuido_por)
            values(:t,:id,:u,:autor) on conflict (igreja_id,turma_id,usuario_id) do update set ativo=true,
            atribuido_por=excluded.atribuido_por,atribuida_em=clock_timestamp()
            where not uv_responsaveis.ativo'''),
            dict(t=t, id=turma_id, u=uid, autor=autor))
    return {'status': 'salvo'}


def enroll(db, user, turma_id, payload):
    t, uid, roles = actor(db, user)
    current = turma(db, t, turma_id, lock=True)
    require_scope(db, t, uid, roles, turma_id)
    previous = rows(db, 'select id,turma_id,pessoa_id from uv_matriculas where igreja_id=:t and id=:id', t=t, id=payload.id)
    if previous:
        if previous[0]['turma_id'] != turma_id or previous[0]['pessoa_id'] != payload.pessoa_id:
            raise HTTPException(409, 'Identificador reutilizado com outros dados')
        return {'id': payload.id}
    if current['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    person = rows(db, '''select id,celula_id from pessoas where igreja_id=:t and id=:p
        and arquivada_em is null for share''', t=t, p=payload.pessoa_id)
    if not person:
        raise HTTPException(404, 'Pessoa não encontrada')
    # Official decision plus the current canonical individual track, never notes
    # or the historical completion/CD flag. Cell connection is only a pending task.
    decision = rows(db, 'select id from decisions where igreja_id=:t and pessoa_id=:p limit 1', t=t, p=payload.pessoa_id)
    tracks = rows(db, '''select responsavel_id from consolidacoes where igreja_id=:t
        and pessoa_id=:p and tipo='individual' and abandonada_em is null
        order by created_at desc,id desc limit 1 for share''', t=t, p=payload.pessoa_id)
    responsible_id = tracks[0]['responsavel_id'] if tracks else None
    responsible = rows(db, """select id from app_users where igreja_id=:t
        and id=:id and status='ativo' for share""", t=t, id=responsible_id)
    responsible_roles = rows(db, 'select papel from user_roles where igreja_id=:t and user_id=:id for share',
                             t=t, id=responsible_id)
    capable = can_resolve([r['papel'] for r in responsible_roles], 'fonovisita')
    result = avaliar_uv(SituacaoUV(decisao_registrada=bool(decision),
        responsavel_id=responsible_id if responsible and capable else None,
        conectado_celula=person[0]['celula_id'] is not None))
    if not result.pode_ingressar:
        raise HTTPException(422, 'Matrícula exige decisão registrada e responsável definido na consolidação')
    if rows(db, '''select id from uv_matriculas where igreja_id=:t and turma_id=:id
            and pessoa_id=:p and ativa''', t=t, id=turma_id, p=payload.pessoa_id):
        raise HTTPException(409, 'Pessoa já matriculada nesta turma')
    inserted = db.execute(text('''insert into uv_matriculas(id,igreja_id,turma_id,pessoa_id,criada_por)
        values(:id,:t,:turma,:p,:autor) on conflict (id) do nothing returning id'''),
        dict(id=payload.id, t=t, turma=turma_id, p=payload.pessoa_id, autor=uid)).scalar_one_or_none()
    if inserted is None:
        raise HTTPException(409, 'Identificador de matrícula indisponível')
    return {'id': payload.id}


def close(db, user, turma_id):
    t, uid, roles = actor(db, user)
    require_coordination(roles)
    turma(db, t, turma_id, lock=True)
    require_scope(db, t, uid, roles, turma_id)
    db.execute(text('''update uv_turmas set encerrada=true,encerrada_por=:u,encerrada_em=clock_timestamp()
        where igreja_id=:t and id=:id and not encerrada'''), dict(t=t, id=turma_id, u=uid))
    return {'status': 'encerrada'}


def reopen(db, user, turma_id):
    t, uid, roles = actor(db, user)
    require_coordination(roles)
    turma(db, t, turma_id, lock=True)
    db.execute(text('''update uv_turmas set encerrada=false,reaberta_por=:u,reaberta_em=clock_timestamp()
        where igreja_id=:t and id=:id and encerrada'''), dict(t=t, id=turma_id, u=uid))
    return {'status': 'reaberta'}


def options(db, user, search, purpose='pessoas'):
    t, uid, roles = actor(db, user)
    if not roles & COORDINATION_ROLES:
        linked = rows(db, """select r.id from uv_responsaveis r
            join uv_turmas t on t.igreja_id=r.igreja_id and t.id=r.turma_id
            where r.igreja_id=:t and r.usuario_id=:u and r.ativo
            and not t.encerrada limit 1""", t=t, u=uid)
        if not linked:
            raise HTTPException(403, 'Nenhuma turma ativa sob sua responsabilidade')
    if purpose == 'usuarios':
        require_coordination(roles)
        users = rows(db, """select u.id,coalesce(p.nome,'Usuário da equipe') as nome from app_users u
            left join pessoas p on p.igreja_id=u.igreja_id and p.id=u.pessoa_id
            where u.igreja_id=:t and u.status='ativo'
            and exists(select 1 from user_roles r where r.igreja_id=u.igreja_id and r.user_id=u.id
              and r.papel in ('admin','pastor','lider_consol')) order by nome,u.id limit 100""", t=t)
        return {'pessoas': [], 'usuarios': users}
    if purpose != 'pessoas':
        raise HTTPException(422, 'Finalidade inválida')
    # Explicit enrollment picker: minimal identity only, bounded and searchable.
    people = rows(db, """select p.id,p.nome from pessoas p where p.igreja_id=:t
        and p.arquivada_em is null and p.nome ilike :q
        and exists(select 1 from decisions d where d.igreja_id=p.igreja_id and d.pessoa_id=p.id)
        and exists(select 1 from app_users holder where holder.igreja_id=p.igreja_id
          and holder.status='ativo' and exists(select 1 from user_roles hr where
            hr.igreja_id=holder.igreja_id and hr.user_id=holder.id and hr.papel::text=any(:holder_roles))
          and holder.id=(select c.responsavel_id from consolidacoes c
          where c.igreja_id=p.igreja_id and c.pessoa_id=p.id and c.tipo='individual'
          and c.abandonada_em is null order by c.created_at desc,c.id desc limit 1))
        order by p.nome,p.id limit 50""", t=t, holder_roles=sorted(TIPO_RESOLVER_ROLES['fonovisita'] | {'admin'}), q='%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    return {'pessoas': people, 'usuarios': []}


def lesson_number(aula):
    if type(aula) is not int or not 1 <= aula <= 8:
        raise HTTPException(422, 'Presença exige aula de 1 a 8; Encontro é um marco separado')


def attendance_history(db, user, turma_id, matricula_id, aula):
    lesson_number(aula)
    t, uid, roles = actor(db, user)
    turma(db, t, turma_id)
    require_scope(db, t, uid, roles, turma_id)
    return rows(db, '''select h.registro_id,h.anterior_id,h.presente,h.modalidade,h.registrada_por,h.registrada_em
        from uv_presencas_historico h join uv_presencas p on p.igreja_id=h.igreja_id and p.id=h.presenca_id
        where p.igreja_id=:t and p.turma_id=:tid and p.matricula_id=:mid and p.aula=:a
        order by h.registrada_em,h.registro_id''', t=t, tid=turma_id, mid=matricula_id, a=aula)


def attendance(db, user, turma_id, matricula_id, aula, payload):
    lesson_number(aula)
    t, uid, roles = actor(db, user)
    current_turma = turma(db, t, turma_id, lock=True)
    require_scope(db, t, uid, roles, turma_id)
    # Replayed receipts are read only and cannot restore responsibility or undo
    # corrections. The same UUID with any other intent fails closed.
    previous = rows(db, '''select p.turma_id,p.matricula_id,p.aula,h.registro_id,h.anterior_id,
        h.presente,h.modalidade,h.registrada_por,h.registrada_em
        from uv_presencas_historico h join uv_presencas p on p.igreja_id=h.igreja_id and p.id=h.presenca_id
        where h.igreja_id=:t and h.registro_id=:id''', t=t, id=payload.id)
    if previous:
        r = previous[0]
        if (r['turma_id'],r['matricula_id'],r['aula'],r['presente'],r['modalidade'],r['anterior_id'],r['registrada_por']) != (
                turma_id,matricula_id,aula,payload.presente,payload.modalidade,payload.anterior_id,uid):
            raise HTTPException(409, 'Identificador reutilizado com outros dados')
        return {k: r[k] for k in ('registro_id','anterior_id','presente','modalidade','registrada_por','registrada_em')}
    if current_turma['encerrada']:
        raise HTTPException(409, 'Turma encerrada')
    enrollment = rows(db, '''select m.id from uv_matriculas m join pessoas p
        on p.igreja_id=m.igreja_id and p.id=m.pessoa_id
        where m.igreja_id=:t and m.turma_id=:tid and m.id=:mid and m.ativa and p.arquivada_em is null
        for share of m,p''', t=t, tid=turma_id, mid=matricula_id)
    if not enrollment:
        raise HTTPException(409, 'Matrícula ativa não encontrada nesta turma')
    activity = rows(db, '''select id from uv_atividades where igreja_id=:t and turma_id=:tid
        and tipo='aula' and aula=:a''', t=t, tid=turma_id, a=aula)
    if not activity:
        raise HTTPException(422, 'Defina o calendário da aula antes da chamada')
    current = rows(db, '''select registro_id from uv_presencas where igreja_id=:t
        and matricula_id=:mid and aula=:a''', t=t, mid=matricula_id, a=aula)
    if (current[0]['registro_id'] if current else None) != payload.anterior_id:
        raise HTTPException(409, 'Presença já registrada ou corrigida. Atualize e faça uma correção explícita')
    params = dict(t=t, tid=turma_id, mid=matricula_id, a=aula, atividade=activity[0]['id'],
                  id=payload.id, anterior=payload.anterior_id, presente=payload.presente,
                  modalidade=payload.modalidade, u=uid)
    # Cross-turma key collisions are possible even while each turma is locked.
    # A savepoint preserves the request transaction and turns these into 409.
    try:
        with db.begin_nested():
            if current:
                db.execute(text('''update uv_presencas set presente=:presente,modalidade=:modalidade,
                    registro_id=:id,anterior_id=:anterior,registrada_por=:u,registrada_em=clock_timestamp()
                    where igreja_id=:t and matricula_id=:mid and aula=:a'''), params)
            else:
                db.execute(text('''insert into uv_presencas(igreja_id,turma_id,matricula_id,atividade_id,aula,
                    presente,modalidade,registro_id,registrada_por)
                    values(:t,:tid,:mid,:atividade,:a,:presente,:modalidade,:id,:u)'''), params)
    except IntegrityError as exc:
        raise HTTPException(409, 'Identificador de presença indisponível') from exc
    return next(r for r in attendance_history(db, user, turma_id, matricula_id, aula)
                if r['registro_id'] == payload.id)
