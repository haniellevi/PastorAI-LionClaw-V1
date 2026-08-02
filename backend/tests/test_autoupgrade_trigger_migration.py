"""Paridade textual do trigger de auto-upgrade (AUTOUPGRADE-BILLING-WORKER-1).

O CI não aplica as migrations da pasta num Postgres real (a suíte
rls_integration usa DDL própria), então estes testes garantem as propriedades
ESTRUTURAIS da redefinição de `fn_subscription_autoupgrade` na migration da
PR — mesma técnica de test_pessoa_arquivamento_migration.py:

  - a migration histórica 0004 permanece intocada;
  - com assinatura Asaas rastreada, o trigger só INSERE a operação durável
    (origin='autoupgrade'), nunca promove plano/limite/rótulo localmente;
  - o upgrade local imediato sobrevive APENAS no ramo sem vínculo remoto;
  - repetições coalescem via ON CONFLICT no índice único parcial (que também
    dá precedência a uma troca manual aberta);
  - o preço alvo vem do catálogo `planos` (nunca hardcoded) e um plano fora
    do catálogo não gera operação.
"""

from __future__ import annotations

from pathlib import Path

_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
_PR_MIGRATION = _MIGRATIONS / "20260730_205332_billing_setup_configuration.sql"
_HISTORICAL = _MIGRATIONS / "0004_triggers.sql"


def _pr_sql() -> str:
    return _PR_MIGRATION.read_text(encoding="utf-8").lower()


def _fn_body() -> str:
    """Corpo da função redefinida (do CREATE até o fechamento $$;)."""
    sql = _pr_sql()
    start = sql.index("create or replace function fn_subscription_autoupgrade")
    end = sql.index("$$;", start)
    return sql[start:end]


def test_historical_0004_remains_untouched() -> None:
    historical = _HISTORICAL.read_text(encoding="utf-8").lower()
    assert "billing_plan_change_operations" not in historical
    # A promoção direta original continua lá — quem a substitui é a migration
    # FORWARD da PR (aplicada depois, por ordem de nome).
    assert "update igrejas set plano" in historical


def test_trigger_is_redefined_in_the_pr_migration() -> None:
    body = _fn_body()
    # A função já era SECURITY DEFINER desde a migration de branding: o tenant
    # não possui UPDATE(plano) em igrejas e a redefinição não pode rebaixá-la.
    assert "security definer" in body
    assert "set search_path = public, pg_temp" in body  # endurecimento de 0006
    assert "insert into billing_plan_change_operations" in body
    # A operação nasce com a entrega da notificação PENDENTE (durável).
    assert "'autoupgrade', 'prepared', 'pending'" in body
    assert "notify_status" in body


def test_tracked_subscription_branch_never_updates_local_plan() -> None:
    body = _fn_body()
    # Exatamente um UPDATE de plano local (subscriptions) e um em igrejas —
    # ambos DENTRO do ramo sem vínculo (asaas_subscription_id is null), que
    # aparece ANTES do insert da operação (ramo com vínculo).
    assert body.count("update igrejas") == 1
    idx_null_branch = body.index("asaas_subscription_id is null")
    idx_local_update = body.index("update igrejas")
    idx_insert = body.index("insert into billing_plan_change_operations")
    assert idx_null_branch < idx_local_update < idx_insert
    # O único outro UPDATE em subscriptions é a contagem de pessoas.
    assert body.count("update subscriptions") == 2
    assert "set pessoas" in body


def test_trigger_coalesces_repeats_and_respects_open_manual_operation() -> None:
    body = _fn_body()
    # ON CONFLICT no índice único parcial (subscription_id | status aberto):
    # repetições do gatilho coalescem, e uma operação MANUAL aberta nunca é
    # sobrescrita (DO NOTHING).
    assert "on conflict (subscription_id)" in body
    assert "where status in ('prepared','processing','reconciling')" in body
    assert "do nothing" in body


def test_target_price_and_limit_are_frozen_from_master_catalog() -> None:
    body = _fn_body()
    assert "from planos" in body
    assert "preco_mensal" in body
    assert "limite_pessoas" in body
    # Plano fora do catálogo não gera operação (nunca inventar preço remoto).
    assert "v_novo_preco is not null" in body
    # Nenhum preço hardcoded no trigger.
    for hardcoded in ("199", "299", "499"):
        assert hardcoded not in body
    assert "v_novo_limite := 200" not in body
    assert "v_novo_limite := 999999" not in body


def test_creation_claim_leases_and_setup_fee_are_persisted() -> None:
    sql = _pr_sql()
    assert "setup_fee_contracted" in sql
    assert "setup_fee             numeric(10,2)" in sql
    # Duas colunas em CREATE TABLE e duas garantias forward-compatible em ALTER.
    assert sql.count("attempt_started_at") >= 4
