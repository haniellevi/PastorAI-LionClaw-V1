"""Collect metadata/body hashes on the SAME live caller-owned SQL holder.

No connection, env/credential/path reader, persistent body, retry or CLI exists.
WindowEvidence is a required bound assertion from an externally authoritative
guard; this module cannot authenticate writer containment or its producer.
Authority/A8/operational flags always remain false.

Each execute+fetchone is atomic relative to pulse: the existing Pulse may issue
PING on this same cursor and replace its pending result. Open/read/close and
queries are pulsed before/after. A blocking reader can still exceed Pulse's2s
gap and will be REFUSED afterward; cooperative bounded native transport remains
an integration obligation. No threads or native HTTP keepalive proof is added.
reader.open receives a private dict (bucket/key/id/version/bytes/etag/sha256).
The frozen HTTPSReader expects SelectedObject instead: its cooperative adapter
and authenticated window producer are still pending at the native callsite.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re
import time

MAX_OBJECTS, MAX_BYTES, MAX_REFS = 1000, 1000000000, 10000
HEX = re.compile(r'[0-9a-f]{64}\Z')
SNAP = re.compile(r'[0-9A-F]{8}-[0-9A-F]{8}-[1-9][0-9]*\Z')
REFERENCES = {
    'public.messages': ('media_path', 'whatsapp-media'),
    'public.igrejas': ('logo_path', 'church-logos'),
    'public.cell_report_audio_inputs': ('storage_path', 'whatsapp-media'),
    'public.private_deletion_tasks': ('storage_path', 'whatsapp-media'),
}
CATALOG_SQL = b"""SELECT coalesce(jsonb_agg(row),'[]'::jsonb) FROM
(SELECT id,bucket_id,name,version,jsonb_build_object('size',metadata->'size',
'eTag',coalesce(metadata->>'eTag',metadata->>'etag')) AS metadata
FROM storage.objects ORDER BY bucket_id,name LIMIT 1001) row;"""
PRESENCE_SQL = ("SELECT jsonb_build_object(" + ','.join(
    "'%s',to_regclass('%s') IS NOT NULL" % (table, table) for table in REFERENCES) + ');').encode()


class Refused(ValueError):
    pass


@dataclass(frozen=True, repr=False)
class WindowEvidence:
    request_sha256: str
    source_sha256: str
    window_sha256: str
    interval_started_at: float
    valid_until: float
    allowed: bool


@dataclass(frozen=True, repr=False)
class PrivateMaterial:
    sql_projection: bytes
    catalog: tuple
    manifest: dict
    manifest_sha256: str


def need(ok, code):
    if not ok:
        raise Refused(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def hex64(value):
    return type(value) is str and HEX.fullmatch(value) is not None


def copy_cell(value):
    if value is None:
        return b'\\N'
    raw = value.encode()
    for old, new in ((b'\\', b'\\\\'), (b'\b', b'\\b'), (b'\f', b'\\f'),
                     (b'\n', b'\\n'), (b'\r', b'\\r'), (b'\t', b'\\t'), (b'\v', b'\\v')):
        raw = raw.replace(old, new)
    return raw


def copy_block(table, columns, rows):
    return ((f'COPY {table} ({", ".join(columns)}) FROM stdin;\n').encode()
            + b''.join(b'\t'.join(copy_cell(v) for v in row)+b'\n' for row in rows) + b'\\.\n')


class Collector:
    def __init__(self, request_sha256, expected_source_sha256, expected_window_sha256,
                 preserved_objects, reader, guard, state_reader):
        need(all(hex64(v) for v in (request_sha256, expected_source_sha256, expected_window_sha256)),
             'joint-binding-profile')
        need(callable(guard) and callable(state_reader) and callable(getattr(reader, 'open', None)),
             'joint-adapter-profile')
        need(type(preserved_objects) in (list, tuple) and len(preserved_objects) <= MAX_OBJECTS,
             'joint-preserved-limit')
        rows, total = {}, 0
        for item in preserved_objects:
            need(type(item) is dict and all(type(item.get(k)) is str and item[k]
                 for k in ('bucket','key','id','version')) and hex64(item.get('sha256')),
                 'joint-preserved-profile')
            need(type(item.get('bytes')) is int and 0 <= item['bytes'] <= MAX_BYTES,
                 'joint-preserved-limit')
            need(item.get('etag') is None or type(item['etag']) is str, 'joint-preserved-profile')
            total += item['bytes']
            need(total <= MAX_BYTES, 'joint-preserved-limit')
            identity = item['bucket'], item['key']
            need(identity not in rows, 'joint-preserved-profile')
            rows[identity] = {k:item.get(k) for k in ('bucket','key','id','version','bytes','etag','sha256')}
        self.request, self.source, self.window = request_sha256, expected_source_sha256, expected_window_sha256
        self.preserved, self.reader, self.guard, self.state_reader = rows, reader, guard, state_reader

    def __call__(self, *, holder, snapshot, dump, pulse, deadline, capture_started_at, source_identity_sha256):
        try:
            need(hex64(source_identity_sha256) and source_identity_sha256 == self.source, 'joint-source-binding')
            need(type(snapshot) is dict and set(snapshot) == {'exported_id','holder'}
                 and type(snapshot['exported_id']) is str and SNAP.fullmatch(snapshot['exported_id']),
                 'joint-snapshot-profile')
            expected = json.loads(encoded(snapshot['holder']))
            need(type(expected) is dict and set(expected) == {'database','readonly','isolation','snapshot',
                 'backend','role','session_role','transaction_start'} and expected['readonly'] == 'on'
                 and expected['isolation'] == 'repeatable read' and type(expected['backend']) is int
                 and expected['backend'] > 0 and all(type(expected[k]) is str and expected[k]
                 for k in ('database','snapshot','role','session_role','transaction_start')),
                 'joint-holder-profile')
            need(type(dump) is dict and set(dump) == {'exit_code','imported_snapshot','sha256','bytes'}
                 and type(dump['exit_code']) is int and dump['exit_code'] == 0
                 and dump['imported_snapshot'] == snapshot['exported_id'] and hex64(dump['sha256'])
                 and type(dump['bytes']) is int and 0 < dump['bytes'] <= 104857600, 'joint-dump-binding')
            need(callable(pulse) and finite(deadline) and finite(capture_started_at), 'joint-adapter-profile')

            def checkpoint():
                need(time.monotonic() < deadline, 'joint-deadline')
                try:
                    pulse()
                except Exception:
                    raise Refused('joint-pulse-refused') from None
                try:
                    evidence = self.guard(self.request, self.source, self.window, capture_started_at, deadline)
                except Exception:
                    raise Refused('joint-window-refused') from None
                now = time.time()
                need(type(evidence) is WindowEvidence and evidence.allowed is True
                     and (evidence.request_sha256,evidence.source_sha256,evidence.window_sha256)
                     == (self.request,self.source,self.window)
                     and finite(evidence.interval_started_at) and finite(evidence.valid_until)
                     and evidence.interval_started_at <= capture_started_at <= now < evidence.valid_until,
                     'joint-window-refused')
                need(time.monotonic() < deadline, 'joint-deadline')
                try:
                    pulse()
                except Exception:
                    raise Refused('joint-pulse-refused') from None

            def state():
                checkpoint()
                current = self.state_reader(holder)
                checkpoint()
                need(current == expected, 'joint-holder-changed')

            def query(sql):
                checkpoint()
                holder.execute(sql)
                result = holder.fetchone()  # NO pulse here: Pulse can replace pending rows.
                checkpoint()
                need(type(result) in (tuple,list) and len(result) == 1, 'joint-query-profile')
                value = json.loads(result[0]) if type(result[0]) is str else result[0]
                need(len(encoded(value)) <= 16*1024*1024, 'joint-query-limit')
                return value

            state()
            catalog = query(CATALOG_SQL)
            need(type(catalog) is list and len(catalog) <= MAX_OBJECTS, 'joint-catalog-limit')
            current = {}
            for item in catalog:
                need(type(item) is dict and set(item) == {'id','bucket_id','name','version','metadata'}
                     and all(type(item[k]) is str and item[k] for k in ('id','bucket_id','name','version'))
                     and type(item['metadata']) is dict, 'joint-catalog-profile')
                metadata = item['metadata']
                size = metadata.get('size')
                etag = metadata.get('eTag', metadata.get('etag'))
                need(type(size) is int and 0 <= size <= MAX_BYTES
                     and (etag is None or type(etag) is str), 'joint-catalog-profile')
                identity = item['bucket_id'], item['name']
                need(identity not in current, 'joint-catalog-profile')
                current[identity] = dict(bucket=identity[0],key=identity[1],id=item['id'],version=item['version'],
                                         bytes=size,etag=etag)
            need(set(current) == set(self.preserved) and all(all(row[k] == self.preserved[i][k]
                 for k in ('id','version','bytes','etag')) for i,row in current.items()), 'joint-catalog-drift')
            presence = query(PRESENCE_SQL)
            need(type(presence) is dict and set(presence) == set(REFERENCES)
                 and all(type(v) is bool for v in presence.values()), 'joint-reference-profile')
            summaries, blocks, reference_total = {}, [], 0
            for table,(column,bucket) in REFERENCES.items():
                if not presence[table]:
                    summaries[table] = dict(state='not_projected', rows=None, nonempty_references=None,
                                             missing_in_catalog=None,missing_in_preserved=None)
                    continue
                sql = (f"SELECT coalesce(jsonb_agg(row),'[]'::jsonb) FROM "
                       f"(SELECT {column} AS path FROM {table} ORDER BY {column} NULLS FIRST LIMIT 10001) row;").encode()
                rows = query(sql)
                need(type(rows) is list, 'joint-reference-profile')
                reference_total += len(rows)
                need(reference_total <= MAX_REFS, 'joint-reference-limit')
                need(all(type(row) is dict and set(row) == {'path'}
                     and (row['path'] is None or type(row['path']) is str
                     and len(row['path'].encode()) <= 4096) for row in rows), 'joint-reference-profile')
                refs = [(bucket,row['path']) for row in rows if row['path'] not in (None,'')]
                summaries[table] = dict(state='projected',rows=len(rows),nonempty_references=len(refs),
                    missing_in_catalog=sum(i not in current for i in refs),
                    missing_in_preserved=sum(i not in self.preserved for i in refs))
                blocks.append(copy_block(table,[column],[(row['path'],) for row in rows]))
            hashed, total = [], 0
            for identity in sorted(current):
                entry = self.preserved[identity]
                checkpoint()
                with self.reader.open(dict(entry), deadline) as stream:
                    checkpoint()
                    size, digest = 0, hashlib.sha256()
                    while True:
                        checkpoint()
                        # Never consume cap+1. Once the hard aggregate quota is
                        # exhausted without observed EOF, refuse before probing
                        # again (even an exactly-cap-sized body is conservative
                        # refusal until a native EOF contract is available).
                        need(total < MAX_BYTES, 'joint-body-quota')
                        limit = min(65536, entry['bytes']-size+1, MAX_BYTES-total)
                        chunk = stream.read(limit, deadline)
                        checkpoint()
                        need(type(chunk) is bytes and len(chunk) <= limit, 'joint-body-profile')
                        if not chunk:
                            break
                        size += len(chunk)
                        total += len(chunk)
                        need(size <= entry['bytes'] and total <= MAX_BYTES, 'joint-body-size')
                        digest.update(chunk)
                    checkpoint()  # Immediately before reader cleanup.
                checkpoint()
                need(size == entry['bytes'], 'joint-body-size')
                need(digest.hexdigest() == entry['sha256'], 'joint-body-hash')
                hashed.append(dict(entry))
            state()
            catalog_rows = [(r['id'],r['bucket'],r['key'],r['version'],
                             encoded(dict(size=r['bytes'],eTag=r['etag'])).decode())
                            for _,r in sorted(current.items())]
            projection = copy_block('storage.objects',['id','bucket_id','name','version','metadata'],catalog_rows)
            projection += b''.join(blocks)
            need(len(projection) <= 16*1024*1024, 'joint-projection-limit')
            manifest = dict(schema='igreja12.live-holder-joint-material/1',request_sha256=self.request,
                source_sha256=self.source,window_sha256=self.window,capture_started_at=capture_started_at,
                snapshot=dict(exported_id=snapshot['exported_id'],holder=expected),dump=dict(dump),
                sql_projection_sha256=hashlib.sha256(projection).hexdigest(),objects=hashed,
                authority_verified=False,provider_immutability_verified=False)
            checkpoint()
            private = PrivateMaterial(projection,tuple(current[i] for i in sorted(current)),manifest,
                                      hashlib.sha256(encoded(manifest)).hexdigest())
            aggregate = dict(schema='igreja12.joint-collector-aggregates/1',selected_objects=len(current),
                hashed_objects=len(hashed),hashed_bytes=total,references=summaries,
                same_holder_snapshot_observed=True,source_body_hashes_verified=True,
                authority_verified=False,native_transport_keepalive_proven=False,
                all_application_references_covered=False,a8_window_proven=False,
                operational_receipt=False,production_go=False)
            return private, aggregate
        except Refused:
            raise
        except Exception:
            raise Refused('joint-collector-failed') from None
