"""Triagem semântica em modo sombra via TypeSafe/Jev (pós-V1).

O roteador do orquestrador (`app.agent.nodes.route_intent`) decide por regex e
listas de palavras. Este módulo faz, sobre a mesma mensagem, perguntas tipadas
ao Jev (System One da TypeSafe) para medir onde as regras erram — e onde nada
decide hoje (risco pastoral/crise).

Contrato do modo sombra:
  * nenhuma resposta do Jev altera rota, resposta, consentimento, opt-out,
    etapa G12 ou tool; o runtime só grava um evento auditável com as
    probabilidades, sem o texto da mensagem;
  * desligado por padrão: só roda para igrejas listadas explicitamente em
    `JEV_SHADOW_TRIAGE_IGREJA_IDS`, com `TYPESAFE_API_KEY` configurada e com o
    guard global de efeitos externos aberto (`ALLOW_REAL_SENDS`);
  * o corpo da mensagem sai como a pessoa escreveu, redigindo apenas CPF,
    e-mail, telefones (inclusive formatados) e sequências de 7+ dígitos
    (`redact_for_egress`). Nome, endereço e conteúdo pastoral sensível (fé,
    saúde, crise) SAEM em claro para a TypeSafe: exige DPA antes de listar
    qualquer igreja. Os únicos campos adicionados pelo servidor são o canal e
    um booleano de papel;
  * qualquer falha (rede, timeout, resposta inesperada) vira `None` — o turno
    do agente nunca depende deste módulo.

Ainda não está ligado ao turno: `app/config.py`, `app/agent/runtime.py` e
`app/workers/queue_worker.py` estão congelados pelo gate offline D3
(`tests/test_d2b2b2_decision_packet_docs.py`). Por isso a configuração vive
aqui, e a integração é uma única chamada a `log_shadow_triage` no runtime,
logo após os eventos do turno serem auditados e antes do retorno de handoff —
a ser feita somente quando esse gate for revisado.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.orm import Session

from app.agent.masking import log_agent_event, mask_text
from app.domain import consent as consent_rules
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
    """Configuração própria (ver nota sobre o congelamento de `app/config.py`)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Lista de igreja_id separados por vírgula. Vazio = desligado.
    jev_shadow_triage_igreja_ids: str = Field(default="")
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
