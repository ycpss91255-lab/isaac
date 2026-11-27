"""Resolve ``ISAAC_OUTPUT_MODE`` for Python callbacks (isaac#514).

``python`` is the default and the only supported value.
"""

import os
from collections.abc import Mapping

ENV_VAR = "ISAAC_OUTPUT_MODE"
MODES = ("python",)
DEFAULT_MODE = "python"


def resolve_output_mode(environ: Mapping[str, str] | None = None) -> str:
    """Return the active output mode.

    Args:
        environ: Mapping to read ``ISAAC_OUTPUT_MODE`` from. Defaults to
            ``os.environ``.

    Returns:
        ``"python"`` when the variable is unset or explicitly set to ``python``.

    Raises:
        ValueError: The variable is set to anything other than exactly
            ``python`` (wrong case, empty, ``both``, ...).
            The message names the offending value and the allowed set;
            there is no silent fallback.
    """
    env = os.environ if environ is None else environ
    if ENV_VAR not in env:
        return DEFAULT_MODE
    value = env[ENV_VAR]
    if value not in MODES:
        allowed = ", ".join(repr(m) for m in MODES)
        raise ValueError(f"invalid {ENV_VAR}={value!r}; allowed: {allowed}")
    return value
