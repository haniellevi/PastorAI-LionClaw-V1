# V3: consolidação pelo WhatsApp, proposta para aprovação
Base histórica do plano: PR435 `342f0ced7af53d2d7e708d99e3b92d54e7a3e22c`; aprovado pelos conselheiros com ajuste de privacidade. A PR436 foi retargetada para main após o merge #435; CI e revisão Sarah da composição continuam gates separados.
Fontes: PRD0611 delta-052/RF-D6/RF-43/RF-46, plano MVP, S3 e outbox V2b.
1. Objetivo: decisão confirmada abre consolidação; equipe acompanha pendências e confirma ações pelo WhatsApp.
2. Reusar `register_decision` e o trigger canônico: visitante gera conexão em 24h; pessoa já vinculada conserva o fluxo sem esse prazo.
3. Garantir uma pendência canônica de fonovisita por nova consolidação, na mesma transação; não duplicar consolidação aberta, decisão ou pendência em replay; totais agregados do relatório V1 não identificam pessoas nem geram decisões individuais.
4. Identidade: PrivilegeContext servidor, telefone único, Pessoa/AppUser ativos, papéis e escopo atuais; ambiguidade ou revogação leva a humano.
5. Catálogo fechado: `consultar_pendencias_consolidacao`, `marcar_fonovisita_feita`, `atribuir_consolidacao`; preservar `registrar_decisao` S3.
6. Consulta: apenas pendências autorizadas pela fila humana; responsável vê suas tarefas; lider_consol/pastor/admin respeitam o escopo existente.
7. Somente ao responsável atualmente atribuído, com identidade S3 revalidada na consulta e antes do HTTP: primeiro nome normalizado + tipo + prazo, sempre 1:1, nunca grupo; nome só no template, fora do LLM.
8. Coordenação sem atribuição recebe apenas contagens/códigos opacos vinculados a ator/tenant. Telefone, sobrenome e contexto ficam no painel com Clerk e link curto autenticado, sem PII na URL; código/link nunca concede acesso.
9. Fonovisita feita: somente responsável autorizado confirma a etapa canônica e baixa sua pendência, atomicamente; não conclui toda a consolidação.
10. Atribuir: lider_consol/pastor/admin, destino ativo da própria igreja e elegível; sincronizar responsável da consolidação e tarefas abertas sob lock, recusando proposta desatualizada.
11. A atribuição distribui trabalho; não altera papel, permissão ou vínculo da Pessoa com célula. Esses vínculos e conclusão geral ficam fora desta fatia.
12. Extrair as operações humanas de `pipeline`/`work_queue` para serviços compartilhados sem commit interno; web e WhatsApp usam a mesma autorização, transação e auditoria.
13. S3 para toda escrita: ator/alvo/versão/hash de args, resumo efetivamente enviado, SIM determinístico antes do roteador, TTL 10min, uso único e comprovante somente pós-commit.
14. Roteador LLM da igreja recebe enum fechado e handles; timeout/schema inválido vira handoff. Supressão crise/opt-out permanece; Jev B/C/D inertes.
15. Alertas só à equipe autorizada: responsável atual ou coordenação elegível quando sem atribuição; resolver destinatários ativos no servidor e revalidar antes do envio.
16. Conectar em 24h: aviso na abertura e, se ainda pendente, no prazo persistido; fonovisita: aviso na criação da pendência, sem inventar outro SLA.
17. Sem destinatário elegível, manter a pendência visível na fila; nunca escolher pessoa arbitrária nem alertar o visitante automaticamente.
18. Usar apenas `notification_outbox` e dispatcher V2b; unicidade igreja+destinatário+ocorrência+finalidade, sem produtor/consumidor alternativo.
19. Janela 08:00–21:00 São Paulo; teto proposto de 2 avisos V3 por destinatário/dia, contando enviado/ambíguo; excedente permanece na fila, sem rajada posterior.
20. Cada aviso vence em 24h após seu instante previsto; fora da janela adiar dentro desse limite, sem renovar prazo nem prometer atendimento dentro do SLA.
21. Pendência resolvida/arquivada ou atribuição alterada cancela intenção inelegível; claim/lease com commit antes do HTTP, revalidação final e ambíguo sem reenvio.
22. LGPD: termo existente versionado, timestamp/revogação e preferência explícita de lembretes da equipe; sem inferir aceite pelo papel, sem E4B/mint/bypass; ilegível bloqueia.
23. Aviso curto na primeira mensagem; PARAR LEMBRETES e SAIR globais prevalecem; retirada cancela pendentes e propostas de reativação anteriores.
24. Cutover prospectivo: pendências antigas continuam consultáveis, mas não geram alertas retroativos; marco durável de ativação e nenhuma reconstrução de recibos.
25. Persistência: migration aditiva/idempotente para finalidades/referências e idempotência necessárias, FKs tenant, RLS/grants mínimos sem DELETE; preservar migrations congeladas.
26. Auditoria sem conteúdo: ator, ação, códigos técnicos, resultado e comprovante; exclusão de Pessoa alcança propostas/derivados conforme o contrato existente.
27. Gates cumulativos: `CONSOLIDATION_WHATSAPP_ENABLED_IGREJA_IDS` vazia, `CONSOLIDATION_WHATSAPP_APPROVED_RELEASE_ID=None`, `CONSOLIDATION_NOTIFY_ENABLED=false` tipado, S3, agente ativo, piloto e ALLOW_REAL_SENDS.
28. Implementação não ativa envio: ativação nominal e release em lote com backup/migration/backend/frontend têm gates próprios; nenhum DPA/egress Jev é aberto.
29. E2E por capacidade: inbound persistido → identidade/catálogo/roteador reais → consulta ou resumo/SIM → serviço/RLS → resposta/comprovante persistido; providers simulados.
30. PG17: decisão→consolidação/24h, fonovisita/baixa, atribuição concorrente, replay/TTL, cross-tenant, papel revogado, código adulterado, PII ausente e rollback integral.
31. E2E por finalidade: alertas de abertura/prazo/fonovisita, preferência/SAIR/PARAR, mudança de responsável, janela/quota, lease/HTTP e ambiguidade; nomes no log rls-integration.
32. Rollback: fechar gates V3, cancelar elegibilidade pendente e preservar histórico; nunca reativar transportes antigos. Fora: UV/CD, finanças, áudio novo e redesign.
Próximo gate humano: Sarah revisar o candidato V3 após implementação/CI; merge e release continuam sujeitos aos gates próprios.
