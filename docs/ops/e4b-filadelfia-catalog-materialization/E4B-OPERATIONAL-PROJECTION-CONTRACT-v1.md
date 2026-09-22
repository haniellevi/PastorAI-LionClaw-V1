# E4b operational projection, negative precheck contract v1

## Scope

This is a source-only, negative precheck. It produces diagnostic `BLOCKED`
receipts and never materializes a root, reads a blob, invokes a consumer, or
authorizes an operational action. It does not alter `RepositorySnapshot`, the
canonical fixture, the frozen coordinator, or candidate source.

`closure_status = NOT_PROVEN`: no complete versioned dependency manifest exists.
`runtime_status = NOT_EVALUATED`: this receipt has no binding to a runtime
oracle. Historical synthetic evidence accepted `Settings()` with a simulated
absent dotenv path, but it is neither a global pytest proof nor an operational
source proof and is not copied into this receipt.

## Precheck inputs

The pure precheck receives synthetic declarations of commit, tree, parent, base,
ancestry and patch-receipt anchors. It compares those declarations to policy; it
does not authenticate raw commit, tree or ancestry objects. The expected SHA-256
of the entire patch receipt and the expected patch digest are separate policy
inputs, never self-asserted fields. The patch receipt has closed JSON keys for
schema, candidate commit/tree/parent/base/ancestry digest, and patch
digest/recipe/version. Duplicate keys, type confusion and any field mismatch
block.

Every input field is type-checked before a membership, ordering, hashing or
format operation. A `RecursionError` from excessively nested, otherwise
repinned JSON is classified as `PATCH_RECEIPT_INVALID`; its content is never
reflected in the diagnostic receipt.

Tree metadata is classified before content. Paths are ASCII, relative POSIX,
and reject empty components, dot components, alternate separators, duplicates
and casefold collisions. Finite protected categories are env, secrets, private
keys, protected Clerk and target-user scripts, Clerk production migration,
backup, dump, export and media. Unknown paths block. A protected object-id
commitment is calculated internally; a selected object id that aliases a
protected one blocks before patch receipt validation or any possible blob read.

## Receipt

The only emitted receipt follows
`E4B-OPERATIONAL-PROJECTION-RECEIPT-SCHEMA-v1.json`, has
`operational_authorization = false`, and contains no root path or root digest.
It is a validation result, not authentication of an operational source. The
consumer module rejects it and has no callback or execution surface.

## Reserved future work

No extraction or finalization type is implemented here. A separate future gate
would need a closed dependency manifest, trusted operational inputs, individual
blob reading, temporary-root verification of exact members, type, mode, hash,
links, ownership and ancestors, then atomic publication. It does not reauthorize
PG17.
