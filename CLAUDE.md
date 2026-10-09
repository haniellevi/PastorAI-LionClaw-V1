@AGENTS.md

# Claude Code no Igreja12

AGENTS.md concentra as regras compartilhadas. Este arquivo contém apenas
orientações específicas do Claude Code, sem repetir o plano do produto.

- Use o checkout atual da tarefa, em branch própria; preserve trabalho alheio.
- Explore com rg e leia somente os trechos relevantes. Grafo de código é
  opcional: use quando disponível e atualizado, sem instalar ou bloquear a tarefa.
- Mudanças locais reversíveis não exigem plano longo, agente extra ou parecer.
  Para mudanças grandes, apresente escopo e critérios antes de implementar.
- Sarah é revisão independente para autenticação/RLS e migration de produção;
  não é etapa obrigatória de toda correção, refatoração ou documentação.
- Rode testes proporcionais ao comportamento alterado. Os quatro checks de
  produto continuam obrigatórios para integrar mudanças.
- Não faça commit, push, merge ou release automaticamente ao terminar.
  Execute quando autorizado pela solicitação e registre o que foi feito.
- Não escreva memória local automaticamente. Registre a entrega em docs/sprints
  e atualize o checklist pertinente do plano operacional.

Plano de refatoração e ambientes: docs/ops/refatoracao-modular-plano.md.
