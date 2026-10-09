/* Painel de acompanhamento. Só visualiza window.PAINEL_DADOS (gerado por atualizar.py).
   Sem rede, sem tokens: tudo vem de dados.js. */
(function () {
  "use strict";

  var D = window.PAINEL_DADOS;
  var raiz = document.getElementById("principal");
  if (!D) {
    raiz.innerHTML = "";
    var msg = document.createElement("div");
    msg.className = "cartao aviso erro";
    msg.textContent = "dados.js não encontrado. Execute ./acompanhar.sh (ou python3 docs/ops/acompanhamento/atualizar.py) para gerá-lo.";
    raiz.appendChild(msg);
    return;
  }

  /* ---------- vocabulário ---------- */
  var STATUS = {
    ok: { rot: "OK", sim: "✓" },
    falhou: { rot: "Falhou", sim: "✕" },
    pendente: { rot: "Pendente", sim: "…" },
    em_andamento: { rot: "Em andamento", sim: "◐" },
    parcial: { rot: "Parcial", sim: "◑" },
    nao_iniciado: { rot: "Não iniciado", sim: "○" },
    nao_aplicavel: { rot: "Não se aplica", sim: "–" },
    desconhecido: { rot: "Sem evidência", sim: "?" }
  };
  var ESTADO_SIM = { futura: "○", pronta: "▷", em_andamento: "◐", em_validacao: "◑", bloqueada: "✕", concluida: "✓" };
  var ORDEM_ESTADOS = ["futura", "pronta", "em_andamento", "em_validacao", "bloqueada", "concluida"];
  var COLUNAS = { futura: "Futuras", pronta: "Prontas", em_andamento: "Em andamento", em_validacao: "Em validação", bloqueada: "Bloqueadas", concluida: "Concluídas" };
  var IND_ROTULO = {
    implementacao: "Implementação",
    validacao_local: "Validação local",
    ci: "CI",
    integracao_main: "Integração na main",
    publicacao_dev: "Publicação em DEV",
    publicacao_prod: "Publicação em PROD"
  };
  var IND_CURTO = { implementacao: "Impl.", validacao_local: "Local", ci: "CI", integracao_main: "Main", publicacao_dev: "DEV", publicacao_prod: "PROD" };
  var TRILHAS = { principal: "Sequência principal", paralela: "Trilhas paralelas", backlog: "Backlog condicionado" };
  var VIEWS = [
    { id: "visao", rot: "Visão geral" },
    { id: "quadro", rot: "Quadro" },
    { id: "pipeline", rot: "Pipeline" },
    { id: "historico", rot: "Histórico" }
  ];

  var porId = {};
  D.tarefas.forEach(function (t) { porId[t.id] = t; });
  var faseDe = {};
  D.fases.forEach(function (f) { faseDe[f.id] = f; });

  /* ---------- utilidades ---------- */
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k.slice(0, 2) === "on") el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? "" : v);
      });
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, c) {
    if (c === null || c === undefined || c === false) return;
    if (Array.isArray(c)) c.forEach(function (x) { add(el, x); });
    else if (typeof c === "string") el.appendChild(document.createTextNode(c));
    else el.appendChild(c);
  }
  var FMT = new Intl.DateTimeFormat("pt-BR", { timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
  function dataHora(iso) { return iso ? FMT.format(new Date(iso)) + " (Brasília)" : "sem registro"; }
  function soData(iso) {
    if (!iso) return "";
    var p = iso.slice(0, 10).split("-");
    return p[2] + "/" + p[1] + "/" + p[0];
  }
  function idade(iso) {
    if (!iso) return null;
    var min = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (min < 60) return "há " + min + " min";
    var hs = Math.round(min / 60);
    if (hs < 48) return "há " + hs + " h";
    return "há " + Math.round(hs / 24) + " dias";
  }
  function curto(sha) { return sha ? sha.slice(0, 8) : ""; }
  function pct(a, b) { return b ? Math.round((a / b) * 100) : 0; }

  function chipStatus(status, rotulo) {
    var s = STATUS[status] || STATUS.desconhecido;
    return h("span", { class: "chip s-" + status }, h("span", { class: "sim", "aria-hidden": "true" }, s.sim), rotulo ? rotulo + ": " + s.rot : s.rot);
  }
  function chipEstado(estado) {
    return h("span", { class: "chip e-" + estado }, h("span", { class: "sim", "aria-hidden": "true" }, ESTADO_SIM[estado]), D.estados[estado]);
  }
  function linkExterno(url, texto) {
    return h("a", { href: url, target: "_blank", rel: "noopener noreferrer" }, texto);
  }
  function botaoTarefa(id) {
    var t = porId[id];
    return h("button", { type: "button", class: "link-tarefa", onclick: function () { abrirDetalhe(id); } }, id + " · " + (t ? t.titulo : "?"));
  }

  /* ---------- estado e roteamento (hash: #view/ID?q=..&fase=..&estado=..&trilha=..) ---------- */
  var estado = { view: "visao", tarefa: null, q: "", fase: "", est: "", trilha: "" };

  function lerHash() {
    var raw = location.hash.replace(/^#/, "");
    var partes = raw.split("?");
    var caminho = partes[0].split("/");
    var v = caminho[0];
    estado.view = VIEWS.some(function (x) { return x.id === v; }) ? v : "visao";
    estado.tarefa = caminho[1] && porId[caminho[1]] ? caminho[1] : null;
    var qs = new URLSearchParams(partes[1] || "");
    estado.q = qs.get("q") || "";
    estado.fase = qs.get("fase") || "";
    estado.est = qs.get("estado") || "";
    estado.trilha = qs.get("trilha") || "";
  }
  function queryStr() {
    var qs = new URLSearchParams();
    if (estado.q) qs.set("q", estado.q);
    if (estado.fase) qs.set("fase", estado.fase);
    if (estado.est) qs.set("estado", estado.est);
    if (estado.trilha) qs.set("trilha", estado.trilha);
    var s = qs.toString();
    return s ? "?" + s : "";
  }
  function gravarHash(replace) {
    var novo = "#" + estado.view + (estado.tarefa ? "/" + estado.tarefa : "") + queryStr();
    if (location.hash === novo) return;
    if (replace) history.replaceState(null, "", novo);
    else location.hash = novo;
  }

  /* ---------- filtros ---------- */
  function casa(t) {
    if (estado.fase && t.fase !== estado.fase) return false;
    if (estado.est && t.estado !== estado.est) return false;
    if (estado.trilha && t.trilha !== estado.trilha) return false;
    if (estado.q) {
      var termo = estado.q.toLowerCase();
      var palha = [t.id, t.titulo, t.objetivo, faseDe[t.fase].nome, D.estados[t.estado], t.situacao]
        .concat(t.pr.map(function (n) { return "#" + n + " pr " + n; })).join(" ").toLowerCase();
      if (palha.indexOf(termo) === -1) return false;
    }
    return true;
  }
  function filtradas() { return D.tarefas.filter(casa); }
  function filtrosAtivos() { return !!(estado.q || estado.fase || estado.est || estado.trilha); }

  function montarFiltros() {
    var fase = document.getElementById("f-fase");
    var est = document.getElementById("f-estado");
    var tri = document.getElementById("f-trilha");
    function opcoes(sel, pares, todos) {
      sel.innerHTML = "";
      sel.appendChild(h("option", { value: "", text: todos }));
      pares.forEach(function (p) { sel.appendChild(h("option", { value: p[0], text: p[1] })); });
    }
    opcoes(fase, D.fases.map(function (f) { return [f.id, f.nome]; }), "Todas as fases");
    opcoes(est, ORDEM_ESTADOS.map(function (e) { return [e, D.estados[e]]; }), "Todos os estados");
    opcoes(tri, Object.keys(TRILHAS).map(function (k) { return [k, TRILHAS[k]]; }), "Todas as trilhas");
    var busca = document.getElementById("f-busca");
    var atraso;
    busca.addEventListener("input", function () {
      clearTimeout(atraso);
      atraso = setTimeout(function () { estado.q = busca.value.trim(); gravarHash(true); desenhar(); }, 150);
    });
    fase.addEventListener("change", function () { estado.fase = fase.value; gravarHash(true); desenhar(); });
    est.addEventListener("change", function () { estado.est = est.value; gravarHash(true); desenhar(); });
    tri.addEventListener("change", function () { estado.trilha = tri.value; gravarHash(true); desenhar(); });
    document.getElementById("f-limpar").addEventListener("click", function () {
      estado.q = estado.fase = estado.est = estado.trilha = "";
      gravarHash(true);
      sincronizarControles();
      desenhar();
    });
  }
  function sincronizarControles() {
    document.getElementById("f-busca").value = estado.q;
    document.getElementById("f-fase").value = estado.fase;
    document.getElementById("f-estado").value = estado.est;
    document.getElementById("f-trilha").value = estado.trilha;
  }

  /* ---------- cabeçalho: abas e frescor ---------- */
  function desenharAbas() {
    var nav = document.getElementById("abas");
    nav.innerHTML = "";
    VIEWS.forEach(function (v) {
      nav.appendChild(h("a", { href: "#" + v.id + queryStr(), "aria-current": v.id === estado.view ? "page" : null, text: v.rot }));
    });
  }
  function envelopes() {
    var g = D.github || {};
    var lista = [];
    Object.keys(g.prs || {}).forEach(function (k) { lista.push({ nome: "PR #" + k, env: g.prs[k] }); });
    if (g.main) lista.push({ nome: "main", env: g.main });
    Object.keys(g.monitores || {}).forEach(function (k) { lista.push({ nome: k, env: g.monitores[k] }); });
    return lista;
  }
  function desenharFrescor() {
    var el = document.getElementById("frescor");
    el.innerHTML = "";
    var g = D.github || {};
    var env = envelopes();
    var falhas = env.filter(function (e) { return !e.env.ok; });
    var datas = env.map(function (e) { return e.env.consultado_em; }).filter(Boolean).sort();
    var maisAntiga = datas[0];
    var velha = maisAntiga && Date.now() - new Date(maisAntiga).getTime() > 24 * 3600 * 1000;
    el.appendChild(h("div", null, "Painel gerado em ", h("strong", { text: dataHora(D.gerado_em) }),
      D.git && D.git.sha ? " · a partir de " + D.git.branch + "@" + D.git.sha : ""));
    var linha = h("div", null, "GitHub (somente leitura): ",
      maisAntiga ? ["leitura mais antiga em ", h("strong", { text: dataHora(maisAntiga) }), " (" + idade(maisAntiga) + ")"] : "sem leitura registrada");
    el.appendChild(linha);
    if (falhas.length) {
      el.appendChild(h("div", null, h("span", { class: "alerta" }, "Desatualizado"), " Falha na última consulta de " +
        falhas.map(function (f) { return f.nome; }).join(", ") + ". A última evidência foi preservada."));
    } else if (velha || !env.length) {
      el.appendChild(h("div", null, h("span", { class: "alerta" }, "Pode estar desatualizado"), " Leitura com mais de 24 h. Rode ./acompanhar.sh."));
    }
    if (g.aviso) el.appendChild(h("div", null, h("span", { class: "alerta" }, "Aviso"), " " + g.aviso));
  }


  /* ---------- pipeline visual: etapas e barras de progresso ---------- */
  function estadoDaFase(ts) {
    var e = ts.map(function (t) { return t.estado; });
    if (e.every(function (x) { return x === "concluida"; })) return "concluida";
    if (e.indexOf("bloqueada") !== -1) return "bloqueada";
    if (e.indexOf("em_validacao") !== -1) return "em_validacao";
    if (e.indexOf("em_andamento") !== -1) return "em_andamento";
    if (e.indexOf("pronta") !== -1) return "pronta";
    return "futura";
  }
  function barraSegmentada(ts, rotulo) {
    var barra = h("div", { class: "barra", role: "img", "aria-label": rotulo });
    ts.forEach(function (t) {
      barra.appendChild(h("span", { class: "seg e-" + t.estado, title: t.id + " · " + t.titulo + " — " + t.estado_rotulo }));
    });
    return barra;
  }
  function pipelineVisual() {
    var r = D.resumo;
    var principais = D.fases.filter(function (f) { return f.trilha === "principal"; }).sort(function (a, b) { return a.ordem - b.ordem; });
    var atual = r.etapa_atual ? r.etapa_atual.fase : null;
    var sec = h("section", { class: "cartao larga hero", "aria-labelledby": "hero-t" },
      h("h2", { id: "hero-t", text: "Pipeline de progresso (sequência principal)" }));

    // barra geral: um segmento por tarefa, colorido pelo estado
    var princ = D.tarefas.filter(function (t) { return t.trilha === "principal"; }).sort(function (a, b) { return a.sequencia - b.sequencia; });
    var p = r.proporcao.principal;
    sec.appendChild(h("div", { class: "hero-geral" },
      h("div", { class: "hero-num" }, h("strong", { text: p.concluidas + " de " + p.total }), " tarefas concluídas (" + pct(p.concluidas, p.total) + "%)"),
      barraSegmentada(princ, "Cada segmento é uma tarefa da sequência principal; a cor mostra o estado. " + p.texto)));

    var ol = h("ol", { class: "pipe", "aria-label": "Etapas em ordem" });
    principais.forEach(function (f) {
      var ts = D.tarefas.filter(function (t) { return t.fase === f.id; }).sort(function (a, b) { return a.sequencia - b.sequencia; });
      var est = estadoDaFase(ts);
      var feitas = ts.filter(function (t) { return t.estado === "concluida"; }).length;
      var aqui = f.id === atual;
      ol.appendChild(h("li", { class: "etapa f-" + est + (aqui ? " aqui" : ""), "aria-current": aqui ? "step" : null },
        h("a", { href: "#quadro?fase=" + f.id, class: "etapa-link" },
          h("span", { class: "etapa-ordem", "aria-hidden": "true", text: String(f.ordem) }),
          h("span", { class: "etapa-nome", text: f.nome.replace(/^F\d[a-b]? · |^F0 · /, "") }),
          h("span", { class: "chip e-" + est }, h("span", { class: "sim", "aria-hidden": "true" }, ESTADO_SIM[est]), D.estados[est]),
          barraSegmentada(ts, f.nome + ": " + feitas + " de " + ts.length + " tarefas concluídas"),
          h("span", { class: "etapa-cont", text: feitas + " de " + ts.length + " concluídas" }),
          aqui ? h("span", { class: "etapa-aqui", text: "etapa atual" }) : null)));
    });
    sec.appendChild(ol);

    var leg = h("ul", { class: "legenda", "aria-label": "Legenda das cores" });
    ORDEM_ESTADOS.forEach(function (e) {
      leg.appendChild(h("li", null, h("span", { class: "seg e-" + e, "aria-hidden": "true" }), D.estados[e]));
    });
    sec.appendChild(leg);
    sec.appendChild(h("p", { class: "nota", text: "Cada segmento é uma tarefa; as barras contam itens, não esforço nem prazo. As trilhas paralelas e o backlog ficam fora desta sequência (veja Pipeline)." }));
    return sec;
  }

  /* ---------- visão geral ---------- */
  function cartao(titulo, filhos, classe) {
    return h("section", { class: "cartao" + (classe ? " " + classe : "") }, h("h2", { text: titulo }), filhos);
  }
  function visaoGeral() {
    var r = D.resumo;
    var frag = document.createDocumentFragment();

    frag.appendChild(h("div", { class: "grade" }, pipelineVisual()));

    var grade = h("div", { class: "grade" });
    // Etapa atual
    var etapa = r.etapa_atual;
    grade.appendChild(cartao("Etapa atual", etapa ? [
      h("span", { class: "grande", text: etapa.nome }),
      h("p", { class: "nota" }, etapa.tarefa + " · ", h("strong", { text: etapa.situacao })),
      r.em_curso.length ? [h("p", { class: "nota", text: "Em curso agora:" }), h("ul", { class: "nota" }, r.em_curso.map(function (id) { return h("li", null, botaoTarefa(id)); }))] : null
    ] : h("p", { text: "Sequência principal concluída." })));
    // Próxima executável
    var prox = r.proxima_executavel ? porId[r.proxima_executavel] : null;
    var tambem = r.tambem_prontas || [];
    grade.appendChild(cartao("Próxima tarefa executável", prox ? [
      h("span", { class: "grande" }, botaoTarefa(prox.id)),
      h("p", { class: "nota", text: prox.proxima_acao }),
      tambem.length ? [h("p", { class: "nota", text: "Também prontas:" }), h("ul", { class: "nota" }, tambem.map(function (id) { return h("li", null, botaoTarefa(id)); }))] : null
    ] : h("p", { class: "vazio", text: "Nenhuma tarefa da sequência principal está pronta." })));
    // Bloqueios e esperas
    var itens = [];
    r.bloqueios.forEach(function (b) { itens.push(h("li", null, h("strong", { text: "Bloqueio · " }), botaoTarefa(b.id), ": " + b.motivo)); });
    r.esperas.forEach(function (b) { itens.push(h("li", null, h("strong", { text: "Espera · " }), botaoTarefa(b.id), ": " + b.motivo)); });
    grade.appendChild(cartao("Bloqueios e esperas", itens.length ? h("ul", null, itens) : h("p", { class: "vazio", text: "Nenhum registrado." })));
    frag.appendChild(grade);

    // Contagens + proporção
    var grade2 = h("div", { class: "grade" });
    var cont = h("div", { class: "contagens" });
    ORDEM_ESTADOS.forEach(function (e) {
      cont.appendChild(h("a", { href: "#quadro?estado=" + e }, h("span", { class: "n", text: String(r.contagem[e]) }), h("span", { class: "r" }, chipEstado(e))));
    });
    grade2.appendChild(cartao("Tarefas por estado", cont));
    var p = r.proporcao;
    var linhas = [
      ["Geral", p.geral], ["Sequência principal", p.principal], ["Trilhas paralelas", p.paralela], ["Backlog condicionado", p.backlog]
    ].map(function (x) {
      return h("div", { class: "nota" }, h("strong", { text: x[0] + ": " }), x[1].concluidas + " de " + x[1].total + " tarefas concluídas (" + pct(x[1].concluidas, x[1].total) + "%)",
        h("progress", { value: x[1].concluidas, max: x[1].total || 1, "aria-label": x[0] + ": " + x[1].concluidas + " de " + x[1].total + " tarefas concluídas" }));
    });
    grade2.appendChild(cartao("Proporção de tarefas concluídas", [linhas, h("p", { class: "nota" }, "Cálculo: " + p.formula)]));
    frag.appendChild(grade2);

    // GitHub: PRs, main, monitor
    frag.appendChild(secaoGithub());

    // Matriz de indicadores
    var tarefas = filtradas();
    frag.appendChild(h("section", { class: "secao" },
      h("h2", { text: "Indicadores por tarefa" }),
      h("p", { class: "nota", text: "Seis indicadores separados. CI e integração na main vêm da leitura do GitHub quando há PR de referência." }),
      matrizIndicadores(tarefas)));
    return frag;
  }

  function secaoGithub() {
    var g = D.github || {};
    var sec = h("section", { class: "secao" }, h("h2", { text: "Sinais do GitHub (leitura)" }));
    var prs = Object.keys(g.prs || {}).sort();
    var linhas = prs.map(function (k) {
      var env = g.prs[k];
      var d = env.dados;
      if (!d) return h("tr", null, h("td", { text: "#" + k }), h("td", { colspan: 4, text: "Sem leitura. " + (env.erro || "") }));
      var req = D.checks_obrigatorios.map(function (n) {
        var c = d.checks.filter(function (x) { return x.nome === n; })[0];
        var st = !c ? "desconhecido" : c.conclusao === "SUCCESS" ? "ok" : (c.conclusao && c.conclusao !== "SKIPPED" && c.conclusao !== "NEUTRAL") ? "falhou" : "pendente";
        return h("span", null, chipStatus(st, n), " ");
      });
      return h("tr", null,
        h("td", null, linkExterno(d.url, "#" + d.numero)),
        h("td", null, d.titulo, h("br"), h("span", { class: "sha", title: d.sha, text: curto(d.sha) }), " · " + d.branch),
        h("td", { text: d.estado === "OPEN" ? "Aberto" : d.estado === "MERGED" ? "Integrado" : "Fechado" }),
        h("td", null, req),
        h("td", { text: (env.ok ? "" : "Desatualizado · ") + dataHora(env.consultado_em) }));
    });
    sec.appendChild(h("div", { class: "tabela-rolagem" }, h("table", { "aria-label": "Pull requests acompanhados" },
      h("thead", null, h("tr", null, ["PR", "Título e SHA", "Situação", "Checks obrigatórios", "Consultado"].map(function (x) { return h("th", { scope: "col", text: x }); }))),
      h("tbody", null, linhas))));
    var info = [];
    if (g.main && g.main.dados) {
      info.push(h("p", { class: "nota" }, h("strong", { text: "main: " }), h("span", { class: "sha", title: g.main.dados.sha, text: curto(g.main.dados.sha) }),
        " · " + g.main.dados.mensagem + " · " + dataHora(g.main.dados.data) + (g.main.ok ? "" : " · leitura desatualizada")));
    }
    Object.keys(g.monitores || {}).forEach(function (k) {
      var env = g.monitores[k];
      var d = env.dados;
      if (!d) return;
      var txt = d.falhas_consecutivas > 0
        ? d.falhas_consecutivas + " execuções agendadas seguidas em falha" + (d.todas_falharam ? " (ao menos)" : "") + ", desde " + dataHora(d.falhas_desde) + "."
        : "Última execução agendada sem falha.";
      info.push(h("p", { class: "nota" }, h("strong", { text: d.descricao + ": " }), txt + " Causa não determinada; triagem em ", botaoTarefa("S1"), ". Consultado em " + dataHora(env.consultado_em) + (env.ok ? "" : " (desatualizado)") + "."));
    });
    sec.appendChild(h("div", { style: "margin-top:10px" }, info));
    return sec;
  }

  function matrizIndicadores(tarefas) {
    if (!tarefas.length) return h("p", { class: "vazio", text: "Nenhuma tarefa corresponde aos filtros." });
    var cab = h("tr", null, h("th", { scope: "col", text: "Tarefa" }), h("th", { scope: "col", text: "Situação" }),
      D.indicadores.map(function (i) { return h("th", { scope: "col", text: IND_ROTULO[i] }); }));
    var corpo = tarefas.map(function (t) {
      return h("tr", null,
        h("th", { scope: "row" }, botaoTarefa(t.id)),
        h("td", null, chipEstado(t.estado), t.situacao !== t.estado_rotulo ? h("div", { class: "nota", text: t.situacao }) : null),
        D.indicadores.map(function (i) { return h("td", null, chipStatus(t.indicadores[i].status)); }));
    });
    return h("div", { class: "tabela-rolagem" }, h("table", null, h("thead", null, cab), h("tbody", null, corpo)));
  }

  /* ---------- quadro (kanban) ---------- */
  function miniIndicadores(t) {
    var visiveis = D.indicadores.filter(function (i) { return t.indicadores[i].status !== "nao_aplicavel"; });
    return h("div", { class: "mini", "aria-label": "Indicadores (os que não se aplicam ficam só nos detalhes)" }, visiveis.map(function (i) {
      var s = t.indicadores[i].status;
      return h("span", { class: "chip s-" + s, title: IND_ROTULO[i] + ": " + STATUS[s].rot }, h("span", { class: "sim", "aria-hidden": "true" }, STATUS[s].sim), IND_CURTO[i] + " " + STATUS[s].rot);
    }));
  }
  function cartaoTarefa(t) {
    return h("button", { type: "button", class: "tarefa", onclick: function () { abrirDetalhe(t.id); } },
      h("span", { class: "cod", text: t.id + " · " + faseDe[t.fase].nome }),
      h("span", { class: "tit", text: t.titulo }),
      h("span", { class: "meta" }, t.situacao !== t.estado_rotulo ? h("span", { class: "chip e-" + t.estado }, h("span", { class: "sim", "aria-hidden": "true" }, ESTADO_SIM[t.estado]), t.situacao) : null,
        t.prs.map(function (p) { return h("span", { class: "chip s-nao_iniciado", text: "PR #" + p.numero }); })),
      miniIndicadores(t));
  }
  function quadro() {
    var lista = filtradas();
    var q = h("div", { class: "quadro" });
    ORDEM_ESTADOS.forEach(function (e) {
      var col = lista.filter(function (t) { return t.estado === e; });
      var rotId = "col-" + e;
      q.appendChild(h("section", { class: "coluna", "aria-labelledby": rotId },
        h("h2", { id: rotId }, h("span", null, h("span", { "aria-hidden": "true" }, ESTADO_SIM[e] + " "), COLUNAS[e]), h("span", { class: "cont", "aria-label": col.length + " tarefas", text: String(col.length) })),
        col.length ? h("ul", null, col.map(function (t) { return h("li", null, cartaoTarefa(t)); })) : h("p", { class: "vazio", text: "Nenhuma tarefa." })));
    });
    return q;
  }

  /* ---------- pipeline ---------- */
  function noPipeline(t) {
    var deps = (t.depende_de || []).map(function (id) {
      var d = porId[id];
      return h("span", { class: "dep" }, chipEstado(d.estado), botaoTarefa(id));
    });
    var integra = (t.integra_apos || []).map(function (id) {
      return h("span", { class: "dep" }, chipEstado(porId[id].estado), botaoTarefa(id));
    });
    return h("li", { class: "no" },
      h("div", null, h("span", { class: "cod", text: t.id + " " }), h("button", { type: "button", class: "link-tarefa", onclick: function () { abrirDetalhe(t.id); }, text: t.titulo })),
      h("div", { class: "meta", style: "margin-top:6px;display:flex;gap:4px;flex-wrap:wrap" }, chipEstado(t.estado), t.situacao !== t.estado_rotulo ? h("span", { class: "chip s-pendente", text: t.situacao }) : null),
      deps.length ? h("div", { class: "deps" }, h("strong", { text: "Depende de: " }), deps) : h("div", { class: "deps", text: "Sem dependência de tarefa." }),
      integra.length ? h("div", { class: "deps" }, h("strong", { text: "Só integra depois de: " }), integra) : null,
      t.dep_nota ? h("div", { class: "deps", text: t.dep_nota }) : null);
  }
  function pipeline() {
    var lista = filtradas();
    var ids = {};
    lista.forEach(function (t) { ids[t.id] = true; });
    var frag = document.createDocumentFragment();
    var principais = D.fases.filter(function (f) { return f.trilha === "principal"; }).sort(function (a, b) { return a.ordem - b.ordem; });
    var ol = h("ol", { class: "fluxo", "aria-label": "Sequência principal, em ordem" });
    principais.forEach(function (f) {
      var ts = D.tarefas.filter(function (t) { return t.fase === f.id && ids[t.id]; }).sort(function (a, b) { return a.sequencia - b.sequencia; });
      if (!ts.length) return;
      var todas = D.tarefas.filter(function (t) { return t.fase === f.id; });
      var feitas = todas.filter(function (t) { return t.estado === "concluida"; }).length;
      ol.appendChild(h("li", { class: "fase" },
        h("h3", null, h("span", { class: "ordem", "aria-label": "Passo " + f.ordem, text: String(f.ordem) }), f.nome,
          h("span", { class: "chip " + (feitas === todas.length ? "s-ok" : "s-nao_iniciado") }, feitas + " de " + todas.length + " concluídas")),
        h("ul", { class: "nos" }, ts.map(noPipeline))));
    });
    frag.appendChild(h("section", { class: "secao" }, h("h2", { text: TRILHAS.principal }),
      h("p", { class: "nota", text: "Ordem do plano: cada entrega fecha antes da próxima. “Depende de” é impedimento para começar; “só integra depois de” é impedimento para integrar." }),
      ol.childNodes.length ? ol : h("p", { class: "vazio", text: "Nenhuma tarefa da sequência principal corresponde aos filtros." })));
    ["paralela", "backlog"].forEach(function (tr) {
      var ts = lista.filter(function (t) { return t.trilha === tr; });
      frag.appendChild(h("section", { class: "secao" }, h("h2", { text: TRILHAS[tr] }),
        tr === "paralela" ? h("p", { class: "nota", text: "Fora da sequência principal. Suas dependências reais estão indicadas em cada tarefa." }) : h("p", { class: "nota", text: "Só abre quando uma mudança real justificar." }),
        ts.length ? h("ul", { class: "paralelas" }, ts.map(noPipeline)) : h("p", { class: "vazio", text: "Nenhuma tarefa corresponde aos filtros." })));
    });
    return frag;
  }

  /* ---------- histórico ---------- */
  function historico() {
    var q = estado.q.toLowerCase();
    var itens = D.historico.filter(function (e) {
      var t = porId[e.tarefa];
      if (estado.fase && t.fase !== estado.fase) return false;
      if (estado.trilha && t.trilha !== estado.trilha) return false;
      if (q && (e.titulo + " " + e.descricao + " " + e.tarefa + " #" + (e.pr || "")).toLowerCase().indexOf(q) === -1) return false;
      return true;
    }).slice().reverse();
    var integrados = Object.keys((D.github || {}).prs || {}).filter(function (k) { var d = D.github.prs[k].dados; return d && d.estado === "MERGED"; });
    var cabeca = h("p", { class: "nota" }, integrados.length
      ? integrados.length + " PR(s) cadastrados já integrados na main."
      : "Nenhuma das entregas abaixo está integrada na main até a última leitura do GitHub. Entregas aparecem como abertas, não como publicadas.");
    var lista = h("ol", { class: "linha-tempo" });
    itens.forEach(function (e) {
      var env = e.pr ? ((D.github || {}).prs || {})[String(e.pr)] : null;
      var d = env && env.dados;
      var sit = d ? (d.estado === "OPEN" ? "PR aberto" : d.estado === "MERGED" ? "PR integrado" : "PR fechado sem integração") : null;
      lista.appendChild(h("li", null,
        h("div", { class: "data", text: soData(e.data) }),
        h("h3", { text: e.titulo }),
        h("p", { text: e.descricao }),
        h("div", { class: "acoes" },
          e.pr ? linkExterno("https://github.com/" + D.repositorio + "/pull/" + e.pr, "PR #" + e.pr) : null,
          sit ? h("span", { class: "chip " + (d.estado === "MERGED" ? "s-ok" : "s-pendente"), text: sit }) : null,
          d ? h("span", { class: "sha", title: d.sha, text: "head " + curto(d.sha) }) : (e.sha ? h("span", { class: "sha", title: e.sha, text: curto(e.sha) }) : null),
          botaoTarefa(e.tarefa))));
    });
    return h("section", { class: "secao" }, h("h2", { text: "Entregas realizadas" }), cabeca,
      itens.length ? lista : h("p", { class: "vazio", text: "Nenhuma entrega corresponde aos filtros." }));
  }

  /* ---------- diálogo de detalhes ---------- */
  var dlg = document.getElementById("detalhe");
  function secaoDlg(titulo, conteudo) { return h("section", null, h("h3", { text: titulo }), conteudo); }
  function abrirDetalhe(id) {
    estado.tarefa = id;
    gravarHash(true);
    mostrarDetalhe(id);
  }
  function mostrarDetalhe(id) {
    var t = porId[id];
    if (!t) return;
    dlg.innerHTML = "";
    var fechar = h("button", { type: "button", class: "botao", onclick: function () { dlg.close(); } }, "Fechar");
    dlg.appendChild(h("div", { class: "dlg-topo" },
      h("div", null, h("h2", { id: "detalhe-titulo", text: t.id + " · " + t.titulo }),
        h("div", { class: "etiquetas" }, chipEstado(t.estado), t.situacao !== t.estado_rotulo ? h("span", { class: "chip s-pendente", text: t.situacao }) : null,
          h("span", { class: "chip s-nao_iniciado", text: faseDe[t.fase].nome }), h("span", { class: "chip s-nao_iniciado", text: TRILHAS[t.trilha] }))),
      fechar));
    var c = h("div", { class: "dlg-corpo" });
    if (t.bloqueio) c.appendChild(h("div", { class: "aviso erro" }, h("strong", { text: "Bloqueio: " }), t.bloqueio));
    if (t.aguardando) c.appendChild(h("div", { class: "aviso" }, h("strong", { text: "Aguardando: " }), t.aguardando));
    c.appendChild(secaoDlg("Objetivo", h("p", { text: t.objetivo })));
    c.appendChild(secaoDlg("Critério de aceite", h("ul", null, t.criterio_aceite.map(function (x) { return h("li", { text: x }); }))));
    c.appendChild(secaoDlg("Próxima ação", h("p", null, t.proxima_acao, t.responsavel ? h("span", { class: "nota" }, " Responsável: " + t.responsavel + ".") : null)));
    var deps = (t.depende_de || []);
    var integra = (t.integra_apos || []);
    c.appendChild(secaoDlg("Dependências", deps.length || integra.length || t.dep_nota ? h("div", null,
      deps.length ? h("ul", null, deps.map(function (d) { return h("li", null, chipEstado(porId[d].estado), " ", botaoTarefa(d)); })) : h("p", { class: "nota", text: "Nenhuma tarefa precisa estar concluída para começar." }),
      integra.length ? h("div", null, h("strong", { text: "Só integra depois de:" }), h("ul", null, integra.map(function (d) { return h("li", null, chipEstado(porId[d].estado), " ", botaoTarefa(d)); }))) : null,
      t.dep_nota ? h("p", { class: "nota", text: t.dep_nota }) : null) : h("p", { class: "nota", text: "Sem dependências de tarefa." })));

    // PRs
    if (t.prs.length) {
      var linhasPr = t.prs.map(function (p) {
        var env = p.github;
        var d = env && env.dados;
        return h("li", null,
          linkExterno(p.url, "PR #" + p.numero), d ? [" · " + d.titulo, h("br"),
            "Situação: " + (d.estado === "OPEN" ? "aberto" : d.estado === "MERGED" ? "integrado" : "fechado sem integração") + " · branch " + d.branch + " · base ", h("span", { class: "sha", title: d.sha_base, text: curto(d.sha_base) }),
            " · head ", h("span", { class: "sha", title: d.sha, text: curto(d.sha) }), h("br"),
            "Checks: ", d.checks.map(function (k) {
              var st = k.conclusao === "SUCCESS" ? "ok" : (k.conclusao && k.conclusao !== "SKIPPED" && k.conclusao !== "NEUTRAL") ? "falhou" : "pendente";
              return [k.url ? h("a", { href: k.url, target: "_blank", rel: "noopener noreferrer" }, chipStatus(st, k.nome)) : chipStatus(st, k.nome), " "];
            }), h("br"),
            "Consultado em " + dataHora(env.consultado_em) + (env.ok ? "" : " — desatualizado (última falha: " + (env.erro || "sem detalhe") + ")")] : " · sem leitura do GitHub");
      });
      c.appendChild(secaoDlg("Pull request, SHA e checks", h("ul", { class: "evid" }, linhasPr)));
    }

    // Indicadores
    var dl = h("dl", { class: "indic" });
    D.indicadores.forEach(function (i) {
      var v = t.indicadores[i];
      dl.appendChild(h("dt", { text: IND_ROTULO[i] }));
      dl.appendChild(h("dd", null, chipStatus(v.status), v.nota ? " " + v.nota : "", v.origem === "github" ? h("span", { class: "nota" }, " (origem: GitHub, " + dataHora(v.consultado_em) + ")") : null));
    });
    c.appendChild(secaoDlg("Indicadores", dl));

    // Evidências
    c.appendChild(secaoDlg("Evidências disponíveis", t.evidencias.length ? h("ul", { class: "evid" }, t.evidencias.map(function (e) {
      return h("li", null, h("span", { class: "tipo", text: e.tipo }), soData(e.data) + " — " + e.descricao,
        e.sha ? [" ", h("span", { class: "sha", title: e.sha, text: curto(e.sha) })] : null,
        e.url ? [" ", linkExterno(e.url, "abrir")] : null);
    })) : h("p", { class: "vazio", text: "Nenhuma evidência registrada ainda." })));
    if (t.pendencia_externa) c.appendChild(secaoDlg("Pendência fora do repositório", h("p", { text: t.pendencia_externa })));
    c.appendChild(secaoDlg("Plano", h("p", null, "Seção do plano: " + faseDe[t.fase].secao + ". ", h("a", { href: "../refatoracao-modular-plano.md" }, "Abrir o plano"))));
    dlg.appendChild(c);
    if (!dlg.open) dlg.showModal();
    dlg.scrollTop = 0;
  }
  dlg.addEventListener("close", function () {
    if (estado.tarefa) { estado.tarefa = null; gravarHash(true); }
  });
  dlg.addEventListener("click", function (ev) { if (ev.target === dlg) dlg.close(); });

  /* ---------- desenho principal ---------- */
  function desenhar() {
    desenharAbas();
    desenharFrescor();
    var lista = filtradas();
    var cont = document.getElementById("f-contagem");
    cont.textContent = filtrosAtivos()
      ? lista.length + " de " + D.tarefas.length + " tarefas correspondem aos filtros."
      : D.tarefas.length + " tarefas cadastradas.";
    document.getElementById("filtros").hidden = false;
    raiz.innerHTML = "";
    var conteudo;
    if (estado.view === "quadro") conteudo = quadro();
    else if (estado.view === "pipeline") conteudo = pipeline();
    else if (estado.view === "historico") conteudo = historico();
    else conteudo = visaoGeral();
    raiz.appendChild(conteudo);
    document.title = (VIEWS.filter(function (v) { return v.id === estado.view; })[0].rot) + " — Acompanhamento do plano";
  }

  function aoMudarHash() {
    lerHash();
    sincronizarControles();
    desenhar();
    if (estado.tarefa) mostrarDetalhe(estado.tarefa);
    else if (dlg.open) dlg.close();
  }

  montarFiltros();
  window.addEventListener("hashchange", aoMudarHash);
  aoMudarHash();
})();
