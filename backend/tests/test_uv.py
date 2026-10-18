"""Approved UV rules, independent of storage and the individual follow-up."""
from dataclasses import replace
from uuid import UUID

import pytest

from app.domain.uv import (
    AulaConcluida, EvidenciaValidada, ModalidadeAula, OrigemAptidao,
    SituacaoUV, avaliar_uv,
)

RESPONSAVEL = UUID(int=1)
VALIDADOR = UUID(int=2)


def completo():
    return SituacaoUV(
        decisao_registrada=True, responsavel_id=RESPONSAVEL,
        aulas=tuple(AulaConcluida(n) for n in range(1, 9)),
        encontro=EvidenciaValidada(VALIDADOR, anterior=True),
        batismo=EvidenciaValidada(VALIDADOR, anterior=True),
        confirmado_por=RESPONSAVEL,
    )


@pytest.mark.parametrize('decisao,responsavel', [(False, None), (False, RESPONSAVEL), (True, None)])
def test_entrada_exige_decisao_e_responsavel(decisao, responsavel):
    result = avaliar_uv(replace(completo(), decisao_registrada=decisao, responsavel_id=responsavel))
    assert not result.pode_ingressar
    assert not result.concluida
    assert not result.apto_proxima_cd


def test_celula_e_pendencia_sem_bloquear_entrada_ou_conclusao():
    result = avaliar_uv(completo())
    assert result.pode_ingressar and result.concluida
    assert result.conexao_celula_pendente
    assert not avaliar_uv(replace(completo(), conectado_celula=True)).conexao_celula_pendente


@pytest.mark.parametrize('numero', range(1, 9))
def test_cada_aula_e_obrigatoria(numero):
    result = avaliar_uv(replace(completo(), aulas=tuple(a for a in completo().aulas if a.numero != numero)))
    assert result.aulas_pendentes == (numero,)
    assert not result.concluida and not result.apto_proxima_cd


def test_reposicao_registrada_vale_e_duplicata_nao_substitui_aula():
    aulas = completo().aulas[:-1] + (AulaConcluida(8, ModalidadeAula.REPOSICAO),)
    assert avaliar_uv(replace(completo(), aulas=aulas)).concluida
    assert aulas[-1].modalidade == ModalidadeAula.REPOSICAO
    assert not avaliar_uv(replace(completo(), aulas=completo().aulas[:-1] + (AulaConcluida(1),))).concluida


@pytest.mark.parametrize('campo', ['encontro', 'batismo', 'confirmado_por'])
def test_conclusao_exige_evidencias_e_confirmacao(campo):
    assert not avaliar_uv(replace(completo(), **{campo: None})).concluida


def test_confirmacao_de_outro_nao_substitui_responsavel():
    assert not avaliar_uv(replace(completo(), confirmado_por=VALIDADOR)).concluida


def test_eventos_anteriores_validados_valem_sem_repeticao():
    result = avaliar_uv(completo())
    assert result.concluida and result.apto_proxima_cd
    assert result.origem_aptidao == OrigemAptidao.CONCLUSAO_UV


def test_legado_preserva_aptidao_sem_inventar_conclusao():
    result = avaliar_uv(SituacaoUV(apto_cd_legado=True))
    assert result.apto_proxima_cd and not result.concluida
    assert result.origem_aptidao == OrigemAptidao.LEGADO
    assert avaliar_uv(replace(completo(), apto_cd_legado=True)).origem_aptidao == OrigemAptidao.LEGADO
    assert avaliar_uv(SituacaoUV()).origem_aptidao is None


@pytest.mark.parametrize('numero', [0, 9, True, 1.5])
def test_aula_invalida(numero):
    with pytest.raises(ValueError):
        AulaConcluida(numero)


def test_evidencia_exige_identificacao_humana():
    with pytest.raises(ValueError):
        EvidenciaValidada(None)


def test_reposicao_exige_modalidade_conhecida():
    with pytest.raises(ValueError):
        AulaConcluida(1, 'dispensa')
