#!/usr/bin/env python3
"""Gera o painel de acompanhamento do plano de refatoração.

Lê tarefas.json (registro versionado) e github.json (última leitura do GitHub),
valida o registro e escreve dados.js, que painel.html carrega. Só biblioteca padrão.

    python3 docs/ops/acompanhamento/atualizar.py              lê o GitHub e regenera
    python3 docs/ops/acompanhamento/atualizar.py --sem-github  regenera sem consultar
    python3 docs/ops/acompanhamento/atualizar.py --verificar   só valida o registro

Consultas ao GitHub são somente leitura (gh pr view, gh api GET, gh run list) e
usam a autenticação local do gh. Nenhum token é lido, gravado ou enviado ao
navegador. Se uma consulta falhar, a última evidência fica no github.json,
marcada como desatualizada.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AQUI = Path(__file__).resolve().parent
TAREFAS = AQUI / "tarefas.json"
GITHUB = AQUI / "github.json"
DADOS = AQUI / "dados.js"

ESTADOS = {
    "futura": "Futura",
    "pronta": "Pronta",
    "em_andamento": "Em andamento",
    "em_validacao": "Em validação",
    "bloqueada": "Bloqueada",
    "concluida": "Concluída",
}
STATUS_INDICADOR = {"nao_iniciado", "em_andamento", "parcial", "ok", "pendente", "falhou", "nao_aplicavel", "desconhecido"}
INDICADORES = ["implementacao", "validacao_local", "ci", "integracao_main", "publicacao_dev", "publicacao_prod"]
TRILHAS = {"principal", "paralela", "backlog"}
FALHAS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}


def agora() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ler_json(caminho: Path, padrao):
    if not caminho.exists():
        return padrao
    with caminho.open(encoding="utf-8") as f:
        return json.load(f)


# --------------------------------------------------------------------------- validação


def validar(reg: dict) -> tuple[list[str], list[str]]:
    erros: list[str] = []
    avisos: list[str] = []
    fases = {f["id"]: f for f in reg.get("fases", [])}
    tarefas = reg.get("tarefas", [])
    ids = [t.get("id") for t in tarefas]
    if len(ids) != len(set(ids)):
        erros.append("ids de tarefas duplicados")
    por_id = {t["id"]: t for t in tarefas if "id" in t}
    sequencias: list[int] = []
    for t in tarefas:
        i = t.get("id", "?")
        for campo in ("titulo", "fase", "trilha", "estado", "objetivo", "criterio_aceite", "depende_de", "proxima_acao", "indicadores", "evidencias"):
            if campo not in t:
                erros.append(f"{i}: campo ausente: {campo}")
        if t.get("estado") not in ESTADOS:
            erros.append(f"{i}: estado inválido: {t.get('estado')}")
        if t.get("fase") not in fases:
            erros.append(f"{i}: fase inexistente: {t.get('fase')}")
        if t.get("trilha") not in TRILHAS:
            erros.append(f"{i}: trilha inválida: {t.get('trilha')}")
        elif t.get("fase") in fases and fases[t["fase"]]["trilha"] != t["trilha"]:
            erros.append(f"{i}: trilha {t['trilha']} difere da trilha da fase {t['fase']}")
        if t.get("trilha") == "principal":
            if not isinstance(t.get("sequencia"), int):
                erros.append(f"{i}: tarefa da sequência principal sem 'sequencia'")
            else:
                sequencias.append(t["sequencia"])
        for dep in t.get("depende_de", []) + t.get("integra_apos", []):
            if dep not in por_id:
                erros.append(f"{i}: dependência inexistente: {dep}")
        ind = t.get("indicadores", {})
        for nome in INDICADORES:
            if nome == "ci":
                continue  # pode ser derivado do GitHub
            if nome not in ind:
                erros.append(f"{i}: indicador ausente: {nome}")
        for nome, v in ind.items():
            if nome not in INDICADORES:
                erros.append(f"{i}: indicador desconhecido: {nome}")
            elif v.get("status") not in STATUS_INDICADOR:
                erros.append(f"{i}: status de indicador inválido em {nome}: {v.get('status')}")
        for ev in t.get("evidencias", []):
            if not ev.get("descricao") or not ev.get("data") or not ev.get("tipo"):
                erros.append(f"{i}: evidência sem data, tipo ou descrição")
        estado = t.get("estado")
        if estado == "bloqueada" and not t.get("bloqueio"):
            erros.append(f"{i}: tarefa bloqueada sem texto em 'bloqueio'")
        if estado != "concluida" and not t.get("proxima_acao"):
            erros.append(f"{i}: tarefa aberta sem 'proxima_acao'")
        if estado == "concluida":
            if not t.get("evidencias"):
                erros.append(f"{i}: concluída sem evidências")
            abertos = [d for d in t.get("depende_de", []) if por_id.get(d, {}).get("estado") != "concluida"]
            if abertos:
                erros.append(f"{i}: concluída com dependência aberta: {', '.join(abertos)}")
            for nome in ("integracao_main",):
                if ind.get(nome, {}).get("status") not in ("ok", "nao_aplicavel"):
                    erros.append(f"{i}: concluída sem integração na main comprovada")
        if estado == "pronta":
            abertos = [d for d in t.get("depende_de", []) if por_id.get(d, {}).get("estado") != "concluida"]
            if abertos:
                erros.append(f"{i}: marcada como pronta com dependência aberta: {', '.join(abertos)}")
        if estado == "futura" and t.get("depende_de") and all(por_id.get(d, {}).get("estado") == "concluida" for d in t["depende_de"]):
            avisos.append(f"{i}: todas as dependências concluídas; considere marcar como pronta")
        # indicadores que afirmam publicação precisam de evidência própria
        for nome in ("publicacao_dev", "publicacao_prod"):
            if ind.get(nome, {}).get("status") == "ok" and not any(e.get("tipo") == nome for e in t.get("evidencias", [])):
                erros.append(f"{i}: {nome} 'ok' exige evidência com tipo '{nome}'")
    if len(sequencias) != len(set(sequencias)):
        erros.append("sequência principal com números repetidos")
    # ciclos
    visitado: dict[str, int] = {}

    def visita(n: str, pilha: list[str]) -> None:
        if visitado.get(n) == 2:
            return
        if visitado.get(n) == 1:
            erros.append("ciclo de dependências: " + " → ".join(pilha + [n]))
            return
        visitado[n] = 1
        for d in por_id.get(n, {}).get("depende_de", []):
            if d in por_id:
                visita(d, pilha + [n])
        visitado[n] = 2

    for n in por_id:
        visita(n, [])
    for h in reg.get("historico", []):
        if h.get("tarefa") not in por_id:
            erros.append(f"histórico aponta para tarefa inexistente: {h.get('tarefa')}")
    return erros, avisos


# --------------------------------------------------------------------------- GitHub (somente leitura)


def gh(args: list[str], timeout: int = 40) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        linha = (r.stderr or r.stdout or "falha sem mensagem").strip().splitlines()[0]
        raise RuntimeError(linha[:200])
    return r.stdout


def reduzir_checks(rollup: list[dict]) -> list[dict]:
    saida = []
    for c in rollup or []:
        nome = c.get("name") or c.get("context")
        if not nome:
            continue
        saida.append(
            {
                "nome": nome,
                "status": c.get("status") or c.get("state"),
                "conclusao": c.get("conclusion"),
                "url": c.get("detailsUrl") or c.get("targetUrl"),
            }
        )
    return saida


def ler_pr(repo: str, numero: int) -> dict:
    campos = "number,title,url,state,isDraft,createdAt,updatedAt,mergedAt,headRefName,baseRefName,headRefOid,baseRefOid,mergeable,reviewDecision,statusCheckRollup"
    d = json.loads(gh(["pr", "view", str(numero), "--repo", repo, "--json", campos]))
    return {
        "numero": d["number"],
        "titulo": d["title"],
        "url": d["url"],
        "estado": d["state"],
        "rascunho": d["isDraft"],
        "criado_em": d["createdAt"],
        "atualizado_em": d["updatedAt"],
        "integrado_em": d.get("mergedAt"),
        "branch": d["headRefName"],
        "base": d["baseRefName"],
        "sha": d["headRefOid"],
        "sha_base": d["baseRefOid"],
        "mergeavel": d.get("mergeable"),
        "revisao": d.get("reviewDecision"),
        "checks": reduzir_checks(d.get("statusCheckRollup")),
    }


def ler_main(repo: str) -> dict:
    d = json.loads(gh(["api", f"repos/{repo}/commits/main", "--jq", "{sha:.sha,data:.commit.committer.date,mensagem:(.commit.message|split(\"\\n\")|.[0]),url:.html_url}"]))
    return d


def ler_monitor(repo: str, cfg: dict) -> dict:
    campos = "databaseId,conclusion,status,createdAt,headSha,event,url"
    runs = json.loads(gh(["run", "list", "--repo", repo, "--workflow", cfg["workflow"], "--limit", str(cfg.get("limite", 20)), "--json", campos]))
    falhas = 0
    desde = None
    for r in runs:
        if r.get("conclusion") == "failure":
            falhas += 1
            desde = r["createdAt"]
        else:
            break
    return {
        "workflow": cfg["workflow"],
        "descricao": cfg.get("descricao", cfg["id"]),
        "consultadas": len(runs),
        "falhas_consecutivas": falhas,
        "falhas_desde": desde,
        "todas_falharam": bool(runs) and falhas == len(runs),
        "ultimas": [
            {"id": r["databaseId"], "conclusao": r.get("conclusion"), "status": r.get("status"), "criado_em": r["createdAt"], "sha": r["headSha"], "evento": r["event"], "url": r["url"]}
            for r in runs[: cfg.get("exibir", 5)]
        ],
    }


def envelope(antigo: dict | None, leitor, *args) -> dict:
    """Executa a leitura; em falha, preserva a última evidência e marca desatualizada."""
    tentativa = agora()
    try:
        dados = leitor(*args)
        return {"ok": True, "consultado_em": tentativa, "tentativa_em": tentativa, "erro": None, "dados": dados}
    except Exception as e:  # noqa: BLE001 - qualquer falha preserva a evidência anterior
        antigo = antigo or {}
        return {
            "ok": False,
            "consultado_em": antigo.get("consultado_em"),
            "tentativa_em": tentativa,
            "erro": str(e)[:200],
            "dados": antigo.get("dados"),
        }


def consultar_github(reg: dict, anterior: dict) -> dict:
    repo = reg["repositorio"]
    prs_alvo = sorted({n for t in reg["tarefas"] for n in t.get("pr", [])} | {h["pr"] for h in reg.get("historico", []) if h.get("pr")})
    saida = {"repositorio": repo, "tentativa_em": agora(), "prs": {}, "main": None, "monitores": {}}
    try:
        gh(["--version"])
    except Exception as e:  # noqa: BLE001
        print(f"aviso: gh indisponível ({e}); mantendo a última leitura", file=sys.stderr)
        anterior = json.loads(json.dumps(anterior))
        anterior["tentativa_em"] = saida["tentativa_em"]
        anterior["aviso"] = (
            "gh indisponível; leitura anterior preservada"
            if anterior.get("prs") or anterior.get("main")
            else "gh indisponível e sem leitura anterior neste checkout: CI, integração na main e monitor aparecem como desconhecidos"
        )
        envs = list(anterior.get("prs", {}).values()) + list(anterior.get("monitores", {}).values()) + ([anterior["main"]] if anterior.get("main") else [])
        for env in envs:
            env["ok"] = False
            env["tentativa_em"] = saida["tentativa_em"]
            env["erro"] = f"gh indisponível: {str(e)[:150]}"
        return anterior
    for n in prs_alvo:
        saida["prs"][str(n)] = envelope(anterior.get("prs", {}).get(str(n)), ler_pr, repo, n)
    saida["main"] = envelope(anterior.get("main"), ler_main, repo)
    for cfg in reg.get("fontes_github", {}).get("monitores", []):
        saida["monitores"][cfg["id"]] = envelope(anterior.get("monitores", {}).get(cfg["id"]), ler_monitor, repo, cfg)
    return saida


# --------------------------------------------------------------------------- derivação


def indicador_ci(pr_env: dict | None, obrigatorios: list[str]) -> dict | None:
    if not pr_env or not pr_env.get("dados"):
        return None
    dados = pr_env["dados"]
    por_nome = {c["nome"]: c for c in dados["checks"]}
    estados = []
    for nome in obrigatorios:
        c = por_nome.get(nome)
        if c is None:
            estados.append((nome, "ausente"))
        elif c["conclusao"] in FALHAS:
            estados.append((nome, "falhou"))
        elif c["conclusao"] == "SUCCESS":
            estados.append((nome, "ok"))
        elif c["status"] in ("IN_PROGRESS", "QUEUED", "PENDING", "WAITING"):
            estados.append((nome, "em_andamento"))
        else:
            estados.append((nome, "pendente"))
    falhos = [n for n, s in estados if s == "falhou"]
    ok = [n for n, s in estados if s == "ok"]
    desat = " (leitura desatualizada)" if not pr_env.get("ok") else ""
    if falhos:
        status = "falhou"
        nota = f"Reprovados: {', '.join(falhos)}. Aprovados: {len(ok)} de {len(obrigatorios)} checks obrigatórios."
    elif len(ok) == len(obrigatorios):
        status = "ok"
        nota = f"{len(ok)} de {len(obrigatorios)} checks obrigatórios aprovados."
    elif any(s == "em_andamento" for _, s in estados):
        status = "em_andamento"
        nota = f"Em execução. Aprovados: {len(ok)} de {len(obrigatorios)}."
    else:
        status = "pendente"
        nota = f"Aprovados: {len(ok)} de {len(obrigatorios)}; sem resultado dos demais."
    return {"status": status, "nota": nota + desat, "origem": "github", "consultado_em": pr_env.get("consultado_em")}


def indicador_main(pr_env: dict | None) -> dict | None:
    if not pr_env or not pr_env.get("dados"):
        return None
    d = pr_env["dados"]
    desat = " (leitura desatualizada)" if not pr_env.get("ok") else ""
    if d["estado"] == "MERGED":
        if d.get("base") != "main":
            return {"status": "pendente", "nota": "Merge em base temporária ou desconhecida; integração na main precisa de prova própria." + desat, "origem": "github", "consultado_em": pr_env.get("consultado_em")}
        return {"status": "ok", "nota": "PR integrado na main." + desat, "origem": "github", "consultado_em": pr_env.get("consultado_em")}
    if d["estado"] == "CLOSED":
        return {"status": "falhou", "nota": "PR fechado sem integração." + desat, "origem": "github", "consultado_em": pr_env.get("consultado_em")}
    return {"status": "pendente", "nota": "PR aberto, não integrado." + desat, "origem": "github", "consultado_em": pr_env.get("consultado_em")}


def derivar(reg: dict, gh_dados: dict) -> dict:
    tarefas = reg["tarefas"]
    por_id = {t["id"]: t for t in tarefas}
    obrig = reg["checks_obrigatorios"]
    for t in tarefas:
        ind = dict(t["indicadores"])
        pr_env = gh_dados.get("prs", {}).get(str(t["pr_referencia"])) if t.get("pr_referencia") else None
        d_ci = indicador_ci(pr_env, obrig)
        d_main = indicador_main(pr_env)
        if d_ci:
            ind["ci"] = d_ci
        else:
            if t.get("pr_referencia"):
                ind["ci"] = {"status": "desconhecido", "nota": "Sem leitura do GitHub para o PR de referência."}
            elif ind["integracao_main"]["status"] == "nao_aplicavel":
                ind.setdefault("ci", {"status": "nao_aplicavel", "nota": "Sem integração na main, sem CI."})
            else:
                ind.setdefault("ci", {"status": "nao_iniciado", "nota": "Sem PR de referência ainda."})
        if d_main:
            ind["integracao_main"] = d_main
        t["indicadores"] = ind
        t["prs"] = [
            {"numero": n, "url": f"https://github.com/{reg['repositorio']}/pull/{n}", "github": gh_dados.get("prs", {}).get(str(n))}
            for n in t.get("pr", [])
        ]
        abertas = [d for d in t.get("depende_de", []) if por_id[d]["estado"] != "concluida"]
        t["dependencias_abertas"] = abertas
        t["executavel"] = t["estado"] == "pronta" and not abertas
        # situação (rótulo textual, além da cor)
        estado = t["estado"]
        if estado == "concluida":
            sit = "Concluída"
        elif estado == "em_validacao" and ind["ci"]["status"] == "ok" and ind["integracao_main"]["status"] == "pendente":
            sit = "Validado — aguardando integração"
        elif estado == "em_validacao" and ind["ci"]["status"] == "falhou":
            sit = "Em validação — CI reprovado"
        else:
            sit = ESTADOS[estado]
        t["situacao"] = sit
        t["estado_rotulo"] = ESTADOS[estado]

    principal = sorted([t for t in tarefas if t["trilha"] == "principal"], key=lambda t: t["sequencia"])
    abertas_p = [t for t in principal if t["estado"] != "concluida"]
    etapa = None
    if abertas_p:
        primeira = abertas_p[0]
        fase = next(f for f in reg["fases"] if f["id"] == primeira["fase"])
        etapa = {"fase": fase["id"], "nome": fase["nome"], "tarefa": primeira["id"], "situacao": primeira["situacao"]}
    proxima = next((t["id"] for t in principal if t["executavel"]), None)
    tambem = [t["id"] for t in tarefas if t["executavel"] and t["id"] != proxima]
    contagem = {k: 0 for k in ESTADOS}
    for t in tarefas:
        contagem[t["estado"]] += 1

    def proporcao(lista):
        total = len(lista)
        feitas = sum(1 for t in lista if t["estado"] == "concluida")
        return {"concluidas": feitas, "total": total, "texto": f"{feitas} de {total} tarefas concluídas"}

    resumo = {
        "etapa_atual": etapa,
        "proxima_executavel": proxima,
        "tambem_prontas": tambem,
        "em_curso": [t["id"] for t in tarefas if t["estado"] in ("em_andamento", "em_validacao")],
        "bloqueios": [{"id": t["id"], "titulo": t["titulo"], "motivo": t["bloqueio"]} for t in tarefas if t["estado"] == "bloqueada"],
        "esperas": [{"id": t["id"], "titulo": t["titulo"], "motivo": t["aguardando"]} for t in tarefas if t.get("aguardando") and t["estado"] != "concluida"],
        "contagem": contagem,
        "proporcao": {
            "geral": proporcao(tarefas),
            "principal": proporcao(principal),
            "paralela": proporcao([t for t in tarefas if t["trilha"] == "paralela"]),
            "backlog": proporcao([t for t in tarefas if t["trilha"] == "backlog"]),
            "formula": "tarefas em estado Concluída ÷ tarefas cadastradas. É contagem de itens, não medida de esforço nem de prazo.",
        },
    }
    return resumo


def git_info() -> dict:
    def g(*a):
        try:
            return subprocess.run(["git", *a], capture_output=True, text=True, cwd=AQUI, timeout=10).stdout.strip() or None
        except Exception:  # noqa: BLE001
            return None

    return {"branch": g("rev-parse", "--abbrev-ref", "HEAD"), "sha": g("rev-parse", "--short=8", "HEAD")}


# --------------------------------------------------------------------------- principal


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sem-github", action="store_true", help="não consulta o GitHub; usa github.json se existir (arquivo local, não versionado)")
    ap.add_argument("--verificar", action="store_true", help="só valida tarefas.json (não escreve nada)")
    args = ap.parse_args()

    reg = ler_json(TAREFAS, None)
    if reg is None:
        print("erro: tarefas.json ausente", file=sys.stderr)
        return 1
    erros, avisos = validar(reg)
    for a in avisos:
        print(f"aviso: {a}", file=sys.stderr)
    if erros:
        for e in erros:
            print(f"erro: {e}", file=sys.stderr)
        print(f"{len(erros)} erro(s) em tarefas.json; nada foi gerado.", file=sys.stderr)
        return 1
    if args.verificar:
        print(f"tarefas.json válido: {len(reg['tarefas'])} tarefas, {len(reg['fases'])} fases, {len(avisos)} aviso(s).")
        return 0

    anterior = ler_json(GITHUB, {})
    if args.sem_github:
        gh_dados = anterior or {
            "repositorio": reg["repositorio"], "prs": {}, "main": None, "monitores": {},
            "aviso": "Sem leitura do GitHub neste checkout (github.json ausente): CI, integração na main e monitor aparecem como desconhecidos. Rode ./acompanhar.sh com o gh autenticado.",
        }
    else:
        gh_dados = consultar_github(reg, anterior)
        GITHUB.write_text(json.dumps(gh_dados, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    resumo = derivar(reg, gh_dados)
    saida = {
        "gerado_em": agora(),
        "git": git_info(),
        "repositorio": reg["repositorio"],
        "plano": reg["plano"],
        "checks_obrigatorios": reg["checks_obrigatorios"],
        "estados": ESTADOS,
        "indicadores": INDICADORES,
        "fases": reg["fases"],
        "tarefas": reg["tarefas"],
        "historico": reg.get("historico", []),
        "github": gh_dados,
        "resumo": resumo,
    }
    DADOS.write_text("window.PAINEL_DADOS = " + json.dumps(saida, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")

    falhas = [k for k, v in {**gh_dados.get("prs", {}), "main": gh_dados.get("main") or {}}.items() if isinstance(v, dict) and v.get("ok") is False]
    print(f"painel atualizado: {DADOS}")
    print(f"tarefas: {resumo['proporcao']['geral']['texto']} (contagem de itens, não de esforço)")
    if falhas:
        print(f"aviso: leitura do GitHub falhou para {', '.join(falhas)}; evidência anterior preservada e marcada como desatualizada.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
