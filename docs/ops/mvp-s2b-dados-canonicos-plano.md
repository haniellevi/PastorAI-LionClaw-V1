# S2b: dados oficiais da igreja e células no WhatsApp
Status: APROVADO por Claude + Opencoded e autorizado por Raniel, com ajustes incorporados em 27/09/2026. Base: main `e6aafc296014770ceabc24d5ea6bd9572f33ace4`, conferida em 27/09/2026.
1. Fonte única: `Igreja` guarda endereço institucional e horários de culto; `Celula` guarda os dados da célula. O Agente consulta esses cadastros.
2. Adicionar `Igreja.endereco_institucional` e `Igreja.horarios_culto`, textos opcionais de até 400 caracteres, com validação no backend.
3. Adicionar `Celula.bairro` e `Celula.divulgar_whatsapp` (`false` por padrão); reaproveitar `nome`, `dia_reuniao`, `horario` e `ativo`.
4. Publicar exige célula ativa e bairro preenchido; dia/horário ausentes continuam desconhecidos. Bairro é informado pelo cadastro, nunca extraído de endereço residencial.
5. A projeção pública seleciona somente nome/bairro/dia/horário; nunca seleciona `Celula.endereco`, líder, telefone, anfitrião ou links de localização/grupo para o agente.
6. Esses dados privados não entram em prompt, resposta, candidatos Jev, logs ou auditoria. Manter limites e neutralização de delimitadores nas projeções autorizadas.
7. Criar Configurações > Cadastro da igreja usando o router `/igreja`, com edição pelo admin da própria igreja; preservar Identidade Visual e regras atuais de nome/logo.
8. Em cadastro/edição de célula, agrupar Bairro e “Divulgar no WhatsApp”; o líder edita bairro da própria célula pelo serviço humano; publicação continua exclusiva da Central (pastor/admin).
9. Remover “Informações públicas da igreja” da tela Agente. Manter comportamento/tom/credencial no lugar atual, sem novo formulário duplicado.
10. Nas telas tocadas: título, uma frase de ajuda, grupos claros de campos, uma ação principal e feedback curto; teclado e celular verificados. Redesign global fica para trilha posterior.
11. Criar migration aditiva `AAAAMMDD_HHMMSS_...sql`, com checks, grants/revokes por coluna, RLS existente preservada, `lock_timeout` curto e rollback comentado.
12. `Igreja` é raiz tenant: filtrar `Igreja.id == igreja_id` e policy equivalente; `Celula` usa `igreja_id`. Não adicionar tenant redundante à raiz nem conceder escrita de plano/status/dono.
13. Copiar somente `endereco_igreja` e `horarios_culto` válidos de `agent_configs.informacoes_publicas` para a Igreja correspondente, apenas se destino estiver vazio.
14. Migração preserva valores já cadastrados, JSON legado e divergências para conferência sem PII; não cria células nem libera divulgação a partir do JSON antigo.
15. Manter a coluna legada para futura remoção; após a troca, ela não é fallback de consulta nem destino de gravação. Endpoint antigo fica somente leitura temporariamente.
16. Fazer a troca em janela sem edição do perfil legado, conferindo cópia antes de liberar o cadastro novo; não perder alterações entre migration e deploy.
17. Extrair serviço readonly compartilhado, com contexto de tenant do servidor e RLS; ferramentas públicas leem Igreja e apenas células ativas com divulgação autorizada.
18. Procurar por bairro informado, com limite e ordem estável; sem geolocalização, distância ou inferência de endereço. Revalidar publicação/tenant antes do envio após qualquer espera externa.
19. Sem dado: “Não tenho essa informação cadastrada. Quer falar com a secretaria da igreja?”; nenhum horário, endereço ou célula inventado pelo LLM.
20. Ao indicar célula: oferecer encaminhamento à equipe para conectar ao líder, sem divulgar contato e sem prometer transferência direta que o sistema não fez.
21. Registrar oferta pendente tipada na conversa, vinculada à mensagem de oferta efetivamente enviada, com validade de 10 minutos e consumo único.
22. Confirmação sim/não/expiração roda deterministicamente ANTES do Jev; “sim” só confirma essa oferta vigente; “não”/mudança de assunto cancela. Aceite LGPD não confirma oferta; SAIR, estado humano e gates atuais sempre prevalecem.
23. Confirmada a oferta, reutilizar handoff/fences do inbox, suprimir IA e registrar somente evento sanitizado; não criar tarefa de domínio por saída livre do modelo.
24. `CelulaExpectativaVisitante` exige membro autenticado e vínculo ativo na reunião: permanece no fluxo humano existente, sem contorno para visitante desconhecido.
25. Testar PostgreSQL 17 descartável: migration/backfill idempotente, JSON inválido, destino preenchido, isolamento A/B e grants sem escalada sobre Igreja.
26. Testar API/runtime: célula privada/inativa não aparece; endereço/telefone sentinela ausentes em todas as saídas; ausência de dados; oferta/sim/não/expiração/retry/SAIR/LGPD/handoff.
27. Testar UI: salvar/recarregar cadastro, publicação default off, autorização negada, Agente sem formulário antigo, troca de tenant, acessibilidade e mobile; sem provedores reais no CI.
28. Entregar uma PR S2b com sprint, Wiki e roteiro atualizados; não reclassificar domínio no PRD-COVERAGE sem mudança efetiva de cobertura.
29. S3 fica congelada nos arquivos compartilhados, preservando candidato e evidências; retomar/rebase após definir e integrar a fonte canônica da S2b.
30. Código/PR/CI liberados agora. DEV reconciliado e validado condiciona somente migration/deploy PROD; estes exigem backup/gate nominal próprio. Avisar antes de merge com backend.
31. Backend exige deploy manual com gate próprio; Vercel publica frontend no merge, então a UI usa feature-gate e esconde/desabilita campos novos enquanto a API não oferecer suporte, sem quebrar o backend anterior.
32. Rollback: conter envios e reverter aplicação pelo gate operacional, preservando colunas/dados; não restaurar leitura do legado silenciosamente nem apagar dados migrados.
33. Próximo gate humano: liberação nominal de merge da PR após revisão e CI; nenhuma aprovação de código autoriza migration/deploy. Sem PROD/VPS/banco real/provedores nesta missão.
