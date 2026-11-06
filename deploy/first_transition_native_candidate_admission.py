"""Single-client, pre-app Unix admission barrier; no Docker/code authority.

Trusted composition verifies the container, entrypoint, mounts and PID namespace
before running the client. SO_PEERCRED and /proc observations below prove only
the connected main process and its currently live sealed CA. No credentials,
TCP, retries, worker threads, app imports or operational/A8 receipt are involved.
"""
import hashlib
from dataclasses import asdict,is_dataclass
import importlib.util
import json
import math
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import time

SOCKET_PATH='/tmp/igreja12-candidate-admission.sock'
HELLO='igreja12.candidate-admission-marker/1'
ACK='igreja12.candidate-admission-ack/1'
DONE='igreja12.candidate-admission-complete/1'
LIMIT=8192


class Refused(ValueError):
    """Fixed public refusal; no native/driver/profile exception text."""


def _need(value):
    if not value:raise Refused('native-candidate-admission-refused')


def profile_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def _deadline(timeout):
    _need(type(timeout) in (int,float) and math.isfinite(timeout) and 0<timeout<=30)
    return time.monotonic()+timeout


def _budget(sock,deadline):
    left=deadline-time.monotonic()
    _need(left>0)
    sock.settimeout(left)


def _peer(sock):
    return struct.unpack('3i',sock.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,struct.calcsize('3i')))


def _send(sock,value,deadline):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    _need(0<len(raw)<=LIMIT)
    _budget(sock,deadline)
    sock.sendall(struct.pack('!I',len(raw))+raw)
    _budget(sock,deadline)


def _exact(sock,length,deadline):
    value=bytearray()
    while len(value)<length:
        _budget(sock,deadline)
        chunk=sock.recv(length-len(value));_need(bool(chunk));value.extend(chunk)
    _budget(sock,deadline)
    return bytes(value)


def _pairs(items):
    value={}
    for key,item in items:
        _need(key not in value);value[key]=item
    return value


def _receive(sock,deadline):
    length=struct.unpack('!I',_exact(sock,4,deadline))[0]
    _need(0<length<=LIMIT)
    value=json.loads(_exact(sock,length,deadline),object_pairs_hook=_pairs)
    _need(type(value) is dict)
    return value


def _eof(sock,deadline):
    _budget(sock,deadline)
    _need(sock.recv(1)==b'')
    _budget(sock,deadline)


def _path_pin():
    info=os.lstat(SOCKET_PATH)
    _need(stat.S_ISSOCK(info.st_mode) and info.st_uid==os.geteuid()
          and stat.S_IMODE(info.st_mode)==0o600 and info.st_nlink==1)
    return info.st_dev,info.st_ino


def _remove_owned(pin):
    try:info=os.lstat(SOCKET_PATH)
    except FileNotFoundError:return False
    _need((info.st_dev,info.st_ino)==pin and stat.S_ISSOCK(info.st_mode))
    os.unlink(SOCKET_PATH)
    return True


def serve_admission(custody, *, timeout=30, expected_client_uid=None):
    """One attempt, inside CA custody, before app import. No preexisting adoption."""
    listener=connection=None;pin=None
    try:
        deadline=_deadline(timeout)
        uid=os.geteuid() if expected_client_uid is None else expected_client_uid
        _need(type(uid) is int and uid>=0)
        # A fresh kernel bind refuses every existing filesystem entry.
        marker=custody.marker()
        _need(marker['pid']==os.getpid())
        listener=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        listener.bind(SOCKET_PATH)
        info=os.lstat(SOCKET_PATH)
        pin=(info.st_dev,info.st_ino)
        _need(stat.S_ISSOCK(info.st_mode) and info.st_uid==os.geteuid())
        os.chmod(SOCKET_PATH,0o600,follow_symlinks=False)
        _need(_path_pin()==pin)
        listener.listen(1);_budget(listener,deadline)
        connection,_=listener.accept()
        listener.close();listener=None  # never accept or emit to a second client
        _need(_peer(connection)[1]==uid and _path_pin()==pin)
        marker_sha=profile_digest(marker)
        _send(connection,dict(schema=HELLO,marker=marker),deadline)
        observed=_receive(connection,deadline)
        expected=dict(schema=ACK,request_digest=marker['request_digest'],context_digest=marker['context_digest'],
            profile_sha256=marker['profile_sha256'],marker_sha256=marker_sha)
        _need(observed==expected)
        _eof(connection,deadline)
        _need(_peer(connection)[1]==uid and _path_pin()==pin and custody.marker()==marker)
        _need(_remove_owned(pin));pin=None
        _need(custody.marker()==marker)
        _send(connection,dict(schema=DONE,marker_sha256=marker_sha),deadline)
        return expected
    except Exception:
        raise Refused('native-candidate-admission-refused') from None
    except BaseException:
        raise KeyboardInterrupt from None
    finally:
        if connection is not None:connection.close()
        if listener is not None:listener.close()
        if pin is not None:
            try:_remove_owned(pin)
            except Exception:pass  # never unlink a replacement/foreign inode


def _ca_module():
    # Explicit sibling loading works under python -I; source/mount pins remain
    # the caller's independently verified responsibility.
    path=Path(__file__).resolve().with_name('first_transition_native_candidate_ca.py')
    spec=importlib.util.spec_from_file_location('igreja12_ca_admission_observer',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def load_profile(path):
    """Bounded public profile, never credentials; its expected SHA stays external."""
    fds=[]
    try:
        path=Path(path)
        _need(path.is_absolute() and '..' not in path.parts)
        parent=os.open('/',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC);fds.append(parent)
        for part in path.parts[1:-1]:
            parent=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            fds.append(parent)
        fd=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=parent);fds.append(fd)
        info=os.fstat(fd)
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and 0<info.st_size<=16384 and not info.st_mode&0o022)
        module=_ca_module()
        raw=os.pread(fd,16385,0)
        _need(len(raw)==info.st_size and module._pin(os.fstat(fd))==module._pin(info)
              and module._pin(os.stat(path.name,dir_fd=parent,follow_symlinks=False))==module._pin(info))
        return module.CandidateCAProfile.from_dict(json.loads(raw,object_pairs_hook=_pairs))
    except Exception:
        raise Refused('native-candidate-admission-profile') from None
    finally:
        for fd in reversed(fds):os.close(fd)


def acknowledge_candidate(profile,expected_profile_sha256, *, expected_uid,expected_main_pid=1,timeout=10):
    """Verify peer PID/UID and actual CA FD before ACK. Exactly one Unix connect."""
    client=None
    try:
        deadline=_deadline(timeout)
        _need(type(expected_uid) is int and expected_uid>=0
              and type(expected_main_pid) is int and expected_main_pid>0)
        module=_ca_module()
        if is_dataclass(profile):profile=asdict(profile)
        reviewed=module.CandidateCAProfile.from_dict(profile)
        _need(module.hex64(expected_profile_sha256) and profile_digest(profile)==expected_profile_sha256)
        client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);_budget(client,deadline)
        client.connect(SOCKET_PATH)
        # Kernel peer credentials are checked BEFORE trusting JSON PID/marker.
        peer=_peer(client)
        _need(peer[0]==expected_main_pid and peer[1]==expected_uid)
        hello=_receive(client,deadline)
        _need(set(hello)=={'schema','marker'} and hello['schema']==HELLO and type(hello['marker']) is dict)
        marker=hello['marker']
        _need(marker.get('request_digest')==reviewed.request_digest
              and marker.get('context_digest')==reviewed.context_digest
              and marker.get('profile_sha256')==expected_profile_sha256)
        observation=module.observe_candidate_ca(marker,expected_pid=expected_main_pid,
            expected_profile_sha256=expected_profile_sha256,expected_ca_sha256=reviewed.ca_sha256)
        _need(_peer(client)==peer)
        marker_sha=profile_digest(marker)
        _send(client,dict(schema=ACK,request_digest=reviewed.request_digest,context_digest=reviewed.context_digest,
            profile_sha256=expected_profile_sha256,marker_sha256=marker_sha),deadline)
        client.shutdown(socket.SHUT_WR)
        _need(_receive(client,deadline)==dict(schema=DONE,marker_sha256=marker_sha))
        _eof(client,deadline)
        return dict(schema='igreja12.native-candidate-admission/1',pid=expected_main_pid,peer_uid=peer[1],
            request_digest=reviewed.request_digest,context_digest=reviewed.context_digest,
            profile_sha256=expected_profile_sha256,ca_sha256=observation['ca_sha256'],
            process_start_ticks=observation['process_start_ticks'],fd=marker['fd'],
            device=observation['device'],inode=observation['inode'],size=observation['size'],seals=observation['seals'])
    except Exception:
        raise Refused('native-candidate-admission-refused') from None
    except BaseException:
        raise KeyboardInterrupt from None
    finally:
        if client is not None:client.close()
