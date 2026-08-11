# Decisões pendentes

Nenhuma destas escolhas deve ser resolvida por implementação silenciosa.

## D01. Quem é o admin principal

**Problema:** `dono` protege assinatura, mas credencial/modelo, WhatsApp e outras ações sensíveis aceitam qualquer admin.

**Recomendação:** formalizar owner/admin principal, separado de pastor principal e master da plataforma.

**Bloqueia:** governança do agente, WhatsApp, permissões e comunicação real.

## D02. Quem lidera Ganhar

**Problema:** líder de célula possui acesso amplo no estado atual, mas o usuário definiu que a vinculação pertence à liderança de Ganhar.

**Opções:**

1. responsabilidade `lider_ganhar` configurável;
2. liderança de consolidação acumula Ganhar;
3. pastor/admin até existir equipe específica.

**Recomendação:** responsabilidade configurável, com escopo de fila, não novo enum imediato.

## D03. Pastor pode administrar Pessoas e acessos

**Problema:** a superfície `/gestao` é admin-only. A visão do usuário cita pastor/admin em alguns contextos.

**Recomendação:** separar diretório pastoral escopado de diretório administrativo completo. Pastor não recebe gestão de acesso por padrão.

## D04. Responsabilidades customizadas

**Problema:** CRUD de papéis pode inflar o enum de segurança.

**Recomendação:** papéis-base estáveis e responsabilidades/cargos configuráveis com capacidades e escopos.

## D05. Pastor principal

**Problema:** proprietário da conta não representa pastor principal.

**Recomendação:** campo e fluxo ministerial próprios, com vigência e auditoria.

## D06. Conteúdo educativo em área restrita

**Problema:** esconder tudo é seguro, mas pode perder oportunidade de ensino.

**Recomendação:** conteúdo público aprovado em Enviar e etapas semelhantes; ocultar quando não houver conteúdo seguro. Dados e ações continuam restritos.

## D07. Configuração local do agente

**Problema:** comportamento é controlado pelo master e admin solicita ajustes; credencial e modelo são locais.

**Opções:**

1. master controla comportamento, owner local controla credencial/modelo;
2. master controla tudo;
3. owner local recebe instruções limitadas e versionadas.

**Recomendação:** opção 1 no curto prazo. Avaliar opção 3 depois de auditoria e rollback.

## D08. Evolution e Meta Cloud API

**Problema:** o produto usa Evolution, não integração direta Meta Cloud API.

**Recomendação:** dizer `número oficial da igreja conectado via Evolution`. Avaliar Meta em discovery próprio, sem prometer compatibilidade atual.

## D09. Consentimento para comunicação proativa

**Problema:** primeira mensagem recebida hoje pode tornar o contato elegível para broadcast.

**Recomendação:** separar atendimento, cadastro, cuidado e comunicação proativa. Submeter a política final a validação jurídica.

## D10. Revisão cadastral semestral

**Problema:** frequência e lembrete são desejados, mas podem gerar fadiga.

**Recomendação:** revisão diferencial, perguntando primeiro se algo mudou. Definir canais, janela, número de tentativas e opt-out.

## D11. Agenda abre em Semana ou Mês

**Problema:** documento antigo pede Semana; produto abre em Mês.

**Recomendação:** teste com usuários. Pastor e secretaria podem preferir Semana; membro pode preferir próximos eventos, não calendário.

## D12. Aba Planejamento

**Problema:** a especificação pede uma quinta aba, mas ela não existe.

**Recomendação:** manter no roadmap P1 somente se testes confirmarem utilidade. Começar com pendências da semana, não IA generativa.

## D13. Google Calendar, direção e controle

**Problema:** importação atual é Google para app. O documento sugere sincronização completa e acesso pastor/admin.

**Recomendação:** declarar direção atual, definir fonte de verdade, conflito e owner/admin principal antes de bidirecionalidade.

## D14. Evento confirmado versus comunicado

**Problema:** audiência, tempo e mensagem são persistidos, mas a entrega não existe.

**Recomendação:** ações separadas e linguagem honesta. O dispatcher só entra depois de consentimento e outbox.

## D15. Visitante da célula

**Problema:** a UI registra nome, enquanto o domínio possui espaço para telefone e a visão pede decisão por Cristo.

**Recomendação:** coletar telefone com consentimento, localizar ou criar Pessoa idempotentemente e gerar Ganhar/Consolidar conforme evento real.

## D16. Métricas da Central

**Problema:** o dashboard possui contadores operacionais, mas a visão pede indicadores agregados.

**Recomendação:** validar frequência de uso de total de células, relatórios, visitantes, participantes e cobertura da igreja antes de adicionar.

## D17. Planejamento de reunião de célula

**Problema:** a implementação atual possui data, hora e tema; o documento deseja roteiro completo.

**Recomendação:** adicionar seções de responsáveis e foco pastoral sem transformar em wizard obrigatório. Cada igreja pode tornar campos opcionais ou configurar um modelo.

## D18. Teal na identidade

**Problema:** a lembrança de marca inclui teal, mas o design system atual consolidou azul mineral.

**Recomendação:** manter Diamond como ação primária e testar teal apenas como acento pastoral, com contraste e distinção de verde de sucesso/WhatsApp.

## D19. Membro no app

**Direção recebida:** membro comum deve acessar conteúdo público, Agenda, avisos, própria célula e próprios dados, sem ação sobre terceiros.

**Pendente:** decidir autenticação, onboarding e política de dados próprios. Essa direção não deve reabrir acesso a telas administrativas.

## D20. Universidade da Vida e Capacitação Destino

**Problema:** visão de aluno e supervisão foram definidas, mas os módulos ainda não existem por completo.

**Recomendação:** PRD separado de formação, com matrículas, turmas, progresso e papéis, após estabilizar escopos.

## Ordem de decisão

1. D01, D02, D03 e D04, autorização e governança.
2. D09 e D14, comunicação real.
3. D11, D12, D16, D17 e D18, experiência e visual.
4. D05, D06, D19 e D20, expansão pastoral.
5. D07, D08, D10, D13 e D15, integrações e automação.
