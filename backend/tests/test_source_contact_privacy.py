"""Offline current-tree guard: personal-looking contacts require review.

No Git/history dependency. Diagnostics never include contact values.
No protected files, network, database, or runtime configuration are read.
Run: python -m unittest discover -s backend/tests -p test_source_contact_privacy.py
"""

from collections import Counter
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE = re.compile(r"(?<![\w])\+?55[ .-]*\(?[1-9][1-9]\)?[ .-]*[2-9](?:[ .-]*\d){7,8}(?![\w])")
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".html", ".yaml", ".yml"}
EXCLUDED_DIRS = {"secrets", "node_modules", ".next", "dist", "build", "dumps", "backups", "exports", "media", ".venv", "venv", "__pycache__", ".pytest_cache", ".git"}
REVIEW_PATH = "backend/tests/source_contact_synthetic_review.json"
PERSONAL_PROVIDER = re.compile(r"^(?:gmail|hotmail|outlook|yahoo|live|icloud|aol|proton|protonmail)\.", re.I)
INSTITUTIONAL_ALIASES = {"contato@igreja12.com.br", "no-reply@igreja12.com.br"}
# Exact technical contexts confirmed during triage. These are NOT global phone
# exceptions; executable assignments, other symbols and changed text still fail.
REVIEWED_DOCSTRINGS = {
    "backend/app/domain/phone.py": ("normalize_phone", "9e653f83ac8df81f5ddba799ec644c2db4e4fecedca3fb76096b0b7013efe56a"),
    "backend/app/services/evolution.py": ("numero_from_jid", "cefda5e588f75ab89f2c2477051ff1e37be7cc700ea2693e72bcab0291c24a70"),
}
REVIEWED_DEPRECATION = (
    "node_modules/rimraf/node_modules/glob",
    "55485ce46ec1f7d3378548cbc9d651e489f775e5b19ce47544e7c1de8782b504",
)


def technical_view(name, text):
    """Mask only exact reviewed non-executable contexts, preserving line count."""
    if name in REVIEWED_DOCSTRINGS:
        symbol, expected = REVIEWED_DOCSTRINGS[name]
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return text  # Parse failure never exempts a candidate.
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
                doc = ast.get_docstring(node, clean=False)
                if doc is not None and hashlib.sha256(doc.encode()).hexdigest() == expected:
                    lines = text.splitlines(keepends=True)
                    expression = node.body[0]
                    # Only a standalone literal docstring; do not mask code on
                    # the same line (e.g. a semicolon followed by an assignment).
                    first = lines[expression.lineno - 1]
                    last = lines[expression.end_lineno - 1]
                    if first[:expression.col_offset].strip() or last[expression.end_col_offset:].strip():
                        return text
                    for i in range(expression.lineno - 1, expression.end_lineno):
                        lines[i] = "\n" if lines[i].endswith("\n") else ""
                    return "".join(lines)
    if name == "frontend/package-lock.json":
        package, expected = REVIEWED_DEPRECATION
        try:
            value = json.loads(text)["packages"][package]["deprecated"]
        except (ValueError, KeyError, TypeError):
            return text
        if isinstance(value, str) and hashlib.sha256(value.encode()).hexdigest() == expected:
            literal = json.dumps(value, ensure_ascii=False)
            # Only this exact field, exactly once. Other contacts remain visible.
            field = '"deprecated": ' + literal
            if text.count(field) == 1:
                return text.replace(field, '"deprecated": ""', 1)
    return text


def fixture_path(name):
    return permitted_path(name) and (name.startswith("backend/tests/")
                                    or name.startswith("frontend/e2e/")
                                    or (name.startswith("frontend/") and ".test." in Path(name).name))


def personal_provider(key):
    kind, value = key
    return kind == "email" and bool(PERSONAL_PROVIDER.match(value.rsplit("@", 1)[1]))


def contact_fingerprint(found):
    # Scoped evidence of the exact fixture set confirmed by the owner, NOT a
    # global domain/phone allowlist. Counts prevent insertion of extra copies.
    data = sorted([kind, value, count] for (kind, value), count in found.items()
                  if not personal_provider((kind, value)))
    return hashlib.sha256(json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def reviewed_entries(root):
    path = root / REVIEW_PATH
    if not path.exists():
        return {}  # No manifest => no exceptions, never skip current-tree scan.
    if path.is_symlink():
        raise ValueError("Review manifest must not be a symlink")
    data = json.loads(path.read_text(encoding="utf-8"))
    if set(data) != {"schema_version", "scope", "provenance", "entries"} or data["schema_version"] != 1:
        raise ValueError("Invalid review manifest")
    if data["scope"] != "exact-reviewed-synthetic-contact-set-per-fixture" or data["provenance"] != "owner-confirmed-synthetic-during-local-triage":
        raise ValueError("Invalid review scope")
    for name, entry in data["entries"].items():
        if not fixture_path(name) or ".." in Path(name).parts or set(entry) != {"contact_set_sha256", "occurrences"}:
            raise ValueError("Invalid review entry")
        if not re.fullmatch(r"[0-9a-f]{64}", entry["contact_set_sha256"]) or type(entry["occurrences"]) is not int or entry["occurrences"] <= 0:
            raise ValueError("Invalid review fingerprint")
    return data["entries"]


def permitted_path(name):
    path = Path(name)
    parts = path.parts
    if not parts or parts[0] not in {"frontend", "backend"}:
        return False
    if any(p in EXCLUDED_DIRS for p in parts):
        return False
    if any(p.startswith(".env") for p in parts):
        return False
    if path.name.startswith(("clerk_", "target_users", "id_rsa", "id_ed25519")):
        return False
    if path.name == "migrate_clerk_production.py":
        return False
    return path.suffix in EXTENSIONS


def contacts(text):
    found = Counter()
    for match in EMAIL.finditer(text):
        address = match.group().lower()
        domain = address.split("@", 1)[1]
        # Reserved domains plus two exact institutional aliases, never a domain.
        if address in INSTITUTIONAL_ALIASES or domain in {"example.com", "example.org", "example.net"} or domain.endswith((".example", ".test", ".invalid")):
            continue
        # Numeric JIDs are protocol identifiers, not mailboxes. The PHONE
        # pass still rejects their digits when they look like real contacts.
        if re.fullmatch(r"\d+@(?:s\.whatsapp\.net|g\.us)", address):
            continue
        # Escaped newline followed by a Python decorator, not a mailbox.
        if re.fullmatch(r"n@pytest\.mark(?:\.[a-z]+)*", address) and match.start() and text[match.start() - 1] == "\\":
            continue
        # In DSN authority user:password@host, @ is a separator, not a mailbox.
        # Additional @ (e.g. a personal email in userinfo) is NOT exempted.
        # This contact guard is not a credential scanner.
        at = text.index("@", match.start(), match.end())
        if any(authority.group().count("@") == 1
               and authority.start() <= match.start() < at < authority.end()
               for authority in re.finditer(r"(?:postgresql|redis)://[^/\s\"']+", text)):
            continue
        found[("email", address)] += 1
    for match in PHONE.finditer(text):
        found[("phone", re.sub(r"\D", "", match.group()))] += 1
    return found


def source_paths(root):
    for surface in ("backend", "frontend"):
        start = root / surface
        if not start.is_dir() or start.is_symlink():
            continue
        for directory, dirs, files in os.walk(start, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIRS
                             and not d.startswith(".env")
                             and not (Path(directory) / d).is_symlink())
            for filename in sorted(files):
                path = Path(directory) / filename
                if permitted_path(path.relative_to(root)) and not path.is_symlink():
                    yield path


def violations(root):
    found = []
    try:
        reviews = reviewed_entries(root)
    except (ValueError, TypeError, KeyError, OSError):
        return [REVIEW_PATH + ":invalid (details withheld)"]
    for path in source_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
            text = technical_view(path.relative_to(root).as_posix(), text)
            lines = text.splitlines()
        except (UnicodeError, OSError):
            found.append(str(path.relative_to(root)) + ":unreadable")
            continue
        name = path.relative_to(root).as_posix()
        current = contacts(text)
        review = reviews.get(name) if fixture_path(name) else None
        reviewed = bool(review and contact_fingerprint(current) == review["contact_set_sha256"]
                        and sum(n for key, n in current.items() if not personal_provider(key)) == review["occurrences"])
        for number, line in enumerate(lines, 1):
            if any(not reviewed or personal_provider(key) for key in contacts(line)):
                found.append(f"{path.relative_to(root)}:{number}")
    return found


class SourceContactPrivacyTests(unittest.TestCase):
    def test_personal_looking_contacts_are_detected_without_real_samples(self):
        # Negative probes constructed in memory; no personal mailbox literal.
        personal = "synthetic-user" + chr(64) + "gmail.com"
        phone = "55" + "11" + "9" + "0" * 8
        self.assertEqual(len(contacts(personal + " " + phone)), 2)
        formatted = "+55 (11) 9" + "0" * 4 + "-" + "0" * 4
        self.assertEqual(sum(contacts(formatted).values()), 1)

    def test_reserved_and_authorized_placeholders_are_allowed(self):
        self.assertFalse(contacts("contato@igreja12.com.br no-reply@igreja12.com.br user@example.com 5500000000000"))
        self.assertTrue(contacts("other" + chr(64) + "igreja12.com.br"))
        for provider in ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com"):
            self.assertTrue(contacts("synthetic-probe" + chr(64) + provider))

    def test_protected_paths_are_excluded(self):
        for name in ["backend/.env", "backend/.env.example", "backend/secrets/a.json", "backend/scripts/clerk_test.py", "backend/scripts/target_users.json", "backend/backups/test.json"]:
            self.assertFalse(permitted_path(name))

    def test_current_tree_has_no_unreviewed_contacts(self):
        found = violations(ROOT)
        self.assertFalse(found, "Contacts requiring review (values withheld): " + ", ".join(found))

    def test_three_reported_surfaces_contain_no_contact_candidates(self):
        for name in ["frontend/src/components/legal/legal-config.ts", "frontend/src/app/legal-pages.test.tsx", "frontend/src/components/whatsapp/WhatsappScreen.tsx"]:
            self.assertFalse(contacts((ROOT / name).read_text()), "Contact candidate in " + name + " (value withheld)")

    def test_sanitized_literals_cannot_regress_to_baseline(self):
        legal = (ROOT / "frontend/src/components/legal/legal-config.ts").read_text()
        screen = (ROOT / "frontend/src/components/whatsapp/WhatsappScreen.tsx").read_text()
        self.assertTrue('LEGAL_CONTACT_EMAIL = "contato@igreja12.com.br"' in legal,
                        "Institutional alias changed; value withheld")
        self.assertTrue('placeholder="Ex.: 5500000000000"' in screen,
                        "Synthetic placeholder changed; value withheld")

    def test_technical_formats_and_invalid_area_placeholder_allowed(self):
        self.assertFalse(contacts('placeholder="+55 (DD) 9XXXX-XXXX"'))
        self.assertFalse(contacts(r"^\+?55\d{2}9\d{8}$"))
        self.assertFalse(contacts("5500000000000" + "@s.whatsapp.net"))
        self.assertFalse(contacts("import pytest\\n" + "@pytest.mark.rls_integration"))
        self.assertFalse(contacts("postgresql://u:" + "p@host.invalid:5432/db"))
        self.assertFalse(contacts("redis://user:" + "secret@cache.internal/0"))
        self.assertTrue(contacts("postgresql://user:" + "person" + chr(64) + "gmail.com" + "@db.internal/db"))
        self.assertTrue(contacts("55" + "11" + "9" * 9 + "@s.whatsapp.net"))
        self.assertTrue(contacts("user" + "@" + "example.com.br"))

    def test_no_git_or_base_object_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "frontend").mkdir()
            fixture = root / "frontend" / "fixture.ts"
            fixture.write_text('const email = "user@example.com";', encoding="utf-8")
            with patch("subprocess.run", side_effect=AssertionError("Git forbidden")):
                self.assertEqual(violations(root), [])
                fixture.write_text('const email = "user' + chr(64) + 'gmail.com";', encoding="utf-8")
                self.assertEqual(violations(root), ["frontend/fixture.ts:1"])

    def test_review_is_exact_scoped_and_cannot_allow_personal_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "frontend/src/fixture.test.ts"
            source = 'const email = "fixture' + '@ex.com";'
            path = root / name
            path.parent.mkdir(parents=True)
            path.write_text(source, encoding="utf-8")
            manifest = root / REVIEW_PATH
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "scope": "exact-reviewed-synthetic-contact-set-per-fixture",
                "provenance": "owner-confirmed-synthetic-during-local-triage",
                "entries": {name: {"contact_set_sha256": contact_fingerprint(contacts(source)), "occurrences": 1}},
            }), encoding="utf-8")
            self.assertEqual(violations(root), [])
            # Same domain in a new literal or duplicate still requires review.
            path.write_text(source + source, encoding="utf-8")
            self.assertTrue(violations(root))
            path.write_text(source + ' const other = "person' + chr(64) + 'gmail.com";', encoding="utf-8")
            self.assertTrue(violations(root))
            path.write_text(source, encoding="utf-8")
            (path.parent / "runtime.ts").write_text(source, encoding="utf-8")
            self.assertEqual(violations(root), ["frontend/src/runtime.ts:1"])

    def test_phone_review_changes_and_counts_fail_closed(self):
        original = contacts("55" + "11" + "9" + "0" * 8)
        changed = contacts("55" + "11" + "9" + "0" * 7 + "1")
        self.assertNotEqual(contact_fingerprint(original), contact_fingerprint(changed))
        self.assertNotEqual(contact_fingerprint(original), contact_fingerprint(original + original))
        self.assertFalse(fixture_path("backend/app/config.py"))
        self.assertTrue(fixture_path("backend/tests/test_example.py"))

    def test_review_manifest_has_only_scoped_fingerprints(self):
        entries = reviewed_entries(ROOT)
        self.assertTrue(entries, "Explicit local review manifest required")

    def test_technical_review_does_not_exempt_executable_or_changed_content(self):
        contact = "55" + "11" + "9" + "0" * 8
        doc = "Synthetic format example " + contact
        source = 'def format_example():\n    """' + doc + '"""\n    return None\n'
        name = "backend/app/domain/synthetic_format.py"
        review = {name: ("format_example", hashlib.sha256(doc.encode()).hexdigest())}
        with patch.dict(REVIEWED_DOCSTRINGS, review, clear=True):
            self.assertFalse(contacts(technical_view(name, source)))
            self.assertTrue(contacts(technical_view(name, source + 'phone = "' + contact + '"\n')))
            self.assertTrue(contacts(technical_view(name, source.replace("example", "changed", 1))))
            self.assertTrue(contacts(technical_view("backend/app/other.py", source)))
            same_line = source.replace('"""\n', '"""; phone = "' + contact + '"\n')
            self.assertTrue(contacts(technical_view(name, same_line)))

    def test_technical_dependency_review_is_exact_field_only(self):
        value = "Synthetic upstream notice " + "contact" + chr(64) + "vendor.internal"
        package = "node_modules/synthetic-package"
        review = (package, hashlib.sha256(value.encode()).hexdigest())
        data = {"packages": {package: {"deprecated": value}}}
        with patch.dict(globals(), {"REVIEWED_DEPRECATION": review}):
            text = json.dumps(data)
            self.assertFalse(contacts(technical_view("frontend/package-lock.json", text)))
            self.assertTrue(contacts(technical_view("frontend/src/source.json", text)))
            data["contact"] = value
            self.assertTrue(contacts(technical_view("frontend/package-lock.json", json.dumps(data))))
            data["packages"][package]["deprecated"] = value + " changed"
            self.assertTrue(contacts(technical_view("frontend/package-lock.json", json.dumps(data))))


if __name__ == "__main__":
    unittest.main()
