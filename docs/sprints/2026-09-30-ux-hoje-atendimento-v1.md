# Hoje e atendimento humano: UX v1

Conjunto visual aprovado por Raniel em 30/09/2026, com avanço da formalização
local autorizado após a prévia. Base atualizada:
`226fa6b85dad3f30e400f8ecf8396412571d6c2a`.

Rascunho preservado em falhas e trocas de conversa, envio concorrente bloqueado,
scroll conservado durante leitura, histórico com erro explícito, lista paginada
com cobertura parcial e responsabilidade humana visível. Hoje explicita suas
pendências. Tokens/rotas/capacidades e contratos backend permanecem intactos.

951 testes frontend passaram em 104 arquivos, sob Node 24.19.0. Build local
Next 15.5.25 passou. QA visual usa apenas mock em loopback; zoom de 200%, leitor
de tela e integração com backend/provedor não foram verificados.

[Registro de aprovação, QA, reprodução e rollback](../design/2026-09-30-ux-hoje-atendimento-v1.md).
Raniel autorizou produção em 30/09 e solicitou avaliação com Sites. O ajuste
adicional anuncia o carregamento completo e conserva foco de teclado na busca
quando o botão da última página desaparece, sem roubar foco de outro campo.
O teste negativo falhou antes da correção. Aparência e hospedagem preservadas.
Publicação frontend autorizada, condicionada ao CI e ao SHA exato. Sem banco
compartilhado, deploy backend, alteração de gates ou envio real.

PR #445: timeout inicial do histórico também mostra erro e retry, conforme
achado P2 da revisão automática. Teste negativo falhou antes do patch; teste
de troca de conversa confirma que cancelamento não vira timeout da visita nova.

Publicado em 30/09, 19:27 UTC (16:27 BRT): PR #445 integrada com merge commit
`363ecb5fecb2fb81a52a14577555b9f281eef7ca`, pais `226fa6b` e `76df51f`.
Os cinco checks obrigatórios passaram no candidato `76df51f`; branch preservada.
Vercel `dpl_4juA4wN6JMVQCJekLa7mqj3wZM65` READY, target production, SHA do merge,
aliases app/admin/painel.igreja12.com.br. Os três domínios e health/ready da API
responderam HTTP 200 sem cookies; assets públicos apontam api.igreja12.com.br.
Rollback: `dpl_BDsG4TXaEM19J6BFPnSAYQi1gN4a` (`226fa6b`). Sem deploy backend,
banco, mudança de gates ou envios. Atendimento autenticado em PROD não exercitado.
