# Receitas de reprodutibilidade offline

## Limites da receita

Todas as receitas abaixo são locais, source-only e sem rede ou banco. Este
pacote não abre captura privada. O aceite determinístico local registrado
adiante foi executado pelo Orquestrador fora deste pacote, sem ambiente vivo e
sem imprimir conteúdo. Qualquer novo uso futuro da captura exige gate humano
próprio, arquivo externo em modo `0600` e os mesmos bytes do derivador aprovado.
Nenhuma receita imprime identificador do alvo, valor de ledger, statements,
valor de idempotency, dado de domínio ou hash derivado por posição.

## Seleção top-level e digest de basenames

No pino `de1ea1e659be9a4f2a988740b72a9ed8edd68bfb`, a seleção de histórico é
somente de arquivos diretos de `backend/migrations`. A receita canônica é:

```bash
find backend/migrations -maxdepth 1 -type f -name '*.sql' -printf '%f\0' | LC_ALL=C sort -z | sha256sum
```

O resultado esperado é
`950bde59ce2b65b4596a6ca9ecf284a85aa18ba49dba9b8cac6913004b8fa415` para
`77` basenames top-level. A árvore inteira de migrations tem OID da árvore Git
`ff84b1274a342ea47e1e378446ed72caa27cef4b` e há `78` arquivos `.sql`
recursivos. O único arquivo adicional fica sob `private_runtime` e permanece
fora do universo histórico atual.

Esta verificação de contagem não imprime basenames:

```bash
python3 -I -B - <<'PY'
from pathlib import Path

root = Path('backend/migrations')
top_level = sorted(
    path.name for path in root.iterdir()
    if path.is_file() and path.suffix == '.sql'
)
recursive_count = sum(1 for path in root.rglob('*.sql') if path.is_file())
if len(top_level) != 77 or recursive_count != 78:
    raise SystemExit('RESULT=FAIL_F2_EPOCH_CATALOG_SCOPE')
print('RESULT=PASS_F2_EPOCH_CATALOG_SCOPE')
PY
```

## `catalog_ref` e derivação determinística

`catalog_ref` é calculado somente a partir do basename versionado, com framing
fixo. A fórmula canônica é:

```python
import hashlib

def catalog_ref(basename: str) -> str:
    return hashlib.sha256(
        b'F2-PROD-NATIVE-CATALOG-BASENAME-v1\0' + basename.encode('utf-8')
    ).hexdigest()
```

A chave candidata só existe para a forma exata
`AAAAMMDD_HHMMSS_slug.sql`. Esta receita usa a mesma seleção top-level, ordena
somente basenames e não imprime os itens:

```bash
python3 -I -B - <<'PY'
from pathlib import Path
import re

pattern = re.compile(
    r'^(?P<date>[0-9]{8})_(?P<time>[0-9]{6})_(?P<slug>[A-Za-z0-9][A-Za-z0-9_-]*)\.sql$'
)
entries = sorted(
    path.name for path in Path('backend/migrations').iterdir()
    if path.is_file() and path.suffix == '.sql'
)
keys = [
    None if (match := pattern.fullmatch(basename)) is None
    else match.group('date') + match.group('time')
    for basename in entries
]
if len(entries) != 77 or keys.count(None) != 17:
    raise SystemExit('RESULT=FAIL_F2_EPOCH_DERIVATION_SHAPE')
print('RESULT=PASS_F2_EPOCH_DERIVATION_SHAPE')
PY
```

O slug e os hashes de nome são evidência secundária. Duplicidade, colisão ou
ambiguidade não promovem match. Hashes de chaves de 14 dígitos são enumeráveis
e não são anonimização.

## Reproduzir a derivação contra captura congelada

O aceite determinístico local já foi concluído pelo Orquestrador, sem ambiente
vivo e sem imprimir conteúdo. A receita abaixo é permitida somente após gate
humano futuro próprio. Ela autentica captura, derivador e snapshot privado
antes de invocar o derivador; qualquer divergência falha fechada. A captura
congelada teve SHA-256
`c7831ca5d17b8c250e2cd7a6bc1a5f65c66ddcd874ddbca214c16f4d067b8830`; o
derivador teve SHA-256
`d3f0e9610ace59d704bb5e77dc49e52f6f115cdf2b7847a8bd7e0b5bcc3c85e8`; e o
resultado foi byte-idêntico ao JSON externo de SHA-256
`5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d`. O
arquivo temporário foi removido. Qualquer novo uso futuro da captura continua
bloqueado nesta missão e exige gate humano posterior. Quando esse gate
disponibilizar a captura externa e os bytes aprovados do derivador, use apenas
variáveis locais de caminho, sem imprimir conteúdo da captura:

```bash
set +o history
umask 077

f2_expected_capture_sha256='c7831ca5d17b8c250e2cd7a6bc1a5f65c66ddcd874ddbca214c16f4d067b8830'
f2_expected_deriver_sha256='d3f0e9610ace59d704bb5e77dc49e52f6f115cdf2b7847a8bd7e0b5bcc3c85e8'
f2_expected_source_commit='de1ea1e659be9a4f2a988740b72a9ed8edd68bfb'
f2_expected_migrations_tree='ff84b1274a342ea47e1e378446ed72caa27cef4b'
f2_expected_output_sha256='5399bb7db895be26c7fb0dcaf67375d0aa7a78c58c03de80b50ed27a9fd2944d'

f2_capture_path='<frozen-evidence-directory>/f2-prod-native-identity-cast-retry-01.txt'
f2_deriver_path='<approved-deriver-path>/derive_catalog_native_keys.py'
f2_source_root='<private-trusted-snapshot-of-de1ea1e>'
f2_catalog_dir="$f2_source_root/backend/migrations"
f2_output_path='<frozen-evidence-directory>/f2-prod-native-derived-comparison.json'

f2_fail() {
  printf '%s\n' "$1"
  exit 1
}

[[ -f "$f2_capture_path" && ! -L "$f2_capture_path" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_CAPTURE_SOURCE'
[[ "$(stat -c '%a' "$f2_capture_path")" == 600 ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_CAPTURE_MODE'
[[ "$(sha256sum "$f2_capture_path" | awk '{print $1}')" == "$f2_expected_capture_sha256" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_CAPTURE_SHA256'

[[ -f "$f2_deriver_path" && ! -L "$f2_deriver_path" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_DERIVER_SOURCE'
[[ "$(sha256sum "$f2_deriver_path" | awk '{print $1}')" == "$f2_expected_deriver_sha256" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_DERIVER_SHA256'

[[ "$(git -C "$f2_source_root" rev-parse HEAD)" == "$f2_expected_source_commit" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_SOURCE_COMMIT'
[[ "$(git -C "$f2_source_root" rev-parse HEAD:backend/migrations)" == "$f2_expected_migrations_tree" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_MIGRATIONS_TREE'
[[ -z "$(git -C "$f2_source_root" status --porcelain --untracked-files=all -- backend/migrations)" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_MIGRATIONS_WORKTREE'

if [[ -e "$f2_output_path" ]]; then
  [[ -f "$f2_output_path" && ! -L "$f2_output_path" &&
     "$(stat -c '%a' "$f2_output_path")" == 600 ]] ||
    f2_fail 'RESULT=FAIL_F2_EPOCH_OUTPUT_MODE'
  : > "$f2_output_path"
else
  install -m 600 /dev/null "$f2_output_path" ||
    f2_fail 'RESULT=FAIL_F2_EPOCH_OUTPUT_CREATE'
fi
[[ "$(stat -c '%a' "$f2_output_path")" == 600 ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_OUTPUT_MODE'

python3 -I -B "$f2_deriver_path" \
  --catalog-dir "$f2_catalog_dir" \
  --prod-capture "$f2_capture_path" \
  > "$f2_output_path" ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_DERIVATION'
[[ "$(stat -c '%a' "$f2_output_path")" == 600 ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_OUTPUT_MODE'
[[ "$(sha256sum "$f2_output_path" | awk '{print $1}')" == "$f2_expected_output_sha256" ]] ||
  f2_fail 'RESULT=FAIL_F2_EPOCH_JSON_SHA256'

unset f2_expected_capture_sha256 f2_expected_deriver_sha256
unset f2_expected_source_commit f2_expected_migrations_tree
unset f2_expected_output_sha256 f2_capture_path f2_deriver_path
unset f2_source_root f2_catalog_dir f2_output_path
unset -f f2_fail
printf '%s\n' 'RESULT=PASS_F2_EPOCH_JSON_BYTE_IDENTITY'
```

Aceite determinístico significa que o mesmo pino, catálogo e captura congelada
reproduzem os mesmos bytes de JSON e exatamente o SHA-256 acima. Qualquer
diferença falha fechada. Essa receita não transforma o JSON em prova de
aplicação e não autoriza leitura, epoch, cutover ou executor.

## Exclusão obrigatória de `private_runtime`

O contrato atual deliberadamente usa `Path('backend/migrations').iterdir()` e a
seleção `find` com `-maxdepth 1`. Portanto, o SQL em `private_runtime` não entra
no digest, no `catalog_ref`, nas `77` entradas ou nas `75` sem chave PROD.
Inclusão futura requer contrato próprio, revisão independente e redefinição
explícita do universo; este pacote não a propõe nem a autoriza.

## Próximo gate único

Estado vigente após a rodada corretiva do PR #403: OpenCode e QWEN concluíram o APTO conjunto sobre estes bytes, e o commit e o push corretivos foram publicados no PR #403. O MERGE permanece retido até frase nominal de Raniel, e qualquer fase executável exige gate humano próprio.
