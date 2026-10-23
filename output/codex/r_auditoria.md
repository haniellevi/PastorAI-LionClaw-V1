# Auditoria de segurança, tarefa C

Base conferida: `origin/main` em `ef54f9c107305801c9633ddcf2d4d9b0102457de`.

| Achado | Ainda existe em main? Evidência | Severidade | Tratamento nesta branch |
|---|---|---|---|
| Token em query string no access log | Sim. `backend/app/routers/whatsapp.py:339, 344-353`; Uvicorn padrão em `deploy/docker-compose.yml:134` registra o alvo da requisição. | P1 | Corrigido. Filtro de `uvicorn.access` mascara todos os valores da query; formato de log desconhecido é descartado. |
| Escopo de igreja em cron/SLA | Sim. `backend/app/workers/cron_worker.py:136-155` lê crons ativos globalmente e executa SLA na mesma sessão; `backend/app/services/sla_engine.py:481-503` faz descoberta cross-tenant sem marca explícita. | P1 | Corrigido. Descoberta nomeada retorna somente `igreja_id`; leitura dos crons e ação SLA usam sessão nova, marcada por igreja e consulta com filtro explícito. |
| MFA no console | Sim. `backend/app/routers/platform_admin.py:238-263` autentica senha e retorna o JWT PastorAI; `backend/app/services/clerk.py:144-171` emite e verifica esse JWT sem prova MFA. | P1 | Pendente de configuração e integração do dono. No Clerk Dashboard, abrir User & authentication > Multi-factor authentication, habilitar os fatores aprovados, ativar Require multi-factor authentication e salvar. O login customizado ainda precisa validar a etapa MFA antes de emitir a sessão. Nenhuma configuração externa foi alterada. |
| Logout sem revogação no servidor | Sim. `frontend/src/lib/auth-context.tsx:300-314` e `frontend/src/lib/admin-auth-context.tsx:147-153` limpam apenas o estado local; o JWT não tem identificador de sessão revogável em `backend/app/services/clerk.py:144-171`. | P1 | Documentado, sem mudança de código. O modelo atual não guarda revogação por sessão; `password_changed_at` revoga tokens em nível de usuário e não serve para logout individual. |

## Verificação

43 testes passaram, incluindo o teste PostgreSQL sem skip em banco descartável local com duas igrejas sintéticas. Um aviso existente de depreciação do Starlette permanece. `git diff --check` passou. Gates permaneceram fechados; sem produção, deploy ou banco remoto.
