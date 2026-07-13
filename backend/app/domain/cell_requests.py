"""Regras puras de Solicitações de célula (Células PR3-PR9 — Domínio Solicitações).

Este módulo NÃO toca o banco: concentra o contrato/validação do `payload_proposto`
discriminado por `tipo` (SPEC §6.3), as constantes de estado/ação e a matriz de
conflito (SPEC §6.8 / E13). Router e serviços transacionais reusam daqui, mantendo
a camada de domínio pura (sem FastAPI/SQLAlchemy) e testável isoladamente.

Tipos de solicitação (`celula_solicitacao.tipo`):
  - campos sensíveis: alterar_dia / alterar_horario / alterar_endereco /
    alterar_anfitriao / alterar_auxiliar
  - membros: transferir_membro / remover_membro
  - multiplicacao

`celula_id` da solicitação é sempre a ORIGEM; nunca confiar em "origem" vinda do
payload (SPEC §6.3).
"""

from __future__ import annotations

import datetime as dt
import re
import uuid

from pydantic import BaseModel, ConfigDict, field_validator

# ---------------------------------------------------------------------------
# Constantes de tipo / status / ação
# ---------------------------------------------------------------------------
TIPO_ALTERAR_DIA = "alterar_dia"
TIPO_ALTERAR_HORARIO = "alterar_horario"
TIPO_ALTERAR_ENDERECO = "alterar_endereco"
TIPO_ALTERAR_ANFITRIAO = "alterar_anfitriao"
TIPO_ALTERAR_AUXILIAR = "alterar_auxiliar"
TIPO_TRANSFERIR_MEMBRO = "transferir_membro"
TIPO_REMOVER_MEMBRO = "remover_membro"
TIPO_MULTIPLICACAO = "multiplicacao"

SENSITIVE_TIPOS: frozenset[str] = frozenset(
    {
        TIPO_ALTERAR_DIA,
        TIPO_ALTERAR_HORARIO,
        TIPO_ALTERAR_ENDERECO,
        TIPO_ALTERAR_ANFITRIAO,
        TIPO_ALTERAR_AUXILIAR,
    }
)
MEMBER_TIPOS: frozenset[str] = frozenset(
    {TIPO_TRANSFERIR_MEMBRO, TIPO_REMOVER_MEMBRO}
)
VALID_TIPOS: frozenset[str] = SENSITIVE_TIPOS | MEMBER_TIPOS | {TIPO_MULTIPLICACAO}

# celula_solicitacao.status
STATUS_AGUARDANDO = "aguardando"
STATUS_APROVADA = "aprovada"
STATUS_REJEITADA = "rejeitada"
STATUS_AJUSTE_SOLICITADO = "ajuste_solicitado"
STATUS_CANCELADA = "cancelada"
# Estados "abertos" (conflitam na criação — E13; canceláveis — E12).
OPEN_STATUSES: frozenset[str] = frozenset(
    {STATUS_AGUARDANDO, STATUS_AJUSTE_SOLICITADO}
)

# celula_solicitacao_evento.acao (trilha append-only)
ACAO_CRIADA = "criada"
ACAO_REENVIADA = "reenviada"
ACAO_APROVADA = "aprovada"
ACAO_REJEITADA = "rejeitada"
ACAO_AJUSTE_SOLICITADO = "ajuste_solicitado"
ACAO_CANCELADA = "cancelada"

# Limites textuais (SPEC §6.1 / E1).
_ENDERECO_MAX = 255
_MOTIVO_MAX = 1000
_NOME_CELULA_MAX = 120
_DIA_MAX = 120
_DESCENDENCIA_MAX = 400

# HH:MM (24h), espelha o CHECK de celulas.horario.
_HORA_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class InvalidPayload(ValueError):
    """Payload de solicitação inválido para o `tipo` — o router mapeia para 422."""


# ---------------------------------------------------------------------------
# Validadores reutilizáveis de borda
# ---------------------------------------------------------------------------
def _require_text(value: str, max_len: int, field: str) -> str:
    trimmed = (value or "").strip()
    if not trimmed:
        raise ValueError(f"{field} é obrigatório")
    if len(trimmed) > max_len:
        raise ValueError(f"{field} deve ter no máximo {max_len} caracteres")
    return trimmed


def _optional_text(value: str | None, max_len: int, field: str) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) > max_len:
        raise ValueError(f"{field} deve ter no máximo {max_len} caracteres")
    return trimmed


def _valid_hora(value: str) -> str:
    trimmed = (value or "").strip()
    if not _HORA_RE.match(trimmed):
        raise ValueError("horario deve estar no formato HH:MM")
    return trimmed


# ---------------------------------------------------------------------------
# Schemas de payload por tipo (extra="forbid": chave desconhecida => 422)
# ---------------------------------------------------------------------------
class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AlterarDiaPayload(_StrictModel):
    dia_reuniao: str

    @field_validator("dia_reuniao")
    @classmethod
    def _dia(cls, v: str) -> str:
        return _require_text(v, _DIA_MAX, "dia_reuniao")


class AlterarHorarioPayload(_StrictModel):
    horario: str

    @field_validator("horario")
    @classmethod
    def _hora(cls, v: str) -> str:
        return _valid_hora(v)


class AlterarEnderecoPayload(_StrictModel):
    endereco: str

    @field_validator("endereco")
    @classmethod
    def _end(cls, v: str) -> str:
        return _require_text(v, _ENDERECO_MAX, "endereco")


class AlterarAnfitriaoPayload(_StrictModel):
    anfitriao_id: uuid.UUID


class AlterarAuxiliarPayload(_StrictModel):
    auxiliar_id: uuid.UUID


class TransferirMembroPayload(_StrictModel):
    pessoa_id: uuid.UUID
    celula_destino_id: uuid.UUID
    motivo: str | None = None

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v: str | None) -> str | None:
        return _optional_text(v, _MOTIVO_MAX, "motivo")


class RemoverMembroPayload(_StrictModel):
    pessoa_id: uuid.UUID
    motivo: str | None = None

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v: str | None) -> str | None:
        return _optional_text(v, _MOTIVO_MAX, "motivo")


class MultiplicacaoPayload(_StrictModel):
    """Payload de `tipo='multiplicacao'` (SPEC §6.3, E7).

    Validações estruturais (aqui, 422 na criação/reenvio): `membros_transferidos_ids`
    mínimo 1. `novo_lider_id` PODE estar fora da lista (regra 2026-07-06: a
    Central pode escolher um apto sem célula, externo à origem). As validações
    de elegibilidade do novo líder (apto/não-CSIM/não lidera célula ativa)
    dependem do banco e rodam no serviço transacional (aprovação).
    """

    idempotency_key: str | None = None
    nome_nova_celula: str
    novo_lider_id: uuid.UUID
    membros_transferidos_ids: list[uuid.UUID]
    dia_reuniao: str | None = None
    horario: str | None = None
    endereco: str | None = None
    anfitriao_id: uuid.UUID | None = None
    auxiliar_id: uuid.UUID | None = None
    data_prevista: dt.date | None = None
    descendencia: str | None = None

    @field_validator("nome_nova_celula")
    @classmethod
    def _nome(cls, v: str) -> str:
        return _require_text(v, _NOME_CELULA_MAX, "nome_nova_celula")

    @field_validator("dia_reuniao")
    @classmethod
    def _dia(cls, v: str | None) -> str | None:
        return _optional_text(v, _DIA_MAX, "dia_reuniao")

    @field_validator("horario")
    @classmethod
    def _hora(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        return _valid_hora(v)

    @field_validator("endereco")
    @classmethod
    def _end(cls, v: str | None) -> str | None:
        return _optional_text(v, _ENDERECO_MAX, "endereco")

    @field_validator("descendencia")
    @classmethod
    def _desc(cls, v: str | None) -> str | None:
        return _optional_text(v, _DESCENDENCIA_MAX, "descendencia")

    @field_validator("idempotency_key")
    @classmethod
    def _idem(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        return trimmed or None

    @field_validator("membros_transferidos_ids")
    @classmethod
    def _membros(cls, v: list[uuid.UUID]) -> list[uuid.UUID]:
        if not v:
            raise ValueError("membros_transferidos_ids: mínimo 1 membro")
        # Dedup preservando ordem.
        seen: set[uuid.UUID] = set()
        unique: list[uuid.UUID] = []
        for m in v:
            if m not in seen:
                seen.add(m)
                unique.append(m)
        return unique

_PAYLOAD_MODELS: dict[str, type[_StrictModel]] = {
    TIPO_ALTERAR_DIA: AlterarDiaPayload,
    TIPO_ALTERAR_HORARIO: AlterarHorarioPayload,
    TIPO_ALTERAR_ENDERECO: AlterarEnderecoPayload,
    TIPO_ALTERAR_ANFITRIAO: AlterarAnfitriaoPayload,
    TIPO_ALTERAR_AUXILIAR: AlterarAuxiliarPayload,
    TIPO_TRANSFERIR_MEMBRO: TransferirMembroPayload,
    TIPO_REMOVER_MEMBRO: RemoverMembroPayload,
    TIPO_MULTIPLICACAO: MultiplicacaoPayload,
}


def validate_payload(tipo: str, payload: dict | None) -> dict:
    """Valida `payload` conforme o `tipo` e devolve a versão NORMALIZADA (JSON-safe).

    Levanta `InvalidPayload` (→ 422) quando o tipo é desconhecido ou o payload não
    satisfaz o schema. UUID/date saem como strings (prontos para JSONB).
    """
    model = _PAYLOAD_MODELS.get(tipo)
    if model is None:
        raise InvalidPayload(f"tipo inválido: {tipo}")
    try:
        obj = model.model_validate(payload or {})
    except ValueError as exc:  # ValidationError deriva de ValueError
        raise InvalidPayload(str(exc)) from exc
    return obj.model_dump(mode="json", exclude_none=False)


def conflict_pessoa_id(tipo: str, payload: dict) -> str | None:
    """`pessoa_id` alvo da solicitação (transferir/remover), para a matriz E13.

    Retorna None para tipos que não são baseados em pessoa.
    """
    if tipo in MEMBER_TIPOS:
        value = payload.get("pessoa_id")
        return str(value) if value else None
    return None


def referenced_pessoa_ids(tipo: str, payload: dict) -> list[str]:
    """TODOS os ids de Pessoa referenciados no payload, por `tipo` (W3.2A).

    Superset de ``conflict_pessoa_id``: usado para validar elegibilidade
    (ex.: pessoa arquivada) de QUALQUER pessoa citada no payload — não só o
    alvo de transferir/remover. `anfitriao_id`/`auxiliar_id` da multiplicação
    são opcionais (podem faltar no payload).
    """
    ids: list[str] = []
    if tipo in MEMBER_TIPOS:
        value = payload.get("pessoa_id")
        if value:
            ids.append(str(value))
    elif tipo == TIPO_ALTERAR_ANFITRIAO:
        value = payload.get("anfitriao_id")
        if value:
            ids.append(str(value))
    elif tipo == TIPO_ALTERAR_AUXILIAR:
        value = payload.get("auxiliar_id")
        if value:
            ids.append(str(value))
    elif tipo == TIPO_MULTIPLICACAO:
        for key in ("novo_lider_id", "anfitriao_id", "auxiliar_id"):
            value = payload.get(key)
            if value:
                ids.append(str(value))
        ids.extend(str(m) for m in payload.get("membros_transferidos_ids") or [])
    return ids
