"""Pure nominal contract, including private failures at the proposal boundary."""

import pytest

from app.domain.visitor import VisitorNameError, canonical_visitor_name
from app.services.agent_action_proposals import (
    ProposalContractError,
    canonical_visitor_name as proposal_name,
)


@pytest.mark.parametrize("value,expected", [
    (" A ", "A"), ("\u00a0Érica\u00a0", "Érica"), ("架空訪問者", "架空訪問者"),
    ("e\u0301", "e\u0301"), ("A" * 200, "A" * 200),
])
def test_valid_names_keep_content_without_normalization(value, expected):
    assert canonical_visitor_name(value) == proposal_name(value) == expected


class _StringSubclass(str):
    pass


@pytest.mark.parametrize("value", [
    None, True, 123, {}, _StringSubclass("A"), "", "  ", "A" * 201,
    "private\nname", "private\x00name", "private\u202ename", "private\ud800name",
])
def test_invalid_names_have_private_errors_and_preserve_boundary_type(value):
    with pytest.raises(VisitorNameError, match="^nome de visitante inválido$"):
        canonical_visitor_name(value)
    with pytest.raises(ProposalContractError, match="^nome de visitante inválido$"):
        proposal_name(value)
