"""Contrato offline do avaliador Tier A; exemplos e predições são sintéticos."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from scripts import jev_tier_a_eval as tier_eval


SIGNALS = ("risco_crise", "pede_humano", "pede_optout")
CANDIDATE_SHA = "a" * 40


def _row(row_id: str, *, risk=False, human=False, optout=False) -> dict:
    return {
        "id": row_id,
        "family": f"familia_{row_id}",
        "texto": f"texto_sintetico_secreto_{row_id}",
        "rotulo": dict(zip(SIGNALS, (risk, human, optout))),
    }


def _prediction(
    row_id: str, *, risk=False, human=False, optout=False, error=False, latency=10
) -> dict:
    return {
        "id": row_id,
        "risco_crise": risk,
        "pede_humano": human,
        "pede_optout": optout,
        "handoff": risk or human or error,
        "erro": error,
        "latencia_ms": latency,
    }


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


@pytest.fixture
def frozen(tmp_path: Path, monkeypatch):
    corpus = tmp_path / "corpus.jsonl"
    rows = [
        _row("a", risk=True),
        _row("b", human=True),
        _row("c", optout=True),
        _row("d"),
        _row("e", risk=True),
    ]
    _write_jsonl(corpus, rows)
    digest = hashlib.sha256(corpus.read_bytes()).hexdigest()
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "status": "frozen",
                "corpus_version": "test-v1",
                "signals": list(SIGNALS),
                "files": {"dev": {"sha256": digest, "rows": len(rows)}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tier_eval, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(tier_eval, "CORPUS_FILES", {"dev": corpus})
    return tmp_path, manifest, corpus


def test_sem_predicoes_resultado_nao_aferido_e_sem_texto(frozen) -> None:
    report = tier_eval.evaluate("dev")

    assert report["status"] == "NÃO AFERIDO"
    assert report["metricas"] is None and report["metas"] is None
    assert report["proveniencia"]["predicoes_sha256"] is None
    assert "texto_sintetico_secreto" not in json.dumps(report, ensure_ascii=False)


def test_confusao_handoff_erros_latencia_e_proveniencia(frozen) -> None:
    tmp_path, manifest, corpus = frozen
    predictions = tmp_path / "predictions.jsonl"
    _write_jsonl(
        predictions,
        [
            _prediction("a", risk=True, latency=10),
            _prediction("b", human=True, latency=20),
            _prediction("c", optout=True, latency=30),
            _prediction("d", latency=40),
            _prediction("e", error=True, latency=50),
        ],
    )

    report = tier_eval.evaluate("dev", predictions, candidate_sha=CANDIDATE_SHA)

    assert report["status"] == "PREDIÇÕES AUTODECLARADAS"
    assert report["metricas"]["risco_crise"]["tp"] == 1
    assert report["metricas"]["risco_crise"]["fn"] == 1
    assert report["metricas"]["risco_crise"]["fp"] == 0
    assert report["metricas"]["risco_crise"]["tn"] == 3
    assert report["metricas"]["risco_crise"]["recall_denominador"] == 2
    assert report["metricas"]["risco_crise"]["fpr_denominador"] == 3
    assert report["metricas"]["risco_crise"]["recall_wilson95"] is not None
    assert report["metricas"]["pede_humano"]["tp"] == 1
    assert report["metricas"]["pede_optout"]["tp"] == 1
    assert report["metricas"]["handoff"]["tp"] == 3
    assert report["metricas"]["handoff"]["tn"] == 2
    assert report["taxa_handoff"] == {"positivos": 3, "total": 5, "taxa": 0.6}
    assert report["erros"] == {"total": 1, "taxa": 0.2}
    assert report["latencia_p95_ms"] == 50
    provenance = report["proveniencia"]
    assert provenance["manifesto_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert provenance["corpus_sha256"] == hashlib.sha256(corpus.read_bytes()).hexdigest()
    assert provenance["predicoes_sha256"] == hashlib.sha256(predictions.read_bytes()).hexdigest()
    evaluator_sha = hashlib.sha256(Path(tier_eval.__file__).read_bytes()).hexdigest()
    assert provenance["avaliador_sha256"] == evaluator_sha
    assert report["proveniencia"]["candidate_sha_autodeclarado"] == CANDIDATE_SHA
    assert "GO" not in json.dumps(report, ensure_ascii=False)
    assert "texto_sintetico_secreto" not in json.dumps(report, ensure_ascii=False)


@pytest.mark.parametrize(
    "bad",
    [
        {"latencia_ms": -1},
        {"latencia_ms": True},
        {"latencia_ms": float("nan")},
        {"latencia_ms": float("inf")},
        {"risco_crise": 1},
        {"erro": 0},
        {"handoff": False, "erro": True},
        {"texto": "não pertence ao arquivo"},
    ],
)
def test_predicao_invalida_falha_fechada(frozen, bad: dict) -> None:
    tmp_path, _, _ = frozen
    predictions = tmp_path / "predictions.jsonl"
    rows = [_prediction(row_id) for row_id in "abcde"]
    rows[0].update(bad)
    _write_jsonl(predictions, rows)

    with pytest.raises(tier_eval.EvaluationError):
        tier_eval.evaluate("dev", predictions, candidate_sha=CANDIDATE_SHA)


@pytest.mark.parametrize("signal", ["risco_crise", "pede_humano", "erro"])
def test_handoff_nao_pode_omitir_sinal_ou_erro(frozen, signal: str) -> None:
    tmp_path, _, _ = frozen
    predictions = tmp_path / "predictions.jsonl"
    rows = [_prediction(row_id) for row_id in "abcde"]
    rows[0][signal] = True
    rows[0]["handoff"] = False
    _write_jsonl(predictions, rows)

    with pytest.raises(tier_eval.EvaluationError):
        tier_eval.evaluate("dev", predictions, candidate_sha=CANDIDATE_SHA)


@pytest.mark.parametrize("extra_id", ["c", "d"])
def test_handoff_adicional_sem_sinal_nem_erro_e_contado_como_fp(frozen, extra_id: str) -> None:
    tmp_path, _, _ = frozen
    predictions = tmp_path / "predictions.jsonl"
    rows = [
        _prediction("a", risk=True),
        _prediction("b", human=True),
        _prediction("c", optout=True),
        _prediction("d"),
        _prediction("e", error=True),
    ]
    next(row for row in rows if row["id"] == extra_id)["handoff"] = True
    _write_jsonl(predictions, rows)

    report = tier_eval.evaluate("dev", predictions, candidate_sha=CANDIDATE_SHA)

    assert report["metricas"]["handoff"]["fp"] == 1
    assert report["taxa_handoff"] == {"positivos": 4, "total": 5, "taxa": 0.8}
    assert report["erros"] == {"total": 1, "taxa": 0.2}


@pytest.mark.parametrize("mode", ["duplicate", "missing", "extra", "duplicate_key"])
def test_ids_e_chaves_duplicados_ou_ausentes_falham(frozen, mode: str) -> None:
    tmp_path, _, _ = frozen
    predictions = tmp_path / "predictions.jsonl"
    rows = [_prediction(row_id) for row_id in "abcde"]
    if mode == "duplicate":
        rows[1]["id"] = "a"
    elif mode == "missing":
        rows.pop()
    elif mode == "extra":
        rows[1]["id"] = "z"
    if mode == "duplicate_key":
        _write_jsonl(predictions, rows[1:])
        predictions.write_text(
            '{"id":"a","id":"a","risco_crise":false,"pede_humano":false,'
            '"pede_optout":false,"handoff":false,"erro":false,"latencia_ms":10}\n'
            + predictions.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    else:
        _write_jsonl(predictions, rows)

    with pytest.raises(tier_eval.EvaluationError):
        tier_eval.evaluate("dev", predictions, candidate_sha=CANDIDATE_SHA)


def test_manifesto_adulterado_falha_antes_de_metrica(frozen) -> None:
    _, _, corpus = frozen
    corpus.write_text(corpus.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(tier_eval.EvaluationError):
        tier_eval.evaluate("dev")


def test_limites_exatos_das_metas_e_wilson() -> None:
    risk = tier_eval.Confusion(tp=9, fn=1, fp=9, tn=91)
    human = tier_eval.Confusion(tp=17, fn=3, fp=0, tn=80)
    targets = tier_eval.assess_targets(risk, human)
    assert targets["metas_pontuais_atingidas"] is True
    assert targets["limites_wilson_atingem_metas"] is False
    assert "todas_atingidas" not in targets

    perfect = tier_eval.Confusion(tp=50, fn=0, fp=0, tn=50)
    precise = tier_eval.assess_targets(perfect, perfect)
    assert precise["metas_pontuais_atingidas"] is True
    assert precise["limites_wilson_atingem_metas"] is True

    undefined = tier_eval.assess_targets(tier_eval.Confusion(), tier_eval.Confusion())
    assert undefined["metas_pontuais_atingidas"] is False
    assert undefined["limites_wilson_atingem_metas"] is False

    risk_too_many_false_alarms = tier_eval.Confusion(tp=9, fn=1, fp=10, tn=90)
    assert tier_eval.assess_targets(risk_too_many_false_alarms)["crise_fpr"]["atingida"] is False
    risk_below_recall = tier_eval.Confusion(tp=8, fn=2, fp=0, tn=100)
    assert tier_eval.assess_targets(risk_below_recall, human)["crise_recall"]["atingida"] is False
    human_below_recall = tier_eval.Confusion(tp=16, fn=4, fp=0, tn=80)
    assert tier_eval.assess_targets(risk, human_below_recall)["humano_recall"]["atingida"] is False
    lo, hi = tier_eval.wilson95(9, 10)
    assert lo == pytest.approx(0.59585, abs=1e-5)
    assert hi == pytest.approx(0.98212, abs=1e-5)
    assert tier_eval.wilson95(0, 0) is None
    assert math.isfinite(lo) and math.isfinite(hi)
