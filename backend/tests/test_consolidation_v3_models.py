from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint

from app.db.models import (
    AgentActionProposal,
    AgentActionReceipt,
    Consolidacao,
    ConsolidationWhatsappActivation,
    Decision,
    NotificationOutbox,
    WhatsappReminderPreference,
    WorkQueueItem,
)


def _foreign_keys(table):
    return {
        (
            constraint.name,
            tuple(column.name for column in constraint.columns),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in table.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _unique_keys(table):
    return {
        (constraint.name, tuple(column.name for column in constraint.columns))
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _checks(table):
    return {
        (constraint.name, str(constraint.sqltext))
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def _indexes(table):
    return {
        (
            index.name,
            tuple(column.name for column in index.columns),
            index.unique,
            str(index.dialect_options['postgresql'].get('where')),
        )
        for index in table.indexes
        if isinstance(index, Index)
    }


def test_v3_models_keep_tenant_bound_origin_assignment_and_activation_state():
    assert {'origin_decision_id', 'assignment_revision'} <= set(
        Consolidacao.__table__.c.keys()
    )
    assert ('consolidacoes_tenant_id_key', ('igreja_id', 'id')) in _unique_keys(
        Consolidacao.__table__
    )
    assert (
        'consolidacoes_origin_decision_once_key',
        ('igreja_id', 'origin_decision_id'),
    ) in _unique_keys(Consolidacao.__table__)
    assert (
        'consolidacoes_tenant_origin_decision_fkey',
        ('igreja_id', 'origin_decision_id'),
        ('decisions.igreja_id', 'decisions.id'),
        'SET NULL (origin_decision_id)',
    ) in _foreign_keys(Consolidacao.__table__)
    assert ('decisions_tenant_id_key', ('igreja_id', 'id')) in _unique_keys(
        Decision.__table__
    )

    activation = ConsolidationWhatsappActivation.__table__
    assert set(activation.c.keys()) == {'igreja_id', 'activated_at', 'gate_open'}
    assert (
        'consolidation_whatsapp_activation_igreja_fkey',
        ('igreja_id',),
        ('igrejas.id',),
        'CASCADE',
    ) in _foreign_keys(activation)
    assert (
        'consolidation_whatsapp_activation_gate_open_chk',
        'NOT gate_open OR activated_at IS NOT NULL',
    ) in _checks(activation)


def test_v3_work_queue_and_outbox_references_are_tenant_bound_and_survive_source_delete():
    assert 'consolidacao_id' in WorkQueueItem.__table__.c
    assert ('work_queue_items_tenant_id_key', ('igreja_id', 'id')) in _unique_keys(
        WorkQueueItem.__table__
    )
    assert (
        'work_queue_items_fonovisita_consolidacao_once_idx',
        ('igreja_id', 'consolidacao_id'),
        True,
        "tipo = 'fonovisita' AND consolidacao_id IS NOT NULL",
    ) in _indexes(WorkQueueItem.__table__)
    assert (
        'work_queue_items_tenant_consolidacao_fkey',
        ('igreja_id', 'consolidacao_id'),
        ('consolidacoes.igreja_id', 'consolidacoes.id'),
        'CASCADE',
    ) in _foreign_keys(WorkQueueItem.__table__)

    outbox = NotificationOutbox.__table__
    assert {'consolidacao_id', 'work_queue_item_id'} <= set(outbox.c.keys())
    assert (
        'notification_outbox_tenant_consolidacao_fkey',
        ('igreja_id', 'consolidacao_id'),
        ('consolidacoes.igreja_id', 'consolidacoes.id'),
        'SET NULL (consolidacao_id)',
    ) in _foreign_keys(outbox)
    assert (
        'notification_outbox_tenant_work_queue_item_fkey',
        ('igreja_id', 'work_queue_item_id'),
        ('work_queue_items.igreja_id', 'work_queue_items.id'),
        'SET NULL (work_queue_item_id)',
    ) in _foreign_keys(outbox)
    checks = dict(_checks(outbox))
    assert "'consolidation_connection_open'" in checks[
        'notification_outbox_purpose_closed'
    ]
    assert "'consolidation_connection_deadline'" in checks[
        'notification_outbox_purpose_closed'
    ]
    assert "'consolidation_fonovisita'" in checks[
        'notification_outbox_purpose_closed'
    ]
    assert "'consolidacao'" in checks['notification_outbox_origin_kind_closed']
    assert "'work_queue'" in checks['notification_outbox_origin_kind_closed']
    assert 'consolidacao_id IS NULL OR' in checks[
        'notification_outbox_live_origin_identity_chk'
    ]
    assert 'work_queue_item_id IS NULL OR' in checks[
        'notification_outbox_live_origin_identity_chk'
    ]
    assert "purpose = 'consolidation_fonovisita'" in checks[
        'notification_outbox_reference_shape_chk'
    ]
    assert 'AND consolidacao_id IS NULL)' in checks[
        'notification_outbox_reference_shape_chk'
    ]


def test_v3_optin_reuses_the_existing_versioned_reminder_preference():
    checks = dict(_checks(WhatsappReminderPreference.__table__))
    assert "'consolidation'" in checks[
        'whatsapp_reminder_preferences_kind_closed'
    ]


def test_v3_s3_actions_and_receipts_match_the_closed_database_contract():
    proposal_checks = dict(_checks(AgentActionProposal.__table__))
    receipt_checks = dict(_checks(AgentActionReceipt.__table__))

    action_check = proposal_checks['agent_action_proposals_action_closed']
    target_check = proposal_checks['agent_action_proposals_target_kind_closed']
    for action in (
        'configurar_lembrete_consolidacao',
        'marcar_fonovisita_feita',
        'atribuir_consolidacao',
    ):
        assert f"'{action}'" in action_check
    assert "target_kind = 'pendencia_consolidacao'" in target_check
    assert "target_kind = 'consolidacao'" in target_check
    assert "'Fonovisita confirmada.'" in receipt_checks[
        'agent_action_receipts_receipt_text_closed'
    ]
    assert "'Consolidação atribuída.'" in receipt_checks[
        'agent_action_receipts_receipt_text_closed'
    ]
    assert "'Lembretes de consolidação ativados.'" in receipt_checks[
        'agent_action_receipts_receipt_text_closed'
    ]
