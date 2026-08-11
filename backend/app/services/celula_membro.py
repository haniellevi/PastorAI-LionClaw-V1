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
    """A pessoa não pode receber um vínculo/responsabilidade ministerial.

    Regras (fonte: célula = discípulos daquela célula; W3.2A estende ao
    arquivamento de Pessoa):
      * ``pastor`` nunca é membro de célula;
      * o líder indicado em ``celulas.lider_id`` nunca é membro da PRÓPRIA célula;
      * o número conectado ao WhatsApp/Evolution da igreja não participa de célula;
      * uma Pessoa ARQUIVADA (``arquivada_em`` preenchido) não pode receber NENHUM
        vínculo/responsabilidade ministerial novo — invariante de domínio (W3.2A,
        revisão externa da PR#163): o arquivamento não pode ser silenciosamente
        desfeito por um write-path que ignore a coluna.

    Levantada no seam canônico (``ensure_active_membro``), no caller que escreve
    fora dele (``cells.add_cell_member``) e na validação de referências de Pessoa
    em ``celula_solicitacao`` (``assert_pessoas_nao_arquivadas`` — criação e
    reaprovação sob lock). ``code`` é o rótulo estável para o cliente; o handler
    global em ``app.main`` mapeia para HTTP 409.
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
    escrita (seam ``ensure_active_membro``, solicitações, multiplicação e tool do
    agente), sem duplicar a regra.
    Usa ``getattr`` porque os fakes de teste modelam a pessoa/célula como
    ``SimpleNamespace`` parcial; em produção os atributos são colunas reais.
    """
    if getattr(pessoa, "arquivada_em", None) is not None:
        raise MembroInelegivelError(
            "pessoa_arquivada",
            "Pessoa arquivada não pode receber novos vínculos ministeriais.",
        )

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

    leads_active_cell = db.execute(
        select(Celula.id)
        .where(
            Celula.igreja_id == igreja_id,
            Celula.lider_id == pessoa.id,
            Celula.ativo.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()
    if leads_active_cell is not None:
        raise MembroInelegivelError(
            "active_leader_cannot_be_member",
            "Pessoa que lidera uma célula ativa não pode ser adicionada como membro.",
        )

    if phone_matches_active_whatsapp(
        db, igreja_id=igreja_id, telefone=getattr(pessoa, "telefone", None)
    ):
        raise MembroInelegivelError(
            "numero_whatsapp_nao_participa",
            "O número conectado ao WhatsApp da igreja não pode participar de célula.",
        )


def assert_pessoas_nao_arquivadas(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    pessoa_ids: list[uuid.UUID | str | None],
    for_update: bool = False,
) -> None:
    """Recusa (``MembroInelegivelError``) se ALGUMA de `pessoa_ids` estiver arquivada.

    Guarda canônica usada por TODOS os pontos de escrita que atribuem uma
    Pessoa a uma responsabilidade/vínculo ministerial: seam ``ensure_active_
    membro``/``add_cell_member`` (via ``assert_membro_elegivel`` acima),
    ``cell_requests.create_cell_request`` + ``cell_requests_service.approve``
    (revalida DENTRO da transação travada da solicitação — TOCTOU
    create->approve), e ``cells.upsert_cell`` (líder/anfitrião/auxiliar).

    IDs vazios/None são ignorados; duplicatas são deduplicadas. A ORDEM é
    SEMPRE determinística (ordenada por UUID) — necessário quando
    ``for_update=True`` trava múltiplas Pessoas na mesma chamada (ex.:
    upsert_cell com líder+anfitrião+auxiliar distintos): duas chamadas
    concorrentes que referenciam o MESMO conjunto de pessoas em ordens
    diferentes travam na MESMA ordem e nunca deadlockam entre si.

    ``for_update=True`` serializa contra ``archive_pessoa`` (que trava a
    própria Pessoa com o mesmo padrão SEC-4B, ``db.refresh(...,
    with_for_update=True)``): quem trava primeiro decide o estado; o outro
    relê sob lock e vê o resultado já commitado — nunca os dois vencem
    (responsabilidade criada + archive bloqueado pelo bloqueador
    `celula_lider`/`celula_anfitriao`/`celula_auxiliar`/`celula_membro_ativo`
    já existente, OU pessoa arquivada + este assert recusando).

    ``populate_existing=True`` (BLOCKER real, confirmado na 4ª revisão externa
    PR#163): se a MESMA Pessoa já estiver no identity map da Session — carregada
    antes por ESTE ou por OUTRO call site que segure uma referência Python viva
    ao objeto (ex.: `cell_requests_service._apply_payload`, que guarda `pessoa`
    numa variável local usada em várias linhas após a 1ª leitura) — um `SELECT
    ... FOR UPDATE` subsequente, SEM `populate_existing`, devolve o MESMO objeto
    Python já presente, com `arquivada_em` desatualizado, mesmo com o lock tendo
    esperado e lido a linha certa no Postgres (o SELECT roda, o lock é real, mas
    o RESULTADO não é aplicado ao objeto já mapeado). A 3ª rodada desta revisão
    chegou a marcar isso como "não reproduz" — o teste daquela rodada estava
    ERRADO: sem uma referência Python forte mantida viva propositalmente, o
    identity map (que guarda referência FRACA por padrão) deixava o GC coletar o
    objeto entre as duas leituras, e a "prova" de que não precisava de
    `populate_existing` era só o efeito colateral de reconstruir um objeto novo,
    não de o SQLAlchemy atualizar o antigo.
    `test_assert_pessoas_nao_arquivadas_for_update_refreshes_strongly_referenced_object`
    mantém uma referência forte deliberada (`pessoa_ref`) viva durante todo o
    cenário e prova: sem esta opção, o assert NÃO detecta o arquivamento
    concorrente (`DID NOT RAISE`); com ela, detecta e atualiza `arquivada_em`
    IN PLACE no mesmo objeto.

    Uma lookup por id (só igualdade — ``id ==`` / ``igreja_id ==``) em vez de
    `IN`: a lista de referências por payload é pequena (poucas unidades) e a
    checagem em Python de `arquivada_em` evita depender de operadores
    compostos (`IN`/`IS NOT NULL`) que o harness de teste offline
    (`cell_backend_fakes.py`) não interpreta — mesmo padrão de
    `_assert_pessoa_in_tenant`.
    """
    uuids = sorted({uuid.UUID(str(raw_id)) for raw_id in pessoa_ids if raw_id}, key=str)
    for pid in uuids:
        query = select(Pessoa).where(Pessoa.id == pid, Pessoa.igreja_id == igreja_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        pessoa = db.execute(query).scalar_one_or_none()
        if pessoa is not None and getattr(pessoa, "arquivada_em", None) is not None:
            raise MembroInelegivelError(
                "pessoa_arquivada",
                "Pessoa arquivada não pode receber novos vínculos ministeriais.",
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
    reject_existing_active: bool = False,
) -> CelulaMembro:
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
        select(Celula)
        .where(Celula.id == celula_id, Celula.igreja_id == igreja_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if celula is None:
        raise ValueError("Célula fora do escopo da igreja — vínculo recusado")
    if not bool(celula.ativo):
        raise MembroInelegivelError(
            "celula_inativa",
            "Célula inativa não pode receber membros.",
        )
    if celula.lider_id is None:
        raise MembroInelegivelError(
            "celula_sem_lider",
            "Célula sem líder não pode receber membros.",
        )

    # Missão M7B-W1.2: guarda de elegibilidade no seam canônico. Carrega a pessoa
    # UMA vez (reusada na promoção adiante) e recusa pastor / líder ativo /
    # número do WhatsApp ANTES de qualquer escrita. Pessoa fora do
    # escopo do tenant (None) não é avaliável aqui — a FK barra o vínculo órfão.
    pessoa = db.execute(
        select(Pessoa)
        .where(Pessoa.id == pessoa_id, Pessoa.igreja_id == igreja_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if pessoa is None:
        raise ValueError("Pessoa fora do escopo da igreja — vínculo recusado")
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
    ativos = list(
        db.execute(
            select(CelulaMembro)
            .where(
                CelulaMembro.pessoa_id == pessoa_id,
                CelulaMembro.igreja_id == igreja_id,
                CelulaMembro.ativo.is_(True),
            )
            .order_by(CelulaMembro.id.asc())
            .with_for_update()
        ).scalars().all()
    )
    outro_ativos = [
        membro for membro in ativos if str(membro.celula_id) != str(celula_id)
    ]
    espelho = pessoa.celula_id
    espelho_em_outra = espelho is not None and str(espelho) != str(celula_id)
    if reject_existing_active and ativos:
        raise MembroInelegivelError(
            "member_already_active",
            "Pessoa já está em uma célula ativa",
        )
    if reject_existing_active and espelho_em_outra:
        raise MembroInelegivelError(
            "member_already_active",
            "Pessoa já está em uma célula ativa",
        )
    if outro_ativos or espelho_em_outra:
        if not pode_transferir:
            raise TransferenciaNaoAutorizadaError(
                "Apenas um administrador pode transferir alguém de célula"
            )
        for outro_ativo in outro_ativos:
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
        .with_for_update()
    ).scalars().all()
    existing = historico[0] if historico else None
    if existing is not None:
        existing.ativo = True
        existing.papel = papel
        membro = existing
    else:
        membro = CelulaMembro(
            igreja_id=igreja_id,
            celula_id=celula_id,
            pessoa_id=pessoa_id,
            papel=papel,
            ativo=True,
        )
        db.add(membro)

    # Vínculo ativo ⇒ a pessoa é, no mínimo, membro. Reusa a `pessoa` já carregada
    # acima (era uma 2ª query separada antes). Fora do tenant → no-op.
    pessoa.celula_id = celula.id
    promote_tipo_para_membro(pessoa)
    return membro


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
