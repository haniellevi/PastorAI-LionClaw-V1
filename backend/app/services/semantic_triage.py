"""Triagem semântica em modo sombra via TypeSafe/Jev (pós-V1).

O roteador do orquestrador (`app.agent.nodes.route_intent`) decide por regex e
listas de palavras. Este módulo faz, sobre a mesma mensagem, perguntas tipadas
ao Jev (System One da TypeSafe) para medir onde as regras erram — e onde nada
decide hoje (risco pastoral/crise).

Contrato do modo sombra:
  * nenhuma resposta do Jev altera rota, resposta, consentimento, opt-out,
    etapa G12 ou tool; o runtime só grava um evento auditável com as
    probabilidades, sem o texto da mensagem;
  * desligado por padrão: só roda para igrejas listadas explicitamente (no
    Console da Plataforma ou em `JEV_SHADOW_TRIAGE_IGREJA_IDS`), com chave
    configurada (console ou `TYPESAFE_API_KEY`) e com o guard global de efeitos
    externos aberto (`ALLOW_REAL_SENDS`, só no ambiente);
  * o corpo da mensagem sai como a pessoa escreveu, redigindo apenas CPF,
    e-mail, telefones (inclusive formatados) e sequências de 7+ dígitos
    (`redact_for_egress`). Nome, endereço e conteúdo pastoral sensível (fé,
    saúde, crise) SAEM em claro para a TypeSafe: exige DPA antes de listar
    qualquer igreja. Os únicos campos adicionados pelo servidor são o canal e
    um booleano de papel;
  * qualquer falha (rede, timeout, resposta inesperada) vira `None` — o turno
    do agente nunca depende deste módulo.

Ainda não está ligado ao turno. O gate D3 (testes de hash) foi removido na
Fase 0 do plano MVP; a ligação segue a trilha Jev de
`docs/ops/MVP-PLANO-SIMPLIFICACAO.md`: avaliação offline primeiro
(`scripts/jev_eval.py`), depois sombra chamada fora da transação do turno,
só com DPA e termo LGPD atualizados.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import os
import re
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final

import httpx
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.agent.masking import log_agent_event, mask_text
from app.db.models import PlatformJevSettings
from app.domain import consent as consent_rules
from app.services.crypto import (
    SecretDecryptionError,
    SecretsConfigError,
    decrypt_secret,
)
from app.services.outbound_guard import external_sends_allowed, log_suppressed

if TYPE_CHECKING:
    from app.agent.context import TrustedAgentContext

logger = logging.getLogger("pastorai.services.semantic_triage")

EVENTO_SHADOW = "jev_shadow_triage"

# Telefones brasileiros com separadores, que `mask_text` não pega, como
# "+55 (DD) 9XXXX-XXXX", "DD 9XXXX-XXXX" ou "XXXX XXXX".
_PHONE_RE = re.compile(
    r"(?:\+?55[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?)?9?\d{4}[\s.-]\d{4}\b"
)


def redact_for_egress(texto: str) -> str:
    """Redação aplicada antes de qualquer envio à TypeSafe.

    Parcial por natureza: nome, endereço e relato pastoral continuam no texto.
    """
    return _PHONE_RE.sub("***", mask_text(texto))


class TriageSettings(BaseSettings):
    """Configuração do ambiente; o console pode sobrepor (`effective_settings`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Lista de igreja_id separados por vírgula. Vazio = desligado.
    jev_shadow_triage_igreja_ids: str = Field(default="")
    # Lista ativa do Tier A. Ela nunca herda a lista de modo sombra.
    jev_enabled_igreja_ids: str = Field(default="")
    typesafe_api_key: str = Field(default="")
    typesafe_api_url: str = Field(default="https://api.typesafe.ai/v1/systemone")
    typesafe_model: str = Field(default="jev-latest")
    typesafe_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @field_validator("typesafe_api_url")
    @classmethod
    def _url_https(cls, value: str) -> str:
        # O header Authorization carrega a chave: nunca em texto claro.
        if not value.startswith("https://"):
            raise ValueError("TYPESAFE_API_URL precisa usar https://")
        return value


@lru_cache
def get_triage_settings() -> TriageSettings:
    return TriageSettings()


@dataclass(frozen=True)
class EffectiveTriageSettings:
    """Ambiente sobreposto pelo que o Console da Plataforma salvou."""

    settings: TriageSettings
    # "console", "ambiente" ou None (sem chave utilizável).
    chave_origem: str | None
    # Chave salva que não decifra (SECRETS_ENCRYPTION_KEY trocada ou ausente).
    chave_ilegivel: bool
    chave_atualizada_em: dt.datetime | None
    dpa_assinado_em: dt.date | None


def console_table_exists(session: Session) -> bool:
    # Antes da migration `20260926_120446` a tabela não existe e vale só o
    # ambiente: o deploy do código não depende dessa migration.
    return bool(
        session.execute(
            text("select to_regclass('public.platform_jev_settings') is not null")
        ).scalar()
    )


def load_console_settings(session: Session) -> PlatformJevSettings | None:
    if not console_table_exists(session):
        return None
    return session.execute(
        select(PlatformJevSettings).where(PlatformJevSettings.id == 1)
    ).scalar_one_or_none()


def effective_settings(
    session: Session, base: TriageSettings | None = None
) -> EffectiveTriageSettings:
    """Configuração em vigor: o que o console salvou vale sobre o ambiente.

    Campo nulo no console cai no ambiente. A lista de igrejas, depois de salva
    pelo console, é do console (vazia = nenhuma). A URL da API é só do
    ambiente: editável pelo console, desviaria a chave para outro servidor.
    """
    base = base or get_triage_settings()
    row = load_console_settings(session)
    origem = "ambiente" if is_configured(base) else None
    if row is None:
        return EffectiveTriageSettings(base, origem, False, None, None)
    updates: dict[str, Any] = {
        "jev_shadow_triage_igreja_ids": ",".join(str(i) for i in row.igreja_ids or []),
    }
    ilegivel = False
    if row.api_key_encrypted:
        try:
            updates["typesafe_api_key"] = decrypt_secret(row.api_key_encrypted)
            origem = "console"
        except (SecretDecryptionError, SecretsConfigError):
            # Não cai em silêncio na chave do ambiente: o master salvou outra.
            logger.warning("Chave do Jev salva no console não pôde ser decifrada")
            updates["typesafe_api_key"] = ""
            origem = None
            ilegivel = True
    if row.modelo:
        updates["typesafe_model"] = row.modelo
    if row.timeout_seconds is not None:
        updates["typesafe_timeout_seconds"] = float(row.timeout_seconds)
    return EffectiveTriageSettings(
        settings=base.model_copy(update=updates),
        chave_origem=origem,
        chave_ilegivel=ilegivel,
        chave_atualizada_em=row.api_key_updated_at,
        dpa_assinado_em=row.dpa_assinado_em,
    )


# Intenções candidatas. `outro` garante uma saída quando nada se aplica.
INTENCOES: dict[str, str] = {
    "relatorio_celula": (
        "Relatório de reunião de célula: presentes, visitantes, decisões, oferta "
        "ou observações do encontro."
    ),
    "pedido_oracao": "Pede oração por si ou por alguém.",
    "interesse_visitar": (
        "Quer conhecer a igreja ou uma célula, pergunta horário/endereço de culto "
        "ou de reunião."
    ),
    "contato_comercial": (
        "Oferta de produto/serviço, cobrança, orçamento, publicidade ou outro "
        "contato comercial sem interesse ministerial."
    ),
    "fora_da_cidade": (
        "Diz que mora em outra cidade/estado ou longe demais para frequentar."
    ),
    "conversa_geral": "Saudação, agradecimento, dúvida ou conversa pastoral comum.",
    "outro": "Nenhuma das anteriores.",
}


@dataclass(frozen=True)
class ShadowTriage:
    """Respostas tipadas de uma chamada; nunca contém o texto da mensagem."""

    modelo: str
    risco_pastoral: float
    pede_optout: float
    aceita_termo: float | None
    intencao: str
    intencao_confianca: float
    latencia_ms: int
    tokens_in: int
    tokens_out: int

    def to_log_payload(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo,
            "risco_pastoral": round(self.risco_pastoral, 3),
            "pede_optout": round(self.pede_optout, 3),
            "aceita_termo": (
                None if self.aceita_termo is None else round(self.aceita_termo, 3)
            ),
            "intencao": self.intencao,
            "intencao_confianca": round(self.intencao_confianca, 3),
            "latenciaMs": self.latencia_ms,
            "tokensIn": self.tokens_in,
            "tokensOut": self.tokens_out,
        }


def is_configured(settings: TriageSettings) -> bool:
    return bool(settings.typesafe_api_key.strip())


def parse_allowlist(raw: str) -> tuple[set[uuid.UUID], int]:
    """Ids válidos da lista e quantos itens inválidos foram ignorados."""
    allowed: set[uuid.UUID] = set()
    invalid = 0
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            allowed.add(uuid.UUID(item))
        except ValueError:
            invalid += 1
    return allowed, invalid


def shadow_enabled_for(settings: TriageSettings, igreja_id: uuid.UUID) -> bool:
    """True só com chave configurada e a igreja na lista explícita."""
    if not is_configured(settings):
        return False
    allowed, invalid = parse_allowlist(settings.jev_shadow_triage_igreja_ids)
    if invalid:
        logger.warning("JEV_SHADOW_TRIAGE_IGREJA_IDS contém um id inválido")
    return igreja_id in allowed


# Tier A ----------------------------------------------------------------------
# Estas bandas são iniciais e não calibradas. Aferição em holdout e aprovação
# nominal continuam fora desta mudança; não devem ser ajustadas por casos reais.
TIER_A_NEGATIVE_MAX = 0.10
TIER_A_POSITIVE_MIN = 0.90
TIER_A_HTTP_MAX_SECONDS = 1.2
# Nenhuma versão tem aprovação de release nesta mudança. Uma alteração futura
# revisada deve vincular métricas reais, versão de perguntas/modelo/limiares e
# decisão nominal antes de preencher este identificador.
TIER_A_APPROVED_RELEASE_ID: Final[str | None] = None
_TIER_A_QUESTION_IDS = ("risco_crise", "pede_humano", "pede_optout")


class TierAError(str, Enum):
    """Motivos enumerados, sem texto pastoral ou detalhes do provedor."""

    GATE_FECHADO = "gate_fechado"
    HTTP = "http"
    INCONCLUSIVO = "inconclusivo"
    LIMITE_ENTRADA = "limite_entrada"
    SCHEMA_INVALIDO = "schema_invalido"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class TierADecision:
    """Resultado finito do batch Noul, pronto para a política do worker."""

    risco_crise: bool
    pede_humano: bool
    pede_optout: bool
    handoff: bool
    erro: TierAError | None
    latencia_ms: int

    def to_log_payload(self) -> dict[str, Any]:
        return {
            "risco_crise": self.risco_crise,
            "pede_humano": self.pede_humano,
            "pede_optout": self.pede_optout,
            "handoff": self.handoff,
            "erro": None if self.erro is None else self.erro.value,
            "latencia_ms": self.latencia_ms,
        }


def _tier_a_failure(error: TierAError, *, latencia_ms: int = 0) -> TierADecision:
    return TierADecision(
        risco_crise=False,
        pede_humano=False,
        pede_optout=False,
        handoff=True,
        erro=error,
        latencia_ms=max(0, int(latencia_ms)),
    )


def _parse_active_allowlist(raw: object) -> frozenset[uuid.UUID] | None:
    """Parse the active list atomically: one malformed item disables all."""

    if not isinstance(raw, str):
        return None
    if not raw.strip():
        return frozenset()
    values = raw.split(",")
    if any(not value.strip() for value in values):
        return None
    try:
        allowed = frozenset(uuid.UUID(value.strip()) for value in values)
    except ValueError:
        return None
    return allowed if len(allowed) == len(values) else None


def tier_a_listed_for(settings: TriageSettings, igreja_id: uuid.UUID) -> bool:
    """Return only the explicit active-flag decision, never the shadow flag."""

    allowed = _parse_active_allowlist(settings.jev_enabled_igreja_ids)
    return allowed is not None and igreja_id in allowed


def tier_a_enabled_from_environment(igreja_id: uuid.UUID) -> bool:
    """Read only the activation list before parsing optional transport config.

    This leaves legacy turns untouched when the active list is absent, even if
    an unrelated TypeSafe URL or timeout setting is malformed.
    """

    allowed = _parse_active_allowlist(os.environ.get("JEV_ENABLED_IGREJA_IDS", ""))
    return allowed is not None and igreja_id in allowed


def tier_a_optout_confirmation_key(
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> str:
    """Expose the Tier A key alongside its active-decision contract."""

    return consent_rules.tier_a_optout_confirmation_key(igreja_id, conversation_id)


def tier_a_egress_allowed(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    *,
    approved_release_id: str | None = None,
) -> bool:
    """Gate the active provider call; release approval is absent by default.

    A future reviewed release may add an immutable code identifier and pass a
    matching configuration approval only after holdout evidence and the
    owner's nominal decision. This function never infers approval from a flag,
    DPA date or configured key.
    """

    return bool(
        TIER_A_APPROVED_RELEASE_ID is not None
        and approved_release_id == TIER_A_APPROVED_RELEASE_ID
        and tier_a_listed_for(effective.settings, igreja_id)
        and is_configured(effective.settings)
        and not effective.chave_ilegivel
        and effective.dpa_assinado_em is not None
        and external_sends_allowed()
    )


def build_tier_a_request(texto: str, *, model: str) -> dict[str, Any]:
    """Build the sole Tier A batch with its fixed, public evaluator ids."""

    return {
        "state": {
            "mensagem": redact_for_egress(texto),
            "canal": "WhatsApp oficial de uma igreja evangélica",
        },
        "model": model,
        "questions": {
            "risco_crise": {
                "type": "noul",
                "instructions": (
                    "A `mensagem` tem sinal de crise, autoagressão, violência "
                    "ou risco imediato que exige atenção humana?"
                ),
                "criteria": {
                    "true": "Há risco atual ou iminente à integridade ou à vida.",
                    "false": "Não há sinal de crise ou risco imediato.",
                },
            },
            "pede_humano": {
                "type": "noul",
                "instructions": (
                    "A `mensagem` pede claramente atendimento de uma pessoa, "
                    "pastor ou liderança?"
                ),
                "criteria": {
                    "true": "Há pedido de atendimento humano.",
                    "false": "Não há pedido de atendimento humano.",
                },
            },
            "pede_optout": {
                "type": "noul",
                "instructions": (
                    "A `mensagem` provavelmente pede interrupção das mensagens "
                    "da igreja neste canal?"
                ),
                "criteria": {
                    "true": "Há pedido para parar comunicações neste canal.",
                    "false": "Não há pedido para parar comunicações neste canal.",
                },
            },
        },
    }


def _noul_signal(value: object) -> bool | None:
    """Classify one strict Noul number; ``None`` is the uncalibrated middle."""

    if type(value) not in (int, float):
        raise ValueError("noul não numérico")
    try:
        probability = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError("noul fora do intervalo") from exc
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError("noul fora do intervalo")
    if probability >= TIER_A_POSITIVE_MIN:
        return True
    if probability <= TIER_A_NEGATIVE_MAX:
        return False
    return None


def parse_tier_a_response(
    body: object,
    *,
    latencia_ms: int,
) -> TierADecision:
    """Parse a response exactly; malformed data is always a safe handoff."""

    try:
        if not isinstance(body, dict) or not set(body) <= {"answers", "model", "usage"}:
            raise ValueError("corpo inválido")
        answers = body.get("answers")
        if not isinstance(answers, dict) or set(answers) != set(_TIER_A_QUESTION_IDS):
            raise ValueError("answers inválidas")
        signals: dict[str, bool | None] = {}
        for question_id in _TIER_A_QUESTION_IDS:
            answer = answers[question_id]
            if not isinstance(answer, dict) or set(answer) != {"type", "noul"}:
                raise ValueError("answer inválida")
            if answer["type"] != "noul":
                raise ValueError("tipo inválido")
            signals[question_id] = _noul_signal(answer["noul"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return _tier_a_failure(TierAError.SCHEMA_INVALIDO, latencia_ms=latencia_ms)

    risco_crise = signals["risco_crise"] is True
    pede_humano = signals["pede_humano"] is True
    pede_optout = signals["pede_optout"] is True
    if any(signal is None for signal in signals.values()):
        return TierADecision(
            risco_crise=risco_crise,
            pede_humano=pede_humano,
            pede_optout=pede_optout,
            handoff=True,
            erro=TierAError.INCONCLUSIVO,
            latencia_ms=max(0, int(latencia_ms)),
        )
    return TierADecision(
        risco_crise=risco_crise,
        pede_humano=pede_humano,
        pede_optout=pede_optout,
        handoff=risco_crise or pede_humano,
        erro=None,
        latencia_ms=max(0, int(latencia_ms)),
    )


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("chave JSON duplicada")
        result[key] = value
    return result


def parse_tier_a_json(raw: bytes | str, *, latencia_ms: int) -> TierADecision:
    """Decode provider JSON without silently accepting duplicate object keys."""

    try:
        body = json.loads(raw, object_pairs_hook=_reject_duplicate_json_keys)
    except (TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        return _tier_a_failure(TierAError.SCHEMA_INVALIDO, latencia_ms=latencia_ms)
    return parse_tier_a_response(body, latencia_ms=latencia_ms)


async def run_tier_a(
    effective: EffectiveTriageSettings,
    igreja_id: uuid.UUID,
    texto: str,
    *,
    approved_release_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_seconds: float | None = None,
) -> TierADecision:
    """Run one cancelable, no-retry Tier A batch outside a database session."""

    if not isinstance(texto, str) or not texto.strip():
        return _tier_a_failure(TierAError.SCHEMA_INVALIDO)
    if not tier_a_egress_allowed(
        effective,
        igreja_id,
        approved_release_id=approved_release_id,
    ):
        log_suppressed("JEV", "tier_a")
        return _tier_a_failure(TierAError.GATE_FECHADO)
    settings = effective.settings
    try:
        budget = min(
            float(settings.typesafe_timeout_seconds),
            TIER_A_HTTP_MAX_SECONDS,
            TIER_A_HTTP_MAX_SECONDS
            if timeout_seconds is None
            else float(timeout_seconds),
        )
    except (TypeError, ValueError, OverflowError):
        return _tier_a_failure(TierAError.SCHEMA_INVALIDO)
    if not math.isfinite(budget) or budget <= 0:
        return _tier_a_failure(TierAError.SCHEMA_INVALIDO)
    payload = build_tier_a_request(texto, model=settings.typesafe_model)
    started = time.monotonic()
    try:
        async with asyncio.timeout(budget):
            async with httpx.AsyncClient(
                timeout=budget,
                transport=transport,
            ) as client:
                response = await client.post(
                    settings.typesafe_api_url,
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
                )
                response.raise_for_status()
                body = await response.aread()
    except TimeoutError:
        return _tier_a_failure(
            TierAError.TIMEOUT,
            latencia_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.TimeoutException:
        return _tier_a_failure(
            TierAError.TIMEOUT,
            latencia_ms=int((time.monotonic() - started) * 1000),
        )
    except httpx.HTTPError:
        return _tier_a_failure(
            TierAError.HTTP,
            latencia_ms=int((time.monotonic() - started) * 1000),
        )
    return parse_tier_a_json(
        body,
        latencia_ms=int((time.monotonic() - started) * 1000),
    )


def build_request(
    texto: str,
    *,
    termo_pendente: bool,
    remetente_ministerial: bool,
    model: str,
) -> dict[str, Any]:
    """Monta o corpo do POST /v1/systemone (puro, testável).

    `redact_for_egress` é redação parcial, não anonimização: ver o contrato.
    """
    state = {
        "mensagem": redact_for_egress(texto),
        "canal": "WhatsApp oficial de uma igreja evangélica",
        "remetente_e_lider_ou_pastor": remetente_ministerial,
    }
    questions: dict[str, Any] = {
        "risco_pastoral": {
            "type": "noul",
            "instructions": (
                "A `mensagem` indica que quem escreve, ou alguém que ela menciona, "
                "corre risco à vida ou à integridade física/emocional agora ou em "
                "breve — por exemplo ideação suicida, automutilação, abuso, "
                "violência doméstica, ameaça ou emergência médica?"
            ),
            "criteria": {
                "true": (
                    "Há sinal de risco real que um pastor deveria saber "
                    "imediatamente, mesmo que dito de forma indireta."
                ),
                "false": (
                    "Tristeza, luto, pedido de oração comum ou dificuldade sem "
                    "sinal de risco à vida ou à integridade."
                ),
            },
        },
        "pede_optout": {
            "type": "noul",
            "instructions": (
                "Na `mensagem`, a pessoa pede para parar de receber mensagens ou "
                "comunicações da igreja por este canal?"
            ),
            "criteria": {
                "true": "Pedido para não ser mais contatada ou sair da lista.",
                "false": (
                    "Qualquer outro uso de palavras como 'sair' ou 'parar' (sair "
                    "do trabalho, parar de fumar) ou nenhum pedido desse tipo."
                ),
            },
        },
        "intencao": {
            "type": "choice",
            "instructions": "Qual é a intenção principal da `mensagem`?",
            "criteria": INTENCOES,
        },
    }
    if termo_pendente:
        # Só perguntamos quando há termo pendente: fora desse contexto a
        # pergunta não tem significado e a resposta seria descartada.
        questions["aceita_termo"] = {
            "type": "noul",
            "instructions": (
                "A igreja enviou um termo de consentimento de uso de dados (LGPD) "
                "e aguarda a resposta. A `mensagem` é um aceite claro e sem "
                "ressalvas desse termo?"
            ),
            "criteria": {
                "true": "Aceite inequívoco (ex.: 'aceito', 'sim, pode').",
                "false": (
                    "Recusa, dúvida, aceite com ressalva ('sim, mas não quero…') "
                    "ou mensagem sobre outro assunto."
                ),
            },
        }
    return {"state": state, "model": model, "questions": questions}


def parse_response(body: dict[str, Any], *, latencia_ms: int) -> ShadowTriage:
    """Converte a resposta da API; KeyError/TypeError/ValueError se inválida."""
    answers = body["answers"]
    intencao = answers["intencao"]
    escolha = str(intencao["choice"])
    if escolha not in INTENCOES:
        raise ValueError("intenção fora do conjunto definido")
    aceita = answers.get("aceita_termo")
    usage = body.get("usage") or {}
    return ShadowTriage(
        modelo=str(body.get("model", "")),
        risco_pastoral=float(answers["risco_pastoral"]["noul"]),
        pede_optout=float(answers["pede_optout"]["noul"]),
        aceita_termo=None if aceita is None else float(aceita["noul"]),
        intencao=escolha,
        intencao_confianca=float(intencao.get("confidence", 0.0)),
        latencia_ms=latencia_ms,
        tokens_in=int(usage.get("input_tokens", 0)),
        tokens_out=int(usage.get("output_tokens", 0)),
    )


def run_shadow_triage(
    settings: TriageSettings,
    texto: str,
    *,
    termo_pendente: bool,
    remetente_ministerial: bool,
    transport: httpx.BaseTransport | None = None,
) -> ShadowTriage | None:
    """Uma chamada ao Jev; `None` em qualquer falha (nunca levanta)."""
    if not texto.strip():
        return None
    # Mesmo gate deny-by-default dos demais provedores externos (B2): sem
    # ALLOW_REAL_SENDS nenhum texto sai e nenhum token é gasto.
    if not external_sends_allowed():
        log_suppressed("JEV", "shadow_triage")
        return None
    payload = build_request(
        texto,
        termo_pendente=termo_pendente,
        remetente_ministerial=remetente_ministerial,
        model=settings.typesafe_model,
    )
    started = time.monotonic()
    try:
        with httpx.Client(
            timeout=settings.typesafe_timeout_seconds, transport=transport
        ) as client:
            resp = client.post(
                settings.typesafe_api_url,
                json=payload,
                headers={"Authorization": f"Bearer {settings.typesafe_api_key}"},
            )
        resp.raise_for_status()
        latencia_ms = int((time.monotonic() - started) * 1000)
        return parse_response(resp.json(), latencia_ms=latencia_ms)
    except httpx.HTTPError as exc:
        # Sem corpo/headers no log: a resposta pode ecoar o estado enviado.
        logger.warning("Triagem Jev indisponível: %s", type(exc).__name__)
    except (KeyError, TypeError, ValueError):
        logger.warning("Triagem Jev retornou resposta inesperada")
    return None


def log_shadow_triage(
    session: Session,
    *,
    igreja_id: uuid.UUID,
    conversation_id: uuid.UUID,
    context: TrustedAgentContext,
    texto: str | None,
    route: str | None,
    settings: TriageSettings | None = None,
) -> None:
    """Registra a triagem Jev ao lado da rota decidida pelas regras.

    Modo sombra: nada volta para o turno. Serve só para comparar, com dados
    reais, o que as regras decidiram e o que o Jev teria decidido. O evento
    participa da transação do chamador (quem faz commit é o runtime).
    """
    # Sessão com escopo de tenant roda como `authenticated`, que não lê
    # `platform_jev_settings`: quem ligar o runtime (J1) resolve
    # `effective_settings` numa sessão de plataforma e passa `settings=`.
    settings = settings or get_triage_settings()
    if not shadow_enabled_for(settings, igreja_id):
        return
    termo_pendente = consent_rules.needs_reaccept(
        context.legacy_term.accepted_version,
        context.legacy_term.current_version,
    )
    ministerial = context.privilege.is_ministerial
    result = run_shadow_triage(
        settings,
        texto or "",
        termo_pendente=termo_pendente,
        remetente_ministerial=ministerial,
    )
    payload: dict[str, Any] = {
        "routeRegras": route,
        "termoPendente": termo_pendente,
        "remetenteMinisterial": ministerial,
    }
    if result is None:
        payload["status"] = "indisponivel"
    else:
        payload["status"] = "ok"
        payload.update(result.to_log_payload())
    log_agent_event(
        session,
        igreja_id=igreja_id,
        evento=EVENTO_SHADOW,
        payload=payload,
        conversation_id=conversation_id,
    )
