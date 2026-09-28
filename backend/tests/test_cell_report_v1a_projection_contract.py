"""Boundary tests: removing private prose must not change a declared number."""
import pytest

from app.services.cell_report_whatsapp import v1a_whitelisted_extraction_projection


@pytest.mark.parametrize('value', ('2.5', '2,5', '20000000', 'doze mil'))
def test_invalid_or_unsupported_count_never_becomes_a_smaller_prefix(value):
    projection = v1a_whitelisted_extraction_projection(f'Relatório: presentes: {value}; visitantes: dois')
    assert 'presentes' not in projection


@pytest.mark.parametrize('value,allowed', (
    ('30,50', {'30,50', '30.50'}),
    ('30.50', {'30,50', '30.50'}),
    ('30 mil', set()),
    ('30 centavos', set()),
))
def test_money_is_preserved_whole_or_left_for_clarification(value, allowed):
    projection = v1a_whitelisted_extraction_projection(f'presentes: dez; oferta: {value}')
    assert 'oferta' not in projection or projection['oferta'] in allowed
