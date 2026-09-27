# Revisão UI S2b

**Candidato:** `S2B-UI-v2.patch` SHA-256 `6209fa366dc86bbfd8194dc37995f8ea53b6e2bb2768409fa3c3c59c8ae7db76`.

## Veredito

**APTO técnico, limitado à UI deste patch.** Não é veredito da integração backend, migration ou runtime.

Os dois P1 do primeiro snapshot foram corrigidos. O modal agora representa campos públicos ausentes como desconhecidos e só os envia após alteração explícita. Assim, uma lista antiga ou em cache não limpa `bairro` nem despublica a célula ao salvar outro campo. A rota `cadastro-igreja` entrou em `ADMIN_ONLY`, e o teste do Sidebar confirma que o administrador a vê e que o líder não a vê.

## Controles revisados

- A tela institucional usa escopo por token, igreja, usuário e recarga; limpa estado, aborta GET e PUT tardios e descarta respostas de escopo anterior.
- Capability usa `no-store`, falha fechada e não abre GET ou PUT quando o servidor antigo não a anuncia. Não há URL, storage ou log contendo fatos do cadastro.
- O PUT envia somente `enderecoInstitucional` e `horariosCulto`, com `null` explícito para limpeza e limite local de 400 caracteres. A autorização efetiva permanece no backend.
- O líder tem caminho normal pelo Dashboard: “Visão geral do seu cuidado” permite abrir “Células ativas”, selecionar sua célula e editar o bairro. A rota permanece fora da sidebar, mas não depende de hash manual.
- Publicação continua visível apenas para pastor ou admin no cliente. O endpoint precisa manter essa regra, célula ativa e bairro preenchido como controles autoritativos.

## Condições de integração

- A capability deve ser autorizada ao líder que edita o bairro da própria célula, enquanto GET e PUT do cadastro institucional permanecem exclusivos de admin.
- O teste de integração deve cobrir o caminho do líder até o modal, além dos testes já presentes de payload desconhecido e Sidebar.

Não executei build, E2E ou chamadas externas nesta revisão. O candidato deve ser validado junto ao backend congelado e aos respectivos gates antes de merge.
