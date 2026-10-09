"""Target identity and containment are checked before any connection exists."""
import pytest

from scripts.dev_online import validate_target

_REF = 'cxmjojnocigekgcxhubi'


def target():
    return dict(database_url=f'postgresql://postgres.{_REF}:synthetic@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?sslmode=verify-full&sslrootcert=system',
                supabase_url=f'https://{_REF}.supabase.co', approved_project=_REF, app_env='development',
                allow_real_sends=False, brevo_mode='off', asaas_enabled=False, transport='simulado')


def test_nominal_direct_and_pooler_destinations_are_accepted():
    validate_target(**target())
    validate_target(**(target() | {'database_url':f'postgresql://postgres:synthetic@db.{_REF}.supabase.co:5432/postgres?sslmode=verify-full&sslrootcert=system'}))


@pytest.mark.parametrize('change', [
    {'approved_project':'pffafnchtxbimpwyaczq'},
    {'database_url':'postgresql://postgres.pffafnchtxbimpwyaczq:synthetic@aws-0-sa-east-1.pooler.supabase.com:6543/postgres'},
    {'supabase_url':'https://pffafnchtxbimpwyaczq.supabase.co'},
    {'database_url':f'postgresql://postgres.{_REF}:synthetic@attacker.example:6543/postgres'},
    {'database_url':f'postgresql://postgres.{_REF}:synthetic@aws-0-sa-east-1.pooler.supabase.com:6543/postgres?host=attacker.example'},
    {'supabase_url':f'https://{_REF}.supabase.co@attacker.example'},
    {'app_env':'production'}, {'allow_real_sends':True}, {'brevo_mode':'live'},
    {'asaas_enabled':True}, {'transport':'real'},
])
def test_wrong_identity_or_open_gate_is_refused_without_network(change):
    with pytest.raises(ValueError):
        validate_target(**(target() | change))
