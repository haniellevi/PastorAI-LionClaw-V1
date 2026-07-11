# PRD — Minha Célula · Visão Líder (Igreja 12)

> **Status:** Rascunho para revisão. Deriva do contrato de UX/UI e do PRD Discípulo, ambos já em `main`.
> **Data:** 2026-07-03.
> **Natureza:** docs-only. Nenhum código, migration, env ou deploy nesta entrega.
> **Escopo deste PRD:** apenas a **visão Líder** do menu **Minha Célula**. A visão Discípulo e a Central de Células têm PRDs próprios.

> **Atualização (M7B-W1.3, 2026-07-11):** decisão do dono — **transferir/remover membro NÃO parte da tela do líder**, nem como solicitação. A gestão de membros (entrada/transferência/saída) é atribuição da **Central de Célula**. Isto **supera** as menções a *transferir/remover membro* / *saída de membro* em **§5 (componente 9)**, **§9** e **CA-6**: na visão Líder a lista de discípulos é **estritamente de leitura** e as solicitações permitidas ao líder passam a ser apenas **alterar dia/horário/endereço/anfitrião/auxiliar** e **multiplicação**. Alinhado ao protótipo aprovado (que nunca teve esses botões). Backend barra a criação/reenvio desses tipos por `POST /cell-requests` (403); a **decisão da Central** sobre solicitações legadas permanece intacta.

## Fontes de verdade

1. **Contrato UX/UI** — [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) (vinculante). Este PRD detalha a **seção 7 (Visão Líder)** e não pode contrariar os invariantes (seção 15 do contrato).
2. **PRD Discípulo** — [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md) (a outra visão sob o mesmo menu).
3. **Protótipo refinado aprovado** — `Igreja12 Prototipo (standalone) refinado.html` (base visual da visão Líder).
4. **Regras decididas** (abaixo), que prevalecem em qualquer ambiguidade.

### Regras decididas (travadas)

- O menu chama-se **"Minha Célula"**; dentro dele há **visão Discípulo** e **visão Líder**.
- A **Central de Células NÃO aparece** dentro de Minha Célula.
- O **líder gerencia a própria célula**.
- O líder vê **participantes numerados**, com **líder, auxiliar e anfitrião** identificados.
- O líder **registra o relatório** da célula: presença/faltas, visitantes, observações e planejamento.
- **Visitantes** adicionados **acumulam abaixo do formulário**, que **limpa** para o próximo.
- O **planejamento tem 8 etapas**.
- Alterar **dia / horário / endereço / anfitrião / auxiliar**, **transferir/remover membro** e **multiplicar** viram **solicitação para a Central**.
- O líder **pode solicitar multiplicação** (novo líder apto, membros que irão, dia/hora, endereço, anfitrião).
- A **Central analisa e aprova/rejeita**.
- **Dados sensíveis não mudam direto** sem aprovação da Central.

---

## 1. Objetivo da visão Líder

Dar ao líder uma central de gestão da **própria** célula, mobile-first, que responda:

- **Como está minha célula?** (saúde, KPIs da trilha, pendências)
- **Quem participa e como cada um vai?** (discípulos, presença, ficha, trilha)
- **O que aconteceu na última reunião?** (relatório: presença, visitantes, decisões, observações)
- **O que vou fazer na próxima?** (planejamento das 8 etapas, responsáveis)
- **O que preciso pedir para a Central?** (dados sensíveis, transferências, multiplicação)

Metas de produto:
- Garantir **relatório enviado** a cada reunião (dado que alimenta a Central e a trilha).
- Tornar a **gestão da célula autônoma** no que é leve, e **governada pela Central** no que é sensível.
- Impulsionar a **multiplicação** (formar novos líderes aptos).

Não-objetivos: gerir a rede (Central), ver dados de outras células, aprovar as próprias solicitações.

## 2. Persona / papel que acessa

- **Papel:** `Líder de célula` — responsável por **uma** célula (pode liderar mais de uma no futuro; ver perguntas abertas). Todo líder de célula **já é apto** (realizou o Reencontro).
- **Contexto:** mobile predominante, muitas vezes logo após a reunião (para preencher relatório). Precisa de fluxo rápido.
- **O que enxerga:** a **própria** célula em 7 seções (Painel · Editar célula · Avisos · Discípulos · Planejar · Relatório · Multiplicação).
- **O que NÃO enxerga:** gestão da rede (Central), dados de outras células, aprovação de solicitações (quem aprova é a Central).
- **Poder de escrita:** total nos **dados leves** e no **relatório/planejamento/avisos da célula**; **restrito** nos dados sensíveis (só via solicitação).

## 3. Navegação — menu Minha Célula → visão Líder

- Item **"Minha Célula"** no grupo **GESTÃO**. No produto real, quem é líder acessa a **visão Líder**; o alternador "Visão discípulo | Visão líder" do protótipo é de demonstração e não é papel de produto.
- Dentro da visão Líder, navegação secundária = **fila horizontal rolável de abas**: **Painel · Editar célula · Avisos · Discípulos · Planejar · Relatório · Multiplicação**. Uma seção por vez; trocar de aba rola ao topo.
- **Invariante:** a Central de Células **não** aparece aqui. Solicitações partem daqui, mas a **decisão** acontece na Central (Jornada G12 → Discipular → Central de Célula).

## 4. Estados da tela

| # | Estado | Comportamento |
|---|--------|---------------|
| 4.1 | **Líder sem célula** | Papel de líder sem célula atribuída (recém-nomeado / célula fechada). Empty state: "**Você ainda não tem uma célula ativa.**" + orientação (a Central cadastra/atribui). Sem abas de gestão. |
| 4.2 | **Célula ativa** | Estado base: resumo da célula + abas habilitadas. Painel mostra KPIs da trilha. |
| 4.3 | **Próxima reunião aberta** | Há ocorrência futura. Painel mostra "Próxima célula" (data/hora/status Planejada/Confirmada) + atalho para Planejar. |
| 4.4 | **Relatório pendente** | Passou o horário previsto e não houve envio (dispara **2h** depois). Banner grande `warn`/`danger` no Painel e na aba Relatório: "**Relatório pendente!** A célula de {data} ainda não teve o relatório enviado." + botão "Enviar relatório agora". |
| 4.5 | **Relatório enviado** | O relatório da última ocorrência foi enviado. Banner some; a reunião entra em "Relatórios anteriores" com pill **Enviado**. |
| 4.6 | **Solicitação pendente** | Existe solicitação de dado sensível/multiplicação aguardando a Central. Pill `warn` "Em análise" / "Aguardando aprovação" **junto ao campo** afetado e/ou na aba correspondente (Editar célula, Multiplicação). Enquanto pendente, o valor **não muda**. |
| 4.7 | **Solicitação aprovada** | A Central aprovou. O dado passa a valer; pill `ok` "Aprovada"; o líder é avisado (pelo agente, fora deste PRD). |
| 4.8 | **Solicitação rejeitada** | A Central rejeitou com **motivo**. Pill `danger` "Rejeitada" + motivo visível; o líder pode corrigir e reenviar. |

## 5. Componentes da tela

1. **Resumo da célula** — nome + pill Ativa + "dia · hora · local"; identifica líder/auxiliar/anfitrião.
2. **Próxima reunião** — data/hora + status (Planejada/Confirmada) + atalho para Planejar.
3. **Participantes numerados** — lista dos membros **numerada**, com **5 bolinhas** das últimas reuniões (verde presente / vermelho ausente) e **alerta amarelo** de cadastro incompleto.
4. **Identificação líder / auxiliar / anfitrião** — pills destacando os três papéis dentro da lista.
5. **Formulário de relatório** — ver seção 6.
6. **Lista de visitantes** — abaixo do formulário do relatório; **acumula**; cada item com nome, contato e marcador "Aceitou Jesus".
7. **Planejamento com 8 etapas** — ver seção 8.
8. **Avisos da célula** — "Da célula" (azul, cria/agenda/expira) + "Da igreja" (vermelho, leitura).
9. **Ações sensíveis** — bloco visualmente distinto (cadeado) para dia/horário/endereço/anfitrião/auxiliar/saída de membro → cada um abre "Solicitar alteração".
10. **Solicitações para a Central** — reflexo do estado das solicitações abertas (pills pendente/aprovada/rejeitada) nas abas Editar célula e Multiplicação.

Componentes de apoio herdados do contrato (seção 9): KPIs da trilha (stat-cards), ficha do discípulo (modal), modais de confirmação/rejeição/ajuste. Não redefinidos aqui.

## 6. Relatório da célula

Preenchido pelo líder após a reunião (rápido, mobile). Campos:

- **Data da reunião** — a ocorrência a que o relatório se refere (pré-preenchida com a última reunião).
- **Presença** — lista de membros com marcação; marcado = **presente**, não marcado = **falta**. Contador de presentes.
- **Faltas** — derivadas da presença (membros não marcados); não é campo separado, é o complemento.
- **Visitantes** — lista dinâmica (ver seção 7): nome, WhatsApp, **Aceitou Jesus? sim/não**.
- **Decisões** — profissões de fé da reunião: visitantes (e membros) que **aceitaram Jesus**; microtexto "quem aceitou Jesus inicia consolidação". Alimenta o módulo Ganhar/Consolidar (leitura, fora deste PRD).
- **Observações** — texto livre do líder sobre a reunião (opcional).
- **Pedidos de oração** — anotações de intercessão levantadas na reunião (opcional).
- **Planejamento** — vínculo com o que foi planejado (tema/etapas); se a mensagem real mudou, o líder atualiza o **tema** aqui.
- Checagens rápidas: **Deu os avisos?** (sim/não) · **Teve oferta?** (sim/não, valor opcional).
- Ação: **"Enviar relatório para a Central"** → confirmação; a reunião passa a **Enviado**.

Abaixo, **"Relatórios anteriores"**: linhas "nº · data · tema · presentes/visitantes" com pill Enviado.

> **Nota de fidelidade:** o protótipo demonstra tema, avisos, oferta, presença e visitantes. Os campos **observações**, **pedidos de oração** e **decisões** explícitas são alvo de produto deste PRD (o protótipo captura decisões via "Aceitou Jesus?" por visitante). Nada contraria o contrato.

## 7. Regras de visitantes

1. O **líder pode adicionar visitante** no relatório da reunião.
2. Ao adicionar, o **visitante aparece abaixo do campo** (lista acumulada).
3. O **formulário limpa** após adicionar, pronto para o próximo.
4. **Pode haver múltiplos** visitantes por reunião.
5. O **visitante do relatório não vira membro automaticamente** — é um registro de comparecimento; quem **aceitou Jesus** entra em **consolidação** (não em membresia direta). A promoção a membro é decisão posterior, fora desta tela.

## 8. Regras de planejamento

1. **8 etapas fixas, nesta ordem e tempos**: 1 Boas-vindas (2') · 2 Louvor (5–10') · 3 Quebra-gelo (5') · 4 Mensagem (20') · 5 Oração por necessidades (5') · 6 Oração de salvação (5') · 7 Oferta (5') · 8 Comunhão (10').
2. Cada etapa pode registrar **responsável** (membro da célula) e **observação** curta, quando necessário. Não é obrigatório preencher todas.
   - **Louvor**: responsável escolhe a música, ou líder seleciona do banco, ou adiciona por link.
   - **Quebra-gelo**: selecionar do banco ou criar novo (nome/conteúdo/tema; tema sugerível por IA).
   - **Mensagem**: sermão da Central, ou sugerir tema, ou tema livre (líder atualiza no relatório se mudar).
3. O **planejamento pertence à reunião/célula** — cada ocorrência tem o seu; data/hora vêm do padrão da célula (alterar dia/hora vira solicitação — seção 9).
4. Confirmar a programação avisa cada responsável no WhatsApp (envio pelo agente do sistema; fora deste PRD).

## 9. Ações que viram solicitação para a Central

Estas ações **não** são aplicadas direto — nascem como **solicitação pendente** e a Central decide (aprovar/rejeitar com motivo/pedir ajuste):

- Alterar **dia**;
- Alterar **horário**;
- Alterar **endereço**;
- Alterar **anfitrião**;
- Alterar **auxiliar**;
- **Transferir membro** (para outra célula);
- **Remover membro** (saída da célula / da igreja);
- **Multiplicar célula** (seção 10).

Contraponto (aplicação **direta**, sem Central): **adicionar/entrada de membro**, editar **dados leves** (nome, link do grupo de WhatsApp, mensagem de convite, link da localização), relatório, planejamento e avisos da própria célula.

Cada solicitação: abre modal (novo valor + **motivo**), envia à Central, mostra pill `warn` "Alteração pendente" junto ao campo e reflete o desfecho (4.6/4.7/4.8).

## 10. Multiplicação

1. O **líder solicita** a multiplicação (aba Multiplicação).
2. Seleciona **novo líder apto** — só membros **aptos = realizaram o Reencontro**; não aptos aparecem **desabilitados** com o motivo ("ainda não fez o Reencontro").
3. Seleciona os **membros que irão** (multi-seleção).
4. Define **dia e hora** da nova célula.
5. Define **endereço**.
6. Define **anfitrião**.
7. (Opcional) **data prevista**.
8. Nasce **pendente**; a **Central aprova ou rejeita** (rejeição com motivo).
9. **Aprovação cria a nova célula**, transfere os membros escolhidos e **atualiza o organograma/Árvore Ministerial**; o novo líder recebe a gestão da célula nova (organograma real fora deste PRD).

## 11. Fora de escopo

- **Visão Discípulo** (PRD próprio).
- **Tela administrativa da Central** (PRD próprio; e invariante: não aparece aqui).
- **Implementação backend** / contratos de API.
- **Envio de WhatsApp** (agente do sistema; aqui só há a intenção, não o disparo).
- **Aprovação real** das solicitações (é ato da Central).
- **Organograma / Árvore Ministerial real** (módulo separado; multiplicação só sinaliza a atualização).
- **Migrations** / modelo de dados implementado.
- UV/CD/Encontro (só citados como KPIs da trilha), Pessoas, Comunicação, billing.

## 12. Dados necessários no futuro

Modelo que a implementação precisará (não faz parte desta entrega; nomes ilustrativos):

1. **Célula** — nome, dados leves (link grupo, mensagem de convite, link localização) e sensíveis (dia, horário, endereço, anfitrião, auxiliar, cobertura). Campos hoje ausentes = bloqueador estrutural.
2. **Reunião / ocorrência** — instância datada (data, hora, tema, status Planejada/Confirmada/Realizada).
3. **Relatório por ocorrência** — presença por membro, visitantes, decisões, observações, pedidos de oração, deu-avisos, oferta.
4. **Planejamento por ocorrência** — as 8 etapas com responsável/observação; tema; música.
5. **Vínculo membro ↔ célula** e papéis (líder/auxiliar/anfitrião).
6. **Solicitação** — tipo (dado sensível / transferência / remoção / multiplicação), valor atual → proposto, motivo, estado (pendente/aprovada/rejeitada/ajuste), autor, decisor.
7. **Aptidão** — flag "realizou Reencontro" por pessoa (governa o select de novo líder).
8. **Histórico de participação e de solicitações** — série temporal para KPIs e auditoria.

Itens **2, 3, 4 e 6** são os que hoje **não existem** e destravam a visão Líder; núcleo do PRD de implementação.

## 13. Critérios de aceite

1. **CA-1 (7 seções)** — a visão Líder expõe exatamente Painel · Editar célula · Avisos · Discípulos · Planejar · Relatório · Multiplicação; **sem** Central.
2. **CA-2 (participantes)** — lista numerada; líder, auxiliar e anfitrião identificados por pill; presença por bolinhas; alerta amarelo em cadastro incompleto.
3. **CA-3 (relatório)** — permite registrar data, presença/faltas, visitantes, decisões, observações e pedidos de oração; "Enviar relatório" marca a ocorrência como Enviado.
4. **CA-4 (visitantes acumulam)** — adicionar visitante o coloca **abaixo** do formulário, **limpa** o form, incrementa a lista; suporta **múltiplos**; visitante **não** vira membro automaticamente.
5. **CA-5 (planejamento)** — 8 etapas fixas na ordem/tempos; responsável e observação por etapa quando necessário; planejamento pertence à ocorrência.
6. **CA-6 (solicitação — sensíveis)** — alterar dia/horário/endereço/anfitrião/auxiliar, transferir/remover membro e multiplicar **abrem solicitação com motivo** e mostram pill "pendente"; o valor **não muda** antes da aprovação.
7. **CA-7 (aplicação direta)** — adicionar membro e editar dados leves aplicam **na hora**, sem Central.
8. **CA-8 (multiplicação)** — o wizard só permite **novo líder apto**; coleta membros, dia/hora, endereço, anfitrião; nasce pendente.
9. **CA-9 (relatório pendente)** — 2h após o horário sem envio, aparece o banner de pendência com atalho de envio.
10. **CA-10 (desfechos)** — solicitação mostra estados pendente (`warn`) → aprovada (`ok`) / rejeitada (`danger` + motivo).
11. **CA-11 (avisos)** — avisos da célula em azul (cria/agenda/expira); da igreja em vermelho (leitura).
12. **CA-12 (sem Central)** — em nenhum estado da visão Líder aparece a tela da Central ou a aprovação das próprias solicitações.
13. **CA-13 (responsivo)** — abas roláveis sem quebrar layout; sem scroll horizontal ≥360px; alvos ≥44px no mobile.

## 14. Perguntas abertas

1. **Dados leves vs. sensíveis** — o protótipo (Editar célula) trata **anfitrião, auxiliar e endereço** como dados leves (salvam direto), mas o **contrato e este PRD** os classificam como **sensíveis** (solicitação). **Decidir a fronteira definitiva** e alinhar protótipo ↔ contrato. (Recomendação: seguir o contrato — sensíveis viram solicitação.)
2. **Um líder, N células** — o modelo permite 1 líder para várias células. Como a visão Líder alterna entre elas (seletor de célula no topo)?
3. **Editar solicitação pendente** — o líder pode cancelar/editar uma solicitação ainda não decidida?
4. **Relatório retroativo** — dá para enviar relatório de reuniões antigas não reportadas, ou só da última?
5. **Reabertura do relatório** — depois de "Enviado", o líder corrige? Precisa de aprovação?
6. **Decisões de membros** — "decisões" cobre só visitantes que aceitaram Jesus ou também reconciliações de membros? Definir o que conta.
7. **Privacidade de observações/pedidos de oração** — quem vê (só líder, Central, célula)?
8. **Auxiliar com poderes** — o auxiliar pode preencher relatório/planejar no lugar do líder? Qual o escopo de escrita do auxiliar?
9. **Multiplicação — cobertura** — a nova célula herda a cobertura da célula-mãe ou a Central redefine na aprovação?

---

### Referências

- [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — contrato vinculante (seção 7 = visão Líder; seção 8 = Central).
- [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md) — a outra visão do mesmo menu.
- [`docs/design/CELULAS-prompt-claude-designer.md`](CELULAS-prompt-claude-designer.md) — design system e regras de negócio.
- Protótipo aprovado: `Igreja12 Prototipo (standalone) refinado.html`.
