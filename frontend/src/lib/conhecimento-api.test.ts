import { afterEach, expect, it, vi } from 'vitest';
import { conhecimento } from './conhecimento-api';
import { SessionExpiredError } from './api';
afterEach(() => vi.unstubAllGlobals());
it('envia token e corpo sem cache para o serviço editorial', async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ acao: 'criar' }), { status: 200 }));
  vi.stubGlobal('fetch', fetch);
  const payload = { operacao_id: 'synthetic-operation', titulo: 'Guia fictício' };
  await expect(conhecimento('synthetic', 'documentos', payload)).resolves.toEqual({ acao: 'criar' });
  expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/conhecimento/documentos'), expect.objectContaining({
    method: 'POST', cache: 'no-store', body: JSON.stringify(payload),
    headers: { Authorization: 'Bearer synthetic', 'Content-Type': 'application/json' },
  }));
});
it('propaga sessão expirada e recusa sem conceder capacidades locais', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(new Response('{}', { status: 401 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Sem permissão editorial' }), { status: 403 }));
  vi.stubGlobal('fetch', fetch);
  await expect(conhecimento('synthetic', 'documentos')).rejects.toBeInstanceOf(SessionExpiredError);
  await expect(conhecimento('synthetic', 'documentos')).rejects.toMatchObject({ status: 403, message: 'Sem permissão editorial' });
});
