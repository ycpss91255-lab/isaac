# Standalone scripts smoke

Integration smoke for `isaac_ws/src/script/*_standalone.py`. Each script
must reach its "ready marker" within a timeout when run through
`just docker exec -t stream /isaac-sim/python.sh <script>`. The runner
launches the script, polls its stdout for the marker, kills the run
once seen, and reports PASS / FAIL per case.

**[English](README.md)** | **[繁體中文](../../doc/readme/script-test/README.zh-TW.md)** | **[简体中文](../../doc/readme/script-test/README.zh-CN.md)** | **[日本語](../../doc/readme/script-test/README.ja.md)**

## Usage

```bash
# Full matrix (~6-10 min)
./isaac_ws/src/script/test/standalone_smoke.sh

# Single case (fast iteration during script edit)
./isaac_ws/src/script/test/standalone_smoke.sh --only ros2_test_pub
```

Pre-requisites:

- `just docker run -t stream -d` succeeds (smoke auto-runs it if container is down)

## Cases

| Script | Marker phrase | Timeout |
|--------|---------------|--------:|
| `ros2_test_pub_standalone.py` | `standalone publishing` | 150s |
| `ros2_test_sub_standalone.py` | `standalone subscribed to` | 150s |

The marker is grepped as a regex against captured stdout+stderr. Each
standalone script prints exactly one of these tagged lines once its
core setup completes (rclpy subscriber active, or first `[tick]`).

## Exit codes

| Code | Meaning |
|-----:|---------|
| 0 | All selected cases PASS |
| 1 | At least one FAIL |
| 2 | Unknown flag or pre-flight failure (docker dir missing / standalone container won't start) |

## Failure debugging

When a case FAILs the runner prints the last 20 lines of the script's
combined stdout+stderr to stderr. Common patterns:

- `ModuleNotFoundError: No module named 'rclpy'` — the `enable_extension("isaacsim.ros2.bridge")` call is missing or runs after `import rclpy`
- Hangs to timeout with no marker — kit booted but the script's main loop never reached the print; check for an exception above the marker line in the captured tail

## Why integration not unit

The standalone scripts boot kit + livestream + rclpy subscriber. Pure
Python unit tests cannot substitute for "does the script actually reach
the ROS subscriber loop with the bridge running". The marker
phrase is the contract — once the script can print it, all of
SimulationApp init, the ROS 2 bridge extension load, rclpy import,
and node creation have succeeded.

## Why this dir, not isaac_ws/src/docker/test/

`isaac_ws/src/docker/test/` belongs to the docker repo
(`ycpss91255-lab/isaac`) and tests the container image / wrappers,
not the scripts that run inside it. The standalone scripts live in
`isaac_ws/src/script/` (this repo, `ycpss91255-lab/isaac`); their smoke
lives alongside them so it travels with them.
