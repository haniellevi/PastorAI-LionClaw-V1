# V1a: aceite do candidato por texto

Base congelada f2a532a; implementação autorizada em branch própria. Esta matriz é um roteiro de teste, não evidência de execução. Somente fixtures sintéticas e PostgreSQL17 loopback descartável; provedores simulados.

| Fluxo | Resultado exigido |
|---|---|
| Env preenchida, release None; flags vazias; agente parado | Nenhuma query V1a dependente de schema, LLM, envio ou efeito |
| LGPD ausente, ilegível, timestamp inválido, versão velha, revogação posterior/qualquer empate terminal | Nenhum lembrete, extração externa ou gravação; aceite geral não cria finalidade E4B |
| Líder ativo único da célula e reunião elegível | Somente dados da própria igreja/célula, sem tenant/ator/alvo fornecidos pelo modelo |
| Texto com quatro campos; campos faltantes; números negativos/fração/overflow | Proposta tipada validada, pedir lacunas sem inventar zero, sem lançar finanças ou consolidar pessoas |
| Correção do resumo; SIM anterior à entrega; SIM após dez minutos; NÃO | Apenas última revisão entregue pode executar; correção invalida resumo anterior; hash do conteúdo deve conferir antes de corrigir e executar; expiração/cancelamento sem efeito |
| Dois SIM simultâneos; retry após commit; gravação humana concorrente | Um efeito e comprovante durável, conflito seguro e transação atômica |
| Commit falha; transporte falha ou retorna ambíguo | Sem comprovante de sucesso antes do commit; transporte não repete efeito nem envio ambíguo |
| Lembrete +2h,08h-21h SãoPaulo, reunião velha/cancelada/enviada, vários cron concorrentes | Dedup por reunião/líder, máximo um/líder24h, sem catch-up em massa |
| Aviso inicial, PARAR LEMBRETES, SAIR, humano, papel/telefone/termo revogado após claim | Preferência/aviso registrados; supressão revalidada antes do envio e confirmação |
| Quatro extrações, budget concorrente, custo desconhecido/estourado, retry | Reserva atômica limita gasto; falha fechada sem chamada; custo mínimo auditável sem payload |
| Rascunho24h, proposta expirada, reset/exclusão | Conteúdo transitório purgado e nenhuma ressurreição; relatório confirmado e histórico privado têm políticas distintas |
| RLS/ACL/FK/SQL idempotente | Cruzamento entre igrejas/atores negado; SQL próprio aplicado duas vezes sem perder dados; SQL426/428 byte-idênticos |

V1b não faz parte desta prova. Não há áudio real, ativação, DEV/PROD/VPS ou declaração de qualidade/latência real de LLM. Próximo gate humano: Sarah revisar o candidato exato após testes/CI.
