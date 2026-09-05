"""Review-maintained V5 pins kept outside the mutable proposal JSON.

The V4 values are historical anchors and must not be sourced from the V5
proposal. V5 artifact digests are updated only when the corresponding source
artifact is reviewed; the verifier's own digest is therefore not
self-referential.
"""

V4_ANCHORS = {
    "v4_proposal_sha256": "92b1c33ab3e2cd0a6c9b5ad486a317c229d7aefc7c60da88913716d58345e6ac",
    "v4_schema_sha256": "e10d8922a68a6f475191330dbecf0c00b2e5ffccf03e9fb4726bdcb30c4d494f",
    "v4_verifier_sha256": "3cb09957b283b254bb88b97456e065a18f390d707fcbd77c71530f8052266af3",
}

# Set after the source package is stable. This module intentionally does not
# contain its own digest, avoiding a hash cycle.
V5_ARTIFACT_PINS: dict[str, str] = {
    "intent_v2_sha256": "ed88e94768d00d4c874005bcefa58489699c09445193c0e0db6b53d9ccb66bf9",
    "author_sha256": "a32ba4e92aabfa38e7b8a4cad5ce0682e387fad61f67351ca08568cca8719c48",
    "replay_sha256": "bfe5e8dea591a9b3085b5d19ebac70ddcc8d48937dce9dd76289f00ecdbabd8f",
    "tests_sha256": "667fe23cc1ecfd05a535d71de4d1ada7f65986bc8739335779ca0363884213f9",
    "v5_schema_sha256": "474d0c38b8a630284232e3002c469a9a09a9a4d203b7d5009100c233143ddf97",
    "v5_verifier_sha256": "d200da14d3d287840ccae7a8a2cef75ad03c69737a58417f673e91dd17d1090a",
    "workflow_sha256": "d06affc6051d46fdfa88fa5d24bfd42ce013572c8d0ba55c25c28056e9df525a",
}
