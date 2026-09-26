# MVP fase 2, fatia 2: handoff e consultas públicas

Base inicial: `b45e99408feb33531c4d11500c7661c212f17c9c` (merge #419).
Base integrada: `7480eac9fa349e89d1a4d9baa9d9b1d3195923bd` (merge #420).
Ambiente de implementação e testes: local, fixtures sintéticas. Nenhum acesso
a DEV, PROD, VPS, banco real, provedor ou credencial.

## Comportamento

Pedidos como “gostaria de falar com o pastor”, “chama alguém”, “chamem um
pastor”, “quero um humano” e o sinal “me sinto sem vontade de viver” passam
pelo handoff determinístico. Negação direta, acentos e caixa são exercitados
nos testes. A regra continua limitada às formas previstas; não é uma avaliação
clínica nem uma garantia de reconhecer toda crise.

O avaliador J0 consulta a regra real. Seu sinal local de risco é um proxy de
encaminhamento, que também pode marcar pedido de atendimento humano. Handoff
é medido separadamente contra rótulos sintéticos do corpus. O Jev não fornece
uma probabilidade dedicada a handoff: o relatório identifica esse braço como
N/A, sem inventar resultado nem usá-lo nos critérios de GO do provedor.
Nenhuma chamada real ao Jev é necessária para o baseline.

Consultas de horário e endereço usam informações públicas explicitamente
preenchidas no perfil do agente da própria igreja. A resposta é determinística
e não chama o LLM. O caminho confirma a mensagem persistida, a configuração
da igreja e a rota elegível, respeitando consentimento, opt-out, handoff e os
gates de ativação existentes. Não aplica coleta de cadastro nem ferramentas
de escrita ao responder a uma consulta pública.

Células são indicadas somente por bairro publicado nesse perfil. Não há
cálculo de distância, geocodificação, leitura de endereço residencial da tabela
Celula, endereço da Pessoa, agenda interna ou abertura de permissões. Bairro
sem informação ou ambíguo gera uma limitação explícita; o resultado nunca é
anunciado como a célula geograficamente mais próxima.

## Configuração e exemplos

No campo Comportamento do agente, o administrador pode manter o texto livre
e acrescentar um único bloco opcional como este exemplo sintético:

```text
[informacoes_publicas]
endereco_igreja = Rua Exemplo, 100
horarios_culto = Domingo, 19h
celula = Centro | Esperança | terça, 19h
celula = Vila Nova | Caminho | quinta, 20h
[/informacoes_publicas]
```

Use somente conteúdo institucional aprovado para divulgação. O bloco aceita
as chaves `endereco_igreja`, `horarios_culto` e até cinco linhas `celula`, com
dois separadores `|` exatos. Não inclua endereço residencial, telefone ou
nome de anfitrião. Há uma indicação por bairro; duplicata, linha inválida,
campo desconhecido ou excesso invalida o bloco, sem inferir dados alternativos.
Encontro de célula aceita dia da semana e horário opcional, por exemplo
`terça, 19h` ou `quinta, 20:30`. O terceiro campo pode ficar vazio.

O perfil completo deve ter até 4.000 caracteres, cada valor até 400 e a
resposta até 1.600. Se o perfil exceder o limite, a consulta não usa o bloco.
O bloco público inteiro é excluído do perfil enviado ao LLM no WhatsApp e no
painel, inclusive quando inválido; somente o texto externo permanece. Parser e
filtro usam o mesmo reconhecedor NFKD/casefold, aceitando acentos, colchetes,
chaves, parênteses e os separadores sublinhado, hífen ou espaço.
Delimitadores malformados também devem falhar fechados. A resposta pública
registra evento de auditoria sem copiar pergunta ou dados do perfil.

Exemplos de consultas: `que horas é o culto?`, `onde fica a igreja?` e
`célula no bairro Centro`, `tem célula no bairro Centro?` e
`a que horas começa o culto?`. O bairro é comparado sem acentos e sem distinção
de maiúsculas, com correspondência completa. Sem dado configurado, o agente
informa que não o encontrou. Um pedido de proximidade sem bairro não expõe
uma lista nem usa localização da pessoa.

## Verificação e rollback

No primeiro candidato integrado, test-local passou com 5.167 testes backend,
864 frontend e verificação de tipos; PostgreSQL 17.6 descartável passou 322
casos RLS, sem skip. A revisão encontrou dois P2 no parser/intenção, corrigidos
com testes antes do candidato final; sua validação será registrada no PR. Testes
sintéticos não provam deploy, conteúdo de uma igreja real ou qualidade geral
das respostas do modelo.

Sem migration ou mudança de RLS. Rollback de código por revert do PR; nenhum
serviço, provedor ou dado de produção foi alterado nesta missão.

## Limite medido e restrição do piloto

Baseline offline do corpus versionado (216 frases sintéticas, sem `--jev`):

| Sinal local | TP | FN | FP | TN |
|---|---:|---:|---:|---:|
| Risco, proxy de encaminhamento | 5 | 38 | 7 | 166 |
| Handoff | 10 | 38 | 2 | 166 |

O corpus mede casos rotulados, não tráfego real. As frases pontuais desta
fatia passam, mas as regras deixam muitos sinais do corpus sem encaminhamento.
Consenso de 26/09: Filadélfia fica restrita a testadores internos da equipe
pastoral; não divulgar o número ao público até a nova detecção ser avaliada.
A direção posterior substituiu LLM com moderação por um plano de decisões
Jev tipadas, raciocínio LLM, privilégios confiáveis e consultas por papel/RLS.
Esse plano exige aprovação dos conselheiros antes de implementação; não há
classificador novo nem chamadas de provedor neste PR.
