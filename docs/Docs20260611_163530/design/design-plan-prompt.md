## Design Plan aprovado antes do Open Design

Este e o blueprint de produto para o artifact visual. O schema do design-contract e o Design Lock continuam tendo prioridade maxima.
Plano deterministico gerado pelo LionClaw; validacao deterministica: aprovada.


Telas planejadas:
- login (Login) — Autenticar usuario antes de acessar dados protegidos. — stories: US-01
- principal (Principal) — Executar as principais tarefas do produto usando dados das stories aprovadas. — stories: US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09, US-10, US-11, US-12, US-13, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31, US-32, US-33, US-34, US-35, US-36, US-37, US-38, US-39, US-40, US-41, US-42, US-43

Navegacao planejada:
- Principal -> principal — stories: US-01, US-02, US-03, US-04, US-05, US-06, US-07, US-08, US-09, US-10, US-11, US-12, US-13, US-14, US-15, US-16, US-17, US-18, US-19, US-20, US-21, US-22, US-23, US-24, US-25, US-26, US-27, US-28, US-29, US-30, US-31, US-32, US-33, US-34, US-35, US-36, US-37, US-38, US-39, US-40, US-41, US-42, US-43

Vocabulario obrigatorio de dominio:
- dashboard
- registros
- configuracao

Copy proibida ou arriscada:
- acesse seu ambiente
- painel operacional
- eleve sua produtividade

Dados fake recomendados:
(nao declarado)

Instrucoes especificas para Open Design:
- Gere uma SPA operacional, nao uma landing page.
- Use entidades concretas das user stories e evite copy generica.
- Nao escreva regras de negocio na tela; mostre apenas dados, estados, formularios e acoes.
- Gere os fluxos de todas as telas necessarias com navegacao clicavel.
- Arquivo unico index.html e permitido, mas telas empilhadas no scroll sao proibidas. Use [hidden] e JS real para mostrar apenas uma section por vez.

Cobertura planejada:
- US-01: principal — Cobertura deterministica.
- US-02: principal — Cobertura deterministica.
- US-03: principal — Cobertura deterministica.
- US-04: principal — Cobertura deterministica.
- US-05: principal — Cobertura deterministica.
- US-06: principal — Cobertura deterministica.
- US-07: principal — Cobertura deterministica.
- US-08: principal — Cobertura deterministica.
- US-09: principal — Cobertura deterministica.
- US-10: principal — Cobertura deterministica.
- US-11: principal — Cobertura deterministica.
- US-12: principal — Cobertura deterministica.
- US-13: principal — Cobertura deterministica.
- US-14: principal — Cobertura deterministica.
- US-15: principal — Cobertura deterministica.
- US-16: principal — Cobertura deterministica.
- US-17: principal — Cobertura deterministica.
- US-18: principal — Cobertura deterministica.
- US-19: principal — Cobertura deterministica.
- US-20: principal — Cobertura deterministica.
- US-21: principal — Cobertura deterministica.
- US-22: principal — Cobertura deterministica.
- US-23: principal — Cobertura deterministica.
- US-24: principal — Cobertura deterministica.
- US-25: principal — Cobertura deterministica.
- US-26: principal — Cobertura deterministica.
- US-27: principal — Cobertura deterministica.
- US-28: principal — Cobertura deterministica.
- US-29: principal — Cobertura deterministica.
- US-30: principal — Cobertura deterministica.
- US-31: principal — Cobertura deterministica.
- US-32: principal — Cobertura deterministica.
- US-33: principal — Cobertura deterministica.
- US-34: principal — Cobertura deterministica.
- US-35: principal — Cobertura deterministica.
- US-36: principal — Cobertura deterministica.
- US-37: principal — Cobertura deterministica.
- US-38: principal — Cobertura deterministica.
- US-39: principal — Cobertura deterministica.
- US-40: principal — Cobertura deterministica.
- US-41: principal — Cobertura deterministica.
- US-42: principal — Cobertura deterministica.
- US-43: principal — Cobertura deterministica.

Regras para usar este plano:
- Use este plano como mapa operacional, nao como copy literal.
- Nao mostre este plano, JSON, criterios internos ou racional no HTML.
- O HTML final deve mostrar apenas a SPA funcional do produto.
- Nao gere landing page, hero, pitch comercial, galeria de telas ou secoes explicativas.
- Um index.html unico e permitido; telas empilhadas no scroll sao proibidas.
- Inclua CSS `[hidden] { display: none !important; }` e JS real para alternar qual `section` esta visivel.
- Login e app shell nunca podem coexistir visualmente. Ao submeter login, esconda login e mostre a primeira tela interna.
- Gere os fluxos de todas as telas necessarias com navegacao clicavel.
- Nao escreva regra de negocio, criterio de aceite ou contrato como texto visivel na UI.