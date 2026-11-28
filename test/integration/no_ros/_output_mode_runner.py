"""Measure headless Jetbot RGB output in Python mode (isaac#390)."""

import argparse
import math
import os
import sys
import time
from pathlib import Path

_PYTEST_DIR = Path(__file__).resolve().parents[1] / "pytest"
sys.path.insert(0, str(_PYTEST_DIR))

from _output_hub_runner import _build_stage, _CAMERA, _HEIGHT, _WIDTH  # noqa: E402

_WARMUP = 30
_STEPS = 300


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--robot-usd", required=True)
    args = parser.parse_args()

    os.environ["ISAAC_LIVESTREAM"] = "0"
    os.environ["ISAAC_OUTPUT_MODE"] = "python"
    sys.path.insert(0, str(Path(args.repo_root).resolve() / "framework"))
    from isaac_devkit.output import CameraOutput, setup_output
    from isaacsim import SimulationApp

    app = SimulationApp({
        "headless": True,
        "extra_args": ["--enable", "isaacsim.core.nodes"],
    })
    import omni.graph.core as og
    import omni.timeline

    _build_stage(args.robot_usd)
    out = setup_output(cameras=[CameraOutput("rgb", _CAMERA, _WIDTH, _HEIGHT)])
    rgb_count = 0

    def count_rgb(_frame):
        nonlocal rgb_count
        rgb_count += 1

    out.register(count_rgb, kinds=["rgb"])
    omni.timeline.get_timeline_interface().play()
    for _ in range(_WARMUP):
        app.update()
        out.step(time.monotonic())

    durations_ms = []
    for _ in range(_STEPS):
        start = time.perf_counter()
        app.update()
        out.step(time.monotonic())
        durations_ms.append((time.perf_counter() - start) * 1000)

    mean_ms = sum(durations_ms) / _STEPS
    p95_ms = sorted(durations_ms)[math.ceil(0.95 * _STEPS) - 1]
    ros2_nodes = sum(
        node.get_type_name().startswith("isaacsim.ros2.bridge.")
        for graph in (og.get_all_graphs_and_subgraphs() or ())
        for node in graph.get_nodes()
    )
    print(f"[MODE RGB] count={rgb_count}", flush=True)
    print(f"[MODE ROS2_NODES] count={ros2_nodes}", flush=True)
    print(f"[MODE STEP] warmup={_WARMUP} steps={_STEPS} "
          f"mean_ms={mean_ms} p95_ms={p95_ms}", flush=True)
    print("[MODE EXIT CLEAN]", flush=True)
    app.close()


if __name__ == "__main__":
    try:
        _main()
    except Exception as exc:
        print(f"[MODE RAISED] {type(exc).__name__}: {exc}", flush=True)
        raise
