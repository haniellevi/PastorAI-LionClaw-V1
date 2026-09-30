"""Real SQL on a named, network-isolated, synthetic PG17 container only."""
import os
from pathlib import Path
import subprocess
import unittest
import uuid

LEDGER = Path(__file__).resolve().parents[1] / 'backend-release-ledger.sql'
SQL = Path(__file__).resolve().parents[1] / 'backend-release-inventory.sql'
TENANT = '00000000-0000-0000-0000-000000000001'
OTHER = '00000000-0000-0000-0000-000000000002'

class InventoryPG17Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get('BACKEND_INVENTORY_PG17_SYNTHETIC') != '1':
            raise unittest.SkipTest('requires explicitly isolated synthetic PG17 container')
        cls.database = 'inventory_' + uuid.uuid4().hex[:12]
        cls.role = cls.database + '_read'
        cls.filtered = cls.database + '_filtered'
        cls.psql('CREATE DATABASE '+cls.database, database='rls_disposable')
        cls.psql(f'''
CREATE ROLE {cls.role} NOLOGIN BYPASSRLS;
CREATE ROLE {cls.filtered} NOLOGIN;
CREATE TABLE schema_migrations (name text PRIMARY KEY);
INSERT INTO schema_migrations SELECT lpad(n::text,4,'0') || '_synthetic.sql' FROM generate_series(1,17) n;
CREATE TABLE consolidation_whatsapp_activation (igreja_id uuid PRIMARY KEY, activated_at timestamptz, gate_open boolean);
ALTER TABLE consolidation_whatsapp_activation ENABLE ROW LEVEL SECURITY;
ALTER TABLE consolidation_whatsapp_activation FORCE ROW LEVEL SECURITY;
CREATE TABLE notification_outbox (igreja_id uuid, purpose text, state text, origin_kind text);
CREATE TABLE cell_report_reminders (igreja_id uuid, state text);
CREATE TABLE consolidacoes (igreja_id uuid, concluida boolean, abandonada_em timestamptz, created_at timestamptz);
CREATE TABLE work_queue_items (igreja_id uuid, tipo text, status text, created_at timestamptz);
GRANT SELECT ON ALL TABLES IN SCHEMA public TO {cls.role}, {cls.filtered};
INSERT INTO consolidation_whatsapp_activation VALUES ('{TENANT}', now(), false), ('{OTHER}', now(), true);
INSERT INTO notification_outbox SELECT '{TENANT}', 'consolidation_fonovisita', 'pendente', 'work_queue' FROM generate_series(1,121);
INSERT INTO notification_outbox VALUES ('{OTHER}', 'agenda_evt7', 'pendente', 'event');
INSERT INTO cell_report_reminders VALUES ('{TENANT}', 'cancelado');
INSERT INTO consolidacoes VALUES ('{TENANT}', false, null, now()-interval '2 days');
INSERT INTO work_queue_items VALUES ('{TENANT}', 'fonovisita', 'pendente', now()-interval '2 days');
''')

    @classmethod
    def psql(cls, sql, database=None, variables=(), check=True):
        result = subprocess.run(['docker','exec','-i','igreja12-predispatch-pg17-synthetic',
                                 'psql','-X','-U','postgres','-d', database or cls.database,
                                 '-v','ON_ERROR_STOP=1', *variables], input=sql,
                                text=True, capture_output=True)
        if check and result.returncode:
            raise AssertionError(result.stderr)
        return result

    @classmethod
    def tearDownClass(cls):
        cls.psql('DROP DATABASE '+cls.database, database='rls_disposable')
        cls.psql(f'DROP ROLE {cls.role}; DROP ROLE {cls.filtered};', database='rls_disposable')

    def inventory(self, targets=TENANT, role=None, closed='true'):
        return self.psql(SQL.read_text(), variables=['-v','inventory_role='+ (role or self.role),
                         '-v','target_igrejas='+targets,'-v','require_closed='+closed], check=False)

    def test_rls_filtered_empty_is_not_evidence(self):
        empty = self.psql(f'SET ROLE {self.filtered}; SELECT count(*) FROM consolidation_whatsapp_activation;')
        self.assertIn('0', empty.stdout)
        result = self.inventory(role=self.filtered)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PARE', result.stdout)

    def test_missing_marker_refuses(self):
        result = self.inventory(targets='00000000-0000-0000-0000-000000000003')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('PARE_MARCADOR_AUSENTE', result.stdout)

    def test_open_marker_refuses_closure(self):
        result = self.inventory(targets=OTHER)
        self.assertNotEqual(result.returncode, 0)

    def test_empty_target_refuses(self):
        self.assertNotEqual(self.inventory(targets='').returncode, 0)

    def test_duplicate_target_refuses(self):
        self.assertNotEqual(self.inventory(targets=TENANT+','+TENANT).returncode, 0)

    def test_complete_marker_and_scoped_counts(self):
        result = self.inventory()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('121', result.stdout)
        self.assertIn('FECHADO_OBSERVADO', result.stdout)
        self.assertNotIn(OTHER, result.stdout)
        self.assertIn('cancelado', result.stdout)
        self.assertIn('fonovisita', result.stdout)

    def test_partial_target_set_refuses(self):
        self.assertNotEqual(self.inventory(targets=TENANT+','+OTHER).returncode, 0)

    def test_read_only_transaction_rejects_write(self):
        result = self.psql(f'BEGIN READ ONLY; SET LOCAL ROLE {self.role}; DELETE FROM notification_outbox;', check=False)
        self.assertNotEqual(result.returncode, 0)

    def test_ledger_lists_names_and_each_legacy_prefix(self):
        result = self.psql(LEDGER.read_text(), variables=['-v','inventory_role='+self.role])
        self.assertEqual(result.returncode, 0)
        for n in range(1,18):
            self.assertIn(f'{n:04d}_synthetic.sql', result.stdout)
        self.assertIn('legacy_0001_0017', result.stdout)

    def test_null_gate_refuses(self):
        self.psql(f"UPDATE consolidation_whatsapp_activation SET gate_open=null WHERE igreja_id='{TENANT}'")
        try:
            self.assertNotEqual(self.inventory().returncode, 0)
        finally:
            self.psql(f"UPDATE consolidation_whatsapp_activation SET gate_open=false WHERE igreja_id='{TENANT}'")

    def test_null_epoch_refuses(self):
        self.psql(f"UPDATE consolidation_whatsapp_activation SET activated_at=null WHERE igreja_id='{TENANT}'")
        try:
            self.assertNotEqual(self.inventory().returncode, 0)
        finally:
            self.psql(f"UPDATE consolidation_whatsapp_activation SET activated_at=now() WHERE igreja_id='{TENANT}'")
