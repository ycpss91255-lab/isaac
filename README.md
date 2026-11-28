# isaac

**[English](README.md)** | **[繁體中文](doc/README.zh-TW.md)** | **[简体中文](doc/README.zh-CN.md)** | **[日本語](doc/README.ja.md)**

A reusable base repository for NVIDIA Isaac Sim 6.2.0. The Docker development environment is built on [`ycpss91255-lab/base`](https://github.com/ycpss91255-lab/base).

Downstream projects pin this repository as a Git submodule and import the shared Python framework from [framework/isaac_devkit/](framework/isaac_devkit/). [src/](src/README.md) contains driver scripts and sensor configurations outside the downstream framework contract.

Scene spawning and articulation drive defaults use Isaac Sim Core Experimental (`isaacsim.core.experimental`). Configure asset physics in sim_asset for asset_converter to write into USD. `IsaacDriver` starts Kit with `isaacsim.SimulationApp`. Downstream application nodes (CoreSAM, AGV bring-up) and the ROS 1 / ROS 2 bridge for Noetic interop live in sibling docker folders.

## Prerequisites

- NVIDIA Linux x86_64 driver `595.58.03` (version tested by NVIDIA for Isaac Sim 6.2.0). [Official requirements](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html)
- GPU `>= RTX 4080` (or equivalent), VRAM `>= 16 GB`
- Docker + nvidia-container-toolkit
- ~50 GB free disk. A runtime image is about 21 GB, including the 20.7 GB NGC base. Stages share layers. Allow extra space for BuildKit and 5–10 GB for caches after the first launch.

NGC image (`nvcr.io/nvidia/isaac-sim:6.2.0.1`, the 6.2.0 GA build -- see the `Dockerfile` `BASE_IMAGE` comment for why not `:6.2.0`) is publicly pullable — no `docker login nvcr.io` required.

## Quick Start

From a fresh clone, run these two first-time steps from the repo root:

```bash
./script/checkout_identity.sh isolate   # first time only — gives this checkout its own image tag + compose project
./script/init_isaac_dirs.sh             # first time only — runs ./script/setup.sh apply, creates the 10 host-owned cache dirs
```

> The cache dirs must exist and be owned by you **before** a container mounts them. Otherwise the docker daemon creates them as **root**, and Kit cannot write its caches. `init_isaac_dirs.sh` creates them, and the pre-run hook runs it again before every `just docker run`. If they are already root-owned, the script stops and prints a `chown` fix.

Then pick **one** path. The stages are independent: build only the stage you are going to run. The devel build is **not** needed before the headless path.

| You want to | Build | Run |
|---|---|---|
| Run a headless scene | `just docker build -t headless` | `just docker run -t headless -d`, then [Headless: bring Isaac up and run a scene](#headless-bring-isaac-up-and-run-a-scene) |
| An interactive shell to develop in | `just docker build` (devel) | `just docker run` |
| Watch the sim over WebRTC | `just docker build -t stream` | `just docker run -t stream -d`, then [Connecting to the WebRTC livestream](#connecting-to-the-webrtc-livestream) |

A cold build pulls the 20.7 GB NGC base image. Pull time depends on network speed. Later builds reuse cached layers across stages.

Production stages (both idle on startup — exec driver scripts into the running container):

```bash
just docker run -t headless -d                             # pure sim, no streaming (ISAAC_LIVESTREAM=0)
just docker run -t stream -d                               # sim + WebRTC streaming (ISAAC_LIVESTREAM=2)
just docker exec -t stream /isaac-sim/python.sh <script>   # run a driver script
```

> Stage tree: `devel-base` -> `devel` (shared layer: isaac code + common config) -> `gui` / `stream` / `headless`. Only the `gui` service mounts X11 (`["stage:gui"] "gui.mode" = "force"` in `setup.toml`; top-level `[gui]` sets `mode = "off"`, so `devel` and the other stages mount none): `just docker run -t gui`. Two stages auto-emitted as profile-gated compose services per [base #215](https://github.com/ycpss91255-lab/base/issues/215): `headless` (pure sim, `ISAAC_LIVESTREAM=0`) and `stream` (sim + WebRTC, `ISAAC_LIVESTREAM=2`). Both idle on startup — the container stays up and you exec driver scripts in via `just docker exec -t <stage> <cmd>`. Use `just docker run -t <stage> -d` to launch.

### Headless: bring Isaac up and run a scene

Start the headless container once for the session.

```bash
just docker build -t headless
just docker run -t headless -d
```

From the host, run `just run scene <usd>` with a path visible inside the container. Relative paths start at the repository root (`~/work`). The default driver opens the USD, plays the timeline and updates until you quit. For custom behavior, pass a Python file defining one `IsaacDriver` subclass. Its `USD` takes precedence when set.

```bash
just run scene "models/my robot.usd"
just run scene "models/my robot.usd" --driver "drivers/my driver.py"
```

For ROS I/O, set `ISAAC_IO_PLUGIN=module:function` in the container environment. The driver calls the plugin before playback. With the variable unset or empty, the default driver loads no ROS modules.

To run a standalone Python example, choose a headless script from the [official Isaac Sim examples](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/introduction/examples.html#standalone-examples). Replace `path/to/your_scene.py` with the script’s path inside the container. Relative paths start at the repository root (`~/work`).

```bash
./script/exec.sh -t headless bash -c \
  'echo $$ > /tmp/isaac-driver.pid; exec /isaac-sim/python.sh path/to/your_scene.py'

just docker stop
```

Kit writes its session log to `isaac-sim/kit/logs/Kit/<app>/<version>/kit_<timestamp>.log` on the host. To follow the newest one:

```bash
tail -f "$(ls -t isaac-sim/kit/logs/Kit/*/*/kit_*.log | head -1)"
```

`docker logs` on the container shows only its idle main process (`sleep infinity`), not the scripts you exec in.

> Commands with a quoted `bash -c '...'` go through `./script/exec.sh` instead of `just docker exec`. In base v0.42.0, the `just` recipe re-splits its arguments, so the quoted command and any `>` would run on the host. base fixed this in v0.43.0-rc5 (base PR #1298), and this repo still pins v0.42.0 (#297).

### Startup warnings you can ignore

Kit prints a few warnings on every launch that do not affect the run:

- `OmniHub: ... Hub encountered error. Trying to reconnect to Hub. retry_reason="Hub failed to launch: ..."`, about 40 lines in the first 2 seconds. OmniHub is an optional local cache service for Nucleus assets. Its helper (`/usr/local/bin/hub`) exits with `Permission denied` inside the container, so Kit loads assets directly.
- `Extensions config 'extension.toml' doesn't exist '/home/<user>/work/<dir>'`, one per top-level directory of the repo (about 15). These came from images built before this fix: the experience file's `extsUser` extension folder was missing from the image, the container user could not create it, and Kit searched the working directory for extensions instead. The image now creates the folder. If you still see these warnings, rebuild the stage with `just docker build -t <stage>`.

### Stopping a driver script

Ctrl+C in an interactive `just docker exec` reaches the script. Its SIGINT handler then shuts Kit down. But if the exec client is not a TTY, or if it is killed (a closed terminal, `timeout`, CI), the signal never reaches the script and **Kit keeps running** inside the container. To stop it reliably, record the PID when you start the script, as the example above does with `echo $$ > /tmp/isaac-driver.pid`. Then send SIGINT to that process's child, which is the Python that `python.sh` started:

```bash
./script/exec.sh -t headless bash -c 'pkill -INT -P "$(cat /tmp/isaac-driver.pid)"'
```

Each container uses a private PID namespace, so `pkill` inside it sees only that container's processes. Avoid a bare `pkill -f <script>` because it can still match other processes in the same container. To stop everything in this checkout, use `just docker stop` to remove its containers and stop any Kit running inside.

### One image and one compose project per checkout

Every checkout of this repo on a host used to resolve the same image tag (`<hub>/isaac:<stage>`) and the same compose project (`<hub>-isaac`). `just docker build` then pruned the image another checkout had built, and `just docker stop` / `run` removed another checkout's containers (upstream: [base#1550](https://github.com/ycpss91255-lab/base/issues/1550), [base#1551](https://github.com/ycpss91255-lab/base/issues/1551), [base#1552](https://github.com/ycpss91255-lab/base/issues/1552)). Until base fixes that:

- `./script/checkout_identity.sh isolate` writes `[[image.rules]] rule = "string:isaac-<dir>-<hash>"` (and `[project] name`) into the gitignored `setup.local.toml`. The image tag, the compose project and the container names all follow it. `./script/checkout_identity.sh show` prints what this checkout resolves to.
- The pre build / run / stop hooks refuse to act on the shared names. `ISAAC_ALLOW_SHARED_IDENTITY=1` overrides that; CI's build steps use it.
- `just docker run` does not rebuild an image that already exists (base#1552). After pulling changes, run `just docker build -t <stage>` before `just docker run -t <stage>`.
- Disk cost: each checkout or worktree that builds has its own image tags (`<hub>/isaac-<dir>-<hash>:<stage>`). The nominal size shown by `docker images` is about 21 GB per stage tag. Shared layers mean removing a tag reclaims less disk space. Deleting the checkout directory leaves the images in the Docker daemon.
- Cleaning up a deleted checkout: take the `isaac-<dir>-<hash>` name from `./script/checkout_identity.sh show` (run it before deleting the directory; it needs `.env.generated`) or from `docker images`. A custom `PROJECT_NAME` can differ from `<hub>-<slug>`. Copy the project from the label output on the row for the deleted checkout's image.

  ```bash
  SLUG='isaac-<dir>-<hash>'   # exact name, e.g. from "image: <hub>/<SLUG>:<stage>"
  docker ps -a --format '{{.Label "com.docker.compose.project"}}  {{.Image}}  {{.Names}}'
  PROJECT='<project>'
  docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}'
  docker ps -aq --filter "label=com.docker.compose.project=${PROJECT}" | xargs -r docker rm -f  # kills running containers. Use only for a checkout that no longer exists, never a live one
  docker images --filter "reference=*/${SLUG}:*"
  docker images --filter "reference=*/${SLUG}:*" --format '{{.Repository}}:{{.Tag}}' | xargs -r docker rmi
  ```

  Untagging an image with `docker rmi` frees nothing from shared layers another checkout still uses until the last tag referencing them is gone. The filters match the exact project and image slug. Do not widen them to `isaac*` and do not run `docker image prune -a`: the shared `test-tools:<base version>` image (next bullet) must not be removed by this procedure.
- One image stays shared: every build also builds the lint/bats tool image `test-tools:<base version>` (now `test-tools:v0.42.0`), named by the pinned base version only. Every checkout and every repo on the host that pins the same base version writes the same tag, so do not delete it while another checkout may be building. `just docker build --clean-tools` removes it for all of them. It comes from base's `build.sh` and is tracked upstream on [base#1551](https://github.com/ycpss91255-lab/base/issues/1551).
- Containers started before isolating stay in the shared project. List them with `docker compose -p <hub>-isaac ps -a` and stop yours by name. `ISAAC_ALLOW_SHARED_IDENTITY=1 just docker stop` stops the whole shared project, other checkouts' containers included.

### Running multiple instances

One instance per checkout is the deliberate default. This repo removed its built-in support for running several instances from one checkout ([ADR-0019](src/doc/adr/0019-remove-same-repo-multi-instance.md)). To run N instances, use multi_run to launch this repo's `compose.yaml` N times. The design is recorded in [multi_run#15](https://github.com/ycpss91255-lab/multi_run/issues/15).

- Give each instance a unique compose project name with `-p <name>`. This keeps `just docker stop` scoped to its own instance and prevents a new run from adopting a stale instance.
- Each instance needs its own isolated `isaac-sim/` cache and data tree. Sharing writable cache directories silently corrupts the Kit cache of an already running instance. See [Cache layout](#cache-layout).
- Parallel headless runs need no port overrides. Override ports only for streaming.

Available GPU memory sets the practical instance count. On a 32607 MiB card, each running Isaac instance used about 3.9 GiB, enough for 6–7 instances. Divide your card's available memory in GiB by 3.9 for an estimate. The instances share GPU compute, so each runs more slowly.

## Mounting local USD models

Isaac ships no example models. Use USD models from `sim_asset` or the output of `asset_converter`.

To validate a USD asset, use Isaac Sim’s [Asset Validation](https://docs.isaacsim.omniverse.nvidia.com/latest/robot_setup/asset_validation.html) tool.

1. Run `cp setup.isaac_sample.toml setup.local.toml` to create the gitignored local configuration. If you already have a local configuration, merge the sample into it to keep your checkout settings.
2. Edit the model mount’s `source` to point to your models. Keep its read-only target at `/home/${USER_NAME}/models/sim_asset` so scenes resolve the same paths on every machine. If you add model mounts, add their container paths to `MODEL_PATH`, separated by colons.
3. Start the container with `just docker run -t headless -d`.

Base replaces the entire `[[volumes]]` list when it applies the local configuration. Keep every mount from `setup.toml` in your copy and update it whenever the repo adds a mount. Before starting the container, `just docker run` warns about missing source and target pairs and continues startup. A local configuration without a volume list inherits the repository mounts.

## Connecting to the WebRTC livestream

Isaac Sim 6.2.0 uses the NVCF (`omni.services.livestream.nvcf`) livestream protocol. Connect with the desktop client or a browser-based viewer:

1. Download the **Isaac Sim WebRTC Streaming Client** from [NVIDIA docs — manual livestream clients](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/manual_livestream_clients.html). Use the client version NVIDIA lists there for your Isaac Sim release.
2. While `stream` is running, launch the client and enter Server: `<server-ip>` (use `localhost` for same-machine, the server's LAN IP otherwise). **Do not add `:8011` or any port suffix** — the client manages signaling/data ports internally; appending a port routes through the wrong path and yields a black screen.
3. Click Connect. First-time shader compile takes 1–3 min before the viewport renders.

### Browser-based viewer (omniverse_web_viewer)

The [`omniverse_web_viewer`](https://github.com/ycpss91255-lab/omniverse_web_viewer) repo provides a browser-based client as a sidecar container. Bundled as a submodule at `web_viewer/` in this repo.

```bash
# First time: init submodules + create per-host config
git submodule update --init --recursive web_viewer
cp config/host.yaml.example config/host.yaml
# Edit config/host.yaml: set network.public_ip to this host's LAN IP

# Bring up the idle stream container + host.yaml + web-viewer.
# The post-run hook (base #440) copies host.yaml in and starts the viewer.
just docker run -t stream -d

# Launch Isaac Sim into the container -- an explicit step (run = infra,
# exec = workload). Either a driver script:
just docker exec -t stream /isaac-sim/python.sh <driver.py>
# ...or, for a no-driver quick stream, the livestream wrapper:
#   just docker exec -t stream /usr/local/bin/runheadless-host-config.sh

# Watch Isaac Sim load: Kit's session log on the host (docker logs only
# shows the container's idle main process)
tail -f "$(ls -t isaac-sim/kit/logs/Kit/*/*/kit_*.log | head -1)"

# Open Chrome -> http://<host-ip>:5173
# Boots straight into the live stream (stream-only auto-launch; no UI Option screen)

# Stop everything (the post-stop hook removes the web-viewer)
just docker stop
```

`config/host.yaml` is gitignored and per-machine. Its `network.public_ip` is mounted into both the Isaac container (read by `runheadless-host-config.sh` for the Kit `publicEndpointAddress` arg) and the web-viewer container (read by entrypoint for `SIGNALING_SERVER`).

The post-run hook also passes `network.public_ip` to the viewer container as `SIGNALING_SERVER` env -- defense in depth so the viewer still gets the right host IP if its locally cached image was built before `omniverse_web_viewer#12` (the entrypoint that reads `/etc/host.yaml`). Rebuild `owv:runtime` after the `web_viewer/` submodule pointer bumps to pick up newer entrypoint changes.

Requirements: Chrome or Chromium (Firefox incompatible). One interactive client per running Isaac Sim.

Notes:

- The streaming kit app simultaneously listens on `8011` (NVCF signaling, FastAPI/uvicorn), `49100` (self-host WebRTC), and `8211` (kit API / streaming viewer). The WebRTC Streaming Client picks the right one — leave the port off.
- **Only one client can connect at a time** (NVIDIA limitation). A second connection attempt is rejected.
- `[network]` sets `mode = "host"` in `setup.toml`, so the container's listen port = host's listen port. Make sure the host firewall allows `8011/tcp` and `49100/tcp` (e.g. `sudo ufw allow 8011/tcp && sudo ufw allow 49100/tcp`).
- In `setup.toml`, `[deploy]` sets `gpu_capabilities = "all"`, which includes `video` — without it, nvidia-container-runtime does not mount NVENC libs (`libnvidia-encode.so`, `libnvcuvid.so`), so the server connects but cannot encode frames → black screen.
- Verify the listeners from the server: `ss -tln | grep -E ':8011|:49100'` should show both `LISTEN ... :8011` and `LISTEN ... :49100`.

### Deterministic stream-source producer (GHCR image, isaac#223)

For CI and the browser-based visual e2e ([`omniverse_web_viewer#48`](https://github.com/ycpss91255-lab/omniverse_web_viewer/issues/48)), a pullable, pinned producer image publishes a *guaranteed non-black* WebRTC source without a live desktop Isaac session. On boot it renders a deterministic empty-but-lit stage — a dome + distant key light over a 12×12 checkerboard floor, the perspective camera set to `eye=[15,-15,11]` and aimed at `target=[0,0,0]` via Isaac Sim’s `ViewportManager.set_camera_view` — and livestreams it forever, so a browser can connect at any time and always see a reproducible frame. The whole scene is authored programmatically (no external asset), so the image is self-contained.

- **Image**: `ghcr.io/ycpss91255-lab/isaac-stream-source:<tag>` (pinned, immutable tag — not `:latest`). Built from the `producer` Dockerfile stage.
- **Driver**: `src/script/stream_source_producer.py`, baked at `/opt/isaac-producer/stream_source_producer.py` and launched by the image `CMD`.
- **Publish**: manual only via the `Publish Stream-Source Producer (GHCR)` workflow (`workflow_dispatch`, input `tag`, default `0.0.1`). There is no push/tag trigger, so nothing publishes on merge.

Run it:

```bash
# --network=host so the container's WebRTC listen ports = host's.
# PUBLIC_IP is this host's LAN IP (what a remote browser dials);
# ISAAC_SIGNAL_PORT overrides the default signaling port (49100).
docker run --rm --network=host --gpus all \
  -e PUBLIC_IP=<host-lan-ip> \
  -e ISAAC_SIGNAL_PORT=49100 \
  ghcr.io/ycpss91255-lab/isaac-stream-source:0.0.2

# Then connect a browser / the omniverse_web_viewer to <host-lan-ip> (see above).
```

No producer image has been published from Isaac Sim 6.2.0 yet. The newest one is `0.0.2`, built on 6.0.1, so the table below ends there. Publishing is a manual `workflow_dispatch` of the publish workflow, and the table updates from the image's own label.

### Which Isaac Sim is in which image

The producer image version increments on its own; it does not encode the Isaac Sim version. To find out which Isaac Sim a given image was built on, ask the image.

<!-- producer-versions:start -->
| Tag | Isaac Sim | Source |
|---|---|---|
| `0.0.1` | 5.1.0 | declared (predates the label) |
| `0.0.2` | 6.0.1 | declared (predates the label) |

Generated by `script/ci/sync_producer_versions.py`; do not edit by hand.

The table is a convenience view. The authority is the image itself --
ask it directly when it matters:

```bash
docker inspect ghcr.io/ycpss91255-lab/isaac-stream-source:<tag> \
  --format '{{index .Config.Labels "org.opencontainers.image.base.name"}}'
```
<!-- producer-versions:end -->

Required: an NVIDIA GPU runtime (`--gpus all`) for NVENC frame encoding, `--network=host`, and `PUBLIC_IP` for a non-localhost client. `ISAAC_SIGNAL_PORT` is optional (defaults to `49100`). The driver also accepts `--public-ip` / `--port` / `--run-seconds N` (`N>0` bounds a smoke run; the default runs forever).

## Driver configuration

The base `IsaacDriver` enables only `isaacsim.core.nodes` at boot. To use ROS 2 with this driver, set `ISAAC_IO_PLUGIN` to the external plugin’s `module:function` and pass any Kit extensions it requires through `ISAAC_KIT_EXTRA_ARGS`. Sensor setup accepts the existing `ros:` YAML fields and returns the USD prim or mount path.

### Extra Kit arguments (`ISAAC_KIT_EXTRA_ARGS`)

`IsaacDriver.run` reads `ISAAC_KIT_EXTRA_ARGS`, splits it on whitespace, and appends the tokens to the Kit arguments it boots with (after the built-in boot arguments). Unset, empty or whitespace-only leaves behaviour unchanged. Only `IsaacDriver` reads this variable; `stream_source_producer` and the scripts under `src/script/` do not support it.

```bash
export ISAAC_KIT_EXTRA_ARGS='--/app/isaac_test/marker=1'
/isaac-sim/python.sh my_driver.py
# or, on one line:
ISAAC_KIT_EXTRA_ARGS='--/app/isaac_test/marker=1' /isaac-sim/python.sh my_driver.py
```

### Startup plugin (`ISAAC_IO_PLUGIN`)

`IsaacDriver.run` reads `ISAAC_IO_PLUGIN` (`module:function`). After the stage is built and before the timeline plays, it imports the module and calls `function(stage, robot_prim, config)` once. `config` is an opaque dict (currently `usd_path` and `robot_prim`, the stage's default prim path). Unset or empty calls nothing and imports no ROS module. A malformed value, a module that cannot be imported, or a missing function each fail at startup with an error naming the cause. Only `IsaacDriver.run` supports it; `stream_source_producer` and the scripts under `src/script/` do not.

```bash
export ISAAC_IO_PLUGIN='my_pkg.io:setup_io'
/isaac-sim/python.sh my_driver.py
# or, on one line:
ISAAC_IO_PLUGIN='my_pkg.io:setup_io' /isaac-sim/python.sh my_driver.py
```

### Python output API (isaac#365)

`isaac_devkit.output.setup_output` delivers simulation data to Python callbacks without ROS. Kinds: `rgb` (uint8 `(H, W, 3)`), `depth` (float32 `(H, W)`), `joint_state` (`names` / `positions` / `velocities` / `efforts`) and `imu` (`lin_acc` / `ang_vel` / `orientation`, order `w, x, y, z`). The GPU to CPU copy happens only for kinds that have a registered consumer. `ISAAC_OUTPUT_MODE` supports only `python` (the default). Any other value, including `ros`, raises `ValueError`. The `isaac_ros_io` plugin provides ROS output through `ISAAC_IO_PLUGIN` (ADR-0025 has been superseded).

```python
from isaac_devkit.output import CameraOutput, JointOutput, setup_output

out = setup_output(
    cameras=[CameraOutput("rgb", "/World/Robot/cam", 640, 480)],
    joint=JointOutput("/World/Robot"),
)
out.register(lambda frame: print(frame.kind, frame.stamp), kinds=["rgb", "joint_state"])
# per app.update():
out.step(sim_time_seconds)
```

## Cache layout

All Isaac Sim runtime state persists under `${WS_PATH}/isaac-sim/` on the host. `WS_PATH` resolves to the repo root, so this is `isaac-sim/` in your checkout. It is gitignored and kept out of the docker build context by `.dockerignore`:

| Host | Container | Purpose |
|------|-----------|---------|
| `isaac-sim/kit/cache` | `/isaac-sim/kit/cache` | Kit framework cache |
| `isaac-sim/kit/data` | `/isaac-sim/kit/data` | Kit app data (`user.config.json`, pipapi envs) |
| `isaac-sim/kit/logs` | `/isaac-sim/kit/logs` | Kit app logs |
| `isaac-sim/ov/cache` | `/home/${USER_NAME}/.cache/ov` | Omniverse cache (shader build, mostly) |
| `isaac-sim/ov/data` | `/home/${USER_NAME}/.local/share/ov/data` | Omniverse data |
| `isaac-sim/ov/logs` | `/home/${USER_NAME}/.nvidia-omniverse/logs` | Omniverse logs |
| `isaac-sim/pip` | `/home/${USER_NAME}/.cache/pip` | pip cache |
| `isaac-sim/nvidia/glcache` | `/home/${USER_NAME}/.cache/nvidia/GLCache` | GL shader cache |
| `isaac-sim/nvidia/computecache` | `/home/${USER_NAME}/.nv/ComputeCache` | CUDA compute cache |
| `isaac-sim/documents` | `/home/${USER_NAME}/Documents` | User Documents (USD scenes etc.) |

Pre-2026-05-21 layout (`cache/{kit,ov,pip,glcache,computecache}`, flat `logs/`, flat `data/`) is auto-migrated to the new namespaced paths by `./script/init_isaac_dirs.sh` on first run after upgrade (issue #21 fix-A). Pre-existing shader / pip / compute caches are preserved through the move.

Kit creates `isaac-sim/documents/Kit/shared/screenshots` with mode 000 when the directory does not exist yet. `init_isaac_dirs.sh` pre-creates it as 0755 and repairs a mode-000 one.

The containers report no health status (`HEALTHCHECK NONE`). The NGC base image's check greps a Kit log for `App is loaded`, but these containers idle with no Kit by design, so it marked every one of them `unhealthy`.

First headless launch spends 1–3 min compiling shaders; subsequent launches start in `< 30s` thanks to the persisted caches.

## Container user

The container runs as a host-UID-aligned non-root user (`USER_NAME` from `.env`, UID 1000 by default). The user is added, by numeric gid, to the group of the base image's official account (probed from its `USER`, not hard-coded) so it can read `/isaac-sim/*` (mode `0750`). The MJCF importer and its UI grant this group write access to their `data` directories and the importer’s `data/mjcf` directory so the UI can export beside the source XML. Files written through `/home/${USER_NAME}/work` (mounted to `${WS_PATH}` on the host) keep their host owner — no `chown` dance.

## Container permissions

The defaults grant the minimum permissions needed for headless simulation and livestreaming. If your GUI or a special device needs more access, copy only the required settings below into `setup.local.toml`. To expose a single device, replace `/dev:/dev` with its mapping, such as `/dev/video0:/dev/video0`.

```toml
[security]
privileged = true

[[devices.bindings]]
path = "/dev:/dev"

[[security.cap_add]]
cap = "SYS_ADMIN"

[[security.cap_add]]
cap = "NET_ADMIN"

[[security.cap_add]]
cap = "MKNOD"
```

## EULA

`ACCEPT_EULA=Y` and `PRIVACY_CONSENT=Y` are injected via `setup.toml [environment]`. Note: Isaac Sim 6.x reads privacy consent from `OMNI_ENV_PRIVACY_CONSENT` (the name adopted in 5.1, different from pre-5.1 versions); the `PRIVACY_CONSENT=Y` we currently set is harmless but has no effect — set explicitly if you want telemetry opt-in.

## Smoke Tests

See [doc/test/TEST.md](doc/test/TEST.md).

Every test belongs to exactly one scope group (`core`, `gui`, `stream`, `headless`, `docs`): a pytest module sets `pytestmark = pytest.mark.<group>` (run one group with `pytest -m <group>`), a bats spec carries `# bats file_tags=<group>`. A test with no group fails collection. `test/pytest-baseline.txt` keeps one floor per group. See the group table in TEST.md.

The stream group’s `stream-visual-e2e` GPU job boots the stream stage and checks that Chromium receives advancing frames showing the red test cube.

The `core-gpu` job runs the official Isaac Sim `asset` and `deprecated` Python test buckets in sequence. Both JUnit reports are included in the `official-tests` artifact.

The scoped `core-official-nativepython` job runs NVIDIA’s standalone Python test bucket and the livestream and hello_world examples. See [TEST.md](doc/test/TEST.md#official-isaac-sim-standalone-tests-437) for local execution and artifacts.

Workflow and job names follow [doc/workflow-naming.md](doc/workflow-naming.md); `script/ci/lint_workflow_names.py` checks them.

## Python testing toolkit (devel-test stage)

The `devel-test` stage ships `pytest`, `pyyaml`, and `pytest-cov` installed into Isaac Sim's bundled Python (`/isaac-sim/python.sh`), so consumer repos can run Python unit / integration tests inside the container. The runtime `devel` stage stays lean — the testing dependencies are only paid for in `devel-test`.

Usage:

```bash
just docker build -t test                                                 # build the devel-test stage (compose service `test`)
just docker run -t test -- /isaac-sim/python.sh -m pytest test/unit/
just docker run -t test -- /isaac-sim/python.sh -m pytest --cov=<pkg> test/
```

System `python3` cannot install these packages (PEP 668 blocks `pip` on the Isaac base image) — always invoke `/isaac-sim/python.sh -m pytest ...` instead of `pytest ...`.

GPU integration tests (Isaac Sim must boot, e.g. headless camera prim smoke test, #127) run through the `test` compose service, which gets an NVIDIA GPU reservation from the `["stage:devel-test"]` override in `setup.toml` (`"deploy.gpu_mode" = "force"`, base #493):

```bash
just docker run -t test -- /isaac-sim/python.sh -m pytest \
    test/integration/pytest/test_camera_headless.py
```

The scoped `core-gpu` CI job also runs the official Isaac Sim `core` and `sensors` Python buckets. See the [test guide](doc/test/TEST.md#official-isaac-sim-python-buckets-438-440) for scheduling, artifacts, and known exceptions.

Run pytest against `test/integration/` to include both the GPU integration tests and the [no-ROS checks](test/integration/no_ros/README.md).

Pass criterion is stdout marker lines (`[BOOT OK]` / `[CAMERA PRIM]` / `[EXIT CLEAN]`), not the return code — Kit's `app.close` calls `_exit(0)`. See [doc/test/TEST.md](doc/test/TEST.md).
