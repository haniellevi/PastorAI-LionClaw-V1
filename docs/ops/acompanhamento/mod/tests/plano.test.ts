import { expect, mock, test } from 'claude-code/testing'

// Dados mínimos no formato que ./acompanhar.sh grava em dados.js
const ind = (status: string) => ({ status, nota: '' })
const indicadores = (s: string) => ({
  implementacao: ind(s),
  validacao_local: ind(s),
  ci: ind(s),
  integracao_main: ind('pendente'),
  publicacao_dev: ind('nao_aplicavel'),
  publicacao_prod: ind('nao_aplicavel'),
})
const tarefa = (id: string, fase: string, sequencia: number, estado: string, rotulo: string, extra = {}) => ({
  id,
  titulo: 'Tarefa ' + id,
  fase,
  trilha: 'principal',
  sequencia,
  estado,
  estado_rotulo: rotulo,
  situacao: rotulo,
  objetivo: 'Objetivo de ' + id,
  proxima_acao: 'Próxima ação de ' + id,
  depende_de: [],
  prs: [],
  evidencias: [],
  indicadores: indicadores(estado === 'concluida' ? 'ok' : 'nao_iniciado'),
  ...extra,
})

const DADOS = {
  gerado_em: '2026-10-09T12:00:00-03:00',
  checks_obrigatorios: ['backend-tests'],
  estados: { futura: 'Futura', pronta: 'Pronta', em_andamento: 'Em andamento', em_validacao: 'Em validação', bloqueada: 'Bloqueada', concluida: 'Concluída' },
  fases: [
    { id: 'A', nome: 'Preparação: dependências', trilha: 'principal', ordem: 1 },
    { id: 'B', nome: 'F2a · Transporte simulado', trilha: 'principal', ordem: 2 },
  ],
  tarefas: [
    tarefa('T1', 'A', 1, 'em_validacao', 'Em validação', { situacao: 'Validado — aguardando integração', aguardando: 'Integração pelo proprietário' }),
    tarefa('T2', 'B', 2, 'bloqueada', 'Bloqueada', { bloqueio: 'Depende do T1' }),
  ],
  github: { prs: {}, monitores: {} },
  resumo: {
    etapa_atual: { fase: 'A', nome: 'Preparação: dependências', tarefa: 'T1', situacao: 'Validado — aguardando integração' },
    proxima_executavel: null,
    bloqueios: [{ id: 'T2', titulo: 'Tarefa T2', motivo: 'Depende do T1' }],
    esperas: [{ id: 'T1', titulo: 'Tarefa T1', motivo: 'Integração pelo proprietário' }],
  },
}
const TEXTO = 'window.PAINEL_DADOS = ' + JSON.stringify(DADOS) + ';\n'

const PANE = {
  plugin: 'acompanhamento-plano',
  component: 'Pane',
  requestId: 'plano',
  viewport: { columns: 120, rows: 40 },
  props: { title: 'Plano', isFocused: true, bodyColumns: 80, placement: 'inline', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

// Responde as chamadas que o mod faz ao Claude Code durante o session.start
function preparar(on: any, arquivo: string | null, salvo: Map<string, unknown> = new Map()) {
  mock.clock(on)
  on('session.root', () => ({ value: '/work' }))
  on('fs.exists', () => ({ value: arquivo !== null }))
  on('fs.read', () => ({ value: arquivo ?? '' }))
  on('command.register', () => ({ value: undefined }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', ($: any, e: any) => {
    salvo.set(e.key, e.value)
    return { value: undefined }
  })
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', () => ({ cwd: '/work' }))
}

test('o painel mostra o pipeline e o texto "Validado — aguardando integração" nos dois apps', async ($, on) => {
  preparar(on, TEXTO)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect(await ui.find({ type: 'Text', text: /0 de 2 tarefas da sequência principal concluídas/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /Etapa atual: Preparação: dependências/ })).toBeDefined()
    await ui.unmount()
  }
})

test('as abas trocam a vista e a tarefa abre os detalhes', async ($, on) => {
  preparar(on, TEXTO)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  await ui.press({ key: 'aba-bloqueios' })
  expect(await ui.find({ type: 'Text', text: /T2 · Tarefa T2 — Depende do T1/ })).toBeDefined()
  await ui.press({ key: 'aba-tarefas' })
  await ui.press({ key: 't-T2' })
  expect(await ui.find({ type: 'Text', text: /Bloqueio: Depende do T1/ })).toBeDefined()
  await ui.press({ key: 'voltar' })
  expect(await ui.find({ key: 't-T2' })).toBeDefined()
  await ui.unmount()
})

test('/plano abre o painel e avisa quando o dados.js não existe', async ($, on) => {
  preparar(on, null)
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.command.run({ command: 'plano', args: '' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /dados.js não encontrado/ })).toBeDefined()
  await ui.unmount()
})

test('a atividade do Claude aparece no painel e a ferramenta segue o caminho normal', async ($, on) => {
  preparar(on, TEXTO)
  on('turn.start', ($, e) => ({ turnId: e.turnId }))
  on('tool.call', () => ({ result: 'ok' }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  await $.turn.start({ turnId: 't1' })
  const resposta = await $.tool.call({ tool: 'Edit', file_path: 'a.md' })
  // O mod só observa: a resposta é a do stub, sem alteração
  expect(resposta).toEqual({ result: 'ok' })
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' })
  expect(await ui.find({ type: 'Text', text: /Claude: trabalhando · última ferramenta: Edit · 1 chamadas/ })).toBeDefined()
  await ui.unmount()
})

test('/plano-faixa liga a faixa e guarda a escolha', async ($, on) => {
  const salvo = new Map<string, unknown>()
  preparar(on, TEXTO, salvo)
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['desenho do Claude Code'] }))
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })
  const resposta = await $.command.run({ command: 'plano-faixa', args: '' })
  expect(resposta.text).toBe('Faixa de progresso ligada.')
  expect(salvo.get('faixa')).toBe(true)
  const ui = await $.ui.mount({
    plugin: 'acompanhamento-plano',
    component: 'AbovePrompt',
    requestId: 'faixa',
    surface: 'terminal',
    viewport: { columns: 120, rows: 40 },
    props: { hasSurvey: false, isWorking: false, maxRows: 5, bodyColumns: 100, scroll: { offset: 0, bodyRows: 5 }, view: {} },
  } as any)
  expect(await ui.find({ type: 'Text', text: 'Plano' })).toBeDefined()
  await ui.unmount()
})
