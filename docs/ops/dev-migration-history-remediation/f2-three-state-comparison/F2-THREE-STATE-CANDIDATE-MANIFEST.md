# Manifesto do candidato F2, comparação de três estados

## Escopo fechado

Base Git: `f856f53f48e79a53609ff699d5603119f60202e0`.

Ficha vinculada, sem alteração:
`docs/missions/M-2026-09-16-f2-three-state-comparison-epoch-cutover.md`,
SHA-256 `7995e005a92a8a6c7f1bbc335a69c316805aa54b8e3c688e6a663cd0adc158bc`.

Este conjunto contém exatamente os nove arquivos abaixo. Os oito artefatos
materiais usam SHA-256 de bytes. O próprio manifesto contribui por seu digest
canônico, que substitui somente as três linhas de digest por marcadores fixos
antes do cálculo. Assim, a verificação não depende de um hash autorreferente
impossível.

| Arquivo | SHA-256 ou forma canônica |
| --- | --- |
| `DEV-F2-SEALED-RECEIPT.md` | `7d416765c5673d4c17b4a6d8cc5d9335f4ef19246cc07f4f71e5ebfb051e3d99` |
| `PROD-F2-V2-ACCEPTANCE-RECEIPT.md` | `926043d9d1b9b2cf866f8d553a11670fe91f5db08b1662866da652bd819e5324` |
| `THREE-STATE-INVENTORY.json` | `e4a6c3101c68bfd2e0a13041dbb2732258dfb1da5c1c0bd03370b51c75994580` |
| `THREE-STATE-COMPARISON.md` | `4398da8a7196b70d44dfd849878e08333baa8ee23ea3be8948a3bab5f5332b5c` |
| `STRATEGY-A-B-EPOCH-CUTOVER.md` | `3d6fb96f8cbbe33eec3a40171ccad579076a6eaa378bc80815808f149d28d802` |
| `DECISION-PACKET.md` | `9e93063e1297a70a08997780a2982ec9f16351ddd00d53a2d68843a6f6d21e13` |
| `validate_f2_capture_contract.py` | `80b490ed80dc2364e65186da0b1271db37a5dfeeea24ef3a51b04e197da14c9d` |
| `test_validate_f2_capture_contract.py` | `5e81bc57ddb026f978ffdb22d9fb09cb2f222c35011a5f862ce16095353bbcb7` |
| `F2-THREE-STATE-CANDIDATE-MANIFEST.md` | `SELF_CANONICAL` abaixo |

PATCH_CANONICAL=14bd410dc1e190aa3deac121f44ffbdf914955b554a617864ed13963ebf23cc0
SELF_CANONICAL=b9372558a53d4b2ecd37a5cec8f5fbc9b75d03c6f8529daf81221f2dbac32958
AGGREGATE=3211933f3c05ea7a257d916048a607a051ef5b4bc4f5a681b73103a148379d1c

## Reprodutor autocanônico

Execute o bloco abaixo na raiz do repositório. Ele não abre banco, rede ou
captura externa; confere somente os bytes deste pacote e da ficha vinculada.

```bash
python3 -I -B - <<'PY'
from hashlib import sha256
from pathlib import Path
import re

base = Path("docs/ops/dev-migration-history-remediation/f2-three-state-comparison")
mission = Path("docs/missions/M-2026-09-16-f2-three-state-comparison-epoch-cutover.md")
expected_mission = "7995e005a92a8a6c7f1bbc335a69c316805aa54b8e3c688e6a663cd0adc158bc"
expected = {
    "DEV-F2-SEALED-RECEIPT.md": "7d416765c5673d4c17b4a6d8cc5d9335f4ef19246cc07f4f71e5ebfb051e3d99",
    "PROD-F2-V2-ACCEPTANCE-RECEIPT.md": "926043d9d1b9b2cf866f8d553a11670fe91f5db08b1662866da652bd819e5324",
    "THREE-STATE-INVENTORY.json": "e4a6c3101c68bfd2e0a13041dbb2732258dfb1da5c1c0bd03370b51c75994580",
    "THREE-STATE-COMPARISON.md": "4398da8a7196b70d44dfd849878e08333baa8ee23ea3be8948a3bab5f5332b5c",
    "STRATEGY-A-B-EPOCH-CUTOVER.md": "3d6fb96f8cbbe33eec3a40171ccad579076a6eaa378bc80815808f149d28d802",
    "DECISION-PACKET.md": "9e93063e1297a70a08997780a2982ec9f16351ddd00d53a2d68843a6f6d21e13",
    "validate_f2_capture_contract.py": "80b490ed80dc2364e65186da0b1271db37a5dfeeea24ef3a51b04e197da14c9d",
    "test_validate_f2_capture_contract.py": "5e81bc57ddb026f978ffdb22d9fb09cb2f222c35011a5f862ce16095353bbcb7",
}
manifest_name = "F2-THREE-STATE-CANDIDATE-MANIFEST.md"
expected_files = set(expected) | {manifest_name}
actual_files = {path.name for path in base.iterdir() if path.is_file()}
if actual_files != expected_files or sha256(mission.read_bytes()).hexdigest() != expected_mission:
    raise SystemExit("RESULT=FAIL_F2_THREE_STATE_MANIFEST")
entries = []
for name in sorted(expected):
    digest = sha256((base / name).read_bytes()).hexdigest()
    if digest != expected[name]:
        raise SystemExit("RESULT=FAIL_F2_THREE_STATE_MANIFEST")
    entries.append(f"{digest}  docs/ops/dev-migration-history-remediation/f2-three-state-comparison/{name}\n")
patch = sha256("".join(entries).encode("ascii")).hexdigest()
manifest = (base / manifest_name).read_text(encoding="utf-8")
normalized = re.sub(
    r"^(PATCH_CANONICAL|SELF_CANONICAL|AGGREGATE)=[0-9a-f]{64}$",
    r"\1=<CANONICAL>",
    manifest,
    flags=re.MULTILINE,
)
self_digest = sha256(normalized.encode("utf-8")).hexdigest()
aggregate = sha256(
    ("F2-THREE-STATE-AGGREGATE-v1\0" + expected_mission + "\0" + patch + "\0" + self_digest).encode("ascii")
).hexdigest()
for label, value in (("PATCH_CANONICAL", patch), ("SELF_CANONICAL", self_digest), ("AGGREGATE", aggregate)):
    if f"{label}={value}" not in manifest:
        raise SystemExit("RESULT=FAIL_F2_THREE_STATE_MANIFEST")
print("RESULT=PASS_F2_THREE_STATE_MANIFEST_REPRODUCIBLE")
print("PATCH_CANONICAL=" + patch)
print("SELF_CANONICAL=" + self_digest)
print("AGGREGATE=" + aggregate)
PY
```

O único próximo gate deste candidato é parecer `APTO` conjunto de OpenCode e
CLAUDE sobre os mesmos bytes antes de commit, push ou publicação.
