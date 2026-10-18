"""Adaptador puro de leitura de Pessoa; sem sessão, rota ou escrita.

O chamador deve carregar a pessoa pelo caminho humano autorizado. Este adaptador
valida o escopo recebido, mas não substitui autorização nem consulta liderança.
UV/CD oficiais serão consumidos na fatia 3; nesta fatia estão indisponíveis para
esta leitura, independentemente da presença de schema UV no código ou no banco.
"""
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.enviar import (
    EstadoEvidencia,
    EvidenciasEnviar,
    ResultadoEnviar,
    avaliar_aptidao,
)


class PessoaEnviar(Protocol):
    igreja_id: UUID
    apto_lider: bool
    sem_interesse: bool
    arquivada_em: datetime | None
    etapa: str | None


def ler_pendencias_pessoa(pessoa: PessoaEnviar, *, igreja_id: UUID) -> ResultadoEnviar:
    """Lê campos já carregados, sem inferir certificados de etapa ou apto_lider.

    A flag histórica não comprova Reencontro. A responsabilidade de liderança
    também não pode ser inferida desses campos; não é consultada nesta fatia.
    """
    if not isinstance(igreja_id, UUID) or pessoa.igreja_id != igreja_id:
        raise ValueError("Pessoa fora do escopo da igreja")
    return avaliar_aptidao(EvidenciasEnviar(
        uv=EstadoEvidencia.INDISPONIVEL,
        cd=EstadoEvidencia.INDISPONIVEL,
        reencontro=EstadoEvidencia.PENDENTE,
        csim=pessoa.sem_interesse,
        arquivada=pessoa.arquivada_em is not None,
        apto_lider_legado=pessoa.apto_lider,
    ))
