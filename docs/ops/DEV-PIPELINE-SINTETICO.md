# Pipeline do DEV sintético

## Desenvolvimento e operação

GitHub Actions com Docker Compose via SSH é a opção implementada para T09 e
para o ensaio da T10. Não contrata recursos. Ativação continua condicionada a
região, custo, executor nominal, identidade e ausência de dados reais. O
workflow `dev-synthetic.yml` fica desativado enquanto
`DEV_PIPELINE_ENABLED` não for `true`. Não alterar publicação Vercel de PROD
por causa deste workflow; a transição de PROD permanece uma operação própria.

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

## Ativação futura

Após autorização nominal, preparar um executor exclusivo e TLS para os dois
origins. Não reutilizar a VPS de PROD nem o DEV antigo sem verificar identidade,
isolamento e ausência de dados reais. O banco precisa de projeto Supabase DEV
aprovado, TLS verify-full e usuário/projeto correspondentes. O guard recusa o
projeto PROD conhecido e domínios `igreja12.com.br`. Seed recusa outro tenant;
nunca adota ou apaga dados em deploy normal. Um projeto vazio também precisa
do bootstrap nominal das migrations e da remoção autorizada dos fixtures
históricos do runner antes de receber o seed próprio. Migration concorrente
pendente reprova o deploy automático e exige operação específica; não há
reparo silencioso de DDL parcialmente aplicada.

No GitHub Environment `dev-sintetico`, configurar os valores públicos
`DEV_API_ORIGIN`, `DEV_FRONTEND_ORIGIN`, `DEV_SSH_HOST`, `DEV_SSH_USER` e os
segredos `DEV_SSH_KEY`, `DEV_SSH_KNOWN_HOSTS`. A chave é inserida na configuração
de segredos pelo proprietário, nunca em arquivo versionado ou chat. SSH usa
verificação estrita do host e autenticação não interativa. O hostname deve ser
confirmado nominalmente como DEV; não usar alias ou IP da VPS de produção.

O usuário do executor precisa de Docker e escrita somente no seu controller e
estado. Preparar `/opt/pastorai-dev-controller/candidates`,
`/var/lib/pastorai-dev`, `/etc/pastorai-dev/controller.json` e a configuração
runtime privada `/etc/pastorai-dev/runtime.conf`. O agente não lê nem registra
o conteúdo desta última. O controller consome os segredos dentro do container
autorizado e expõe apenas erros sanitizados.

Exemplo de configuração pública, preencher os repositories correspondentes
aos artefatos publicados pela organização:

```json
{
  "project": "pastorai-synthetic-dev",
  "profile": "online",
  "approved_project": "cxmjojnocigekgcxhubi",
  "runtime_env_file": "/etc/pastorai-dev/runtime.conf",
  "state_dir": "/var/lib/pastorai-dev",
  "backend_repository": "ghcr.io/haniellevi/pastorai-lionclaw-v1-dev-backend",
  "frontend_repository": "ghcr.io/haniellevi/pastorai-lionclaw-v1-dev-frontend",
  "api_port": 18000,
  "frontend_port": 13000
}
```

O ID histórico acima é informação do proprietário, não prova atual de recurso
sintético. Confirmá-lo antes de ativar. Runtime exige DATABASE_URL e
SUPABASE_URL guardados, sessão/autenticação própria, chave de criptografia DEV
e assinatura de webhook sintética. Compose fixa envios, Brevo e Asaas fechados;
Redis é próprio e persistente, o transporte usa apenas o simulador. Nenhum
número piloto ou credencial de PROD entra nesse ambiente.

## Ordem e recuperação

O gate exige que o SHA ainda seja a main atual, com as últimas execuções push
dos quatro workflows obrigatórios e do ensaio sintético aprovadas. Não usa
artefato ou checkout de fork. Reconstrução e build acontecem antes de publicar
os digests no GHCR. O frontend tem build próprio para os valores públicos do
alvo, porque NEXT_PUBLIC é incorporado durante o build. O gate da main é
reconferido antes de transferir o pacote; sequência crescente e mutex do
executor impedem troca por candidato antigo.

Deploy e reset compartilham mutex com a reserva de aceite. Antes do primeiro
efeito, o estado registra recuperação necessária. Parar fisicamente API e os
três consumidores, aguardar saída, preservar Redis/leases, aplicar migrations
do candidato e verificar ledger/catálogo independente. Seed é idempotente.
Iniciar simulador, API e frontend correspondentes, conferir o smoke inicial,
retomar consumidores e exigir prontidão completa. Falha contém API e workers e
conserva a evidência de incerteza, sem afirmar que o pacote anterior está vivo.
O controller não fecha o gate como estratégia de pausa.

`recover` recebe o pacote anterior registrado e o catálogo independente que o
schema vivo deve corresponder. Só inicia o código antigo se a compatibilidade
aditiva for provada. Não executa migrations antigas nem restaura banco. DDL
incompatível, drift ou falha não aditiva exigem correção para frente ou operação
de restauração separada. Não há rollback universal. A opção estrita do release legado é documentada em
[compatibilidade entre releases](COMPATIBILIDADE-RELEASE-REVISADA.md); ela exige
bundle revisado e não autoriza um release naquele ambiente.

`reserve --owner NOME --ttl 1800` retorna token vinculado ao pacote.
`finish --owner NOME --token TOKEN` registra o aceite declarado pelo responsável.
O token é metadado de coordenação, sem conferir permissão de produto. Expiração
ou reset invalida reserva pendente, mantendo recibos anteriores já concluídos.

`reset` exige pacote atual com nova versão de seed e
`--confirm-synthetic-reset IDENTIDADE_DO_PACOTE`. É destrutivo somente para o
recurso sintético nominal: contém consumidores, verifica schema e dois tenants
do seed, recria o schema e zera o DB Redis exclusivo. O proprietário deve
atestar ausência de dados reais antes dessa operação; IDs conhecidos, por si
só, não provam isso. O mesmo mutex invalida a sessão pendente e preserva
evidência de aceitações concluídas. Em produção o controller recusa o alvo.

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
