# V1a: relatório de célula por texto

Candidato implementado sobre a S3 `f2a532a`, com gates de ativação fechados. O [plano aprovado](../mvp-v1-relatorio-celula-whatsapp-plano.md) separa esta fatia do áudio, reservado à V1b. A [matriz de aceite](ACCEPTANCE.md) distingue requisitos das evidências de execução.

## Contrato

O líder identifica os quatro agregados por texto: presentes, visitantes, decisões e oferta total. Campos ausentes continuam vazios até serem declarados. O resumo identifica a ocorrência e precisa ser entregue antes de um novo `SIM`. Correções invalidam a proposta anterior; a confirmação vale por dez minutos. A proposta e o comprovante reutilizam a S3.

Oferta é somente total declarado em centavos. A contagem de decisões não cria pessoas ou consolidações. Identidade, igreja, liderança e reunião vêm do servidor; o modelo não escolhe esses identificadores.

Consentimento exige o termo LGPD vigente, versão, timestamp e ausência de revogação. E4B permanece pausado no MVP. O aviso de lembrete e `PARAR LEMBRETES` são persistidos; `SAIR` tem precedência global. Dados ilegíveis ou ambíguos negam a operação.

Lembretes usam intenção durável, no máximo uma por líder em 24 horas. A janela é 08h–21h em São Paulo, a partir de duas horas após a reunião. Claim e revalidação são confirmados antes do transporte, sem conexão de banco aberta durante HTTP. Falhas comprovadamente pré-envio têm duas retries; resultados ambíguos ficam para conciliação.

## Dados transitórios e custo

O rascunho dura no máximo 24 horas. Cancelamento ou expiração da proposta exige limpeza em até uma hora. Resumo comprovadamente não entregue deve ser apagado; histórico entregue ou de entrega ambígua permanece privado, separado do rascunho. O relatório confirmado e o comprovante não dependem do conteúdo transitório.

Parser determinístico primeiro, sem LLM para valores numéricos reconhecidos. A extração opcional recebe somente campos rotulados por extenso ainda não resolvidos, sem texto bruto, nomes ou histórico; o modelo não pode substituir os valores já reconhecidos. Observações explícitas e entradas inválidas recebem pedido de esclarecimento antes de qualquer reserva paga. Cada relatório admite até quatro extrações, com reserva antes de qualquer chamada paga: US$0,10 por relatório e US$2 por igreja/dia UTC. Preço desconhecido ou teto excedido nega a chamada. Testes usam mocks; não há medição real de qualidade, latência ou cobrança nesta missão.

## Verificação e limite

A [validação final](VALIDATION.json) registra os testes locais, hashes do candidato e limites da prova. Os demais relatórios deste diretório preservam etapas intermediárias; falhas nelas descritas foram corrigidas no candidato final. Revisão independente de fonte: [outbox](REVIEW-OUTBOX-DELTA.md), [orçamento/finalizador](REVIEW-BUDGET-FINAL.md) e [extração/cron](REVIEW-EXTRACTION.md).

Mensagens distintas enviadas simultaneamente podem consumir duas reservas permitidas e produzir handoff por revisão desatualizada. A revisão do rascunho impede sobrescrita; não há serialização nova por rascunho nesta fatia.

## Gates e reversão

`CELL_REPORT_ENABLED_IGREJA_IDS` nasce vazia e `CELL_REPORT_APPROVED_RELEASE_ID=None`; a env sozinha permanece inerte. Gates S3, agente, consentimento, piloto e envio continuam cumulativos. A nova migration depende da S3 e usa o fluxo MVP datado, RLS/ACL, FKs de tenant e `lock_timeout=2s`.

Desligar a flag deve impedir novos efeitos e cancelar pendências, preservando o relatório oficial. A limpeza de dados transitórios continua ativa. Reversão de código/schema requer drenar pendências incompatíveis e seguir o rollback comentado da migration; esta missão não executa esse procedimento em ambiente compartilhado.

PR426 e PR428 permanecem congeladas. Rebase/retarget, migration, deploy e ativação exigem conferências próprias. O próximo gate humano desta entrega é Sarah revisar o candidato completo, com testes e CI do mesmo SHA.
