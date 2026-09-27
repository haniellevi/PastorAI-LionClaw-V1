# Revisão independente, PR430 P2

## Candidato

- Base: `7d98d0ced6652437d4689e5f71f1ebad0a9f5274`.
- Patch fonte: `6f66b635722c594d505e6ff9c31099840e9254b836d7e545fd79e6230ae3ab60`.
- Manifesto conferido: `90bf0b86dd9ce8ca2dd4097c3165adaa6f3ab22bb4558e7fbdea02a09a9d04aa`.
- SQL: `20260927_190000_cell_report_whatsapp_v1a.sql` SHA-256 `b318e47a27204a2abba3490b7fbfee21b7029890ef329880277c59df7b02ee6f`.

Os 11 blobs do manifesto conferem com o snapshot lido.

## Parecer

**APTO técnico, limitado ao patch acima.** Não restou P0, P1 ou P2 neste recorte.

O relatório parcial não captura mais pergunta pública quando há rascunho ativo: patch vazio sem projeção retorna `NOT_APPLICABLE`, preserva rascunho e deixa o roteador normal responder. O recibo da confirmação é composto de célula e data obtidas do estado servidor, gravado na mesma transação do efeito e do ledger; uma tentativa posterior reutiliza a `Message` persistida, inclusive após renomeação da célula.

O dispatcher agora separa fila esgotada de item descartado, adiado ou bloqueado. Mantém um conjunto de IDs já tentados por tenant, portanto uma cabeça bloqueada não ocupa todas as tentativas repetindo o mesmo item, sem antecipar o lock de lembrete antes dos locks de contexto. O limite continua contar varreduras, conforme os testes de limite 1 e 2.

A migration revoga `DELETE` nas cinco relações V1a e falha se o privilégio persistir. O índice parcial que impede dois efeitos executados para a mesma reunião está espelhado no ORM e a guarda de reaplicação confere unicidade, validade, prontidão, três chaves na ordem exata e predicado exato. Isso fecha o caso de índice homônimo com chaves ou predicado incompatíveis.

## Evidência recebida

- Backend: 5.755 testes, zero falhas e zero skips, 45,896 s.
- RLS/PG17: 515 testes, zero falhas, erros ou skips, 163,113 s.
- Inclui 25 provas SQL byte-exatas da migration `b318`, com rejeição `P0001` para índice homônimo de chaves ou predicado incorretos.

Essas evidências validam o SHA do candidato; não demonstram deploy, flag ativa ou envio externo.
