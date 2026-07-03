# PRD — Minha Célula · Visão Discípulo (Igreja 12)

> **Status:** Rascunho para revisão. Deriva do contrato de UX/UI já vinculante em `main`.
> **Data:** 2026-07-03.
> **Natureza:** docs-only. Nenhum código, migration, env ou deploy nesta entrega.
> **Escopo deste PRD:** apenas a **visão Discípulo** do menu **Minha Célula**. A visão Líder e a Central de Células têm PRDs próprios.

## Fontes de verdade

1. **Contrato UX/UI** — [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) (já em `main`, vinculante). Este PRD detalha a seção 6 (Visão Discípulo) e não pode contrariar seus invariantes (seção 15 do contrato).
2. **Protótipo refinado aprovado** — `Igreja12 Prototipo (standalone) refinado.html` (base visual da tela do discípulo).
3. **Regras decididas** (abaixo), que prevalecem em qualquer ambiguidade.

### Regras decididas (travadas)

- O menu chama-se **"Minha Célula"**.
- A **visão Discípulo** é para o **membro** da célula.
- **"Confirmar presença"** = o próprio membro confirma que vai à próxima célula.
- **"Confirmar expectativa"** = o membro informa que espera **levar visitante**.
- A expectativa registra **nome do visitante** + **observação / pedido de oração**.
- Visitantes adicionados **aparecem abaixo do campo** e o **formulário limpa** para adicionar outro.
- **Participantes** da célula aparecem **numerados**.
- Mostrar **líder, auxiliar e anfitrião**.
- Mostrar **histórico do membro**: participou / faltou.
- A **Central de Células não aparece dentro de Minha Célula** (invariante do contrato).

---

## 1. Objetivo da visão Discípulo

Dar ao membro uma tela **única, acolhedora e sem jargão de gestão** que responda três perguntas:

- **Quando e onde é minha próxima célula?** (e confirmar que eu vou)
- **Estou esperando levar alguém?** (registrar expectativa de visitante para a célula orar junto)
- **Quem é minha célula e como tenho participado?** (participantes, avisos, histórico)

Metas de produto:
- Aumentar **confirmação de presença** antes da reunião (previsibilidade para o líder).
- Estimular o **evangelismo relacional** capturando expectativa de visitante com antecedência.
- Dar **pertencimento** (ver a célula, os líderes, o próprio histórico) sem expor gestão.

Não-objetivos: gerir a célula, ver dados de outros membros, aprovar nada, enviar relatório.

## 2. Persona / papel que acessa

- **Papel:** `Discípulo` (membro de uma célula). É o papel mais restrito do módulo.
- **Contexto de uso:** predominantemente **mobile**, entre um culto e outro, em poucos segundos. Baixo letramento administrativo. Precisa de linguagem leve.
- **O que enxerga:** apenas a **sua** célula, a **sua** próxima reunião e o **seu** histórico.
- **O que NÃO enxerga:** relatórios, dados cadastrais de outros membros, gestão da célula, e **nunca** a Central de Células.
- **Vínculo:** um membro pertence a **uma** célula ativa por vez (ver seção 7, vínculo membro ↔ célula). Casos de 0 células ou transição são tratados nos estados (seção 4).

## 3. Navegação — menu Minha Célula

- Item de menu **"Minha Célula"** no grupo **GESTÃO** da sidebar.
- Ao entrar, o membro cai direto na **visão Discípulo** (tela única). No produto real, quem é membro **só** vê esta visão; o alternador "Visão discípulo | Visão líder" do protótipo é recurso de demonstração e **não** é papel de produto.
- A visão Discípulo é **uma tela por vez** (sem telas empilhadas), com rolagem vertical.
- **Invariante:** a Central de Células **não** aparece aqui — vive em Jornada G12 → Discipular → Central de Célula, e só para admin/líder da central.

## 4. Estados da tela

| # | Estado | Comportamento |
|---|--------|---------------|
| 4.1 | **Sem célula** | Membro não vinculado a nenhuma célula ativa. Empty state acolhedor: "**Você ainda não está em uma célula.**" + orientação para procurar a liderança / aguardar convite. Sem hero, sem presença, sem histórico. (Único caminho de entrada de membro é **direto pelo líder** — ver contrato; o discípulo não se auto-vincula aqui.) |
| 4.2 | **Com célula ativa** | Estado base: hero da célula (nome, líder·auxiliar, dia·hora, endereço) + ações (Convidar amigo, Grupo no WhatsApp se houver link, Localização se houver link). |
| 4.3 | **Próxima reunião disponível** | Existe uma ocorrência futura da célula. Mostra o card "Próxima célula" (data/hora/tema) + os dois contadores dinâmicos (**participantes confirmados** / **visitantes esperados**) + fluxo ① presença e fluxo ② expectativa habilitados. |
| 4.3b | **Sem próxima reunião definida** | Não há ocorrência futura agendada. O card "Próxima célula" mostra estado neutro ("Próxima reunião ainda não definida") e **desabilita** presença/expectativa. (Ver perguntas abertas.) |
| 4.4 | **Presença já confirmada** | Botão de presença vira estado verde **"Presença confirmada"**; o contador "participantes confirmados" reflete a confirmação. O membro pode **desfazer** a confirmação (toggle), refletindo no contador. |
| 4.5 | **Expectativa registrada** | Há ≥1 visitante esperado. Cada visitante aparece na **lista de visitantes esperados** abaixo do formulário; o contador "visitantes esperados" reflete a contagem; o formulário fica **limpo** e pronto para adicionar outro. |
| 4.6 | **Histórico vazio** | Membro sem reuniões passadas (recém-adicionado). Empty state: "**Seu histórico aparece aqui.**" + microtexto ("depois da sua primeira célula"). |
| 4.7 | **Histórico com dados** | Card rolável com linhas por reunião: nº, tema, pill **participou** (verde) / **faltou** (vermelho), presentes/visitantes, data. |

Combinações válidas: 4.2 é pré-requisito de 4.3–4.7. 4.4 e 4.5 são independentes (posso confirmar presença sem expectativa e vice-versa — ver regra 6.2).

## 5. Componentes da tela

1. **Card da próxima célula (hero + próxima reunião)**
   - Hero: nome da célula, "Líder X · Auxiliar Y", dia·hora, endereço; ações Convidar amigo / Grupo no WhatsApp / Localização.
   - Sub-card "Próxima célula": data/hora + tema; abaixo, **dois contadores dinâmicos**: `participantes confirmados` e `visitantes esperados`.
2. **Botão Confirmar presença** (Fluxo ①)
   - Rótulo numerado "1 · Sua presença". Botão **"Confirmar minha presença"** → estado verde **"Presença confirmada"** (toggle). Atualiza o contador de participantes confirmados.
3. **Bloco Confirmar expectativa** (Fluxo ②)
   - Separado por divisória, rótulo numerado "2 · Expectativa de visitante".
   - Texto guia: *"Você está esperando levar alguém? Informe o nome para a célula orar junto."*
   - Gatilho **"Confirmar expectativa de visitante"** que revela o formulário.
4. **Formulário de visitante**
   - Campos: **nome do visitante** (obrigatório) + **observação / pedido de oração por essa pessoa** (opcional).
   - Botão **"Confirmar expectativa"**. Ao confirmar: adiciona à lista, **limpa o formulário**, mantém o bloco aberto para adicionar outro.
5. **Lista de visitantes esperados**
   - Aparece **abaixo** do formulário; **acumula** (não substitui). Cada item: nome + (opcional) resumo da observação. Atualiza o contador "visitantes esperados".
6. **Participantes numerados**
   - Lista dos membros da célula, **numerados**.
7. **Identificação líder / auxiliar / anfitrião**
   - Dentro dos participantes: **Líder** (pill), **Auxiliar** (pill) e **Anfitrião** (pill) destacados; demais numerados na sequência.
8. **Histórico**
   - Card rolável (rolagem interna) com as reuniões passadas do membro e a pill participou/faltou (seção 4.7).

> Componentes de apoio herdados do contrato (seção 9): mural de avisos (igreja vermelho / célula azul, ação "Visto" que some do mural), modal "Convidar amigo" (mensagem configurada pelo líder + Copiar/Enviar). Reaproveitam os componentes já definidos; não são redefinidos aqui.

## 6. Regras de negócio

1. **Presença é do próprio membro** — só o membro confirma a **própria** presença; ninguém confirma por ele nesta tela. É reversível (toggle) até a reunião.
2. **Expectativa não substitui presença** — são fluxos **independentes**: registrar expectativa de visitante **não** confirma presença, e confirmar presença **não** cria expectativa. Os dois contadores são distintos.
3. **Pode haver mais de um visitante esperado** — o membro adiciona **N** visitantes; cada um vira um item na lista de visitantes esperados; o formulário limpa entre um e outro.
4. **Visitante esperado NÃO vira pessoa cadastrada automaticamente** — é apenas uma **expectativa/alvo de oração** vinculada à ocorrência da célula. O cadastro de pessoa só acontece quando o visitante **realmente comparece** e é lançado pelo líder no relatório (fora deste PRD).
5. **Observação / pedido de oração é opcional** — o nome do visitante é obrigatório; a observação não.
6. **Membro não edita dados sensíveis da célula** — dia, horário, endereço, anfitrião, auxiliar, entrada/saída de membro são geridos por líder/Central (ver contrato). O discípulo **só lê** esses dados no hero.

Regras herdadas do contrato aplicáveis a esta tela:
- Avisos: **igreja = vermelho, célula = azul**; aviso vencido ou marcado "Visto" **some** do mural.
- Contadores "participantes confirmados" e "visitantes esperados" são **dinâmicos** e refletem as ações do membro em tempo real.

## 7. Dados necessários no futuro

Modelo de dados que a implementação precisará (não faz parte desta entrega docs-only; nomes ilustrativos):

1. **Reunião / ocorrência da célula** — instância datada de uma célula (data, hora, tema, status). Hoje **inexistente** no modelo — é bloqueador estrutural conhecido.
2. **Presença por reunião** — vínculo (membro, ocorrência) com estado confirmado/compareceu; base dos contadores e do histórico participou/faltou.
3. **Expectativa por reunião** — intenção do membro de levar visitante, atrelada a uma ocorrência (contador "visitantes esperados").
4. **Visitante esperado** — nome + observação/pedido de oração, ligado à expectativa; **não** é um registro de pessoa cadastrada (regra 6.4).
5. **Vínculo membro ↔ célula** — qual célula ativa o membro pertence (dirige o estado 4.1 vs 4.2 e o que a tela mostra).
6. **Histórico de participação** — série das ocorrências passadas do membro com presença/ausência (alimenta 4.7).

Observação: itens 1–3 são os que hoje **não existem** e destravam esta visão; são o núcleo do PRD de implementação.

## 8. Fora de escopo

- **Visão Líder** de Minha Célula (PRD próprio).
- **Central de Células** (PRD próprio; e invariante: não aparece aqui).
- **Aprovação de solicitações** (fluxo da Central).
- **Relatório da célula** (visão Líder — inclusive o lançamento do visitante que **compareceu**).
- **Multiplicação** de célula.
- **Envio de WhatsApp** (agente do sistema; aqui só há links "Convidar amigo"/"Grupo", não disparo automático).
- Edição de dados sensíveis da célula, cadastro de pessoas, trilha/consolidação.

## 9. Critérios de aceite

Dado um membro com célula ativa e próxima reunião disponível:

1. **CA-1 (presença)** — ao tocar "Confirmar minha presença", o botão vira "Presença confirmada" (verde) e o contador "participantes confirmados" incrementa em 1; tocar de novo **desfaz** e decrementa.
2. **CA-2 (expectativa independente)** — registrar expectativa **não** altera o estado de presença, e confirmar presença **não** abre/registra expectativa.
3. **CA-3 (expectativa — nome obrigatório)** — o botão "Confirmar expectativa" só efetiva com **nome** preenchido; observação pode ficar vazia.
4. **CA-4 (acúmulo)** — ao confirmar uma expectativa, o visitante aparece **abaixo** do formulário, o formulário **limpa**, o contador "visitantes esperados" incrementa, e é possível adicionar **outro** sem recarregar.
5. **CA-5 (não vira cadastro)** — nenhum visitante esperado gera registro de pessoa cadastrada nem entra em consolidação nesta tela.
6. **CA-6 (participantes)** — a lista de participantes mostra **líder**, **auxiliar** e **anfitrião** identificados e os demais **numerados**.
7. **CA-7 (histórico)** — cada reunião passada do membro exibe pill **participou** (verde) ou **faltou** (vermelho); histórico vazio mostra empty state.
8. **CA-8 (avisos)** — avisos da igreja aparecem em vermelho e da célula em azul; marcar "Visto" remove o aviso do mural.
9. **CA-9 (leitura de dados sensíveis)** — o membro vê dia/hora/endereço/anfitrião no hero mas **não** tem controle de edição.
10. **CA-10 (sem Central)** — em nenhum estado desta tela aparece a Central de Células ou ações de gestão.
11. **CA-11 (sem célula)** — membro sem vínculo vê o empty state 4.1, sem hero/presença/histórico.
12. **CA-12 (responsivo)** — sem scroll horizontal em ≥360px; alvos de toque ≥44px no mobile (conforme contrato).

## 10. Perguntas abertas

1. **Janela de confirmação** — presença/expectativa ficam abertas de quando até quando? (ex.: da abertura da ocorrência até o horário da reunião; reabrir a cada nova ocorrência). Impacta o estado 4.3b.
2. **Cancelar expectativa** — o membro pode **remover** um visitante já adicionado à lista (e decrementar o contador)? O protótipo hoje só adiciona.
3. **Uma expectativa por visitante vs. lista livre** — limite de nº de visitantes esperados por membro/ocorrência?
4. **Persistência da observação/oração** — para quem fica visível o pedido de oração (só líder? célula toda no mural interno?). Definir privacidade.
5. **Reaproveitar visitante recorrente** — se o mesmo visitante é esperado em semanas seguidas, é sempre entrada nova ou há sugestão de nomes anteriores?
6. **Múltiplas células** — regra confirma 1 célula ativa por membro; tratar transição (transferência pendente) — qual célula a tela mostra durante uma transferência em análise?
7. **Notificação ao líder** — a confirmação/expectativa do membro dispara aviso ao líder? (fora do escopo de envio de WhatsApp, mas decide o valor do dado).

> **Nota de fidelidade ao protótipo:** o protótipo aprovado demonstra o fluxo de expectativa com **um** visitante simulado (nome + observação + confirmar) e contadores estáticos que reagem ao toggle. Este PRD define o alvo de produto: **múltiplos** visitantes acumulando abaixo do formulário (regra 6.3 / CA-4), alinhado ao padrão já provado na visão Líder (relatório). Nada aqui contradiz os invariantes do contrato.

---

### Referências

- [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — contrato vinculante (seção 6 = visão Discípulo).
- [`docs/design/CELULAS-prompt-claude-designer.md`](CELULAS-prompt-claude-designer.md) — design system e regras de negócio.
- Protótipo aprovado: `Igreja12 Prototipo (standalone) refinado.html`.
