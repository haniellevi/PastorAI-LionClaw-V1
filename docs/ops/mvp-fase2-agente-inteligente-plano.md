# Fase 2: agente com decisões tipadas e privilégios

Aprovado com ajustes por Claude + Opencoded, 26/09/2026; S1 autorizada após fechar PR421. Ativação externa continua fechada.
S1 PR422 MERGED por ordem nominal, main `a5244ca`; ativação fechada. S2 candidata separada; merge depende de liberação explícita coordenada com schema/deploy.
Substitui a proposta LLM+moderação. Piloto Filadélfia continua interno, sem divulgar o número.
Base estudada: PR418/419/420 e candidato PR421 `d48b3d2`. Um PR por fatia; priorizar S1, S2 pode seguir em paralelo se houver capacidade.

## Princípio e sequência
Jev é o classificador principal; LLM raciocina sobre contexto permitido e propõe resposta/ação tipada.
Código decide rota, autorização, argumentos e envio. Probabilidade não concede privilégio.
Regex permanece rede mínima; esta fatia não amplia listas de frases nem adiciona moderação OpenAI.
S1: tier A real, fail-safe, flag vazia, corpus congelado e relatório. S2: migration + API + UI de campos públicos, removendo o bloco em `comportamento`; filtrar `Cf` na leitura legada até sua remoção; consultas naturais de culto (que horas começa/é, horário do, quando é) devem usar o cadastro, sem cair no LLM.
1. Validar inbound/tenant e `AgentConfig.ativo`; opt-out reconhecido é persistido primeiro. Termo pendente/estado humano/opt-out não egressam.
2. S3, depois: confirmação Clerk, identidade/papel e ferramentas readonly por papel; Jev B/C/D só entram nessa fatia. Modelo nunca fornece tenant/papel.
3. Só com gates de egress abertos, enviar estado mínimo à primeira decisão Jev.
4. Aplicar decisões abaixo em código; perguntas dependentes só são construídas após a decisora.
5. Executar leitura autorizada, produzir resposta LLM com fatos e revalidar estado antes do envio.

## Perguntas Jev e gates
| Ordem | Primitiva e pergunta | Decisão determinística |
|---|---|---|
| A | Noul: há sinal de crise/autoagressão no contexto atual? | Positivo ou inconclusivo: handoff. |
| A | Noul: a pessoa pede atendimento humano? | Positivo ou inconclusivo: handoff. |
| A | Noul: pede interrupção das mensagens? | Positivo só pede uma confirmação: “Deseja parar de receber mensagens? Responda SAIR”. |
| B | Choice: informação pública, consulta restrita, conversa pastoral, outro? | Só após A liberar; `outro`/incerteza pede esclarecimento sem ferramenta. |
| C | Choice: qual ferramenta entre as permitidas para essa rota/papel, ou nenhuma? | Só após B; catálogo fechado pelo backend, nunca nomes livres. |
| D | Choice: qual candidato autorizado atende ao argumento, ou nenhum? | Só após C e busca autorizada; usar handles opacos por turno, mapeados pelo código para IDs validados. |

Noul retorna probabilidade de sim, sem confiança separada. Limiar e faixa de incerteza são versionados e calibrados só em dev.
Perguntas A são independentes e usam uma única chamada/batch, deadline conjunto de1,2s; não antecipar B/C/D nesse lote.
Só palavra explícita/regex aplica opt-out direto. Confirmação inferida tem dedupe durável por conversa; nunca repetir, reabrir conversa nem superar humano/opt-out/termo/crise.
Erro/timeout/schema inválido em Jev: handoff sem fallback; opt-out já reconhecido sempre persiste e suprime, inclusive com falha simultânea.
Crise/pedido humano do Jev OU regex OU sinal tipado do LLM suprime a resposta gerada e persiste handoff.
LLM não revoga sinal positivo; erro/timeout/schema inválido também causa handoff; não pedir nem guardar cadeia interna de raciocínio.
Reusar supressão durável/CAS do worker para que retry e retorno à IA não ressuscitem resposta descartada.
Termo exige aceite explícito; Jev não cria consentimento/autoridade. Auditar razão enumerada, versão, latência/falhas, sem texto pastoral, telefone, chave ou raciocínio privado.

## Identidade e matriz de leitura (S3)
Vínculo backend: instância WhatsApp → igreja → contato/conversa → pessoa → app_user ativo → UserRole da mesma igreja.
App_user único, com identidade Clerk válida; vínculo ausente, ambíguo ou revogado não concede papel.
`Pessoa.tipo`, telefone, autodeclaração e `leads_cells` isolados não provam privilégio.
Antes de qualquer dado não público, exigir confirmação recente em sessão autenticada do painel/Clerk.
Vincular confirmação a igreja, app_user, conversa e desafio de uso único com expiração; OTP no mesmo WhatsApp não basta.
Revalidar vínculo/papéis por turno e antes do envio; sem confirmação, oferecer só público ou handoff.

| Papel confirmado | Ferramentas/dados máximos na S3 |
|---|---|
| Desconhecido/visitante ou identidade não confirmada | Horário/endereço da igreja e células explicitamente publicados; nenhum cadastro privado. |
| Membro | Público + própria vinculação ativa e agenda que o serviço humano já permite ver. |
| Líder | Acima + células sob sua responsabilidade, nos mesmos limites do serviço humano. |
| Pastor/admin da igreja | Consultas da própria igreja permitidas ao papel no serviço humano; sem privilégio de plataforma. |

Campos S2 são separados do estilo; só projeções validadas/autorizadas chegam às ferramentas/LLM. Ferramentas S3 são tipadas/readonly, com filtro de igreja e RLS.
Reusar autorização/serviços humanos; não expor lista de pessoas, endereço residencial, notas ou conversas privadas nesta fatia.
Negar por padrão operações sem serviço autorizado. Proximidade exige fonte geográfica aprovada; bairro não prova distância.

## Tempo, configuração e dados enviados
Alvo p95 ponta a ponta <10s: deadline monotônico global de 9s, reserva 1s para persistência/retorno; medir cada estágio.
Jev: A≤1,2s; B/C/D≤0,6s cada, total≤3s. LLM≤4s; consultas≤1s. Cada etapa usa min(saldo global menos reserva de1s, teto), sem retry.
Paralelizar só trabalho independente; dependências continuam sequenciais. Saldo insuficiente aciona handoff; testar preservação da reserva.
Novo HTTP Jev/LLM fora de transação/lock; revalidar após cada espera. Lease legado do envio Evolution permanece; alvo total ainda exige medição separada.
Nova flag `JEV_ENABLED_IGREJA_IDS`, vazia por padrão e distinta da lista shadow; shadow nunca ativa decisões.
Reusar chave/modelo/timeout efetivos do PR420, resolvidos em sessão de plataforma; não ler essa tabela pelo tenant.
Ativação S1 exige TAMBÉM metas do holdout aferidas com Wilson95%, além de flag, configuração válida, DPA/registro e decisão nominal de Raniel sobre egress.
Flag ativa vazia desliga decisões Jev; shadow segue gate separado. Zero egress exige ambas listas vazias; nenhuma flag libera piloto público.
LGPD: registrar TypeSafe como destinatário/processador proposto, finalidade, campos, retenção, região e versão do aviso.
Enviar só mensagem/contexto estritamente necessário, com mascaramento existente; nomes, religião e saúde podem permanecer.
Mascaramento parcial não anonimiza. Egress TypeSafe exige decisão nominal de Raniel sobre DPA; testadores internos dão aceite. Nenhuma chamada real nesta preparação.

## Avaliação e entrega
Congelar dev/holdout sintéticos rotulados e hashes antes de ajustar perguntas, limiares ou prompt; separar famílias de paráfrases.
Ajustar só em dev; holdout reservado para avaliação final, incluindo negação, ambiguidade, ataques e pedidos indiretos.
Gate de ativação: crise TP/(TP+FN) ≥90%, FP/(FP+TN) <10% e handoff ≥85% TP, todos aferidos no holdout com Wilson95%.
Relatar TP/FN/FP/TN, tamanhos por grupo, latência p95, erros e intervalos Wilson95%; dimensionar holdout antes do ajuste, sem arredondar para passar.
Medir taxa total de handoff no holdout; teto inicial no piloto: >30% das conversas avaliadas na janela diária pausa o piloto para revisão. Expor numerador/denominador.
CI usa mocks para gates, dependências, timeout, dedupe, revogação, tenant/RLS e retry. Mocks não aferem metas; rodada real só com chave de teste autorizada por Raniel.
Rollback: esvaziar flag por igreja e reverter PR por fluxo normal; eventual erro mantém handoff e piloto restrito.
Sem avaliação real autorizada, S1 pode ser revisada com flag vazia, mas ativação permanece bloqueada. S2/migration e S3 seguem PRs/gates separados; merge não abre egress.

Fontes: [Noul](https://docs.typesafe.ai/primitives/noul), [Choice](https://docs.typesafe.ai/primitives/choice), [roteamento tipado](https://docs.typesafe.ai/cookbooks/function_calling).
