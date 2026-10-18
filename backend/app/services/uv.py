"""UV panel service. Tenant/role checks are live; callers own the transaction.

Turma locks serialize calendar, responsible changes, closure and enrollment.
Only explicit DTO fields leave this service; no conversation or pastoral notes.
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import CurrentUser
from app.domain.uv import SituacaoUV, avaliar_uv

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
    inserted = db.execute(text('''insert into uv_turmas(id,igreja_id,nome) values(:id,:t,:nome)
        on conflict (id) do nothing returning id'''), dict(id=payload.id, t=t, nome=payload.nome)).scalar_one_or_none()
    row = turma(db, t, payload.id, lock=True)
    if row['nome'] != payload.nome:
        raise HTTPException(409, 'Identificador reutilizado com outros dados')
    if inserted is None:
        require_scope(db, t, uid, roles, payload.id)
    else:
        # Only the first creation grants the link. A retry cannot restore removal.
        db.execute(text('''insert into uv_responsaveis(igreja_id,turma_id,usuario_id)
            values(:t,:id,:u)'''), dict(t=t, id=payload.id, u=uid))
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
        where m.igreja_id=:t and m.turma_id=:id and m.ativa order by m.criada_em,m.id''', t=t, id=turma_id)
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
        db.execute(text('''insert into uv_atividades(igreja_id,turma_id,ordem,tipo,aula,data)
            values(:t,:id,:ordem,:tipo,:aula,:data)
            on conflict (igreja_id,turma_id,ordem) do update set data=excluded.data'''),
            dict(t=t, id=turma_id, **a.model_dump()))
    return get_turma(db, user, turma_id)


def responsaveis(db, user, turma_id, payload):
    t = writable(db, user, turma_id)
    # Lock live accounts/roles before granting links. No stale CurrentUser roles.
    for uid in sorted(payload.usuarios, key=str):
        eligible = rows(db, '''select u.id from app_users u where u.igreja_id=:t and u.id=:u
            and u.status='ativo' and exists(select 1 from user_roles r where
            r.igreja_id=u.igreja_id and r.user_id=u.id and r.papel in ('admin','pastor','lider_consol'))
            for share''', t=t, u=uid)
        if not eligible:
            raise HTTPException(422, 'Responsável deve ser usuário ativo e autorizado da igreja')
    db.execute(text('update uv_responsaveis set ativo=false where igreja_id=:t and turma_id=:id'), dict(t=t, id=turma_id))
    for uid in payload.usuarios:
        db.execute(text('''insert into uv_responsaveis(igreja_id,turma_id,usuario_id)
            values(:t,:id,:u) on conflict (igreja_id,turma_id,usuario_id) do update set ativo=true'''),
            dict(t=t, id=turma_id, u=uid))
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
    result = avaliar_uv(SituacaoUV(decisao_registrada=bool(decision),
        responsavel_id=responsible_id if responsible else None,
        conectado_celula=person[0]['celula_id'] is not None))
    if not result.pode_ingressar:
        raise HTTPException(422, 'Matrícula exige decisão registrada e responsável definido na consolidação')
    if rows(db, '''select id from uv_matriculas where igreja_id=:t and turma_id=:id
            and pessoa_id=:p and ativa''', t=t, id=turma_id, p=payload.pessoa_id):
        raise HTTPException(409, 'Pessoa já matriculada nesta turma')
    inserted = db.execute(text('''insert into uv_matriculas(id,igreja_id,turma_id,pessoa_id)
        values(:id,:t,:turma,:p) on conflict (id) do nothing returning id'''),
        dict(id=payload.id, t=t, turma=turma_id, p=payload.pessoa_id)).scalar_one_or_none()
    if inserted is None:
        raise HTTPException(409, 'Identificador de matrícula indisponível')
    return {'id': payload.id}


def close(db, user, turma_id):
    t, uid, roles = actor(db, user)
    turma(db, t, turma_id, lock=True)
    require_scope(db, t, uid, roles, turma_id)
    db.execute(text('update uv_turmas set encerrada=true where igreja_id=:t and id=:id'), dict(t=t, id=turma_id))
    return {'status': 'encerrada'}


def options(db, user, search):
    t, _, _ = actor(db, user)
    # Explicit enrollment picker: minimal identity only, bounded and searchable.
    people = rows(db, """select p.id,p.nome from pessoas p where p.igreja_id=:t
        and p.arquivada_em is null and p.nome ilike :q
        and exists(select 1 from decisions d where d.igreja_id=p.igreja_id and d.pessoa_id=p.id)
        and exists(select 1 from app_users holder where holder.igreja_id=p.igreja_id
          and holder.status='ativo' and holder.id=(select c.responsavel_id from consolidacoes c
          where c.igreja_id=p.igreja_id and c.pessoa_id=p.id and c.tipo='individual'
          and c.abandonada_em is null order by c.created_at desc,c.id desc limit 1))
        order by p.nome,p.id limit 50""", t=t, q='%' + search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%')
    users = rows(db, """select u.id,coalesce(p.nome,'Usuário da equipe') as nome from app_users u
        left join pessoas p on p.igreja_id=u.igreja_id and p.id=u.pessoa_id
        where u.igreja_id=:t and u.status='ativo'
        and exists(select 1 from user_roles r where r.igreja_id=u.igreja_id and r.user_id=u.id
          and r.papel in ('admin','pastor','lider_consol')) order by nome,u.id limit 100""", t=t)
    return {'pessoas': people, 'usuarios': users}
