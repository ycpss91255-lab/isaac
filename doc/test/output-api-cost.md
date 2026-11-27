# Python output API cost per step (isaac#385)

This benchmark re-measures the per-step cost of delivering data through `OutputHub`, the Python output API prototyped in isaac#365. All five cases ran on one shared single-GPU host with one scene, the official Jetbot. The measurements cover producer-side reads and delivery. Subscriber-side processing was outside the timing scope.

## Method

Each run calls `setup_output` once and uses the same hub for both phases. The baseline steps the hub with no consumer. The with-output phase registers a no-op consumer so the hub reads and delivers the data, including GPU-to-CPU readback for camera frames. The consumer discards each frame.

The runner warms up for 30 seconds in each consumer state, then times five interleaved block pairs. Each pair has 120 baseline steps followed by 120 with-output steps, for 600 timed steps per phase. Each step includes both `app.update()` and `out.step()` with the frame rate uncapped. For each run, extra ms is the with-output mean minus the baseline mean. The table gives the mean extra ms across three runs per case, the minimum and maximum in parentheses, and the mean as a percentage of the case's step budget.

## Results

| case | budget ms | extra ms | share of budget | n | warm-up seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| cam_1280 | 33.3 | 5.1635 (4.5492..5.8024) (contaminated) | 15.51% | 3 | 30.0 |
| cam_640_30hz | 33.3 | 1.1987 (-0.9742..3.3077) (contaminated) | 3.60% | 3 | 30.0 |
| cam_640_60hz | 16.7 | 1.6699 (1.3930..1.9854) (contaminated) | 10.00% | 3 | 30.0 |
| depth_640 | 33.3 | 0.8801 (0.5888..1.2361) (contaminated) | 2.64% | 3 | 30.0 |
| jsimu | 5.0 | 0.1954 (-0.1598..0.6971) (contaminated) | 3.91% | 3 | 30.0 |

The prototype measured `cam_640` at +0.448 ms (1.3% of budget), `cam_1280` at +0.630 ms (1.9%), `depth_640` at +0.804 ms (2.4%), and `jsimu` at +0.040 ms (0.8%), with a noise floor of 0.010–0.011 ms. The largest difference is at 1280 × 720, where the shared-host mean reached 5.1635 ms. Depth stayed closest to its prototype figure at 0.8801 ms. [Prototype measurements (isaac#365)](https://github.com/ycpss91255-lab/isaac/issues/365)

## Noise floor and contamination

Every row is flagged contaminated. Other Isaac containers ran concurrently, and no isolated idle window became available within the waiting limit. The one-minute host load average was between 10 and 69 at run end (peaking near 99 while waiting for a quiet window) during measurement. The per-run table shows the readings at run end, which ranged from 10.27 to 68.96.

No dedicated baseline-vs-baseline run was performed. The observed run-to-run spread in extra ms serves as the noise floor for each case. In the first runs of `cam_640_30hz` and `jsimu`, the with-output phase finished faster than the baseline. Those negative differences show that contention noise can exceed the API cost. Treat these means as rough upper-bound indications only. The prototype figures remain the reference pending a re-run on an idle host using the runner and steps below.

## Per-run measurements

Base and with-output are mean milliseconds per step. Times are rounded to three decimal places and one-minute load averages to two.

| case | run | base ms | with-output ms | extra ms | 1-min load at run end |
| --- | ---: | ---: | ---: | ---: | ---: |
| cam_1280 | 1 | 10.941 | 15.491 | 4.549 | 20.14 |
| cam_1280 | 2 | 11.485 | 17.288 | 5.802 | 14.95 |
| cam_1280 | 3 | 12.269 | 17.408 | 5.139 | 17.61 |
| cam_640_30hz | 1 | 13.383 | 12.409 | -0.974 | 68.96 |
| cam_640_30hz | 2 | 18.012 | 19.275 | 1.263 | 60.14 |
| cam_640_30hz | 3 | 11.642 | 14.950 | 3.308 | 47.95 |
| cam_640_60hz | 1 | 10.704 | 12.689 | 1.985 | 38.05 |
| cam_640_60hz | 2 | 10.150 | 11.781 | 1.631 | 29.98 |
| cam_640_60hz | 3 | 14.399 | 15.792 | 1.393 | 33.62 |
| depth_640 | 1 | 9.936 | 10.751 | 0.815 | 23.60 |
| depth_640 | 2 | 7.926 | 9.163 | 1.236 | 19.31 |
| depth_640 | 3 | 7.457 | 8.046 | 0.589 | 10.27 |
| jsimu | 1 | 4.818 | 4.659 | -0.160 | 20.34 |
| jsimu | 2 | 7.536 | 7.585 | 0.049 | 32.60 |
| jsimu | 3 | 6.852 | 7.549 | 0.697 | 65.77 |

## How to reproduce

From the repository root on an idle single-GPU host, build the test image and open a shell in the test container.

```sh
./script/build.sh test
./script/run.sh -t test -- bash
```

Inside the container, work from the repository root and set `JETBOT_USD` to the container-visible path of the official Jetbot USD. Run the five cases sequentially and render the saved JSON files.

```sh
set -e
runner=test/integration/pytest/_output_cost_runner.py
results=$(mktemp -d)
for case_name in cam_1280 cam_640_30hz cam_640_60hz depth_640 jsimu
do
    /isaac-sim/python.sh "$runner" --case "$case_name" \
        --robot-usd "${JETBOT_USD:?Set JETBOT_USD to the official Jetbot USD path}" \
        --repeats 3 --out "$results/$case_name.json"
done
python3 "$runner" --render "$results"/*.json
```
