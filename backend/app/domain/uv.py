"""Universidade da Vida: approved pastoral contract for the five UV slices.

This pure evaluation is not authorization or persistence. Callers must load
trusted, tenant-scoped records and revalidate human capabilities before use.
Individual consolidation (decision/cell/fonovisita) does not prove UV completion
and must not newly grant CD eligibility. Existing eligibility is preserved with
legacy provenance; neither evaluation nor completion enrolls anyone in CD.
"""
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class ModalidadeAula(StrEnum):
    REGULAR = "regular"
    REPOSICAO = "reposicao"


class OrigemAptidao(StrEnum):
    LEGADO = "legado"
    CONCLUSAO_UV = "conclusao_uv"


@dataclass(frozen=True)
class AulaConcluida:
    numero: int
    modalidade: ModalidadeAula = ModalidadeAula.REGULAR

    def __post_init__(self) -> None:
        if type(self.numero) is not int or not 1 <= self.numero <= 8:
            raise ValueError("A UV exige aulas numeradas de 1 a 8")
        if not isinstance(self.modalidade, ModalidadeAula):
            raise ValueError("Informe modalidade regular ou reposição")


@dataclass(frozen=True)
class EvidenciaValidada:
    """Encontro/baptism verified by a human, including prior participation.

    Only construct from validated official records. A previous baptism is
    accepted here and never produces a request to repeat it.
    """
    validada_por: UUID
    anterior: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.validada_por, UUID):
            raise ValueError("A evidência exige identificação do validador humano")


@dataclass(frozen=True)
class SituacaoUV:
    decisao_registrada: bool = False
    responsavel_id: UUID | None = None
    conectado_celula: bool = False
    aulas: tuple[AulaConcluida, ...] = ()
    encontro: EvidenciaValidada | None = None
    batismo: EvidenciaValidada | None = None
    confirmado_por: UUID | None = None
    apto_cd_legado: bool = False


@dataclass(frozen=True)
class ResultadoUV:
    pode_ingressar: bool
    conexao_celula_pendente: bool
    aulas_pendentes: tuple[int, ...]
    concluida: bool
    apto_proxima_cd: bool
    origem_aptidao: OrigemAptidao | None


def avaliar_uv(situacao: SituacaoUV) -> ResultadoUV:
    """Require all eight lessons, Encontro, baptism and responsible approval.

    Cell connection remains an independent follow-up task, with no attendance
    percentage. Legacy CD eligibility never supplies missing UV evidence.
    """
    pode_ingressar = situacao.decisao_registrada and situacao.responsavel_id is not None
    presentes = {aula.numero for aula in situacao.aulas}
    pendentes = tuple(n for n in range(1, 9) if n not in presentes)
    concluida = (
        pode_ingressar and not pendentes
        and situacao.encontro is not None and situacao.batismo is not None
        and situacao.confirmado_por == situacao.responsavel_id
    )
    origem = (
        OrigemAptidao.LEGADO if situacao.apto_cd_legado
        else OrigemAptidao.CONCLUSAO_UV if concluida else None
    )
    return ResultadoUV(
        pode_ingressar=pode_ingressar,
        conexao_celula_pendente=not situacao.conectado_celula,
        aulas_pendentes=pendentes,
        concluida=concluida,
        apto_proxima_cd=situacao.apto_cd_legado or concluida,
        origem_aptidao=origem,
    )
