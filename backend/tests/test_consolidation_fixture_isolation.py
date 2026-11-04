"""V3 fixture settings must not poison a dedicated login's later import."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("import_login_first", (False, True))
def test_v3_fixture_preserves_dedicated_login_settings_in_fresh_process(import_login_first, tmp_path):
    # A fresh interpreter makes the late-import case independent of collection
    # order. Only configuration is read: no DB, provider or socket is opened.
    script = f"""
import uuid
from pytest import MonkeyPatch
from app.config import get_settings
from tests.test_consolidation_turn_e2e_pg import _install_v3_gates
if {import_login_first!r}:
    import app.db.private_send_session
url = 'postgresql+psycopg2://private_send_runtime:synthetic@127.0.0.1:65431/fixture_test'
with MonkeyPatch.context() as patch:
    patch.setenv('PRIVATE_SEND_DATABASE_URL', url)
    _install_v3_gates(patch, uuid.UUID('11111111-1111-1111-1111-111111111111'))
    from app.db.private_send_session import _validated_url
    assert _validated_url() == url
    assert get_settings().frontend_url == 'https://app.igreja12.example'
    assert get_settings().agent_term_version == 'v3-turn-synthetic-term'
    assert get_settings().effective_session_secret == 'v3-turn-synthetic-secret'
get_settings.cache_clear()
"""
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "PYTHONPATH": os.pathsep.join([str(backend), *sys.path]),
            "LANG": "C.UTF-8",
            "PYTHON_DOTENV_DISABLED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
