"""Shared pure helpers for the standalone driver scripts in ``src/script/``.

Import-safe on a host without Isaac Sim (no ``omni`` / ``pxr`` /
``isaacsim`` / ``rclpy`` import here), so the hosted unit tests can pin it
(``test/unit/pytest/test_standalone_scripts.py``).

Why these exist:

- ``run_and_exit``: ``SimulationApp.close()`` ends the process with
  ``_exit(0)``, and an exception raised at module top (for example a
  removed extension module) never reaches any handler. Both made a failed
  script exit 0. Scripts now build their ``SimulationApp`` inside ``main()``
  and hand ``main`` to ``run_and_exit``, which prints the traceback and
  exits 1 on any exception, skipping Kit's own teardown.
- ``kit_config``: the ``headless`` / ``stream`` Docker stages set
  ``ISAAC_LIVESTREAM`` (0 / 2); scripts follow it instead of hard-coding
  ``livestream: 2``.
- ``PeriodicTimer``: Kit's update rate depends on the stage, the renderer
  and the host load (measured 200-450 updates/s headless), so "every 60
  updates" is not "every second".
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Any, Callable, Dict, Optional


def kit_config(livestream_env: Optional[str]) -> Dict[str, Any]:
    """Map an ``ISAAC_LIVESTREAM`` value to ``SimulationApp`` kwargs.

    Args:
        livestream_env: ``None`` / ``""`` / ``"0"`` for headless, ``"2"``
            for WebRTC streaming.

    Returns:
        The config dict for ``SimulationApp``.

    Raises:
        ValueError: for any other value, so a typo fails at boot.
    """
    if livestream_env in (None, "", "0"):
        return {"headless": True}
    if livestream_env == "2":
        return {
            "headless": False,
            "livestream": 2,
            "renderer": "RaytracedLighting",
        }
    raise ValueError(
        f"unsupported ISAAC_LIVESTREAM value {livestream_env!r}; "
        "expected '', '0' or '2'"
    )


class PeriodicTimer:
    """Wall-clock gate: ``due()`` is True at most once per ``period_s``.

    After a stall longer than one period it fires once and re-arms from
    the current time instead of firing a burst to catch up.
    """

    def __init__(
        self, period_s: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if period_s <= 0:
            raise ValueError("period_s must be > 0")
        self._period = period_s
        self._clock = clock
        self._next = clock() + period_s

    def due(self) -> bool:
        """Return True when a period has elapsed since the last fire."""
        now = self._clock()
        if now < self._next:
            return False
        self._next += self._period
        if self._next <= now:
            self._next = now + self._period
        return True


def run_and_exit(
    main: Callable[[], Optional[int]],
    exit_fn: Callable[[int], Any] = os._exit,
) -> None:
    """Run ``main`` and end the process with its exit code.

    Args:
        main: returns ``None`` / ``0`` on success or a non-zero code.
        exit_fn: process exit; ``os._exit`` by default, because Kit's own
            ``SimulationApp.close()`` would turn every outcome into 0 and
            can hang or abort in a cold container (isaac#248).
    """
    try:
        rc = main()
        code = 0 if rc is None else int(rc)
    except SystemExit as exc:
        if isinstance(exc.code, int):
            code = exc.code
        else:
            code = 0 if exc.code is None else 1
    except BaseException:  # noqa: BLE001 - every failure must be non-zero
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    exit_fn(code)
