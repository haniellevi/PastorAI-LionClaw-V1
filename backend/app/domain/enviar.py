"""Contrato puro de Enviar: formação habilita avaliação humana, nunca promoção.

Não autoriza nomeações, não altera apto_lider, papéis ou células. Evidências
precisam vir de registros oficiais da mesma igreja; integrações são posteriores.
"""
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal


# Regras provisórias: aguarda confirmação pastoral. Critérios independentes.
VERSAO_REGRAS: Final = "enviar-v1-provisoria"
STATUS_REGRAS: Final = "aguarda confirmação pastoral"
Criterio = Literal["uv", "cd", "reencontro"]
CRITERIOS_PROVISORIOS: Final[tuple[Criterio, ...]] = ("uv", "cd", "reencontro")
AVISO_LEGADO: Final = "origem legada, comprovação pendente"


class EstadoEvidencia(StrEnum):
    NAO_INFORMADA = "nao_informada"
    COMPROVADA = "comprovada"
    PENDENTE = "pendente"
    INDISPONIVEL = "indisponivel_nesta_base"
    REVOGADA = "revogada"


class SituacaoEnviar(StrEnum):
    APTO_PARA_AVALIACAO = "apto_para_avaliacao"
    PENDENTE = "pendente"
    BLOQUEADO = "bloqueado"


@dataclass(frozen=True)
class EvidenciasEnviar:
    uv: EstadoEvidencia = EstadoEvidencia.PENDENTE
    cd: EstadoEvidencia = EstadoEvidencia.PENDENTE
    reencontro: EstadoEvidencia = EstadoEvidencia.PENDENTE
    csim: bool = False
    arquivada: bool = False
    apto_lider_legado: bool = False
    # Responsabilidade efetiva fornecida pelo chamador, nunca inferida de tipo.
    lideranca_existente: bool = False


@dataclass(frozen=True)
class PendenciaEnviar:
    criterio: Criterio
    estado: EstadoEvidencia
    descricao: str


@dataclass(frozen=True)
class ResultadoEnviar:
    situacao: SituacaoEnviar
    pendencias: tuple[PendenciaEnviar, ...] = ()
    motivo: Literal["pessoa_arquivada", "csim", "evidencia_revogada"] | None = None
    aviso_legado: str | None = None
    revisao_pastoral_lideranca: bool = False
    decisao_humana_exigida: Literal[True] = True
    versao_regras: str = VERSAO_REGRAS
    status_regras: str = STATUS_REGRAS


def avaliar_aptidao(evidencias: EvidenciasEnviar) -> ResultadoEnviar:
    """Avalia pendências; nenhuma saída concede aptidão ou nomeação.

    Revogação impede novas nomeações e sinaliza revisão de liderança existente,
    inclusive havendo outros impedimentos. Não destitui nem rebaixa legados.
    """
    rotulos = {"uv": "UV", "cd": "CD certificado", "reencontro": "Reencontro confirmado"}
    descricoes = {
        EstadoEvidencia.NAO_INFORMADA: "referência não informada",
        EstadoEvidencia.PENDENTE: "comprovação pendente",
        EstadoEvidencia.INDISPONIVEL: "indisponível nesta base",
        EstadoEvidencia.REVOGADA: "evidência revogada",
    }
    estados = (evidencias.uv, evidencias.cd, evidencias.reencontro)
    pendencias = tuple(
        PendenciaEnviar(criterio, estado, f"{rotulos[criterio]}: {descricoes[estado]}")
        for criterio, estado in zip(CRITERIOS_PROVISORIOS, estados)
        if estado != EstadoEvidencia.COMPROVADA
    )
    revogada = EstadoEvidencia.REVOGADA in estados
    motivo = None
    if evidencias.arquivada:
        motivo = "pessoa_arquivada"
    elif evidencias.csim:
        motivo = "csim"
    elif revogada:
        motivo = "evidencia_revogada"
    situacao = (
        SituacaoEnviar.BLOQUEADO if motivo else
        SituacaoEnviar.PENDENTE if pendencias else
        SituacaoEnviar.APTO_PARA_AVALIACAO
    )
    return ResultadoEnviar(
        situacao=situacao,
        pendencias=pendencias,
        motivo=motivo,
        aviso_legado=AVISO_LEGADO if evidencias.apto_lider_legado and pendencias else None,
        revisao_pastoral_lideranca=revogada and evidencias.lideranca_existente,
    )
