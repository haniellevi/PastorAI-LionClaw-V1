"""Offline ratchet: no new personal-looking contacts in source/fixtures.

The pinned baseline is historical debt, NOT an approval of existing PII.
Only counts are compared in memory; diagnostics never include contact values.
No protected files, network, database, or runtime configuration are read.
Run: python -m unittest discover -s backend/tests -p test_source_contact_privacy.py
"""

from collections import Counter
from pathlib import Path
import re
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
BASE = "2a20a2174efdedd65dde831e8e10a8dcb68e5390"
EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE = re.compile(r"(?<![\w])\+?55[ .-]*\(?[1-9][1-9]\)?[ .-]*9(?:[ .-]*\d){8}(?![\w])")
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".html", ".yaml", ".yml"}


def permitted_path(name):
    path = Path(name)
    parts = path.parts
    if not parts or parts[0] not in {"frontend", "backend"}:
        return False
    if any(p in {"secrets", "node_modules", ".next", "dist", "build", "dumps", "backups", "exports", "media"} for p in parts):
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
        # Reserved domains only, plus the single authorized institutional alias.
        if address == "contato@igreja12.com.br" or domain in {"example.com", "example.org", "example.net"} or domain.endswith((".example", ".test", ".invalid")):
            continue
        found[("email", address)] += 1
    for match in PHONE.finditer(text):
        found[("phone", re.sub(r"\D", "", match.group()))] += 1
    return found


def git(*args):
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True)
    if result.returncode:
        raise AssertionError("Privacy guard requires local baseline objects; Git check failed (output withheld)")
    return result.stdout


class SourceContactPrivacyTests(unittest.TestCase):
    def test_personal_looking_contacts_are_detected_without_real_samples(self):
        personal = "synthetic-user" + "@" + "gmail.com"
        phone = "55" + "11" + "9" + "0" * 8
        self.assertEqual(len(contacts(personal + " " + phone)), 2)
        formatted = "+55 (11) 9" + "0" * 4 + "-" + "0" * 4
        self.assertEqual(sum(contacts(formatted).values()), 1)

    def test_reserved_and_authorized_placeholders_are_allowed(self):
        self.assertFalse(contacts("contato@igreja12.com.br user@example.com 5500000000000"))

    def test_protected_paths_are_excluded(self):
        for name in ["backend/.env", "backend/.env.example", "backend/secrets/a.json", "backend/scripts/clerk_test.py", "backend/scripts/target_users.json", "backend/backups/test.json"]:
            self.assertFalse(permitted_path(name))

    def test_no_new_contact_occurrences_in_source_or_fixtures(self):
        names = git("ls-files", "-z", "--cached", "--others", "--exclude-standard").decode().split("\0")
        baseline_names = set(git("ls-tree", "-r", "--name-only", "-z", BASE).decode().split("\0"))
        violations = []
        for name in sorted(set(names)):
            if not permitted_path(name):
                continue
            path = ROOT / name
            if not path.exists() or path.is_symlink():
                continue
            current = contacts(path.read_text(encoding="utf-8"))
            previous = contacts(git("show", BASE + ":" + name).decode()) if name in baseline_names else Counter()
            if current - previous:
                violations.append(name)
        self.assertFalse(violations, "New contact candidates (values withheld): " + ", ".join(violations))

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

    def test_ratchet_rejects_added_duplicates_and_new_contacts(self):
        candidate = "synthetic-user" + "@" + "gmail.com"
        baseline = contacts(candidate)
        self.assertFalse(contacts(candidate) - baseline)
        self.assertTrue(contacts(candidate + " " + candidate) - baseline)
        self.assertTrue(contacts(candidate) - Counter())


if __name__ == "__main__":
    unittest.main()
