"""Fictional edge transports; the lifecycle/guards/observers/runners stay real."""

import os
import tempfile

from first_transition_c2_containment import BroadcastRunner
from first_transition_c2_native import NativeReadRunner, NativeSnapshotProducer
from first_transition_c2_systemctl import SystemctlReadRunner
from initial_transition_ops import Refused
from test_first_transition_c2_guards import GuardWorld
from test_first_transition_c2_native import World as DockerWorld
from test_first_transition_c2_systemctl import World as SystemctlWorld


class DockerChild:
    def __init__(self, root, body, rc=0):
        self.stdout = tempfile.TemporaryFile(dir=root)
        self.stdout.write(body)
        self.stdout.seek(0)
        self.rc, self.alive, self.kills = rc, True, 0
        self.waits = []
        self.wait_error = None

    def poll(self):
        return None if self.alive else self.rc

    def kill(self):
        self.kills += 1
        self.alive = False

    def wait(self, *, timeout):
        self.waits.append(timeout)
        if self.wait_error is not None:
            error, self.wait_error = self.wait_error, None
            raise error
        self.alive = False
        return self.rc


class DockerCLI:
    def __init__(self, root, world):
        self.root, self.world = root, world
        self.calls, self.children, self.effects = [], [], []
        self.before = self.after = self.spawn_error = None

    def spawn(self, command, **options):
        # This factory never launches a process. NativeReadRunner/BroadcastRunner
        # still enforce their own CLI grammar, framing, output cap and cleanup.
        assert command[:5] == [
            "/fixture/docker",
            "--config",
            "/fixture/docker-config",
            "--host",
            "unix:///fixture/docker.sock",
        ]
        self.calls.append((list(command), options))
        argv = ("docker", *command[5:])
        if self.before is not None:
            self.before(argv)
        if self.spawn_error is not None:
            raise self.spawn_error
        target = self.world.target
        if argv == ("docker", "update", "--restart=no", target):
            self.effects.append("restart-no")
            self.world.row[4]["RestartPolicy"] = {"Name": "no", "MaximumRetryCount": 0}
            rc, body = 0, (target + "\n").encode()
        elif argv == ("docker", "kill", "--signal=TERM", target):
            self.effects.append("TERM")
            self.world.row[5].update(Status="exited", Running=False, ExitCode=0, Pid=0)
            self.world.row[7] = {}
            rc, body = 0, (target + "\n").encode()
        elif (
            argv[1:2] == ("info",)
            or argv[1:2] == ("inspect",)
            or argv[1:3] == ("network", "inspect")
        ):
            rc, body = self.world.run(argv)
        else:
            raise Refused("fixture-command-refused")
        child = DockerChild(self.root, body, rc)
        self.children.append(child)
        if self.after is not None:
            self.after(argv, child)
        return child


class SessionFixture:
    def __init__(self, tmp_path):
        self.world = DockerWorld()
        w = self.world
        self.guards = GuardWorld(
            tmp_path, scope=w.manifest.digest, target=w.target, nonce="fixture_nonce"
        )
        g = self.guards
        self.clock = g.clock
        self.scheduler = SystemctlWorld(tmp_path)
        self.scheduler.stdout = g.run_result[1]
        self.schedule_runner = SystemctlReadRunner(
            g.schedule.units,
            deadline=g.admission.deadline,
            clock=g.clock,
            popen=self.scheduler.spawn,
            enabled=True,
            synthetic_only=True,
        )
        g.schedule.run = self.schedule_runner
        g.guard = g.make_guard()
        self.docker = DockerCLI(tmp_path, w)
        self.spawn = self.docker.spawn
        self.read_runner = NativeReadRunner(
            manifest=w.manifest,
            admission=w.admission,
            enabled=True,
            docker_binary="/fixture/docker",
            endpoint="unix:///fixture/docker.sock",
            config_dir="/fixture/docker-config",
            popen=self.spawn,
        )
        self.observer = NativeSnapshotProducer(
            w.manifest,
            w.admission,
            runner=self.read_runner,
            deadline=g.admission.deadline,
            enabled=True,
            clock=g.clock,
        )
        self.runner = BroadcastRunner(
            manifest=w.manifest,
            docker_binary="/fixture/docker",
            endpoint="unix:///fixture/docker.sock",
            config_dir="/fixture/docker-config",
            popen=self.spawn,
        )

    def sleep(self, delay):
        self.guards.now += delay

    def session(self, **overrides):
        from first_transition_c2_lifecycle import ContainmentSession

        options = dict(
            observer=self.observer,
            guard=self.guards.guard,
            runner=self.runner,
            clock=self.clock,
            sleep=self.sleep,
            owner_uid=os.geteuid(),
            enabled=True,
            synthetic_only=True,
        )
        options.update(overrides)
        return ContainmentSession(self.world.manifest, **options)

    @property
    def journal(self):
        return self.guards.root / ("broadcast-" + self.world.target)

    @property
    def effects(self):
        return self.docker.effects
