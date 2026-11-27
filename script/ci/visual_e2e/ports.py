"""Select distinct host-network ports for one visual E2E run."""

import errno
import os
import random
import socket


def port_available(port):
    try:
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            with socket.socket(type=kind) as sock:
                sock.bind(("0.0.0.0", port))
    except OSError as error:
        if error.errno == errno.EADDRINUSE:
            return False
        raise
    return True


def select_ports():
    names = ("ISAAC_SIGNAL_PORT", "ISAAC_MEDIA_PORT", "ISAAC_API_PORT", "SERVE_PORT")
    selected = {}
    for name in names:
        if os.environ.get(name):
            port = int(os.environ[name])
            if not 0 < port <= 65535 or port in selected.values() or not port_available(port):
                raise ValueError(f"{name}={port} is unavailable")
            selected[name] = port

    candidates = list(range(16000, 32000))
    seed = f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    random.Random(seed).shuffle(candidates)
    free = (p for p in candidates if p not in selected.values() and port_available(p))
    for name in names:
        if name not in selected:
            port = next(free, None)
            if port is None:
                raise ValueError(f"no available port for {name}")
            selected[name] = port
    return [selected[name] for name in names]


if __name__ == "__main__":
    try:
        print(*select_ports())
    except (ValueError, OSError) as error:
        raise SystemExit(f"port preflight failed: {error}")
