# PRD — Células · Solicitações & Aprovação (Igreja 12)

> **Status:** Rascunho para revisão. Deriva do contrato de UX/UI e dos PRDs Discípulo/Líder, todos já em `main`.
> **Data:** 2026-07-03.
> **Natureza:** docs-only. Nenhum código, migration, env ou deploy nesta entrega.
> **Escopo deste PRD:** o **fluxo transversal de Solicitações & Aprovação** de mudanças sensíveis de célula — do lado do **Líder** (origem) ao lado da **Central** (decisão). É o "contrato de comportamento" que liga a visão Líder à visão Central.

## Fontes de verdade

1. **Contrato UX/UI** — [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) (vinculante). Detalha aqui as seções 8.3 (Central · Solicitações) e 11 (estados pendente/aprovado/rejeitado).
2. **PRD Líder** — [`docs/design/PRD-MINHA-CELULA-LIDER.md`](PRD-MINHA-CELULA-LIDER.md) (origem das solicitações, seção 9).
3. **PRD Discípulo** — [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md) (transferência de discípulo como caso de solicitação).
4. **Protótipo refinado aprovado** — `Igreja12 Prototipo (standalone) refinado.html` (modais Aprovar/Rejeitar/Pedir ajuste).
5. **Regras decididas** (abaixo), que prevalecem em qualquer ambiguidade.

### Regras decididas (travadas)

- A **Central de Células NÃO aparece** dentro de Minha Célula.
- **Dados sensíveis** da célula **não mudam direto** — viram **solicitação** para a Central.
- A Central pode **aprovar**, **rejeitar** ou **pedir ajuste**.
- **Rejeição exige motivo**; **pedir ajuste exige observação**.
- **Aprovação aplica a mudança real** no sistema.
- **Multiplicação passa pela Central**; ao aprovar, a **nova célula é criada, membros são movidos, organograma/dados atualizam e o novo líder recebe a gestão**.
- **Discrepância conhecida (provisória):** o protótipo salva **anfitrião/auxiliar/endereço direto**, mas o contrato/PRD os classificam como **sensíveis**. **Neste PRD, a regra provisória é: seguir o contrato** (esses campos são sensíveis → viram solicitação). Decisão do dono fica **aberta** (seção 16).

---

## 1. Objetivo do fluxo Solicitações & Aprovação

Garantir que toda mudança **sensível** de uma célula seja **proposta pelo líder** e **decidida pela Central**, com trilha de auditoria, sem que o dado real mude antes da aprovação. O fluxo:

- **Protege a rede**: a Central mantém consistência de dias/horários/endereços/lideranças/cobertura.
- **Dá autonomia ao líder** no que é leve, e **governança** no que é sensível.
- **Registra decisões** (quem pediu, quem decidiu, quando, por quê) para histórico e reversão futura.

Não-objetivo: aprovar dados leves (nome, link do grupo, mensagem de convite) — esses aplicam direto e **não** entram neste fluxo.

## 2. Papéis envolvidos

| Papel | No fluxo |
|---|---|
| **Líder solicitante** | Cria a solicitação (sobre a **própria** célula). Responde a pedidos de ajuste. Pode cancelar enquanto pendente (ver 16). |
| **Central de Células** | Recebe a fila, **aprova / rejeita / pede ajuste**. É quem aplica a mudança ao aprovar. Papel de admin/líder da central. |
| **Pastor / Admin (fallback)** | Onde não houver um "líder da central" designado, o pastor/admin exerce o papel da Central. **Fallback**, não um segundo nível de aprovação. (Papel definitivo em aberto — seção 16.) |
| **Membro impactado** | Quando a solicitação afeta uma pessoa (transferência/remoção de membro; multiplicação que move membros). Não decide; é **objeto** da mudança e destinatário de aviso ao aprovar. |

Regra: **quem solicita não aprova a própria solicitação** (segregação de função).

## 3. Tipos de solicitação

1. **Alterar dia** da célula.
2. **Alterar horário**.
3. **Alterar endereço**.
4. **Alterar anfitrião**.
5. **Alterar auxiliar**.
6. **Transferir membro** (para outra célula).
7. **Remover membro** (saída da célula / da igreja).
8. **Multiplicar célula**.
9. **Outros ajustes sensíveis futuros** — o modelo deve ser **extensível por `tipo`** sem quebrar os existentes (novos tipos herdam o mesmo ciclo de vida e auditoria).

> Itens 1–5 (e a discrepância 14.1 do PRD Líder) são classificados como **sensíveis** neste PRD por regra provisória (seguir o contrato).

## 4. Status da solicitação

Máquina de estados:

| Status | Significado |
|---|---|
| `rascunho` *(opcional)* | Líder começou a montar mas não enviou. Pode não existir na 1ª versão (ver 16). |
| `pendente` | Enviada à Central, aguardando decisão. **Estado inicial efetivo.** |
| `ajuste_solicitado` | Central pediu correção; devolvida ao líder com observação. |
| `aprovada` | Central aprovou; **mudança aplicada** (estado terminal). |
| `rejeitada` | Central rejeitou com motivo; **nada muda** (estado terminal). |
| `cancelada` | Líder cancelou antes da decisão (estado terminal; ver 16). |

Terminais: `aprovada`, `rejeitada`, `cancelada`. De `ajuste_solicitado`, o líder reenvia → volta a `pendente`.

## 5. Ciclo de vida

```
[líder cria] ──► pendente ──► (Central decide)
                    │
        ┌───────────┼─────────────┬───────────────┐
        ▼           ▼             ▼               ▼
    aprovada    rejeitada   ajuste_solicitado  cancelada
   (aplica)   (não aplica)      │  (líder)     (líder, não aplica)
                                 ▼
                          [líder corrige] ──► pendente ──► ...
```

1. **Líder cria** a solicitação (tipo + payload proposto + motivo).
2. **Central recebe** na fila (`pendente`).
3. **Central decide**: **aprovar** (aplica) · **rejeitar** (motivo obrigatório) · **pedir ajuste** (observação obrigatória).
4. **Líder responde ajuste**: corrige o payload e reenvia → `pendente` de novo.
5. **Aprovação aplica** a mudança real (transacional — seção 10).
6. **Rejeição / cancelamento não altera** os dados finais.

## 6. Dados comuns da solicitação

Campos que toda solicitação carrega (nomes ilustrativos; modelagem real fora do escopo):

- `igreja_id` — tenant (RLS).
- `celula_id` — célula alvo.
- `solicitante` — usuário/líder que criou.
- `tipo` — um dos itens da seção 3.
- `status` — seção 4.
- `payload_proposto` — objeto tipado por `tipo` (o "valor novo").
- `payload_atual` *(snapshot)* — valor no momento da criação, para exibir "de → para" e detectar conflito (ver 7).
- `motivo` / `observacao` — texto do líder (na criação) e da Central (rejeição/ajuste).
- `aprovado_por` / `rejeitado_por` / `decidido_em` — quem decidiu e quando.
- `timestamps` — `criado_em`, `atualizado_em`, `enviado_em`, `decidido_em`.
- `historico` / auditoria — trilha append-only de transições (quem, de→para status, quando, texto).

## 7. Validações gerais

1. **Tenant** — solicitação e célula pertencem à **mesma `igreja_id`**; nunca cruzar igrejas (RLS por tenant).
2. **Autoria** — o **líder só solicita sobre a própria célula**; não pode abrir solicitação de célula alheia.
3. **Autoridade** — a **Central só decide dentro da própria igreja**; e **quem solicitou não aprova** (segregação).
4. **Payload por tipo** — cada `tipo` valida o próprio payload (seção 8); payload inválido não vira `pendente`.
5. **Imutabilidade até aprovação** — os **dados finais da célula não mudam** enquanto a solicitação não for `aprovada`.
6. **Conflito / staleness** — se o dado atual mudou entre a criação e a decisão (outra solicitação aprovada antes), a aprovação deve **detectar o conflito** (compara `payload_atual` snapshot) e **não** aplicar cegamente — ver perguntas abertas.
7. **Unicidade razoável** — evitar solicitações duplicadas idênticas pendentes para o mesmo (célula, tipo) — ver 16.

## 8. Regras por tipo

### 8.1 Dia / horário / endereço / anfitrião / auxiliar
- Payload: campo alvo + novo valor. `anfitrião`/`auxiliar` referenciam **pessoas** válidas da igreja; `auxiliar` deve ser membro da própria célula.
- Aprovar → atualiza o campo na célula + avisa envolvidos.
- **Regra provisória:** todos os cinco são **sensíveis** (seguir o contrato; discrepância registrada).

### 8.2 Transferência / remoção de membro
- **Transferir membro**: payload = membro + destino (nova célula) **ou** "saída da igreja". A Central, ao aprovar, **aponta a nova célula** OU **registra a saída** (com motivo). Origem: também disparável pela **ficha do discípulo** na visão Líder ("Transferir para a Central") e pela visão Discípulo (contexto de saída).
- **Remover membro**: payload = membro + motivo (saída da célula/igreja). Aprovar → desliga o vínculo membro↔célula.
- **Contraponto direto:** **entrada/adicionar membro é direta** (não passa por este fluxo) — invariante do contrato.
- Ao aprovar, o **membro impactado** é avisado (agente; fora do escopo).

### 8.3 Multiplicação
- Ver seção 9 (regras próprias, por ser a de maior impacto).

## 9. Multiplicação

Regras específicas (o tipo mais complexo):

1. **Novo líder deve ser apto** = realizou o **Reencontro**. Não aptos são **inválidos** no payload (bloqueados na origem, com motivo "ainda não fez o Reencontro").
2. **Selecionar membros que irão** (multi-seleção; subconjunto dos membros da célula-mãe).
3. **Definir dia/hora** da nova célula.
4. **Definir endereço**.
5. **Definir anfitrião**.
6. (Opcional) **data prevista**; **cobertura** herdada da mãe ou redefinida pela Central na aprovação (aberto — seção 16).
7. **Central aprova / rejeita** (rejeição com motivo).
8. **Aprovação (transacional)**: **cria a nova célula** → **move os membros selecionados** para ela → **atualiza vínculos e organograma/Árvore Ministerial** → **atribui a gestão ao novo líder**. Se qualquer passo falhar, **nada é aplicado** (seção 10).

> O detalhamento visual/UX da multiplicação pode ter PRD próprio; aqui fica o **contrato do fluxo de aprovação** da multiplicação.

## 10. Regras de aprovação

1. **Transacional** — aplicar a mudança é **tudo-ou-nada**. Multiplicação (criar célula + mover membros + atualizar organograma) roda numa transação lógica única.
2. **Sem estado parcial** — se falhar no meio, **rollback**; a solicitação **não** vira `aprovada` e a célula fica intacta. Erro é reportado para nova tentativa.
3. **Auditoria obrigatória** — toda aprovação grava `aprovado_por` + `decidido_em` + snapshot do que mudou (de→para).
4. **Idempotência / anti-duplo-clique** — aprovar duas vezes a mesma solicitação **não** aplica duas vezes; uma vez em estado terminal, novas tentativas são no-op (retornam o resultado, não reaplicam). Proteção contra corrida/duplo clique na UI e no servidor.
5. **Revalidação na hora da aprovação** — reconferir aptidão (multiplicação), existência das pessoas e conflito de staleness (seção 7.6) **no momento** de aprovar, não só na criação.

## 11. Regras de rejeição e ajuste

1. **Rejeição exige motivo** (texto obrigatório); o líder recebe o motivo (agente).
2. **Pedir ajuste exige observação** (texto obrigatório) do que corrigir.
3. **Rejeição não altera a célula** (estado terminal, nada aplicado).
4. **Ajuste não altera a célula** até uma **nova aprovação**; a solicitação volta ao líder (`ajuste_solicitado`) e, ao reenviar, retorna a `pendente`.
5. Motivo/observação entram na **auditoria**.

## 12. Impactos em UI

- **Minha Célula / Líder**: mostra as **solicitações pendentes** e seus desfechos — pill `warn` "Em análise" junto ao campo (Editar célula) e na aba Multiplicação; `ok` "Aprovada" / `danger` "Rejeitada" + motivo.
- **Central**: **fila de solicitações** (aba Solicitações) com tipo, célula, líder, resumo "de → para", data; ações **Aprovar** (abre **confirmação de segurança** listando o que muda) · **Rejeitar** (modal exige motivo) · **Pedir ajuste** (modal exige observação).
- **Estados visíveis**: aprovado/rejeitado/ajuste ficam claros em ambas as pontas; rejeição sempre mostra o motivo.
- **Anti-ilusão de escrita direta** — nos campos sensíveis do líder, o controle é **"Solicitar alteração"** (com cadeado), **nunca** um "Salvar" que finja aplicar direto. O usuário precisa entender que **depende da Central**.
- **Vazio** — fila da Central sem itens mostra empty state "Nenhuma solicitação pendente." (contrato).

## 13. Fora de escopo

- **Implementação backend** / contratos de API / máquina de estados em código.
- **Migrations** / modelo de dados implementado.
- **Tela completa da Central** (tem PRD próprio; aqui só a fatia "Solicitações").
- **Envio de WhatsApp** (agente; aqui só a intenção de avisar).
- **Organograma / Árvore Ministerial visual completo** (módulo separado; multiplicação só sinaliza a atualização).
- **PRD de multiplicação detalhado** (UX passo-a-passo), se tratado separadamente — aqui fica o fluxo de aprovação.
- Dados leves (nome, link do grupo, mensagem de convite) — aplicam direto, **não** entram neste fluxo.

## 14. Dados necessários no futuro

Modelo que a implementação precisará (nomes ilustrativos; fora desta entrega docs-only):

1. **Solicitação** — todos os campos da seção 6 (`igreja_id`, `celula_id`, `solicitante`, `tipo`, `status`, `payload_proposto`, `payload_atual`, `motivo/observacao`, `aprovado_por`/`rejeitado_por`, timestamps).
2. **Transições / auditoria** — tabela append-only de mudanças de status (quem, de→para, quando, texto) por solicitação.
3. **Payloads tipados** — schema por `tipo` (dia/hora/endereço/anfitrião/auxiliar; transferência/remoção; multiplicação com novo líder + membros + dia/hora + endereço + anfitrião).
4. **Célula** — os campos sensíveis alvo (dia, horário, endereço, anfitrião, auxiliar, cobertura) e vínculos membro↔célula.
5. **Aptidão** — flag "realizou Reencontro" por pessoa (valida novo líder na multiplicação).
6. **Permissões** — quem é "Central" por igreja (papel), para autorização de decisão; fallback pastor/admin.

Núcleo que hoje **não existe**: a própria entidade Solicitação + auditoria + payloads tipados + papel "líder da Central".

## 15. Critérios de aceite

1. **CA-1 (origem)** — mudança de dado sensível pelo líder cria uma solicitação `pendente` e **não** altera a célula.
2. **CA-2 (tipos)** — o fluxo cobre os 8 tipos (dia, horário, endereço, anfitrião, auxiliar, transferir membro, remover membro, multiplicar) e é **extensível** por `tipo`.
3. **CA-3 (segregação)** — quem solicitou **não** consegue aprovar a própria solicitação; a Central só decide na própria igreja.
4. **CA-4 (aprovar aplica)** — aprovação muda o dado real e grava auditoria (`aprovado_por` + snapshot de→para).
5. **CA-5 (rejeitar/ajuste)** — rejeição **exige motivo** e não altera a célula; pedir ajuste **exige observação** e devolve ao líder sem aplicar.
6. **CA-6 (imutabilidade)** — em `pendente` / `ajuste_solicitado` / `rejeitada` / `cancelada`, os dados finais permanecem inalterados.
7. **CA-7 (multiplicação transacional)** — aprovar multiplicação cria célula + move membros + atualiza organograma numa transação; falha parcial faz rollback e **não** marca `aprovada`.
8. **CA-8 (apto)** — multiplicação só aceita **novo líder apto** (Reencontro); não apto é bloqueado na origem e revalidado na aprovação.
9. **CA-9 (idempotência)** — aprovar duas vezes não aplica em dobro; estado terminal é no-op.
10. **CA-10 (UI honesta)** — campos sensíveis do líder usam "Solicitar alteração" (não "Salvar" direto); pills refletem pendente/aprovada/rejeitada em ambas as pontas.
11. **CA-11 (tenant)** — nenhuma solicitação/decisão cruza igrejas.
12. **CA-12 (entrada direta)** — adicionar/entrada de membro **não** passa por solicitação.

## 16. Perguntas abertas

1. **Papel definitivo da Central** — existe um papel formal "líder da Central" por igreja, ou é sempre pastor/admin? Como se atribui? (define autorização de decisão).
2. **Anfitrião / auxiliar / endereço — sensível ou direto?** Discrepância herdada (PRD Líder 14.1): protótipo salva direto, contrato classifica como sensível. **Regra provisória aqui = sensível (seguir contrato)**; decisão do dono **pendente** — pode reduzir a lista de tipos sensíveis.
3. **Cancelamento pelo líder** — o líder pode **cancelar** uma solicitação `pendente` (e existe `rascunho`)? Este PRD assume que **sim** (status `cancelada`), a confirmar.
4. **Central edita payload antes de aprovar?** — a Central pode **corrigir** o valor proposto e aprovar já ajustado, ou só aprovar/rejeitar/pedir-ajuste como está? (afeta segregação e auditoria).
5. **Notificações** — aprovação/rejeição/ajuste notificam o **líder**? E o **membro impactado** (transferência/remoção/multiplicação)? Por qual canal (agente/WhatsApp)?
6. **Membro impactado em transferência/remoção** — o membro precisa **consentir** ou é decisão pastoral unilateral? O que ele vê na visão Discípulo durante uma transferência pendente (qual célula aparece)?
7. **Conflito / staleness** — se o dado mudou entre criação e decisão, a aprovação deve reabrir/pedir ajuste automaticamente, ou aplicar sobre o valor mais novo? (seção 7.6).
8. **Duplicidade** — bloquear duas solicitações pendentes idênticas para o mesmo (célula, tipo)?

---

### Referências

- [`docs/design/CONTRATO-UX-CELULAS-CENTRAL.md`](CONTRATO-UX-CELULAS-CENTRAL.md) — seções 8.3 (Solicitações) e 11 (estados).
- [`docs/design/PRD-MINHA-CELULA-LIDER.md`](PRD-MINHA-CELULA-LIDER.md) — origem (seção 9) e discrepância 14.1.
- [`docs/design/PRD-MINHA-CELULA-DISCIPULO.md`](PRD-MINHA-CELULA-DISCIPULO.md) — transferência de discípulo.
- Protótipo aprovado: `Igreja12 Prototipo (standalone) refinado.html` (modais Aprovar/Rejeitar/Pedir ajuste).
