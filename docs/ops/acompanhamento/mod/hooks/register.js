// Mod do Claude Code: pipeline e barras de progresso do plano de refatoração.
// Só lê docs/ops/acompanhamento/dados.js (gerado por ./acompanhar.sh) na raiz da sessão.
// Não escreve arquivos, não faz rede e não altera nenhuma chamada de ferramenta.

const PANE = 'plano'
const ARQUIVO = 'docs/ops/acompanhamento/dados.js'
const PREFIXO = 'window.PAINEL_DADOS = '

// Dados lidos e estado de tela (perdidos ao recarregar o mod)
let dados = null
let erro = null
let assinatura = ''
let abaAtual = 'pipeline'
let selecionada = null
let faixa = false

// O que o Claude está fazendo agora (mostrado no painel e na faixa)
let trabalhando = false
let ultimaFerramenta = null
let chamadas = 0

const SIM_ESTADO = { futura: '○', pronta: '▷', em_andamento: '◐', em_validacao: '◑', bloqueada: '✕', concluida: '✓' }
const SIM_IND = { ok: '✓', falhou: '✕', pendente: '…', parcial: '◑', nao_iniciado: '○', nao_aplicavel: '–', desconhecido: '?', em_andamento: '◐' }
const ROT_STATUS = { ok: 'OK', falhou: 'Falhou', pendente: 'Pendente', parcial: 'Parcial', nao_iniciado: 'Não iniciado', nao_aplicavel: 'Não se aplica', desconhecido: 'Sem evidência', em_andamento: 'Em andamento' }
const INDICADORES = ['implementacao', 'validacao_local', 'ci', 'integracao_main', 'publicacao_dev', 'publicacao_prod']
const ROT_IND = { implementacao: 'Implementação', validacao_local: 'Validação local', ci: 'CI', integracao_main: 'Integração na main', publicacao_dev: 'Publicação em DEV', publicacao_prod: 'Publicação em PROD' }
const ROT_IND_CURTO = 'Impl Loc CI Main DEV PROD'

// Cor do texto por estado. "futura" fica esmaecida; a cor nunca é a única pista (há símbolo e rótulo).
function corDe(estado) {
  const cores = { pronta: 'cyan', em_andamento: 'blue', em_validacao: 'yellow', bloqueada: 'red', concluida: 'green' }
  return cores[estado] ? { color: cores[estado] } : { dimColor: true }
}

function corIndicador(status) {
  const cores = { ok: 'green', falhou: 'red', pendente: 'yellow', parcial: 'yellow', em_andamento: 'blue' }
  return cores[status] ? { color: cores[status] } : { dimColor: true }
}

function estadoDaFase(ts) {
  const e = ts.map((t) => t.estado)
  if (e.every((x) => x === 'concluida')) return 'concluida'
  for (const k of ['bloqueada', 'em_validacao', 'em_andamento', 'pronta']) {
    if (e.includes(k)) return k
  }
  return 'futura'
}

function etapas() {
  const fases = dados.fases.filter((f) => f.trilha === 'principal').sort((a, b) => a.ordem - b.ordem)
  return fases.map((f) => {
    const ts = dados.tarefas.filter((t) => t.fase === f.id).sort((a, b) => a.sequencia - b.sequencia)
    return { f, ts, estado: estadoDaFase(ts), feitas: ts.filter((t) => t.estado === 'concluida').length }
  })
}

function principais() {
  return dados.tarefas.filter((t) => t.trilha === 'principal').sort((a, b) => a.sequencia - b.sequencia)
}

function quando(iso) {
  if (!iso) return 'sem registro'
  return new Date(iso).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', dateStyle: 'short', timeStyle: 'short' }) + ' (Brasília)'
}

function nomeCurto(fase) {
  return fase.nome.replace(/^F\d[a-b]? · |^F0 · /, '')
}

// Lê o dados.js. Devolve true quando algo mudou e o painel precisa ser redesenhado.
async function carregar($) {
  const raiz = await $.session.root()
  const caminho = raiz.replace(/\/$/, '') + '/' + ARQUIVO
  const anterior = erro
  try {
    if (!(await $.fs.exists(caminho))) {
      dados = null
      erro = 'dados.js não encontrado em ' + ARQUIVO + '. Rode ./acompanhar.sh na raiz do repositório.'
      return anterior !== erro
    }
    const texto = await $.fs.read(caminho)
    if (texto === assinatura) return false
    const inicio = texto.indexOf(PREFIXO)
    if (inicio === -1) throw new Error('formato inesperado em dados.js')
    dados = JSON.parse(texto.slice(inicio + PREFIXO.length).trim().replace(/;\s*$/, ''))
    assinatura = texto
    erro = null
    return true
  } catch (falha) {
    erro = 'Não foi possível ler os dados: ' + (falha && falha.message ? falha.message : String(falha))
    return anterior !== erro
  }
}

function linhaAgora() {
  if (!trabalhando) return 'Claude: ocioso'
  return 'Claude: trabalhando' + (ultimaFerramenta ? ' · última ferramenta: ' + ultimaFerramenta : '') + ' · ' + chamadas + ' chamadas neste turno'
}

// Barra segmentada: um bloco por tarefa, colorido pelo estado.
function barra(E, ts, largura) {
  return E.Box({
    flexDirection: 'row',
    children: ts.map((t) => E.Text({ ...corDe(t.estado), children: ['█'.repeat(largura) + ' '] })),
  })
}

function vistaPipeline(E) {
  const { Box, Text } = E
  const r = dados.resumo
  const lista = etapas()
  const principal = principais()
  const feitas = principal.filter((t) => t.estado === 'concluida').length
  const atual = r.etapa_atual ? r.etapa_atual.fase : null
  const prox = r.proxima_executavel ? dados.tarefas.find((t) => t.id === r.proxima_executavel) : null

  const linhas = lista.map((x) => {
    const aqui = x.f.id === atual
    return Box({
      flexDirection: 'row',
      columnGap: 1,
      children: [
        Text({ ...(aqui ? { color: 'cyan', bold: true } : { dimColor: true }), children: [aqui ? '▶' : ' '] }),
        Text({ dimColor: true, children: [String(x.f.ordem)] }),
        Box({ width: 24, children: [Text({ bold: aqui, wrap: 'truncate', children: [nomeCurto(x.f)] })] }),
        barra(E, x.ts, 2),
        Text({ ...corDe(x.estado), children: [SIM_ESTADO[x.estado] + ' ' + dados.estados[x.estado]] }),
        Text({ dimColor: true, children: [x.feitas + '/' + x.ts.length] }),
      ],
    })
  })

  return Box({
    flexDirection: 'column',
    children: [
      Text({ bold: true, children: [feitas + ' de ' + principal.length + ' tarefas da sequência principal concluídas (itens, não esforço)'] }),
      barra(E, principal, 2),
      Text({ children: [' '] }),
      ...linhas,
      Text({ children: [' '] }),
      Text({
        children: [
          'Etapa atual: ',
          r.etapa_atual ? r.etapa_atual.nome + ' (' + r.etapa_atual.tarefa + ') — ' + r.etapa_atual.situacao : 'sequência concluída',
        ],
      }),
      Text({ wrap: 'wrap', children: ['Próxima executável: ' + (prox ? prox.id + ' · ' + prox.titulo : 'nenhuma')] }),
      Box({
        flexDirection: 'row',
        columnGap: 2,
        children: ['futura', 'pronta', 'em_andamento', 'em_validacao', 'bloqueada', 'concluida'].map((s) =>
          Text({ ...corDe(s), children: [SIM_ESTADO[s] + ' ' + dados.estados[s]] }),
        ),
      }),
    ],
  })
}

function vistaTarefas(E, redraw) {
  const { Box, Text, Button } = E
  const grupos = [
    ['principal', 'Sequência principal'],
    ['paralela', 'Trilhas paralelas'],
    ['backlog', 'Backlog condicionado'],
  ]
  const filhos = [Text({ dimColor: true, children: ['Indicadores: ' + ROT_IND_CURTO] })]
  for (const [trilha, titulo] of grupos) {
    const ts = dados.tarefas.filter((t) => t.trilha === trilha)
    if (trilha === 'principal') ts.sort((a, b) => a.sequencia - b.sequencia)
    filhos.push(Text({ children: [' '] }))
    filhos.push(Text({ bold: true, children: [titulo] }))
    for (const t of ts) {
      filhos.push(
        Box({
          flexDirection: 'row',
          columnGap: 1,
          children: [
            Text({ ...corDe(t.estado), children: [SIM_ESTADO[t.estado]] }),
            Button({
              key: 't-' + t.id,
              label: t.id + ' ' + t.titulo,
              plain: true,
              onPress: () => {
                selecionada = t.id
                redraw()
              },
            }),
          ],
        }),
      )
      filhos.push(
        Box({
          flexDirection: 'row',
          columnGap: 1,
          children: [
            Text({ dimColor: true, children: ['  '] }),
            Text({ ...corDe(t.estado), children: [t.situacao] }),
            Text({ dimColor: true, children: ['·'] }),
            ...INDICADORES.map((i) => Text({ ...corIndicador(t.indicadores[i].status), children: [SIM_IND[t.indicadores[i].status]] })),
          ],
        }),
      )
    }
  }
  return Box({ flexDirection: 'column', children: filhos })
}

function vistaDetalhe(E, t, redraw) {
  const { Box, Text, Button } = E
  const deps = (t.depende_de || []).map((id) => {
    const d = dados.tarefas.find((x) => x.id === id)
    return d ? id + ' (' + d.estado_rotulo + ')' : id
  })
  const prs = (t.prs || []).map((p) => {
    const g = p.github && p.github.dados
    return g ? 'PR #' + p.numero + ' ' + g.estado.toLowerCase() + ' · head ' + g.sha.slice(0, 8) : 'PR #' + p.numero + ' (sem leitura do GitHub)'
  })
  const linhasInd = INDICADORES.map((i) => {
    const v = t.indicadores[i]
    return Box({
      flexDirection: 'row',
      columnGap: 1,
      children: [
        Text({ ...corIndicador(v.status), children: [SIM_IND[v.status]] }),
        Text({ bold: true, children: [ROT_IND[i] + ':'] }),
        Text({ ...corIndicador(v.status), children: [ROT_STATUS[v.status]] }),
      ],
    })
  })
  return Box({
    flexDirection: 'column',
    children: [
      Button({
        key: 'voltar',
        label: 'Voltar à lista',
        hotkey: 'b',
        onPress: () => {
          selecionada = null
          redraw()
        },
      }),
      Text({ children: [' '] }),
      Text({ bold: true, wrap: 'wrap', children: [t.id + ' · ' + t.titulo] }),
      Text({ ...corDe(t.estado), children: [SIM_ESTADO[t.estado] + ' ' + t.situacao] }),
      t.bloqueio ? Text({ color: 'red', wrap: 'wrap', children: ['Bloqueio: ' + t.bloqueio] }) : Text({ children: [' '] }),
      t.aguardando ? Text({ color: 'yellow', wrap: 'wrap', children: ['Aguardando: ' + t.aguardando] }) : Text({ children: [' '] }),
      Text({ children: [' '] }),
      Text({ wrap: 'wrap', children: ['Objetivo: ' + t.objetivo] }),
      Text({ wrap: 'wrap', children: ['Próxima ação: ' + t.proxima_acao] }),
      Text({ dimColor: true, wrap: 'wrap', children: ['Depende de: ' + (deps.length ? deps.join(', ') : 'nada')] }),
      ...prs.map((p) => Text({ dimColor: true, wrap: 'wrap', children: [p] })),
      Text({ children: [' '] }),
      ...linhasInd,
      Text({ children: [' '] }),
      Text({ dimColor: true, children: [(t.evidencias || []).length + ' evidência(s) registrada(s); detalhes no painel em HTML.'] }),
    ],
  })
}

function vistaBloqueios(E) {
  const { Box, Text } = E
  const r = dados.resumo
  const g = dados.github || {}
  const filhos = []
  filhos.push(Text({ bold: true, children: ['Bloqueios'] }))
  if (!r.bloqueios.length) filhos.push(Text({ dimColor: true, children: ['Nenhum registrado.'] }))
  for (const b of r.bloqueios) filhos.push(Text({ color: 'red', wrap: 'wrap', children: ['✕ ' + b.id + ' · ' + b.titulo + ' — ' + b.motivo] }))
  filhos.push(Text({ children: [' '] }))
  filhos.push(Text({ bold: true, children: ['Esperas'] }))
  if (!r.esperas.length) filhos.push(Text({ dimColor: true, children: ['Nenhuma registrada.'] }))
  for (const b of r.esperas) filhos.push(Text({ color: 'yellow', wrap: 'wrap', children: ['… ' + b.id + ' · ' + b.titulo + ' — ' + b.motivo] }))
  filhos.push(Text({ children: [' '] }))
  filhos.push(Text({ bold: true, children: ['Sinais do GitHub (leitura)'] }))
  const mon = g.monitores && g.monitores['production-monitor']
  if (mon && mon.dados) {
    const d = mon.dados
    filhos.push(
      Text({
        color: d.falhas_consecutivas > 0 ? 'red' : 'green',
        wrap: 'wrap',
        children: [
          d.falhas_consecutivas > 0
            ? d.descricao + ': ' + d.falhas_consecutivas + ' execuções seguidas em falha desde ' + quando(d.falhas_desde) + '. Causa não determinada (tarefa S1).'
            : d.descricao + ': última execução sem falha.',
        ],
      }),
    )
  }
  const prs = Object.keys(g.prs || {}).sort()
  for (const k of prs) {
    const env = g.prs[k]
    const d = env.dados
    if (!d) continue
    const ok = d.checks.filter((c) => dados.checks_obrigatorios.includes(c.nome) && c.conclusao === 'SUCCESS').length
    filhos.push(
      Text({
        dimColor: !env.ok,
        wrap: 'wrap',
        children: ['PR #' + d.numero + ' ' + d.estado.toLowerCase() + ' · checks obrigatórios ' + ok + '/' + dados.checks_obrigatorios.length + ' · ' + quando(env.consultado_em) + (env.ok ? '' : ' (desatualizado)')],
      }),
    )
  }
  return Box({ flexDirection: 'column', children: filhos })
}

export function register(on) {
  // Registra os comandos e carrega os dados; depois relê o arquivo a cada poucos segundos,
  // para o painel acompanhar o que ./acompanhar.sh grava enquanto o Claude trabalha.
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'plano', description: 'Abrir o painel de acompanhamento do plano (pipeline e barras)', immediate: true })
    await $.command.register({ name: 'plano-faixa', description: 'Ligar ou desligar a faixa de progresso acima do prompt', immediate: true })
    faixa = (await $.store.get('faixa')) === true
    await carregar($)
    $.clock.every(4000, async () => {
      if (await carregar($)) $.ui.invalidate('ui.render')
    })
    return next(e)
  })

  on('command.run', { command: 'plano' }, async ($) => {
    await carregar($)
    await $.ui.open({ id: PANE, title: 'Plano', focus: true, closeOnEscape: true })
    return {}
  })

  on('command.run', { command: 'plano-faixa' }, async ($) => {
    faixa = !faixa
    await $.store.set('faixa', faixa)
    $.ui.invalidate('ui.render')
    return { text: faixa ? 'Faixa de progresso ligada.' : 'Faixa de progresso desligada.' }
  })

  // Só observa: registra a atividade do Claude e deixa a ferramenta rodar como sempre.
  on('turn.start', async ($, e, next) => {
    trabalhando = true
    chamadas = 0
    ultimaFerramenta = null
    $.ui.invalidate('ui.render')
    return next(e)
  })

  on('tool.call', async ($, e, next) => {
    chamadas += 1
    ultimaFerramenta = e.tool
    $.ui.invalidate('ui.render')
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    trabalhando = false
    $.ui.invalidate('ui.render')
    return next(e)
  })

  // O painel (um pane aberto por /plano)
  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== PANE) return next(e)
    const E = $.ui.resolve(e)
    const { Box, Text, Button } = E
    const redraw = () => $.ui.invalidate('ui.render')

    const aba = (nome, rotulo, tecla) =>
      Button({
        key: 'aba-' + nome,
        label: rotulo,
        hotkey: tecla,
        plain: true,
        dimColor: abaAtual !== nome,
        onPress: () => {
          abaAtual = nome
          selecionada = null
          redraw()
        },
      })

    if (!dados) {
      return Box({
        flexDirection: 'column',
        children: [
          Text({ color: 'red', wrap: 'wrap', children: [erro || 'Sem dados.'] }),
          Button({ key: 'recarregar', label: 'Tentar de novo', hotkey: 'r', onPress: redraw }),
        ],
      })
    }

    const g = dados.github || {}
    const datas = [
      ...Object.values(g.prs || {}),
      ...(g.main ? [g.main] : []),
      ...Object.values(g.monitores || {}),
    ]
    const desatualizado = datas.some((x) => x.ok === false)
    const t = selecionada ? dados.tarefas.find((x) => x.id === selecionada) : null
    let corpo
    if (abaAtual === 'tarefas') corpo = t ? vistaDetalhe(E, t, redraw) : vistaTarefas(E, redraw)
    else if (abaAtual === 'bloqueios') corpo = vistaBloqueios(E)
    else corpo = vistaPipeline(E)

    return Box({
      flexDirection: 'column',
      children: [
        Box({ flexDirection: 'row', columnGap: 3, children: [aba('pipeline', 'Pipeline', '1'), aba('tarefas', 'Tarefas', '2'), aba('bloqueios', 'Bloqueios', '3')] }),
        Text({ wrap: 'wrap', ...(trabalhando ? { color: 'cyan' } : { dimColor: true }), children: [linhaAgora()] }),
        Text({ children: [' '] }),
        corpo,
        Text({ children: [' '] }),
        Text({ dimColor: true, wrap: 'wrap', children: ['Painel gerado em ' + quando(dados.gerado_em) + (datas.length === 0 ? ' · sem dados do GitHub' : desatualizado ? ' · GitHub desatualizado' : '') + ' · rode ./acompanhar.sh para atualizar'] }),
      ],
    })
  })

  // A faixa acima do prompt (opcional, /plano-faixa): uma linha de progresso sempre à vista
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (!faixa || !dados) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const theirs = await next(e)
    const principal = principais()
    const feitas = principal.filter((t) => t.estado === 'concluida').length
    const r = dados.resumo
    return Box({
      flexDirection: 'column',
      children: [
        theirs,
        Box({
          flexDirection: 'row',
          columnGap: 1,
          children: [
            Text({ bold: true, children: ['Plano'] }),
            barra({ Box, Text }, principal, 1),
            Text({ children: [feitas + '/' + principal.length] }),
            Text({ dimColor: true, wrap: 'truncate', children: [(r.etapa_atual ? '· ' + nomeCurto({ nome: r.etapa_atual.nome }) + ' ' : '') + '· ' + linhaAgora()] }),
          ],
        }),
      ],
    })
  })
}
