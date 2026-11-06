"""CA custody and psycopg2 entrypoint guard for one explicitly admitted process.

Enter before importing the application; keep the context for its entire life.
Only calls through the installed psycopg2.connect entrypoint are covered. This
is not a sandbox for arbitrary Python, cached driver aliases or native code.
While custody/cleanup is armed, os.fork children immediately os._exit(78), without interpreter/libpq teardown;
exec inheritance is disabled and multiprocessing is not admitted. This is not
coverage of native C forks/execs that bypass Python's at-fork callbacks. Local
filesystem/native-driver calls still need an external deadline.
The public profile's expected digest must come from independent trusted review.
"""
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import PurePosixPath
import re
import stat
import sys
import threading

import psycopg2
from psycopg2.extensions import make_dsn, parse_dsn

SCHEMA = 'igreja12.native-candidate-ca-profile/1'
MARKER_SCHEMA = 'igreja12.native-candidate-ca-live-fd/1'
OPTIONS = ('-c default_transaction_read_only=off -c search_path=pg_catalog,public '
           '-c row_security=on -c statement_timeout=8000')
ADD_SEALS, GET_SEALS, SEALS = 1033, 1034, 15  # Linux UAPI: all four original seals.
MAX_CA = 65536
IDENTITY_SQL = (
    'SELECT s.system_identifier::text,d.oid::bigint,d.datname,current_user,session_user,'
    "pg_catalog.current_setting('transaction_read_only'),"
    "pg_catalog.current_setting('transaction_isolation'),"
    "pg_catalog.current_setting('default_transaction_read_only'),"
    "pg_catalog.current_setting('row_security') "
    'FROM pg_catalog.pg_control_system() s,pg_catalog.pg_database d '
    'WHERE d.datname=pg_catalog.current_database()')
KEEPALIVES = dict(keepalives='1',keepalives_idle='30',keepalives_interval='10',keepalives_count='3')
_installed = None
_IMPORT_PID = os.getpid()
FORK_EXIT_CODE = 78


class Refused(ValueError):
    """Fixed public code; no driver/conninfo text is reflected."""


def need(value, code='native-candidate-ca-refused'):
    if not value:raise Refused(code)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def hex64(value):return type(value) is str and re.fullmatch('[0-9a-f]{64}',value) is not None


@dataclass(frozen=True)
class CandidateCAProfile:
    request_digest: str
    context_digest: str
    host: str
    hostaddr: str
    port: int
    ca_file: str
    ca_sha256: str
    ca_owner: int
    source_identity: str
    schema: str = SCHEMA
    process_model: str = 'single-process-no-exec'
    dbname: str = 'postgres'
    user: str = 'postgres'
    server_version: int = 170006

    def validated(self):
        need(self.schema == SCHEMA and self.process_model == 'single-process-no-exec'
             and all(hex64(value) for value in (self.request_digest,self.context_digest,self.ca_sha256,self.source_identity))
             and type(self.host) is str and len(self.host)<=253
             and re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',self.host)
             and all(label and len(label)<=63 and not label.startswith('-') and not label.endswith('-')
                     for label in self.host.split('.'))
             and type(self.hostaddr) is str and '%' not in self.hostaddr
             and str(ipaddress.ip_address(self.hostaddr)) == self.hostaddr
             and type(self.port) is int and 0<self.port<65536
             and type(self.ca_owner) is int and self.ca_owner>=0
             and type(self.ca_file) is str and self.ca_file.startswith('/')
             and not any(part in ('.','..') for part in self.ca_file.split('/')[1:])
             and str(PurePosixPath(self.ca_file)) == self.ca_file
             and self.dbname == self.user == 'postgres'
             and type(self.server_version) is int and self.server_version == 170006)
        return self

    @classmethod
    def from_dict(cls,value):
        try:
            need(type(value) is dict and set(value)==set(cls.__dataclass_fields__))
            return cls(**value).validated()
        except Exception:
            raise Refused('native-candidate-ca-profile') from None


def _pin(info):
    return (info.st_dev,info.st_ino,info.st_uid,info.st_mode,info.st_nlink,
            info.st_size,info.st_mtime_ns,info.st_ctime_ns)


def _dirpin(info):return (info.st_dev,info.st_ino,info.st_uid,info.st_mode)


def _start_ticks(pid):
    with open(f'/proc/{pid}/stat',encoding='ascii') as handle:value=handle.read(8192)
    return int(value[value.rfind(')')+2:].split()[19])


class NativeCandidateCA:
    """Own sealed CA and validated DB handles until application shutdown.

    The hook deliberately stays installed, closed, after exit. It cannot turn
    into an unguarded connection path while leftover application threads exit.
    No second lifecycle, exec or inherited child lifecycle is supported.
    """
    def __init__(self, profile, expected_profile_sha256):
        try:
            need(type(profile) is CandidateCAProfile and hex64(expected_profile_sha256))
            profile.validated()
            need(digest(asdict(profile)) == expected_profile_sha256)
        except Exception:
            raise Refused('native-candidate-ca-profile') from None
        self.profile,self._profile_digest=profile,expected_profile_sha256
        self._pid=self._start=None
        self._fds=[];self._directories=[];self._source=self._sealed=None
        self._source_pin=self._sealed_pin=None
        self._used=self._active=self._failed=False
        self._connections=[];self._auth=None;self._driver=None
        self._fork_state=None
        self._lock=threading.RLock()
        self._hook=self.connect

    def __repr__(self):return '<NativeCandidateCA private>'

    def _owner_process(self):
        need(self._pid is not None,'native-candidate-ca-process')
        if os.getpid()!=self._pid:
            # Only a process whose PID changed since module import may be
            # terminated here. A damaged owner field in the original process
            # must never terminate the parent.
            if os.getpid()!=_IMPORT_PID:os._exit(FORK_EXIT_CODE)
            raise Refused('native-candidate-ca-process')

    def _remember(self,fd):
        try:info=os.fstat(fd)
        except BaseException:
            os.close(fd)
            raise
        self._fds.append((fd,info.st_dev,info.st_ino))
        return fd

    def __enter__(self):
        global _installed
        need(not self._used,'native-candidate-ca-used');self._used=True
        try:
            need(sys.version_info[:2] == (3,13) and threading.current_thread() is threading.main_thread()
                 and _installed is None and not any(name=='app' or name.startswith('app.') for name in sys.modules)
                 and not isinstance(getattr(psycopg2.connect,'__self__',None),NativeCandidateCA),
                 'native-candidate-ca-process')
            self._pid,self._start=os.getpid(),_start_ticks(os.getpid())
            parts=self.profile.ca_file.split('/')[1:]
            parent=self._remember(os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC))
            self._directories.append((None,None,parent,_dirpin(os.fstat(parent))))
            for name in parts[:-1]:
                child=self._remember(os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent))
                self._directories.append((parent,name,child,_dirpin(os.fstat(child))))
                parent=child
            self._source=self._remember(os.open(parts[-1],os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent))
            info=os.fstat(self._source)
            need(stat.S_ISREG(info.st_mode) and info.st_uid==self.profile.ca_owner and info.st_nlink==1
                 and stat.S_IMODE(info.st_mode) in (0o400,0o444,0o600,0o644) and 0<info.st_size<=MAX_CA)
            self._source_pin=_pin(info)
            data=os.pread(self._source,MAX_CA+1,0)
            need(len(data)==info.st_size and hashlib.sha256(data).hexdigest()==self.profile.ca_sha256
                 and _pin(os.fstat(self._source))==self._source_pin)
            self._sealed=self._remember(os.memfd_create('igreja12-candidate-ca',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING))
            os.fchmod(self._sealed,0o400)
            offset=0
            while offset<len(data):
                count=os.write(self._sealed,data[offset:]);need(count>0);offset+=count
            fcntl.fcntl(self._sealed,ADD_SEALS,SEALS)
            self._sealed_pin=_pin(os.fstat(self._sealed))
            self._active=True
            self._driver=psycopg2.connect
            self._assert_live(installed=False)
            owner_pid=os.getpid()
            fork_state={'armed':True}
            def after_child():
                # Never decref inherited connections: psycopg2's destructor
                # can PQfinish/Terminate a socket still used by the parent.
                # No cleanup, logging, Python finalizers or inherited locks.
                if fork_state['armed'] and os.getpid()!=owner_pid:os._exit(FORK_EXIT_CODE)
            os.register_at_fork(after_in_child=after_child)
            self._fork_state=fork_state
            psycopg2.connect=self._hook
            _installed=self
            return self
        except Exception:
            self._failed=True;self._active=False;self._release_fds()
            raise Refused('native-candidate-ca-startup') from None
        except BaseException:
            self._failed=True;self._active=False;self._release_fds()
            raise KeyboardInterrupt from None

    def _assert_live(self, *, installed=True):
        need(self._active and not self._failed and os.getpid()==self._pid
             and digest(asdict(self.profile))==self._profile_digest,'native-candidate-ca-lifetime')
        if installed:need(psycopg2.connect is self._hook and _installed is self,'native-candidate-ca-lifetime')
        for parent,name,fd,pin in self._directories:
            need(_dirpin(os.fstat(fd))==pin)
            need(_dirpin(os.stat('/' if parent is None else name,dir_fd=parent,follow_symlinks=False))==pin)
        parent=self._directories[-1][2]
        need(_pin(os.stat(PurePosixPath(self.profile.ca_file).name,dir_fd=parent,follow_symlinks=False))==self._source_pin
             and _pin(os.fstat(self._source))==self._source_pin
             and hashlib.sha256(os.pread(self._source,MAX_CA+1,0)).hexdigest()==self.profile.ca_sha256)
        need(_pin(os.fstat(self._sealed))==self._sealed_pin
             and fcntl.fcntl(self._sealed,GET_SEALS)&SEALS==SEALS
             and not os.get_inheritable(self._sealed)
             and hashlib.sha256(os.pread(self._sealed,MAX_CA+1,0)).hexdigest()==self.profile.ca_sha256)

    def _parameters(self,args,kwargs):
        need(len(args)<=1 and (not args or type(args[0]) is str))
        values=dict(kwargs)
        need('dsn' not in values or not args)
        dsn=values.pop('dsn',args[0] if args else '')
        need(dsn is None or type(dsn) is str and len(dsn)<=16384 and not any(c in dsn for c in '\r\n\x00'))
        need(not any(name.upper().startswith('PG') for name in os.environ),'native-candidate-ca-environment')
        need(parse_dsn('sslcertmode=disable')=={'sslcertmode':'disable'})
        need(all(type(value) in (str,int) for value in values.values()))
        parsed=parse_dsn(make_dsn(dsn,**values))
        required=dict(host=self.profile.host,hostaddr=self.profile.hostaddr,port=str(self.profile.port),
            dbname=self.profile.dbname,user=self.profile.user,sslmode='verify-full',sslcertmode='disable',
            channel_binding='require',gssencmode='disable',ssl_min_protocol_version='TLSv1.2',
            connect_timeout='5',application_name='igreja12-native-candidate',options=OPTIONS)
        if self.profile.port==5432:parsed.setdefault('port','5432')
        need(set(parsed)<=set(required)|{'password','sslrootcert'}|set(KEEPALIVES)
             and all(parsed.get(key)==value for key,value in required.items())
             and all(key not in parsed or parsed[key]==value for key,value in KEEPALIVES.items())
             and parsed.get('sslrootcert') in (self.profile.ca_file,f'/proc/self/fd/{self._sealed}')
             and type(parsed.get('password')) is str and 0<len(parsed['password'])<=8192
             and not any(c in parsed['password'] for c in '\r\n\x00'),'native-candidate-ca-conninfo')
        auth=(parsed['host'],parsed['port'],parsed['dbname'],parsed['user'],parsed['password'])
        need(self._auth is None or self._auth==auth,'native-candidate-ca-credentials')
        self._auth=auth
        parsed['sslrootcert']=f'/proc/self/fd/{self._sealed}'
        return parsed

    def _validate_connection(self,conn,params):
        info=conn.info
        need(not conn.closed and info.used_password is True and info.ssl_in_use is True
             and info.ssl_attribute('protocol') in ('TLSv1.2','TLSv1.3')
             and type(info.server_version) is int and info.server_version==self.profile.server_version
             and type(info.transaction_status) is int and info.transaction_status==0
             and all(info.dsn_parameters.get(key)==value for key,value in params.items() if key!='password'),
             'native-candidate-ca-authentication')
        need(conn.autocommit is False)
        conn.autocommit=True
        with conn.cursor() as cursor:
            cursor.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            try:
                cursor.execute(IDENTITY_SQL);rows=cursor.fetchall()
                need(len(rows)==1 and len(rows[0])==9)
                row=rows[0]
                need(type(row[0]) is str and row[0].isdigit() and type(row[1]) is int and row[1]>0
                     and row[2]==self.profile.dbname and digest(list(row[:3]))==self.profile.source_identity
                     and tuple(row[3:])==(self.profile.user,self.profile.user,'on','repeatable read','off','on'),
                     'native-candidate-ca-identity')
            finally:cursor.execute('ROLLBACK')
        need(type(conn.info.transaction_status) is int and conn.info.transaction_status==0)
        conn.autocommit=False

    def connect(self,*args,**kwargs):
        self._owner_process()
        with self._lock:
            conn=None
            try:
                self._assert_live()
                params=self._parameters(args,kwargs)
                self._connections=[value for value in self._connections if not value.closed]
                need(len(self._connections)<64,'native-candidate-ca-connections')
                self._assert_live()
                conn=self._driver(**params)
                self._connections.append(conn)
                self._assert_live()
                self._validate_connection(conn,params)
                self._assert_live()
                return conn
            except Exception:
                self._failed=True
                if conn is not None:self._discard(conn)
                raise Refused('native-candidate-ca-connect') from None
            except BaseException:
                self._failed=True
                if conn is not None:self._discard(conn)
                raise KeyboardInterrupt from None

    @staticmethod
    def _discard(conn):
        failed=False
        try:
            if conn.closed:return True
        except BaseException:failed=True
        try:conn.rollback()
        except BaseException:failed=True
        try:conn.close()
        except BaseException:failed=True
        try:return not failed and bool(conn.closed)
        except BaseException:return False

    def marker(self):
        """Kernel observations, to be independently re-probed in this PID namespace."""
        self._owner_process()
        with self._lock:
            try:
                self._assert_live()
                info=os.fstat(self._sealed)
                return dict(schema=MARKER_SCHEMA,pid=self._pid,process_start_ticks=self._start,fd=self._sealed,
                    device=info.st_dev,inode=info.st_ino,size=info.st_size,seals=fcntl.fcntl(self._sealed,GET_SEALS),
                    ca_sha256=self.profile.ca_sha256,profile_sha256=self._profile_digest,
                    request_digest=self.profile.request_digest,context_digest=self.profile.context_digest)
            except Exception:
                self._failed=True
                raise Refused('native-candidate-ca-marker') from None

    def _release_fds(self):
        failed=False
        for fd,device,inode in reversed(self._fds):
            try:
                info=os.fstat(fd)
                if (info.st_dev,info.st_ino)==(device,inode):
                    try:os.close(fd)
                    except BaseException:failed=True
            except OSError as error:
                if error.errno!=9:failed=True
        self._fds=[]
        return not failed

    def __exit__(self,*exc):
        global _installed
        self._owner_process()  # before acquiring a possibly inherited RLock
        with self._lock:
            failure=self._failed
            try:self._assert_live()
            except BaseException:failure=True
            self._active=False
            all_closed=True
            for conn in self._connections:
                failure|=not self._discard(conn)
                try:all_closed &= bool(conn.closed)
                except BaseException:all_closed=False
            self._connections=[];self._auth=None
            failure|=not self._release_fds()
            if all_closed and self._fork_state is not None:self._fork_state['armed']=False
            if _installed is self:_installed=None
            if failure:raise Refused('native-candidate-ca-close') from None
        return False


def observe_candidate_ca(marker, *, expected_pid, expected_profile_sha256, expected_ca_sha256):
    """Observe a live kernel FD; marker booleans never grant CA/app admission.

    Caller must identify its own candidate PID and PID namespace independently.
    This checks current FD bytes/seals, not guard code or the application's
    lifetime/process model. Docker ownership/entrypoint verification stays external.
    """
    fd=None
    try:
        keys={'schema','pid','process_start_ticks','fd','device','inode','size','seals','ca_sha256',
              'profile_sha256','request_digest','context_digest'}
        need(type(marker) is dict and set(marker)==keys and marker['schema']==MARKER_SCHEMA
             and type(expected_pid) is int and expected_pid>0 and marker['pid']==expected_pid
             and all(type(marker[key]) is int and marker[key]>=0 for key in
                     ('pid','process_start_ticks','fd','device','inode','size','seals'))
             and all(hex64(marker[key]) for key in ('ca_sha256','profile_sha256','request_digest','context_digest'))
             and hex64(expected_profile_sha256) and marker['profile_sha256']==expected_profile_sha256
             and hex64(expected_ca_sha256) and marker['ca_sha256']==expected_ca_sha256)
        need(_start_ticks(expected_pid)==marker['process_start_ticks'])
        fd=os.open(f'/proc/{expected_pid}/fd/{marker["fd"]}',os.O_RDONLY|os.O_CLOEXEC|os.O_NONBLOCK)
        info=os.fstat(fd);seals=fcntl.fcntl(fd,GET_SEALS)
        need(stat.S_ISREG(info.st_mode) and 0<info.st_size<=MAX_CA
             and (info.st_dev,info.st_ino,info.st_size,seals)==
                 (marker['device'],marker['inode'],marker['size'],marker['seals']) and seals&SEALS==SEALS
             and hashlib.sha256(os.pread(fd,MAX_CA+1,0)).hexdigest()==expected_ca_sha256
             and _pin(os.stat(f'/proc/{expected_pid}/fd/{marker["fd"]}'))==_pin(info)
             and _start_ticks(expected_pid)==marker['process_start_ticks'])
        return dict(pid=expected_pid,process_start_ticks=marker['process_start_ticks'],device=info.st_dev,
                    inode=info.st_ino,size=info.st_size,seals=seals,ca_sha256=expected_ca_sha256)
    except Exception:
        raise Refused('native-candidate-ca-observation') from None
    finally:
        if fd is not None:os.close(fd)
