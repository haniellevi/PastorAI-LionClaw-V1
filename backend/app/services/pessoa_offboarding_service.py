"""Preflight + arquivamento seguro de Pessoa (M7B-W3.2A).

Contrato aprovado (não hard delete de Pessoa):
  - "Arquivar pessoa" é a única ação de desligamento; nunca desfaz vínculos
    ministeriais em silêncio — enquanto houver conexão operacional relevante,
    o arquivamento é BLOQUEADO (409) apontando exatamente o que precisa ser
    resolvido primeiro.
  - Única exceção automática: uma consolidação individual ABERTA da própria
    Pessoa é encerrada como "abandonada" NA MESMA transação do archive
    (nunca no GET de preflight, que é somente leitura).
  - Histórico, conversas, mensagens, consentimentos, decisões e presenças NÃO
    são tocados — preservados por completo.

``preflight_archive`` é reutilizado tanto pelo GET (só leitura) quanto pelo
POST /archive (revalidado dentro da MESMA transação travada — TOCTOU fechado
no padrão SEC-4B, ver ``archive_pessoa``).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from dataclasses import dataclass, field

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AppUser,
    Celula,
    CelulaMembro,
    CelulaSolicitacao,
    CellAlert,
    Consolidacao,
    Event,
    EventNotifyTarget,
    Igreja,
    Multiplicacao,
    Pessoa,
    PessoaArquivamentoEvento,
    UserRole,
    WhatsappConnection,
    WorkQueueItem,
)
from app.deps import ADMIN_ROLE, REVOKED_USER_STATUS
from app.domain.cell_requests import OPEN_STATUSES
from app.services.celula_membro import phone_matches_active_whatsapp

ACAO_ARQUIVADA = "arquivada"

# multiplicacoes.status: só 'concluida' é terminal (0001_extensions_and_enums).
_OPEN_MULTIPLICACAO_STATUSES = ("agendada", "sem_agendamento", "aprovada")
# work_queue_items.status: só 'resolvido' é terminal.
_OPEN_WORK_QUEUE_STATUSES = ("aberto", "assumido")


@dataclass
class PreflightItem:
    """Um bloqueador, efeito automático ou item preservado (mesmo formato)."""

    tipo: str
    rotulo: str
    recurso_id: str | None = None
    recurso_nome: str | None = None
    acao_recomendada: str | None = None


@dataclass
class PreflightResult:
    pessoa_id: str
    pode_arquivar: bool
    bloqueadores: list[PreflightItem] = field(default_factory=list)
    automaticos: list[PreflightItem] = field(default_factory=list)
    preservados: list[PreflightItem] = field(default_factory=list)


# Categorias SEMPRE preservadas pelo arquivamento (política, não consulta por
# linha — o contrato garante que estas tabelas nunca são tocadas pelo archive).
#
# `celula_expectativa_visitante.pessoa_id` (revisão externa PR#163) foi
# avaliada e NÃO é bloqueador: (1) criar uma linha NOVA já exige vínculo ATIVO
# em celula_membro na própria célula (cell_discipulo.py: 403 "Você não tem
# vínculo ativo na célula desta reunião") — esse pré-requisito já é o
# bloqueador `celula_membro_ativo` existente; (2) nenhum cron/notificação/ação
# automatizada lê `pessoa_id` desta tabela para agir no futuro — os únicos 2
# leitores (`cell_health_service.py` para o sinal de saúde da reunião,
# `cell_discipulo.py` para o discípulo listar as PRÓPRIAS expectativas) são
# ambos read-only de histórico/relatório, mesma categoria de `celula_presenca`
# (já preservada abaixo). Entra aqui como preservado, não como bloqueador.
_PRESERVADOS_FIXOS: tuple[PreflightItem, ...] = (
    PreflightItem(
        tipo="conversas_mensagens", rotulo="Conversas e mensagens do WhatsApp"
    ),
    PreflightItem(
        tipo="consentimentos", rotulo="Registros de consentimento (LGPD)"
    ),
    PreflightItem(tipo="decisoes", rotulo="Decisões por Jesus"),
    PreflightItem(
        tipo="presencas_reuniao", rotulo="Presenças em reuniões de célula"
    ),
    PreflightItem(
        tipo="expectativas_visitante",
        rotulo="Expectativas de visitante registradas em reuniões de célula",
    ),
    # 2ª revisão externa PR#163 — completando a lista com as demais relações
    # históricas/de autoria (não bloqueadoras — nenhuma é uma responsabilidade
    # ATIVA que o archive precise desfazer) relevantes ao relatório do admin:
    PreflightItem(
        tipo="relatorios_reuniao",
        rotulo="Relatórios de reunião de célula enviados",
    ),
    PreflightItem(
        tipo="registros_pastorais",
        rotulo="Registros pastorais de reunião (decisão/oração/observação)",
    ),
    PreflightItem(
        tipo="trilha_decisoes_celula",
        rotulo="Decisões e trilha de auditoria de solicitações de célula",
    ),
    PreflightItem(
        tipo="avisos_materiais_publicados",
        rotulo="Avisos e materiais de célula publicados",
    ),
    PreflightItem(
        tipo="logs_ia", rotulo="Logs de uso e conversas do agente de IA"
    ),
)


def preflight_archive(
    db: Session,
    *,
    pessoa: Pessoa,
    actor_app_user_id: uuid.UUID | None,
) -> PreflightResult:
    """Calcula bloqueadores/automáticos/preservados para arquivar `pessoa`.

    Somente leitura — nenhuma escrita acontece aqui (a mission proíbe qualquer
    mutação no preflight). Reusado dentro de ``archive_pessoa`` na MESMA
    transação travada, para a decisão de bloquear ser sobre o estado
    corrente sob lock (não uma leitura anterior desatualizada).
    """
    igreja_id = pessoa.igreja_id
    pessoa_id = pessoa.id
    pid_str = str(pessoa_id)
    bloqueadores: list[PreflightItem] = []

    # 1) vínculo ativo em celula_membro (fonte de verdade — Q1).
    membros_ativos = db.execute(
        select(CelulaMembro, Celula)
        .join(Celula, Celula.id == CelulaMembro.celula_id)
        .where(
            CelulaMembro.igreja_id == igreja_id,
            CelulaMembro.pessoa_id == pessoa_id,
            CelulaMembro.ativo.is_(True),
        )
    ).all()
    celulas_com_vinculo: set[uuid.UUID] = set()
    for _membro, celula in membros_ativos:
        celulas_com_vinculo.add(celula.id)
        bloqueadores.append(
            PreflightItem(
                tipo="celula_membro_ativo",
                rotulo="Vínculo ativo em célula",
                recurso_id=str(celula.id),
                recurso_nome=celula.nome,
                acao_recomendada=(
                    "Remova o vínculo da pessoa nesta célula "
                    "(transferir/remover) antes de arquivar."
                ),
            )
        )

    # 2) espelho legado pessoas.celula_id SEM vínculo canônico correspondente
    # (achado C-02: um vínculo desalinhado não pode ficar invisível ao archive).
    if pessoa.celula_id is not None and pessoa.celula_id not in celulas_com_vinculo:
        celula_legado = db.execute(
            select(Celula).where(
                Celula.id == pessoa.celula_id, Celula.igreja_id == igreja_id
            )
        ).scalar_one_or_none()
        bloqueadores.append(
            PreflightItem(
                tipo="celula_id_espelho",
                rotulo="Vínculo de célula (registro legado, sem linha canônica ativa)",
                recurso_id=str(pessoa.celula_id),
                recurso_nome=celula_legado.nome if celula_legado else None,
                acao_recomendada="Limpe o vínculo legado (pessoas.celula_id) antes de arquivar.",
            )
        )

    # 3) líder / anfitrião / auxiliar de célula ATIVA.
    papeis_celula = db.execute(
        select(Celula).where(
            Celula.igreja_id == igreja_id,
            Celula.ativo.is_(True),
            or_(
                Celula.lider_id == pessoa_id,
                Celula.anfitriao_id == pessoa_id,
                Celula.auxiliar_id == pessoa_id,
            ),
        )
    ).scalars().all()
    for celula in papeis_celula:
        if celula.lider_id == pessoa_id:
            bloqueadores.append(
                PreflightItem(
                    tipo="celula_lider",
                    rotulo="Líder de célula ativa",
                    recurso_id=str(celula.id),
                    recurso_nome=celula.nome,
                    acao_recomendada="Troque o líder da célula antes de arquivar.",
                )
            )
        if celula.anfitriao_id == pessoa_id:
            bloqueadores.append(
                PreflightItem(
                    tipo="celula_anfitriao",
                    rotulo="Anfitrião de célula ativa",
                    recurso_id=str(celula.id),
                    recurso_nome=celula.nome,
                    acao_recomendada="Troque o anfitrião da célula antes de arquivar.",
                )
            )
        if celula.auxiliar_id == pessoa_id:
            bloqueadores.append(
                PreflightItem(
                    tipo="celula_auxiliar",
                    rotulo="Auxiliar de célula ativa",
                    recurso_id=str(celula.id),
                    recurso_nome=celula.nome,
                    acao_recomendada="Troque o auxiliar da célula antes de arquivar.",
                )
            )

    # 4) discípulos vinculados (pessoas.lider_id == pessoa.id) — só os NÃO
    # arquivados contam: um discípulo já arquivado não é mais uma dependência
    # ativa e não pode travar o arquivamento do líder indefinidamente (revisão
    # externa da PR#163). `lider_id` não tem writer em produção hoje (só
    # seed/dev), mas o cálculo do bloqueador precisa estar correto de qualquer
    # forma — não há remediação (endpoint de escrita) para desvincular.
    discipulos_count = db.execute(
        select(func.count())
        .select_from(Pessoa)
        .where(
            Pessoa.igreja_id == igreja_id,
            Pessoa.lider_id == pessoa_id,
            Pessoa.arquivada_em.is_(None),
        )
    ).scalar_one()
    if discipulos_count:
        bloqueadores.append(
            PreflightItem(
                tipo="discipulos_vinculados",
                rotulo="Possui discípulos vinculados",
                recurso_nome=f"{discipulos_count} discípulo(s)",
                acao_recomendada="Reatribua os discípulos a outro líder antes de arquivar.",
            )
        )

    # 5/6/7/8) AppUser(s) vinculado(s) — acesso ativo / dono da igreja / último
    # admin / auto-arquivamento. Uma Pessoa pode ter MAIS DE UM app_user na
    # mesma igreja (ex.: um convite reemitido criou um segundo registro); por
    # isso NUNCA usar scalar_one_or_none() aqui — estoura MultipleResultsFound
    # (500) com dois. Avalia-se o CONJUNTO completo: qualquer app_user ativo
    # inclui acesso_painel_ativo; se algum for o dono, inclui dono_igreja.
    app_users = db.execute(
        select(AppUser).where(
            AppUser.pessoa_id == pessoa_id, AppUser.igreja_id == igreja_id
        )
    ).scalars().all()
    igreja = (
        db.execute(select(Igreja).where(Igreja.id == igreja_id)).scalar_one_or_none()
        if app_users
        else None
    )
    for app_user in app_users:
        acesso_ativo = app_user.status != REVOKED_USER_STATUS
        if acesso_ativo:
            bloqueadores.append(
                PreflightItem(
                    tipo="acesso_painel_ativo",
                    rotulo="Possui acesso ativo ao painel",
                    recurso_id=str(app_user.id),
                    recurso_nome=app_user.email,
                    acao_recomendada="Revogue o acesso ao painel (Equipe) antes de arquivar.",
                )
            )

        if igreja is not None and igreja.dono_id == app_user.id:
            bloqueadores.append(
                PreflightItem(
                    tipo="dono_igreja",
                    rotulo="É o dono (admin principal) da igreja",
                    recurso_id=str(igreja.id),
                    recurso_nome=igreja.nome,
                    acao_recomendada=(
                        "Transfira a titularidade da igreja para outro "
                        "administrador antes de arquivar."
                    ),
                )
            )

        is_admin = acesso_ativo and db.execute(
            select(UserRole.id).where(
                UserRole.igreja_id == igreja_id,
                UserRole.user_id == app_user.id,
                UserRole.papel == ADMIN_ROLE,
            )
        ).scalar_one_or_none() is not None
        if is_admin:
            active_admin_count = db.execute(
                select(func.count(func.distinct(UserRole.user_id)))
                .select_from(UserRole)
                .join(AppUser, AppUser.id == UserRole.user_id)
                .where(
                    UserRole.igreja_id == igreja_id,
                    UserRole.papel == ADMIN_ROLE,
                    AppUser.status.is_distinct_from(REVOKED_USER_STATUS),
                )
            ).scalar_one()
            if active_admin_count <= 1:
                bloqueadores.append(
                    PreflightItem(
                        tipo="ultimo_administrador",
                        rotulo="É o último administrador ativo da igreja",
                        recurso_id=str(app_user.id),
                        acao_recomendada="Promova outro administrador antes de arquivar.",
                    )
                )

        # 8) tentativa de arquivar a própria Pessoa do administrador logado.
        if actor_app_user_id is not None and app_user.id == actor_app_user_id:
            bloqueadores.append(
                PreflightItem(
                    tipo="auto_arquivamento",
                    rotulo="Tentativa de arquivar a própria Pessoa do administrador logado",
                    acao_recomendada="Peça a outro administrador para executar este arquivamento.",
                )
            )

    # 9) número oficial conectado ao WhatsApp da igreja.
    if phone_matches_active_whatsapp(db, igreja_id=igreja_id, telefone=pessoa.telefone):
        conn = db.execute(
            select(WhatsappConnection).where(WhatsappConnection.igreja_id == igreja_id)
        ).scalar_one_or_none()
        bloqueadores.append(
            PreflightItem(
                tipo="whatsapp_oficial",
                rotulo="Número conectado ao WhatsApp oficial da igreja",
                recurso_id=str(conn.id) if conn else None,
                recurso_nome=conn.numero if conn else None,
                acao_recomendada=(
                    "Desconecte ou substitua o número oficial do WhatsApp antes de arquivar."
                ),
            )
        )

    # 10) solicitação de célula ABERTA que dependa da pessoa — inclusive IDs
    # dentro do payload JSONB (alterar_anfitriao/auxiliar, transferir/remover
    # membro, novo_lider_id e membros_transferidos_ids da multiplicação).
    solicitacoes = db.execute(
        select(CelulaSolicitacao)
        .where(
            CelulaSolicitacao.igreja_id == igreja_id,
            CelulaSolicitacao.status.in_(OPEN_STATUSES),
            or_(
                CelulaSolicitacao.pessoa_id == pessoa_id,
                CelulaSolicitacao.solicitante_id == pessoa_id,
                CelulaSolicitacao.payload_proposto["anfitriao_id"].astext == pid_str,
                CelulaSolicitacao.payload_proposto["auxiliar_id"].astext == pid_str,
                CelulaSolicitacao.payload_proposto["pessoa_id"].astext == pid_str,
                CelulaSolicitacao.payload_proposto["novo_lider_id"].astext == pid_str,
                CelulaSolicitacao.payload_proposto["membros_transferidos_ids"].contains(
                    [pid_str]
                ),
            ),
        )
        .order_by(CelulaSolicitacao.created_at.asc())
    ).scalars().all()
    for sol in solicitacoes:
        bloqueadores.append(
            PreflightItem(
                tipo="celula_solicitacao_aberta",
                rotulo=f"Solicitação de célula aberta ({sol.tipo})",
                recurso_id=str(sol.id),
                recurso_nome=sol.tipo,
                acao_recomendada="Decida (aprove/rejeite/cancele) a solicitação antes de arquivar.",
            )
        )

    # 11) fila de trabalho aberta.
    fila_aberta = db.execute(
        select(WorkQueueItem)
        .where(
            WorkQueueItem.igreja_id == igreja_id,
            WorkQueueItem.pessoa_id == pessoa_id,
            WorkQueueItem.status.in_(_OPEN_WORK_QUEUE_STATUSES),
        )
        .order_by(WorkQueueItem.created_at.asc())
    ).scalars().all()
    for item in fila_aberta:
        bloqueadores.append(
            PreflightItem(
                tipo="fila_trabalho_aberta",
                rotulo="Item aberto na fila de trabalho",
                recurso_id=str(item.id),
                recurso_nome=item.titulo,
                acao_recomendada="Resolva ou reatribua o item da fila antes de arquivar.",
            )
        )

    # 12) alerta de célula não tratado.
    alertas = db.execute(
        select(CellAlert)
        .where(
            CellAlert.igreja_id == igreja_id,
            CellAlert.pessoa_id == pessoa_id,
            CellAlert.tratado.is_(False),
        )
        .order_by(CellAlert.created_at.asc())
    ).scalars().all()
    for alerta in alertas:
        bloqueadores.append(
            PreflightItem(
                tipo="alerta_celula_pendente",
                rotulo="Alerta de célula não tratado",
                recurso_id=str(alerta.id),
                recurso_nome=alerta.gatilho,
                acao_recomendada="Trate o alerta antes de arquivar.",
            )
        )

    # 13) alvo futuro de evento/notificação (recorrente sem data ou data >= hoje).
    hoje = dt.date.today()
    alvos_evento = db.execute(
        select(Event)
        .join(EventNotifyTarget, EventNotifyTarget.event_id == Event.id)
        .where(
            EventNotifyTarget.igreja_id == igreja_id,
            EventNotifyTarget.pessoa_id == pessoa_id,
            or_(Event.data.is_(None), Event.data >= hoje),
        )
        .order_by(Event.created_at.asc())
    ).scalars().all()
    for evento in alvos_evento:
        bloqueadores.append(
            PreflightItem(
                tipo="evento_notificacao_futura",
                rotulo="Alvo de notificação de evento futuro/recorrente",
                recurso_id=str(evento.id),
                recurso_nome=evento.titulo,
                acao_recomendada="Remova a pessoa da lista de notificação do evento antes de arquivar.",
            )
        )

    # 14) achado adicional da auditoria de código: multiplicação de célula
    # pendente que indica a pessoa como NOVO líder (o payload da solicitação já
    # é coberto acima, mas a linha em `multiplicacoes` sobrevive à aprovação
    # da solicitação e carrega o mesmo novo_lider_id de forma independente).
    multiplicacoes = db.execute(
        select(Multiplicacao)
        .where(
            Multiplicacao.igreja_id == igreja_id,
            Multiplicacao.novo_lider_id == pessoa_id,
            Multiplicacao.status.in_(_OPEN_MULTIPLICACAO_STATUSES),
        )
        .order_by(Multiplicacao.created_at.asc())
    ).scalars().all()
    for mult in multiplicacoes:
        bloqueadores.append(
            PreflightItem(
                tipo="multiplicacao_pendente",
                rotulo="Indicada como nova líder em multiplicação de célula pendente",
                recurso_id=str(mult.id),
                acao_recomendada="Resolva ou reatribua a multiplicação antes de arquivar.",
            )
        )

    # automáticos: consolidação individual ABERTA -> vira "abandonada" SOMENTE
    # dentro da transação real de archive (archive_pessoa). Aqui é só o aviso.
    automaticos: list[PreflightItem] = []
    consolidacoes_abertas = db.execute(
        select(Consolidacao).where(
            Consolidacao.igreja_id == igreja_id,
            Consolidacao.pessoa_id == pessoa_id,
            Consolidacao.concluida.is_(False),
            Consolidacao.abandonada_em.is_(None),
        )
    ).scalars().all()
    for cons in consolidacoes_abertas:
        automaticos.append(
            PreflightItem(
                tipo="consolidacao_abandonada",
                rotulo="Consolidação individual aberta será encerrada como 'abandonada'",
                recurso_id=str(cons.id),
            )
        )

    return PreflightResult(
        pessoa_id=pid_str,
        pode_arquivar=not bloqueadores,
        bloqueadores=bloqueadores,
        automaticos=automaticos,
        preservados=list(_PRESERVADOS_FIXOS),
    )


def archive_pessoa(
    db: Session,
    *,
    pessoa: Pessoa,
    actor_app_user_id: uuid.UUID,
    motivo: str,
) -> tuple[Pessoa, bool]:
    """Arquiva `pessoa` transacionalmente. Retorna ``(pessoa, ja_estava_arquivada)``.

    SEC-4B (mesmo padrão de ``cell_requests_service.approve``): a linha é
    travada com ``SELECT ... FOR UPDATE`` (``db.refresh(..., with_for_update=
    True)``) e o preflight é REVALIDADO dentro da MESMA transação que aplica o
    abandono de consolidação, grava ``arquivada_em/por/motivo`` e a auditoria,
    e faz commit. Duas chamadas concorrentes serializam nesse lock: a primeira
    a obtê-lo arquiva; a segunda espera, relê ``arquivada_em`` já preenchido e
    retorna idempotente (``ja_estava_arquivada=True``) sem duplicar efeito nem
    linha de auditoria.
    """
    db.refresh(pessoa, with_for_update=True)

    if pessoa.arquivada_em is not None:
        # Idempotente: nenhuma escrita nova, nenhum evento duplicado.
        db.rollback()
        return pessoa, True

    preflight = preflight_archive(
        db, pessoa=pessoa, actor_app_user_id=actor_app_user_id
    )
    if not preflight.pode_arquivar:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=dataclasses.asdict(preflight),
        )

    try:
        agora = dt.datetime.now(dt.timezone.utc)

        # FOR UPDATE: estas linhas estão prestes a ser escritas (abandonada_em).
        # Serializa contra pipeline.advance_stage, que trava a MESMA linha com
        # o mesmo with_for_update() — sem isso, um advance_stage concorrente
        # poderia concluir a consolidação entre esta leitura e a escrita abaixo,
        # produzindo concluida=true E abandonada_em preenchido (revisão externa
        # PR#163; a exclusividade mútua é também garantida pelo CHECK do banco,
        # este lock evita a corrida ANTES do CHECK precisar intervir).
        consolidacoes_abertas = db.execute(
            select(Consolidacao)
            .where(
                Consolidacao.igreja_id == pessoa.igreja_id,
                Consolidacao.pessoa_id == pessoa.id,
                Consolidacao.concluida.is_(False),
                Consolidacao.abandonada_em.is_(None),
            )
            .with_for_update()
        ).scalars().all()
        for cons in consolidacoes_abertas:
            cons.abandonada_em = agora
            cons.abandonada_motivo = f"Pessoa arquivada: {motivo}"

        pessoa.arquivada_em = agora
        pessoa.arquivada_por = actor_app_user_id
        pessoa.arquivada_motivo = motivo

        db.add(
            PessoaArquivamentoEvento(
                igreja_id=pessoa.igreja_id,
                pessoa_id=pessoa.id,
                ator_id=actor_app_user_id,
                acao=ACAO_ARQUIVADA,
                motivo=motivo,
            )
        )

        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    return pessoa, False
