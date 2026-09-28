# PR430: correções Sarah de 28/09/2026

Base: `c3e8fb3171682b5f2bdfa36ae153414fe73bb47a`, branch `feat/whatsapp-cell-report-text`.

O predicado temporal V1a no finalizador compartilhado fazia o painel humano retornar 409 para reuniões de hoje sem hora ou com hora 23:59. A correção o aplica somente no finalizador V1a, depois do lock e antes de qualquer mutação. A rota humana volta ao contrato anterior, com os mesmos controles de tenant, liderança, locks e estado terminal.

O parser V1a aceita LF/CRLF como separador adicional, incluindo texto misto e moeda brasileira. Observações continuam recusadas; a projeção existente conserva somente os agregados, e o parser legado permanece intacto. Unicode NFC/NFD e prefixos já aceitos preservam compatibilidade. Os quatro caminhos CLARIFY explicam o formato e dão exemplo completo.

Regressões reproduzidas antes da correção: dois HTTP409 humanos e sete falhas de parser/CLARIFY. Depois: 470 testes locais sintéticos passaram, sem skip, incluindo os dois HTTP200 pela rota real, repetição409 e negativas V1a futuras/sem hora sem mutação. SQLs S2b/S3/V1a preservados por hash; nenhum replay PostgreSQL local nesta rodada.

[Manifesto do delta](../ops/v1a-cell-report-20260927/DELTA-VALIDATION.json) e [hashes do candidato](../ops/v1a-cell-report-20260927/SARAH-FIXES-CANDIDATE-HASHES.json) vinculam a prova aos arquivos exatos. Manifestos anteriores ficam como histórico, sem atribuir seus testes a este candidato.

[Revisão independente](../ops/v1a-cell-report-20260927/REVIEW-SARAH-FIXES-20260928.md): APTO no patch exato, P0/P1/P2=0; 65 testes focais executados pela revisora. CI remoto e Sarah permanecem gates separados.

Rollback de código: commit normal que reverta somente este delta, após revisão. Nenhuma operação de ambiente executada. Próximo gate humano: Sarah revisar o novo head publicado após CI verde. Sem autorização de merge, migration, deploy ou ativação.
