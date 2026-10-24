"""Vínculo Pessoa ↔ acesso do painel, compartilhado pela rota e pela reconciliação.

A rota ``PUT /team/{id}/pessoa`` e a reconciliação nominal de um vínculo
duplicado legado usam as mesmas guardas: trava Igreja -> Pessoas ordenadas ->
acessos, revalida o vínculo sob trava, recusa liderança ativa e preserva o piso
de administradores. Nada aqui commita: o caller grava a auditoria na mesma
transação e decide commit ou rollback.

As guardas leem somente colunas, nunca a entidade ``Pessoa`` inteira: a
reconciliação roda contra um schema anterior ao lote, em que colunas novas do
modelo ainda não existem.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import insert, or_, select, text, update
from sqlalchemy.orm import Session

from app.db.models import AppUser, Celula, Igreja, Pessoa, PlatformAdmin, PlatformAuditLog, UserRole
from app.services.cell_leadership import sync_role_after_activation

# Mesmos valores de app.deps, sem importar a configuração da aplicação.
ADMIN_ROLE = "admin"
REVOKED_USER_STATUS = "revogado"
ACTIVE_USER_STATUS = "ativo"

RecordEvent = Callable[[str, uuid.UUID], None]


class TeamPessoaError(Exception):
    """Recusa do vínculo web; a rota converte em HTTP com o mesmo detalhe."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def pessoa_ativa_para_vinculo(pessoa) -> bool:
    """Regra de elegibilidade do vínculo administrativo."""

    return pessoa is not None and pessoa.arquivada_em is None and not pessoa.sem_interesse


def active_admin_user_ids(db: Session, igreja_id: uuid.UUID) -> set[uuid.UUID]:
    """Admins com acesso utilizável, não apenas um papel persistido.

    ``status IS NULL`` é legado ativo. Convidado/revogado e conta sem Clerk não
    sustentam o piso de último administrador.
    """
    rows = db.execute(
        select(UserRole.user_id)
        .join(AppUser, AppUser.id == UserRole.user_id)
        .where(
            UserRole.igreja_id == igreja_id,
            UserRole.papel == ADMIN_ROLE,
            AppUser.igreja_id == igreja_id,
            AppUser.clerk_user_id.is_not(None),
            or_(AppUser.status.is_(None), AppUser.status == ACTIVE_USER_STATUS),
        )
    ).scalars().all()
    return set(rows)


def leads_active_cell(db: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID) -> bool:
    return db.execute(
        select(Celula.id).where(
            Celula.igreja_id == igreja_id,
            Celula.lider_id == pessoa_id,
            Celula.ativo.is_(True),
        ).limit(1)
    ).scalar_one_or_none() is not None


def _church_exists(db: Session, igreja_id: uuid.UUID, *, lock: bool) -> bool:
    query = select(Igreja.id).where(Igreja.id == igreja_id)
    return db.execute(query.with_for_update() if lock else query).scalar_one_or_none() is not None


def _people(db: Session, igreja_id: uuid.UUID, ids: list[uuid.UUID], *, lock: bool):
    if not ids:
        return {}
    query = select(Pessoa.id, Pessoa.arquivada_em, Pessoa.sem_interesse).where(
        Pessoa.igreja_id == igreja_id, Pessoa.id.in_(ids),
    ).order_by(Pessoa.id)
    return {row.id: row for row in db.execute(query.with_for_update() if lock else query).all()}


def _lock_access(db: Session, *, igreja_id: uuid.UUID, app_user: AppUser) -> AppUser:
    """Pessoa -> AppUser, como ``cell_leadership`` e a ativação."""

    if app_user.pessoa_id is not None and not _people(
        db, igreja_id, [app_user.pessoa_id], lock=True
    ):
        raise TeamPessoaError(409, "O acesso possui um vínculo de pessoa inconsistente")
    locked = db.execute(
        select(AppUser)
        .where(AppUser.id == app_user.id, AppUser.igreja_id == igreja_id)
        .with_for_update(of=AppUser)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if locked is None:
        raise TeamPessoaError(404, "Usuário não encontrado")
    return locked


def change_pessoa_link(
    db: Session,
    *,
    igreja_id: uuid.UUID,
    usuario_id: uuid.UUID,
    pessoa_id: uuid.UUID | None,
    record: RecordEvent,
) -> bool:
    """Vincula, troca ou desvincula; retorna se houve mudança. Não commita."""

    target = db.execute(select(AppUser).where(
        AppUser.id == usuario_id, AppUser.igreja_id == igreja_id,
    )).scalar_one_or_none()
    if target is None:
        raise TeamPessoaError(404, "Usuário não encontrado")
    previous_pessoa_id = target.pessoa_id
    if not _church_exists(db, igreja_id, lock=True):
        raise TeamPessoaError(409, "Não foi possível validar o piso administrativo da igreja")

    # Igreja -> Pessoas ordenadas -> acesso, compatível com Pessoa -> AppUser
    # da ativação. Revalidar também a espera pela Igreja (FK da Pessoa nova).
    ids = sorted({p for p in (previous_pessoa_id, pessoa_id) if p}, key=str)
    by_id = _people(db, igreja_id, ids, lock=True)
    if pessoa_id is not None:
        person = by_id.get(pessoa_id)
        if person is None:
            raise TeamPessoaError(404, "Pessoa não encontrada")
        if not pessoa_ativa_para_vinculo(person):
            raise TeamPessoaError(409, "Selecione uma Pessoa ativa com interesse ministerial")
        linked = db.execute(select(AppUser.id).where(
            AppUser.igreja_id == igreja_id, AppUser.pessoa_id == pessoa_id,
            AppUser.id != usuario_id,
        ).limit(1)).scalar_one_or_none()
        if linked is not None:
            raise TeamPessoaError(409, "Esta Pessoa já está vinculada a outro usuário")
    target = _lock_access(db, igreja_id=igreja_id, app_user=target)
    if target.pessoa_id != previous_pessoa_id:
        raise TeamPessoaError(409, "O vínculo mudou; atualize a equipe e tente novamente")
    if pessoa_id is not None and target.status == REVOKED_USER_STATUS:
        raise TeamPessoaError(409, "Reative o acesso do usuário antes de vincular uma Pessoa")
    if target.pessoa_id == pessoa_id:
        return False
    # Desvincular/trocar não pode contornar o bloqueio da revogação de líder.
    if target.pessoa_id is not None and leads_active_cell(db, igreja_id, target.pessoa_id):
        raise TeamPessoaError(409, "Transfira ou encerre a liderança antes de alterar o vínculo")
    target.pessoa_id = pessoa_id
    db.flush()
    sync_role_after_activation(db, app_user=target)
    for operation, event_pessoa_id in (("desvincular", previous_pessoa_id),
                                       ("vincular", pessoa_id)):
        if event_pessoa_id is not None:
            record(operation, event_pessoa_id)
    return True


# ---------------------------------------------------------------------------
# Reconciliação excepcional de vínculo duplicado legado
# ---------------------------------------------------------------------------

RECONCILE_ACTION = "team_pessoa_reconciliar_duplicidade"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_REQUIRED_COLUMNS = {
    "igrejas": {"id", "dono_id"},
    "pessoas": {"id", "igreja_id", "arquivada_em", "sem_interesse"},
    "app_users": {"id", "igreja_id", "pessoa_id", "status", "clerk_user_id"},
    "user_roles": {"igreja_id", "user_id", "papel"},
    "celulas": {"id", "igreja_id", "lider_id", "ativo"},
    "platform_admins": {"app_user_id"},
    "platform_audit_log": {
        "id", "actor_id", "actor_email", "acao", "alvo_tipo", "alvo_id",
        "alvo_nome", "detalhe", "created_at",
    },
}

LOCK_TIMEOUT_MIN_MS = 1
LOCK_TIMEOUT_MAX_MS = 30000

REFUSALS = {
    "contas_iguais": "a conta a manter e a conta a corrigir precisam ser diferentes",
    "sha_invalido": "informe o SHA exato de 40 caracteres",
    "lock_timeout_invalido": "lock_timeout deve ficar entre 1 e 30000 ms",
    "confirmacao_invalida": "a confirmação não corresponde ao código emitido pela prévia",
    "conexao_invalida": "conexão inválida; use somente uma URL postgresql na variável dedicada",
    "conta_mantida_invalida": "a conta a manter não é um acesso ativo utilizável",
    "falha_interna": "falha interna; nada foi alterado",
    "role_sem_bypassrls": "a role não ignora RLS; a operação poderia ocultar linhas",
    "schema_incompativel": "schema incompatível com a reconciliação",
    "auditoria_ausente": "auditoria de plataforma ausente ou incompatível",
    "operacao_reutilizada": "o id de operação já foi usado com outro conteúdo",
    "igreja_nao_encontrada": "igreja não encontrada",
    "pessoa_nao_encontrada": "pessoa não encontrada nesta igreja",
    "grupo_resolvido": "o grupo aprovado não está mais duplicado",
    "grupo_divergente": "o grupo atual difere do grupo aprovado",
    "admin_igreja_invalido": "o admin informado não é admin ativo desta igreja",
    "operador_invalido": "o operador informado não é platform admin ativo",
    "lideranca_ativa": "a pessoa lidera célula ativa; transfira ou encerre a liderança antes",
    "lock_indisponivel": "registro em uso por outra operação; nada foi alterado",
    "pos_verificacao_falhou": "a verificação posterior divergiu; nada foi alterado",
    "falha_banco": "falha de banco; nada foi alterado",
}


class ReconciliationRefused(Exception):
    """Recusa sanitizada: só um código e uma mensagem fixa, sem identificadores."""

    def __init__(self, code: str) -> None:
        super().__init__(REFUSALS[code])
        self.code = code


@dataclass(frozen=True)
class DuplicateLinkReconciliation:
    operation_id: uuid.UUID
    igreja_id: uuid.UUID
    pessoa_id: uuid.UUID
    keep_user_id: uuid.UUID
    target_user_id: uuid.UUID
    church_admin_id: uuid.UUID
    operator_id: uuid.UUID
    release_sha: str
    confirmation: str | None = None

    def payload_sha256(self) -> str:
        """Conteúdo aprovado: todos os campos, exceto a própria confirmação."""

        payload = {
            "operation_id": str(self.operation_id),
            "igreja_id": str(self.igreja_id),
            "pessoa_id": str(self.pessoa_id),
            "keep_user_id": str(self.keep_user_id),
            "target_user_id": str(self.target_user_id),
            "church_admin_id": str(self.church_admin_id),
            "operator_id": str(self.operator_id),
            "release_sha": self.release_sha,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class ReconciliationResult:
    code: str  # PREVIA_OK | APLICADA | JA_APLICADA
    group_rows_before: int
    group_rows_after: int
    active_admins_before: int
    active_admins_after: int
    changed_rows: int
    confirmation_token: str | None = None  # emitido só pela prévia


def _require_privileged_schema(db: Session) -> None:
    privileged = db.execute(text(
        "select coalesce((select rolsuper or rolbypassrls from pg_catalog.pg_roles"
        " where rolname = current_user), false)"
    )).scalar_one()
    if not privileged:
        raise ReconciliationRefused("role_sem_bypassrls")
    rows = db.execute(text(
        "select table_name, column_name from information_schema.columns"
        " where table_schema = 'public' and table_name = any(:tables)"
    ), dict(tables=list(_REQUIRED_COLUMNS))).all()
    present: dict[str, set[str]] = {}
    for table, column in rows:
        present.setdefault(table, set()).add(column)
    if not _REQUIRED_COLUMNS["platform_audit_log"] <= present.get("platform_audit_log", set()):
        raise ReconciliationRefused("auditoria_ausente")
    if any(not columns <= present.get(table, set()) for table, columns in _REQUIRED_COLUMNS.items()):
        raise ReconciliationRefused("schema_incompativel")


def _previous_payloads(db: Session, operation_id: uuid.UUID) -> set[str | None]:
    return set(db.execute(text(
        "select detalhe->>'payload_sha256' from public.platform_audit_log"
        " where acao = :acao and detalhe->>'operation_id' = :op"
    ), dict(acao=RECONCILE_ACTION, op=str(operation_id))).scalars().all())


def _roles(db: Session, igreja_id: uuid.UUID, user_ids: list[uuid.UUID]):
    return sorted(db.execute(select(UserRole.user_id, UserRole.papel).where(
        UserRole.igreja_id == igreja_id, UserRole.user_id.in_(user_ids),
    )).all(), key=lambda row: (str(row[0]), row[1]))


def _group(db: Session, igreja_id: uuid.UUID, pessoa_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.execute(select(AppUser.id).where(
        AppUser.igreja_id == igreja_id, AppUser.pessoa_id == pessoa_id,
    )).scalars().all())


def _usable(row) -> bool:
    return row is not None and row.clerk_user_id is not None and (
        row.status is None or row.status == ACTIVE_USER_STATUS
    )


def confirmation_token(request: DuplicateLinkReconciliation) -> str:
    """Código técnico emitido pela prévia; muda com qualquer campo aprovado."""

    return f"DESVINCULAR:{request.payload_sha256()}"


def validate_request(
    request: DuplicateLinkReconciliation, *, apply: bool, lock_timeout_ms: int
) -> None:
    """Recusas que não dependem do banco; o caller as roda antes de conectar."""

    if request.keep_user_id == request.target_user_id:
        raise ReconciliationRefused("contas_iguais")
    if not _SHA_RE.fullmatch(request.release_sha or ""):
        raise ReconciliationRefused("sha_invalido")
    if (
        isinstance(lock_timeout_ms, bool)
        or not isinstance(lock_timeout_ms, int)
        or not LOCK_TIMEOUT_MIN_MS <= lock_timeout_ms <= LOCK_TIMEOUT_MAX_MS
    ):
        raise ReconciliationRefused("lock_timeout_invalido")
    if apply and request.confirmation != confirmation_token(request):
        raise ReconciliationRefused("confirmacao_invalida")


_ACCESS_COLUMNS = (
    AppUser.id, AppUser.igreja_id, AppUser.pessoa_id, AppUser.status, AppUser.clerk_user_id,
)


def _accesses(db: Session, condition, *, lock: bool) -> dict:
    query = select(*_ACCESS_COLUMNS).where(condition).order_by(AppUser.id)
    if lock:
        query = query.with_for_update(of=AppUser)
    return {row.id: row for row in db.execute(query).all()}


def _authorize(db: Session, request: DuplicateLinkReconciliation, rows: dict, *, lock: bool) -> None:
    """Revalida admin da igreja e operador no estado atual.

    Na aplicação trava, depois dos acessos, a linha do papel ``admin`` e a da
    allowlist ``platform_admins``: revogação concorrente espera o commit ou faz
    esta operação recusar após a espera. Operador e admin podem ser o mesmo
    acesso quando ele tem os dois papéis atuais.
    """

    admin = rows.get(request.church_admin_id)
    role = select(UserRole.id).where(
        UserRole.igreja_id == request.igreja_id,
        UserRole.user_id == request.church_admin_id,
        UserRole.papel == ADMIN_ROLE,
    )
    if (
        not _usable(admin)
        or admin.igreja_id != request.igreja_id
        or db.execute(role.with_for_update() if lock else role).first() is None
    ):
        raise ReconciliationRefused("admin_igreja_invalido")
    operator = rows.get(request.operator_id)
    membership = select(PlatformAdmin.id).where(PlatformAdmin.app_user_id == request.operator_id)
    if not _usable(operator) or db.execute(
        membership.with_for_update() if lock else membership
    ).first() is None:
        raise ReconciliationRefused("operador_invalido")


def reconcile_duplicate_link(
    db: Session,
    request: DuplicateLinkReconciliation,
    *,
    apply: bool,
    lock_timeout_ms: int = 5000,
) -> ReconciliationResult:
    """Prévia ou desvínculo de UM acesso escolhido nominalmente. Não commita.

    Na prévia o caller abre transação somente leitura e nada é travado. Na
    aplicação, a ordem Igreja -> Pessoa -> acessos -> papel admin -> allowlist
    estende a da rota, ativação, revogação e liderança; ``lock_timeout`` faz a
    operação desistir em vez de esperar indefinidamente. A auditoria em
    ``platform_audit_log`` é gravada na mesma transação: qualquer falha anula
    também o desvínculo.
    """

    validate_request(request, apply=apply, lock_timeout_ms=lock_timeout_ms)
    _require_privileged_schema(db)
    payload_sha = request.payload_sha256()
    if apply:
        db.execute(text("select set_config('lock_timeout', :v, true)"),
                   dict(v=f"{lock_timeout_ms}ms"))
        # Serializa execuções do mesmo id antes da checagem de idempotência.
        db.execute(text("select pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                   dict(k=f"{RECONCILE_ACTION}:{request.operation_id}"))
    previous = _previous_payloads(db, request.operation_id)
    if previous and previous != {payload_sha}:
        raise ReconciliationRefused("operacao_reutilizada")

    tenant, pessoa_id = request.igreja_id, request.pessoa_id
    keep, target = request.keep_user_id, request.target_user_id
    if previous:
        # Replay: o grupo já foi resolvido, mas a autorização é a de agora.
        rows = _accesses(db, AppUser.id.in_([request.church_admin_id, request.operator_id]), lock=apply)
        _authorize(db, request, rows, lock=apply)
        return ReconciliationResult("JA_APLICADA", 0, 0, 0, 0, 0)

    if not _church_exists(db, tenant, lock=apply):
        raise ReconciliationRefused("igreja_nao_encontrada")
    if not _people(db, tenant, [pessoa_id], lock=apply):
        raise ReconciliationRefused("pessoa_nao_encontrada")
    rows = _accesses(db, or_(
        (AppUser.igreja_id == tenant) & (AppUser.pessoa_id == pessoa_id),
        AppUser.id.in_([keep, target, request.church_admin_id, request.operator_id]),
    ), lock=apply)
    _authorize(db, request, rows, lock=apply)

    group = {uid for uid, row in rows.items() if row.igreja_id == tenant and row.pessoa_id == pessoa_id}
    if target not in group:
        raise ReconciliationRefused("grupo_resolvido" if group == {keep} else "grupo_divergente")
    if group != {keep, target}:
        raise ReconciliationRefused("grupo_divergente")
    if not _usable(rows[keep]):
        raise ReconciliationRefused("conta_mantida_invalida")
    if leads_active_cell(db, tenant, pessoa_id):
        raise ReconciliationRefused("lideranca_ativa")

    admins = active_admin_user_ids(db, tenant)
    statuses = {uid: row.status for uid, row in rows.items()}
    roles = _roles(db, tenant, [keep, target])
    owner = db.execute(select(Igreja.dono_id).where(Igreja.id == tenant)).scalar_one()
    if not apply:
        return ReconciliationResult(
            "PREVIA_OK", len(group), 1, len(admins), len(admins), 0, confirmation_token(request),
        )

    # Só o vínculo muda. Papéis não são sincronizados: com Pessoa nula,
    # ``sync_role_after_activation`` não faria nada, e a regra aqui é mantê-los;
    # a verificação abaixo recusa qualquer diferença.
    changed = db.execute(
        update(AppUser)
        .where(AppUser.id == target, AppUser.igreja_id == tenant, AppUser.pessoa_id == pessoa_id)
        .values(pessoa_id=None)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.execute(insert(PlatformAuditLog).values(
        actor_id=request.operator_id,
        acao=RECONCILE_ACTION,
        alvo_tipo="app_user",
        alvo_id=target,
        detalhe={
            "operation_id": str(request.operation_id),
            "payload_sha256": payload_sha,
            "operacao": "desvincular",
            "igreja_id": str(tenant),
            "pessoa_id": str(pessoa_id),
            "conta_mantida": str(keep),
            "conta_corrigida": str(target),
            "admin_igreja": str(request.church_admin_id),
            "release_sha": request.release_sha,
        },
    ))

    after_rows = db.execute(select(AppUser.id, AppUser.status).where(
        AppUser.id.in_(list(rows)),
    )).all()
    admins_after = active_admin_user_ids(db, tenant)
    if (
        changed != 1
        or _group(db, tenant, pessoa_id) != {keep}
        or admins_after != admins
        or {uid: state for uid, state in after_rows} != statuses
        or _roles(db, tenant, [keep, target]) != roles
        or db.execute(select(Igreja.dono_id).where(Igreja.id == tenant)).scalar_one() != owner
    ):
        raise ReconciliationRefused("pos_verificacao_falhou")
    return ReconciliationResult("APLICADA", len(group), 1, len(admins), len(admins_after), changed)
