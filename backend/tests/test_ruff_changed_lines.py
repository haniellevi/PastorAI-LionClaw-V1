"""Gate do ruff ampliado: só linhas novas ou alteradas contam."""

from scripts import ruff_changed_lines as gate

_DIFF = """\
diff --git a/backend/app/novo.py b/backend/app/novo.py
new file mode 100644
--- /dev/null
+++ b/backend/app/novo.py
@@ -0,0 +1,3 @@
+import os
+import datetime as dt
+agora = dt.datetime.now()
diff --git a/backend/app/antigo.py b/backend/app/antigo.py
--- a/backend/app/antigo.py
+++ b/backend/app/antigo.py
@@ -10 +10 @@ def f():
-    x = 1
+    x = 2
@@ -20,2 +19,0 @@ def g():
-    a = 1
-    b = 2
@@ -30,0 +30,2 @@ def h():
+    try:
+        pass
diff --git a/frontend/src/x.ts b/frontend/src/x.ts
--- a/frontend/src/x.ts
+++ b/frontend/src/x.ts
@@ -1 +1 @@
-a
+b
"""


def _finding(path, row, code, end_row=None):
    return {
        "filename": path,
        "code": code,
        "message": "mensagem",
        "location": {"row": row, "column": 1},
        "end_location": {"row": end_row or row, "column": 9},
    }


def test_changed_lines_keeps_only_added_or_modified_python_lines():
    assert gate.changed_lines(_DIFF) == {
        "backend/app/novo.py": {1, 2, 3},
        "backend/app/antigo.py": {10, 30, 31},
    }


def test_findings_on_untouched_lines_are_ignored():
    changed = {"backend/app/antigo.py": {10, 30, 31}}
    findings = [
        _finding("/repo/backend/app/antigo.py", 10, "DTZ005"),
        _finding("/repo/backend/app/antigo.py", 12, "BLE001"),
        _finding("/repo/backend/app/outro.py", 10, "F401"),
    ]

    kept = gate.violations_on_changed_lines(findings, changed, "/repo")

    assert [(f["filename"], f["location"]["row"], f["code"]) for f in kept] == [
        ("backend/app/antigo.py", 10, "DTZ005"),
    ]


def test_multiline_finding_counts_when_any_of_its_lines_changed():
    changed = {"backend/app/antigo.py": {31}}
    findings = [_finding("/repo/backend/app/antigo.py", 29, "BLE001", end_row=32)]

    assert len(gate.violations_on_changed_lines(findings, changed, "/repo")) == 1


def test_run_fails_with_findings_on_changed_lines(capsys):
    calls = []

    def fake_git(args):
        if args[0] == "rev-parse":
            return "/repo\n"
        calls.append(args)
        return _DIFF

    def fake_ruff(ruff, paths):
        assert ruff == "ruff"
        assert paths == ["/repo/backend/app/antigo.py", "/repo/backend/app/novo.py"]
        return [
            _finding("/repo/backend/app/novo.py", 1, "F401"),
            _finding("/repo/backend/app/antigo.py", 5, "BLE001"),
        ]

    assert gate.run("HEAD^1", "HEAD", "ruff", git=fake_git, ruff_json=fake_ruff) == 1
    out = capsys.readouterr()
    assert "backend/app/novo.py:1:1: F401 mensagem" in out.out
    assert "antigo.py:5" not in out.out
    assert "RUFF_CHANGED_LINES_FAIL arquivos=2 achados=1" in out.err
    assert calls[0][-3:] == ["HEAD^1...HEAD", "--", "*.py"]


def test_run_passes_when_no_python_changed(capsys):
    def fake_git(args):
        return "/repo\n" if args[0] == "rev-parse" else ""

    def fake_ruff(ruff, paths):  # pragma: no cover - não deve ser chamado
        raise AssertionError("ruff não deveria rodar sem .py alterado")

    assert gate.run("HEAD^1", "HEAD", "ruff", git=fake_git, ruff_json=fake_ruff) == 0
    assert "RUFF_CHANGED_LINES_OK arquivos=0" in capsys.readouterr().out
