#!/usr/bin/env python3
"""Banco LOCAL de desenvolvimento: migrations e dados de teste (usado pelo dev.sh).

    python scripts/dev_local.py migrate   # cria o ledger e aplica as migrations pendentes
    python scripts/dev_local.py seed      # dados fictícios e vínculo das contas de teste

Recusa qualquer banco que não seja o Supabase local: DEV e PROD ficam de fora.
Tudo é fictício. Os telefones usam o DDD 00, que não existe, e os e-mails o
domínio reservado ``.test``. O seed é idempotente: rodar de novo só religa as
contas de teste (útil depois de preencher os e-mails no ``.env.dev``).
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

LOCAL_DB_HOST = "127.0.0.1"
LOCAL_DB_PORT = 54322
LOCAL_DB_NAME = "postgres"
LOCAL_DB_SCHEMES = frozenset({"postgresql", "postgresql+psycopg2"})
LOCAL_DB_RECEIPT_SCHEMA = "pastorai-local-db-identity-v1"
_CONTAINER_BACKEND_ROOT = Path("/app")
_CONTAINER_RECEIPT_PATH = Path("/run/pastorai/local-db-identity.json")
_LIBPQ_ROUTING_ENV = (
    "PGHOST",
    "PGHOSTADDR",
    "PGPORT",
    "PGDATABASE",
    "PGSERVICE",
    "PGSERVICEFILE",
    "PGOPTIONS",
)

# Criados pela migration 0005_seed (igreja piloto, Pastor Piloto e seu login).
IGREJA_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
PASTOR_PESSOA_ID = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PASTOR_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a1")

_NS = uuid.UUID("0c9f5a52-3d8e-4f1b-9d7a-6f2b1e4c8a10")


def _id(chave: str) -> uuid.UUID:
    """UUID estável por chave: o seed gera sempre os mesmos ids."""
    return uuid.uuid5(_NS, chave)


IGREJA_VIZINHA_ID = _id("igreja:vizinha")

# Papel no seed, variável do .env.dev com o e-mail da conta no Clerk de
# desenvolvimento e o app_user que ela assume.
CONTAS_DE_TESTE = (
    ("pastor", "DEV_SEED_EMAIL_PASTOR", PASTOR_USER_ID),
    ("admin", "DEV_SEED_EMAIL_ADMIN", _id("usuario:admin")),
    ("lider", "DEV_SEED_EMAIL_LIDER", _id("usuario:marcos")),
    ("consolidacao", "DEV_SEED_EMAIL_CONSOLIDACAO", _id("usuario:patricia")),
    ("membro", "DEV_SEED_EMAIL_MEMBRO", _id("usuario:ana")),
    ("plataforma", "DEV_SEED_EMAIL_PLATAFORMA", _id("usuario:plataforma")),
)


def fone(n: int) -> str:
    """Telefone fictício no formato do WhatsApp: 55 + DDD 00 (não existe)."""
    return f"5500900000{n:03d}"


def local_database_url() -> str:
    """DATABASE_URL do Supabase local; qualquer outro alvo é recusado."""
    if any(os.environ.get(name) for name in _LIBPQ_ROUTING_ENV):
        sys.exit("recusado: variáveis libpq de roteamento não são aceitas")
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        sys.exit("defina DATABASE_URL (o dev.sh já faz isso)")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        sys.exit("recusado: dev_local.py só roda no Supabase local")
    if (
        parsed.scheme not in LOCAL_DB_SCHEMES
        or parsed.hostname != LOCAL_DB_HOST
        or port != LOCAL_DB_PORT
        or parsed.path != f"/{LOCAL_DB_NAME}"
        or parsed.query
        or parsed.fragment
    ):
        sys.exit("recusado: dev_local.py só roda no Supabase local")
    if os.environ.get("APP_ENV", "development").strip().lower() == "production":
        sys.exit("recusado: APP_ENV=production")
    return url


def _local_database_receipt_path() -> Path:
    if _BACKEND_ROOT == _CONTAINER_BACKEND_ROOT:
        return _CONTAINER_RECEIPT_PATH
    return _BACKEND_ROOT.parent / ".dev" / "local-db-identity.json"


def _receipt_system_identifier() -> str:
    try:
        receipt = json.loads(_local_database_receipt_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        sys.exit("recusado: recibo da instância local ausente ou inválido")

    expected = {
        "schema": LOCAL_DB_RECEIPT_SCHEMA,
        "host": LOCAL_DB_HOST,
        "port": LOCAL_DB_PORT,
        "database": LOCAL_DB_NAME,
    }
    if not isinstance(receipt, dict) or any(
        receipt.get(key) != value for key, value in expected.items()
    ):
        sys.exit("recusado: recibo da instância local inválido")
    system_identifier = receipt.get("system_identifier")
    if not isinstance(system_identifier, str) or not system_identifier.isdecimal():
        sys.exit("recusado: recibo da instância local inválido")
    return system_identifier


def _confirm_local_database_identity(connection: object) -> None:
    """Confere o recibo emitido pelo dev.sh na própria conexão que vai escrever."""
    expected = _receipt_system_identifier()
    try:
        if hasattr(connection, "cursor"):
            with connection.cursor() as cursor:  # type: ignore[attr-defined]
                cursor.execute("SELECT system_identifier FROM pg_control_system()")
                row = cursor.fetchone()
                actual = row[0] if row else None
        else:
            actual = connection.exec_driver_sql(  # type: ignore[attr-defined]
                "SELECT system_identifier FROM pg_control_system()"
            ).scalar_one()
    except Exception:
        sys.exit("recusado: não foi possível comprovar a instância local")
    if str(actual) != expected:
        sys.exit("recusado: instância local não confere com o recibo")


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------


def cmd_migrate() -> int:
    import psycopg2

    from scripts import migrate

    url = local_database_url().replace("postgresql+psycopg2://", "postgresql://", 1)
    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        _confirm_local_database_identity(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.schema_migrations') IS NULL")
            if cur.fetchone()[0]:
                # Banco novo: o PROD nasceu com os privilégios padrão antigos do
                # Supabase (tudo para anon/authenticated/service_role) e as
                # migrations contam com eles; os REVOKE delas fazem o resto.
                # O Supabase local de hoje não concede, então repomos antes da 1ª.
                for objeto in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                    cur.execute(
                        "ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public"
                        f" GRANT ALL ON {objeto} TO anon, authenticated, service_role"
                    )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS public.schema_migrations ("
                " name text PRIMARY KEY,"
                " applied_at timestamptz NOT NULL DEFAULT now())"
            )
            applied = migrate._applied(cur)
    finally:
        conn.close()

    todo = migrate.pending(migrate.migration_files(), applied)
    for name in todo:
        body = (migrate.MIGRATIONS_DIR / name).read_text(encoding="utf-8")
        concurrently = any(
            "index concurrently" in line.lower()
            for line in body.splitlines()
            if not line.lstrip().startswith("--")
        )
        # Conexão nova por arquivo: cmd_apply liga o autocommit nas sem transação.
        conn = psycopg2.connect(url)
        try:
            _confirm_local_database_identity(conn)
            with contextlib.redirect_stdout(io.StringIO()):
                migrate.cmd_apply(conn, name, transactional=not concurrently)
        finally:
            conn.close()
    print(f"migrations: {len(todo)} aplicadas agora, {len(applied) + len(todo)} no banco")
    return 0


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------


def cmd_seed() -> int:
    url = local_database_url()
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from app.db.models import Igreja

    hoje = dt.date.today()
    agora = dt.datetime.now(dt.timezone.utc)
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            _confirm_local_database_identity(db.connection())
            novo = (
                db.execute(
                    select(Igreja.id).where(Igreja.id == IGREJA_VIZINHA_ID)
                ).scalar_one_or_none()
                is None
            )
            if novo:
                _criar_dados(db, hoje, agora)
            vinculos = _ligar_contas_de_teste(db)
            db.commit()
            resumo = _resumo(db)
    finally:
        engine.dispose()

    print("dados de teste: " + ("criados" if novo else "já existiam (mantidos)"))
    for linha in resumo:
        print(f"  {linha}")
    print("contas de teste (Clerk de desenvolvimento):")
    for papel, estado in vinculos:
        print(f"  {papel:<13} {estado}")
    return 0


def _ins(db, model, **values) -> None:
    from sqlalchemy import insert

    db.execute(insert(model.__table__).values(**values))


def _upd(db, model, row_id: uuid.UUID, **values) -> None:
    from sqlalchemy import update

    table = model.__table__
    db.execute(update(table).where(table.c.id == row_id).values(**values))


def _ultima(hoje: dt.date, weekday: int, semanas_atras: int) -> dt.date:
    """Data da reunião de ``semanas_atras`` semanas atrás (weekday: segunda=0)."""
    delta = (hoje.weekday() - weekday) % 7 or 7
    return hoje - dt.timedelta(days=delta + 7 * (semanas_atras - 1))


def _proxima(hoje: dt.date, weekday: int) -> dt.date:
    return hoje + dt.timedelta(days=(weekday - hoje.weekday()) % 7 or 7)


def _criar_dados(db, hoje: dt.date, agora: dt.datetime) -> None:
    from app.db.models import (
        AppUser,
        Igreja,
        Pessoa,
        PlatformAdmin,
        UserRole,
    )

    dias = lambda n: agora - dt.timedelta(days=n)  # noqa: E731

    # -- Igreja local: a piloto da 0005 ganha nome de teste e dados fictícios --
    _upd(db, Igreja, IGREJA_ID, nome="Igreja Local (teste)")
    _upd(
        db,
        Pessoa,
        PASTOR_PESSOA_ID,
        nome="Pr. André Luiz",
        telefone=fone(1),
        email="pastor@igreja-local.test",
        genero="m",
        aceitou_jesus=True,
        consentimento=True,
    )
    _upd(
        db,
        AppUser,
        PASTOR_USER_ID,
        nome="Pr. André Luiz",
        email="pastor@igreja-local.test",
        clerk_user_id=None,
    )

    def pessoa(chave, nome, n, genero, tipo, etapa, subetapa, acomp, **extra):
        pid = _id(f"pessoa:{chave}")
        _ins(
            db,
            Pessoa,
            id=pid,
            igreja_id=extra.pop("igreja_id", IGREJA_ID),
            nome=nome,
            telefone=fone(n),
            genero=genero,
            tipo=tipo,
            etapa=etapa,
            subetapa=subetapa,
            acompanhamento=acomp,
            **extra,
        )
        return pid

    # Líderes de célula (cobertura do pastor).
    lideres = {
        chave: pessoa(
            chave, nome, n, genero, "lider", "enviar", "consolidado", "consolidado",
            aceitou_jesus=True, apto_lider=True, presencas_celula=40,
            lider_id=PASTOR_PESSOA_ID, origem="celula", endereco=bairro,
            created_at=dias(900),
        )
        for chave, nome, n, genero, bairro in (
            ("marcos", "Marcos Oliveira", 2, "m", "Centro"),
            ("juliana", "Juliana Costa", 3, "f", "Jardim América"),
            ("rafael", "Rafael Souza", 4, "m", "Vila Nova"),
        )
    }

    # Membros e discípulos: (chave, nome, nº, gênero, tipo, papel na célula).
    celulas = (
        ("esperanca", "Célula Esperança", "marcos", "Quarta-feira", 2, "20:00",
         "Rua das Acácias, 45 — Centro", "Centro", (
             ("patricia", "Patrícia Lima", 10, "f", "discipulo", "auxiliar"),
             ("ana", "Ana Beatriz Rocha", 11, "f", "membro", "anfitriao"),
             ("carlos", "Carlos Mendes", 12, "m", "membro", "membro"),
             ("fernanda", "Fernanda Alves", 13, "f", "membro", "membro"),
         )),
        ("vida-nova", "Célula Vida Nova", "juliana", "Quinta-feira", 3, "19:30",
         "Avenida Brasil, 1200, ap. 32 — Jardim América", "Jardim América", (
             ("lucas", "Lucas Ferreira", 20, "m", "discipulo", "auxiliar"),
             ("mariana", "Mariana Santos", 21, "f", "membro", "anfitriao"),
             ("pedro", "Pedro Henrique Dias", 22, "m", "membro", "membro"),
             ("camila", "Camila Ribeiro", 23, "f", "membro", "membro"),
         )),
        ("jovens", "Célula Jovens em Cristo", "rafael", "Sábado", 5, "17:00",
         "Rua São João, 88 — Vila Nova", "Vila Nova", (
             ("gabriel", "Gabriel Martins", 30, "m", "discipulo", "auxiliar"),
             ("larissa", "Larissa Gomes", 31, "f", "membro", "anfitriao"),
             ("thiago", "Thiago Araújo", 32, "m", "membro", "membro"),
             ("beatriz", "Beatriz Carvalho", 33, "f", "membro", "membro"),
         )),
    )
    membros: dict[str, uuid.UUID] = {}
    for _, _, lider, _, _, _, _, bairro, integrantes in celulas:
        for i, (chave, nome, n, genero, tipo, _papel) in enumerate(integrantes):
            membros[chave] = pessoa(
                chave, nome, n, genero, tipo, "discipular", "consolidado",
                "consolidado", aceitou_jesus=True, consentimento=False,
                presencas_celula=8 + 3 * i, lider_id=lideres[lider],
                origem="celula", endereco=bairro, created_at=dias(300 - 40 * i),
            )

    # Em consolidação: aceitaram Jesus há poucos dias.
    consolidandos = {
        chave: pessoa(
            chave, nome, n, genero, "membro", "consolidar", "em_consolidacao",
            "em_andamento", aceitou_jesus=True, presencas_celula=1,
            origem=origem, endereco=bairro, primeiro_contato=dias(dias_atras),
            created_at=dias(dias_atras),
        )
        for chave, nome, n, genero, origem, bairro, dias_atras in (
            ("rodrigo", "Rodrigo Pereira", 40, "m", "culto", "Centro", 10),
            ("sofia", "Sofia Barbosa", 41, "f", "celula", "Jardim América", 4),
            ("eduardo", "Eduardo Nunes", 42, "m", "culto", "Vila Nova", 20),
        )
    }

    # Visitantes (foram a um culto ou célula) e contatos novos do WhatsApp.
    visitantes = {
        chave: pessoa(
            chave, nome, n, genero, "visitante", "ganhar", "visitante", "sem",
            origem=origem, primeiro_contato=dias(dias_atras),
            created_at=dias(dias_atras),
        )
        for chave, nome, n, genero, origem, dias_atras in (
            ("vanessa", "Vanessa Moreira", 50, "f", "culto", 6),
            ("diego", "Diego Cardoso", 51, "m", "celula", 8),
            ("aline", "Aline Teixeira", 52, "f", "indicacao", 13),
        )
    }
    contatos = {
        chave: pessoa(
            chave, nome, n, genero, "contato", "ganhar", "novo_contato", "sem",
            origem="whatsapp", primeiro_contato=dias(dias_atras),
            created_at=dias(dias_atras),
        )
        for chave, nome, n, genero, dias_atras in (
            ("carla", "Carla Monteiro", 60, "f", 2),
            ("bruno", "Bruno Almeida", 61, "m", 0),
            ("renata", "Renata Freitas", 62, "f", 1),
            ("paulo", "Paulo Vieira", 63, "m", 3),
        )
    }

    # -- Logins do painel (ligados ao Clerk dev por e-mail, depois) ----------
    def usuario(chave, nome, pessoa_id, papeis, igreja_id=IGREJA_ID):
        uid = _id(f"usuario:{chave}")
        _ins(
            db,
            AppUser,
            id=uid,
            igreja_id=igreja_id,
            pessoa_id=pessoa_id,
            nome=nome,
            email=f"{chave}@igreja-local.test",
            status="ativo",
        )
        for papel in papeis:
            _ins(db, UserRole, igreja_id=igreja_id, user_id=uid, papel=papel)
        return uid

    usuarios = {
        "admin": usuario("admin", "Secretaria da Igreja", None, ["admin"]),
        "marcos": usuario("marcos", "Marcos Oliveira", lideres["marcos"],
                          ["lider_celula", "lider_g12"]),
        "juliana": usuario("juliana", "Juliana Costa", lideres["juliana"],
                           ["lider_celula"]),
        "rafael": usuario("rafael", "Rafael Souza", lideres["rafael"],
                          ["lider_celula"]),
        "patricia": usuario("patricia", "Patrícia Lima", membros["patricia"],
                            ["lider_consol"]),
        "ana": usuario("ana", "Ana Beatriz Rocha", membros["ana"], ["membro"]),
        "plataforma": usuario("plataforma", "Equipe PastorAI", None, []),
    }
    _ins(
        db,
        PlatformAdmin,
        app_user_id=usuarios["plataforma"],
        email="plataforma@igreja-local.test",
    )

    _criar_celulas(db, hoje, agora, celulas, lideres, membros, consolidandos,
                   visitantes, usuarios)
    _criar_consolidacao(db, agora, consolidandos, visitantes, contatos, usuarios)
    _criar_agenda(db, hoje)
    _criar_agente(db)
    _criar_conversas(db, agora, contatos)
    _criar_igreja_vizinha(db, pessoa)
    db.flush()


def _criar_celulas(db, hoje, agora, celulas, lideres, membros, consolidandos,
                   visitantes, usuarios) -> None:
    from app.db.models import (
        Celula,
        CelulaPresenca,
        CelulaReuniao,
        CelulaReuniaoRegistro,
        CelulaVisitante,
    )
    from app.routers.cell_meetings import _build_report_out
    from app.services.celula_membro import ensure_active_membro

    temas = (
        "O amor que acolhe",
        "Fé em tempos difíceis",
        "Servir com alegria",
    )
    for chave, nome, lider, dia, weekday, horario, endereco, _, integrantes in celulas:
        cid = _id(f"celula:{chave}")
        papeis = {c: papel for c, *_, papel in integrantes}
        _ins(
            db,
            Celula,
            id=cid,
            igreja_id=IGREJA_ID,
            nome=nome,
            lider_id=lideres[lider],
            anfitriao_id=membros[next(c for c, p in papeis.items() if p == "anfitriao")],
            auxiliar_id=membros[next(c for c, p in papeis.items() if p == "auxiliar")],
            dia_reuniao=dia,
            horario=horario,
            endereco=endereco,
            cobertura_espiritual="Pr. André Luiz",
            mensagem_convite=f"Venha para a {nome}! {dia} às {horario}.",
            ativo=True,
        )
        db.flush()
        for integrante, papel in papeis.items():
            ensure_active_membro(
                db, igreja_id=IGREJA_ID, celula_id=cid,
                pessoa_id=membros[integrante], papel=papel,
            )

        # Três reuniões realizadas e a próxima planejada. A mais recente da
        # célula de jovens fica com o relatório pendente (aparece como atraso).
        for semanas in (3, 2, 1):
            data = _ultima(hoje, weekday, semanas)
            rid = _id(f"reuniao:{chave}:{semanas}")
            _ins(
                db,
                CelulaReuniao,
                id=rid,
                igreja_id=IGREJA_ID,
                celula_id=cid,
                data=data,
                hora=horario,
                tema=temas[semanas - 1],
                status="realizada",
                relatorio_status="pendente",
                oferta_valor=Decimal("40.00") + Decimal(semanas * 7),
            )
            for i, integrante in enumerate(papeis):
                _ins(
                    db,
                    CelulaPresenca,
                    igreja_id=IGREJA_ID,
                    reuniao_id=rid,
                    pessoa_id=membros[integrante],
                    estado="ausente" if (i + semanas) % 4 == 0 else "compareceu",
                )
            if chave == "vida-nova" and semanas == 1:
                _ins(
                    db,
                    CelulaVisitante,
                    igreja_id=IGREJA_ID,
                    reuniao_id=rid,
                    nome_visitante="Diego Cardoso",
                    telefone=fone(51),
                    observacao="Veio convidado pelo Pedro.",
                )
                _ins(
                    db,
                    CelulaReuniaoRegistro,
                    igreja_id=IGREJA_ID,
                    reuniao_id=rid,
                    tipo="decisao",
                    conteudo="Sofia Barbosa aceitou Jesus.",
                    pessoa_id=consolidandos["sofia"],
                )
            if semanas == 1:
                _ins(
                    db,
                    CelulaReuniaoRegistro,
                    igreja_id=IGREJA_ID,
                    reuniao_id=rid,
                    tipo="oracao",
                    conteudo="Pela saúde da família e por emprego para o grupo.",
                )
            if chave == "jovens" and semanas == 1:
                continue
            db.flush()
            reuniao = db.get(CelulaReuniao, rid)
            reuniao.relatorio_status = "enviado"
            reuniao.relatorio_enviado_em = dt.datetime.combine(
                data, dt.time(23, 30), tzinfo=dt.timezone.utc
            )
            reuniao.relatorio_enviado_por = lideres[lider]
            db.flush()
            reuniao.relatorio_snapshot = _build_report_out(
                db, IGREJA_ID, reuniao
            ).model_dump()
            db.flush()

        _ins(
            db,
            CelulaReuniao,
            id=_id(f"reuniao:{chave}:proxima"),
            igreja_id=IGREJA_ID,
            celula_id=cid,
            data=_proxima(hoje, weekday),
            hora=horario,
            tema="Esperança que não decepciona",
            status="planejada",
            relatorio_status="pendente",
        )


def _criar_consolidacao(db, agora, consolidandos, visitantes, contatos,
                        usuarios) -> None:
    from app.db.models import Consolidacao, ConsolidacaoEtapa, WorkQueueItem
    from app.domain.consolidation import compute_progresso

    patricia = usuarios["patricia"]
    for chave, dias_atras, feitas, prazo_dias in (
        ("rodrigo", 10, ("aceitou_jesus", "fonovisita"), 4),
        ("sofia", 4, ("aceitou_jesus",), 10),
        ("eduardo", 20, ("aceitou_jesus",), -2),
    ):
        inicio = agora - dt.timedelta(days=dias_atras)
        cid = _id(f"consolidacao:{chave}")
        _ins(
            db,
            Consolidacao,
            id=cid,
            igreja_id=IGREJA_ID,
            pessoa_id=consolidandos[chave],
            tipo="individual",
            responsavel_id=patricia,
            progresso=compute_progresso(set(feitas)),
            concluida=False,
            prazo_conexao=agora + dt.timedelta(days=prazo_dias),
            created_at=inicio,
        )
        for i, etapa in enumerate(feitas):
            _ins(
                db,
                ConsolidacaoEtapa,
                igreja_id=IGREJA_ID,
                consolidacao_id=cid,
                etapa=etapa,
                concluida=True,
                confirmada_por=patricia,
                confirmada_em=inicio + dt.timedelta(days=2 * i),
            )

    fila = (
        ("fonovisita", "Fonovisita: Sofia Barbosa",
         "Aceitou Jesus na Célula Vida Nova. Ligar para acolher e marcar a visita.",
         consolidandos["sofia"], patricia, 1, 2),
        ("fonovisita", "Fonovisita atrasada: Eduardo Nunes",
         "Aceitou Jesus no culto há 20 dias e ainda não recebeu a ligação.",
         consolidandos["eduardo"], patricia, -1, 1),
        ("conectar_celula", "Conectar Rodrigo Pereira a uma célula",
         "Mora no Centro. Sugestão: Célula Esperança, quarta-feira às 20h.",
         consolidandos["rodrigo"], patricia, 3, 2),
        ("visitante", "Acolher visitante: Vanessa Moreira",
         "Visitou o culto de domingo e ainda não tem célula.",
         visitantes["vanessa"], PASTOR_USER_ID, 2, 2),
        ("atendimento", "Atendimento humano: Bruno Almeida",
         "Pediu para conversar com um pastor. Conversa aguardando no inbox.",
         contatos["bruno"], None, 0, 1),
        ("relatorio", "Relatório da Célula Jovens em Cristo pendente",
         "A reunião do último sábado ainda não tem relatório.",
         None, usuarios["rafael"], 1, 2),
    )
    for tipo, titulo, contexto, pessoa_id, responsavel, prazo_dias, prioridade in fila:
        _ins(
            db,
            WorkQueueItem,
            igreja_id=IGREJA_ID,
            tipo=tipo,
            titulo=titulo,
            contexto=contexto,
            pessoa_id=pessoa_id,
            responsavel_id=responsavel,
            status="aberto",
            prioridade=prioridade,
            prazo=agora + dt.timedelta(days=prazo_dias, minutes=15),
        )


def _criar_agenda(db, hoje) -> None:
    from app.db.models import Event

    domingo = 0  # events.dia_semana: 0=domingo … 6=sábado
    for titulo, tipo, recorrencia, dia_semana, data, hora, status in (
        ("Culto da Família", "culto", "semanal", domingo, None, "10:00", "confirmado"),
        ("Culto de Celebração", "culto", "semanal", domingo, None, "18:00", "confirmado"),
        ("Reunião de líderes", "reuniao", "pontual", None, _proxima(hoje, 5),
         "09:00", "a_confirmar"),
        ("Encontro com Deus", "especial", "pontual", None,
         hoje + dt.timedelta(days=20), "08:00", "confirmado"),
    ):
        _ins(
            db,
            Event,
            igreja_id=IGREJA_ID,
            titulo=titulo,
            tipo=tipo,
            recorrencia=recorrencia,
            dia_semana=dia_semana,
            data=data,
            hora=hora,
            status=status,
            origem="manual",
        )


def _criar_agente(db) -> None:
    from sqlalchemy import update

    from app.agent.read_only_info import canonical_public_info
    from app.db.models import AgentConfig

    info = canonical_public_info(
        {
            "endereco_igreja": "Rua das Flores, 123 — Centro",
            "horarios_culto": "Domingo às 10h e às 18h.",
            "celulas": [
                {"bairro": "Centro", "nome": "Célula Esperança",
                 "encontro": "Quarta-feira às 20h"},
                {"bairro": "Jardim América", "nome": "Célula Vida Nova",
                 "encontro": "Quinta-feira às 19:30"},
                {"bairro": "Vila Nova", "nome": "Célula Jovens em Cristo",
                 "encontro": "Sábado às 17h"},
            ],
        }
    )
    if info is None:
        raise RuntimeError("perfil público do seed foi recusado pelo validador")
    table = AgentConfig.__table__
    db.execute(
        update(table)
        .where(table.c.igreja_id == IGREJA_ID)
        .values(
            nome="Assistente da Igreja Local",
            tom="acolhedor",
            comportamento=(
                "Você é o assistente pastoral da Igreja Local. Acolha com carinho, "
                "responda de forma curta e convide para o culto ou para a célula "
                "mais próxima. Nunca invente informações."
            ),
            ativo=True,
            informacoes_publicas=info,
        )
    )


def _criar_conversas(db, agora, contatos) -> None:
    from app.db.models import ConsentRecord, Conversation, Message, Pessoa

    termo = (
        "Olá! Sou o assistente virtual da Igreja Local. Para continuar, "
        "guardamos seu nome e telefone só para o acompanhamento pastoral (LGPD). "
        "Você concorda? Responda SIM para continuar ou SAIR para não receber "
        "mensagens."
    )
    # (contato, estado, assumido_por, espera, [(minutos atrás, direção, autor, texto)])
    conversas = (
        ("carla", "ia", None, None, (
            (2900, "in", "contato", "Oi! Vi o Instagram de vocês. Que horas é o culto de domingo?"),
            (2899, "out", "ia", termo),
            (2897, "in", "contato", "sim"),
            (2896, "out", "ia", "Obrigado, Carla! Os cultos são aos domingos às 10h e às 18h, na Rua das Flores, 123 — Centro. Vai ser uma alegria receber você!"),
            (2890, "in", "contato", "Obrigada! Vou domingo à noite 🙂"),
        )),
        ("bruno", "aguardando", None, 24, (
            (25, "in", "contato", "Boa noite. Estou passando por um momento difícil e queria conversar com um pastor."),
            (24, "out", "ia", "Sinto muito que você esteja passando por isso, Bruno. Vou chamar alguém da equipe pastoral para falar com você."),
            (20, "in", "contato", "Obrigado, fico no aguardo."),
        )),
        ("renata", "humano", PASTOR_USER_ID, None, (
            (1500, "in", "contato", "Olá, gostaria de pedir oração pela minha mãe, que está internada."),
            (1499, "out", "ia", termo),
            (1497, "in", "contato", "Sim, concordo."),
            (1496, "out", "ia", "Recebemos seu pedido, Renata. Vou passar para a equipe pastoral."),
            (1470, "out", "humano", "Renata, estamos orando pela sua mãe. Em qual hospital ela está? Posso visitá-la amanhã."),
            (1458, "in", "contato", "No Hospital São Lucas, quarto 204. Muito obrigada, pastor!"),
        )),
        ("paulo", "ia", None, None, (
            (4300, "in", "contato", "Quem é?"),
            (4299, "out", "ia", termo),
            (4290, "in", "contato", "SAIR"),
            (4289, "out", "ia", "Pronto, Paulo. Você não vai mais receber mensagens nossas. Se mudar de ideia, é só mandar OI."),
        )),
    )
    for chave, estado, assumido_por, espera, mensagens in conversas:
        cid = _id(f"conversa:{chave}")
        ultima = mensagens[-1]
        quando = lambda minutos: agora - dt.timedelta(minutes=minutos)  # noqa: E731
        _ins(
            db,
            Conversation,
            id=cid,
            igreja_id=IGREJA_ID,
            pessoa_id=contatos[chave],
            telefone=fone({"carla": 60, "bruno": 61, "renata": 62, "paulo": 63}[chave]),
            estado=estado,
            assumido_por=assumido_por,
            assumido_em=quando(1480) if assumido_por else None,
            ultima_mensagem=ultima[3],
            nao_lidas=2 if estado == "aguardando" else 0,
            espera_desde=quando(espera) if espera is not None else None,
            numero_oficial=True,
            updated_at=quando(ultima[0]),
        )
        for minutos, direcao, autor, texto in mensagens:
            _ins(
                db,
                Message,
                igreja_id=IGREJA_ID,
                conversation_id=cid,
                direcao=direcao,
                autor=autor,
                texto=texto,
                tipo="texto",
                criado_em=quando(minutos),
                autor_nome="Pr. André Luiz" if autor == "humano" else None,
                enviado_por=PASTOR_USER_ID if autor == "humano" else None,
            )

    # O gatilho das mensagens recebidas marca consentimento; aqui fica o estado
    # real de cada conversa: termo aceito, sem resposta ao termo ou opt-out.
    for chave, consentimento, optout in (
        ("carla", True, False),
        ("renata", True, False),
        ("bruno", False, False),
        ("paulo", False, True),
    ):
        _upd(db, Pessoa, contatos[chave], consentimento=consentimento, optout=optout)
    for chave, minutos in (("carla", 2897), ("renata", 1497)):
        _ins(
            db,
            ConsentRecord,
            igreja_id=IGREJA_ID,
            pessoa_id=contatos[chave],
            termo_versao="v1",
            aceite_em=agora - dt.timedelta(minutes=minutos),
        )


def _criar_igreja_vizinha(db, pessoa) -> None:
    """Segunda igreja, criada e aprovada como pelo console: testa o isolamento."""
    from app.db.models import AppUser, Igreja, UserRole
    from app.routers.platform_admin import (
        _seed_agent_from_template,
        _seed_role_permissions,
    )

    admin_id = _id("usuario:vizinha-admin")
    _ins(db, Igreja, id=IGREJA_VIZINHA_ID, nome="Igreja Vizinha (teste)",
         status="ativa", plano="ate_100")
    _ins(db, AppUser, id=admin_id, igreja_id=IGREJA_VIZINHA_ID,
         nome="Secretaria da Igreja Vizinha", email="admin@igreja-vizinha.test",
         status="ativo")
    _ins(db, UserRole, igreja_id=IGREJA_VIZINHA_ID, user_id=admin_id, papel="admin")
    _upd(db, Igreja, IGREJA_VIZINHA_ID, dono_id=admin_id)
    db.flush()
    _seed_role_permissions(db, IGREJA_VIZINHA_ID)
    _seed_agent_from_template(db, IGREJA_VIZINHA_ID)
    for chave, nome, n, genero, tipo, etapa, subetapa in (
        ("vizinha-joao", "João Batista", 901, "m", "visitante", "ganhar", "visitante"),
        ("vizinha-marta", "Marta Silva", 902, "f", "contato", "ganhar", "novo_contato"),
        ("vizinha-lia", "Lia Santos", 903, "f", "contato", "ganhar", "novo_contato"),
    ):
        pessoa(chave, nome, n, genero, tipo, etapa, subetapa, "sem",
               igreja_id=IGREJA_VIZINHA_ID, origem="whatsapp")


def _ligar_contas_de_teste(db) -> list[tuple[str, str]]:
    """Liga as contas do Clerk de desenvolvimento aos logins do seed, por e-mail."""
    from sqlalchemy import select, update

    from app.config import get_settings
    from app.db.models import AppUser, PlatformAdmin
    from app.services.clerk import ClerkAuthError, ClerkClient

    pedidos = [
        (papel, var, alvo, os.environ.get(var, "").strip())
        for papel, var, alvo in CONTAS_DE_TESTE
    ]
    if not any(email for *_, email in pedidos):
        return [(papel, f"sem e-mail ({var})") for papel, var, *_ in pedidos]
    settings = get_settings()
    if not settings.clerk_secret_key:
        return [(papel, "CLERK_SECRET_KEY vazio no .env.dev") for papel, *_ in pedidos]
    if settings.clerk_secret_key.startswith("sk_live_"):
        sys.exit("recusado: CLERK_SECRET_KEY é de produção; use a instância de desenvolvimento")

    users = AppUser.__table__
    admins = PlatformAdmin.__table__
    resultado: list[tuple[str, str]] = []
    clerk = ClerkClient(settings)
    try:
        for papel, var, alvo, email in pedidos:
            if not email:
                resultado.append((papel, f"sem e-mail ({var})"))
                continue
            try:
                clerk_id = clerk.find_user_id_by_email(email)
            except ClerkAuthError:
                resultado.append((papel, "o Clerk recusou a consulta: confira CLERK_SECRET_KEY"))
                continue
            if clerk_id is None:
                resultado.append((papel, f"{email} não existe no Clerk de desenvolvimento"))
                continue
            dono = db.execute(
                select(users.c.id).where(users.c.clerk_user_id == clerk_id)
            ).scalar_one_or_none()
            if papel == "plataforma" and dono is not None:
                alvo = dono  # a mesma conta de outro papel só ganha o console
            elif dono is not None and dono != alvo:
                resultado.append((papel, f"{email} já está ligado a outro papel"))
                continue
            db.execute(
                update(users)
                .where(users.c.id == alvo)
                .values(clerk_user_id=clerk_id, email=email)
            )
            if papel == "plataforma" and db.execute(
                select(admins.c.id).where(admins.c.app_user_id == alvo)
            ).first() is None:
                db.execute(admins.insert().values(app_user_id=alvo, email=email))
            resultado.append((papel, f"ligada a {email}"))
    finally:
        clerk.close()
    return resultado


def _resumo(db) -> list[str]:
    from sqlalchemy import func, select

    from app.db.models import (
        Celula,
        CelulaReuniao,
        Consolidacao,
        Conversation,
        Igreja,
        Pessoa,
    )

    linhas = []
    for igreja_id, nome in db.execute(select(Igreja.id, Igreja.nome).order_by(Igreja.nome)):
        conta = lambda model: db.execute(  # noqa: E731
            select(func.count()).select_from(model).where(model.igreja_id == igreja_id)
        ).scalar_one()
        linhas.append(
            f"{nome}: {conta(Pessoa)} pessoas, {conta(Celula)} células, "
            f"{conta(CelulaReuniao)} reuniões, {conta(Consolidacao)} consolidações, "
            f"{conta(Conversation)} conversas"
        )
    return linhas


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("comando", choices=("migrate", "seed"))
    args = parser.parse_args(argv)
    if args.comando == "migrate":
        return cmd_migrate()
    return cmd_seed()


if __name__ == "__main__":
    raise SystemExit(main())
