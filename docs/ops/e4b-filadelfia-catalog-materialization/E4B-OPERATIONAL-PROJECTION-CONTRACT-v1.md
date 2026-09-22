# E4b operational projection source contract v1

## Boundary

`materialize_authenticated_projection()` is an explicit, source-only API. There
is no command-line entrypoint, default adapter, PG17 call, Docker call, network
call, archive operation or consumer execution path. The core materializer has
no Git subprocess. `e4b_local_git_blob_reader.py` is a separate, explicit
local-object adapter, still injected by the caller and still unable to invoke a
consumer.

The caller supplies a `GitBlobReader`; no reader is constructed by default. The
implementation passes its closed `FIXED_GIT_ENV` object to every adapter call
and requests only individual approved object ids. The local adapter accepts
that object by identity and requires an exact `LocalGitRepositoryHandle`; it
does not accept a repository pathname. The handle carries held descriptors for
the executable, object database and a private minimal Git control directory.
Every invocation duplicates and revalidates those descriptors, uses only their
`/proc/self/fd` paths as cwd, executable, `GIT_DIR` and
`GIT_OBJECT_DIRECTORY`, and exposes no generic Git-command proxy. The child
environment is closed and never inherits `PATH`, `GIT_DIR`, alternates or user
configuration. Any adapter `Exception` other than an internal
`ProjectionSourceError` becomes the fixed `READER_ADAPTER_FAILURE` code;
adapter text is never returned. The local adapter maps its own runner failures to fixed
`LOCAL_GIT_*` `ProjectionSourceError` codes without command, path, author,
message or blob content.

The candidate deliberately has no operational `LocalGitRepositoryHandle`
constructor, path constructor, descriptor constructor or synthetic-helper
factory. Every normal `LocalGitRepositoryHandle(...)` construction raises the
fixed `LOCAL_GIT_HANDLE_UNAVAILABLE` code without interpreting its arguments.
A future snapshot implementation must provide an already-bound capability under
a separately reviewed immutable-private-storage contract. This module neither
creates that capability, validates it as a trust root nor converts a pathname
or descriptor into one.

The offline test module alone uses `object.__new__` to assemble a white-box
fixture from synthetic descriptors. That is equivalent to arbitrary code in
the same Python interpreter and is outside this module's threat model; Python
does not make a private exact type an authority against arbitrary in-process
code. The runtime module exports no route for that construction. Normal import
and normal use therefore remain blocked until a future reviewed supplier
exists.

`GitBlobReader.inspect_commit()` receives both `expected_commit_sha` and
`expected_base_sha`. The local adapter derives facts only with fixed local Git
argv: typed commit and tree resolution, exact parent list, typed base
resolution, `merge-base --is-ancestor`, then `rev-list --ancestry-path`.
Root and merge commits are rejected because this v1 receipt has one parent
anchor. The base must be an ancestor. Its canonical ancestry digest is
`SHA256("E4B-LOCAL-GIT-ANCESTRY-V1\\0" + base + "\\0" + commit + "\\0" +
NUL-joined-lexically-sorted-rev-list-ids)`, all identifiers encoded as ASCII.
`list_tree()` first resolves a tree, then parses only `ls-tree -r -z -l` bytes;
invalid NUL framing, non-blob entries, disallowed modes and malformed metadata
fail closed. `read_blob()` validates an exact lowercase 40-hex object id,
checks `cat-file` type and declared size, and bounds the content bytes before
returning them. The adapter runs no fetch, archive, filter, replace-object or
network-capable protocol. It rechecks a supplied capability's descriptors,
private control metadata and alternates immediately before a child exists.
Those checks detect state visible at that point, but cannot prevent a party
that can mutate the supplied object storage, control directory or executable
after the recheck. The future supplier must provide all three as private and
immutable. This module does not claim that a mutable shared checkout has become
a contained operational source. Descriptor execution contexts retain their
duplicated descriptors through one invocation and make close idempotent, so a
concurrent or repeated close cannot close a later reused descriptor.

## Independent anchors

`e4b_external_trust_anchors.py` is an inert, pure in-memory parser for a
synthetic external-anchor bundle. It accepts only `bytes` or absence, has no
path, descriptor, environment, Git, filesystem, process, socket or network
API, and applies a fixed 1,024-byte limit before UTF-8 decoding. The closed
flat bundle contains exact `schema`, `version`, and `algorithm` declarations,
then the current expected commit, tree, parent, base, ancestry digest,
patch-receipt digest, patch digest, recipe id/version, and mandatory opaque
manifest digest. It contains neither a self-digest nor an authority, signature,
issuer, trust-root, or operational-authorization value.

The canonical byte representation uses this exact field order, compact JSON
separators, ASCII-safe JSON encoding, and exactly one final LF. Parsing uses
strict UTF-8, duplicate-key rejection, exact scalar types, lowercase fixed-size
hashes, and the supported `sha256` algorithm, schema/version, and patch
recipe/version. Parse followed by serialization is byte-identical only for
canonical input. Absence, malformed input, non-canonical bytes, missing,
unknown or duplicate fields, malformed digests, unsupported declarations, and
limit excess have fixed sanitized codes. Invalid UTF-8, invalid JSON syntax,
and decoder-depth failure all intentionally share `ANCHOR_MALFORMED`; the JSON
decoder provides no safer useful distinction without echoing untrusted input.

The parser returns `ParsedSourceTrustAnchors`, which is a syntactic declaration
only. `VerifiedSourceTrustAnchors` is a nominal, nonconstructible capability
reserved for a future separately reviewed immutable-snapshot authority. This
slice has no factory, adopter, converter, deserializer, or public function that
produces it. A test-only `object.__new__` fixture represents arbitrary code in
the same Python interpreter and is outside the runtime API boundary; the exact
type is not claimed as protection against arbitrary in-process code.

Because the bundle deliberately has no self-authentication or authority value,
a differently canonical bundle can only become a different parsed declaration,
never a verified capability. That distinction is intentional and prevents this
parser from claiming provenance it cannot establish.

`materialize_authenticated_projection()` requires the exact verified type as
its first action. Absence, parsed declarations, subclasses, and any other type
raise `TRUST_ANCHORS_UNVERIFIED` before patch parsing, manifest parsing, reader
calls, blob requests, destination validation, or filesystem work. A lexically
invalid exact capability raises `TRUST_ANCHORS_INVALID` at the same boundary.
The materializer still does not accept repository metadata, a patch receipt, or
a manifest as their own authority. A future authority must bind the verified
capability to independently authenticated provenance before this source-only
interface can be adopted.

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

The local adapter is source-only infrastructure. It does not supply a trusted
fc09 input, change `closure_status`, establish an operational root of trust or
authorize adoption of the adapter in any environment. In particular, no
runtime synthetic-handle fixture exists, and the test-only white-box fixture
does not authorize a live local repository or close the future snapshot
requirement.

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
