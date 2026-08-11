# Dependency locking

## V1 contract

`requirements.lock` and `requirements-audit.lock` are reviewed installation
artifacts and the source of truth for their environments. A clean environment
must install only from the applicable lock with `--require-hashes`, pass
`pip check`, pass the manifest verifier, and pass its tests or audit.

Cold compilation from `requirements.txt` or `requirements-audit.in` against the
mutable public package index is **not** guaranteed to reproduce the same bytes.
It may select newer compatible releases. Reproducibility in V1 means installing
the reviewed lock, not independently recreating it from ranges at a later date.

## Clean installation

Run from `backend/`, using Python 3.13.14:

```bash
python -m venv .venv-runtime
.venv-runtime/bin/python -m pip install --require-hashes -r requirements.lock
.venv-runtime/bin/python -m pip check
.venv-runtime/bin/python scripts/verify_manifest_requirements.py requirements.txt

python -m venv .venv-audit
.venv-audit/bin/python -m pip install --require-hashes -r requirements-audit.lock
.venv-audit/bin/python -m pip check
.venv-audit/bin/python scripts/verify_manifest_requirements.py requirements-audit.in
.venv-audit/bin/python -m pip_audit --require-hashes --disable-pip -r requirements.lock
.venv-audit/bin/python -m pip_audit --require-hashes --disable-pip -r requirements-audit.lock
```

On Windows, replace `.venv-*/bin/python` with `.venv-*\Scripts\python.exe`.
The runtime and audit environments must remain separate.

## Manifest contract limits

The verifier supports named index requirements and their direct extras, such as
`uvicorn[standard]` and `PyJWT[crypto]`. It intentionally rejects PEP 508
direct references, including HTTPS, VCS, local-file, and other URL sources,
until it can validate their provenance.

It also rejects nested extras activated by another extra. Recursive extra
validation is not part of the current contract. Any future introduction of a
direct reference or nested extra must expand the verifier and its tests before
the corresponding change is merged.

## Controlled lock maintenance

Lock changes are intentional, reviewed updates. Use the pinned generator without
adding it to the application runtime:

```bash
uvx --from uv==0.12.1 uv pip compile requirements.txt --universal --python-version 3.13 --generate-hashes -o requirements.lock
uvx --from uv==0.12.1 uv pip compile requirements-audit.in --universal --python-version 3.13 --generate-hashes -o requirements-audit.lock
```

With an existing output file and no `--upgrade`, `uv pip compile -o` preserves
compatible pins as preferences. This is a controlled refresh; it is not proof
of cold regeneration. To intentionally refresh compatible versions, add
`--upgrade`, then review the complete lock diff and rerun installation,
auditing, backend, RLS, and Docker gates before committing.

Never delete a reviewed lock and present a later cold resolution from the
mutable index as byte-equivalent. If a lock must be rebuilt from scratch, treat
the result as a dependency upgrade requiring its own review.

References: [uv pip compile](https://docs.astral.sh/uv/pip/compile/) and
[uv CLI `--require-hashes`](https://docs.astral.sh/uv/reference/cli/).
