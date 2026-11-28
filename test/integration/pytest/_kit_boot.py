"""Measure the SimulationApp constructor, including when called by IsaacDriver."""

import time
from contextlib import contextmanager
from unittest.mock import patch


@contextmanager
def time_kit_boot():
    from isaacsim import SimulationApp

    init = SimulationApp.__init__

    def timed_init(self, *args, **kwargs):
        start = time.monotonic()
        init(self, *args, **kwargs)
        print(f"[KIT-TIMING] boot_sec={time.monotonic() - start:.6f}", flush=True)

    with patch.object(SimulationApp, "__init__", timed_init):
        yield SimulationApp
