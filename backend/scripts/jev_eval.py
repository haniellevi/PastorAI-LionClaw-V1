#!/usr/bin/env python3
"""Avaliação offline (J0) da triagem Jev contra as regras atuais do agente.

Mede, num corpus sintético pt-BR rotulado, o que as regras de hoje decidem
(opt-out, aceite do termo, CSIM, relatório) e, com ``--jev``, o que o Jev
(TypeSafe) decidiria com as mesmas perguntas de ``app.services.semantic_triage``.
Não toca banco, runtime nem WhatsApp.

Uso, a partir de ``backend/``::

    python scripts/jev_eval.py                        # só regras, sem rede
    python scripts/jev_eval.py --jev --arm pt --arm en --out relatorio.json

``--jev`` exige ``TYPESAFE_API_KEY`` e só envia o corpus versionado
``scripts/data/jev_corpus_v1.jsonl``, revisado no git como dado sintético. Outro
arquivo é recusado: a redação de egresso não detecta nome, endereço ou relato
pastoral, então não prova que um texto é inventado. Texto de pessoa real só sai
pelo modo sombra, com ``ALLOW_REAL_SENDS``, a lista de igrejas e o DPA. Como
defesa extra, a execução para se a redação alterar alguma frase. O gasto tem teto
(``--max-cost-usd``). O relatório traz só ids, nunca o texto, e o veredito só é
GO ou NO-GO quando todas as frases foram respondidas; senão, fica INCONCLUSIVO.

Saída: 0 ok; 2 uso inválido (sem chave, outro corpus, corpus inválido ou não
sintético); 3 interrompido pelo teto de custo (relatório parcial).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Direct ``python scripts/jev_eval.py`` starts with scripts/ as the import root.
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

import httpx

from app.domain import consent as consent_rules
from app.domain.classification import classify_contact
from app.domain.report import looks_like_report
from app.services.semantic_triage import (
    INTENCOES,
    TriageSettings,
    build_request,
    parse_response,
    redact_for_egress,
)

DEFAULT_CORPUS = Path(__file__).resolve().parent / "data" / "jev_corpus_v1.jsonl"

# Preço de tabela da TypeSafe em 2026-09-26: entrada por milhão; saída grátis.
JEV_USD_PER_MILLION_INPUT = 0.042
THRESHOLDS: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95)

SIGNALS: tuple[str, ...] = ("risco", "optout", "aceite", "csim", "relatorio")
# Como a política de produção combinaria cada sinal com a regra existente:
# risco e opt-out somam (regra OU Jev); aceite, CSIM e relatório só passam se
# a regra E o Jev concordarem (o Jev veta, nunca concede sozinho).
ADDITIVE: frozenset[str] = frozenset({"risco", "optout"})
DIFICULDADES: frozenset[str] = frozenset({"direto", "indireto", "armadilha"})
ARMS: tuple[str, ...] = ("pt", "en")

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_COST = 3

# Instruções em inglês sobre o mesmo estado em pt-BR. O inglês é a língua
# principal do Jev; este braço mede se vale a pena trocar o idioma das perguntas.
_EN_QUESTIONS: dict[str, dict[str, Any]] = {
    "risco_pastoral": {
        "instructions": (
            "Does the `mensagem` indicate that the writer, or someone they mention, "
            "is at risk to life or to physical/emotional integrity now or soon, for "
            "example suicidal ideation, self-harm, abuse, domestic violence, a threat "
            "or a medical emergency?"
        ),
        "criteria": {
            "true": (
                "There is a real risk signal a pastor should know about "
                "immediately, even if it is stated indirectly."
            ),
            "false": (
                "Sadness, grief, an ordinary prayer request or a difficulty with no "
                "sign of risk to life or integrity."
            ),
        },
    },
    "pede_optout": {
        "instructions": (
            "In the `mensagem`, does the person ask to stop receiving messages or "
            "communications from the church on this channel?"
        ),
        "criteria": {
            "true": "A request not to be contacted anymore or to leave the list.",
            "false": (
                "Any other use of words like 'sair' (leave) or 'parar' (stop), such "
                "as leaving a job or quitting smoking, or no such request."
            ),
        },
    },
    "intencao": {"instructions": "What is the main intention of the `mensagem`?"},
    "aceita_termo": {
        "instructions": (
            "The church sent a data-use consent term (Brazilian LGPD) and is waiting "
            "for the reply. Is the `mensagem` a clear acceptance of that term, "
            "without reservations?"
        ),
        "criteria": {
            "true": "Unambiguous acceptance (e.g. 'aceito', 'sim, pode').",
            "false": (
                "Refusal, doubt, acceptance with a reservation ('sim, mas não "
                "quero…') or a message about something else."
            ),
        },
    },
}
_EN_INTENCOES: dict[str, str] = {
    "relatorio_celula": (
        "Cell group meeting report: attendance, visitors, decisions, offering or "
        "notes from the meeting."
    ),
    "pedido_oracao": "Asks for prayer for themselves or someone else.",
    "interesse_visitar": (
        "Wants to visit the church or a cell group, or asks for service or meeting "
        "times or address."
    ),
    "contato_comercial": (
        "Offer of a product or service, billing, a quote, advertising or another "
        "commercial contact with no ministerial interest."
    ),
    "fora_da_cidade": "Says they live in another city/state or too far away to attend.",
    "conversa_geral": "Greeting, thanks, a question or an ordinary pastoral conversation.",
    "outro": "None of the above.",
}


class CorpusError(ValueError):
    """Corpus malformado; a mensagem cita o id ou a linha."""


@dataclass(frozen=True)
class Row:
    id: str
    texto: str
    termo_pendente: bool
    ministerial: bool
    rotulo: dict[str, Any]
    dificuldade: str


@dataclass(frozen=True)
class JevAnswer:
    """Uma resposta do Jev já validada por ``parse_response``."""

    modelo: str
    scores: dict[str, float | None]
    intencao: str
    latencia_ms: int
    tokens_in: int
    tokens_out: int


@dataclass
class Confusion:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    tn: int = 0
    fp_ids: list[str] = field(default_factory=list)
    fn_ids: list[str] = field(default_factory=list)

    def add(self, row_id: str, predicted: bool, expected: bool) -> None:
        if predicted and expected:
            self.tp += 1
        elif predicted:
            self.fp += 1
            self.fp_ids.append(row_id)
        elif expected:
            self.fn += 1
            self.fn_ids.append(row_id)
        else:
            self.tn += 1

    @property
    def recall(self) -> float | None:
        total = self.tp + self.fn
        return None if total == 0 else self.tp / total

    @property
    def precision(self) -> float | None:
        total = self.tp + self.fp
        return None if total == 0 else self.tp / total

    @property
    def false_alarm(self) -> float | None:
        """Falso alarme: fração dos negativos marcados como positivos."""
        total = self.fp + self.tn
        return None if total == 0 else self.fp / total

    def as_dict(self) -> dict[str, Any]:
        return {
            "tp": self.tp,
            "fp": self.fp,
            "fn": self.fn,
            "tn": self.tn,
            "precisao": _round(self.precision),
            "recall": _round(self.recall),
            "falso_alarme": _round(self.false_alarm),
            "fp_ids": list(self.fp_ids),
            "fn_ids": list(self.fn_ids),
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------
def load_corpus(path: Path) -> list[Row]:
    rows: list[Row] = []
    seen: set[str] = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            row = Row(
                id=str(raw["id"]),
                texto=str(raw["texto"]),
                termo_pendente=bool(raw["contexto"]["termo_pendente"]),
                ministerial=bool(raw["contexto"]["ministerial"]),
                rotulo=dict(raw["rotulo"]),
                dificuldade=str(raw["dificuldade"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise CorpusError(f"linha {lineno}: {type(exc).__name__}") from exc
        _validate_row(row)
        if row.id in seen:
            raise CorpusError(f"{row.id}: id repetido")
        seen.add(row.id)
        rows.append(row)
    if not rows:
        raise CorpusError("corpus vazio")
    return rows


def _validate_row(row: Row) -> None:
    if not row.texto.strip():
        raise CorpusError(f"{row.id}: texto vazio")
    if row.dificuldade not in DIFICULDADES:
        raise CorpusError(f"{row.id}: dificuldade inválida")
    missing = (set(SIGNALS) | {"intencao"}) - set(row.rotulo)
    if missing:
        raise CorpusError(f"{row.id}: rótulos ausentes {sorted(missing)}")
    for signal in ("risco", "optout", "csim", "relatorio"):
        if not isinstance(row.rotulo[signal], bool):
            raise CorpusError(f"{row.id}: {signal} precisa ser booleano")
    aceite = row.rotulo["aceite"]
    if row.termo_pendente != isinstance(aceite, bool):
        raise CorpusError(f"{row.id}: aceite é booleano só com termo pendente")
    intencao = row.rotulo["intencao"]
    if intencao is not None and intencao not in INTENCOES:
        raise CorpusError(f"{row.id}: intenção fora de INTENCOES")


def non_synthetic_ids(rows: list[Row]) -> list[str]:
    """Ids cujo texto seria alterado pela redação de egresso (dado real)."""
    return [row.id for row in rows if redact_for_egress(row.texto) != row.texto]


# ---------------------------------------------------------------------------
# Previsões
# ---------------------------------------------------------------------------
def rules_predict(row: Row) -> dict[str, bool | None]:
    """O que as regras de produção decidem hoje para a frase."""
    return {
        # Não existe detecção de crise nas regras (bug B6).
        "risco": False,
        "optout": consent_rules.is_optout_request(row.texto),
        "aceite": consent_rules.is_acceptance(row.texto) if row.termo_pendente else None,
        "csim": classify_contact(row.texto).sem_interesse is True,
        # O roteador só trata relatório de remetente ministerial.
        "relatorio": row.ministerial and looks_like_report(row.texto),
    }


def build_payload(row: Row, *, model: str, arm: str) -> dict[str, Any]:
    payload = build_request(
        row.texto,
        termo_pendente=row.termo_pendente,
        remetente_ministerial=row.ministerial,
        model=model,
    )
    if arm == "en":
        _to_english(payload)
    return payload


def _to_english(payload: dict[str, Any]) -> None:
    questions = payload["questions"]
    for qid, question in questions.items():
        english = _EN_QUESTIONS[qid]
        question["instructions"] = english["instructions"]
        if qid == "intencao":
            question["criteria"] = dict(_EN_INTENCOES)
        else:
            question["criteria"] = dict(english["criteria"])


def parse_jev(body: dict[str, Any], *, latencia_ms: int) -> JevAnswer:
    """Valida com ``parse_response`` e extrai os escores de cada sinal."""
    triage = parse_response(body, latencia_ms=latencia_ms)
    raw_probs = body["answers"]["intencao"].get("probabilities") or {}
    probs = {str(k): float(v) for k, v in raw_probs.items()}
    if not probs:
        probs = {triage.intencao: 1.0}
    return JevAnswer(
        modelo=triage.modelo,
        scores={
            "risco": triage.risco_pastoral,
            "optout": triage.pede_optout,
            "aceite": triage.aceita_termo,
            "csim": probs.get("contato_comercial", 0.0) + probs.get("fora_da_cidade", 0.0),
            "relatorio": probs.get("relatorio_celula", 0.0),
        },
        intencao=triage.intencao,
        latencia_ms=triage.latencia_ms,
        tokens_in=triage.tokens_in,
        tokens_out=triage.tokens_out,
    )


def jev_cost_usd(tokens_in: int) -> float:
    return tokens_in * JEV_USD_PER_MILLION_INPUT / 1_000_000


def _estimate_tokens(payload: dict[str, Any]) -> int:
    # Estimativa conservadora antes da primeira resposta (~3 caracteres/token).
    return math.ceil(len(json.dumps(payload, ensure_ascii=False)) / 3)


@dataclass
class ArmRun:
    arm: str
    answers: dict[str, JevAnswer] = field(default_factory=dict)
    erros: Counter[str] = field(default_factory=Counter)
    modelos: set[str] = field(default_factory=set)


@dataclass
class JevRun:
    arms: list[ArmRun]
    gasto_usd: float = 0.0
    chamadas: int = 0
    interrompido_por_custo: bool = False


def run_jev(
    rows: list[Row],
    *,
    settings: TriageSettings,
    arms: list[str],
    model: str,
    max_cost_usd: float,
    timeout: float,
    transport: httpx.BaseTransport | None = None,
) -> JevRun:
    """Uma chamada por frase e braço, com um único cliente (conexão reaproveitada)."""
    run = JevRun(arms=[ArmRun(arm=arm) for arm in arms])
    headers = {"Authorization": f"Bearer {settings.typesafe_api_key}"}
    with httpx.Client(timeout=timeout, transport=transport) as client:
        for arm_run in run.arms:
            for row in rows:
                payload = build_payload(row, model=model, arm=arm_run.arm)
                if run.chamadas:
                    media = sum(
                        a.tokens_in for r in run.arms for a in r.answers.values()
                    ) / max(1, sum(len(r.answers) for r in run.arms))
                    previsto = jev_cost_usd(math.ceil(media) or _estimate_tokens(payload))
                else:
                    previsto = jev_cost_usd(_estimate_tokens(payload))
                if run.gasto_usd + previsto > max_cost_usd:
                    run.interrompido_por_custo = True
                    return run
                started = time.monotonic()
                run.chamadas += 1
                try:
                    resp = client.post(settings.typesafe_api_url, json=payload, headers=headers)
                    resp.raise_for_status()
                    latencia_ms = int((time.monotonic() - started) * 1000)
                    answer = parse_jev(resp.json(), latencia_ms=latencia_ms)
                except httpx.HTTPError as exc:
                    # Sem corpo no relatório: a resposta pode ecoar o estado.
                    arm_run.erros[type(exc).__name__] += 1
                    continue
                except (KeyError, TypeError, ValueError):
                    arm_run.erros["resposta_inesperada"] += 1
                    continue
                run.gasto_usd += jev_cost_usd(answer.tokens_in)
                arm_run.answers[row.id] = answer
                arm_run.modelos.add(answer.modelo)
    return run


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def score_rules(rows: list[Row]) -> dict[str, Confusion]:
    result = {signal: Confusion() for signal in SIGNALS}
    for row in rows:
        predicted = rules_predict(row)
        for signal in SIGNALS:
            expected = row.rotulo[signal]
            if expected is None or predicted[signal] is None:
                continue
            result[signal].add(row.id, bool(predicted[signal]), bool(expected))
    return result


def score_jev(
    rows: list[Row], answers: dict[str, JevAnswer], *, policy: bool
) -> dict[str, dict[str, Confusion]]:
    """Confusão por sinal e limiar; ``policy`` combina com a regra existente."""
    result = {
        signal: {f"{t:.2f}": Confusion() for t in THRESHOLDS} for signal in SIGNALS
    }
    for row in rows:
        answer = answers.get(row.id)
        if answer is None:
            continue
        rules = rules_predict(row)
        for signal in SIGNALS:
            expected = row.rotulo[signal]
            score = answer.scores[signal]
            if expected is None or score is None:
                continue
            if signal == "relatorio" and not row.ministerial and not policy:
                # Relatório só existe para remetente ministerial.
                score = 0.0
            for t in THRESHOLDS:
                jev_says = score >= t
                if policy:
                    rule = bool(rules[signal])
                    predicted = (rule or jev_says) if signal in ADDITIVE else (rule and jev_says)
                else:
                    predicted = jev_says
                result[signal][f"{t:.2f}"].add(row.id, predicted, bool(expected))
    return result


def score_intent(rows: list[Row], answers: dict[str, JevAnswer]) -> dict[str, Any]:
    total = acertos = 0
    trocas: Counter[str] = Counter()
    for row in rows:
        expected = row.rotulo["intencao"]
        answer = answers.get(row.id)
        if expected is None or answer is None:
            continue
        total += 1
        if answer.intencao == expected:
            acertos += 1
        else:
            trocas[f"{expected}->{answer.intencao}"] += 1
    return {
        "avaliadas": total,
        "acuracia": _round(acertos / total) if total else None,
        "trocas": dict(trocas.most_common()),
    }


def latency_stats(answers: dict[str, JevAnswer], order: list[str]) -> dict[str, Any]:
    """Primeira chamada à parte (inclui o handshake TLS no 1º braço) e p50/p95 das demais."""
    samples = [answers[row_id].latencia_ms for row_id in order if row_id in answers]
    if not samples:
        return {"primeira_ms": None, "p50_ms": None, "p95_ms": None, "amostras": 0}
    demais = sorted(samples[1:]) or [samples[0]]

    def pct(p: float) -> int:
        return demais[max(0, math.ceil(p * len(demais)) - 1)]

    return {
        "primeira_ms": samples[0],
        "p50_ms": pct(0.50),
        "p95_ms": pct(0.95),
        "amostras": len(samples),
    }


# ---------------------------------------------------------------------------
# Critérios de GO
# ---------------------------------------------------------------------------
def go_checks(
    rules: dict[str, Confusion],
    jev: dict[str, dict[str, Confusion]],
    policy: dict[str, dict[str, Confusion]],
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    # Crise: o maior limiar com recall >= 95% e falso alarme <= 5%.
    ok_t = [
        t for t, c in jev["risco"].items()
        if (c.recall or 0) >= 0.95 and (c.false_alarm or 0) <= 0.05
    ]
    chosen = max(ok_t) if ok_t else None
    checks.append(_check(
        "crise: recall >= 95% com falso alarme <= 5%", chosen, jev["risco"],
    ))

    # Opt-out: o menor limiar em que o Jev não acrescenta nenhum falso opt-out
    # e pega mais do que a regra sozinha. Os falsos da própria regex (B15) não
    # contam aqui: a política soma, então fp da política = fp da regra + fp novo.
    base = rules["optout"]
    ok_t = [
        t for t, c in policy["optout"].items()
        if c.fp - base.fp == 0 and (c.recall or 0) > (base.recall or 0)
    ]
    chosen = min(ok_t) if ok_t else None
    checks.append(_check(
        "opt-out: o Jev não cria falso opt-out e pega mais que a regra",
        chosen,
        policy["optout"],
    ))

    # Aceite: o menor limiar em que o veto barra todo aceite falso da regra.
    ok_t = [t for t, c in policy["aceite"].items() if c.fp == 0]
    chosen = min(ok_t) if ok_t else None
    checks.append(_check(
        "aceite: o veto barra todo 'sim, mas não…'", chosen, policy["aceite"],
    ))

    # CSIM: o menor limiar sem falso positivo mantendo 80% dos acertos da regra.
    base_tp = rules["csim"].tp
    ok_t = [
        t for t, c in policy["csim"].items()
        if c.fp == 0 and c.tp >= 0.8 * base_tp
    ]
    chosen = min(ok_t) if ok_t else None
    checks.append(_check(
        "CSIM: sem os falsos positivos de substring (mantém 80% dos acertos)",
        chosen,
        policy["csim"],
    ))
    return checks


def _check(
    criterio: str, chosen: str | None, by_threshold: dict[str, Confusion]
) -> dict[str, Any]:
    if chosen is None:
        return {"criterio": criterio, "ok": False, "limiar": None}
    c = by_threshold[chosen]
    return {
        "criterio": criterio,
        "ok": True,
        "limiar": float(chosen),
        "recall": _round(c.recall),
        "falso_alarme": _round(c.false_alarm),
    }


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------
def build_report(
    rows: list[Row], corpus: Path, jev_run: JevRun | None
) -> dict[str, Any]:
    rules = score_rules(rows)
    report: dict[str, Any] = {
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": corpus.stem,
        "frases": len(rows),
        "por_dificuldade": dict(Counter(row.dificuldade for row in rows)),
        "modo": "regras+jev" if jev_run else "regras",
        "regras": {signal: c.as_dict() for signal, c in rules.items()},
        "jev": {},
        "go": None,
        "veredito": None,
    }
    if jev_run is None:
        return report
    order = [row.id for row in rows]
    report["custo"] = {
        "chamadas": jev_run.chamadas,
        "usd": round(jev_run.gasto_usd, 6),
        "usd_por_mil_mensagens": _cost_per_thousand(jev_run),
        "interrompido_por_custo": jev_run.interrompido_por_custo,
    }
    go_por_braco: dict[str, list[dict[str, Any]]] = {}
    vereditos: dict[str, str] = {}
    for arm_run in jev_run.arms:
        jev = score_jev(rows, arm_run.answers, policy=False)
        policy = score_jev(rows, arm_run.answers, policy=True)
        answers = arm_run.answers
        completo = len(answers) == len(rows)
        report["jev"][arm_run.arm] = {
            "respondidas": len(answers),
            "erros": dict(arm_run.erros),
            "modelos": sorted(arm_run.modelos),
            "latencia": latency_stats(answers, order),
            "tokens_in": sum(a.tokens_in for a in answers.values()),
            "tokens_out": sum(a.tokens_out for a in answers.values()),
            "sozinho": _dump(jev),
            "politica": _dump(policy),
            "intencao": score_intent(rows, answers),
            "completo": completo,
        }
        checks = go_checks(rules, jev, policy)
        go_por_braco[arm_run.arm] = checks
        vereditos[arm_run.arm] = _verdict(checks, completo=completo)
    report["go"] = go_por_braco
    report["veredito"] = vereditos
    return report


def _verdict(checks: list[dict[str, Any]], *, completo: bool) -> str:
    # Com frases sem resposta (erro da API ou teto de custo), as métricas
    # descrevem um subconjunto enviesado e não podem decidir o J0.
    if not completo:
        return "INCONCLUSIVO"
    return "GO" if all(c["ok"] for c in checks) else "NO-GO"


def _cost_per_thousand(jev_run: JevRun) -> float | None:
    respondidas = sum(len(r.answers) for r in jev_run.arms)
    if not respondidas:
        return None
    return round(jev_run.gasto_usd / respondidas * 1000, 4)


def _dump(data: dict[str, dict[str, Confusion]]) -> dict[str, Any]:
    return {
        signal: {t: c.as_dict() for t, c in by_t.items()} for signal, by_t in data.items()
    }


def render_markdown(report: dict[str, Any]) -> str:
    out: list[str] = [
        "# Avaliação Jev (J0)",
        "",
        f"- Gerado em: {report['gerado_em']}",
        f"- Corpus: `{report['corpus']}`, {report['frases']} frases "
        f"({_fmt_counts(report['por_dificuldade'])})",
        f"- Modo: {report['modo']}",
    ]
    if report.get("custo"):
        custo = report["custo"]
        por_mil = custo["usd_por_mil_mensagens"]
        out.append(
            f"- Chamadas: {custo['chamadas']}; custo US$ {custo['usd']:.6f} "
            f"(US$ {'-' if por_mil is None else por_mil} por mil mensagens)"
        )
        if custo["interrompido_por_custo"]:
            out.append("- **Interrompido pelo teto de custo: relatório parcial.**")
    out += [
        "",
        "## Regras atuais",
        "",
        "| Sinal | Precisão | Recall | Falso alarme | FP | FN |",
        "|---|---|---|---|---|---|",
    ]
    for signal, c in report["regras"].items():
        out.append(_metric_row(signal, c))
    for signal, c in report["regras"].items():
        if c["fp_ids"] or c["fn_ids"]:
            out.append(
                f"- {signal}: FP {', '.join(c['fp_ids']) or '-'}; "
                f"FN {', '.join(c['fn_ids']) or '-'}"
            )
    for arm, data in report["jev"].items():
        lat = data["latencia"]
        out += [
            "",
            f"## Jev, instruções {arm.upper()}",
            "",
            f"- Respondidas: {data['respondidas']}; erros: {data['erros'] or 'nenhum'}; "
            f"modelo(s): {', '.join(data['modelos']) or '-'}",
            f"- Latência: primeira chamada {lat['primeira_ms']} ms; p50 {lat['p50_ms']} ms; "
            f"p95 {lat['p95_ms']} ms",
            f"- Intenção: acurácia {data['intencao']['acuracia']} em "
            f"{data['intencao']['avaliadas']} frases",
            "",
            "| Sinal | Fonte | Limiar | Precisão | Recall | Falso alarme | FP | FN |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for fonte in ("sozinho", "politica"):
            for signal, by_t in data[fonte].items():
                for t, c in by_t.items():
                    out.append(
                        f"| {signal} | {fonte} | {t} | {_pct(c['precisao'])} | "
                        f"{_pct(c['recall'])} | {_pct(c['falso_alarme'])} | "
                        f"{c['fp']} | {c['fn']} |"
                    )
    out += ["", "## Critérios de GO", ""]
    if not report["go"]:
        out.append("Sem Jev nesta execução: rode com `--jev` para decidir.")
    else:
        for arm, checks in report["go"].items():
            veredito = report["veredito"][arm]
            if veredito == "INCONCLUSIVO":
                out.append(
                    f"**{arm.upper()}: INCONCLUSIVO** ({report['jev'][arm]['respondidas']} "
                    f"de {report['frases']} frases respondidas; rode de novo)"
                )
            else:
                out.append(f"**{arm.upper()}: {veredito}**")
            for c in checks:
                detalhe = (
                    f"limiar {c['limiar']}, recall {_pct(c['recall'])}, "
                    f"falso alarme {_pct(c['falso_alarme'])}"
                    if c["ok"]
                    else "nenhum limiar atende"
                )
                out.append(f"- {'ok' if c['ok'] else 'falha'}: {c['criterio']} ({detalhe})")
    return "\n".join(out) + "\n"


def _metric_row(signal: str, c: dict[str, Any]) -> str:
    return (
        f"| {signal} | {_pct(c['precisao'])} | {_pct(c['recall'])} | "
        f"{_pct(c['falso_alarme'])} | {c['fp']} | {c['fn']} |"
    )


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.0f}%"


def _fmt_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(
    argv: list[str] | None = None,
    *,
    transport: httpx.BaseTransport | None = None,
    settings: TriageSettings | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--jev", action="store_true", help="chama o Jev (exige chave)")
    parser.add_argument("--arm", action="append", choices=ARMS, help="pt (padrão) e/ou en")
    parser.add_argument("--model", help="modelo; padrão TYPESAFE_MODEL. Fixe a versão para limiares")
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--out", type=Path, help="grava o relatório JSON neste caminho")
    args = parser.parse_args(argv)

    try:
        rows = load_corpus(args.corpus)
    except (CorpusError, OSError) as exc:
        print(f"Corpus inválido: {exc}", file=sys.stderr)
        return EXIT_USAGE

    jev_run: JevRun | None = None
    if args.jev:
        if args.corpus.resolve() != DEFAULT_CORPUS.resolve():
            print(
                f"--jev só envia o corpus sintético versionado ({DEFAULT_CORPUS.name}); "
                "inclua outras frases nele, por PR, antes de enviar.",
                file=sys.stderr,
            )
            return EXIT_USAGE
        settings = settings or TriageSettings()
        if not settings.typesafe_api_key.strip():
            print("--jev exige TYPESAFE_API_KEY no ambiente.", file=sys.stderr)
            return EXIT_USAGE
        reais = non_synthetic_ids(rows)
        if reais:
            print(
                "Frases alteradas pela redação de egresso (não parecem sintéticas): "
                + ", ".join(reais),
                file=sys.stderr,
            )
            return EXIT_USAGE
        jev_run = run_jev(
            rows,
            settings=settings,
            arms=list(dict.fromkeys(args.arm or ["pt"])),
            model=args.model or settings.typesafe_model,
            max_cost_usd=args.max_cost_usd,
            timeout=args.timeout,
            transport=transport,
        )

    report = build_report(rows, args.corpus, jev_run)
    print(render_markdown(report), end="")
    if args.out:
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if jev_run and jev_run.interrompido_por_custo:
        return EXIT_COST
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
