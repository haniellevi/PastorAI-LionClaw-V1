"""Avaliação offline J0 (`scripts/jev_eval.py`).

Sem rede: a API da TypeSafe é simulada por `httpx.MockTransport`. Os testes
cobrem o contrato do corpus, os guardas do modo `--jev` e as métricas; a
qualidade das regras em si fica para as fatias que corrigem B4, B5, B6 e B15.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.services.semantic_triage import INTENCOES, TriageSettings
from scripts import jev_eval


@pytest.fixture(autouse=True)
def _sem_env_typesafe(monkeypatch) -> None:
    for var in (
        "TYPESAFE_API_KEY",
        "TYPESAFE_API_URL",
        "TYPESAFE_MODEL",
        "JEV_SHADOW_TRIAGE_IGREJA_IDS",
    ):
        monkeypatch.delenv(var, raising=False)


def _settings(**overrides: object) -> TriageSettings:
    values: dict[str, object] = {"typesafe_api_key": "test-key"}
    values.update(overrides)
    return TriageSettings(_env_file=None, **values)  # type: ignore[call-arg]


def _row(
    row_id: str,
    texto: str,
    *,
    risco: bool = False,
    handoff: bool = False,
    optout: bool = False,
    aceite: bool | None = None,
    csim: bool = False,
    relatorio: bool = False,
    intencao: str | None = None,
    ministerial: bool = False,
    dificuldade: str = "direto",
) -> dict[str, Any]:
    return {
        "id": row_id,
        "texto": texto,
        "contexto": {"termo_pendente": aceite is not None, "ministerial": ministerial},
        "rotulo": {
            "risco": risco,
            "handoff": handoff,
            "optout": optout,
            "aceite": aceite,
            "intencao": intencao,
            "csim": csim,
            "relatorio": relatorio,
        },
        "dificuldade": dificuldade,
    }


def _write(tmp_path: Path, rows: list[dict[str, Any]]) -> Path:
    path = tmp_path / "corpus.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    return path


def _answer(
    *,
    risco: float = 0.01,
    optout: float = 0.01,
    aceite: float | None = None,
    intencao: str = "conversa_geral",
    probabilities: dict[str, float] | None = None,
    tokens: int = 100,
) -> dict[str, Any]:
    answers: dict[str, Any] = {
        "risco_pastoral": {"type": "noul", "noul": risco},
        "pede_optout": {"type": "noul", "noul": optout},
        "intencao": {
            "type": "choice",
            "choice": intencao,
            "confidence": 0.9,
            "probabilities": probabilities or {intencao: 0.9, "outro": 0.1},
        },
    }
    if aceite is not None:
        answers["aceita_termo"] = {"type": "noul", "noul": aceite}
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": tokens, "output_tokens": 5},
    }


class _FakeJev:
    """API simulada: responde pela mensagem enviada e conta as chamadas."""

    def __init__(self, by_text: dict[str, dict[str, Any]]) -> None:
        self.by_text = by_text
        self.calls: list[dict[str, Any]] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer test-key"
            body = json.loads(request.content)
            self.calls.append(body)
            return httpx.Response(200, json=self.by_text[body["state"]["mensagem"]])

        return httpx.MockTransport(handler)


def _no_calls() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nenhuma chamada deveria sair")

    return httpx.MockTransport(handler)


def _versionado(monkeypatch, path: Path) -> Path:
    """Faz o corpus de teste passar pela trava de corpus versionado do --jev."""
    monkeypatch.setattr(jev_eval, "DEFAULT_CORPUS", path)
    return path


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------
def test_corpus_do_repo_e_valido_sintetico_e_cobre_as_classes() -> None:
    rows = jev_eval.load_corpus(jev_eval.DEFAULT_CORPUS)

    assert jev_eval.non_synthetic_ids(rows) == []
    positivos = {
        s: sum(1 for r in rows if r.rotulo[s] is True) for s in jev_eval.SIGNALS
    }
    assert positivos["risco"] >= 40
    assert positivos["handoff"] >= 40
    assert positivos["optout"] >= 40
    assert positivos["aceite"] >= 15
    assert positivos["csim"] >= 10
    assert positivos["relatorio"] >= 10
    assert sum(1 for r in rows if r.dificuldade == "armadilha") >= 40
    assert {r.rotulo["intencao"] for r in rows} - {None} <= set(INTENCOES)


@pytest.mark.parametrize(
    "rows",
    [
        [_row("a", "oi"), _row("a", "olá")],
        [{**_row("a", "oi"), "contexto": {"termo_pendente": True, "ministerial": False}}],
        [_row("a", "oi", intencao="fofoca")],
        [{**_row("a", "oi"), "rotulo": {"risco": False}}],
        [{**_row("a", "oi"), "dificuldade": "facil"}],
    ],
    ids=["id-repetido", "aceite-sem-rotulo", "intencao-invalida", "rotulo-ausente", "dificuldade"],
)
def test_corpus_malformado_e_recusado(tmp_path: Path, rows, capsys) -> None:
    path = _write(tmp_path, rows)

    with pytest.raises(jev_eval.CorpusError):
        jev_eval.load_corpus(path)
    assert jev_eval.main(["--corpus", str(path)]) == jev_eval.EXIT_USAGE
    assert "Corpus inválido" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Modo regras (padrão)
# ---------------------------------------------------------------------------
def test_baseline_roda_sem_rede(monkeypatch, capsys) -> None:
    def _sem_rede(*args: object, **kwargs: object) -> None:
        raise AssertionError("o baseline não pode abrir cliente HTTP")

    monkeypatch.setattr(httpx.Client, "__init__", _sem_rede)

    assert jev_eval.main([]) == jev_eval.EXIT_OK
    out = capsys.readouterr().out
    assert "## Regras atuais" in out
    assert "rode com `--jev`" in out


def test_confusao_das_regras_por_sinal(tmp_path: Path, monkeypatch) -> None:
    rows = jev_eval.load_corpus(
        _write(
            tmp_path,
            [
                _row("tp", "a", optout=True),
                _row("fn", "b", optout=True),
                _row("fp", "c"),
                _row("tn", "d"),
            ],
        )
    )
    decide = {"a": True, "b": False, "c": True, "d": False}
    monkeypatch.setattr(
        jev_eval,
        "rules_predict",
        lambda row: {
            "risco": False,
            "handoff": False,
            "optout": decide[row.texto],
            "aceite": None,
            "csim": False,
            "relatorio": False,
        },
    )

    c = jev_eval.score_rules(rows)["optout"]

    assert (c.tp, c.fp, c.fn, c.tn) == (1, 1, 1, 1)
    assert c.fp_ids == ["fp"] and c.fn_ids == ["fn"]
    assert c.recall == 0.5 and c.precision == 0.5 and c.false_alarm == 0.5


# ---------------------------------------------------------------------------
# Modo --jev
# ---------------------------------------------------------------------------
def test_jev_sem_chave_sai_com_2_sem_chamar(capsys) -> None:
    rc = jev_eval.main(
        ["--jev"],
        transport=_no_calls(),
        settings=TriageSettings(_env_file=None),  # type: ignore[call-arg]
    )

    assert rc == jev_eval.EXIT_USAGE
    assert "TYPESAFE_API_KEY" in capsys.readouterr().err


def test_jev_so_envia_o_corpus_versionado(tmp_path: Path, capsys) -> None:
    # Nome, endereço e relato passam intactos pela redação de egresso: só o
    # corpus revisado no git pode sair, nunca um arquivo qualquer.
    path = _write(
        tmp_path, [_row("real", "Sou a Maria, moro na rua das Flores e estou doente")]
    )

    rc = jev_eval.main(
        ["--jev", "--corpus", str(path)], transport=_no_calls(), settings=_settings()
    )

    assert rc == jev_eval.EXIT_USAGE
    assert "corpus sintético versionado" in capsys.readouterr().err


def test_jev_recusa_frase_que_parece_dado_real(tmp_path: Path, monkeypatch, capsys) -> None:
    path = _versionado(
        monkeypatch, _write(tmp_path, [_row("real", "Me liga no (11) 99999-8888")])
    )

    rc = jev_eval.main(
        ["--jev", "--corpus", str(path)], transport=_no_calls(), settings=_settings()
    )

    assert rc == jev_eval.EXIT_USAGE
    assert "real" in capsys.readouterr().err


def _mini_corpus(tmp_path: Path) -> Path:
    return _write(
        tmp_path,
        [
            _row("crise", "Não aguento mais, quero sumir pra sempre", risco=True, handoff=True),
            _row("luto", "Minha avó faleceu, orem por nós", intencao="pedido_oracao"),
            _row("sai", "Me tira da lista", optout=True),
            _row("ressalva", "sim, mas não autorizo", aceite=False),
            _row("aceite", "Aceito", aceite=True),
        ],
    )


def _mini_jev() -> _FakeJev:
    return _FakeJev(
        {
            "Não aguento mais, quero sumir pra sempre": _answer(risco=0.97, tokens=120),
            "Minha avó faleceu, orem por nós": _answer(
                risco=0.04, intencao="pedido_oracao", tokens=110
            ),
            "Me tira da lista": _answer(optout=0.93, tokens=100),
            "sim, mas não autorizo": _answer(aceite=0.02, tokens=150),
            "Aceito": _answer(aceite=0.98, tokens=140),
        }
    )


def test_handoff_e_proxy_local_sem_score_do_provedor(tmp_path: Path) -> None:
    rows = jev_eval.load_corpus(
        _write(
            tmp_path,
            [
                _row("humano", "GOSTARIA DE FALAR COM ALGUÉM", handoff=True),
                _row("negado", "não quero um humano"),
            ],
        )
    )
    assert jev_eval.SIGNALS == ("risco", "handoff", "optout", "aceite", "csim", "relatorio")
    assert jev_eval.rules_predict(rows[0])["risco"] is True
    assert jev_eval.rules_predict(rows[0])["handoff"] is True
    assert jev_eval.rules_predict(rows[1])["handoff"] is False
    metrics = jev_eval.score_rules(rows)
    assert (metrics["handoff"].tp, metrics["handoff"].tn) == (1, 1)


def test_metricas_exatas_com_api_simulada(tmp_path: Path, monkeypatch) -> None:
    fake = _mini_jev()
    out = tmp_path / "relatorio.json"

    rc = jev_eval.main(
        ["--jev", "--corpus", str(_versionado(monkeypatch, _mini_corpus(tmp_path))), "--out", str(out)],
        transport=fake.transport(),
        settings=_settings(),
    )

    assert rc == jev_eval.EXIT_OK
    assert len(fake.calls) == 5
    report = json.loads(out.read_text(encoding="utf-8"))
    pt = report["jev"]["pt"]
    assert "handoff" in report["regras"]
    assert report["sinais_nao_mensurados_jev"] == ["handoff"]
    assert "handoff" not in pt["sozinho"]
    assert "handoff" not in pt["politica"]
    assert "Handoff no Jev: N/A" in jev_eval.render_markdown(report)
    assert pt["respondidas"] == 5 and pt["erros"] == {}
    assert pt["modelos"] == ["jev-1.13.0"]
    assert pt["tokens_in"] == 620
    assert report["custo"]["usd"] == pytest.approx(620 * 0.042 / 1_000_000, abs=1e-6)

    risco = pt["sozinho"]["risco"]["0.50"]
    assert (risco["tp"], risco["fp"], risco["fn"], risco["tn"]) == (1, 0, 0, 4)
    # A regex não pega "Me tira da lista"; a política (regra OU Jev) pega.
    assert report["regras"]["optout"]["fn_ids"] == ["sai"]
    assert pt["politica"]["optout"]["0.50"]["fn"] == 0
    # B4: a regra já veta a ressalva; a política com Jev preserva o veto.
    assert report["regras"]["aceite"]["fp_ids"] == []
    assert report["regras"]["aceite"]["tp"] == 1
    aceite = pt["politica"]["aceite"]["0.50"]
    assert (aceite["tp"], aceite["fp"]) == (1, 0)
    assert pt["intencao"] == {"avaliadas": 1, "acuracia": 1.0, "trocas": {}}

    assert pt["completo"] is True
    assert report["veredito"] == {"pt": "GO"}
    go = {c["criterio"].split(":")[0]: c for c in report["go"]["pt"]}
    assert go["crise"]["ok"] and go["crise"]["limiar"] == 0.95
    assert go["opt-out"]["ok"] and go["opt-out"]["limiar"] == 0.5
    assert go["aceite"]["ok"] and go["aceite"]["limiar"] == 0.5


def test_relatorio_nunca_traz_o_texto_das_frases(tmp_path: Path, monkeypatch, capsys) -> None:
    out = tmp_path / "relatorio.json"

    jev_eval.main(
        ["--jev", "--corpus", str(_versionado(monkeypatch, _mini_corpus(tmp_path))), "--out", str(out)],
        transport=_mini_jev().transport(),
        settings=_settings(),
    )

    dumped = out.read_text(encoding="utf-8") + capsys.readouterr().out
    for texto in _mini_jev().by_text:
        assert texto not in dumped


def test_teto_de_custo_interrompe_com_relatorio_parcial(tmp_path: Path, monkeypatch) -> None:
    caro = _FakeJev(
        {
            texto: {**resposta, "usage": {"input_tokens": 2_000_000, "output_tokens": 5}}
            for texto, resposta in _mini_jev().by_text.items()
        }
    )
    out = tmp_path / "relatorio.json"

    rc = jev_eval.main(
        ["--jev", "--corpus", str(_versionado(monkeypatch, _mini_corpus(tmp_path))), "--out", str(out)],
        transport=caro.transport(),
        settings=_settings(),
    )

    assert rc == jev_eval.EXIT_COST
    assert len(caro.calls) == 1
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["custo"]["interrompido_por_custo"]
    assert report["veredito"] == {"pt": "INCONCLUSIVO"}


def test_falha_da_api_conta_erro_sem_derrubar(tmp_path: Path, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    out = tmp_path / "relatorio.json"
    rc = jev_eval.main(
        ["--jev", "--corpus", str(_versionado(monkeypatch, _mini_corpus(tmp_path))), "--out", str(out)],
        transport=httpx.MockTransport(handler),
        settings=_settings(),
    )

    assert rc == jev_eval.EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    pt = report["jev"]["pt"]
    assert pt["respondidas"] == 0
    assert pt["erros"] == {"HTTPStatusError": 5}
    assert report["veredito"] == {"pt": "INCONCLUSIVO"}


def test_falha_parcial_nao_decide_o_go(tmp_path: Path, monkeypatch, capsys) -> None:
    by_text = _mini_jev().by_text

    def handler(request: httpx.Request) -> httpx.Response:
        mensagem = json.loads(request.content)["state"]["mensagem"]
        if mensagem == "Minha avó faleceu, orem por nós":
            return httpx.Response(503)
        return httpx.Response(200, json=by_text[mensagem])

    out = tmp_path / "relatorio.json"
    rc = jev_eval.main(
        ["--jev", "--corpus", str(_versionado(monkeypatch, _mini_corpus(tmp_path))), "--out", str(out)],
        transport=httpx.MockTransport(handler),
        settings=_settings(),
    )

    assert rc == jev_eval.EXIT_OK
    report = json.loads(out.read_text(encoding="utf-8"))
    # As 4 respostas que chegaram atendem a todos os critérios, mas um
    # subconjunto não decide o J0.
    assert all(c["ok"] for c in report["go"]["pt"])
    assert report["jev"]["pt"]["completo"] is False
    assert report["veredito"] == {"pt": "INCONCLUSIVO"}
    assert "PT: INCONCLUSIVO" in capsys.readouterr().out


def test_braco_en_troca_so_as_perguntas(tmp_path: Path) -> None:
    row = jev_eval.load_corpus(
        _write(tmp_path, [_row("a", "sim, mas não autorizo", aceite=False)])
    )[0]

    pt = jev_eval.build_payload(row, model="jev-latest", arm="pt")
    en = jev_eval.build_payload(row, model="jev-latest", arm="en")

    assert en["state"] == pt["state"]
    assert en["questions"].keys() == pt["questions"].keys()
    assert set(en["questions"]["intencao"]["criteria"]) == set(INTENCOES)
    for qid in pt["questions"]:
        assert en["questions"][qid]["type"] == pt["questions"][qid]["type"]
        assert en["questions"][qid]["instructions"] != pt["questions"][qid]["instructions"]


def test_dois_bracos_usam_as_mesmas_frases(tmp_path: Path, monkeypatch) -> None:
    fake = _mini_jev()
    out = tmp_path / "relatorio.json"

    jev_eval.main(
        [
            "--jev",
            "--arm",
            "pt",
            "--arm",
            "en",
            "--corpus",
            str(_versionado(monkeypatch, _mini_corpus(tmp_path))),
            "--out",
            str(out),
        ],
        transport=fake.transport(),
        settings=_settings(),
    )

    assert len(fake.calls) == 10
    report = json.loads(out.read_text(encoding="utf-8"))
    assert set(report["jev"]) == {"pt", "en"}
    assert set(report["go"]) == {"pt", "en"}
