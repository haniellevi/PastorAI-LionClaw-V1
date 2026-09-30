# Checker de rollback do backend: preparação de fonte em 30/09/2026

Missão: M-2026-09-30-compose-rollback-source. PR #443, branch
fix/compose-rollback-source-20260930, base
b18baeee104f73fb7f23dc2d10f301c5bebf8202. Fonte funcional e testes conferidos no
SHA 4b4c831a378ad0f3088d54dcceab0c029661debf; esta nota acrescenta somente
rastreabilidade documental, sem atribuir CI ou revisão ao commit que a publica
antes de sua verificação.

Raniel escolheu a opção B source-only, conforme transmissão do Conselheiro
Claude do texto exato "B entao" no chat dele em 30/09; horário original
indisponível. A opção A de engine isolado foi descartada. A escolha autoriza
preparação, PR e revisões, sem autorizar merge ou operação de ambiente.

O rollback substitui compose run por up --no-start e start de um backend
temporário dedicado ao checker Python da release anterior. Confere gates do
Compose e do contêiner parado, copia o checker anterior, usa o manifesto
anterior e exige saída zero da espera limitada a 180 s. Depois recria os quatro
serviços sem overlay, inspeciona seus gates e inicia a aplicação. Falhas entram
em contenção e preservam configuração e status original.

O manual declara Compose 5.0.0 como piso suportado escolhido, exige suporte a
start --wait/--wait-timeout e executa probe inerte das opções de timeout antes
de configuração, build ou parada. Documenta recuperação humana e seus gates
independentes. A versão mínima não é uma alegação da primeira versão histórica
das flags.

FORJA reproduziu falhas antes das correções e executou 45 testes de dublê e
18 de runbook; o Orquestrador confirmou ambos, bash -n e diff-check. LENTE deu
GO source-only no SHA 4b4c831, P0/P1/P2 novos=0, após resolver dois P2: aceitação
tardia de timeout incompatível e cobertura de recriação normal. Testes
stateful rejeitam ausência de recriação e reutilização do overlay do checker.
CI, LENTE e Sarah devem vincular seus pareceres ao head final da PR, inclusive
este delta documental.

Limites: sem Compose/engine real, banco, VPS, PROD, dispatch ou deploy.
Compatibilidade no alvo do P1 Sarah e recuperação operacional P2-5 permanecem
abertas; P2-1/2/3/4 históricos não são encerrados. Nenhuma classificação de
domínio mudou, portanto PRD-COVERAGE não recebe alteração nesta fatia.

Rollback source-only: reversão por commit normal deste delta após revisão,
preservando histórico e alterações alheias. Não há rollback de schema.
Próximo gate humano único: sim DIRETO de Raniel para merge da PR #443 no head
exato, depois de CI, LENTE, Sarah e preflight vivo. Isso não autoriza operação
futura.
