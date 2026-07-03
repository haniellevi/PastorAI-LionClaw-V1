# Contrato UX/UI — Módulo Minha Célula + Central de Células (Igreja 12)

> **Status:** Aprovado como base visual. Documento vinculante para PRD e implementação.
> **Data:** 2026-07-02.
> **Natureza:** docs-only. Nenhum código, migration, env ou deploy nesta entrega.

## Fontes de verdade

Este contrato reconcilia três fontes, nesta ordem de precedência:

1. **Protótipo HTML refinado aprovado** — `Igreja12 Prototipo (standalone) refinado.html` (base visual e de fluxo aprovada pelo dono). É a **verdade visual**: o que estiver renderizado nele manda sobre descrições textuais divergentes.
2. **Prompt do Claude Designer** — [`docs/design/CELULAS-prompt-claude-designer.md`](CELULAS-prompt-claude-designer.md). É a **verdade de negócio e de tokens** (design system, regras de aprovação, aptidão, cobertura).
3. **Regras já decididas** (abaixo), que prevalecem sobre qualquer ambiguidade das duas anteriores.

### Regras decididas (travadas)

- Menu **Minha Célula** = visão **Discípulo** + visão **Líder** (as duas convivem sob o mesmo menu).
- **Central de Células** = **Jornada G12 → Discipular → Central de Célula** (sub-item; **não** é aba do menu Minha Célula).
- **Árvore Ministerial** (quem lidera quem) é módulo **separado** da célula comum — só é citada como destino da multiplicação aprovada.
- **Apto a liderar = realizou o Reencontro** (não é a CD).
- **Todo líder de célula já é apto** implicitamente (não exibir selo redundante em quem já lidera).
- **A Central aprova alterações sensíveis** (dia, horário, endereço, anfitrião, auxiliar, entrada/saída de membro, multiplicação).

Onde o protótipo diverge do prompt, a divergência está registrada na seção **16 (Limitações do protótipo)**.

---

## 1. Escopo

O contrato cobre **dois recortes de produto** e a navegação entre eles:

- **Minha Célula** (menu próprio no grupo GESTÃO): duas visões sob o mesmo menu —
  - **Discípulo** (membro): tela acolhedora, minimalista, sem jargão de gestão.
  - **Líder**: gestão completa da própria célula em 7 seções.
- **Central de Células** (dentro de Jornada G12 → Discipular): supervisão da rede de células, em 5 seções.

Cobre: navegação, papéis, mapa de telas, todos os componentes visuais, estados (vazio/pendente/aprovado/rejeitado), regras de cor, responsividade e interações obrigatórias das telas acima.

## 2. Fora de escopo

- **Agenda / Eventos** (módulo próprio, já em produção — EVT-1..7). Intocado.
- **Universidade da Vida (UV), Capacitação Destino (CD), Encontro com Deus** — citados como etapas da trilha e como KPIs, mas **suas telas não são expandidas** aqui; permanecem nos seus módulos.
- **Árvore Ministerial / Descendências** — módulo separado; aqui só entra como destino da multiplicação aprovada.
- Configurações, billing, chat/Conversas, Pessoas, Comunicação, Agente IA — outros módulos.
- Backend, contratos de API, migrations, workers, deploy — não fazem parte deste contrato de UX.

## 3. Navegação

### 3.1 Onde cada coisa vive na sidebar

```
Igreja 12  (sidebar escura, card da igreja ativa)
├─ GESTÃO
│  ├─ Painel de Hoje
│  ├─ Conversas
│  └─ Minha Célula            ← [visão Discípulo | visão Líder]
├─ A JORNADA G12
│  ├─ Ganhar
│  ├─ Consolidar
│  ├─ Discipular  → abas: Visão · **Central de Célula** · Capacitação Destino · Treinamentos
│  └─ Enviar
├─ IGREJA        (Pessoas · Árvore Ministerial · Agenda · Comunicação)
├─ ADMINISTRAÇÃO (Gestão Administrativa)
└─ CONFIGURAÇÃO  (WhatsApp · Agente IA · Assinatura · Permissões · Usuários)
```

### 3.2 Regras de navegação

- **Minha Célula** abre com um alternador no topo do conteúdo: **`Visão discípulo` | `Visão líder`**, com selo discreto "alternância de demonstração" (no produto real, quem vê cada visão é definido pelo papel — ver seção 4).
- Dentro de **Visão líder**, a navegação secundária é uma fila horizontal rolável de abas: **Painel · Editar célula · Avisos · Discípulos · Planejar · Relatório · Multiplicação**.
- **Central** só é alcançada por **Discipular → aba "Central de Célula"**. Dentro dela, navegação secundária própria: **Dashboard · Gerenciar células · Solicitações · Avisos · Materiais**.
- **A Central nunca aparece dentro de Minha Célula.** Este é um invariante (seção 15).
- Toda troca de aba/seção rola a tela para o topo. Uma "tela" visível por vez dentro de cada visão.

## 4. Papéis

| Papel | Enxerga | Não enxerga |
|---|---|---|
| **Discípulo** (membro) | Minha Célula · visão Discípulo (tela única) | relatórios, dados de outros membros, gestão, Central |
| **Líder de célula** | Minha Célula · visão Líder (7 seções) da **sua** célula | Central (gestão da rede); dados sensíveis só via solicitação |
| **Central / Admin** | Central de Células (5 seções) + tudo da igreja | — |

- **Líder** edita apenas **dados leves** da célula (nome, link do grupo, mensagem de convite). **Dados sensíveis** viram solicitação à Central.
- **Central/Admin** cadastra células, aprova/rejeita solicitações, gerencia materiais e avisos da rede.
- **Aptidão**: "Apto a liderar" = realizou o Reencontro. Todo líder já é apto (selo omitido em quem lidera). Só aptos podem ser novo líder numa multiplicação.

## 5. Mapa de telas

### 5.1 Minha Célula — Discípulo (tela única)
`discipulo` — hero da próxima célula · dois fluxos (presença / expectativa) · participantes · mural de avisos · histórico.

### 5.2 Minha Célula — Líder (7 seções)
| Seção | Conteúdo |
|---|---|
| Painel | banner de relatório pendente + KPIs da trilha |
| Editar célula | dados leves (salva direto) + dados sensíveis (solicitação) |
| Avisos | "Da célula" (azul, cria) + "Da igreja" (vermelho, leitura) |
| Discípulos | lista numerada + presença + ficha (modal) + transferir p/ Central |
| Planejar | data/hora + material da central + 8 etapas + confirmar |
| Relatório | tema, avisos, oferta, presença, visitantes (acumulam abaixo) |
| Multiplicação | solicitar multiplicação (novo líder apto) |

### 5.3 Central de Células (5 seções)
| Seção | Conteúdo |
|---|---|
| Dashboard | stat-cards + "Saúde das células" (10 bolinhas) + ordenação por saúde |
| Gerenciar células | busca/filtros + lista + "Nova célula" + detalhe + **editar célula** |
| Solicitações | aprovar (com confirmação) · rejeitar (com motivo) · pedir ajuste |
| Avisos | "Novo aviso" (público, agora/agendar) + lista |
| Materiais | rascunho/publicado · editar · IA-tema · upload · link só música |

### 5.4 Modais compartilhados
Convite · Ficha do discípulo · Detalhe da célula · Editar célula (Central) · Nova célula · Novo aviso (Central) · Novo/editar material · Biblioteca de materiais (líder) · Rejeitar solicitação · Confirmar aprovação · Pedir ajuste · Aviso da célula (líder) · Confirmação genérica ("done").

## 6. Visão Discípulo

Ordem vertical (mobile-first; 2 colunas no desktop onde indicado):

1. **Hero da célula** — card gradiente petróleo, texto claro: nome da célula, líder · auxiliar, dia · hora, endereço. Ações: **Convidar amigo** (modal), **Grupo no WhatsApp**, **Localização**.
2. **Próxima célula** — cabeçalho com data/hora e tema. Abaixo, **dois números dinâmicos**: **participantes confirmados** e **visitantes esperados** (atualizam ao interagir).
   - **Fluxo ① · Sua presença** — rótulo numerado "1" + botão **"Confirmar minha presença"**; ao confirmar vira estado verde **"Presença confirmada"** e incrementa "participantes confirmados".
   - **Fluxo ② · Expectativa de visitante** — separado por divisória, rótulo numerado "2". Texto guia: *"Você está esperando levar alguém? Informe o nome para a célula orar junto."* Checkbox **"Confirmar expectativa de visitante"** revela: **nome do visitante**, **observação / pedido de oração por essa pessoa (opcional)** e botão **"Confirmar expectativa"**; ao confirmar, incrementa "visitantes esperados" e mostra confirmação ("A célula já vai orar pelo seu convidado").
3. **Participantes** — lista com **Líder** (pill), **Auxiliar** (pill), **Anfitrião** (pill) identificados; demais **numerados**.
4. **Mural de avisos** — cards compactos; **igreja em vermelho**, **célula em azul**; cada aviso mostra validade e ação **"Visto"**. Aviso vencido ou marcado como visto **some do mural** (microtexto: "Somem quando expiram ou quando você marca como visto").
5. **Histórico de células** — card rolável; cada linha: nº, tema, pill **"Você participou"** (verde) / **"Você faltou"** (vermelho), presentes/visitantes, data.

O discípulo **não vê** relatórios, dados de outros membros nem gestão.

## 7. Visão Líder

### 7.1 Painel
- Banner de **relatório pendente** (tom warn/danger): "Relatório da última célula pendente — Realizada há 3h, envie para a Central" + botão **"Enviar agora"** → seção Relatório. Regra: dispara **2h após o horário previsto**.
- **KPIs da trilha** (stat-cards): Reuniões realizadas · Membros · Visitantes (mês) · Precisam aceitar Jesus · Em consolidação · Na UV atual · Concluíram a UV · Batizados · Fazendo a CD · Fizeram Reencontro · Formados na CD · Aptos a liderar.

### 7.2 Editar célula
- **Dados leves** (salva direto, feedback "salva na hora"): nome, endereço, link da localização, link do grupo (WhatsApp), mensagem de convite (textarea), anfitrião, auxiliar.
- **Bloco "Dados que a Central confirma"** (visualmente distinto): dia & horário, entrada/saída de membro. Microtexto: alterar dia/horário ou registrar saída **vira solicitação**; **entrada de membro é direta**. Mostra bloco **"Solicitação em andamento"** com pill **"Em análise"** quando há pendência.

### 7.3 Avisos
- **"Da célula"** (azul): botão **"Novo aviso"** → modal (mensagem + Enviar agora/Agendar + data/hora). Aviso é **sempre para a própria célula** (sem escolher público). Aviso vencido/visto some do mural.
- **"Da igreja"** (vermelho): somente leitura, com selo "só leitura".

### 7.4 Discípulos
- Lista **numerada**, com **Auxiliar** e **Apto a liderar** destacados por pill. Cada linha: nº, avatar, nome, trilha, **5 bolinhas** das últimas reuniões (verde presente / vermelho ausente), **alerta amarelo** de cadastro incompleto.
- Botão **"Adicionar participante"** → entrada **direta** (sem aprovação).
- Clicar → **ficha do discípulo** (modal): aniversário, atividade, família (com marcador da igreja/não), maior sonho, dificuldade, onde gostaria de servir, próxima meta na trilha. Cadastro incompleto ganha alerta + "Atualizar cadastro".
- **Ação "Transferir para a Central"** no rodapé da ficha: indica **saída da célula**; vira **solicitação** com status "alteração pendente". A Central decide (ver 8.3): apontar **nova célula** OU registrar **saída da igreja** (com motivo).

### 7.5 Planejar
- **Data/hora já vêm preenchidas** pelo padrão da célula. Botão **"Alterar"** revela inputs + aviso: *"Alterar dia/horário vira uma solicitação para a Central de Célula."*
- Atalho **"Material da Central"** → biblioteca de materiais.
- **Programação — 8 etapas fixas, nesta ordem**: 1 Boas-vindas (2 min) · 2 Louvor (5–10) · 3 Quebra-gelo (5) · 4 Mensagem (20) · 5 Oração por necessidades (5) · 6 Oração de salvação (5) · 7 Oferta (5) · 8 Comunhão (10). Cada etapa: **responsável** (select) + **observação** opcional.
  - **Louvor**: escolher responsável; responsável escolhe a música **ou** líder seleciona do banco **ou** líder adiciona por link.
  - **Quebra-gelo**: responsável; selecionar do banco **ou** criar novo (nome + conteúdo + tema; **tema sugerido por IA**).
  - **Mensagem**: responsável; **sermão da Central** (traz pronto) **ou** sugerir tema **ou** tema livre (responsável escolhe; líder atualiza no relatório).
- Botão **"Revisar e confirmar programação"** → toast: cada responsável recebe sua parte no WhatsApp (envio pelo agente do sistema).

### 7.6 Relatório
- Card minimalista: **tema da mensagem**, **Deu os avisos?** (sim/não), **Teve oferta?** (sim/não), **presença** (chips por membro, contador de marcados).
- **Visitantes**: formulário (nome, WhatsApp, **Aceitou Jesus? sim/não**) + botão **"Adicionar"**. Ao adicionar, o visitante entra numa **lista logo abaixo do campo**, o **formulário limpa** e permite cadastrar o próximo; a lista **acumula** (não substitui). Microtexto: quem aceitou Jesus **inicia consolidação automaticamente**.
- Botão **"Enviar relatório para a Central"**.

### 7.7 Multiplicação
- Card de status (se há solicitação: pill Aguardando/Aprovada/Rejeitada).
- Solicitar multiplicação: **novo líder** (só membros **aptos = fizeram o Reencontro**; não aptos desabilitados com motivo), membros que vão, dia/hora, endereço, anfitrião, data prevista. Nasce **pendente**. Microtexto: aprovada, a nova célula entra na Árvore Ministerial e o novo líder recebe a gestão.

## 8. Visão Central

### 8.1 Dashboard
- **Stat-cards**: Total de células · Relatórios recebidos · Relatórios pendentes · Frequência média · Visitantes no mês · Participantes no mês · % de membros em célula.
- **"Saúde das células"**: uma linha por célula — **posição/número como primeira informação**, avatar, nome, líder · dia, e **10 bolinhas** (últimas 10 reuniões: **verde = relatório enviado/realizada**, **vermelho = não enviado/não realizada**). Legenda "enviado / não enviado".
- **Ordenação**: abas **Ordem padrão · Menos saudáveis · Mais saudáveis** (as duas últimas destacam o topo em vermelho/verde). Clicar na linha abre o detalhe da célula.

### 8.2 Gerenciar células
- Busca (célula ou líder) + filtros (Descendência · Cobertura · Status). Botão **"Nova célula"** → modal: **cobertura espiritual*** (obrigatória), líder, nome, endereço, dia, horário.
- Lista de células (nº, avatar, nome, líder · cobertura · dia · membros, pill status). Clicar → **detalhe** → botão **"Editar célula"**.
- **Editar célula (Central)** atualiza: **líder · auxiliar · anfitrião · membros · dia · horário · local · cobertura/liderança**. Bloco **"Transferir liderança (cobertura)"**: ao escolher nova cobertura, microtexto deixa claro que **a célula passa a ficar abaixo da nova liderança** e o líder aparece automaticamente sob o novo líder.

### 8.3 Solicitações
- Linha por solicitação: tipo (Multiplicação / Alteração / Troca…), célula, líder solicitante, resumo (valor atual → proposto), data.
- **Aprovar** → **modal de confirmação de segurança** listando **todas as mudanças que serão aplicadas** (checklist) + aviso "esta ação aplica as mudanças e avisa os envolvidos" → botão **"Confirmar e aprovar"**.
- **Rejeitar** → modal exige **motivo obrigatório** (o líder recebe pelo WhatsApp).
- **Pedir ajuste** → modal com campo **"observação"** para o líder (ele corrige e reenvia).
- **Transferência de discípulo** (vinda de 7.4): a Central só aprova escolhendo **nova célula** OU **saída da igreja com motivo**.

### 8.4 Avisos
- Botão **"Novo aviso"** → modal: título, mensagem, público (chips: Todas as células · Líderes · Célula específica · Descendência/cobertura), **Enviar agora / Agendar**. Lista com pill Enviado/Agendado/Rascunho. Avisos da Central chegam **em vermelho** no mural.
- Nota: avisos gerais da igreja (homens, mulheres, jovens…) ficam em **Comunicação**, não aqui.

### 8.5 Materiais
- Botão **"Novo material"** e **editar** material existente. Status **Publicado / Rascunho** (rascunho fica só com a Central; publicar libera para líderes).
- **Tipo**: Sermão · Quebra-gelo · Música. **Tema/tags** para busca; **sugestão de tema por IA**.
- **Conteúdo**: texto; **upload de arquivo** (.docx · .pdf · .txt); **link somente para músicas** (YouTube/Spotify). Ao colar link de música, **preenchimento automático simulado** de nome + artista.

## 9. Componentes principais

| Componente | Regra |
|---|---|
| **Botão** | Sora; primário teal (`--accent`); variantes ghost/danger/sm; foco com `--ring`; loading com spinner |
| **Card / Panel** | surface + borda forte + raio 16px + sombra; cabeçalho `panel-title` com contador |
| **Stat-card** | rótulo `--muted` + ícone accent; valor Sora 30px; variação alerta em `--warn` |
| **Pill de status** | 11.5px, dot 6px; tons ok/warn/danger/accent/muted/info |
| **Tabs** | trilho surface-2; ativa surface + sombra; contador ` · N` |
| **Modal** | overlay escuro translúcido; caixa 420px (560px wizard); cabeçalho + rodapé de ações; ≥44px de alvo no mobile |
| **Toast** | inferior centralizado; ícone ok/erro; some ~3.2s |
| **Empty state** | centrado, ícone 40px, "**Frase forte.** complemento" |
| **Formulários** | label 12.5px; input raio 10px, foco accent + ring; helper `--muted` |
| **Lista `.list-row`** | padding 12/16, borda inferior, hover surface-2 |
| **Bolinhas de presença/saúde** | 8–10px, verde/vermelho, com `title` acessível |
| **Selo "Apto a liderar"** | pill accent; **só** em quem é apto e **não** lidera |
| **Avatar de iniciais** | círculo 34–38px, paleta rotativa por índice |

## 10. Estados vazios

Todo componente de lista tem estado vazio explícito (empty state centrado, ícone + frase forte):

- **Mural do discípulo vazio**: "**Tudo em dia!** Nenhum aviso no momento."
- **Avisos da célula (líder) sem itens**: "Nenhum outro aviso ativo."
- **Fila de expectativa (discípulo)**: quando não há confirmação, o número é 0 (sem card de erro).
- **Solicitações da Central vazias**: "Nenhuma solicitação pendente."
- **Visitantes no relatório**: a lista abaixo do formulário só aparece quando há ≥1 visitante adicionado.
- **Histórico / relatórios anteriores**: card rolável; vazio mostra frase neutra.

## 11. Estados pendentes / aprovados / rejeitados

Ciclo de vida de uma solicitação, com pill de cor fixa:

| Estado | Pill | Onde aparece |
|---|---|---|
| **Aguardando** | `warn` "Em análise" / "Aguardando aprovação" | painel do líder (Editar célula, Multiplicação); fila da Central |
| **Aprovada** | `ok` "Aprovada" | histórico; toast de confirmação na Central |
| **Rejeitada** | `danger` "Rejeitada" + **motivo** | card de status do líder |
| **Ajuste pedido** | `info` | líder recebe observação e reenvia |

Regras:
- **Multiplicação** e **alterações sensíveis** **nascem pendentes**.
- **Entrada de membro** é **direta** (nunca vira pendência).
- Aprovar sempre passa pelo **modal de confirmação** (lista o que muda). Rejeitar sempre exige **motivo**.
- Transferência de discípulo pendente → a Central decide nova célula OU saída da igreja (com motivo).

## 12. Regras de cor

O design system canônico (tokens `oklch`) está na **seção 3 do prompt do Designer** — é a referência para a implementação de produção. Regras semânticas travadas:

- **Marca / ação primária**: teal petróleo (`--accent`). Tinta de texto: verde-petróleo escuro (`--fg`).
- **Avisos da igreja / Central** → **vermelho** (`--danger` / `--danger-soft`), borda esquerda 3px + fundo soft.
- **Avisos da célula** → **azul** (`--info` / `--info-soft`), mesma anatomia.
- **Presença / saúde**: **verde** = presente / relatório enviado; **vermelho** = ausente / não enviado.
- **Pendência cadastral**: **amarelo** (`--warn`) ao lado do nome.
- **Solicitações**: `warn` (aguardando) → `ok` (aprovada) → `danger` (rejeitada).
- **Selo Apto a liderar**: pill `accent`.
- `--faint` **proibido em texto informativo** (reprova AA). Contraste **AA** obrigatório em todo texto.

> **Nota de fidelidade**: o protótipo aprovado usa aproximações **hex** dos tokens (ex.: `#0d9488`, `#0f3a36`, `#16a34a`, `#ef4444`, `#3b82f6`). A implementação de produção deve usar os **tokens `oklch`** da seção 3 do prompt; as regras semânticas acima são o que está travado, não os valores hex do protótipo.

## 13. Responsividade

- **Desktop (≥1280px)**: grid `sidebar 248px | conteúdo`; só a área de conteúdo rola.
- **Breakpoint principal ≤860px**: sidebar vira **drawer**; aparece **bottom-nav** fixa. Sem **scroll horizontal** em nenhuma largura **≥360px** (verificado no protótipo: 4 abas cabem em 360px).
- **Mobile 390px**: shell "device" (moldura arredondada) no protótipo; layouts de 2 colunas colapsam para 1.
- Grades (`repeat(auto-fit/auto-fill, minmax(...))`) reflowam; tabelas viram cards.
- Alvos de toque **≥44px** no mobile; `prefers-reduced-motion` neutraliza animações; foco sempre visível.
- Abas secundárias (líder e central) são **fileiras horizontais roláveis** — nunca quebram o layout.

## 14. Interações obrigatórias

Estas interações **devem** existir e funcionar (simuladas no protótipo, reais na implementação):

1. **Discípulo — confirmar presença**: botão → estado verde "Presença confirmada" + incremento do contador "participantes confirmados".
2. **Discípulo — confirmar expectativa**: checkbox revela nome + observação + botão "Confirmar expectativa"; incrementa "visitantes esperados"; mostra confirmação.
3. **Discípulo — marcar aviso como "Visto"**: some do mural.
4. **Líder — adicionar visitante no relatório**: acumula na lista **abaixo** do form; form limpa; repete.
5. **Líder — alterar dia/horário no Planejar/Editar**: mostra o aviso de que **vira solicitação** para a Central.
6. **Líder — transferir discípulo para a Central**: status "alteração pendente".
7. **Líder — adicionar participante**: entrada **direta**, sem aprovação.
8. **Central — aprovar solicitação**: abre **confirmação de segurança** com o que muda antes de confirmar.
9. **Central — rejeitar**: exige **motivo**.
10. **Central — pedir ajuste**: abre campo **observação**.
11. **Central — material música**: colar link YouTube/Spotify → preenchimento automático simulado de nome + artista.
12. **Central — ordenar saúde**: alternar Ordem padrão / Menos saudáveis / Mais saudáveis reordena a lista.
13. **Toggle Discípulo | Líder** em Minha Célula alterna as duas visões.

## 15. Pontos que não podem mudar sem nova aprovação

Invariantes. Alterar qualquer um exige nova rodada de aprovação do dono:

1. **Central NUNCA dentro de Minha Célula** — vive só em Discipular → Central de Célula.
2. **Minha Célula = Discípulo + Líder** sob o mesmo menu.
3. **Programação = 8 etapas fixas, nesta ordem e tempos.**
4. **Dados sensíveis** (dia, horário, endereço, anfitrião, auxiliar, entrada/**saída** de membro, multiplicação) **só mudam com aprovação da Central**; **entrada de membro é direta**.
5. **Aprovar** sempre passa por **confirmação com a lista do que muda**; **rejeitar** sempre exige **motivo**.
6. **Apto a liderar = realizou o Reencontro**; **todo líder já é apto** (selo omitido em quem lidera); só aptos viram novo líder.
7. **Toda célula tem cobertura espiritual** (obrigatória no cadastro).
8. **Cores semânticas**: igreja = vermelho, célula = azul; presença/saúde verde/vermelho; pendência amarelo.
9. **Dois fluxos separados no discípulo**: presença (①) e expectativa de visitante (②) são blocos distintos e rotulados.
10. **Visitante que aceitou Jesus** inicia consolidação.
11. **Link só para música** nos materiais (YouTube/Spotify); demais tipos usam texto/arquivo.

## 16. Limitações do protótipo

O protótipo é **mockup navegável** (framework `dc-runtime`, dados mock, nada persiste). Divergências conhecidas vs. o prompt do Designer, aceitas nesta base:

1. **Cores em hex**, não nos tokens `oklch` do design system. Produção usa os tokens (ver seção 12).
2. **Entrada por login + papel demo** e **toggle interno Discípulo|Líder** em Minha Célula, em vez do "switcher de contexto Líder·Discípulo·Central" descrito no prompt. A regra estrutural (Central fora de Minha Célula) é respeitada.
3. **Central sem aba "Líderes"** — o prompt previa; o protótipo não a implementa. A gestão de liderança acontece via "Editar célula → Transferir liderança".
4. **Planejar exibe as 8 etapas inline**, não como wizard modal com barra "Etapa X de 8".
5. **Multiplicação** é um card de solicitação simples, não o wizard completo do prompt.
6. **Campos do discípulo (expectativa)** não são persistidos nem propagam o nome digitado para a confirmação — é simulação visual.
7. **Sem backend real**: contadores, aprovações, envios de WhatsApp e "preenchimento automático" de link são **simulados**.
8. **React/ReactDOM/Babel** carregados de CDN em runtime — o standalone só renderiza **com internet**.
9. **Reconstrução do bundle** exige re-serializar o template escapando todo `/` como `/` (detalhe técnico do exportador; não afeta a UX).

Nenhuma dessas limitações contradiz os invariantes da seção 15.

## 17. Próximos PRDs / implementação

Ordem sugerida de trabalho a partir deste contrato (cada item = PRD + PRs; nada aqui é código):

1. **PRD Minha Célula — Discípulo**: modelo de dados de presença/expectativa por reunião; endpoints de confirmar presença e registrar expectativa; mural (fonte dos avisos por escopo igreja/célula).
2. **PRD Minha Célula — Líder**: relatório por reunião (tema, avisos, oferta, presença, visitantes) com escrita real; ficha do discípulo (campos cadastrais + trilha); avisos da célula (criar/agendar/expirar).
3. **PRD Solicitações & aprovação**: máquina de estados (pendente → aprovada/rejeitada/ajuste) para dados sensíveis, transferência de discípulo e multiplicação; confirmação de segurança; notificação ao líder via agente.
4. **PRD Central**: dashboard de saúde (últimas N reuniões), gerenciar células (CRUD + cobertura + transferir liderança), materiais (rascunho/publicado + upload + link música), avisos por público.
5. **PRD Integrações de trilha**: KPIs do painel do líder e do detalhe da célula alimentados por UV/CD/Reencontro/Batismo (leitura dos módulos existentes, sem expandi-los).
6. **Ligação com Árvore Ministerial**: multiplicação aprovada cria célula e atualiza o organograma (módulo separado).

**Bloqueadores estruturais a resolver no PRD** (herdados da análise do módulo): presença por reunião (hoje inexistente no modelo), relatórios com escrita real, campos de célula (cobertura, anfitrião, link do grupo, mensagem de convite), papel de líder da Central, e a fonte de verdade célula ↔ árvore ministerial.

---

### Referências

- [`docs/design/CELULAS-prompt-claude-designer.md`](CELULAS-prompt-claude-designer.md) — design system, tokens, regras de negócio.
- Protótipo aprovado: `Igreja12 Prototipo (standalone) refinado.html` (base visual).
- Convenção de sprints: `docs/sprints/README.md`.
