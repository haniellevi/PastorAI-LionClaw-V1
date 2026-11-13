# Pipeline do DEV sintético

## Ensaio no CI

`synthetic-release.yml` constrói backend development e frontend standalone do
mesmo SHA e executa `deploy/rehearse_dev_pipeline.py`. O catálogo esperado vem
de outro cluster PG17, com as migrations ativas do artefato. O ensaio tem rede
interna sem egress, fixtures sintéticas, Redis persistente, processos reais,
prontidão e HTTP do frontend. O controller monta somente seus dois arquivos de
controle, sem bind de código do produto ou diretório de segredos.

As provas de login, tenant/RLS e turno completo permanecem na suíte T07.
Prontidão e página pública do ensaio físico não substituem esses testes, nem
provam um login Clerk online. Aceite humano online só fecha após login, duas
igrejas e percurso de produto no recurso nominal autorizado.

## Histórico da publicação remota

A publicação do DEV sintético foi suspensa e o workflow foi arquivado.
A versão histórica do guia registra a configuração do executor, a ordem de publicação
e os procedimentos de recuperação.
[Guia no commit anterior](https://github.com/haniellevi/PastorAI-LionClaw-V1/blob/f78cbf44bdccef5b830878c6ee105c58137c7489/docs/ops/DEV-PIPELINE-SINTETICO.md?plain=1#L24)

## Ensaio local

Construir as duas imagens do SHA escolhido e usar seus IDs imutáveis:

```sh
python deploy/rehearse_dev_pipeline.py \
  --backend-image sha256:ID_BACKEND \
  --frontend-image sha256:ID_FRONTEND \
  --sha SHA_COMPLETO \
  --report /tmp/ensaio-sintetico.json
```

Frontend do ensaio usa `https://synthetic-api.example.test` e
`https://synthetic-dev.example.test` no build. O ensaio cria nomes únicos,
PostgreSQL sem porta publicada e segredos aleatórios fictícios; remove somente
suas stacks ao terminar. Relatório contém SHA, IDs, hash do catálogo e códigos
de provas, sem linhas de banco, logs pastorais ou credenciais.
