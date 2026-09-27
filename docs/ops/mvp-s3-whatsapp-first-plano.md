# S3 revisada: identidade, permissões e ferramentas pelo WhatsApp
Status: proposta para aprovação dos conselheiros; nenhum código autorizado por este documento.
Base: `2e08d11d49868091c88e704b32be80e81fb3ec34` (S2b); compartilha models/runtime/worker. PR426 e seu SQL permanecem congelados.
Referências: PRD0611 delta-046/047/052 e ordem WhatsApp-first do MVP-PLANO; substitui Clerk obrigatório para todo dado não público.
Reusar seletivamente candidato S3 `feat/agent-identity-role-tools` (base `a5244ca`): identidade/API/UI, provas e Choice B/C/D; sem importar em bloco.
O delta de identidade congelado ainda exige revisão independente e PG17; evidência antiga não aprova o novo encaixe.
## Identidade e autoridade
Resolver instância autenticada -> igreja -> inbound persistido -> conversa/telefone normalizado -> Pessoa única da mesma igreja.
Nunca confiar em telefone/tenant/ator/papel enviados no texto ou pelo modelo; sem vínculo continua público, duplicidade/inconsistência vai para humano.
`PrivilegeContext` imutável: exigir AppUser único com vínculo ativo `app_users.pessoa_id`, identidade Clerk válida e `user_roles` do tenant.
Resolver células ativas sob responsabilidade por `celulas.lider_id`; liderança não concede papel por si, nem `Pessoa.tipo` concede autoridade.
Telefone único é identificação operacional de menor confiança, nunca prova forte; troca/revogação/ambiguidade invalida permissões e confirmações.
Revalidar vínculos, papéis, escopo e consentimento por turno, após esperas e antes de executar ou enviar; backend e RLS filtram `igreja_id`.

## Matriz e confirmação
Desconhecido/visitante/sem acesso ativo: somente perfil público Igreja/Celula da S2b e oferta de secretaria; sem cadastro privado.
Membro vinculado: público e próprias consultas operacionais autorizadas pelo serviço humano; nenhuma ação ministerial de terceiros.
Líder: consultas operacionais das suas células; pastor/admin: escopo ministerial que o serviço humano permite na própria igreja.
Ações ministeriais comuns existentes só por líder/pastor/admin com vínculo único e confirmação explícita de cada ação; alvo também autorizado.
Proposta mínima durável: tenant, ator, conversa, ação, alvo e hash de argumentos; resumo confirmado como enviado, TTL de 10 min e uso único.
Aceite determinístico antes do Jev, vinculado à proposta/inbound; não/expiração/mudança cancela, edição pede nova confirmação, retry não duplica.
Uma pendência por conversa; jamais reaproveitar sim de LGPD/secretaria. Versão do termo ou autoridade mudou: cancelar e apresentar fluxo correto.
Executor reutiliza serviço humano, revalida e grava atomicamente; comprovante só após commit. Sem serviço/escopo seguro, negar e encaminhar.
Leituras sensíveis exigem confirmação explícita na sessão válida do painel vinculada ao Clerk, mesma Pessoa/igreja/conversa; nenhum OTP no WhatsApp.
Reusar desafio de 5 min e prova de 15 min do candidato; não chamar JWT local/refresh de nova autenticação Clerk; reler expiração após locks.
Finanças nunca por telefone e ficam fora da S3, mesmo com prova; notas pastorais, conversas privadas e endereço residencial de célula fora do catálogo.

## Integração e verificação
Jev B escolhe intenção; C só após B e catálogo autorizado; D só após C, com handles opacos de candidatos scoped; modelo nunca concede capacidade.
Jev/LLM recebem projeção mínima autorizada, sem telefone, credencial ou texto pastoral; regex é rede mínima, erro/timeout/schema inválido faz handoff.
Flag proposta `AGENT_PRIVILEGE_ENABLED_IGREJA_IDS` vazia; `JEV_ENABLED_IGREJA_IDS`/release S3 continuam inertes. SAIR/humano/LGPD/confirmações precedem Jev.
Ativação Jev depende de DPA/decisão nominal, aceite interno, holdout congelado/metas revisadas e Wilson95; nenhuma chamada real nesta preparação.
Alvo p95 <10s, deadline global de 9s e reserva de 1s; chamadas externas sem lock/transação e métricas sem conteúdo privado.
Arquivos previstos: agent_authz/context/runtime/tools, worker, agent_identity/API/UI, semantic_routing, models, testes e migration própria após aprovação.
Escopo S3: leitura por papel e confirmação mínima dos serviços existentes, sem retomar D2C; V1 relatório/áudio, agenda/lembretes e demais verticais seguem planos próprios.
Testes: telefone duplicado/revogado, contas/roles ambíguos, cross-tenant e intra-tenant, escopo do líder, finanças negadas, Clerk expirado/replay/concorrência.
Testar confirmação antes de Jev, troca de termo/ação/papel, entrega/retry, B->C->D, handles forjados, egress zero; PG17 descartável, Node24/E2E e CI do SHA.
Migration futura datada, aditiva, RLS/ACL/FKs tenant e rollback comentado; revisar o SQL antigo de identidade, sem tocar a migration congelada da S2b.
Rollback: desligar a flag da fatia e reverter código, preservando registros; leitura sensível/ação pendente negada por padrão, sem reenvio automático.
Próximo gate: aprovação deste plano pelos conselheiros; depois PR -> Sarah -> merge autorizado -> deploy com gate próprio, sem DEV/PROD/VPS/provedores aqui.
