"""Characterization tests for observed M8-M10 (UV) behavior with synthetic data.

These tests document current observed behavior and discrepancies without
endorsing or altering business rules, security controls, or historical SQL.
"""
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.routers.uv import ConclusaoInput, ResponsaveisInput
from app.services import uv
from tests.test_uv_conclusao_pg import complete, marco
from tests.test_uv_presencas_pg import payload as attendance_payload, setup
from tests.test_uv_turmas_pg import (
    create,
    database,  # noqa: F401
    matricula,
    migrated_database,  # noqa: F401
    principal,
    rls_database_url,  # noqa: F401
    scoped,
    seeded,  # noqa: F401
)

pytestmark = pytest.mark.rls_integration


def _finish(s, v, tid, mid, actor_key='uid'):
    return uv.finish(s, principal(v, actor_key), tid, mid, ConclusaoInput(id=uuid4(), confirmado=True))


def test_characterize_enrollment_requires_active_non_abandoned_consolidation_and_capable_holder(
    database, seeded
):
    """Characterization (M8): abandoned track or holder without fonovisita capability blocks picker and enroll."""
    v = seeded
    with scoped(database, v['t']) as s:
        tid = create(s, v)
        s.execute(
            text("update consolidacoes set abandonada_em=now() where igreja_id=:t and pessoa_id=:p"),
            dict(t=v['t'], p=v['p']),
        )
        assert uv.options(s, principal(v), 'Aluno')['pessoas'] == []
        with pytest.raises(HTTPException) as exc:
            uv.enroll(s, principal(v), tid, matricula(v))
        assert exc.value.status_code == 422

        # Active track with an operator (lacks fonovisita resolver capability) still fails.
        s.execute(
            text(
                "insert into consolidacoes(igreja_id,pessoa_id,tipo,responsavel_id) "
                "values(:t,:p,'individual',:u)"
            ),
            dict(t=v['t'], p=v['p'], u=v['outsider']),
        )
        assert uv.options(s, principal(v), 'Aluno')['pessoas'] == []
        with pytest.raises(HTTPException) as exc:
            uv.enroll(s, principal(v), tid, matricula(v))
        assert exc.value.status_code == 422


def test_characterize_enrollment_cell_pending_flag_and_reactivation_after_inactive(database, seeded):
    """Characterization (M8): connected cell sets pending=False; inactive enrollment allows re-enrolling."""
    v = seeded
    cell_id = uuid4()
    with database.begin() as c:
        c.execute(
            text(
                "insert into celulas(id,igreja_id,nome,cobertura_espiritual) "
                "values(:id,:t,'Célula sintética','Cobertura sintética')"
            ),
            dict(id=cell_id, t=v['t']),
        )
        c.execute(text("update pessoas set celula_id=:c where id=:p"), dict(c=cell_id, p=v['p']))
    with scoped(database, v['t']) as s:
        tid = create(s, v)
        first = matricula(v)
        uv.enroll(s, principal(v), tid, first)
        detail = uv.get_turma(s, principal(v), tid)
        assert len(detail['matriculas']) == 1
        assert detail['matriculas'][0]['conexao_celula_pendente'] is False

        # Deactivating the previous enrollment allows a new active enrollment in the same turma.
        s.execute(text("update uv_matriculas set ativa=false where id=:id"), dict(id=first.id))
        second = matricula(v)
        uv.enroll(s, principal(v), tid, second)
        detail = uv.get_turma(s, principal(v), tid)
        assert [m['id'] for m in detail['matriculas']] == [second.id]


def test_characterize_attendance_count_reverts_on_absent_and_stays_isolated_per_turma(database, seeded):
    """Characterization (M9): correcting present->absent restores pending lesson; Turma B attendance never affects Turma A."""
    v = seeded
    with scoped(database, v['t']) as s:
        tid_a, mid_a = setup(s, v)
        tid_b, mid_b = setup(s, v)

        lessons_a = {}
        for n in range(1, 9):
            p = attendance_payload()
            lessons_a[n] = p.id
            uv.attendance(s, principal(v), tid_a, mid_a, n, p)

        # Correcting lesson 4 to absent removes it from aulas_cumpridas and blocks completion.
        uv.attendance(
            s,
            principal(v),
            tid_a,
            mid_a,
            4,
            attendance_payload(presente=False, anterior_id=lessons_a[4]),
        )
        student_a = uv.get_turma(s, principal(v), tid_a)['matriculas'][0]
        assert student_a['aulas_pendentes'] == [4]
        assert student_a['aulas_cumpridas'] == [1, 2, 3, 5, 6, 7, 8]

        uv.milestone(s, principal(v), tid_a, mid_a, 'encontro', marco())
        uv.milestone(s, principal(v), tid_a, mid_a, 'batismo', marco())
        with pytest.raises(HTTPException) as exc:
            _finish(s, v, tid_a, mid_a)
        assert exc.value.status_code == 422

        # Completing lesson 4 in Turma B counts only in Turma B and leaves Turma A unchanged.
        uv.attendance(s, principal(v), tid_b, mid_b, 4, attendance_payload(modalidade='reposicao'))
        student_b = uv.get_turma(s, principal(v), tid_b)['matriculas'][0]
        assert student_b['aulas_cumpridas'] == [4]
        assert student_b['aulas_pendentes'] == [1, 2, 3, 5, 6, 7, 8]
        with pytest.raises(HTTPException) as exc:
            _finish(s, v, tid_b, mid_b)
        assert exc.value.status_code == 422

        student_a_after_b = uv.get_turma(s, principal(v), tid_a)['matriculas'][0]
        assert student_a_after_b['aulas_pendentes'] == [4]
        assert student_a_after_b['aulas_cumpridas'] == [1, 2, 3, 5, 6, 7, 8]
        with pytest.raises(HTTPException) as exc:
            _finish(s, v, tid_a, mid_a)
        assert exc.value.status_code == 422


def test_characterize_visitor_without_f2_enrolls_then_blocks_finish_until_3_cell_presences(
    database, seeded
):
    """Characterization (M8/M10 discrepancy): visitor with decision row but aceitou_jesus=False & presencas_celula<3 enrolls (200) yet finish fails (409) until 3+ cell presences."""
    v = seeded
    with database.begin() as c:
        c.execute(
            text(
                "update pessoas set tipo='visitante', etapa='ganhar', "
                "aceitou_jesus=false, presencas_celula=2 where id=:p"
            ),
            dict(p=v['p']),
        )
    with scoped(database, v['t']) as s:
        tid, mid = complete(s, v)
        with pytest.raises(HTTPException) as exc:
            _finish(s, v, tid, mid)
        assert exc.value.status_code == 409

        # Once F2 criterion is met (presencas_celula >= 3), DB trigger trg_promote_pipeline advances ganhar -> consolidar,
        # and UV completion advances consolidar -> discipular.
        s.execute(text("update pessoas set presencas_celula=3 where id=:p"), dict(p=v['p']))
        result = _finish(s, v, tid, mid)
        assert result['etapa_anterior'] == 'consolidar'
        assert result['etapa_resultante'] == 'discipular'
        assert result['origem_aptidao'] == 'conclusao_uv'


@pytest.mark.parametrize(
    'initial_etapa,expected_etapa',
    [('consolidar', 'discipular'), ('discipular', 'discipular'), ('enviar', 'enviar')],
)
def test_characterize_journey_stage_preservation_and_lider_consol_finish(
    database, seeded, initial_etapa, expected_etapa
):
    """Characterization (M10): completion promotes consolidar->discipular, preserves discipular/enviar, and allows lider_consol."""
    v = seeded
    with database.begin() as c:
        c.execute(
            text("update pessoas set tipo='membro', etapa=:e where id=:p"),
            dict(e=initial_etapa, p=v['p']),
        )
    with scoped(database, v['t']) as s:
        tid, mid = complete(s, v)
        uv.responsaveis(s, principal(v), tid, ResponsaveisInput(usuarios=[v['leader']]))
        result = _finish(s, v, tid, mid, actor_key='leader')
        assert result['etapa_anterior'] == initial_etapa
        assert result['etapa_resultante'] == expected_etapa
        assert result['confirmada_por'] == v['leader']


def test_characterize_legacy_aptidao_trigger_and_immutable_receipt_after_revocation(database, seeded):
    """Characterization (M10): legacy apto_proxima_cd=True defaults to 'legado'; manual revocation clears person origin while uv_conclusoes receipt remains unchanged."""
    v = seeded
    with scoped(database, v['t']) as s:
        # Legacy caller path: setting apto_proxima_cd=True without origem_aptidao_cd defaults to 'legado'.
        s.execute(text("update pessoas set apto_proxima_cd=true where id=:p"), dict(p=v['p']))
        assert (
            s.execute(text("select origem_aptidao_cd from pessoas where id=:p"), dict(p=v['p'])).scalar_one()
            == 'legado'
        )
        tid, mid = complete(s, v)
        result = _finish(s, v, tid, mid)
        assert result['origem_aptidao'] == 'legado'

        receipt_sql = text(
            "select id, pessoa_id, turma_id, matricula_id, confirmada_por, confirmada_em, "
            "etapa_anterior, etapa_resultante, origem_aptidao "
            "from uv_conclusoes where pessoa_id=:p"
        )
        receipt_before = tuple(s.execute(receipt_sql, dict(p=v['p'])).one())

        # Manual revocation after completion clears origem_aptidao_cd, while the historical receipt remains identical.
        s.execute(text("update pessoas set apto_proxima_cd=false where id=:p"), dict(p=v['p']))
        row = s.execute(
            text("select apto_proxima_cd, origem_aptidao_cd from pessoas where id=:p"), dict(p=v['p'])
        ).one()
        assert tuple(row) == (False, None)
        receipt_after = tuple(s.execute(receipt_sql, dict(p=v['p'])).one())
        assert receipt_after == receipt_before
