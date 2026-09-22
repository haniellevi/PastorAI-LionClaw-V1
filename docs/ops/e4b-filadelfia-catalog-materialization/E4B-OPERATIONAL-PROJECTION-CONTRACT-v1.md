# E4b operational projection source contract v1

## Boundary

`materialize_authenticated_projection()` is an explicit, source-only API. There
is no command-line entrypoint, default adapter, PG17 call, Docker call, network
call, Git subprocess, archive operation or consumer execution path.

The caller supplies a local-object `GitBlobReader` adapter. The implementation
passes a closed, fixed Git environment to every adapter call and requests only
individual approved object ids. An adapter implementation is outside this
candidate and must be separately reviewed before operational adoption.
Any adapter `Exception` other than an internal `ProjectionSourceError` becomes
the fixed `READER_ADAPTER_FAILURE` code; adapter text is never returned.

## Independent anchors

`SourceTrustAnchors` contains externally obtained expected values for commit,
tree, parent, base, ancestry digest, patch-receipt byte digest, patch digest,
patch recipe/version and dependency-manifest byte digest. The materializer does
not accept those values from repository metadata, the patch receipt or the
manifest as their own authority. Each declaration is compared to the separate
anchor before a blob read.

Both the patch receipt and dependency manifest are strict JSON objects with
closed keys, duplicate-key rejection, exact scalar types, canonical path order
and no extra entries. The manifest has an explicit `files` list, so absence,
duplicate, metadata drift and content drift fail closed. This candidate ships no
fc09 manifest instance because no admissible complete source is in scope.

The manifest also has an ordered `omitted` metadata list. The union of selected
files and omitted metadata must equal the complete classified tree. Omitted
entries carry path, object id, mode and size only; their blobs are never read.
This closes tree coverage without treating a protected path as selectable.

## Extraction order

1. Validate anchors, patch receipt and manifest bytes.
2. Read commit facts and full tree metadata through the adapter.
3. Classify every tree path, reject unknown paths, non-blob types and invalid
   modes, then build the protected-object-id set. Protected categories are
   compared on the complete casefolded path before any blob request.
4. Compare every manifest item to tree metadata and reject a selected object id
   that aliases a protected path.
5. Read individual selected blobs only, check size and SHA-256, then repeat
   repository metadata checks to detect a changed view.
6. Reserve a private publication directory, materialize a private staging root,
   retain the validated destination-parent descriptor, create and traverse every
   reservation and staging ancestor by `dir_fd` with `O_NOFOLLOW`, verify the
   exact file and directory sets, restricted mode, ownership, regular type,
   link count and hash, then atomically rename the staging root into the
   reservation through held descriptors.

The receipt omits physical root paths, selected paths, blob ids and protected
path names. `PublishedProjection` exposes no physical root pathname. It owns a
`ProjectionRootHandle` bound to the published root descriptor; callers may read
only an exact manifest path through `read_file(relative_path)`, which traverses
relative to that descriptor with `O_NOFOLLOW` and rechecks size and SHA-256.
`PublishedProjection.close()` is idempotent, and use after closure raises the
fixed `PROJECTION_HANDLE_CLOSED` code. A final receipt remains
`operational_authorization = false` and does not authorize PG17.

## Failure and cleanup

Every validation failure raises `ProjectionSourceError` with a fixed code only.
The materializer removes only staging and reservation directories it created for
that attempt. A preexisting publication name is a conflict and is never
overwritten. Blocked and historical receipts remain rejected; the typed consumer
may only accept an exact `FinalProjectionReceipt`, with no execution effect.
An unexpected empty directory, a protected case variant selected as a file, a
symlink encountered during descriptor traversal and a reader failure all fail
closed before publication.
A changed textual destination-parent path is detected before staging and before
publication; cleanup stays relative to the retained parent descriptor and never
uses the changed textual path for removal.
