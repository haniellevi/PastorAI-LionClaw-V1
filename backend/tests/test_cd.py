"""Synthetic tests of the pure CD contract; no persistence or authorization."""
from dataclasses import FrozenInstanceError, replace
from datetime import date
from uuid import UUID

import pytest

from app.domain.cd import (
    AulaCD, CertificadoCD, ConclusaoModulo, CurriculoCD, EquivalenciaCD,
    SituacaoCD, avaliar_cd,
)
from app.domain.uv import ModalidadeAula, OrigemAptidao

PESSOA, COORD, OUTRO = (UUID(int=n) for n in (1, 2, 3))
CURRICULO = CurriculoCD('v1')


def situacao(**kwargs):
    return replace(SituacaoCD(PESSOA, 'v1', True, OrigemAptidao.CONCLUSAO_UV), **kwargs)


def conclusao(modulo, **kwargs):
    return replace(ConclusaoModulo(
        UUID(int=100 + modulo), PESSOA, 'v1', modulo,
        tuple(AulaCD(n) for n in range(1, 11)),
    ), **kwargs)


def completa():
    return situacao(conclusoes=tuple(conclusao(n) for n in range(1, 7)), confirmado_por=COORD)


def certificado():
    return CertificadoCD(PESSOA, 'v1', tuple(c.id for c in completa().conclusoes), COORD, date(2026, 10, 17))


def test_sequencia_e_modulo_anterior_pendente():
    assert avaliar_cd(CURRICULO, situacao()).modulos_disponiveis == (1,)
    assert avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(1),))).modulos_disponiveis == (2,)
    result = avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(2),)))
    assert result.modulos_concluidos == ()
    assert result.modulos_disponiveis == (1,)


@pytest.mark.parametrize('origem', list(OrigemAptidao))
def test_ingresso_uv_ou_legado(origem):
    assert avaliar_cd(CURRICULO, situacao(origem_aptidao=origem)).pode_ingressar


@pytest.mark.parametrize('apto,origem', [(False, None), (False, OrigemAptidao.LEGADO), (True, None), (True, 'inventada')])
def test_inapto_recusado(apto, origem):
    result = avaliar_cd(CURRICULO, situacao(apto_proxima_cd=apto, origem_aptidao=origem))
    assert not result.pode_ingressar and not result.modulos_disponiveis
    assert not result.pode_certificar


def test_reposicao_e_aula_faltante():
    aulas = conclusao(1).aulas[:-1] + (AulaCD(10, ModalidadeAula.REPOSICAO),)
    assert avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(1, aulas=aulas),))).modulos_concluidos == (1,)
    for numero in range(1, 11):
        incompleto = tuple(a for a in aulas if a.numero != numero) + (AulaCD(1),)
        if numero == 1:
            incompleto = tuple(a for a in aulas if a.numero != numero)
        assert not avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(1, aulas=incompleto),))).modulos_concluidos


@pytest.mark.parametrize('evidencia,origem,coordenador', [('', 'curso anterior', COORD), ('registro', '', COORD), ('registro', 'curso anterior', None)])
def test_equivalencia_exige_evidencia_origem_e_coordenacao(evidencia, origem, coordenador):
    with pytest.raises(ValueError):
        EquivalenciaCD(evidencia, origem, coordenador)


def test_equivalencia_registrada_pela_coordenacao():
    equivalencia = EquivalenciaCD('registro sintetico', 'curso anterior', COORD)
    result = avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(1, aulas=(), equivalencia=equivalencia),)))
    assert result.modulos_concluidos == (1,)


@pytest.mark.parametrize('campo,valor', [('versao_curriculo', 'v2'), ('pessoa_id', OUTRO)])
def test_nao_mistura_versoes_ou_pessoas(campo, valor):
    if campo == 'versao_curriculo':
        with pytest.raises(ValueError):
            avaliar_cd(CURRICULO, situacao(**{campo: valor}))
    with pytest.raises(ValueError):
        avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(1, **{campo: valor}),)))
    with pytest.raises(ValueError):
        avaliar_cd(CURRICULO, replace(completa(), certificado=replace(certificado(), **{campo: valor})))


def test_matricula_ativa_unica_bloqueia_novo_ingresso_no_modulo():
    assert not avaliar_cd(CURRICULO, situacao(matriculas_ativas=(1,))).modulos_disponiveis
    with pytest.raises(ValueError):
        avaliar_cd(CURRICULO, situacao(matriculas_ativas=(1, 1)))


def test_certificacao_exige_confirmacao_da_coordenacao():
    assert avaliar_cd(CURRICULO, completa()).pode_certificar
    assert not avaliar_cd(CURRICULO, replace(completa(), confirmado_por=None)).pode_certificar
    assert not avaliar_cd(CURRICULO, replace(completa(), conclusoes=completa().conclusoes[:-1])).pode_certificar


def test_certificado_registro_revogacao_e_conclusoes_usadas():
    assert avaliar_cd(CURRICULO, replace(completa(), certificado=certificado())).certificado_valido
    revogado = replace(certificado(), revogado_em=date(2026, 10, 17))
    assert not avaliar_cd(CURRICULO, replace(completa(), certificado=revogado)).certificado_valido
    invalido = replace(certificado(), conclusoes_usadas=(UUID(int=999),))
    assert not avaliar_cd(CURRICULO, replace(completa(), certificado=invalido)).certificado_valido


def test_avaliacao_nao_matricula_certifica_ou_promove():
    estado = completa()
    assert avaliar_cd(CURRICULO, estado) == avaliar_cd(CURRICULO, estado)
    assert estado.certificado is None and estado.matriculas_ativas == ()
    with pytest.raises(FrozenInstanceError):
        estado.confirmado_por = OUTRO


def test_curriculo_configuravel_sem_nomes_de_niveis():
    curriculo = CurriculoCD('v2', aulas_por_modulo=(2, 2), niveis=((1, 2),))
    estado = SituacaoCD(PESSOA, 'v2', True, OrigemAptidao.LEGADO)
    assert avaliar_cd(curriculo, estado).modulos_disponiveis == (1,)


@pytest.mark.parametrize('numero', [0, True, 1.5])
def test_numero_aula_invalido(numero):
    with pytest.raises(ValueError):
        AulaCD(numero)


@pytest.mark.parametrize('alteracao', [
    {'modulo': 7}, {'modulo': True}, {'aulas': (AulaCD(11),)},
    {'equivalencia': 'sem validacao'},
])
def test_registros_invalidos_recusados(alteracao):
    with pytest.raises(ValueError):
        avaliar_cd(CURRICULO, situacao(conclusoes=(replace(conclusao(1), **alteracao),)))


def test_conclusoes_duplicadas_recusadas():
    with pytest.raises(ValueError):
        avaliar_cd(CURRICULO, situacao(conclusoes=(conclusao(1), conclusao(1))))


@pytest.mark.parametrize('config', [
    {'versao': ''}, {'aulas_por_modulo': ()}, {'aulas_por_modulo': (True,)},
    {'niveis': ((1,),)}, {'niveis': ((1, 2, 3), (3, 4, 5, 6))},
])
def test_curriculo_invalido(config):
    with pytest.raises(ValueError):
        replace(CURRICULO, **config)


@pytest.mark.parametrize('config', [
    {'emissor_id': None}, {'conclusoes_usadas': ()},
    {'revogado_em': date(2026, 10, 16)}, {'emitido_em': None},
])
def test_certificado_exige_proveniencia_e_datas(config):
    with pytest.raises(ValueError):
        replace(certificado(), **config)


def test_modalidade_desconhecida_recusada():
    with pytest.raises(ValueError):
        AulaCD(1, 'dispensa')


def test_certificado_emitido_independe_da_elegibilidade_atual():
    estado = replace(completa(), certificado=certificado(), confirmado_por=None,
                     apto_proxima_cd=False, origem_aptidao=None)
    result = avaliar_cd(CURRICULO, estado)
    assert not result.pode_certificar
    assert result.certificado_valido
