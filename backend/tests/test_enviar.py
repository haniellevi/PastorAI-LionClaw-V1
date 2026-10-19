"""Contrato de avaliação, sem persistência, promoção ou provedores."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from itertools import product
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.enviar import (
    AVISO_LEGADO,
    CRITERIOS_PROVISORIOS,
    EvidenciasEnviar,
    EstadoEvidencia,
    SituacaoEnviar,
    avaliar_aptidao,
)
from app.services.enviar_read import ler_pendencias_pessoa


COMPROVADA = EstadoEvidencia.COMPROVADA
PENDENTE = EstadoEvidencia.PENDENTE
NAO_INFORMADA = EstadoEvidencia.NAO_INFORMADA
REVOGADA = EstadoEvidencia.REVOGADA
INDISPONIVEL = EstadoEvidencia.INDISPONIVEL
COMPLETAS = EvidenciasEnviar(uv=COMPROVADA, cd=COMPROVADA, reencontro=COMPROVADA)


@pytest.mark.parametrize("estados", tuple(product(EstadoEvidencia, repeat=3)))
def test_combinacoes_exigem_tres_criterios_distintos_e_decisao_humana(estados):
    evidencias = EvidenciasEnviar(uv=estados[0], cd=estados[1], reencontro=estados[2])
    resultado = avaliar_aptidao(evidencias)
    if REVOGADA in estados:
        assert resultado.situacao == SituacaoEnviar.BLOQUEADO
        assert resultado.motivo == "evidencia_revogada"
    elif all(estado == COMPROVADA for estado in estados):
        assert resultado.situacao == SituacaoEnviar.APTO_PARA_AVALIACAO
        assert resultado.pendencias == ()
    else:
        assert resultado.situacao == SituacaoEnviar.PENDENTE
        assert tuple(p.criterio for p in resultado.pendencias) == tuple(
            criterio for criterio, estado in zip(CRITERIOS_PROVISORIOS, estados)
            if estado != COMPROVADA
        )
        assert tuple(p.estado for p in resultado.pendencias) == tuple(
            estado for estado in estados if estado != COMPROVADA
        )
    assert resultado.decisao_humana_exigida is True
    assert resultado.revisao_pastoral_lideranca is False
    assert evidencias == EvidenciasEnviar(uv=estados[0], cd=estados[1], reencontro=estados[2])


@pytest.mark.parametrize("campo,motivo", [("csim", "csim"), ("arquivada", "pessoa_arquivada")])
@pytest.mark.parametrize("base", [COMPLETAS, EvidenciasEnviar(), replace(COMPLETAS, cd=REVOGADA)])
def test_impedimentos_prevalecem_sobre_formacao(campo, motivo, base):
    resultado = avaliar_aptidao(replace(base, **{campo: True}))
    assert resultado.situacao == SituacaoEnviar.BLOQUEADO
    assert resultado.motivo == motivo
    assert resultado.decisao_humana_exigida


@pytest.mark.parametrize("campo", CRITERIOS_PROVISORIOS)
@pytest.mark.parametrize("lideranca_existente", [False, True])
def test_revogacao_bloqueia_novas_nomeacoes_e_sinaliza_revisao(campo, lideranca_existente):
    resultado = avaliar_aptidao(replace(
        COMPLETAS, **{campo: REVOGADA}, lideranca_existente=lideranca_existente,
    ))
    assert resultado.situacao == SituacaoEnviar.BLOQUEADO
    assert resultado.motivo == "evidencia_revogada"
    assert resultado.revisao_pastoral_lideranca is lideranca_existente


def test_revogacao_sinaliza_revisao_mesmo_com_outros_impedimentos():
    resultado = avaliar_aptidao(replace(
        COMPLETAS, uv=REVOGADA, csim=True, arquivada=True, lideranca_existente=True,
    ))
    assert resultado.situacao == SituacaoEnviar.BLOQUEADO
    assert resultado.revisao_pastoral_lideranca


@pytest.mark.parametrize("base", [EvidenciasEnviar(), COMPLETAS, replace(COMPLETAS, cd=REVOGADA)])
def test_legado_e_origem_nao_e_certificado_nem_rebaixamento(base):
    evidencias = replace(base, apto_lider_legado=True, lideranca_existente=True)
    resultado = avaliar_aptidao(evidencias)
    assert resultado.situacao == avaliar_aptidao(base).situacao
    assert resultado.aviso_legado == (None if base == COMPLETAS else AVISO_LEGADO)
    assert evidencias.apto_lider_legado is True
    assert evidencias.lideranca_existente is True
    with pytest.raises(FrozenInstanceError):
        resultado.situacao = SituacaoEnviar.APTO_PARA_AVALIACAO


@pytest.mark.parametrize("etapa", [None, "ganhar", "discipular", "enviar"])
@pytest.mark.parametrize("apto_lider", [False, True])
def test_leitura_pura_nao_infere_formacao_da_flag_ou_etapa(etapa, apto_lider):
    igreja_id = uuid4()
    pessoa = SimpleNamespace(
        igreja_id=igreja_id, apto_lider=apto_lider, sem_interesse=False,
        arquivada_em=None, etapa=etapa,
    )
    antes = vars(pessoa).copy()
    resultado = ler_pendencias_pessoa(pessoa, igreja_id=igreja_id)
    assert resultado.situacao == SituacaoEnviar.PENDENTE
    assert [(p.criterio, p.estado) for p in resultado.pendencias] == [
        ("uv", NAO_INFORMADA), ("cd", NAO_INFORMADA), ("reencontro", NAO_INFORMADA),
    ]
    assert resultado.pendencias[0].descricao == "UV: referência não informada"
    assert resultado.pendencias[1].descricao == "CD certificado: referência não informada"
    assert resultado.aviso_legado == (AVISO_LEGADO if apto_lider else None)
    assert vars(pessoa) == antes


@pytest.mark.parametrize("campo,valor,motivo", [
    ("sem_interesse", True, "csim"),
    ("arquivada_em", datetime(2026, 10, 18, tzinfo=timezone.utc), "pessoa_arquivada"),
])
def test_leitura_preserva_impedimentos_da_pessoa(campo, valor, motivo):
    igreja_id = uuid4()
    pessoa = SimpleNamespace(igreja_id=igreja_id, apto_lider=True,
                             sem_interesse=False, arquivada_em=None, etapa="enviar")
    setattr(pessoa, campo, valor)
    assert ler_pendencias_pessoa(pessoa, igreja_id=igreja_id).motivo == motivo


def test_leitura_recusa_pessoa_de_outra_igreja():
    pessoa = SimpleNamespace(igreja_id=uuid4())
    with pytest.raises(ValueError, match="igreja"):
        ler_pendencias_pessoa(pessoa, igreja_id=uuid4())
