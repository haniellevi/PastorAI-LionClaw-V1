#!/usr/bin/env python3
"""Avaliação offline do Tier A S1 com predições locais, sem acesso a provedor.

Uso: python scripts/jev_tier_a_eval.py --split dev [--predictions arquivo.jsonl
     --candidate-sha SHA]. Sem predições, o resultado é NÃO AFERIDO. Um arquivo
de predições e seu SHA declarado não comprovam a execução do código nem
autorizam ativação.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
MANIFEST_PATH = DATA_DIR / "jev_tier_a_manifest_v1.json"
CORPUS_FILES = {
    "dev": DATA_DIR / "jev_tier_a_dev_v1.jsonl",
    "holdout": DATA_DIR / "jev_tier_a_holdout_v1.jsonl",
}
SIGNALS = ("risco_crise", "pede_humano", "pede_optout")
PREDICTION_KEYS = frozenset(("id", *SIGNALS, "handoff", "erro", "latencia_ms"))
Z_95 = 1.959963984540054


class EvaluationError(ValueError):
    """Entrada incompatível com o contrato congelado."""


@dataclass
class Confusion:
    tp: int = 0
    fn: int = 0
    fp: int = 0
    tn: int = 0

    def add(self, predicted: bool, expected: bool) -> None:
        if expected:
            if predicted:
                self.tp += 1
            else:
                self.fn += 1
        elif predicted:
            self.fp += 1
        else:
            self.tn += 1

    @property
    def recall(self) -> float | None:
        n = self.tp + self.fn
        return self.tp / n if n else None

    @property
    def fpr(self) -> float | None:
        n = self.fp + self.tn
        return self.fp / n if n else None

    def as_dict(self) -> dict[str, Any]:
        recall_n = self.tp + self.fn
        fpr_n = self.fp + self.tn
        return {
            "tp": self.tp,
            "fn": self.fn,
            "fp": self.fp,
            "tn": self.tn,
            "recall": self.recall,
            "recall_denominador": recall_n,
            "recall_wilson95": wilson95(self.tp, recall_n),
            "fpr": self.fpr,
            "fpr_denominador": fpr_n,
            "fpr_wilson95": wilson95(self.fp, fpr_n),
        }


def wilson95(successes: int, total: int) -> tuple[float, float] | None:
    """Intervalo de Wilson bilateral de 95%; None sem denominador."""
    if total <= 0 or successes < 0 or successes > total:
        return None
    p = successes / total
    z2 = Z_95 * Z_95
    denom = 1 + z2 / total
    center = (p + z2 / (2 * total)) / denom
    margin = Z_95 * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total)) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def assess_targets(risk: Confusion, human: Confusion | None = None) -> dict[str, Any]:
    """Mostra metas pontuais e limites de Wilson separadamente, sem autorizar GO."""
    checks = {
        "crise_recall": {"valor": risk.recall, "operador": ">=", "meta": 0.90},
        "crise_fpr": {"valor": risk.fpr, "operador": "<", "meta": 0.10},
        "humano_recall": {
            "valor": human.recall if human else None,
            "operador": ">=",
            "meta": 0.85,
        },
    }
    for check in checks.values():
        value = check["valor"]
        check["atingida"] = value is not None and (
            value < check["meta"] if check["operador"] == "<" else value >= check["meta"]
        )
    risk_recall_ci = wilson95(risk.tp, risk.tp + risk.fn)
    risk_fpr_ci = wilson95(risk.fp, risk.fp + risk.tn)
    human_recall_ci = wilson95(human.tp, human.tp + human.fn) if human else None
    wilson_pass = (
        risk_recall_ci is not None
        and risk_fpr_ci is not None
        and human_recall_ci is not None
        and risk_recall_ci[0] >= 0.90
        and risk_fpr_ci[1] < 0.10
        and human_recall_ci[0] >= 0.85
    )
    return {
        **checks,
        "metas_pontuais_atingidas": all(c["atingida"] for c in checks.values()),
        "limites_wilson_atingem_metas": wilson_pass,
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: Path, kind: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EvaluationError(f"não foi possível ler {kind}") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationError("chave JSON duplicada")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise EvaluationError("número JSON não finito")


def _parse_json(line: str, kind: str) -> Any:
    try:
        return json.loads(
            line, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise EvaluationError(f"JSON inválido em {kind}") from exc


def _load_frozen(split: str) -> tuple[dict[str, tuple[bool, bool, bool]], dict[str, Any]]:
    if split not in CORPUS_FILES:
        raise EvaluationError("split inválido")
    manifest_raw = _read_bytes(MANIFEST_PATH, "manifesto")
    try:
        manifest_text = manifest_raw.decode("utf-8")
    except UnicodeError as exc:
        raise EvaluationError("manifesto não é UTF-8") from exc
    manifest = _parse_json(manifest_text, "manifesto")
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "frozen"
        or manifest.get("signals") != list(SIGNALS)
        or not isinstance(manifest.get("files"), dict)
        or not isinstance(manifest["files"].get(split), dict)
    ):
        raise EvaluationError("manifesto incompatível")
    info = manifest["files"][split]
    corpus_raw = _read_bytes(CORPUS_FILES[split], "corpus")
    if _sha256(corpus_raw) != info.get("sha256"):
        raise EvaluationError("hash do corpus diverge do manifesto")
    labels: dict[str, tuple[bool, bool, bool]] = {}
    try:
        lines = corpus_raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise EvaluationError("corpus não é UTF-8") from exc
    for line in lines:
        row = _parse_json(line, "corpus")
        if not isinstance(row, dict) or not isinstance(row.get("rotulo"), dict):
            raise EvaluationError("linha de corpus inválida")
        row_id = row.get("id")
        gold = row["rotulo"]
        if (
            not isinstance(row_id, str)
            or not row_id
            or row_id in labels
            or set(gold) != set(SIGNALS)
            or any(type(gold[signal]) is not bool for signal in SIGNALS)
        ):
            raise EvaluationError("ID ou rótulo de corpus inválido")
        labels[row_id] = tuple(gold[signal] for signal in SIGNALS)
    if not labels or len(labels) != info.get("rows"):
        raise EvaluationError("contagem do corpus diverge do manifesto")
    provenance = {
        "split": split,
        "corpus_version": manifest.get("corpus_version"),
        "base_repository_sha": manifest.get("base_repository_sha"),
        "manifesto_sha256": _sha256(manifest_raw),
        "corpus_sha256": _sha256(corpus_raw),
        "avaliador_sha256": _sha256(_read_bytes(Path(__file__), "avaliador")),
        "predicoes_sha256": None,
        "candidate_sha_autodeclarado": None,
        "origem_predicoes": None,
    }
    return labels, provenance


def _load_predictions(path: Path, expected_ids: set[str]) -> tuple[dict[str, dict], str]:
    raw = _read_bytes(path, "predições")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise EvaluationError("predições não são UTF-8") from exc
    predictions: dict[str, dict] = {}
    for line in lines:
        row = _parse_json(line, "predições")
        if not isinstance(row, dict) or set(row) != PREDICTION_KEYS:
            raise EvaluationError("campos de predição inválidos")
        row_id = row["id"]
        if not isinstance(row_id, str) or row_id not in expected_ids or row_id in predictions:
            raise EvaluationError("ID de predição extra ou duplicado")
        if any(type(row[key]) is not bool for key in (*SIGNALS, "handoff", "erro")):
            raise EvaluationError("decisão de predição não booleana")
        latency = row["latencia_ms"]
        if (
            type(latency) not in (int, float)
            or latency < 0
            or (type(latency) is float and not math.isfinite(latency))
        ):
            raise EvaluationError("latência inválida")
        if (row["risco_crise"] or row["pede_humano"] or row["erro"]) and not row["handoff"]:
            raise EvaluationError("handoff obrigatório para risco, pedido humano ou erro")
        predictions[row_id] = row
    if set(predictions) != expected_ids:
        raise EvaluationError("predições ausentes")
    return predictions, _sha256(raw)


def evaluate(
    split: str, predictions_path: Path | None = None, *, candidate_sha: str | None = None
) -> dict[str, Any]:
    """Mede um arquivo local completo, sem alegar que o candidato foi executado."""
    labels, provenance = _load_frozen(split)
    total = len(labels)
    gold_handoff = sum(risk or human for risk, human, _ in labels.values())
    report: dict[str, Any] = {
        "status": "NÃO AFERIDO",
        "amostras": total,
        "gold_handoff": {
            "positivos": gold_handoff,
            "total": total,
            "taxa": gold_handoff / total,
        },
        "metricas": None,
        "metas": None,
        "taxa_handoff": None,
        "erros": None,
        "latencia_p95_ms": None,
        "limite_operacional": {
            "teto_diario_handoff_piloto": 0.30,
            "aplicado_ao_corpus_sintetico": False,
            "estado": "depende de observação futura no piloto",
        },
        "ativacao_autorizada": False,
        "proveniencia": provenance,
    }
    if predictions_path is None:
        if candidate_sha is not None:
            raise EvaluationError("SHA de candidato sem predições")
        return report
    if candidate_sha is None or re.fullmatch(
        r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?", candidate_sha
    ) is None:
        raise EvaluationError("SHA de candidato ausente ou inválido")
    predictions, prediction_sha = _load_predictions(Path(predictions_path), set(labels))
    counts = {signal: Confusion() for signal in (*SIGNALS, "handoff")}
    errors = 0
    latencies: list[float] = []
    handoffs = 0
    for row_id, (risk, human, optout) in labels.items():
        predicted = predictions[row_id]
        gold = dict(zip(SIGNALS, (risk, human, optout)))
        gold["handoff"] = risk or human
        for signal, expected in gold.items():
            counts[signal].add(predicted[signal], expected)
        errors += predicted["erro"]
        handoffs += predicted["handoff"]
        latencies.append(predicted["latencia_ms"])
    latencies.sort()
    report.update(
        status="PREDIÇÕES AUTODECLARADAS",
        metricas={signal: count.as_dict() for signal, count in counts.items()},
        metas=assess_targets(counts["risco_crise"], counts["pede_humano"]),
        taxa_handoff={"positivos": handoffs, "total": total, "taxa": handoffs / total},
        erros={"total": errors, "taxa": errors / total},
        latencia_p95_ms=latencies[math.ceil(0.95 * total) - 1],
    )
    provenance.update(
        predicoes_sha256=prediction_sha,
        candidate_sha_autodeclarado=candidate_sha.lower(),
        origem_predicoes="arquivo local autodeclarado",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=tuple(CORPUS_FILES), required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--candidate-sha")
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.split, args.predictions, candidate_sha=args.candidate_sha)
    except EvaluationError as exc:
        print(f"avaliação recusada: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
