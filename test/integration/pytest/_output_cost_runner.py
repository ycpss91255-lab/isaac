"""Measure Python output cost in Kit, or render saved runs with host Python.

Use --case NAME --robot-usd JETBOT --out FILE to measure. Each repeat
warms up the same output hub with and without a consumer, then times
alternating blocks of uncapped updates at the case's simulation time step.
Use --render FILE [FILE ...] to pool repeats by case.
"""

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import fmean


def budget_ms(hz):
    """Return the step period in milliseconds, rounded to tenths."""
    return round(1000 / hz, 1)


CASES = {
    name: dict(kind=kind, resolution=size, hz=hz, budget_ms=budget_ms(hz))
    for name, kind, size, hz in (
        ("cam_640_30hz", "rgb", (640, 480), 30),
        ("cam_640_60hz", "rgb", (640, 480), 60),
        ("cam_1280", "rgb", (1280, 720), 30),
        ("depth_640", "depth", (640, 480), 30),
        ("jsimu", "jsimu", None, 200),
    )
}


def summarize(values):
    """Return the mean, endpoints and width of a range of measurements."""
    low, high = min(values), max(values)
    return dict(mean=fmean(values), min=low, max=high, spread=high - low)


def share_of_budget(extra_ms, budget):
    """Return extra step time as a percentage of the step budget."""
    return 100 * extra_ms / budget


def is_contaminated(load, spread, mean, load_threshold=2.0, spread_ratio=0.25):
    """Flag excessive one-minute host load or run-to-run variation."""
    return load > load_threshold or spread > spread_ratio * abs(mean)


def render_table(results):
    """Format the per-case summaries as a Markdown table."""
    lines = [
        "| case | budget ms | extra ms | share of budget | n | "
        "warm-up seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in results.items():
        budget = row["budget_ms"]
        share = share_of_budget(row["mean"], budget)
        flag = " (contaminated)" if row["contaminated"] else ""
        lines.append(
            f"| {name} | {budget:.1f} | {row['mean']:.4f} "
            f"({row['min']:.4f}..{row['max']:.4f}){flag} | {share:.2f}% | "
            f"{row['n']} | {row['warmup_sec']} |"
        )
    return "\n".join(lines)


def build_parser():
    """Build the CLI shared by the Kit and host entry points."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--case", choices=(*CASES, "jsimu_200hz"))
    mode.add_argument("--render", nargs="+", type=Path, metavar="FILE")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup-sec", type=float, default=30.0,
                        help="Warm-up seconds per consumer state")
    parser.add_argument("--steps", type=int, default=600,
                        help="Total timed steps per consumer state")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--robot-usd", help="Path to the official Jetbot USD")
    parser.add_argument("--repo-root", type=Path,
                        default=Path(__file__).resolve().parents[3])
    return parser


def _render(paths):
    grouped = defaultdict(list)
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        grouped[data["case"]].extend(data["runs"])

    results = {}
    loads = []
    for name, runs in sorted(grouped.items()):
        stats = summarize([run["extra_ms"] for run in runs])
        load = max(run["loadavg"][0] for run in runs)
        warmups = sorted({run["warmup_sec"] for run in runs})
        results[name] = dict(
            **stats, n=len(runs), budget_ms=CASES[name]["budget_ms"],
            warmup_sec=", ".join(map(str, warmups)),
            contaminated=is_contaminated(load, stats["spread"], stats["mean"]),
        )
        loads.append(f"{name} {load:.2f}")
    print(render_table(results))
    print("\nPeak one-minute host load by case: " + ", ".join(loads))


def _discard_frame(frame):
    pass


def _warm_up(app, out, seconds):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        app.update()
        out.step(time.monotonic())


def _measure_phase(app, out, steps):
    """Return wall-clock milliseconds per step for one block."""
    start = time.perf_counter()
    for _ in range(steps):
        app.update()
        out.step(time.monotonic())
    return (time.perf_counter() - start) * 1000 / steps


def _main():
    parser = build_parser()
    args = parser.parse_args()
    if args.render:
        _render(args.render)
        return
    if not args.out or not args.robot_usd:
        parser.error("--case requires --out and --robot-usd")
    if args.steps < 1 or args.repeats < 1:
        parser.error("--steps and --repeats must be positive")
    if not math.isfinite(args.warmup_sec) or args.warmup_sec < 0:
        parser.error("--warmup-sec must be finite and nonnegative")

    from _output_hub_runner import _build_stage, _CAMERA, _CHASSIS, _IMU

    name = "jsimu" if args.case == "jsimu_200hz" else args.case
    case = CASES[name]
    os.environ["ISAAC_OUTPUT_MODE"] = "python"
    os.environ["ISAAC_LIVESTREAM"] = "0"
    sys.path.insert(0, str(args.repo_root.resolve() / "framework"))
    sys.argv = ["runner", "--enable", "isaacsim.core.nodes",
                "--enable", "isaacsim.sensors.experimental.physics",
                "--/app/runLoops/main/rateLimitEnabled=false"]
    app = None
    try:
        from isaaclab.app import AppLauncher
        from isaac_devkit.output import (
            CameraOutput, ImuOutput, JointOutput, setup_output,
        )

        app = AppLauncher({"headless": True, "enable_cameras": True}).app
        import omni.timeline
        import omni.usd
        from isaacsim.sensors.experimental.physics import IMU
        from pxr import PhysxSchema

        timeline = omni.timeline.get_timeline_interface()
        runs = []
        for _ in range(args.repeats):
            _build_stage(args.robot_usd)
            stage = omni.usd.get_context().get_stage()
            stage.SetTimeCodesPerSecond(case["hz"])
            scene = stage.GetPrimAtPath("/World/PhysicsScene")
            physics = PhysxSchema.PhysxSceneAPI.Apply(scene)
            physics.CreateTimeStepsPerSecondAttr(case["hz"])
            for _ in range(10):
                app.update()
            IMU.create(_IMU)

            kind = case["kind"]
            if kind == "jsimu":
                out = setup_output(joint=JointOutput(_CHASSIS),
                                   imu=ImuOutput("imu", _IMU))
                kinds = ["joint_state", "imu"]
            else:
                camera = CameraOutput(kind, _CAMERA, *case["resolution"],
                                      depth=kind == "depth")
                out = setup_output(cameras=[camera])
                kinds = [kind]
            timeline.play()
            _warm_up(app, out, args.warmup_sec)
            out.register(_discard_frame, kinds=kinds)
            _warm_up(app, out, args.warmup_sec)
            out.unregister(_discard_frame)

            baseline_blocks = []
            with_output_blocks = []
            blocks = min(5, args.steps)
            block_steps, remainder = divmod(args.steps, blocks)
            for i in range(blocks):
                steps = block_steps + (i < remainder)
                baseline_blocks.append(_measure_phase(app, out, steps))
                out.register(_discard_frame, kinds=kinds)
                with_output_blocks.append(_measure_phase(app, out, steps))
                out.unregister(_discard_frame)
            loadavg = os.getloadavg()

            # Empty sensor readings skip delivery and can mimic a cheap read.
            received = set()
            out.register(lambda frame: received.add(frame.kind), kinds=kinds)
            app.update()
            out.step(time.monotonic())
            missing = set(kinds) - received
            if missing:
                raise RuntimeError(f"missing output kinds: {sorted(missing)}")
            del out
            timeline.stop()
            app.update()

            baseline = fmean(baseline_blocks)
            with_output = fmean(with_output_blocks)
            extra = with_output - baseline
            runs.append(dict(baseline_ms=baseline, with_output_ms=with_output,
                             baseline_blocks_ms=baseline_blocks,
                             with_output_blocks_ms=with_output_blocks,
                             extra_ms=extra, steps=args.steps,
                             warmup_sec=args.warmup_sec, loadavg=loadavg))
            print(f"[COST CASE] {name} run={len(runs)} extra_ms={extra:.4f}",
                  flush=True)
        args.out.write_text(json.dumps({"case": name, "runs": runs}, indent=2)
                            + "\n", encoding="utf-8")
        print("[COST EXIT CLEAN]", flush=True)
    except Exception as exc:
        print(f"[COST RAISED] {type(exc).__name__}: {exc}", flush=True)
        raise
    finally:
        if app is not None:
            app.close()


if __name__ == "__main__":
    _main()
