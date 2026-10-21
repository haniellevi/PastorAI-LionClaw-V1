import { afterEach, expect, it, vi } from 'vitest';
import { atribuirResponsabilidade, encerrarResponsabilidade, hojeSaoPaulo, listarResponsabilidades, vigencia, type Responsabilidade } from './responsabilidades-api';
import { canSee } from './permissions';
const transport = vi.hoisted(() => vi.fn());
vi.mock('./dashboard-api', async original => ({ ...await original<object>(), authedFetch: transport }));
afterEach(() => vi.clearAllMocks());
it('envia filtro/paginação e mutações autenticadas sem excluir histórico', async () => {
 transport.mockResolvedValue(new Response('[]', { status: 200 }));
 await listarResponsabilidades('fake', { setor: 'agenda', offset: 25 });
 expect(transport).toHaveBeenCalledWith('fake', '/responsabilidades?limit=26&offset=25&setor=agenda', { signal: undefined });
 transport.mockImplementation(async () => new Response('{}', { status: 200 }));
 await atribuirResponsabilidade('fake', { pessoa_id: 'synthetic', setor: 'agenda', inicio: '2026-10-21', fim: null });
 expect(transport).toHaveBeenLastCalledWith('fake', '/responsabilidades', expect.objectContaining({ method: 'POST' }));
 await encerrarResponsabilidade('fake', 'synthetic', '2026-10-22');
 expect(transport).toHaveBeenLastCalledWith('fake', '/responsabilidades/synthetic/encerrar', expect.objectContaining({ method: 'POST', body: '{"fim":"2026-10-22"}' }));
});
it('propaga o erro de domínio sem anunciar sucesso', async () => {
 transport.mockResolvedValue(new Response('{"detail":"Fim não pode ser retroativo"}', { status: 422 }));
 await expect(encerrarResponsabilidade('fake', 'synthetic', '2026-01-01')).rejects.toThrow('Fim não pode ser retroativo');
});
it('respeita a virada do dia em São Paulo e o fim exclusivo', () => {
 expect(hojeSaoPaulo(new Date('2026-10-21T02:59:59Z'))).toBe('2026-10-20');
 expect(hojeSaoPaulo(new Date('2026-10-21T03:00:00Z'))).toBe('2026-10-21');
 const row = { inicio: '2026-10-21', fim: '2026-10-23' } as Responsabilidade;
 expect(vigencia(row, '2026-10-20')).toBe('Programada');
 expect(vigencia(row, '2026-10-21')).toBe('Vigente');
 expect(vigencia(row, '2026-10-23')).toBe('Encerrada');
});
it('mostra a tela a pastor com matriz existente da Central; rejeita concessão a membro', () => {
 expect(canSee('responsabilidades', ['pastor'], { pastor: ['central-celula'] })).toBe(true);
 expect(canSee('responsabilidades', ['pastor'], { pastor: ['dashboard'] })).toBe(false);
 expect(canSee('responsabilidades', ['membro'], { membro: ['responsabilidades'] })).toBe(false);
 expect(canSee('responsabilidades', ['admin'], {})).toBe(true);
});
