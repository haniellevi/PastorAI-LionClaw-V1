"""Pure CD evaluation, without enrollment, issuance or leadership promotion.

Callers supply trusted records scoped to one church/person and revalidate
coordination capabilities on the server. IDs here record provenance, never
establish authorization. Reencontro, apto_lider, appointment and Enviar remain
independent. No persistence, tools or runtime integration in this slice.
"""
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.domain.uv import ModalidadeAula, OrigemAptidao

# Provisional owner decisions, subject to review before merge.
AULAS_POR_MODULO = (10,) * 6
NIVEIS: tuple[tuple[int, ...], ...] = ()  # Configurable; no invented grouping/names.
EXIGIR_TODAS_AULAS = True  # Registered replacement counts; no percentage.
PROGRESSAO_LINEAR = True
MATRICULAS_ATIVAS_POR_MODULO = 1  # Per person, including across curriculum versions.
EXIGIR_CONFIRMACAO_COORDENACAO = True  # Certification only; never grants leadership.


def _identidade(valor: UUID) -> None:
    if not isinstance(valor, UUID):
        raise ValueError('Registro exige identificação')


def _texto(valor: str) -> None:
    if not isinstance(valor, str) or not valor.strip():
        raise ValueError('Registro exige texto não vazio')


@dataclass(frozen=True)
class CurriculoCD:
    versao: str
    aulas_por_modulo: tuple[int, ...] = AULAS_POR_MODULO
    niveis: tuple[tuple[int, ...], ...] = NIVEIS

    def __post_init__(self) -> None:
        _texto(self.versao)
        if not self.aulas_por_modulo or any(type(n) is not int or n < 1 for n in self.aulas_por_modulo):
            raise ValueError('Currículo exige aulas por módulo')
        agrupados = tuple(n for nivel in self.niveis for n in nivel)
        if self.niveis and (
            any(not nivel for nivel in self.niveis)
            or any(type(n) is not int for n in agrupados)
            or sorted(agrupados) != list(range(1, len(self.aulas_por_modulo) + 1))
        ):
            raise ValueError('Níveis devem agrupar cada módulo uma vez')


@dataclass(frozen=True)
class AulaCD:
    numero: int
    modalidade: ModalidadeAula = ModalidadeAula.REGULAR

    def __post_init__(self) -> None:
        if type(self.numero) is not int or self.numero < 1:
            raise ValueError('Número de aula inválido')
        if not isinstance(self.modalidade, ModalidadeAula):
            raise ValueError('Modalidade de aula inválida')


@dataclass(frozen=True)
class EquivalenciaCD:
    """Only construct after server validation of the coordinator's capability."""
    evidencia: str
    origem: str
    coordenador_id: UUID

    def __post_init__(self) -> None:
        _texto(self.evidencia)
        _texto(self.origem)
        _identidade(self.coordenador_id)


@dataclass(frozen=True)
class ConclusaoModulo:
    id: UUID
    pessoa_id: UUID
    versao_curriculo: str
    modulo: int
    aulas: tuple[AulaCD, ...] = ()
    equivalencia: EquivalenciaCD | None = None

    def __post_init__(self) -> None:
        _identidade(self.id)
        _identidade(self.pessoa_id)
        _texto(self.versao_curriculo)
        if self.equivalencia is not None and not isinstance(self.equivalencia, EquivalenciaCD):
            raise ValueError('Equivalência exige registro validado')


@dataclass(frozen=True)
class CertificadoCD:
    pessoa_id: UUID
    versao_curriculo: str
    conclusoes_usadas: tuple[UUID, ...]
    emissor_id: UUID
    emitido_em: date
    revogado_em: date | None = None

    def __post_init__(self) -> None:
        _identidade(self.pessoa_id)
        _identidade(self.emissor_id)
        _texto(self.versao_curriculo)
        if not self.conclusoes_usadas or len(set(self.conclusoes_usadas)) != len(self.conclusoes_usadas):
            raise ValueError('Certificado exige conclusões únicas')
        for identificador in self.conclusoes_usadas:
            _identidade(identificador)
        if type(self.emitido_em) is not date or (
            self.revogado_em is not None and (
                type(self.revogado_em) is not date or self.revogado_em < self.emitido_em
            )
        ):
            raise ValueError('Datas do certificado inválidas')


@dataclass(frozen=True)
class SituacaoCD:
    pessoa_id: UUID
    versao_curriculo: str
    apto_proxima_cd: bool = False
    origem_aptidao: OrigemAptidao | None = None
    conclusoes: tuple[ConclusaoModulo, ...] = ()
    # Trusted active enrollments across versions; uniqueness is person/module.
    matriculas_ativas: tuple[int, ...] = ()
    confirmado_por: UUID | None = None
    certificado: CertificadoCD | None = None


@dataclass(frozen=True)
class ResultadoCD:
    pode_ingressar: bool
    modulos_concluidos: tuple[int, ...]
    modulos_disponiveis: tuple[int, ...]
    pode_certificar: bool
    certificado_valido: bool


def avaliar_cd(curriculo: CurriculoCD, situacao: SituacaoCD) -> ResultadoCD:
    """Evaluate this version only; all modules are mandatory, in linear order.

    Confirmation is a trusted coordination record, not a new permission check.
    Returning eligibility never creates an enrollment or certificate.
    """
    _identidade(situacao.pessoa_id)
    if situacao.versao_curriculo != curriculo.versao:
        raise ValueError('Versão do currículo divergente')
    if situacao.confirmado_por is not None:
        _identidade(situacao.confirmado_por)
    total = len(curriculo.aulas_por_modulo)

    def validar_modulo(numero: int) -> None:
        if type(numero) is not int or not 1 <= numero <= total:
            raise ValueError('Módulo fora do currículo')

    for modulo in situacao.matriculas_ativas:
        validar_modulo(modulo)
    if len(set(situacao.matriculas_ativas)) != len(situacao.matriculas_ativas):
        raise ValueError('Uma matrícula ativa por pessoa e módulo')
    registros = {}
    ids = set()
    for registro in (*situacao.conclusoes, *((situacao.certificado,) if situacao.certificado else ())):
        if registro.pessoa_id != situacao.pessoa_id or registro.versao_curriculo != curriculo.versao:
            raise ValueError('Registro de outra pessoa ou versão')
    for conclusao in situacao.conclusoes:
        validar_modulo(conclusao.modulo)
        if conclusao.modulo in registros or conclusao.id in ids:
            raise ValueError('Conclusão duplicada')
        registros[conclusao.modulo] = conclusao
        ids.add(conclusao.id)
        if any(a.numero > curriculo.aulas_por_modulo[conclusao.modulo - 1] for a in conclusao.aulas):
            raise ValueError('Aula fora do currículo')
    ingresso = situacao.apto_proxima_cd is True and isinstance(situacao.origem_aptidao, OrigemAptidao)
    concluidos = []
    for modulo in range(1, total + 1):
        registro = registros.get(modulo)
        if registro is None or not (
            registro.equivalencia is not None
            or {a.numero for a in registro.aulas} == set(range(1, curriculo.aulas_por_modulo[modulo - 1] + 1))
        ):
            break
        concluidos.append(modulo)
    proximo = len(concluidos) + 1
    disponiveis = (proximo,) if ingresso and proximo <= total and proximo not in situacao.matriculas_ativas else ()
    certificar = ingresso and len(concluidos) == total and situacao.confirmado_por is not None
    certificado = situacao.certificado
    valido = bool(
        certificar and certificado is not None and certificado.revogado_em is None
        and set(certificado.conclusoes_usadas) == ids
    )
    return ResultadoCD(ingresso, tuple(concluidos), disponiveis, certificar, valido)
