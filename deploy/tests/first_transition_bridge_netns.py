"""Helper of test_first_transition_window_bindings: run INSIDE ``unshare -rn`` (synthetic namespace).

Builds a kernel bridge with two peer namespaces, listens on 8000 and 8001 in one of them and
connects from the other before, during and after BridgePortIngress blocks the bridge. Prints one
JSON line of reachability. Touches nothing outside its own user/network namespace.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import first_transition_window_bindings as wb  # noqa: E402

BRIDGE, SCOPE = 'br-0123456789ab', 'a' * 64
SERVER = '''
import socket, threading, time
for port in (8000, 8001):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("10.9.0.2", port)); s.listen()
    threading.Thread(target=lambda s=s: [s.accept() for _ in range(16)], daemon=True).start()
print("ready", flush=True); time.sleep(60)
'''
CLIENT = '''
import socket, sys
out = []
for port in (8000, 8001):
    s = socket.socket(); s.settimeout(1.5)
    try:
        s.connect(("10.9.0.2", port)); out.append(True)
    except OSError:
        out.append(False)
print(" ".join(map(str, out)))
'''


def sh(*argv):
    subprocess.run(argv, check=True, capture_output=True)


def main(nft):
    sh('ip', 'link', 'add', BRIDGE, 'type', 'bridge')
    sh('ip', 'link', 'set', BRIDGE, 'up')
    peers = {}
    for n, name in enumerate('ab', start=1):
        proc = subprocess.Popen(['unshare', '-n', 'sleep', '90'])
        time.sleep(0.2)
        peers[name] = proc
        sh('ip', 'link', 'add', 'v' + name, 'type', 'veth', 'peer', 'name', 'c' + name)
        sh('ip', 'link', 'set', 'c' + name, 'netns', f'/proc/{proc.pid}/ns/net')
        sh('ip', 'link', 'set', 'v' + name, 'master', BRIDGE, 'up')
        for argv in (('ip', 'link', 'set', 'lo', 'up'), ('ip', 'link', 'set', 'c' + name, 'up'),
                     ('ip', 'addr', 'add', f'10.9.0.{n}/24', 'dev', 'c' + name)):
            sh('nsenter', '-t', str(proc.pid), '-n', *argv)
    server = subprocess.Popen(['nsenter', '-t', str(peers['b'].pid), '-n', sys.executable, '-I', '-c', SERVER],
                              stdout=subprocess.PIPE, text=True)
    server.stdout.readline()

    def reach():
        out = subprocess.run(['nsenter', '-t', str(peers['a'].pid), '-n', sys.executable, '-I', '-c', CLIENT],
                             capture_output=True, text=True, check=True).stdout.split()
        return [v == 'True' for v in out]

    ingress = wb.BridgePortIngress(wb.BridgeConfig(nft_binary=nft, bridge=BRIDGE), scope=SCOPE)
    result = dict(before=reach())
    assert ingress.observe(SCOPE, timeout=10) == 'open'
    assert ingress.block(SCOPE, timeout=10) is True
    result['blocked'] = reach()
    assert ingress.open(SCOPE, timeout=10) is True
    result['reopened'] = reach()
    for proc in (server, *peers.values()):
        proc.kill()
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main(sys.argv[1])
