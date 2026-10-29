"""Command encoding for a simulated host driver; no process or network executor.

The mandatory driver supplies sanitized metadata, not raw Docker inspect/env.
Ingress remains a semantic operation: no guessed Nginx/Evolution command.
This adapter cannot certify a real host and provides no start/deploy operation.
"""
from __future__ import annotations

from copy import deepcopy
import re

from first_transition_adapter import ROLES
from initial_transition_ops import Refused, require


class SimulatedHostTransport:
    def __init__(self, driver):
        require(getattr(driver, 'mode', None) == 'local-simulation', 'transport-simulation-required')
        self.driver = driver
        self.identities = None

    def _request(self, argv, timeout):
        require(getattr(self.driver, 'mode', None) == 'local-simulation', 'transport-simulation-required')
        try:
            return self.driver.request(tuple(argv), timeout=timeout)
        except TimeoutError:
            raise TimeoutError('simulated-transport-timeout') from None
        except Exception:
            raise Refused('simulated-transport-failed') from None

    def snapshot(self):
        data = self._request(('snapshot-metadata',), 5)
        require(isinstance(data, dict) and data.get('mode') == 'local-simulation', 'transport-snapshot')
        services = data.get('services')
        require(isinstance(services, dict) and set(services) == set(ROLES), 'transport-scope')
        identities = {role: state.get('id') if isinstance(state, dict) else None
                      for role, state in services.items()}
        require(all(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)
                    for value in identities.values()) and len(set(identities.values())) == 4,
                'transport-identities')
        if self.identities is None:
            self.identities = identities
        require(identities == self.identities, 'transport-identity-changed')
        # Full shape/topology/gates validation remains in LocalHostContract.
        return deepcopy(data)

    def _target(self, identifier):
        require(self.identities is not None and identifier in self.identities.values(), 'transport-target')
        self.snapshot()  # Detect replacement immediately before a simulated effect.

    def block_ingress(self):
        require(self.identities is not None, 'transport-unobserved')
        self.snapshot()
        require(self._request(('block-ingress',), 5) is True, 'transport-ingress-receipt')

    def disable_restart(self, identifier):
        self._target(identifier)
        require(self._request(('docker', 'update', '--restart=no', identifier), 5) is True,
                'transport-restart-receipt')

    def signal_term(self, identifier):
        self._target(identifier)
        require(self._request(('docker', 'kill', '--signal=TERM', identifier), 5) is True,
                'transport-signal-receipt')

    def wait_stopped(self, identifier, timeout):
        require(type(timeout) is int and 0 < timeout <= 30, 'transport-wait-bound')
        self._target(identifier)
        status = self._request(('docker', 'wait', identifier), timeout)
        require(type(status) is int and status == 0, 'transport-exit-not-clean')
