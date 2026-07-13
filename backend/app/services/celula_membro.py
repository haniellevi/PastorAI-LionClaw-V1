"""Vínculo canônico ``celula_membro`` — mantém consistência com o espelho
legado ``pessoas.celula_id`` (achado C-02).

Três pontos de escrita atualizavam só o espelho (convite Parte A em team.py,
ativação Parte B em auth.py, ``link_cell`` em contacts.py), deixando a pessoa
invisível na visão do líder/discípulo (que lê ``celula_membro``, a fonte de
verdade — Q1). Este módulo centraliza a escrita canônica pra não duplicar a
lógica 3x e arriscar divergência entre as cópias.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Celula, CelulaMembro, Pessoa, WhatsappConnection
from app.domain.phone import normalize_phone

# Missão M7B-W1: tipos de ENTRADA (ou tipo ausente) que um vínculo ativo de
# célula promove a "membro". Um vínculo canônico ativo implica que a pessoa é,
# no mínimo, membro — nunca pode continuar "contato"/"visitante". membro/
# discipulo/lider/pastor são PRESERVADOS (nunca rebaixados).
_TIPOS_PROMOVIVEIS_A_MEMBRO: frozenset[str | None] = frozenset(
    {None, "contato", "visitante"}
)


class MembroInelegivelError(ValueError):
    """Missão M7B-W1.2: a pessoa não pode ter vínculo ATIVO de célula.

    Regras ministeriais (fonte: célula = discípulos daquela célula):
      * ``pastor`` nunca é membro de célula;
      * o líder indicado em ``celulas.lider_id`` nunca é membro da PRÓPRIA célula;
      * o número conectado ao WhatsApp/Evolution da igreja não participa de célula.

    Levantada no seam canônico (``ensure_active_membro``) e no único caller que
    escreve fora dele (``cells.add_cell_member``). ``code`` é o rótulo estável
    para o cliente; o handler global em ``app.main`` mapeia para HTTP 409.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class TransferenciaNaoAutorizadaError(ValueError):
    """D2: reatribuir pessoa que JÁ pertence a outra célula exige capacidade.

    O domínio não conhece papéis — recebe apenas ``pode_transferir: bool``
    (nunca ``actor_role``/``CurrentUser``). Cada adapter deriva a capacidade:
    o HTTP administrativo de ``current_user.has_role("admin")``; a tool do
    agente passa sempre ``False``. O primeiro vínculo de uma pessoa sem célula
    não é transferência e segue liberado. O handler global em ``app.main``
    mapeia para HTTP 403.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def assert_membro_elegivel(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    celula: Celula,
    pessoa: Pessoa,
) -> None:
    """Recusa (``MembroInelegivelError``) uma pessoa inelegível a membro de célula.

    Guarda COMPARTILHADA: concentrada aqui para valer em TODOS os pontos de
    escrita (o seam ``ensure_active_membro`` — convite/ativação/link_cell/tool do
    agente — e a entrada direta ``cells.add_cell_member``), sem duplicar a regra.
    Usa ``getattr`` porque os fakes de teste modelam a pessoa/célula como
    ``SimpleNamespace`` parcial; em produção os atributos são colunas reais.
    """
    if (getattr(pessoa, "tipo", None) or "").lower() == "pastor":
        raise MembroInelegivelError(
            "pastor_nao_pode_ser_membro",
            "Pastor não pode ser membro de célula.",
        )

    lider_id = getattr(celula, "lider_id", None)
    if lider_id is not None and str(lider_id) == str(pessoa.id):
        raise MembroInelegivelError(
            "lider_nao_membro_propria_celula",
            "O líder da célula não pode ser membro da própria célula.",
        )

    if phone_matches_active_whatsapp(
        db, igreja_id=igreja_id, telefone=getattr(pessoa, "telefone", None)
    ):
        raise MembroInelegivelError(
            "numero_whatsapp_nao_participa",
            "O número conectado ao WhatsApp da igreja não pode participar de célula.",
        )


def phone_matches_active_whatsapp(
    db: Session, *, igreja_id: uuid.UUID, telefone: str | None
) -> bool:
    """True se ``telefone`` (normalizado) é o número conectado ao WhatsApp do tenant.

    Uma conexão por igreja (UNIQUE igreja_id). Compara pela chave canônica
    ``normalize_phone`` (mesmo normalizador do dedupe de contatos), de modo que
    ``+55`` e o 9º dígito não escondam a correspondência. Público: reusado por
    ``pessoa_offboarding_service`` para o bloqueador "número oficial WhatsApp"
    do preflight de arquivamento (mesma comparação, sem duplicar a lógica).
    """
    normalized = normalize_phone(telefone or "")
    if not normalized:
        return False
    conn = db.execute(
        select(WhatsappConnection).where(
            WhatsappConnection.igreja_id == igreja_id
        )
    ).scalar_one_or_none()
    if conn is None or not conn.numero:
        return False
    return normalize_phone(conn.numero) == normalized


def ensure_active_membro(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    celula_id: uuid.UUID,
    pessoa_id: uuid.UUID,
    papel: str = "membro",
    pode_transferir: bool = False,
) -> None:
    """Garante uma linha ATIVA de celula_membro para (pessoa, célula).

    Idempotente: reativa a linha se já existir (não duplica). Se a pessoa já
    pertence a OUTRA célula (vínculo canônico ativo ou espelho
    ``pessoas.celula_id``), é uma TRANSFERÊNCIA: exige ``pode_transferir=True``
    (D2 — capacidade decidida pelo adapter, nunca papel aqui dentro) e então
    desativa o vínculo antigo antes de ativar o novo (o índice único parcial
    só permite 1 vínculo ativo por pessoa). Sem a capacidade, recusa
    (``TransferenciaNaoAutorizadaError``) ANTES de qualquer escrita — nenhuma
    mutação parcial escapa. O primeiro vínculo (pessoa sem célula) nunca é
    transferência e segue liberado com o default ``False``.

    Recusa (``ValueError``) se ``celula_id`` não pertencer a ``igreja_id`` —
    o service é o ponto canônico de escrita e não deve confiar cegamente nos
    IDs recebidos, mesmo que os 4 callers atuais já validem isso antes de
    chamar (achado de revisão externa do PR #134).
    """
    celula = db.execute(
        select(Celula).where(Celula.id == celula_id, Celula.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if celula is None:
        raise ValueError("Célula fora do escopo da igreja — vínculo recusado")

    # Missão M7B-W1.2: guarda de elegibilidade no seam canônico. Carrega a pessoa
    # UMA vez (reusada na promoção adiante) e recusa pastor / líder da própria
    # célula / número do WhatsApp ANTES de qualquer escrita. Pessoa fora do
    # escopo do tenant (None) não é avaliável aqui — a FK barra o vínculo órfão.
    pessoa = db.execute(
        select(Pessoa).where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
    ).scalar_one_or_none()
    if pessoa is not None:
        assert_membro_elegivel(db, igreja_id=igreja_id, celula=celula, pessoa=pessoa)

    # D2: pessoa que já pertence a OUTRA célula (linha canônica ativa ou espelho
    # legado pessoas.celula_id) só é reatribuída com a capacidade
    # ``pode_transferir``. A recusa acontece AQUI — antes de desativar o vínculo
    # antigo e antes de criar/reativar a linha nova — porque o runtime do agente
    # engole o erro e ainda comita o turno: mutação parcial persistiria.
    # Escopado por igreja_id: vínculo ativo em outro tenant não conta.
    # ``ativo.is_(True)`` é obrigatório aqui: "pertencer a outra célula" =
    # vínculo ATIVO. Sem o filtro, uma linha INATIVA histórica (que o backfill
    # preserva — ver ORDER BY abaixo) recusaria o primeiro vínculo de quem já
    # saiu de célula, e em transferência real (ativa + histórico) a query
    # devolveria 2 linhas → MultipleResultsFound.
    outro_ativo = db.execute(
        select(CelulaMembro).where(
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.ativo.is_(True),
            CelulaMembro.celula_id != celula_id,
        )
    ).scalar_one_or_none()
    espelho = getattr(pessoa, "celula_id", None) if pessoa is not None else None
    espelho_em_outra = espelho is not None and str(espelho) != str(celula_id)
    if outro_ativo is not None or espelho_em_outra:
        if not pode_transferir:
            raise TransferenciaNaoAutorizadaError(
                "Apenas um administrador pode transferir alguém de célula"
            )
        if outro_ativo is not None:
            outro_ativo.ativo = False

    # Histórico anterior a este PR pode ter deixado mais de uma linha inativa
    # pra (pessoa, célula) — a migration de backfill reativa só a mais
    # recente e preserva as demais. scalar_one_or_none() estouraria
    # MultipleResultsFound nesse caso; pega a linha certa deterministicamente.
    #
    # Prioriza `ativo` PRIMEIRO no ORDER BY (não só updated_at): uma linha já
    # ATIVA nunca tem updated_at tocado (fica NULL pra sempre — coluna sem
    # default), enquanto toda linha DESATIVADA sempre ganha `updated_at =
    # now()` no momento da transferência (cell_requests_service.py,
    # cell_multiplication_service.py). Sem isso, uma chamada idempotente
    # pra um par (pessoa, célula) JÁ ativo escolheria por engano uma
    # duplicata histórica inativa (que tem updated_at populado) em vez da
    # linha ativa (updated_at NULL) e tentaria reativá-la também — violando
    # o índice único parcial (achado da 3a revisão externa do PR #134).
    historico = db.execute(
        select(CelulaMembro)
        .where(
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.celula_id == celula_id,
            CelulaMembro.igreja_id == igreja_id,
        )
        .order_by(
            CelulaMembro.ativo.desc(),
            CelulaMembro.updated_at.desc().nullslast(),
            CelulaMembro.created_at.desc(),
        )
    ).scalars().all()
    existing = historico[0] if historico else None
    if existing is not None:
        existing.ativo = True
    else:
        db.add(
            CelulaMembro(
                igreja_id=igreja_id,
                celula_id=celula_id,
                pessoa_id=pessoa_id,
                papel=papel,
                ativo=True,
            )
        )

    # Vínculo ativo ⇒ a pessoa é, no mínimo, membro. Reusa a `pessoa` já carregada
    # acima (era uma 2ª query separada antes). Fora do tenant → no-op.
    if pessoa is not None:
        promote_tipo_para_membro(pessoa)


def promote_tipo_para_membro(pessoa: Pessoa) -> None:
    """Vínculo canônico ATIVO ⇒ a pessoa é, no mínimo, "membro".

    Idempotente: só promove tipo ausente/"contato"/"visitante"; PRESERVA
    membro/discipulo/lider/pastor (sem downgrade). Concentrada aqui para valer em
    TODOS os pontos de escrita de celula_membro — o seam ensure_active_membro E os
    inserts diretos (add_cell_member, aprovação transferir_membro, multiplicação),
    sem duplicar a regra. Mantém o invariante "vínculo ativo ⇒ tipo ≥ membro".
    """
    if getattr(pessoa, "tipo", None) in _TIPOS_PROMOVIVEIS_A_MEMBRO:
        pessoa.tipo = "membro"


# D2: ``deactivate_other_active_membro`` foi absorvida por
# ``ensure_active_membro(pode_transferir=True)`` — manter um helper público que
# desativa o vínculo antigo SEM checar a capacidade seria uma via de bypass da
# guarda de transferência.
