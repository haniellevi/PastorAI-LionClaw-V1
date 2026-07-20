# Smoke autenticado - release b5b990d (W5A + dedupe + JWT) - 2026-07-18

**Ambiente:** producao, `https://app.igreja12.com.br` e `https://admin.igreja12.com.br`
**Release verificado:** `b5b990d` (PR#188) + `fcdb81c` (main atual)
**Usuario:** Raniel Levi Lemos Lima (papeis: admin, pastor)
**Metodo:** navegacao assistida no navegador com o dono logado; verificacao do
primitive de dialogo `ds/Dialog` (abertura, backdrop, foco inicial, Escape e
retorno de foco ao gatilho) nas familias de dialogo migradas no release.

## Resultado: PASS

### Dialogos exercitados diretamente (5 componentes, 4 telas)

| Dialogo | Origem | Tela | Abriu | Backdrop | Foco/trap | Esc fecha | Foco volta ao gatilho |
|---|---|---|---|---|---|---|---|
| Conectar a celula (LinkCell) | W4A | Jornada > Ganhar | ok | ok | ok | ok | ok |
| Novo contato | W4A | Pessoas (admin) | ok | ok | foco no 1o campo | ok | ok |
| Editar papeis (inline EquipeScreen) | FECH-04 | Usuarios do Sistema (admin) | ok | ok | ok | ok | ok |
| Editar pessoa (EditContactModal) | FECH-03 | Inbox > painel do contato | ok | ok | foco no 1o campo | ok | ok |
| Painel do contato (ContactPanel, aside) | FECH-04 | Inbox | abre/fecha como drawer nao-modal, sem `role="dialog"`; sem regressao | - | - | ok | ok |

Observacoes relevantes:
- O "Editar pessoa" e um dialogo ANINHADO dentro do painel lateral do contato;
  Escape fechou o dialogo e o painel, devolvendo o foco ao botao de informacoes -
  prova o retorno de foco encadeado do `ds/Dialog`.
- Legendas de deduplicacao por telefone ("Usado para deduplicar contatos na
  igreja." no Novo contato; "Mudar o telefone re-verifica duplicidade na igreja."
  no Editar pessoa) presentes - superficie do fix FECH-01 (MEDIO-004) exposta.

### Cobertos pelo mesmo primitive (nao exercitados 1 a 1)

Os demais dialogos migrados no release usam o MESMO componente `ds/Dialog`, cujo
comportamento foi provado acima em 4 familias distintas: DecisionModal,
TrackModal (consolidacao), CellFormModal, InviteMemberModal (celulas), AuditModal
e PlanosManagerModal (admin). Risco de regressao especifica: baixo.

### Papeis e status (verificacao visual)

Pills de papel/tipo/status renderizando corretamente em "Usuarios do Sistema"
(Membro, Lider de Celula, Administrador, Lider G12; status Ativo), em "Pessoas"
(Contato, Ganhar, contadores por filtro) e na lista de "Conversas" (Pastor,
Membro, Sem interesse).

### Nota de pendencia (nao e defeito)

O rotulo "Sem interesse (CSIM)" ainda aparece com esse texto em Pessoas e
Conversas - esperado: a renomeacao para "Fora da igreja" e a missao ROTULO-1,
decidida em 2026-07-18 e ainda nao implementada.

## Fora deste smoke

- Agenda (criacao/edicao de evento, W3) e arquivamento de Pessoa: entregas
  ANTERIORES ao release b5b990d; permanecem no escopo do EVID-1 historico, nao
  neste registro.
