# Registro de Sprints / Sessões

Histórico **versionado** do que foi feito no PastorAI, sprint a sprint (ou sessão a sessão).
Diferente da memória local do Claude (que é por máquina), isto vai pro git: é portável,
compartilhável e sobrevive a troca de máquina.

## Quando gravar
- Ao **fechar um sprint** ou um bloco de trabalho significativo.
- Quando você disser **"fecha o sprint"** (o Claude escreve o registro).
- Automaticamente lembrado antes de o contexto da conversa estourar (hook `PreCompact`).

## Formato
Um arquivo por sprint/sessão: `AAAA-MM-DD-titulo-curto.md`. Modelo:

```markdown
# <título> — AAAA-MM-DD

**Branch:** <branch>  ·  **Commits:** <hashes>  ·  **Deploy:** <sim/não + onde>

## O que foi feito
- item objetivo (com arquivo:linha quando útil)

## Decisões
- decisão + porquê

## Pendente / próximo passo
- o que ficou para depois (e por quê)

## Verificação
- testes/smoke que comprovam (ex.: pytest verde, smoke prod = X)
```

## Relação com as outras camadas
- **Grafo CRG / graphify** → "como o código é agora" (contexto/velocidade). Não guarda história.
- **Memória local do Claude** (`~/.claude/.../memory/`) → anotações para o Claude lembrar entre conversas.
- **Estes arquivos** → a história "o que fizemos e por quê", versionada no repo.
