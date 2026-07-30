# Decisao do dono - fechamento da V1 sem cobranca real Asaas em PROD - 2026-07-30

## Contexto

Uma cobranca real no Asaas movimenta dinheiro e pode criar cliente, assinatura,
fatura ou efeitos de webhook em producao. Esse risco nao e necessario para
provar os fluxos funcionais que encerram a V1.

## Decisao registrada

> "Aceito encerrar a V1 sem executar cobranca real do Asaas em PROD; a validacao
> financeira devera ocorrer em sandbox ou ambiente de teste separado."

Consequencias desta decisao:

- A V1 pode ser encerrada sem checkout, cobranca, cancelamento ou alteracao de
  assinatura real em PROD.
- A ausencia desse smoke financeiro nao deve ser apresentada como prova de que
  o billing foi validado ponta a ponta.
- Nenhuma operacao financeira em PROD fica autorizada por este documento.
- A validacao financeira passa a ser uma missao futura separada:
  `BILLING-SANDBOX-1`.

## Escopo futuro de BILLING-SANDBOX-1

A missao so deve iniciar quando houver um sandbox ou ambiente financeiro de
teste claramente separado de PROD. O preflight deve comprovar:

1. endpoint e credenciais de sandbox, com segredos fora do Git;
2. ausencia de chave, cliente, assinatura e endpoint de producao;
3. dados sinteticos identificaveis e descartaveis;
4. envios e efeitos externos limitados ao sandbox;
5. plano de limpeza dos dados de teste.

O smoke deve cobrir, quando suportado pelo contrato atual:

- criacao do checkout ou cobranca de teste, incluindo taxa de adesao e plano;
- transicao de status por webhook ou consulta ao provedor;
- idempotencia para repeticao do mesmo evento;
- tratamento de erro e ausencia de cobranca duplicada;
- cancelamento ou encerramento do artefato de teste;
- registro versionado do resultado, sem copiar segredos ou dados financeiros.

## Criterio de encerramento

`BILLING-SANDBOX-1` termina somente com evidencia de ponta a ponta no ambiente de
teste e confirmacao de que nenhum dinheiro real ou dado de producao foi usado.
Se o sandbox nao estiver disponivel, a missao deve ficar `BLOCKED`, sem tentar
substitui-lo por PROD.

## Estado

**DECISAO ACEITA / NAO BLOQUEANTE PARA O ENCERRAMENTO DA V1.**

Esta decisao nao executou cobranca, deploy, migration, alteracao de ambiente ou
qualquer escrita no Asaas.
