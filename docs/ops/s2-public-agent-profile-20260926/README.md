# S2: informações públicas estruturadas da igreja

Registro canônico da fatia: [sprint S2](../../sprints/2026-09-26-mvp-s2-perfil-publico.md).

Candidato sobre main `a5244cad1f0a888b650258bc910f58952c5f2a72`, 26/09/2026.
Merge bloqueado até liberação explícita para coordenar migration e deploy com
PastorAI PROD operacional. A nota PASSO A PASSO RANIEL está suspensa; este
registro não é autorização de operação PROD, banco compartilhado ou provedor.

## Uso previsto no painel

Em Agente IA > Comportamento, o admin preenche Informações públicas da igreja:
endereço institucional, horários dos cultos e até cinco células públicas.
Cada célula informa bairro, nome público e, opcionalmente, dia/horário.
Exemplo sintético: Rua Exemplo, 100; Domingo, 19h; Centro / Esperança / terça, 19h.
Não cadastrar nome/telefone de líder, anfitrião ou endereço residencial.
O backend rejeita padrões privados conhecidos; isso não é detecção geral de PII.
O administrador continua responsável por publicar somente informação aprovada.

Salvar não ativa o agente. Configuração ausente deve ser criada pelo fluxo
existente: este formulário não a cria. Falha ao salvar preserva o rascunho.
Campos vazios removem a informação publicada. **Sem backfill do bloco legado:**
o reset previsto do piloto torna o conteúdo antigo irrelevante; os campos
estruturados precisam ser publicados novamente pelo admin. Esta missão não
executou reset nem verificou se ele já ocorreu em produção.

## Contrato e isolamento

GET e PUT `/agent/public-profile` exigem admin; tenant vem de CurrentUser.
Envelope: `configured` e `informacoesPublicas`; campos HTTP camelCase
`enderecoIgreja`, `horariosCulto`, `celulas[{bairro,nome,encontro}]`.
PUT substitui o perfil inteiro; omissões limpam. Chaves extras, tipos errados,
limites excedidos e conteúdo privado reconhecido são rejeitados.
A representação armazenada usa snake_case em `agent_configs.informacoes_publicas`.
A migration adiciona JSONB vazio por padrão, preservando políticas e grants
existentes de agent_configs. Sem nova tabela, backfill, papel ou ativação.

A projeção é revalidada no runtime. Perguntas “que horas começa o culto?”,
“que horas é o culto”, “horário do culto”, “quando é o culto” e
“tem célula no bairro Centro?” retornam o cadastrado ou ausência honesta.
A busca por bairro não calcula qual célula é geograficamente mais próxima.
Nenhum cadastro privado é consultado; o perfil estruturado não entra no LLM.
O bloco legado é removido do estilo enviado ao LLM, incluindo variantes Cf,
mas deixa de fornecer fatos. Consentimento, opt-out, handoff e gates continuam.

## Aplicação futura: espera de lock limitada

A sessão operacional deverá definir `lock_timeout` curto, com referência de
2 segundos na sessão aplicadora, antes de aplicar a migration. O default
constante não exige rewrite, mas ALTER TABLE ainda precisa de lock exclusivo.
Em timeout, abortar e reagendar com a sessão responsável, sem espera ilimitada
ou retry automático. É requisito operacional para aplicação futura; este
registro não altera o SQL aprovado nem autoriza ou executa banco compartilhado.

## Verificação e rollback

Testes usam apenas fixtures, navegador loopback e PostgreSQL17 descartável.
A evidência final registra hashes, testes e limites do candidato exato.
Prova RLS sintética não certifica grants ou migration aplicada em produção.

Rollback de código pelo fluxo normal preserva a coluna e seus dados. O SQL de
remoção está apenas comentado na migration e é destrutivo; exige decisão
separada antes de qualquer execução. Reverter o código pode restaurar o
comportamento legado, devendo ser considerado no plano operacional.
