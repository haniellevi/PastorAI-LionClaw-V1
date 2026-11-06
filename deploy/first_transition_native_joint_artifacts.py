"""Private SQL projection/manifest custody, separate from dump and companion.

The live-holder collector may produce 16 MiB of projection, exceeding the
2 MiB companion budget. This fixed pair has its own preprovisioned private
root and request-exclusive directory. It retains no object bodies and proves
neither provider immutability nor an authoritative fence nor recoverability.
Use under the same externally bounded worker as the source holder; local
filesystem calls can block in the kernel. No operational receipt is emitted.
"""
import hashlib
import json
import math
import re

from first_transition_window_backup import NativeWindowArtifacts
from initial_transition_ops import Refused, require

SCHEMA = 'igreja12.live-holder-joint-material/1'
HEX = re.compile(r'[0-9a-f]{64}\Z')
SNAP = re.compile(r'[0-9A-F]{8}-[0-9A-F]{8}-[1-9][0-9]*\Z')
BINDING_FIELDS = frozenset(('request_sha256','source_sha256','window_sha256','snapshot_token','dump_sha256'))
MANIFEST_FIELDS = frozenset(('schema','request_sha256','source_sha256','window_sha256','capture_started_at',
    'snapshot','dump','sql_projection_sha256','objects','authority_verified','provider_immutability_verified'))
HOLDER_FIELDS = frozenset(('database','readonly','isolation','snapshot','backend','role','session_role','transaction_start'))
OBJECT_FIELDS = frozenset(('bucket','key','id','version','bytes','etag','sha256'))


def _hex(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def _encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


class NativeJointArtifacts(NativeWindowArtifacts):
    """Bounded, immutable-on-delivery pair; metadata is never authorization."""
    FILES = {'projection': ('storage-projection.sql',16777216), 'manifest': ('storage-manifest.json',2097152)}

    def capture(self, *_args, **_kwargs):
        """No unvalidated streaming entry for the structured joint material."""
        raise Refused('native-joint-artifact-use-material')

    def capture_material(self, *, projection, manifest, manifest_sha256, expected_binding, timeout=10, pulse):
        """Validate independently supplied bindings, then privately persist both.

        ``expected_binding`` is exactly request_sha256/source_sha256/
        window_sha256/snapshot_token/dump_sha256 from the live job, never
        inferred from this manifest. They establish association only. False
        authority/immutability assertions are preserved and cannot unlock A8.
        The caller must retain and call its SAME dump pulse; no pulse is reset.
        """
        try:
            deadline = self._deadline(timeout)
            self._links()
            require(not self._artifacts and callable(pulse), 'native-joint-artifact-profile')
            pulse()
            require(type(expected_binding) is dict and set(expected_binding) == BINDING_FIELDS
                    and all(_hex(expected_binding[k]) for k in BINDING_FIELDS-{'snapshot_token'})
                    and type(expected_binding['snapshot_token']) is str
                    and SNAP.fullmatch(expected_binding['snapshot_token'])
                    and expected_binding['request_sha256'] == self.request_digest,
                    'native-joint-artifact-binding')
            require(type(projection) is bytes and 0 < len(projection) <= self.FILES['projection'][1]
                    and type(manifest) is dict and set(manifest) == MANIFEST_FIELDS
                    and _hex(manifest_sha256), 'native-joint-artifact-profile')
            encoded = _encoded(manifest)
            require(0 < len(encoded) <= self.FILES['manifest'][1]
                    and hashlib.sha256(encoded).hexdigest() == manifest_sha256,
                    'native-joint-artifact-manifest')
            # Freeze mutable caller input before validating and writing it.
            value = json.loads(encoded)
            require(value['schema'] == SCHEMA
                    and value['authority_verified'] is False and value['provider_immutability_verified'] is False
                    and all(value[k] == expected_binding[k] for k in ('request_sha256','source_sha256','window_sha256'))
                    and type(value['capture_started_at']) in (int,float)
                    and math.isfinite(value['capture_started_at']) and value['capture_started_at'] > 0
                    and value['sql_projection_sha256'] == hashlib.sha256(projection).hexdigest(),
                    'native-joint-artifact-binding')
            snapshot, dump = value['snapshot'],value['dump']
            require(type(snapshot) is dict and set(snapshot) == {'exported_id','holder'}
                    and snapshot['exported_id'] == expected_binding['snapshot_token']
                    and type(snapshot['holder']) is dict and set(snapshot['holder']) == HOLDER_FIELDS,
                    'native-joint-artifact-snapshot')
            holder = snapshot['holder']
            require(holder['readonly'] == 'on' and holder['isolation'] == 'repeatable read'
                    and type(holder['backend']) is int and holder['backend'] > 0
                    and all(type(holder[k]) is str and holder[k]
                            for k in HOLDER_FIELDS-{'backend','readonly','isolation'}),
                    'native-joint-artifact-snapshot')
            require(type(dump) is dict and set(dump) == {'exit_code','imported_snapshot','sha256','bytes'}
                    and type(dump['exit_code']) is int and dump['exit_code'] == 0
                    and dump['imported_snapshot'] == expected_binding['snapshot_token']
                    and dump['sha256'] == expected_binding['dump_sha256']
                    and type(dump['bytes']) is int and 0 < dump['bytes'] <= 104857600,
                    'native-joint-artifact-dump')
            require(type(value['objects']) is list and len(value['objects']) <= 1000,
                    'native-joint-artifact-objects')
            identities, total = set(),0
            for item in value['objects']:
                require(type(item) is dict and set(item) == OBJECT_FIELDS
                        and all(type(item[k]) is str and item[k] for k in ('bucket','key','id','version'))
                        and _hex(item['sha256']) and (item['etag'] is None or type(item['etag']) is str)
                        and type(item['bytes']) is int and 0 <= item['bytes'] <= 1000000000,
                        'native-joint-artifact-objects')
                identity = item['bucket'],item['key']
                total += item['bytes']
                require(identity not in identities and total <= 1000000000, 'native-joint-artifact-objects')
                identities.add(identity)
            pulse()
            self._write_private('projection',projection,timeout=self._remaining(deadline),pulse=pulse)
            self._write_private('manifest',encoded,timeout=self._remaining(deadline),pulse=pulse)
            result = self.metadata(timeout=self._remaining(deadline))
            pulse()
            self._remaining(deadline)
            return result
        except Exception:
            self._failed = True
            raise Refused('native-joint-artifact-failed') from None
        except BaseException:
            self._failed = True
            raise KeyboardInterrupt from None
