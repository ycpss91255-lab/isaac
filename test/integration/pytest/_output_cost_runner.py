"""Measure Python output cost in Kit, or render saved runs with host Python.

Use --case NAME --robot-usd JETBOT --out FILE to measure. After warm-up,
each repeat times paired blocks of uncapped updates at the case's simulation
time step. Cost runs enable a consumer for the second block of each pair.
With --noise-floor, both blocks and their warm-ups run without a consumer.

Use --render FILE [FILE ...] to pool JSON runs by case and mode. Runs without
a mode default to cost. The noise floor is the mean absolute run difference
in milliseconds per step. Its min..max column shows the signed differences.
"""

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from functools import partial
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


def noise_floor_ms(runs):
    """Return the mean magnitude of the baseline-to-baseline differences."""
    return fmean(abs(run["diff_ms"]) for run in runs)


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
    parser.add_argument("--noise-floor", action="store_true",
                        help="Measure paired baseline blocks for --case")
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
    cost_runs = defaultdict(list)
    noise_runs = defaultdict(list)
    groups = {"cost": cost_runs, "noise_floor": noise_runs}
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for run in data["runs"]:
            groups[run.get("mode", "cost")][data["case"]].append(run)

    results = {}
    loads = []
    for name, runs in sorted(cost_runs.items()):
        stats = summarize([run["extra_ms"] for run in runs])
        load = max(run["loadavg"][0] for run in runs)
        warmups = sorted({run["warmup_sec"] for run in runs})
        results[name] = dict(
            **stats, n=len(runs), budget_ms=CASES[name]["budget_ms"],
            warmup_sec=", ".join(map(str, warmups)),
            contaminated=is_contaminated(load, stats["spread"], stats["mean"]),
        )
        loads.append(f"{name} {load:.2f}")
    if results:
        print(render_table(results))
        print("\nPeak one-minute host load by case: " + ", ".join(loads))
    if noise_runs:
        if results:
            print()
        print("Noise floor (baseline vs baseline)")
        print("| case | n | noise floor ms | min..max |")
        print("| --- | ---: | ---: | ---: |")
        for name, runs in sorted(noise_runs.items()):
            diffs = [run["diff_ms"] for run in runs]
            print(f"| {name} | {len(runs)} | {noise_floor_ms(runs):.4f} | "
                  f"{min(diffs):.4f}..{max(diffs):.4f} |")


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


def _measure_blocks(steps, measure, register, unregister, noise_floor):
    """Measure up to five paired blocks, using the same step count in each pair."""
    first = []
    second = []
    blocks = min(5, steps)
    block_steps, remainder = divmod(steps, blocks)
    for i in range(blocks):
        count = block_steps + (i < remainder)
        first.append(measure(count))
        if noise_floor:
            second.append(measure(count))
        else:
            register()
            try:
                second.append(measure(count))
            finally:
                unregister()

    baseline = fmean(first)
    other = fmean(second)
    run = dict(baseline_ms=baseline, baseline_blocks_ms=first)
    if noise_floor:
        run.update(mode="noise_floor", second_baseline_ms=other,
                   second_baseline_blocks_ms=second, diff_ms=other - baseline)
    else:
        run.update(mode="cost", with_output_ms=other,
                   with_output_blocks_ms=second, extra_ms=other - baseline)
    return run


def _main():
    parser = build_parser()
    args = parser.parse_args()
    if args.render:
        if args.noise_floor:
            parser.error("--noise-floor requires --case")
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
            register = partial(out.register, _discard_frame, kinds=kinds)
            unregister = partial(out.unregister, _discard_frame)
            _warm_up(app, out, args.warmup_sec)
            if not args.noise_floor:
                register()
            _warm_up(app, out, args.warmup_sec)
            if not args.noise_floor:
                unregister()

            run = _measure_blocks(args.steps, partial(_measure_phase, app, out),
                                  register, unregister, args.noise_floor)
            run.update(steps=args.steps, warmup_sec=args.warmup_sec,
                       loadavg=os.getloadavg())

            # Empty sensor readings skip delivery and can mimic a cheap read.
            if not args.noise_floor:
                received = set()
                out.register(lambda frame: received.add(frame.kind), kinds=kinds)
                app.update()
                out.step(time.monotonic())
                missing = set(kinds) - received
                if missing:
                    raise RuntimeError(f"missing output kinds: {sorted(missing)}")
            del register, unregister, out
            timeline.stop()
            app.update()

            runs.append(run)
            metric = "diff_ms" if args.noise_floor else "extra_ms"
            print(f"[COST CASE] {name} run={len(runs)} "
                  f"{metric}={run[metric]:.4f}", flush=True)
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
