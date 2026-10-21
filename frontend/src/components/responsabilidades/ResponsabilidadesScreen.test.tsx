// @vitest-environment jsdom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { ResponsabilidadesScreen } from './ResponsabilidadesScreen';
import { ApiError } from '@/lib/dashboard-api';
const mocks = vi.hoisted(() => ({ list: vi.fn(), assign: vi.fn(), end: vi.fn(), roles: ['pastor'], expire: vi.fn() }));
vi.mock('@/lib/auth-context', () => ({ useAuth: () => ({ token: 'synthetic', user: { roles: mocks.roles }, expireSession: mocks.expire }) }));
vi.mock('@/lib/responsabilidades-api', async original => ({ ...await original<object>(), listarResponsabilidades: mocks.list, atribuirResponsabilidade: mocks.assign, encerrarResponsabilidade: mocks.end }));
vi.mock('@/lib/contacts-api', () => ({ fetchContactDetail: vi.fn().mockResolvedValue({ nome: 'Pessoa sintética' }) }));
vi.mock('@/lib/lookup-api', () => ({ fetchContactLookupPage: vi.fn().mockResolvedValue({ items: [{ id: 'p1', nome: 'Pessoa sintética', arquivada: false }, { id: 'p2', nome: 'Pessoa arquivada', arquivada: true }], total: 2, page: 1, pageSize: 25 }) }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const row = { id: 'r1', pessoa_id: 'p1', setor: 'agenda', inicio: '2026-01-01', fim: null, encerrada_em: null };
let host: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
beforeEach(() => { vi.useFakeTimers({ toFake: ['Date'] }); vi.setSystemTime(new Date('2026-10-21T01:00:00Z')); mocks.roles = ['pastor']; mocks.list.mockResolvedValue([row]); host = document.createElement('div'); document.body.append(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); vi.useRealTimers(); });
const render = async () => { await act(async () => root.render(<ResponsabilidadesScreen />)); };
const button = (text: string) => [...host.querySelectorAll('button')].find(b => b.textContent === text)!;
function change(selector: string, value: string) { const el = host.querySelector<HTMLInputElement>(selector)!; act(() => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value); el.dispatchEvent(new Event('input', { bubbles: true })); }); }
it('lista histórico e vigência, informa fim exclusivo e usa hoje em São Paulo', async () => {
 await render(); expect(host.textContent).toContain('Vigente'); expect(host.textContent).toContain('primeiro dia sem responsabilidade');
 await act(async () => button('Encerrar').click());
 expect(host.querySelector<HTMLInputElement>('#encerrar-fim')!.min).toBe('2026-10-20');
});
it('atribui Pessoa ativa e preserva erro de conflito do servidor', async () => {
 mocks.assign.mockRejectedValue(new ApiError(409, 'Setor já possui responsável no período'));
 await render(); await act(async () => button('Nova atribuição').click());
 expect(button('Pessoa arquivada').disabled).toBe(true);
 await act(async () => button('Pessoa sintética').click());
 change('#atribuir-inicio', '2026-10-21');
 await act(async () => host.querySelector('form')!.requestSubmit());
 expect(mocks.assign).toHaveBeenCalledWith('synthetic', { pessoa_id: 'p1', setor: 'atendimento', inicio: '2026-10-21', fim: null });
 expect(host.querySelector('[role="alert"]')?.textContent).toContain('Setor já possui');
});
it('encerra com confirmação explícita e recarrega o histórico', async () => {
 mocks.end.mockResolvedValue({ ...row, fim: '2026-10-21' });
 await render(); await act(async () => button('Encerrar').click()); change('#encerrar-fim', '2026-10-21');
 await act(async () => host.querySelector('form')!.requestSubmit());
 expect(mocks.end).toHaveBeenCalledWith('synthetic', 'r1', '2026-10-21'); expect(mocks.list).toHaveBeenCalledTimes(2);
 expect(host.textContent).toContain('Encerramento registrado');
});
it('não consulta nem mostra ações para membro', async () => { mocks.roles = ['membro']; await render(); expect(mocks.list).not.toHaveBeenCalled(); expect(host.querySelector('button')).toBeNull(); });
it('nega ações após 403 do servidor mesmo com papel local pastor', async () => { mocks.list.mockRejectedValue(new ApiError(403, 'Sem permissão')); await render(); expect(host.querySelector('form')).toBeNull(); expect(host.textContent).not.toContain('Nova atribuição'); });
it('oferece recuperação de erro e estado vazio', async () => { mocks.list.mockRejectedValueOnce(new Error('Falha sintética')).mockResolvedValueOnce([]); await render(); expect(host.querySelector('[role="alert"]')).not.toBeNull(); await act(async () => button('Tentar novamente').click()); expect(host.textContent).toContain('Nenhuma responsabilidade'); });
it('pagina sem truncar histórico e filtra setor desde o início', async () => { mocks.list.mockResolvedValue(Array.from({ length: 26 }, (_, i) => ({ ...row, id: `r${i}` }))); await render(); expect(host.querySelectorAll('article')).toHaveLength(25); await act(async () => button('Próxima').click()); expect(mocks.list).toHaveBeenLastCalledWith('synthetic', { setor: '', offset: 25 }, expect.any(AbortSignal)); const select = host.querySelector<HTMLSelectElement>('#filtro-setor')!; await act(async () => { select.value = 'agenda'; select.dispatchEvent(new Event('change', { bubbles: true })); }); expect(mocks.list).toHaveBeenLastCalledWith('synthetic', { setor: 'agenda', offset: 0 }, expect.any(AbortSignal)); });
it('anuncia carregamento e ignora resposta antiga após mudar o filtro', async () => {
 let finish!: (rows: unknown[]) => void;
 mocks.list.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; })).mockResolvedValueOnce([]);
 await render(); expect(host.textContent).toContain('Carregando responsabilidades');
 const select = host.querySelector<HTMLSelectElement>('#filtro-setor')!;
 await act(async () => { select.value = 'agenda'; select.dispatchEvent(new Event('change', { bubbles: true })); });
 await act(async () => finish([row]));
 expect(host.textContent).toContain('Nenhuma responsabilidade'); expect(host.querySelector('article')).toBeNull();
});
it('remove ações quando a autorização é revogada durante a escrita', async () => {
 mocks.end.mockRejectedValue(new ApiError(403, 'Vínculo revogado'));
 await render(); await act(async () => button('Encerrar').click()); change('#encerrar-fim', '2026-10-21');
 await act(async () => host.querySelector('form')!.requestSubmit());
 expect(host.textContent).toContain('Acesso restrito'); expect(host.querySelector('button')).toBeNull();
});
