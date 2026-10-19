// @vitest-environment jsdom
import { act, createElement as h } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import type { Conversation, PrivateDeletionReceipt } from '@/lib/conversations-api';
import { DeleteConversationDialog } from './DeleteConversationDialog';

it.each([
  ['pendente', 'Exclusão pendente: limpeza de mídia'],
  ['pendente_envio', 'Exclusão pendente: envio em andamento'],
  ['concluido', 'Exclusão concluída'],
] as const)('mostra recibo %s sem mensagens e permite atualização', (estado, label) => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement('div'); document.body.appendChild(container);
  const root = createRoot(container);
  const refresh = vi.fn();
  const receipt: PrivateDeletionReceipt = {id:'synthetic-receipt',estado,camadas:{midias:{encontradas:1,apagadas:0,pendentes:1,falhas:1}}};
  try {
    act(()=>root.render(h(DeleteConversationDialog,{conversation:{id:'c',nome:'Contato fictício',telefone:'5500000000000'} as Conversation,busy:false,error:null,onCancel:vi.fn(),onConfirm:vi.fn(),receipt,onRefresh:refresh})));
    expect(container.querySelector('[role="status"]')?.textContent).toContain(label);
    expect(container.textContent).toContain('1 pendentes; 1 falhas');
    expect(container.textContent).toContain('não cobre backups');
    const buttons=[...container.querySelectorAll('button')];
    expect(buttons.some(button=>button.textContent?.includes('Excluir conversa'))).toBe(false);
    act(()=>buttons.find(button=>button.textContent?.includes('Atualizar recibo'))!.click());
    expect(refresh).toHaveBeenCalledOnce();
  } finally { act(()=>root.unmount());container.remove(); }
});
