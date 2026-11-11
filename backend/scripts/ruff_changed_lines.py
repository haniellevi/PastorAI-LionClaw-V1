"""Ruff ampliado só nas linhas novas ou alteradas de um diff.

O código antigo tem centenas de casos destas regras; corrigir tudo de uma vez
mexeria em arquivos sem relação com a mudança. Este gate impede casos NOVOS:

- DTZ: data/hora sem fuso (``datetime.now()``, ``date.today()``...). Para
  "hoje" da igreja use ``app.datas.hoje_da_igreja()``.
- BLE001: ``except Exception``/``except BaseException`` que engole qualquer
  erro. Capture a exceção esperada; se o amplo for intencional (fronteira de
  worker, por exemplo), marque a linha com ``# noqa: BLE001`` e o motivo.
- F401: import sem uso.

Uso local (a partir da raiz do repositório)::

    python backend/scripts/ruff_changed_lines.py --base origin/main

No CI de pull request o checkout é o merge do PR na base, então o padrão
``HEAD^1`` compara exatamente com a base atual.

Usa só a biblioteca padrão; o executável ``ruff`` vem do PATH ou de ``--ruff``.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterable
import json
import re
import subprocess
import sys

RULES = "DTZ,BLE001,F401"
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines(diff_text: str) -> dict[str, set[int]]:
    """Linhas (na versão nova) adicionadas ou alteradas por arquivo .py."""
    result: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            target = line[4:]
            current = target[2:] if target.startswith("b/") else None
            if current is not None and not current.endswith(".py"):
                current = None
            continue
        match = _HUNK.match(line)
        if match and current is not None:
            start = int(match.group(1))
            count = int(match.group(2)) if match.group(2) is not None else 1
            if count:
                result.setdefault(current, set()).update(range(start, start + count))
    return {path: lines for path, lines in result.items() if lines}


def violations_on_changed_lines(
    findings: Iterable[dict], changed: dict[str, set[int]], root: str
) -> list[dict]:
    """Mantém só os achados cujo intervalo de linhas toca uma linha alterada."""
    prefix = root.rstrip("/") + "/"
    kept = []
    for finding in findings:
        filename = finding.get("filename", "")
        path = filename[len(prefix):] if filename.startswith(prefix) else filename
        lines = changed.get(path)
        if not lines:
            continue
        start = finding["location"]["row"]
        end = (finding.get("end_location") or finding["location"])["row"]
        if any(row in lines for row in range(start, end + 1)):
            kept.append({**finding, "filename": path})
    return sorted(kept, key=lambda f: (f["filename"], f["location"]["row"], f.get("code") or ""))


def _git(args: list[str]) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout


def _ruff_json(ruff: str, paths: list[str]) -> list[dict]:
    completed = subprocess.run(
        [ruff, "check", "--no-cache", "--select", RULES, "--output-format", "json",
         "--exit-zero", *paths],
        check=True, capture_output=True, text=True,
    )
    return json.loads(completed.stdout or "[]")


def run(
    base: str,
    head: str,
    ruff: str,
    git: Callable[[list[str]], str] = _git,
    ruff_json: Callable[[str, list[str]], list[dict]] = _ruff_json,
) -> int:
    root = git(["rev-parse", "--show-toplevel"]).strip()
    diff = git([
        "diff", "--unified=0", "--no-color", "--no-ext-diff", "--diff-filter=AMR",
        f"{base}...{head}", "--", "*.py",
    ])
    changed = changed_lines(diff)
    if not changed:
        print("RUFF_CHANGED_LINES_OK arquivos=0 achados=0")
        return 0
    findings = ruff_json(ruff, [f"{root}/{path}" for path in sorted(changed)])
    kept = violations_on_changed_lines(findings, changed, root)
    for finding in kept:
        location = finding["location"]
        print(f"{finding['filename']}:{location['row']}:{location['column']}: "
              f"{finding.get('code') or 'syntax'} {finding['message']}")
    if kept:
        print(f"RUFF_CHANGED_LINES_FAIL arquivos={len(changed)} achados={len(kept)}",
              file=sys.stderr)
        return 1
    print(f"RUFF_CHANGED_LINES_OK arquivos={len(changed)} achados=0")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="HEAD^1", help="revisão de comparação (padrão: HEAD^1)")
    parser.add_argument("--head", default="HEAD", help="revisão verificada (padrão: HEAD)")
    parser.add_argument("--ruff", default="ruff", help="executável do ruff (padrão: PATH)")
    args = parser.parse_args(argv)
    return run(args.base, args.head, args.ruff)


if __name__ == "__main__":
    sys.exit(main())
