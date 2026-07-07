"""Resolução de destinatários da notificação de um evento (EVT-8 PR2).

Puro, sem I/O — o serviço (``app/services/event_recipients.py``) busca os
candidatos no banco e passa para cá. Espelha ``app/domain/broadcast.py``: as
regras de opt-out e deduplicação ficam determinísticas e testáveis sem banco.

Modelo:
  - **individual**: contatos já validados no PR1 (``event_notify_targets``);
    o serviço resolve ``pessoa_id`` → ``Pessoa`` (telefone + optout) e usa o
    telefone canônico como fallback quando não há pessoa vinculada.
  - **coletivo**: cada público pedido em ``Event.publico_alvo``
    (``toda_igreja``/``pastores``/``g12_pastoral``/``lideres_celula``) já foi
    materializado pelo serviço em candidatos — o *match* é "a query do público
    rodou". Aqui só se aplica opt-out e deduplica contra os individuais.

Regras:
  - **opt-out (LGPD):** candidato com ``optout=true`` nunca entra (conta em
    ``ignored_optout``). Só é verificável quando a pessoa é conhecida; um alvo
    individual só-telefone (sem pessoa vinculada) não tem opt-out para checar.
  - **dedup:** por ``pessoa_id`` quando houver, e também por telefone
    normalizado; o individual tem prioridade (mesma pessoa em individual +
    coletivo entra 1x, mantendo o vínculo/telefone do individual).
  - **sem telefone:** candidato sem número não é entregável — é apenas pulado
    (``skipped_sem_telefone``), não conta como opt-out.

NÃO envia nada e não faz I/O: o disparo real (WhatsApp/Evolution) é EVT-9.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.phone import normalize_phone

# Allowlist coletiva do EVT-8 (D1) — em sincronia com PublicoAlvo do router
# (app/routers/events.py). A seleção individual NÃO faz parte deste conjunto.
PUBLICOS_COLETIVOS: frozenset[str] = frozenset(
    {"toda_igreja", "pastores", "g12_pastoral", "lideres_celula"}
)


@dataclass(frozen=True)
class Candidate:
    """Projeção mínima de um candidato a destinatário (individual ou coletivo)."""

    pessoa_id: str | None
    telefone: str | None
    optout: bool = False


@dataclass(frozen=True)
class ResolvedRecipient:
    """Destinatário resolvido, pronto para um envio futuro (EVT-9)."""

    pessoa_id: str | None
    telefone: str


@dataclass(frozen=True)
class ResolvedAudience:
    """Resultado da resolução: entregáveis + telemetria de exclusões."""

    recipients: list[ResolvedRecipient]
    ignored_optout: int
    skipped_sem_telefone: int

    @property
    def total(self) -> int:
        return len(self.recipients)


def resolve_recipients(
    individual: list[Candidate], coletivo: list[Candidate]
) -> ResolvedAudience:
    """Combina individuais + coletivos, aplica opt-out e deduplica.

    Ordem: **individuais primeiro** (prioridade na dedup). A dedup usa duas
    chaves — ``pessoa_id`` e telefone normalizado — para que a mesma pessoa não
    entre duas vezes mesmo aparecendo por caminhos diferentes (individual por
    telefone vs. coletivo por pessoa, p.ex.). ``optout=true`` nunca entra e conta
    em ``ignored_optout``; candidato sem telefone é pulado.
    """
    seen_pessoa: set[str] = set()
    seen_phone: set[str] = set()
    recipients: list[ResolvedRecipient] = []
    ignored_optout = 0
    skipped_sem_telefone = 0

    for c in [*individual, *coletivo]:
        pid = str(c.pessoa_id) if c.pessoa_id else None
        canonical = normalize_phone(c.telefone or "")
        # Já visto por pessoa OU por telefone → duplicado, ignora silenciosamente.
        if pid and pid in seen_pessoa:
            continue
        if canonical and canonical in seen_phone:
            continue
        # Marca visto (mesmo se excluído adiante) para não reprocessar por outro
        # caminho — evita recontar opt-out e evita duplicar.
        if pid:
            seen_pessoa.add(pid)
        if canonical:
            seen_phone.add(canonical)

        if c.optout:
            ignored_optout += 1
            continue
        phone = (c.telefone or "").strip()
        if not phone:
            skipped_sem_telefone += 1
            continue
        recipients.append(ResolvedRecipient(pessoa_id=pid, telefone=phone))

    return ResolvedAudience(
        recipients=recipients,
        ignored_optout=ignored_optout,
        skipped_sem_telefone=skipped_sem_telefone,
    )
