#!/usr/bin/env python3
"""Gera o painel local derivado do ROADMAP.md.

Lê somente ROADMAP.md e os dois runbooks sanitizados de LOCAL_DOCS, nada mais.
Escreve somente em output/painel/: index.html (visualização), release.html (seção
atual do runbook do lote), ROADMAP.md e as
cópias desses runbooks em docs/ops/, para que os links locais funcionem mesmo
antes do commit. Não serve o repositório inteiro. O painel não é plano paralelo, não calcula percentual global e não
consulta produção; estados, coluna de produção e evidências datadas são os
registrados no roteiro.

Uso (Python 3.13, só biblioteca padrão):
    python3 tools/render_progress.py
    python3 -m http.server 8777 --bind 127.0.0.1 --directory output/painel
"""

from __future__ import annotations

import html
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "ROADMAP.md"
OUT_DIR = ROOT / "output" / "painel"
REPO_URL = "https://github.com/haniellevi/PastorAI-LionClaw-V1"
# Allowlist fixa: únicos arquivos além do ROADMAP lidos e copiados ao painel.
LOCAL_DOCS = (
    "docs/ops/RELEASE-LOTE-2026-10.md",
    "docs/ops/ACEITE-PASTORAL-PILOTO.md",
)
RELEASE_DOC = LOCAL_DOCS[0]
RELEASE_START = "## Plano e prévia atual"
RELEASE_END = "\n## Estado e gates"

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
# Só no início da linha, para não confundir números dentro de parágrafos.
ORDERED_RE = re.compile(r"^(\d{1,3})[.)]\s+(.*)$")
SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
INLINE_RE = re.compile(r"`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|\*\*(.+?)\*\*")
SHA_RE = re.compile(r"sobre a `main` `([0-9a-f]{7,40})`")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

# Ícone e texto acompanham a cor, para o estado não depender só dela.
STATUS_ICON = {"feito": "✓", "andamento": "◐", "falta": "○"}


def now_sao_paulo() -> datetime:
    try:
        return datetime.now(ZoneInfo("America/Sao_Paulo"))
    except ZoneInfoNotFoundError:
        # Sem base de fusos no sistema; Brasil sem horário de verão desde 2019.
        return datetime.now(timezone(timedelta(hours=-3)))


def esc(text: str) -> str:
    return html.escape(text, quote=True)


def resolve_href(url: str, sha: str) -> str | None:
    """Links externos ficam; relativos vão ao GitHub na base, exceto o ROADMAP
    e os runbooks de LOCAL_DOCS, que apontam para as cópias locais."""
    if url.startswith(("https://", "http://", "#")):
        return url
    if SCHEME_RE.match(url) or url.startswith("//"):
        return None
    path = url.removeprefix("./").lstrip("/")
    target = path.split("#", 1)[0]
    if target == "ROADMAP.md" or target in LOCAL_DOCS:
        return path
    return f"{REPO_URL}/blob/{sha}/{path}"


def inline(text: str, sha: str) -> str:
    out = []
    pos = 0
    for match in INLINE_RE.finditer(text):
        out.append(esc(text[pos:match.start()]))
        code, label, url, bold = match.groups()
        if code is not None:
            out.append(f"<code>{esc(code)}</code>")
        elif label is not None:
            href = resolve_href(url, sha)
            inner = inline(label, sha)
            if href is None:
                out.append(inner)
            else:
                rel = ' rel="noopener noreferrer"' if href.startswith("http") else ""
                out.append(f'<a href="{esc(href)}"{rel}>{inner}</a>')
        else:
            out.append(f"<strong>{inline(bold, sha)}</strong>")
        pos = match.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def slugify(text: str, used: set[str]) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "secao"
    slug, n = base, 2
    while slug in used:
        slug, n = f"{base}-{n}", n + 1
    used.add(slug)
    return slug


def classify(estado: str) -> str:
    value = estado.strip().lower()
    if value.startswith("feito"):
        return "feito"
    if value.startswith("em andamento"):
        return "andamento"
    # "falta" e qualquer estado não reconhecido contam como pendentes.
    return "falta"


def is_break(line: str) -> bool:
    return (
        not line.strip()
        or HEADING_RE.match(line) is not None
        or line.lstrip().startswith("|")
        or BULLET_RE.match(line) is not None
        or ORDERED_RE.match(line) is not None
        or line.startswith("```")
    )


def parse_blocks(lines: list[str]) -> list[tuple]:
    blocks: list[tuple] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()
        if not line.strip():
            i += 1
        elif line.startswith("```"):
            buf = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                buf.append(lines[i].rstrip())
                i += 1
            blocks.append(("code", "\n".join(buf)))
            i += 1
        elif match := HEADING_RE.match(line):
            blocks.append(("heading", len(match.group(1)), match.group(2).strip()))
            i += 1
        elif line.lstrip().startswith("|"):
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            blocks.append(("table", rows))
        elif BULLET_RE.match(line) or ORDERED_RE.match(line):
            ordered = BULLET_RE.match(line) is None
            item_re = ORDERED_RE if ordered else BULLET_RE
            start = int(ORDERED_RE.match(line).group(1)) if ordered else 1
            items: list[str] = []
            while i < n:
                cur = lines[i].rstrip()
                if item := item_re.match(cur):
                    items.append(item.group(item_re.groups).strip())
                elif cur.startswith((" ", "\t")) and cur.strip() and items:
                    items[-1] += " " + cur.strip()
                else:
                    break
                i += 1
            blocks.append(("list", items, ordered, start))
        else:
            buf = [line.strip()]
            i += 1
            while i < n and not is_break(lines[i].rstrip()):
                buf.append(lines[i].strip())
                i += 1
            blocks.append(("para", " ".join(buf)))
    return blocks


def split_row(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", row)]


def render_table(rows: list[str], sha: str, title_level: int, stats: dict[str, int]) -> str:
    header = split_row(rows[0])
    body = rows[2:] if len(rows) > 1 and SEPARATOR_RE.match(rows[1]) else rows[1:]
    lowered = [h.lower() for h in header]
    estado_idx = lowered.index("estado") if "estado" in lowered else None
    tag = f"h{min(title_level, 6)}"
    cards = []
    for row in body:
        cells = split_row(row)
        cells += [""] * (len(header) - len(cells))
        attrs, badge = ' class="card"', ""
        if estado_idx is not None:
            kind = classify(cells[estado_idx])
            stats[kind] += 1
            attrs = f' class="card tarefa" data-estado="{kind}"'
            badge = (
                f'<p class="estado estado-{kind}"><span aria-hidden="true">'
                f"{STATUS_ICON[kind]}</span> <span class=\"rotulo\">"
                f"{inline(header[estado_idx], sha)}:</span> "
                f"{inline(cells[estado_idx], sha)}</p>"
            )
        fields = [
            f"<dt>{inline(label, sha)}</dt><dd>{inline(value, sha) or '—'}</dd>"
            for idx, (label, value) in enumerate(zip(header, cells))
            if idx not in (0, estado_idx)
        ]
        cards.append(
            f"<li{attrs}><{tag}><span class=\"rotulo\">{inline(header[0], sha)}:</span> "
            f"{inline(cells[0], sha)}</{tag}>{badge}<dl>{''.join(fields)}</dl></li>"
        )
    columns = ", ".join(esc(h) for h in header)
    group = ' data-grupo-tarefas=""' if estado_idx is not None else ""
    empty = (
        '<p class="vazio" hidden>Nenhuma linha desta tabela corresponde ao filtro.</p>'
        if estado_idx is not None
        else ""
    )
    return (
        f'<div class="tabela"{group}><p class="legenda">Tabela do roteiro, colunas: '
        f'{columns}.</p><ul class="cards" role="list">{"".join(cards)}</ul>{empty}</div>'
    )


def render_document(text: str, sha: str) -> tuple[str, str, dict[str, int]]:
    stats = {"feito": 0, "andamento": 0, "falta": 0}
    parts: list[str] = []
    used: set[str] = {"resumo", "filtros", "inicio-do-roteiro"}
    title = "Roteiro"
    level = 2
    section_open = False
    for block in parse_blocks(text.splitlines()):
        kind = block[0]
        if kind == "heading":
            _, lvl, heading = block
            if lvl == 1:
                title = heading
                continue
            slug = slugify(heading, used)
            if lvl == 2:
                if section_open:
                    parts.append("</section>")
                parts.append(f'<section aria-labelledby="{slug}">')
                section_open = True
            parts.append(f'<h{lvl} id="{slug}">{inline(heading, sha)}</h{lvl}>')
            level = lvl
            continue
        if not section_open:
            parts.append(
                '<section aria-labelledby="inicio-do-roteiro">'
                '<h2 id="inicio-do-roteiro">Início do roteiro</h2>'
            )
            section_open = True
        if kind == "para":
            parts.append(f"<p>{inline(block[1], sha)}</p>")
        elif kind == "list":
            _, entries, ordered, start = block
            items = "".join(f"<li>{inline(item, sha)}</li>" for item in entries)
            if ordered:
                start_attr = f' start="{start}"' if start != 1 else ""
                parts.append(f"<ol{start_attr}>{items}</ol>")
            else:
                parts.append(f"<ul>{items}</ul>")
        elif kind == "table":
            parts.append(render_table(block[1], sha, level + 1, stats))
        elif kind == "code":
            parts.append(f"<pre><code>{esc(block[1])}</code></pre>")
    if section_open:
        parts.append("</section>")
    return title, "\n".join(parts), stats


CSS = """
:root{color-scheme:light;--fundo:#f5f7fa;--texto:#1f2933;--suave:#52606d;--azul:#1f4e9a;--borda:#d5dce4;--cartao:#fff}
*{box-sizing:border-box}
[hidden]{display:none!important}
body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:var(--fundo);color:var(--texto);line-height:1.5}
.topo,main{max-width:72rem;margin:0 auto;padding:1rem}
.topo{border-bottom:3px solid var(--azul)}
a{color:var(--azul)}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:3px solid var(--azul);outline-offset:2px}
h1{font-size:1.6rem;margin:.25rem 0}
h2{font-size:1.3rem;margin:2rem 0 .75rem;color:var(--azul)}
h3,h4{font-size:1.05rem;margin:0 0 .5rem}
.meta{color:var(--suave);margin:.25rem 0}
.links{display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;padding:0;list-style:none;margin:.5rem 0 0}
.aviso,.resumo,.filtros{background:var(--cartao);border:1px solid var(--borda);border-left:4px solid var(--azul);border-radius:6px;padding:.75rem 1rem;margin:1rem 0}
.resumo h2{margin-top:0}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;background:#eef2f7;padding:0 .2em;border-radius:3px;overflow-wrap:anywhere}
pre{overflow-x:auto;background:#eef2f7;padding:.75rem;border-radius:6px}
.cards{list-style:none;padding:0;margin:.5rem 0 1rem;display:grid;gap:.75rem;grid-template-columns:repeat(auto-fill,minmax(min(100%,22rem),1fr))}
.card{background:var(--cartao);border:1px solid var(--borda);border-radius:6px;padding:.75rem 1rem;overflow-wrap:anywhere}
.card dl{margin:0}
.card dt{font-weight:600;color:var(--suave);font-size:.85rem;margin-top:.5rem}
.card dd{margin:0}
.rotulo{font-weight:600;color:var(--suave)}
.estado{display:inline-block;margin:0 0 .25rem;padding:.1rem .5rem;border:1px solid;border-radius:4px;font-size:.9rem}
.estado-feito{border-color:#2f6f3e;background:#eef7f0}
.estado-andamento{border-color:#8a6d1d;border-style:dashed;background:#fbf6e6}
.estado-falta{border-color:#9b2c2c;border-style:dotted;background:#fbeeee}
.legenda,.vazio{font-size:.9rem;color:var(--suave)}
.filtros{display:flex;flex-wrap:wrap;gap:.75rem;align-items:flex-end}
.campo{display:flex;flex-direction:column;gap:.25rem}
select,input,button{font:inherit;padding:.35rem .5rem;border:1px solid #7b8794;border-radius:4px;background:#fff;color:inherit}
button{background:var(--azul);border-color:var(--azul);color:#fff;cursor:pointer}
#filtro-status{flex-basis:100%;margin:0;color:var(--suave)}
"""

SCRIPT = """
(function () {
  var form = document.getElementById("filtros");
  if (!form) return;
  form.hidden = false;
  var select = document.getElementById("filtro-estado");
  var busca = document.getElementById("filtro-busca");
  var status = document.getElementById("filtro-status");
  var cards = Array.prototype.slice.call(document.querySelectorAll(".tarefa"));
  var grupos = Array.prototype.slice.call(document.querySelectorAll("[data-grupo-tarefas]"));
  function norm(s) {
    return s.normalize("NFD").replace(/[\\u0300-\\u036f]/g, "").toLowerCase();
  }
  var textos = cards.map(function (c) { return norm(c.textContent); });
  function aplicar() {
    var modo = select.value;
    var termo = norm(busca.value.trim());
    var visiveis = 0;
    cards.forEach(function (card, i) {
      var feito = card.getAttribute("data-estado") === "feito";
      var ok = (modo === "todas" || (modo === "feitas") === feito) &&
        (!termo || textos[i].indexOf(termo) !== -1);
      card.hidden = !ok;
      if (ok) visiveis++;
    });
    grupos.forEach(function (g) {
      g.querySelector(".vazio").hidden = !!g.querySelector(".tarefa:not([hidden])");
    });
    status.textContent = "Mostrando " + visiveis + " de " + cards.length + " linhas de tarefas.";
  }
  select.addEventListener("change", aplicar);
  busca.addEventListener("input", aplicar);
  document.getElementById("filtro-limpar").addEventListener("click", function () {
    select.value = "todas";
    busca.value = "";
    aplicar();
    busca.focus();
  });
  form.addEventListener("submit", function (e) { e.preventDefault(); aplicar(); });
  aplicar();
})();
"""


def render_page(source: str, sha: str) -> str:
    title, body, stats = render_document(source, sha)
    now = now_sao_paulo()
    total = sum(stats.values())
    pending = stats["andamento"] + stats["falta"]
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — painel local</title>
<style>{CSS}</style>
</head>
<body>
<header class="topo">
<h1>{esc(title)} — painel local</h1>
<p class="meta">Gerado em <time datetime="{now.isoformat(timespec='minutes')}">{now:%d/%m/%Y %H:%M}</time> (America/Sao_Paulo) a partir de <code>ROADMAP.md</code>; base <code>{esc(sha)}</code>.</p>
<ul class="links">
<li><a href="ROADMAP.md">Fonte local (cópia do ROADMAP.md)</a></li>
<li><a href="release.html">Plano e prévia do release</a></li>
<li><a href="{esc(REPO_URL)}/blob/{esc(sha)}/ROADMAP.md" rel="noopener noreferrer">ROADMAP no GitHub (base {esc(sha)})</a></li>
<li><a href="{esc(REPO_URL)}/pulls" rel="noopener noreferrer">PRs no GitHub</a></li>
</ul>
</header>
<main>
<p class="aviso">Visualização derivada do roteiro, não plano paralelo. Não há percentual global. O estado de produção é o das evidências datadas do roteiro; este painel não consulta produção. A fonte local pode conter edições ainda não integradas na base.</p>
<section class="resumo" aria-labelledby="resumo">
<h2 id="resumo">O que falta para concluir o produto</h2>
<ul>
<li><strong>Agora:</strong> conferir backend e banco com o acesso do dono e preparar a janela do release controlado do piloto interno (o pacote já foi validado só localmente, em simulação); fazer o aceite pastoral das 20 conversas e do caminho G12 completo.</li>
<li><strong>Para o produto completo:</strong> completar lacunas funcionais, privacidade e segurança, qualidade e infraestrutura conforme o roteiro.</li>
<li><strong>Código integrado não equivale a módulo liberado:</strong> o critério de pronto exige ainda release controlado com autorização nominal, aceite pastoral, abertura ampliada e monitoramento.</li>
<li>Linhas com coluna Estado: {stats['feito']} feito, {stats['andamento']} em andamento, {stats['falta']} falta ({pending} pendentes de {total}). É contagem de linhas, não medida de conclusão.</li>
</ul>
</section>
<form id="filtros" class="filtros" role="search" aria-label="Filtrar tarefas" hidden>
<div class="campo"><label for="filtro-estado">Estado</label>
<select id="filtro-estado">
<option value="todas">Todas</option>
<option value="pendentes">Pendentes (em andamento ou falta)</option>
<option value="feitas">Feitas em código ou registro</option>
</select></div>
<div class="campo"><label for="filtro-busca">Buscar nas tarefas</label>
<input id="filtro-busca" type="search" autocomplete="off"></div>
<button type="button" id="filtro-limpar">Limpar filtros</button>
<p id="filtro-status" role="status" aria-live="polite"></p>
</form>
{body}
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""


def render_release_page(doc: str, sha: str) -> str:
    """Só a seção atual do runbook do lote; o histórico datado fica no próprio runbook."""
    start = doc.index(RELEASE_START)
    _, body, _ = render_document(doc[start:doc.index(RELEASE_END, start)], sha)
    now = now_sao_paulo()
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plano e prévia do release — Igreja 12</title>
<style>{CSS}</style>
</head>
<body>
<header class="topo">
<h1>Plano e prévia do release — Igreja 12</h1>
<p class="meta">Gerado em <time datetime="{now.isoformat(timespec='minutes')}">{now:%d/%m/%Y %H:%M}</time> (America/Sao_Paulo) a partir de <code>{esc(RELEASE_DOC)}</code>; base <code>{esc(sha)}</code>.</p>
<ul class="links">
<li><a href="index.html">Painel do roteiro</a></li>
<li><a href="{esc(RELEASE_DOC)}">Fonte local (cópia do runbook)</a></li>
</ul>
</header>
<main>
<p class="aviso">Plano para revisão: não é autorização para executar nada em produção. Visualização derivada da seção atual do runbook, não plano paralelo; o histórico datado permanece no runbook.</p>
{body}
</main>
</body>
</html>
"""


def main() -> int:
    source = SOURCE.read_text(encoding="utf-8")
    match = SHA_RE.search(source)
    if match is None:
        # Sem SHA no cabeçalho, os links ao GitHub apontariam para base errada.
        print("ROADMAP.md sem 'sobre a `main` `<sha>`' no cabeçalho; painel não gerado.",
              file=sys.stderr)
        return 1
    sha = match.group(1)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "index.html").write_text(render_page(source, sha), encoding="utf-8")
    release = render_release_page((ROOT / RELEASE_DOC).read_text(encoding="utf-8"), sha)
    (OUT_DIR / "release.html").write_text(release, encoding="utf-8")
    (OUT_DIR / "ROADMAP.md").write_text(source, encoding="utf-8")
    for doc in LOCAL_DOCS:
        dest = OUT_DIR / doc
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text((ROOT / doc).read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Painel gerado em {OUT_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
