#!/usr/bin/env python3
"""Deterministic file-level partitioning and coverage checks for RLS CI."""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TextIO


def parse_collection(output: str) -> dict[str, int]:
    """Count collected node IDs by test file, ignoring pytest's summary lines."""
    counts: dict[str, int] = {}
    for raw_line in output.splitlines():
        node_id = raw_line.strip()
        if "::" not in node_id:
            continue
        path, test_name = node_id.split("::", 1)
        if path.endswith(".py") and test_name:
            counts[path] = counts.get(path, 0) + 1
    if not counts:
        raise ValueError("nenhum nodeid de teste encontrado na coleta pytest")
    return dict(sorted(counts.items()))


def partition_files(test_counts: Mapping[str, int], shard_count: int) -> list[list[str]]:
    """Greedily balance whole files by descending test count, with stable ties."""
    if shard_count < 1:
        raise ValueError("shard_count deve ser maior que zero")
    if len(test_counts) < shard_count:
        raise ValueError("a coleta tem menos arquivos que shards")
    if not test_counts or any(not path or count < 1 for path, count in test_counts.items()):
        raise ValueError("cada arquivo coletado deve ter ao menos um teste")

    files_by_shard: list[list[str]] = [[] for _ in range(shard_count)]
    totals = [0] * shard_count
    for path, count in sorted(test_counts.items(), key=lambda item: (-item[1], item[0])):
        shard = min(range(shard_count), key=lambda index: (totals[index], index))
        files_by_shard[shard].append(path)
        totals[shard] += count
    return [sorted(files) for files in files_by_shard]


def _partition(args: argparse.Namespace) -> int:
    if args.shard < 0 or args.shard >= args.shard_count:
        raise ValueError("shard deve estar entre zero e shard_count - 1")
    counts = parse_collection(args.collection_file.read_text(encoding="utf-8"))
    assignments = partition_files(counts, args.shard_count)
    selected = assignments[args.shard]
    manifest = {
        "schema_version": 1,
        "shard": args.shard,
        "shard_count": args.shard_count,
        "collected_files": counts,
        "collected_total": sum(counts.values()),
        "assigned_files": selected,
        "assigned_total": sum(counts[path] for path in selected),
    }
    args.manifest_file.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print("\n".join(selected))
    return 0


def _junit_counts(path: Path) -> dict[str, int]:
    root = ET.parse(path).getroot()
    suites = list(root.iter("testsuite"))
    if not suites and root.tag == "testsuite":
        suites = [root]
    counts = {"tests": 0, "skipped": 0, "failures": 0, "errors": 0}
    for suite in suites:
        counts["tests"] += int(suite.get("tests", 0))
        counts["skipped"] += int(suite.get("skipped", 0))
        counts["failures"] += int(suite.get("failures", 0))
        counts["errors"] += int(suite.get("errors", 0))
    return counts


def _read_manifest(path: Path, shard: int, shard_count: int) -> dict[str, object]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"{path}: raiz do manifesto deve ser um objeto")
    if manifest.get("schema_version") != 1:
        raise ValueError(f"{path}: schema_version inesperado")
    if manifest.get("shard") != shard or manifest.get("shard_count") != shard_count:
        raise ValueError(f"{path}: identidade de shard divergente")
    files = manifest.get("collected_files")
    assigned = manifest.get("assigned_files")
    if not isinstance(files, dict) or not files or not isinstance(assigned, list):
        raise ValueError(f"{path}: mapa de arquivos ausente ou invalido")
    if any(not isinstance(name, str) or not isinstance(count, int) or count < 1 for name, count in files.items()):
        raise ValueError(f"{path}: contagem de arquivo invalida")
    if any(not isinstance(name, str) for name in assigned):
        raise ValueError(f"{path}: lista atribuida invalida")
    collected_total = sum(files.values())
    assigned_total = sum(files.get(name, 0) for name in assigned)
    if manifest.get("collected_total") != collected_total:
        raise ValueError(f"{path}: total coletado nao confere com os arquivos")
    if manifest.get("assigned_total") != assigned_total:
        raise ValueError(f"{path}: total atribuido nao confere com os arquivos")
    return manifest


def verify_artifacts(
    artifact_directory: Path,
    shard_count: int,
    shard_job_result: str,
    stream: TextIO = sys.stdout,
) -> bool:
    """Print the suite summary and fail on incomplete, duplicate, or failed shards."""
    if shard_count < 1:
        raise ValueError("shard_count deve ser maior que zero")
    shard_manifests: dict[int, dict[str, object]] = {}
    shard_results: dict[int, dict[str, int]] = {}
    validation_errors: list[str] = []

    for shard in range(shard_count):
        manifest_path = artifact_directory / f"rls-shard-{shard}.json"
        junit_path = artifact_directory / f"rls-results-{shard}.xml"
        if manifest_path.is_file():
            try:
                shard_manifests[shard] = _read_manifest(manifest_path, shard, shard_count)
            except (OSError, ValueError, json.JSONDecodeError) as error:
                validation_errors.append(f"FALHA: manifesto do shard {shard} invalido: {error}")
        else:
            validation_errors.append(f"FALHA: manifesto ausente para o shard {shard}.")
        if junit_path.is_file():
            try:
                shard_results[shard] = _junit_counts(junit_path)
            except (OSError, ET.ParseError, ValueError) as error:
                validation_errors.append(f"FALHA: JUnit do shard {shard} invalido: {error}")
        else:
            validation_errors.append(f"FALHA: JUnit ausente para o shard {shard}.")

    total = sum(result["tests"] for result in shard_results.values())
    skipped = sum(result["skipped"] for result in shard_results.values())
    failed = sum(result["failures"] for result in shard_results.values())
    errors_count = sum(result["errors"] for result in shard_results.values())
    executed = total - skipped
    print(
        f"total={total} skipped={skipped} executed={executed} "
        f"failed={failed} errors={errors_count}",
        file=stream,
    )

    if total == 0:
        validation_errors.append(
            "FALHA: 0 testes rls_integration coletados: T1-T6 nao rodaram."
        )
    if executed == 0:
        validation_errors.append(
            "FALHA: todos os testes rls_integration selecionados em skip — "
            "RLS_TEST_DATABASE_URL nao ativou a suite."
        )
    if skipped != 0:
        validation_errors.append(
            "FALHA: houve skip parcial na suite rls_integration selecionada; "
            "todo teste selecionado deve executar no Postgres descartavel."
        )
    if failed != 0 or errors_count != 0:
        validation_errors.append("FALHA: suite rls_integration registrou falha ou erro.")

    if shard_job_result != "success":
        validation_errors.append(
            f"FALHA: job matrix rls-shard terminou com status {shard_job_result}."
        )

    if len(shard_manifests) == shard_count:
        first_manifest = shard_manifests[0]
        collected_files = first_manifest["collected_files"]
        assert isinstance(collected_files, dict)
        collected_total = sum(collected_files.values())
        assigned_owners: dict[str, int] = {}
        for shard, manifest in shard_manifests.items():
            if manifest["collected_files"] != collected_files:
                validation_errors.append(
                    f"FALHA: shard {shard} coletou um mapa de arquivos diferente."
                )
            assigned_files = manifest["assigned_files"]
            assert isinstance(assigned_files, list)
            if len(assigned_files) != len(set(assigned_files)):
                validation_errors.append(f"FALHA: shard {shard} repete arquivo atribuido.")
            for filename in assigned_files:
                if filename not in collected_files:
                    validation_errors.append(
                        f"FALHA: shard {shard} recebeu arquivo ausente da coleta: {filename}."
                    )
                elif filename in assigned_owners:
                    validation_errors.append(
                        f"FALHA: arquivo atribuido aos shards {assigned_owners[filename]} e {shard}: {filename}."
                    )
                else:
                    assigned_owners[filename] = shard
            expected_tests = sum(collected_files.get(filename, 0) for filename in assigned_files)
            if shard in shard_results and shard_results[shard]["tests"] != expected_tests:
                validation_errors.append(
                    f"FALHA: JUnit do shard {shard} registra {shard_results[shard]['tests']} testes; "
                    f"a coleta atribuiu {expected_tests}."
                )
        missing_files = sorted(set(collected_files) - set(assigned_owners))
        if missing_files:
            validation_errors.append(
                "FALHA: arquivos sem shard: " + ", ".join(missing_files)
            )
        if total != collected_total:
            validation_errors.append(
                f"FALHA: total JUnit {total} difere da coleta completa {collected_total}."
            )

    for message in validation_errors:
        print(message, file=stream)
    if validation_errors:
        return False
    print("OK: suite rls_integration selecionada executou de fato.", file=stream)
    return True


def _verify(args: argparse.Namespace) -> int:
    return 0 if verify_artifacts(
        args.artifact_directory,
        args.shard_count,
        args.shard_job_result,
    ) else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    partition_parser = subparsers.add_parser("partition")
    partition_parser.add_argument("--collection-file", type=Path, required=True)
    partition_parser.add_argument("--manifest-file", type=Path, required=True)
    partition_parser.add_argument("--shard", type=int, required=True)
    partition_parser.add_argument("--shard-count", type=int, required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--artifact-directory", type=Path, required=True)
    verify_parser.add_argument("--shard-count", type=int, required=True)
    verify_parser.add_argument("--shard-job-result", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "partition":
            return _partition(args)
        return _verify(args)
    except (OSError, ValueError) as error:
        print(f"FALHA: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
