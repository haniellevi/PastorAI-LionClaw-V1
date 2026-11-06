"""Required SQL/API/Storage authority, with no operational authority issuer.

The supplied inventory is a reviewed lower bound, never discovery or proof of
completeness. Requirements are diagnostics, not a receipt. No JSON, hash, lease,
observation, RLS rule or local containment result can replace a native mechanism
that continuously owns every writer and its in-flight work. That mechanism is
not implemented: admission and authority validation always refuse.
"""
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from initial_transition_ops import Refused, require

INVENTORY_SCHEMA = 'igreja12.native-fence-inventory/1'
REQUIREMENTS_SCHEMA = 'igreja12.native-fence-requirements/1'
CODE = 'native-fence-contract-refused'
UNAVAILABLE = 'native-fence-authoritative-mechanism-unavailable'
REQUIRED_ROUTES = (
    'api-compose', 'queue-worker-compose', 'cron-worker-compose', 'broadcast-worker-compose',
    'sqlalchemy-direct', 'ingress-nginx-public', 'ingress-evolution-bridge',
    'sql-external-clients', 'sql-open-transactions', 'data-api',
    'storage-https-service-role', 'storage-s3', 'storage-signed-uploads',
    'storage-resumable-uploads', 'storage-inflight-uploads',
)
REQUIRED_BUCKETS = ('whatsapp-media', 'church-logos')
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_NAME = re.compile(r'[a-z0-9][a-z0-9._-]{0,127}\Z')


def _hex(value):
    return type(value) is str and _HEX.fullmatch(value) is not None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _names(values, minimum):
    return (type(values) is tuple and len(minimum) <= len(values) <= 256
            and all(type(v) is str and _NAME.fullmatch(v) is not None for v in values)
            and len(set(values)) == len(values) and set(minimum) <= set(values))


@dataclass(frozen=True)
class NativeFenceInventory:
    source_identity: str
    host_scope_digest: str
    routes: tuple[str, ...]
    storage_buckets: tuple[str, ...]
    schema: str = INVENTORY_SCHEMA

    def __post_init__(self):
        require(_hex(self.source_identity) and _hex(self.host_scope_digest)
                and type(self.schema) is str and self.schema == INVENTORY_SCHEMA
                and _names(self.routes, REQUIRED_ROUTES)
                and _names(self.storage_buckets, REQUIRED_BUCKETS), CODE)

    @property
    def digest(self):
        self.__post_init__()
        return _digest(asdict(self))


class NativeFenceContract:
    """Pinned diagnostic obligations; deliberately has no authority callback.

    Hash binding detects drift in the supplied inventory, not completeness or
    malicious code running in this Python process. Additional names are retained
    and represented as unresolved hashes; they do not silently disappear.
    """
    def __init__(self, request_sha256, context_sha256, inventory, expected_inventory_sha256):
        require(_hex(request_sha256) and _hex(context_sha256)
                and _hex(expected_inventory_sha256) and type(inventory) is NativeFenceInventory, CODE)
        require(inventory.digest == expected_inventory_sha256, CODE)
        self._inventory = inventory
        self._bindings = (request_sha256, context_sha256, expected_inventory_sha256)

    def requirements(self):
        try:
            inventory = self._inventory
            request, context, expected = self._bindings
            require(type(inventory) is NativeFenceInventory and inventory.digest == expected, CODE)
            extras = tuple(r for r in inventory.routes if r not in REQUIRED_ROUTES)
            buckets = tuple(b for b in inventory.storage_buckets if b not in REQUIRED_BUCKETS)
            domains = [
                {'domain': 'application', 'routes': list(REQUIRED_ROUTES[:7]), 'coverage_proven': False,
                 'obligations': [
                     'own-compose-api-queue-cron-broadcast-and-direct-sqlalchemy-writers',
                     'control-public-nginx-and-internal-evolution-bridge-independently',
                     'drain-inflight-requests-jobs-and-existing-connection-pools',
                     'exclude-restart-reconnect-and-other-uninventoried-writers',
                 ]},
                {'domain': 'sql', 'routes': list(REQUIRED_ROUTES[7:10]), 'coverage_proven': False,
                 'obligations': [
                     'authenticate-native-control-plane-owner-of-pinned-source-database',
                     'exclude-all-roles-direct-external-clients-and-data-api-writes',
                     'resolve-existing-transactions-and-inflight-statements-before-capture',
                     'cover-sequences-ddl-and-all-mutable-database-state',
                     'read-only-defaults-repeatable-read-table-locks-and-zero-observation-are-insufficient',
                 ]},
                {'domain': 'storage', 'routes': list(REQUIRED_ROUTES[10:]), 'coverage_proven': False,
                 'buckets': list(REQUIRED_BUCKETS), 'obligations': [
                     'independently-bind-storage-project-account-and-source-database',
                     'own-bytes-and-metadata-for-every-bucket-including-uninventoried-buckets',
                     'exclude-service-role-https-s3-and-existing-credentials',
                     'resolve-signed-resumable-and-inflight-uploads-before-capture',
                     'sql-rls-nginx-or-postgres-network-restrictions-do-not-fence-storage',
                 ]},
                {'domain': 'handoff', 'routes': [], 'coverage_proven': False,
                 'obligations': [
                     'independently-verify-authorized-owner-and-complete-writer-inventory',
                     'bind-continuous-authority-to-request-context-source-and-host-scope',
                     'retain-exclusive-custody-through-capture-validation-and-clone-proof',
                     'verify-no-gap-handoff-to-exact-authorized-ddl-writer',
                     'expiry-owner-loss-cancellation-or-uncertainty-must-fail-closed',
                     'no-automatic-resume-or-release-based-on-json-lease-hash-or-cleanup',
                 ]},
            ]
            return {
                'schema': REQUIREMENTS_SCHEMA,
                'bindings': {'request_digest': request, 'context_digest': context,
                             'inventory_digest': expected, 'source_identity': inventory.source_identity,
                             'host_scope_digest': inventory.host_scope_digest},
                'domains': domains,
                'interval': {'continuous_required': True, 'starts_before': 'fresh-capture',
                             'ends_after': 'verified-handoff-to-authorized-ddl-writer'},
                'unresolved': {'route_sha256': [_digest(r) for r in extras],
                               'bucket_sha256': [_digest(b) for b in buckets],
                               'route_count': len(extras), 'bucket_count': len(buckets)},
                'inventory_exhaustive_proven': False, 'mechanism_available': False,
                'authority_verified': False, 'source_unchanged_proven': False,
                'storage_immutability_proven': False, 'a8_window_proven': False,
                'ddl_authorized': False, 'operational_ready': False,
            }
        except BaseException:
            raise Refused(CODE) from None

    def admit(self):
        raise Refused(UNAVAILABLE)

    def validate_authority(self, evidence):
        # Do not inspect/call an untrusted evidence object, even for truthiness.
        raise Refused(UNAVAILABLE)
