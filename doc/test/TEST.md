# TEST.md

**226 tests** total (bats). Hosted pytest collects **756 tests**.

## Tests by group (isaac#434)

CI runs per scope, so every test belongs to exactly one group: core (framework, shared Docker layers, shared scripts, CI tooling), gui, stream, headless, docs. A pytest module declares its group with a module-level `pytestmark = pytest.mark.<group>` (select with `pytest -m <group>`); a bats spec with `# bats file_tags=<group>` (select with `bats --filter-tags <group>`). A test with no group fails collection (`test/group_markers.py`) and the static check (`script/ci/scope_groups.py check`, pinned by `test_test_groups.py`). Floors per group are in `test/pytest-baseline.txt`; `test_test_groups.py` pins this table to the specs and to the baseline file.

| Group | bats | pytest hosted | pytest GPU | Total |
|-------|-----:|--------------:|-----------:|------:|
| core | 123 | 648 | 35 | 806 |
| gui | 0 | 0 | 0 | 0 |
| stream | 90 | 19 | 0 | 109 |
| headless | 13 | 6 | 0 | 19 |
| docs | 0 | 83 | 0 | 83 |

The `**226 tests** total` above counts the bats specs only. `gui` has no tests yet (they arrive with #428); `headless` has the boot check (#461); the GPU integration tests are all `core` because they boot Isaac on the shared `devel` layer.

## test/bats/smoke/host_yaml_spec.bats (16)

Shared host.yaml parser (`script/host_yaml.sh`), used by both the post-run hook and `runheadless-host-config.sh`: the `public_ip` resolver (#104) and the `livestream.ports` resolver (#231).

| Test | Description |
|------|-------------|
| `host_yaml: clean quoted value` | A quoted IPv4 is returned verbatim. |
| `host_yaml: strips a trailing inline comment (#104)` | `public_ip: "1.2.3.4"  # note` yields `1.2.3.4`, not the comment. |
| `host_yaml: trims whitespace on an unquoted value` | Leading/trailing whitespace is removed. |
| `host_yaml: accepts a hostname` | A DNS hostname passes validation. |
| `host_yaml: absent file -> empty, rc 0` | A missing file resolves to empty (localhost-only), no error. |
| `host_yaml: key absent -> empty, no warning` | A file without `public_ip` resolves to empty with no warning. |
| `host_yaml: key present but empty -> empty value + warning (#104)` | Distinguishes "not configured" from "configured but unparseable" -- warns on stderr. |
| `host_yaml: invalid value (metacharacters) -> rc 1 + error (#104)` | A value with illegal characters fails fast with an error instead of passing garbage to Kit / the viewer. |
| `host_yaml: resolve_port reads a numeric livestream port` | `resolve_port` returns the `livestream.ports.signal` integer. |
| `host_yaml: resolve_port resolves each of signal/media/serve/api` | All four port keys resolve independently. |
| `host_yaml: resolve_port strips a trailing inline comment` | An inline `# override` comment is stripped from the port value. |
| `host_yaml: resolve_port absent key -> empty, rc 0, no warning` | A missing port key resolves to empty (omit => default), no warning. |
| `host_yaml: resolve_port present-but-empty -> empty, rc 0 (omit => default)` | A present-but-blank key (e.g. `media:`) is treated as omitted, no warning. |
| `host_yaml: resolve_port absent file -> empty, rc 0` | A missing file resolves every port to empty. |
| `host_yaml: resolve_port non-numeric -> rc 1 + error` | A non-numeric port fails fast with an error. |
| `host_yaml: resolve_port out-of-range -> rc 1 + error` | A port outside 1..65535 fails fast with an error. |

## test/bats/smoke/runheadless_host_config_spec.bats (12)

Single builder of the Isaac livestream Kit invocation (`script/runheadless-host-config.sh`); ports from container env or the post-run hook's port env file (#231/#234), `public_ip` from `/etc/host.yaml`. Exercised via `RUNHEADLESS_DRYRUN=1` (base #465/#440).

| Test | Description |
|------|-------------|
| `runheadless: first token is the Kit launcher` | The emitted command line starts with `/isaac-sim/runheadless.sh`. |
| `runheadless: always emits -v + quitOnSessionEnded=false` | The two unconditional Kit args are always present. |
| `runheadless: port env -> livestream port kit-args` | `ISAAC_SIGNAL_PORT` / `ISAAC_MEDIA_PORT` / `ISAAC_API_PORT` map to `--/app/livestream/port` / `fixedHostPort` / the http port. |
| `runheadless: no port env -> no port kit-args (default instance)` | With no port env, the port args are omitted (Kit defaults). |
| `runheadless: ports env file -> livestream port kit-args (#234)` | The ports the post-run hook copied in as `/etc/isaac/livestream-ports.env` reach the signal / media / api Kit args on any launch path, including the manual `exec`. |
| `runheadless: absent ports env file -> no port kit-args (#234)` | No env file leaves the port args omitted (Kit defaults), the pre-#231 behavior preserved exactly. |
| `runheadless: caller env wins over the ports env file (#234)` | An `ISAAC_*_PORT` already set by the caller overrides the file; keys the caller did not set still come from it. |
| `runheadless: ports env file honors only the ISAAC_*_PORT keys (#234)` | The file is parsed, not sourced -- unrelated keys (e.g. `PATH`) and comment lines cannot reach the launcher environment. |
| `runheadless: host.yaml public_ip -> publicEndpointAddress` | A valid `public_ip` is appended as `--/app/livestream/publicEndpointAddress`. |
| `runheadless: no host.yaml -> no publicEndpointAddress` | Absent host.yaml omits the public-endpoint arg (localhost-only). |
| `runheadless: invalid public_ip -> rc 1 (shared parser rejects)` | Garbage in host.yaml fails fast via the shared `resolve_public_ip`. |
| `runheadless: forwards extra args after the built kit-args` | Trailing `"$@"` (e.g. a scene USD) is appended after the constructed args. |

## test/bats/smoke/post_run_hook_spec.bats (18)

Post-run hook (`script/hooks/post/run.sh`, base #440): on `run.sh -t stream -d`, copies host.yaml into the Isaac container and starts the per-project `${USER_NAME}-${IMAGE_NAME}-owv<suffix>` web-viewer (#237, isaac#238). The WebRTC livestream ports are sourced from `host.yaml` (#231), not hardcoded. base v0.42.0 removed `--instance` / `INSTANCE_SUFFIX` (base#666); the viewer suffix is now derived from the resolved `PROJECT_NAME` (empty when it equals the default `${DOCKER_HUB_USER}-${IMAGE_NAME}` -> byte-identical to today's names, `-<remainder>` for any distinct project; owv#55). A distinct `PROJECT_NAME` is the internal isolation seam for CI/tooling (a distinct compose project + per-project viewer name, so a CI actor never reaps a co-hosted manual stack), not a return of user-facing same-repo multi-instance, which ADR-0019 removed as a feature. The Isaac stream container name is base-fixed by `compose.yaml` `container_name` (no suffix; residual co-host collision filed as base#920), so the `docker cp` target is that fixed name. Exercised via `POST_RUN_DRYRUN=1`.

| Test | Description |
|------|-------------|
| `post-run: non-stream target is a no-op` | A non-`stream` target produces no actions. |
| `post-run: stream without -d is a no-op` | The stream stage without `-d/--detach` produces no actions. |
| `post-run: stream + -d starts the viewer with stream-only UI mode` | Viewer `docker run` carries `VIEWER_UI_MODE=stream-only`; negative guards that `usd-viewer` and the dropped `VIEWER_AUTO_LAUNCH` flag never appear (#123). |
| `post-run: omitted ports fall back to viewer defaults 49100/5173 (#231)` | With no host.yaml, the viewer gets `SIGNALING_PORT=49100` + `SERVE_PORT=5173`, no `MEDIA_PORT` (negotiated), and no per-instance `--env-file` (ADR-0019) -- today's exact behavior. |
| `post-run: viewer signal/serve ports sourced from host.yaml (#231)` | `livestream.ports.signal`/`serve` flow to the viewer as `SIGNALING_PORT`/`SERVE_PORT`; the old literal 49100/5173 no longer appear. |
| `post-run: media port omitted -> no MEDIA_PORT on the viewer (#231)` | Omitting `media` passes no `MEDIA_PORT` -- the viewer negotiates via SDP. |
| `post-run: media port set -> MEDIA_PORT wired to the viewer (#231, PRD:94)` | A set `media` port is passed as `-e MEDIA_PORT`, closing the un-wired media link. |
| `post-run: isaac ports are copied into the Isaac container as an env file (#231)` | Set `ISAAC_*_PORT` are `docker cp`'d to `/etc/isaac/livestream-ports.env` for the later runheadless exec to source. |
| `post-run: no livestream ports -> no env file copied to the Isaac container (#231)` | With no ports set, no env file is copied -- exact current behavior (Kit defaults). |
| `post-run: invalid livestream port aborts with rc 1 (#231)` | A non-numeric / out-of-range port fails the hook via the shared resolver. |
| `post-run: viewer container name derives from IMAGE_NAME (per-stack)` | The viewer name is `${USER_NAME}-${IMAGE_NAME}-owv<suffix>` (here, default project, `alice-isaac-owv`): `docker rm -f alice-isaac-owv` precedes `docker run --name alice-isaac-owv` (idempotent); the default project carries an empty suffix, while a distinct `PROJECT_NAME` appends `-<remainder>` (see the distinct-PROJECT_NAME test below, isaac#238/owv#55); two isolated stacks no longer collide (#237). |
| `post-run: host.yaml present is copied into the default Isaac container` | A present host.yaml is `docker cp`'d to the default Isaac container `${USER_NAME}-${IMAGE_NAME}-stream` at `/etc/host.yaml` (no `-<instance>` suffix). |
| `post-run: invalid host.yaml aborts with rc 1` | Garbage in host.yaml fails the hook (validated on the host first). |
| `post-run: identity is read from .env.generated, not .env (base A2 model)` | With `.env` absent, identity comes from `.env.generated`: container name is `alice-isaac-stream` (no leading dash) and the viewer image is `alice/...` (not `local/...`). |
| `post-run: .env overlays .env.generated identity (user override wins)` | `.env` (sourced second) overrides `.env.generated`: a `USER_NAME=bob` overlay yields `bob-isaac-stream`. |
| `post-run: viewer image is omniverse_web_viewer:runtime, not stale owv:runtime (#121)` | Viewer `docker run` uses `${DOCKER_HUB_USER:-local}/omniverse_web_viewer:runtime` (owv renamed serve->runtime, #123); regression guard that the old short stale `owv:runtime` is not launched. |
| `post-run: a distinct PROJECT_NAME suffixes the viewer; the Isaac cp target stays base-fixed (owv#55, isaac#238)` | With `PROJECT_NAME=alice-isaac-demo` in `.env.generated` (a distinct project a CI actor pins), the viewer is `alice-isaac-owv-demo` (rm + `--name`) and the `docker cp` target stays the base-fixed `alice-isaac-stream`; guards that a per-project-suffixed `alice-isaac-stream-demo:` cp target never appears. base v0.42.0 removed `INSTANCE_SUFFIX` (base#666); the residual co-host collision on the fixed stream name is base#920. |
| `post-run: ISAAC_STREAM_CONTAINER retargets the Isaac cp (per-run smoke name, isaac#291)` | With `ISAAC_STREAM_CONTAINER=alice-isaac-stream-isaac-smoke-7-1` (what the nightly smoke exports after renaming its stream container), both `docker cp` targets -- `/etc/host.yaml` and `/etc/isaac/livestream-ports.env` -- are that container; the base-fixed `alice-isaac-stream` is never a cp target. |

## test/bats/smoke/post_stop_hook_spec.bats (2)

Post-stop hook (`script/hooks/post/stop.sh`, base #440): stops the out-of-compose web-viewer that `stop.sh` does not see. The viewer suffix is derived from the resolved `PROJECT_NAME` (base v0.42.0 removed `INSTANCE_SUFFIX`, base#666; isaac#238).

| Test | Description |
|------|-------------|
| `post-stop: stops the per-stack viewer (name derived from IMAGE_NAME)` | `stop.sh` removes the per-project `${USER_NAME}-${IMAGE_NAME}-owv` viewer (here `alice-isaac-owv`); the default-project case carries no `-<remainder>` suffix; two isolated stacks no longer collide (#237). |
| `post-stop: a distinct PROJECT_NAME scopes the viewer name (owv#55, isaac#238)` | With `PROJECT_NAME=alice-isaac-demo` in `.env.generated`, the post-stop hook derives the same suffix post/run used and targets `alice-isaac-owv-demo`, symmetric with what post/run created, so one stack's stop cannot leave another's viewer behind. |

## test/bats/smoke/headless_smoke_spec.bats (13)

Behavioral guard for the headless boot check (`script/ci/headless_smoke.sh`, isaac#461) and its GPU job script (`headless_smoke_job.sh`). The headless stage was only ever built, never started; base's compose gives it `restart: unless-stopped`, so a broken start command was a container restarting forever with every other check green. The smoke starts `run.sh -t headless -d` under its own compose project and requires `State.Status == running` and `RestartCount == 0` for a settle window. Run against a stub `run.sh` and a stub `docker` (hermetic, no docker, no GPU); baked into `/smoke_test/` by the devel-test stage.

| Test | Description |
|------|-------------|
| `headless_smoke: a running container with no restarts passes` | running + RestartCount 0 exits 0. |
| `headless_smoke: starts the headless stage detached, never another stage` | `run.sh` gets `-t headless -d`, never `stream`. |
| `headless_smoke: a restarting container fails (the #461 symptom)` | status `restarting` fails and says so. |
| `headless_smoke: a container that restarted but is running now still fails` | running with RestartCount 3 fails: a crash loop reports running between restarts. |
| `headless_smoke: an exited container fails` | status `exited` fails. |
| `headless_smoke: a container that is fine at first but restarts later fails (settle window)` | two healthy inspections followed by `restarting 3` fail the smoke and report `restarting`. |
| `headless_smoke: a healthy container is re-checked across the whole settle window` | a container that stays `running 0` passes and is inspected more than once. |
| `headless_smoke: no container for the project fails closed` | no container id resolved fails. |
| `headless_smoke: a failing run.sh fails the smoke` | a non-zero `run.sh` fails the smoke. |
| `headless_smoke: runs under its own compose project and tears it down, pass or fail` | `PROJECT_NAME` pinned in `.env.generated`; teardown is `COMPOSE_PROFILES='*' compose -p <proj> down`; the default project is never addressed. |
| `headless_smoke: the project defaults to '<derived>-headless-smoke'` | default project name. |
| `headless smoke job: apply, build headless, smoke under a per-run project -- in order` | job script order and per-run `SMOKE_PROJECT`. |
| `headless smoke job: a failing smoke fails the job` | job exit status follows the smoke. |

## test/bats/smoke/stream_smoke_isolation_spec.bats (17)

Behavioral guard for `script/ci/stream_smoke.sh` compose-project isolation (the remaining axis of `ycpss91255-lab/omniverse_web_viewer#55`). The nightly Tier A GPU smoke used to bring its stack up in the DEFAULT project and tear it down by name with `docker rm -f "${USER}-${IMAGE}-stream" owv` -- the exact name a manually-run DEFAULT stack uses, plus the stale pre-isaac#238 literal `owv` (which matched nothing, leaving the real viewer on the serve port). base v0.42.0 removed `--instance` (base#666); the smoke now pins a distinct `PROJECT_NAME` (default `<derived>-smoke`, overridable via `SMOKE_PROJECT`) in `.env.generated`, brings the stack up with a plain `run.sh -t stream -d`, resolves its stream container BY PROJECT (`docker compose -p <proj> ps -q stream`), and tears down project-scoped (`docker compose -p <proj> down`) plus the isaac-owned per-project viewer. The spec runs the real driver against a stub `run.sh` + stub `docker` (both record argv) -- behavioral, hermetic (no docker, no GPU). The driver is baked into `/smoke_test/` next to this spec by the devel-test stage.

| Test | Description |
|------|-------------|
| `stream_smoke: brings the stack up under a distinct PROJECT_NAME, no --instance (owv#55)` | With `SMOKE_PROJECT=alice-isaac-demo`, the recorded `run.sh` argv carries `-t stream -d` with NO `--instance` (base#666), and the distinct project is written into `.env.generated` -- the bring-up is placed in a non-default compose project, never the default project a manual stream stack lives in. |
| `stream_smoke: resolves the stream container BY PROJECT, not by a global name (owv#55)` | The recorded `docker` argv carries `compose -p alice-isaac-demo ... ps -q stream` -- the container id is resolved via the project's own compose ps, so a co-hosted stack's identically-named container is never addressed. |
| `stream_smoke: teardown is project-scoped + the per-project viewer, not the bare name or literal owv (owv#55, isaac#238)` | Teardown runs `docker compose -p alice-isaac-demo ... down` plus `docker rm -f alice-isaac-owv-demo`; effective guards (`run ...; [ status -ne 0 ]`) that neither the bare default-project `alice-isaac-stream` nor the stale literal `owv` is ever a `docker rm -f` target. |
| `stream_smoke: project defaults to '<derived>-smoke' when SMOKE_PROJECT is unset (owv#55)` | With the override unset, the dedicated default project is `<derived>-smoke` (`alice-isaac-smoke`): it is written into `.env.generated`, teardown targets `compose -p alice-isaac-smoke ... down` + `alice-isaac-owv-smoke`, so a bare manual `run.sh -t stream -d` (project `alice-isaac`) never collides with the nightly smoke. |
| `stream_smoke: the stream container gets a per-run name, the hook is told, compose.yaml is restored (isaac#291)` | base v0.42.0 emits a fixed `container_name: ${USER_NAME}-isaac-stream` that ignores `PROJECT_NAME`. During the run, `run.sh` sees the stream service renamed to `${USER_NAME}-isaac-stream-isaac-smoke-7-1` (other services untouched) and `ISAAC_STREAM_CONTAINER=alice-isaac-stream-isaac-smoke-7-1` for the post-run hook; afterwards the derived `compose.yaml` is byte-identical to what setup generated. |
| `stream_smoke: teardown activates every profile so the profiled stream service is removed (isaac#291)` | Every project `down` runs with `COMPOSE_PROFILES='*'`; without it `compose down` skips the `profiles: [stream]` service and leaked the stream container + its Kit on every run. |
| `stream_smoke: reaps only OTHER projects under SMOKE_REAP_PROJECT_PREFIX, never a developer stack (isaac#291)` | With prefix `isaac-smoke-` and run project `isaac-smoke-9-1`, the leftover `isaac-smoke-8-1` project, its `alice-isaac-owv-isaac-smoke-8-1` viewer and `isaac-smoke-8-1-client-browser` are removed; the developer project `alice-isaac`, a foreign `isaac-forklift-perf`, this run's own project, `alice-isaac-stream` and `alice-isaac-owv` are never sweep targets. |
| `stream_smoke: no stale-project sweep unless SMOKE_REAP_PROJECT_PREFIX owns the run (isaac#291)` | Unset prefix (local runs) -> no project listing at all; a prefix that does not cover this run's own project is not trusted either. |
| `stream_smoke: a Kit 110 log with a connected peer passes on the default markers (isaac#291)` | A Kit 110 (Isaac Sim 6.0.1) log, lines verbatim from the GPU host, drives the real driver through the ready wait (`Started primary stream server` -> `App is loaded.`), the attach wait (`signaling headers` -> `Client connected to WebRTC server`) and the dwell to `PASS`. The pre-#291 defaults waited for the Kit 107 `Streaming server started.` line Isaac Sim 6.x never prints. |
| `stream_smoke: a peer that never completes the WebRTC handshake fails the attach (isaac#291)` | The same log cut after `Processing N signaling headers` (as far as a peer that never answers the SDP offer gets, i.e. the old curl probe at best) fails with `streams did not start`. |
| `stream_smoke: a stream container that restarted fails even though it is Running now (isaac#461)` | The liveness probe reads `{{.State.Running}} {{.RestartCount}}` and needs `true 0`; a container with RestartCount 4 that is Running now fails the smoke. |
| `stream_smoke: a busy signal port stops bring-up and names the holder (isaac#497)` | An occupied signal port reports the port and Docker container name before `run.sh` runs. |
| `stream_smoke: a busy media port stops bring-up with an unknown holder (isaac#497)` | An occupied media port with no visible owner reports `unknown`, logs load again and exits before bring-up. |
| `stream_smoke: a UDP-only media holder stops bring-up (isaac#497)` | The real port probe finds the UDP media socket through `ss`. The script reports the holder and exits before invoking `run.sh`. |
| `stream_smoke: skipping preflight reaches bring-up with a busy signal port (isaac#497)` | With `SMOKE_SKIP_PORT_PREFLIGHT=1`, the same signal-port conflict allows `run.sh` to run. |
| `stream_smoke: reports load at startup and elapsed time and load at readiness (isaac#497)` | Checks the three load averages before bring-up and again when Kit is ready, along with elapsed seconds. |
| `stream_smoke: ready timeout reports load, marker progress and port holders (isaac#497)` | A live container logs only the first ready marker. The timeout diagnostic includes the wait duration, load, both markers and both ports' holders. |

## test/bats/smoke/stream_smoke_lib_spec.bats (25)

Pass/fail decision logic of the Tier A stream smoke (`script/ci/stream_smoke_lib.sh`, #233). Before #233 the smoke stopped at "Streaming server started.", so a Kit that boots, opens the signaling socket and then dies on the first real client attach passed green; the probe now attaches a client, asserts the observed stream-start sequence, and holds a dwell window. That logic is GPU-free and lives in a sourceable library so it is unit tested on every image build -- the GPU driver (`script/ci/stream_smoke.sh`) itself stays nightly-only (`ci-stream-smoke.yaml`). The liveness probe is the overridable `smoke_alive` hook: the driver binds it to `docker ps`, these specs bind it to stubs (including one that flips to dead mid-dwell).

| Test | Description |
|------|-------------|
| `port_in_use: a UDP-only listener is busy` | A port-filtered UDP query finds a listener on a port closed to TCP. |
| `port_in_use: an empty ss result and a closed TCP port are free` | The probe returns nonzero when neither protocol has a listener. |
| `port_in_use: a TCP listener is busy when ss is absent` | The probe detects a live loopback TCP listener with `ss` absent from `PATH`. |
| `marker_line: present marker prints its 1-based line number` | A fixed-string marker resolves to its kit log line number. |
| `marker_line: absent marker -> rc 1, no stdout` | A missing marker fails without emitting a bogus line number. |
| `marker_line: missing log file -> rc 1 (no crash)` | An absent kit log is a failure, not a crash. |
| `sequence_line: in-order markers -> rc 0 + line of the LAST marker` | The ordered attach sequence resolves to its final line, which anchors the drop scan. |
| `sequence_line: out-of-order markers -> rc 1 naming the unmet marker` | Each marker must appear AFTER the previous one; the unmet one is named on stderr. |
| `sequence_line: truncated attach (no All Streams connected.) -> rc 1` | A half-connect (signaling headers only) is the exact case a boot-only Tier A used to pass -- it now fails. |
| `sequence_line: no markers given -> rc 1 (misuse is not a pass)` | Misuse fails closed rather than reading as a green run. |
| `drop_line: NVST_CCE_DISCONNECTED after the anchor -> rc 0 + line` | A client disconnect after connect counts as a stream drop. |
| `drop_line: 'Stream Server: streamN ... stopped' after anchor -> rc 0` | An individual stream stopping after connect counts as a drop. |
| `drop_line: Kit 110 'Client disconnected from WebRTC server' after anchor -> rc 0 (isaac#291)` | Kit 110's only peer-drop line counts as a drop; it is not in the Kit 107 regex, so a dropped client would otherwise pass the dwell. |
| `drop_line: a drop BEFORE the anchor is ignored (stale prior session)` | An earlier session's teardown must not fail this run's dwell. |
| `drop_line: healthy connected log -> rc 1 (nothing dropped)` | A healthy log reports no drop. |
| `alive: default hook is fail-closed (never a silent pass)` | A caller that forgets to bind a real liveness probe fails the smoke instead of assuming the container is up. |
| `wait_for: sequence already complete -> rc 0 without waiting` | An already-satisfied sequence returns immediately. |
| `wait_for: sequence never appears -> rc 1 (timeout)` | Timeout is reported distinctly from death. |
| `wait_for: Kit dies while waiting -> rc 2 (death, not timeout)` | A dead Kit during the connect wait is attributed as a death, not a slow start. |
| `dwell: alive + no drop for the whole window -> rc 0` | The healthy path holds the connection for the whole window. |
| `dwell: Kit SIGKILLed mid-dwell -> rc 2 (the #233 bug)` | The core regression: a Kit that dies part-way through the dwell fails the smoke. |
| `dwell: streams stop mid-dwell -> rc 3` | Streams stopping during the dwell fails the smoke with its own code. |
| `dwell: a pre-anchor drop does not fail the window` | The anchor keeps stale pre-connect drop lines from failing a healthy dwell. |
| `log_tail: prints the last N lines between markers` | Failure reporting emits a framed, bounded kit log tail. |
| `log_tail: missing log -> rc 0 and says so (teardown stays safe)` | The failure reporter never itself fails, so teardown still runs. |

## test/bats/smoke/docker_env.bats (5)

| Test | Description |
|------|-------------|
| `entrypoint.sh is installed and executable` | Entrypoint check |
| `bash is available on PATH` | Shell sanity |
| `fastdds.xml is baked at /isaac-sim/fastdds.xml and world-readable` | Fast DDS profile (UDPv4-only) shipped by this repo's Dockerfile, content sanity-checked for `useBuiltinTransports=false` |
| `custom streaming kit experience baked at /isaac-sim/apps/ (issue #21 fix-B)` | The repo's custom streaming `.kit` experience file is baked into `/isaac-sim/apps/` so the stream stage launches it |
| `devel stage drops the NGC Kit healthcheck (idle containers are not 'unhealthy')` | The NGC base image's HEALTHCHECK greps a Kit log for `App is loaded`. devel / headless / stream / test idle with no Kit by design, so the devel stage (inherited by the others) resets it with `HEALTHCHECK NONE`. |

## test/bats/smoke/isaac_smoke.bats (10)

| Test | Description |
|------|-------------|
| `isaac-sim launchers exist and are executable` | `/isaac-sim/runheadless.sh` and `/isaac-sim/runapp.sh` both `0755` |
| `isaac-sim ships Python 3.12 in /isaac-sim/kit/python/bin/python3` | Isolated Python interpreter exists and reports `3.12` |
| `runtime user is host-aligned (not root, not isaac-sim default)` | Container user is the host-UID-aligned `USER_NAME`, not the image default `isaac-sim` (UID 1234) |
| `runtime user is in isaac-sim group (can read /isaac-sim/* mode 0750)` | Group membership unlocks read/exec on Isaac Sim binaries |
| `HOME is writable` | `${HOME}` is owned by the runtime user — required for cache / logs / Documents writes |
| `bundled ROS 2 humble + jazzy libs are both readable` | `librmw_fastrtps_cpp.so` present under both `humble/lib/` and `jazzy/lib/` — image carries both distros; the headless / stream shim picks one via `ARG ROS_DISTRO` |
| `bundled ROS 2 humble + jazzy rclpy are both readable (Python 3.12)` | `rclpy/` Python bindings present under both distros; kit-side `import rclpy` resolves to whichever the bridge extension activates |
| `Isaac Lab targets the Isaac Sim release the image bundles` | Isaac Lab's `[tool.isaaclab.versions] isaacsim` (root `pyproject.toml`) names the same `X.Y.Z` as `/isaac-sim/VERSION` -- bumping `BASE_IMAGE` without `ISAACLAB_VERSION` (or the reverse) fails at build time, not at first Kit boot (isaac#295) |
| `Isaac python torch is Isaac Lab's pinned CUDA 13 build` | The torch distribution on the Isaac python is exactly Isaac Lab's pinned version with `+cu130` (sm_120 kernels for the RTX 5090 runner); any other build means a later pip step overrode Isaac Lab's install (isaac#295) |
| `no pip_prebundle package lost its __init__.py (isaac#288)` | No dangling `__init__.py` symlink under any `pip_prebundle` -- the 6.0.1 build left `packaging` dangling under `omni.services.pip_archive`, breaking matplotlib plots and the Newton experience |

## test/bats/smoke/isaac_ros_env_wrapper.bats (10)

| Test | Description |
|------|-------------|
| `wrapper exists and is executable` | `/usr/local/bin/isaac-ros-env-wrapper.sh` 0755 |
| `/etc/isaac/ros-distro is baked with humble (default ARG)` | Const file written from `ARG ROS_DISTRO` at build time |
| `wrapper exports ROS_DISTRO from /etc/isaac/ros-distro` | Wrapper reads file and exports |
| `wrapper exports LD_LIBRARY_PATH derived from ROS_DISTRO` | Wrapper exports `/isaac-sim/exts/isaacsim.ros2.bridge/${ROS_DISTRO}/lib` |
| `wrapper hard-overrides runtime ROS_DISTRO env` | `ROS_DISTRO=jazzy ./wrapper bash -c 'echo ROS_DISTRO'` still prints `humble` — runtime `-e` ineffective on headless / stream |
| `wrapper passes args verbatim to wrapped command` | `./wrapper echo arg1 arg2 arg3` → `arg1 arg2 arg3` |
| `wrapper appends publicEndpointAddress when PUBLIC_IP is set` | With `PUBLIC_IP` exported, the wrapper adds `--/app/livestream/publicEndpointAddress=<ip>` to the Kit args |
| `wrapper does not append publicEndpointAddress when PUBLIC_IP is empty` | With no `PUBLIC_IP`, the wrapper omits the public-endpoint arg (localhost-only WebRTC) |
| `devel stage ENV ROS_DISTRO is baked (soft)` | Devel interactive shell sees `ROS_DISTRO=humble` from Dockerfile `ENV` |
| `devel stage ENV LD_LIBRARY_PATH points to baked humble lib` | Same — `ENV LD_LIBRARY_PATH=/isaac-sim/exts/isaacsim.ros2.bridge/${ROS_DISTRO}/lib` interpolated at build time |

## test/bats/smoke/init_isaac_dirs_spec.bats (13)

| Test | Description |
|------|-------------|
| `script-under-test is baked into the test stage` | `init_isaac_dirs.sh` is present in the devel-test image for the spec to exercise |
| `fresh run creates all 10 namespaced dirs` | A clean run creates the full per-instance namespaced cache directory set |
| `second run is idempotent (no error, no double-mkdir noise)` | Re-running does not error or re-create existing dirs |
| `migration: pre-2026-05-21 layout is auto-moved to new namespaces` | Legacy cache layout is migrated into the namespaced layout |
| `migration skips when destination already exists (no overwrite)` | Migration does not clobber an existing destination |
| `WS_PATH comes from .env.generated, not the .env overlay` | `WS_PATH` is read from the setup-derived `.env.generated`; a stale `.env` value is ignored. |
| `no .env.generated yet: runs ./script/setup.sh apply to generate it` | On a fresh clone the script runs `./script/setup.sh apply` first (stubbed here), then creates the dirs. |
| `no .env.generated and no setup.sh: actionable error, no removed ./build.sh hint` | The error names `./script/setup.sh apply`, not the removed `./build.sh`. |
| `success hint names just docker, not the removed ./build.sh / ./run.sh` | The next-step hint is `just docker build` / `just docker run`. |
| `Kit screenshots dir is pre-created writable and a mode-000 one is repaired` | `documents/Kit/shared/screenshots` exists as 0755, and one that Kit created as mode 000 is reset to 0755. |
| `pre-run hook creates the cache dirs before compose can mount them as root` | The pre-run hook runs the script, so a `just docker run` before init no longer leaves root-owned mount sources. With root-owned sources, Kit failed `kit/cache/ogn_generated` with EACCES, never registered the ROS 2 OmniGraph nodes, and still exited 0. |
| `--help / -h print usage and exit 0 without creating anything` | `--help` and `-h` print the usage and exit 0 without running `setup.sh` or creating any dir. The script used to ignore the flag and run anyway. |
| `an unknown option is an error with usage, not a silent run` | An unknown option exits 2 with the usage on stderr and creates nothing. |

## test/bats/smoke/python_testing.bats (3)

| Test | Description |
|------|-------------|
| `pytest installed in devel-test stage` | `/isaac-sim/python.sh -m pytest --version` exits 0 — pytest importable via Isaac Sim's bundled Python |
| `pyyaml installed in devel-test stage` | `import yaml; print(yaml.__version__)` succeeds — YAML available for Python config / fixture loading |
| `pytest-cov installed in devel-test stage` | `pytest --help` mentions `--cov` — coverage plugin registered, enables `pytest --cov=<pkg>` invocations |

## test/bats/smoke/assert_pytest_baseline_hostxc_spec.bats (4)

Guard for isaac#460: the host-side cross-container leg of `assert_pytest_baseline.sh --gpu` must not be able to vanish silently behind the in-container count. A stub `run.sh` supplies the in-container report and a `python3` shim simulates the host pytest. Hermetic — no docker, no GPU.

| Test | Description |
|------|-------------|
| `assert_pytest_baseline --gpu fails when host python3 has no pytest (isaac#460)` | Host pytest absent: exits non-zero with the "no pytest" error (was a warning only). |
| `assert_pytest_baseline --gpu fails when the host leg produces no JUnit report (isaac#460)` | Host pytest ran but wrote no report: exits non-zero with "no JUnit report". |
| `assert_pytest_baseline --gpu fails when the host leg has zero passing tests (isaac#460)` | All host tests skipped: exits non-zero (host leg needs >= 1 pass). |
| `assert_pytest_baseline --gpu passes when the host leg runs and passes (isaac#460)` | Healthy host leg: exits 0 and prints the OK line. |

## test/bats/smoke/assert_pytest_baseline_isolation_spec.bats (2)

Behavioral guard for `test/assert_pytest_baseline.sh --gpu` (owv#55 second axis; first axis was isaac#239). The `--gpu` tier runs the integration suite via a foreground `script/run.sh -t test` whose EXIT trap `_app_cleanup` does a project-wide `compose down --remove-orphans`; left at the default `<user>-isaac` project that would reap a co-hosted manual stream stack. base v0.42.0 removed `--instance` (base#666); the tier now pins a distinct `PROJECT_NAME` in `.env.generated` (default `<derived>-baseline`, override `BASELINE_PROJECT`) before the `run.sh -t test` call. `assert_pytest_baseline.sh` is baked into `/smoke_test/` next to this spec so the devel-test bats suite can reach it. Hermetic — no docker, no GPU.

| Test | Description |
|------|-------------|
| `assert_pytest_baseline --gpu isolates the GPU pytest run in its own compose project (PROJECT_NAME, owv#55)` | Runs the script against a stub `run.sh` (records argv) + a fake `.env.generated`, and asserts the `-t test` invocation NO LONGER carries `--instance` and that the distinct `BASELINE_PROJECT` was written into `.env.generated` before `run.sh` fired — placing the GPU pytest tier in a non-default, isolated compose project so `_app_cleanup`'s project-wide teardown can never reap a co-hosted manual `stream` container. |
| `assert_pytest_baseline --gpu defaults the baseline project to <derived>-baseline when BASELINE_PROJECT is unset (owv#55)` | With the override unset, the pinned project defaults to a dedicated `<derived>-baseline` (`alice-isaac-baseline`, derived from the cache's own `PROJECT_NAME`), still distinct from the default project. |

## test/bats/smoke/checkout_identity_spec.bats (18)

Behavioral guard for `script/checkout_identity.sh` and the pre build/run/stop hooks (stopgap for base#1550 / base#1551). Every plain checkout used to resolve the same image tag (`<hub>/isaac:<stage>`) and compose project (`<hub>-isaac`), so base's build auto-prune deleted another checkout's image and `stop` / `run` removed another checkout's containers. `isolate` writes a per-checkout `[[image.rules]]` rule into base's gitignored `setup.local.toml`; the hooks refuse build/run/stop while a checkout is still on the shared identity. The script and the three pre hooks are baked into `/smoke_test/` (`checkout_identity.sh`, `pre_{build,run,stop}_hook.sh`). Hermetic -- no docker, no GPU.

| Test | Description |
|------|-------------|
| `checkout_identity: script is baked into the test stage` | `checkout_identity.sh` is present next to the spec. |
| `checkout_identity: slug is deterministic for one path` | The same checkout path always yields the same slug. |
| `checkout_identity: two checkouts with the same basename get different slugs` | `/a/isaac` and `/b/isaac` get different slugs, and neither is the shared `isaac`. |
| `checkout_identity: slug is a valid image name and compose project name` | Lowercase, alphanumeric edges, `isaac-` prefix, even for a path with spaces / capitals / underscores. |
| `checkout_identity: isolate writes a per-checkout image rule to setup.local.toml` | `isolate` writes `[[image.rules]]` / `rule = "string:<slug>"` and no `.setup.conf.local`. |
| `checkout_identity: isolate puts the slug rule first, so the resolved name is not the shared one` | The slug rule precedes the committed `string:isaac` rule. |
| `checkout_identity: isolate pins [project] name so run/stop leave the shared project at once` | `isolate` writes a per-checkout `[project] name`. |
| `checkout_identity: isolate keeps an operator-written [project] name` | An existing local `[project]` name is not overwritten. |
| `checkout_identity: isolate is idempotent and keeps other local sections` | Two runs leave one image rule and keep an existing `[network]` section. |
| `checkout_identity: isolate leaves an operator-written image rule alone` | An existing local `[[image.rules]]` rule is not overwritten. |
| `checkout_identity: isolate leaves an operator-written [image] table alone` | An existing local `[image]` table is not overwritten. |
| `guard: build refuses the shared isaac image tag` | `IMAGE_NAME=isaac` fails and names the tag and the `isolate` remedy. |
| `guard: build passes for a per-checkout image name` | A slugged `IMAGE_NAME` passes. |
| `guard: run and stop refuse the shared default project` | `PROJECT_NAME=<hub>-isaac` fails for both verbs. |
| `guard: run and stop pass for a pinned distinct project (CI) on the shared image` | CI's per-run `PROJECT_NAME` pin passes even with `IMAGE_NAME=isaac`. |
| `guard: ISAAC_ALLOW_SHARED_IDENTITY=1 bypasses with a warning` | The explicit opt-out passes and prints a `WARN`. |
| `guard: no .env.generated yet -> nothing to check, passes` | No resolved identity means nothing to refuse. |
| `pre hooks: build/run/stop refuse a shared checkout and pass an isolated one` | The real baked hooks exit non-zero on the shared identity and zero on an isolated one. |

## test/bats/smoke/gpu_job_scripts_spec.bats (11)

Behavioral guard for the self-hosted GPU job scripts (`script/ci/gpu_integration_job.sh`, `script/ci/stream_smoke_job.sh`). Both jobs run through the org reusable workflow `gpu-self-hosted.yml`, which owns the runner, the fork-PR gate, the pre-checkout workspace reclaim and the checkout, and then runs one repo script. This spec pins what those steps do: the order, the `WS_PATH` pin, which env reaches which command, the writable cache dirs, and that a failing step fails the job. Hermetic -- stub `setup.sh` / `build.sh` / `assert_pytest_baseline.sh`, no docker or GPU.

| Test | Description |
|------|-------------|
| `gpu integration job: apply, pin WS_PATH, build test, caches, gpu baseline -- in order` | The five steps fire in the expected order with the expected env. |
| `gpu integration job: works from any cwd (resolves the repo root itself)` | Invoked from `/`, the script resolves its own repo root. |
| `gpu integration job: a failed build fails the job before the GPU suite` | A build failure (`BUILD_RC=3`) exits non-zero and does not reach the baseline step. |
| `stream smoke job: apply, pin WS_PATH, build stream, caches, smoke -- in order` | The five steps fire in the expected order with the expected env. |
| `gpu_job_cache_dirs makes the workspace world-writable (rootless Docker)` | Creates a restricted-permission file and directory, runs the integration job, and asserts both are widened to include other-read-write (and execute for directories) by the `chmod -R a+rwX` at the end of `gpu_job_cache_dirs`. On a rootless Docker daemon the container's non-root user maps to a host subuid, so the mounted workspace must be world-writable. |
| `stream smoke job: a failed smoke fails the job and prints the full kit log` | A failing smoke exits with its status and prints the kit log. |
| `stream smoke job: a failed smoke with no kit log still fails with the smoke's status` | A failing smoke with no log file still exits with the smoke's exit code. |
| `gpu integration job: replaces existing cache dirs with links keyed by the BASE_IMAGE tag` | `isaac-sim/kit/cache` and `isaac-sim/nvidia/computecache` become symlinks into `<ISAAC_CI_CACHE_ROOT>/<BASE_IMAGE tag>/{kit-cache,computecache}`, outside the workspace; old workspace contents are dropped (isaac#260). |
| `gpu integration job: ISAAC_CI_CACHE_KEY overrides the BASE_IMAGE tag` | An explicit `ISAAC_CI_CACHE_KEY` selects the persistent cache directory instead of the Dockerfile tag. |
| `gpu integration job: both caches survive workspace cleanup between runs` | Files in the persistent cache dirs remain after the workspace `isaac-sim/` is wiped and the job runs again. |
| `gpu integration job: baseline sees writable mounts and state dirs stay in the workspace` | Mounts are writable when the baseline stub runs; state dirs (`kit/data`, `ov/*`, ...) stay real workspace dirs, not links, so state starts cold. |

## test/bats/smoke/cleanup_merged_worktree_spec.bats (14)

Behavioral guard for `script/git/cleanup-merged-worktree.sh` (#368). Hermetic: a throwaway repo (bare origin + clone + sibling `worktree/` dir) is built in `BATS_TEST_TMPDIR` and `gh` is a stub printing a canned `state<TAB>branch<TAB>oid` line. No docker, no network, no real worktree is touched.

| Test | Description |
|------|-------------|
| `cleanup: dirty worktree -> SKIP dirty, nothing removed` | A modified tracked file yields `SKIP dirty`; the worktree and branch remain. |
| `cleanup: untracked file also counts as dirty` | An untracked file also yields `SKIP dirty`. |
| `cleanup: unpushed commit -> SKIP unpushed, nothing removed` | A local commit beyond the PR `headRefOid` yields `SKIP unpushed`. |
| `cleanup: PR not merged -> SKIP not-merged, nothing removed` | An OPEN PR yields `SKIP not-merged`. |
| `cleanup: all checks pass -> worktree and branch removed, removed=1` | The worktree directory, its `git worktree list` entry and the local branch are gone; output carries `removed=1`. |
| `cleanup: root-owned files -> SKIP root-owned files + fix command, nothing else removed` | A `git worktree remove` that fails with "Permission denied" (stub) prints `SKIP root-owned files` and a `chown -R` fix command; worktree and branch remain. |
| `cleanup: --fix-owner runs chown once and retries removal` | The Docker stub receives the exact BusyBox chown arguments once, including the worktree mount and current UID:GID. The retry removes the worktree and branch and reports `removed=1`. |
| `cleanup: --fix-owner skips removal when docker fails` | A failed chown yields `SKIP fix-owner-failed` and exit 0. The worktree and branch remain. |
| `cleanup: --fix-owner reports remove-failed when the retry fails` | A second removal failure after chown yields `SKIP remove-failed:` and exit 0. The worktree remains. |
| `cleanup: permission denied without --fix-owner never invokes docker` | A permission error leaves the Docker call log absent. |
| `cleanup: --fix-owner skips docker when the first removal succeeds` | An ordinary successful removal prints `REMOVED` and leaves the Docker call log absent. |
| `cleanup: worktree outside the worktree root -> SKIP outside-worktree-root` | A worktree not under `<main>/../worktree` is left alone. |
| `cleanup: no PR number -> usage, exit 2` | Missing argument prints usage and exits 2. |
| `cleanup: --dry-run on an all-pass worktree prints WOULD-REMOVE and removes nothing` | `--dry-run` runs every check and prints `WOULD-REMOVE <path> (<branch>)`; worktree and branch remain. |

## test/bats/smoke/cleanup_merged_all_spec.bats (5)

Behavioral guard for `script/git/cleanup-merged-all.sh`, the script behind `just cleanup-merged` (#368). Hermetic: throwaway repo + bare origin, stub `gh` answering `pr list --head` and `pr view` from files.

| Test | Description |
|------|-------------|
| `cleanup-merged-all: removes merged worktrees, skips the rest, prints summary` | Merged+clean is removed; merged+dirty and OPEN are skipped; summary `removed=1 skipped=2`. |
| `cleanup-merged-all: --dry-run removes nothing and still prints the summary` | `WOULD-REMOVE` is printed, summary `removed=0 skipped=1`, worktree and branch remain. |
| `cleanup-merged-all: one worktree failing does not abort the batch` | A stub cleanup that exits 3 for one PR counts as skipped; the next worktree is still removed. |
| `cleanup-merged-all: a worktree with no merged PR is skipped, not an error` | No merged PR for the branch is a skip, exit 0. |
| `cleanup-merged-all: passes --fix-owner and the PR number to the cleanup script` | The per-PR stub receives `--fix-owner` followed by the merged PR number as separate arguments. |

## test/bats/smoke/merge_train_spec.bats (9)

Behavioral guard for `script/git/merge-train.sh` (#368). Hermetic: stub `gh` (canned `pr view` lines from a sequence file, `pr merge` recorded), no-op `sleep`, and a stub cleanup script that records its arguments.

| Test | Description |
|------|-------------|
| `merge-train: cleanup runs once with the PR number after its own merge` | After `PR1: MERGED` the cleanup script was called exactly once with `1`. |
| `merge-train: a PR already MERGED at start is not cleaned up` | A PR that is MERGED on first view triggers no merge call and no cleanup. |
| `merge-train: gh merge error but PR ends MERGED still triggers cleanup once` | A non-zero `gh pr merge` followed by a MERGED view still cleans up once. |
| `merge-train: cleanup SKIP does not change the exit code; each merged PR is cleaned` | Two PRs: exit 0 and both numbers passed to cleanup. |
| `merge-train: a failing required check stops with FAIL and no cleanup` | A FAILURE check exits 1 with `PR1: FAIL`, no cleanup. |
| `merge-train: merge method comes from the repo setting (squash allowed)` | `allow_squash_merge=true` leads to the squash flag in the `gh pr merge` call. |
| `merge-train: merge method falls back to a merge commit when squash is off` | `allow_squash_merge=false` leads to `--merge`, never the squash flag. |
| `merge-train: the script source never hard-codes the squash flag` | `grep -n -e "--squash" script/git/merge-train.sh` prints nothing. |
| `merge-train: the one required check is the summary job gate (isaac#434)` | `REQUIRED_CHECKS` is exactly `gate`; the two pre-#434 required-check names are gone. |

## test/bats/smoke/workflow_pin_spec.bats (4)

The Bats pin checks scan text and read the expected tag from `GPU_REUSABLE_TAG` in `test/unit/pytest/gpu_pin.py` (no hard-coded tag in the spec). The authoritative structural guard is `test_workflow_pins.py`, which parses each workflow's jobs.

Guard: every reusable-workflow reference to the org's `gpu-self-hosted.yml` must be pinned to a release tag, never `@main`. When `.github`'s main branch is broken, every isaac push/PR that reaches `gpu-integration` or `stream-smoke` fails with "workflow file issue" and 0 jobs (run 42776185240, 2026-11-10). The base `build-worker.yaml` and `release-worker.yaml` are already pinned (e.g. `@v0.42.0`); this spec covers `gpu-self-hosted.yml`. Hermetic -- greps (pin tests) or PyYAML-parses (isaac#344 tests) `.github/workflows/` files, no docker or network.

| Test | Description |
|------|-------------|
| `no workflow references gpu-self-hosted.yml@main` | Greps every workflow YAML under `.github/workflows/` and fails if any references `gpu-self-hosted.yml@main`. |
| `every gpu-self-hosted.yml caller uses the pinned tag` | main.yaml, ci-stream-smoke.yaml, ci-headless-smoke.yaml and publish-stream-source.yaml must each exist and reference `gpu-self-hosted.yml@<GPU_REUSABLE_TAG>`; any other `gpu-self-hosted.yml@` tag fails. The spec's `setup` fails when the workflows directory is absent (the devel-test image now bakes `.github/workflows/`). |
| `gpu-integration passes the run-scoped reap-container-filter` | Parses main.yaml with PyYAML (never greps) and asserts the `core-gpu` job uses `gpu-self-hosted.yml@<GPU_REUSABLE_TAG>` and its `with:` carries `reap-container-filter` equal to `label=com.docker.compose.project=isaac-baseline-${{ github.run_id }}-${{ github.run_attempt }}` (isaac#344). |
| `reap-container-filter names the BASELINE_PROJECT gpu_integration_job.sh runs` | Runs the real `gpu_integration_job.sh` against stubs with `GITHUB_RUN_ID=111 GITHUB_RUN_ATTEMPT=2`, captures the `BASELINE_PROJECT` it exports, renders the workflow filter with the same values and asserts they name the same compose project (isaac#344). |

## test/bats/smoke/run_bats_spec.bats (8)

`script/ci/run_bats.sh` (isaac#434): the devel-test stage runs its specs through it, and CI passes the groups a PR did not touch in `BATS_SKIP_GROUPS`. Builds a throwaway spec tree (core x2, stream, gui, one untagged) and counts what bats selects.

| Test | Description |
|------|-------------|
| `run_bats: no skip list selects every spec` | Unset `BATS_SKIP_GROUPS` selects all 5 tests. |
| `run_bats: an empty skip list selects every spec` | An empty value behaves as unset. |
| `run_bats: a skipped group's specs are not selected` | `stream` skipped leaves 4. |
| `run_bats: several skipped groups are all dropped` | `stream,gui` skipped leaves 3. |
| `run_bats: untagged (base-owned) specs always run` | Skipping every tagged group still runs the untagged spec (the shared layer is always checked). |
| `run_bats: whitespace around group names is ignored` | ` stream , gui ` is read as `stream,gui`. |
| `run_bats: an unknown group fails instead of silently skipping nothing` | Exit 2 naming the bad group on stderr. |
| `run_bats: it really runs the selected specs (exit status follows them)` | A failing gui spec fails the run, and passes once `gui` is skipped. |

## test/bats/smoke/assert_pytest_baseline_group_spec.bats (7)

`test/assert_pytest_baseline.sh --group <group>` (isaac#434): the per-scope hosted job. A stub `docker` records the container command, so the spec observes marker selection and coverage without docker.

| Test | Description |
|------|-------------|
| `assert_pytest_baseline --group: an unknown group exits 2 before any docker call` | Exit 2, the bad group named, no docker call. |
| `assert_pytest_baseline --group: a missing value exits 2` | `--group` with no value is a usage error. |
| `assert_pytest_baseline --group: cannot be combined with --gpu` | Exit 2, no docker call. |
| `assert_pytest_baseline --group stream: selects the group with -m and skips coverage` | The container runs `-m stream` with no `--cov`, and the group is checked against its own floor. |
| `assert_pytest_baseline --group core: keeps the framework coverage gate` | `--cov-fail-under=80` stays for `core`. |
| `assert_pytest_baseline --group stream: a group below its own floor fails` | A count under the floor exits 1 with `ratchet violation`. |
| `assert_pytest_baseline --group stream: only that group is counted` | The other groups' floors are not consulted. |

## test/unit/pytest/ — hosted unit (pytest, not in the bats count above)

The hosted suite collects **756 tests** on a host without Isaac Sim. CI runs `test/assert_pytest_baseline.sh` to enforce the per-group floors in `test/pytest-baseline.txt` and the 80% coverage floor for the framework’s pure Python code.

| File | Collected | Scope |
|------|:---------:|-------|
| `test_setup_isaac_sample.py` | 16 | `core`. Checks the documented TOML sample, model search path, read-only model mount, repo mounts after merging, absence of personal paths and URDF references, and sample references and no references to the unavailable `just run scene` recipe in all four READMEs (isaac#338). |
| `test_stage_names_docs.py` | 4 | `docs` (isaac#86). Checks the driver for `headless-stream` and the standalone livestream SOP and ZED installation guide for retired stage names, the `isaac-headless` container name and stale headless prose. Requires the SOP to include both `run -t stream -d` (start the idle container) and `exec -t stream /isaac-sim/runheadless.sh` (start Kit inside it). |
| `test_check_stale_naming.py` | 14 | `core`. Checks retired-name boundaries, path exclusions, and one allowed occurrence per phrase per line. Covers working-tree edits, file and line diagnostics, missing Git or checkout, and the move from Bats to a `core-unit` step after checkout (isaac#458). |
| `test_check_forbidden_names.py` | 14 | `core`. Checks case-insensitive matches, redaction in filenames and matched lines, tracked-file scope, the skip reason when the secret is unavailable, Git errors, and the current checkout. Verifies that CI passes the secret to the standalone scan and hosted core tests, and checks the core runner’s image, skip gate, and per-test reporting (isaac#487). |
| `test_import_safety.py` | 15 | Hosted import of each `isaac_devkit.*` module (incl. `__init__`) leaves `sys.modules` free of `omni` / `pxr` / `isaacsim` (ADR-0017 section 8 / PRD A1). |
| `test_no_module_top_isaac_import.py` | 18 | AST static guard: no module-top `import omni\|pxr\|isaacsim` in any package source (catches try/except-disguised module-top imports; mirrors the ruff TID253 config). |
| `test_output_mode.py` | 12 | `isaac_devkit.output_mode.resolve_output_mode` (isaac#366, #514): unset -> `python`; only `python` passes through; `ros`, `ROS`, `Python`, empty, `both`, leading / trailing space raise `ValueError` naming the offending value, `ISAAC_OUTPUT_MODE` and the allowed set; unrelated variables ignored; defaults to `os.environ`; constants. |
| `test_output_hub.py` | 17 | `isaac_devkit.output_hub.OutputHub` (isaac#365): delivery of the four kinds with the documented payloads (RGB uint8 `(H,W,3)` alpha dropped, depth float32 `(H,W)`, joint `names/positions/velocities/efforts`, IMU `lin_acc/ang_vel/orientation` w,x,y,z), `test_reader_not_called_without_consumer`, `test_reader_called_once_per_emit_with_consumer` (incl. unregister), shared copy for several consumers, `None` readings skipped, unknown kinds and malformed payloads raise `ValueError`. Fake sources only. |
| `test_output.py` | 8 | `isaac_devkit.output.setup_output` (isaac#365 / #366): spec defaults, python mode builds readers (monkeypatched), unset -> python, invalid mode raises, `step` / `unregister`, `ros` raises `ValueError`, `OutputModeError` hierarchy. |
| `test_stamp.py` | 4 | `isaac_devkit.stamp.split_stamp` (isaac#365, Bug 1 regression): `1.0 - 1e-10 -> (1, 0)` nanosecond carry, exact values, strictly increasing `(sec, nanosec)` pairs across second boundaries, `0 <= nanosec < 1e9` for seeded random times. |
| `test_buffers.py` | 7 | `isaac_devkit.buffers.to_u8_buffer` (isaac#365, Bug 2 regression): a float32 depth image is 4 bytes per pixel and equals `tobytes()`, uint8 RGB round-trips, returns `array.array('B')`, accepts stdlib buffers, and the non-contiguous contract (strided / Fortran-ordered input raises `ValueError`, `np.ascontiguousarray` input passes). Needs `numpy` (installed by `assert_pytest_baseline.sh`). |
| `test_no_ros_import_in_devkit.py` | 25 | AST static guard (ADR-0023): no module-top `rclpy` / `rosidl_*` / `builtin_interfaces` / `isaacsim.ros2` import in any `isaac_devkit` source (one case per file), plus 7 detector self-tests; the module list grows with each new `isaac_devkit` file. |
| `test_default_driver.py` | 8 | `isaac_devkit.default_driver.DefaultSceneDriver` (isaac#336 part 3): the driver a scene launch uses with no user driver. Pins that it is an `IsaacDriver` adding no `setup` / `main` / `shutdown` override, requires a scene path, `_open_stage` order (load scene -> new stage -> `build_scene`), the `run()` order with fake Kit (open stage, defaults, play timeline, tick `app.update()`, close), and Kit-free import. |
| `test_camera_setup.py` | 27 | Camera surface of `isaac_devkit.sensors` (former `camera_setup.py`): `validate_camera`, unified `load_config`, role -> Camera Helper type, FOV -> aperture math. |
| `test_sensor_setup.py` | 27 | `isaac_devkit.sensors` (former `sensor_setup.py`): YAML load, shared validation, category dispatch, per-category validation (lidar profile, IMU rigid-body rule), plus `_enable_extensions` through the `omni.kit.app` extension manager with `isaacsim.core.utils` unimportable and a static no-`isaacsim.core.utils`-import scan (isaac#248). |
| `test_sensor_prim.py` | 23 | `isaac_devkit.sensor_prim` (layer a, ADR-0024): config loading, shared/per-category validation, `ros:` section optional (loads without `ros:`, validates `ros:` when present), host-pure helpers (`fov_to_aperture`, `role_to_helper_type`), `get_category`. |
| `test_sensor_ros.py` | 7 | `isaac_devkit.sensor_ros` (layer c, ADR-0024): `build_graph_topology` (host-pure graph-spec builder with mocked `pxr.Sdf`), single/multi stream topology, resolution overrides, topic/frame_id naming, module interface check (`setup_sensor_publish`). |
| `test_sensors_dispatch.py` | 11 | `isaac_devkit.sensors` (layer b dispatcher, ADR-0024): backward-compatible re-exports (`load_config`, `get_category`, `validate_camera`), `setup_sensors` stub, `ros:` optional via backcompat path, `_enable_extensions` unchanged behaviour. |
| `test_material_setup.py` | 29 | `isaac_devkit.materials`: material YAML load / validate, variant enumeration, prim-material mapping, plus `material_cfg_from_yaml` (ADR-0018 decision 7) -- color-only variant -> per-prim spawn cfg-param mapping (`{prim: {shader, diffuse_color (r,g,b), ...}}`), JSON-serializable / GPU-free, the seam #152 attaches to `sim_utils` visual material. |
| `test_scene_builder.py` | 52 | `isaac_devkit.scene`: YAML load / validate, model-path resolution (incl. the `model/usd/`-prefixed transition shim, the `MODEL_PATH` env-var search path -- search order, second-root fallback, absolute-path bypass, missing-MODEL_PATH legacy fallback, error-lists-all-roots, and `package://` URI resolution -- resolved from MODEL_PATH, requires package.xml, searches multiple roots, error names the package), multi-instance generation, sensor-config reference resolution, plus the ADR-0018 (#152) pure `to_isaaclab_cfg` adapter -- `rpy_to_quat` (XYZ-intrinsic deg -> `(w,x,y,z)`), the ordered `SpawnSpec` list (ground / default + curated light / robot + object USD), curated-field translation, `mobility` (dynamic / static / None), `spawn_overrides` spread overrides-win, instance expansion flow-through, `variant` -> `variants` kwarg, optional material diffuse hook, JSON-serializability. |
| `test_no_urdf_import.py` | 6 | Enforces the USD-only boundary and verifies that the USD helpers remain importable. |
| `test_isaac_driver.py` | 57 | Tests both livestream helpers, USD resolution, boot extension ordering, Kit-free construction, and the `SCENE` class attribute. A fake `SimulationApp` records headless mode, streaming experience, and the boot arguments followed by whitespace-split `ISAAC_KIT_EXTRA_ARGS` in `extra_args`. The tests check caller `sys.argv` during and after construction, invalid livestream rejection before startup, signal registration and lifecycle order, traceback output before close, and `ISAAC_IO_PLUGIN` invocation and error handling before timeline play. `TestPlayTimeline` checks warm start callback preference, package fallback, and the warning when neither callback is available. It verifies all three settings (fixed time stepping, rate limiting enabled, and a 60 Hz limit) and the call order from disabling looping through setting the end time, starting playback, and running 10 warmup updates. |
| `test_prim_summary.py` | 3 | Checks the `PrimSummary` fields, link and joint classification from USD prim records, and empty-stage handling. |
| `test_ros_io.py` | 23 | Greenfield `isaac_devkit.ros_io` pure surface: `parse_ros2_io_config`, `expected_attr_paths`, `_build_graph_topology`, `RosIo.latest` non-blocking fresh-once bookkeeping against an injected reader. |
| `test_example_driver.py` | 14 | `example/sim/example_driver.py` pure surface (#131): three-file scene merge (`load_three_file_scene`), expected robot/`base_link` prim-path strings, `cmd_vel_to_planar_velocity` controller mapping, `SCENE` attr shape, the `run()` SCENE-driven lifecycle-order spy + injected-SIGINT shutdown, and example import-safety. |
| `test_stage_structure.py` | 4 | Parses the Dockerfile `FROM ... AS` lines and `setup.toml` (isaac#427): `devel` is `FROM devel-base`; `gui` / `stream` / `headless` are each `FROM devel`; the header `# Stages:` block lists every active stage; top-level `[gui] mode = "off"` with only `["stage:gui"] "gui.mode" = "auto"` (stream / headless / devel-test stay `off`). No docker/GPU. |
| `test_test_groups.py` | 25 | Test-group contract (isaac#434), `core`: every pytest module has exactly one `pytestmark` group (static AST check over `test/unit/pytest` and `test/integration/pytest`, with unmarked / two-group / unknown-group / function-level-marker detector self-tests on temp trees); every bats spec has exactly one `# bats file_tags=<group>` (non-group tags allowed, `test_tags` may not name a group) plus per-group bats counts; the collection-time plugin `test/group_markers.py` aborts a subprocess pytest run for an ungrouped or two-group test, accepts a grouped one, and `-m <other group>` collects nothing without an unknown-marker warning; the plugin and `script/ci/scope_groups.py` agree on the five groups; `test/pytest-baseline.txt` has a floor per group that sums to the total, the bats counts meet the `BATS_BASELINE_*` floors, and the 'Tests by group' table above matches the specs and the baseline. |
| `test_changed_groups.py` | 49 | `core`. Scope selection for CI (isaac#434), `script/ci/changed_groups.py`: push / dispatch / tag run every group; a PR runs the groups its paths belong to plus `docs`; docs-only paths touch only `docs`; a shared layer (Dockerfile, compose, `setup.toml`, config, `.base`, `main.yaml`, the CI scripts and baseline) runs all five; a test file follows the group it declares (not a path pattern); `ci-<group>-*` workflow files follow the group in their name; an unknown or deleted path is `core`, never nothing; dispatch group list validated; outputs (`build`, `stages`, `bats_skip`) per scenario; the CLI prints `$GITHUB_OUTPUT` lines and reads the PR diff with `git diff --name-only base...head` (stub `git`). Each stream smoke input must select `stream` on its own, with the shared entrypoint and pre-hooks selecting all five groups (isaac#459). A merge group selects all five groups and the CLI enables every flag without PR SHAs (isaac#453). |
| `test_ci_gate.py` | 9 | `core`. The required-check summary job (isaac#434), `script/ci/gate_result.py`: success and skipped jobs pass; failure or cancelled fails; `changes` not succeeding fails even when everything else is skipped (nothing was checked); empty needs fails; CLI exit codes 0 / 1 / 2. |
| `test_main_workflow_scope.py` | 21 | `core`. Structure of `main.yaml` after the split (isaac#434): exact job set; no `paths:` filter on any trigger and no `schedule`; PR / main / tag / dispatch triggers; `gate` needs every other job and runs `always()` and calls `gate_result.py` with `toJSON(needs)`; each scoped job needs `changes` and checks its own flag; `docs-unit` has no condition; `core-gpu` keeps the fork guard and needs `core-unit`; `stream-smoke` (stream group, isaac#434 PR3) calls `./.github/workflows/ci-stream-smoke.yaml`, needs `stream-unit` and has the same fork guard; `core-build` receives `stages` and `BATS_SKIP_GROUPS`; `release` waits for `gate`. The merge queue requests checks, and the job conditions admit every job through `gate` while reserving `release` for tags (isaac#453). |
| `test_workflow_naming.py` | 42 | `core`. Workflow naming rule and lint (isaac#443), `script/ci/lint_workflow_names.py` + `doc/workflow-naming.md`: the real `.github/workflows/` follows the rule (and the glob finds `main.yaml` and `ci-stream-smoke.yaml`, no vacuous pass; the pre-rename stream smoke file is gone); detector self-tests on temp trees for bad file names (`.yml`, no category, uppercase, underscores), bad display names (parenthesised note, wrong case, wrong category), non-kebab job ids, a CI job with no group prefix, job-level `name:`; the allowed CI ids (`changes` / `gate` / `release` / `<group>-...`) and a bot job needing only kebab-case; exemptions are by exact file name and each carries a reason; `main.yaml` is exempt from file and display name but not from the job rule; base's `init.sh` still generates `base-version-monitor.yaml` under that name and only creates it when absent (the reason it keeps its name); the doc lists every category, group and exemption; retired names (`RETIRED_NAMES` in the lint: the old job ids, the old stream smoke file name and display name) are reported in docs while the new file name and history (changelog, ADRs) are not. |
| `test_workflow_triggers.py` | 4 | `core`. No nightly run (isaac#434 PR3): only `base-version-monitor.yaml` (an upstream-release bot that runs no tests) may have a `schedule`; the glob must find workflows (no vacuous pass); `ci-stream-smoke.yaml` has no `schedule` but keeps `workflow_dispatch` and is callable (`workflow_call`) from `main.yaml`; it still runs `script/ci/stream_smoke_job.sh` through the pinned org `gpu-self-hosted.yml` with the 30 minute budget. |
| `test_workflow_pins.py` | 3 pin + 2 reap | Three guards cover the GPU workflow pin (isaac#402, isaac#405). The workflow jobs and the Dependabot comment must match `GPU_REUSABLE_TAG` in `gpu_pin.py`, the single source of truth for pytest. The expected callers are `main.yaml`, `ci-stream-smoke.yaml`, `ci-headless-smoke.yaml`, and `publish-stream-source.yaml`. A mismatch lists missing and extra callers and directs maintainers to update `_EXPECTED_CALLERS` and this row. Two tests cover the run-scoped reap filter (isaac#344). |
| `test_readme_cleanup_text.py` | 4 | `docs`. One case per README language (isaac#381) checks the inline force-removal warning, the compose project label lookup, the nominal per-tag size and when shared layers can be reclaimed. |
| `test_stream_source_producer.py` | 19 | Hosted import/CLI-contract for the deterministic WebRTC stream-source producer driver `src/script/stream_source_producer.py` (isaac#223 / owv#48 / isaac#173): the module imports on a non-Isaac host without pulling `omni`/`pxr`/`isaacsim`/`carb` into `sys.modules` (every Isaac import function-local), the argparse surface exposes `--public-ip`/`--port`/`--run-seconds`, `--public-ip`/`--port` default from the `PUBLIC_IP`/`ISAAC_SIGNAL_PORT` env vars (the `docker run -e` container contract) with an explicit flag overriding the env, and `python stream_source_producer.py --help` exits 0 on a bare host (argparse exits before any Isaac import). Loads the driver by file path; no docker/GPU. |
| `test_xc_compose_project_isolation.py` | 4 | Hosted guard for the isaac-side root cause of `ycpss91255-lab/omniverse_web_viewer#55`: the cross-container round-trip's default `COMPOSE_PROJECT` is the dedicated `xc-isaac-roundtrip` (not the `${DOCKER_HUB_USER}-${IMAGE_NAME}` stream-stack project, e.g. `<user>-isaac`), so its project-level teardown can never reach a co-hosted manual `stream` container; asserts the dedicated literal, the isolation intent (distinct from any `${user}-${image}` derivation, which would still coincide), and that the `XC_COMPOSE_PROJECT` env override still wins. Loads the integration module by file path with env cleaned -- pure, no docker/GPU. |
| `test_xc_roundtrip_asset_migration.py` | 4 | Hosted guard for the cross-container round-trip migration onto the official Jetbot asset (isaac#325): expected camera topic / frame_id are `/jetbot/camera/color/image_raw` / `jetbot_camera_color_optical_frame`; the ament `camera_subscriber` sibling is pointed at that topic via its `camera_topic` parameter (no ament package change); the test module fetches the USD through `fetch_test_asset("jetbot")`; the Isaac runner takes `--robot-usd` and no longer imports `example_driver` or references camera_bot. Reads the real module + runner source; no docker, GPU or network. |
| ~~`test_render_settings.py`~~ | ~~13~~ | Moved to `ycpss91255-lab/isaac_physics_test` with `viz_render.py` (isaac#309). The converged-render recipe `_capture_noise_runner.py` used is now inlined there. |
| `test_sim_version.py` | 10 | `isaac_devkit.sim_version.isaac_sim_version` (isaac#295): the Isaac Sim release read from `/isaac-sim/VERSION` (`6.2.0-rc.15+...` -> `6.2.0`, `6.0.1-rc.7+...` -> `6.0.1`, a bare `5.1.0`), `unknown` for an absent or empty file, the default path; plus a structural scan over `src/script/*.py` and `test/verify_*.py` that no script writes `isaac_variant` as a literal; the scan fails when either glob matches nothing, so it cannot pass vacuously (isaac#360). Pure -- tmp trees (each glob empty on its own, planted literal reported) and source reads. |
| `test_adr_drop_isaac_lab.py` | 4 | ADR-0026 (isaac#476), `docs`. Checks the superseded ADR and repository names in the decision, the status in ADR-0018, URDF import ownership in ADR-0020, and the reference in ADR-0017's Isaac Lab amendment. |
| `test_readme_multi_instance.py` | 24 | `docs`. Six checks per README across four languages (isaac#289) cover section placement, the ADR-0019 and multi_run#15 links, per-instance cache, memory and project guidance, headless ports, and the absence of personal identifiers. |
| `test_no_ai_attribution.py` | 30 | PR commit checks (isaac#413, isaac#414). Clean commits, ordinary mentions, and human co-author names containing Claude pass. Model names and versions, anthropic.com co-author, author, or committer addresses, generation notices (including Markdown links), and session trailers flag the offending commit SHAs. Coverage includes indentation, mixed case, and versions written without a space (`Claude Sonnet4.5`, `Claude Opus4`, and `Claude-3`). With a stubbed git log, an empty range succeeds and an invalid range reports an error with exit code 2. Omitting both the range and `--stdin` is a usage error. |
| `test_model_readme_layout.py` | 11 | `docs`. Checks the five moved model paths, the removal of their old paths, the sim_asset README citation (isaac#363). |
| `test_standalone_scripts.py` | 18 | The README-listed standalone drivers (`src/script/{ros2_test_pub,ros2_test_sub}_standalone.py`), from a README-only onboarding run on 6.2.0. Pins the pure helper `src/script/standalone_common.py`: `kit_config` follows `ISAAC_LIVESTREAM`, `PeriodicTimer` fires once per wall-clock period whatever the Kit update rate and does not burst after a stall, and `run_and_exit` turns an exception into exit code 1 and passes a return code through. The helper exposes no OpenBase path or stage setup functions, wheel names, or base-link constant (isaac#358). Each script has no `omni.isaac.dynamic_control` import (removed in 6.x), no hard-coded `/home/<user>`, no module-top Isaac import or `SimulationApp(...)` (a module-top failure bypassed every handler and exited 0), and a `__main__` block that goes through `run_and_exit`. `ros2_test_pub` publishes on a `PeriodicTimer` instead of every 60 ticks (measured 3.5-7.5 Hz against a claimed ~1 Hz). The `move_openbase_planar` / `cmd_vel_planar` standalone scripts and their guards moved to `ycpss91255-lab/isaac_physics_test` (isaac#342). Pure -- AST parses, file reads, and a fake clock. |
| `test_repo_config.py` | 3 | Repo-level config found by onboarding. `.dockerignore` keeps the host Isaac Sim cache tree `isaac-sim/` out of the build context; Kit creates `isaac-sim/documents/Kit/shared/screenshots` with mode 000, which made `just docker build` fail with `permission denied` after the first launch. `setup.toml` `[deploy]` uses `gpu_runtime`, not the deprecated `runtime` that base warns about on every setup. The Dockerfile pre-creates `/isaac-sim/extsUser`: the experience file lists it as an extension folder, the NGC image does not ship it, and the non-root user cannot create it, so Kit scanned `~/work` instead and warned `Extensions config 'extension.toml' doesn't exist` once per top-level directory. Pure file reads. |
| `test_test_assets.py` | 12 | Official Isaac test-asset fetch helper (`test/test_assets.py`, #324). Pins the NVIDIA Jetbot USD URL on the Omniverse S3 bucket with a version segment and SHA-256 digest; cache-hit path returns without calling `_download`; cache-miss path calls `_download`; the return value is a `Path`; an empty cache with a simulated `ConnectionError` raises `RuntimeError` naming the asset; an unknown asset name raises `KeyError`. #325 adds the pinned `nvidia_cube` entry (URL on the same bucket/version, SHA-256) and a structural guard that `test_build_scene_adapter.py` / `_build_scene_runner.py` no longer reference `example_driver` / `example/sim` and use `fetch_test_asset`. Pure -- mocked HTTP, filesystem only. |
| `test_headless_smoke_wiring.py` | 6 | Checks the headless smoke workflow, its CI scope and the scripts installed in the image. |
| `test_producer_versions.py` | 6 | Checks the generated producer-version tables in the four READMEs. |

## test/integration/pytest/ — GPU integration (pytest, not in the bats count above)

The GPU suite collects **35 tests**. CI runs 33 inside the Isaac test container and two cross-container round-trip tests on the host. `test/assert_pytest_baseline.sh --gpu` checks that both legs ran and enforces the combined collection floor.

| Test | Description |
|------|-------------|
| `test_camera_ros2_headless.py::test_camera_custom_yaml_publishes_frame_headless` | M0 gate (#127): headless Isaac boots (CUDA probe + Kit-log Vulkan/CUDA markers), `custom.yaml` camera publish chain builds via `camera_setup.setup_camera`, and >= 1 `sensor_msgs/Image` arrives on `/forklift/camera/color/image_raw` with `frame_id=forklift_camera_color_optical_frame`. Pass criterion = `[BOOT OK]` / `[CAMERA FRAME OK]` / `[EXIT CLEAN]` marker lines (Kit `_exit(0)`s, return code is meaningless). The runner sets `BOOT_EXTENSIONS = ()`, so the ROS 2 bridge is enabled at runtime by `setup_camera` after headless `SimulationApp` startup -- the isaac#248 regression path. |
| `test_example_gpu_integration.py` (8) | M2 gate (#132), re-proven on the Isaac Lab backend (#154): boots a headless scene -- now the official NVIDIA Jetbot USD fetched via `test/test_assets.py` (#325, replacing the `example/sim/` camera_bot), spawned through the framework Isaac Lab adapter (#154) -- and makes the strong L1-L4 + `cmd_vel` assertions on the live scene. `test_l4_boot_and_clean_exit_markers` (`[BOOT OK]` + `[EXIT CLEAN]`, nothing raised); `test_cuda_and_vulkan_init` (libcuda device count + Kit-log CUDA/Vulkan markers); `test_l1_base_link_valid_and_rigidbody` (`/World/Robot/chassis` IsValid + `RigidBodyAPI`; the Jetbot has no `base_link`); `test_l1_link_and_joint_counts` (live Jetbot = 3 links / 2 joints / root `/jetbot`, from pxr inspection of the pinned asset); `test_l3_camera_topic_frame_and_message` (topic + `frame_id` + >= 1 `sensor_msgs/Image`); `test_ros_io_latest_none_before_publish` (non-blocking None); `test_cmd_vel_round_trip` (in-process Twist `vx=0.42 wz=0.21` echoes through `io.latest()`); `test_l4_injected_sigint_runs_shutdown` (live SIGINT -> `shutdown()`). Marker-line acceptance (Kit `_exit(0)`); headless; timeout = boot budget x 1.5 (600 s); retry <= 1, logged. Runner `_example_headless_runner.py` (takes `--robot-usd`; builds its scene in memory, no `example/sim/` files). The genuine cross-container round-trip lives in `test_cross_container_roundtrip.py` (below). |
| `test_joint_drive_integration.py` (1) | Creates a revolute USD joint, applies a runtime drive and reads the angular stiffness and damping back from its DriveAPI. |
| `test_output_hub_gpu.py` (4) | OutputHub delivery (isaac#365): one runner boot (`_output_hub_runner.py`, official Jetbot) builds python-mode output with an RGB and a depth camera, joint state and an IMU prim, steps 300 ticks and the four tests assert RGB uint8 `480x640x3`, depth float32 `480x640`, joint names present, IMU orientation length 4. Marker-line acceptance. NOT run locally; first run is CI `gpu-integration`. |
| `test_kit_extra_args_integration.py` (2) | `ISAAC_KIT_EXTRA_ARGS` (isaac#422): `_kit_extra_args_runner.py` boots a minimal `IsaacDriver` and reads `/app/isaac_test/marker` back through carb settings. With `ISAAC_KIT_EXTRA_ARGS=--/app/isaac_test/marker=1` the value is `1`; without the variable the setting is absent (control). First proof is the CI GPU job. |
| `test_io_plugin_integration.py` (2) | `ISAAC_IO_PLUGIN` (isaac#423): `_io_plugin_runner.py` boots a minimal `IsaacDriver` (no boot extensions) on the official Jetbot asset (`fetch_test_asset`). With `ISAAC_IO_PLUGIN=_io_plugin_marker:make_marker` the fake plugin's marker prim exists once the timeline is playing; without it the marker is absent and `sys.modules` holds no `rclpy` / `isaacsim.ros2*` module. First proof is the CI GPU job. |
| `test_cross_container_roundtrip.py` (2) | M2 gate (#132, PRD Pre-Publish item 1): the genuine Isaac<->ament cross-container ROS 2 round-trip, host-orchestrated against a sibling `ros:humble` container running the `example/ros2/` ament nodes (the proven #127/#131 `docker run --rm ros:humble` + `ROS_DOMAIN_ID` / `fastdds.xml` pattern on the host network). `test_sim_to_ament_camera_received` (sim -> ament: the ament `example_app_py camera_subscriber` node receives a real sim frame from the official Jetbot asset (#325, replacing camera_bot), `[FRAME OK] ... frame_id=jetbot_camera_color_optical_frame`, topic `/jetbot/camera/color/image_raw` passed via `-p camera_topic:=`); `test_ament_to_sim_cmd_vel_received` (ament -> sim: the ament `cmd_vel_publisher` node's Twist `vx=0.37 wz=0.19` crosses the boundary and the Isaac `RosIo.latest('/cmd_vel')` picks it up, `[XC CMD_VEL RX]`). Isaac side = `_cross_container_runner.py` (takes `--robot-usd`, builds its scene in memory; underscore-prefixed, not collected); it publishes NOTHING on `/cmd_vel` so every command observed crossed the container boundary. Because it spawns sibling containers it runs on the GPU HOST (not inside the Isaac container) -- `assert_pytest_baseline.sh --gpu` runs it as a host leg and sums it into the GPU totals. Skipped (not failed) without docker / the built `isaac:test` image; a skip does not advance the `passed > 0` gate. Marker-line acceptance; headless; retry <= 1, logged. Proven on the RTX 5090. |
| `test_build_scene_adapter.py` (4) | MR gate (#152, ADR-0018 decisions 1/3), assertions strengthened (#154); since #325 the scene is built in the runner around the official Jetbot (robot, `/World/Robot/chassis` replaces `base_link`) and NVIDIA cube (`mobility: dynamic`) USDs fetched via `test/test_assets.py` (runner takes `--robot-usd` / `--object-usd`), no `example/sim/` assets; NOT yet run on the GPU runner. Originally: the example scene spawned via the framework `build_scene` adapter (`to_isaaclab_cfg` -> `sim_utils` cfg -> `cfg.func()`). A module-scoped fixture runs `_build_scene_runner.py` once (one `SimulationApp`) and shares its marker stdout. `test_adapter_runner_clean_exit` (`[EXIT CLEAN]`, no `[RAISED]`, returncode 0); `test_adapter_spawns_ground_light_robot` (`[ADAPTER OK] ground=True light=True robot=True objects>=1` -- environment ground (a procedural collision cuboid, NOT the nucleus `GroundPlaneCfg`) + light + robot USD authored on the live stage -- AND, strengthened in #154, `[ADAPTER BASE_LINK] valid=True`: `/World/Robot/base_link` now resolves through the adapter reference + the fb6f580 `defaultPrim`); `test_adapter_spawns_mobility_dynamic_object` (a `mobility: dynamic` object materializes a `UsdFileCfg` with `rigid_props`/`mass_props`/`collision_props`, `cfg.func` spawns it, AND -- strengthened in #154 -- carries `rigidbody=True`, the `UsdPhysics.RigidBodyAPI` now landing on resolved referenced content). Both strengthenings were reported-not-asserted before fb6f580 added the `defaultPrim` to the committed `camera_bot.usd` / `prop_cube.usda`. Collected count unchanged (the base_link assertion is folded into the ground/light/robot test). Marker-line acceptance; headless; runner `_build_scene_runner.py` (underscore-prefixed, not collected). |
| `test_capture_noise.py` (3) | Capture-speckle fix (isaac#266): one Kit boot (`_capture_noise_runner.py`) builds a lit room and captures it TWICE through the SAME render product -- once as replicator creates it, once after `apply_converged_render_settings` (inlined from the former `viz_render` module, now in `ycpss91255-lab/isaac_physics_test`) authors the recipe on the RenderProduct prim. Asserts the default leg is CLEAN, i.e. NGX-denoised (isaac#294: since #285 set `gpu_capabilities = all` the container gets the `ngx` capability, so the old "default must still be noisy" guard was inverted -- a default leg back near 53 now means NGX dropped out again), that the mode reads back as `PathTracing` off the live prim (a carb `/rtx/rendermode` write reads back unchanged, so this is what separates "applied" from "attempted"), and that the converged frame is clean (absolute ceiling, no relative-to-default check since both legs are now clean) with no fully black pixels. The metric is neighbouring-pixel mean absolute difference, NOT frame `std`: `std` is dominated by scene contrast, which is why every failed hypothesis in the issue "left std unchanged" and looked equally inert. Reference on the RTX 5090: pre-#285 default 53.0 vs converged 2.1; post-#285 default ~0.41 vs converged ~1.53 (CI run 34233956492). |
| `test_driver_joint_motion.py` (2) | The #447 regression runs `IsaacDriver` on the official Jetbot with PhysX and Newton. Each case checks the active engine and requires both wheels to move more than one radian in the commanded direction. |
| `test_isaac_driver_integration.py` (1) | Exercises the driver lifecycle in Kit. |
| `test_sensor_setup_integration.py` (5) | Checks sensor setup against a live USD stage. |

## example/ros2/ — app-side ament package tests (colcon test, not in the counts above)

The app-side ROS 2 templates (#133, `example/ros2/src/`) carry their own tests, run by `colcon test` inside a hosted `ros:humble` container (`docker run --rm`, no Isaac / no GPU per the PRD compatibility matrix ament row). They are NOT counted in the bats header total (the drift check counts `^@test` lines only) and are NOT part of the framework hosted-unit pytest baseline (`test/assert_pytest_baseline.sh` collects only `test/unit/pytest/`). Run: `docker run --rm -v "$PWD/example/ros2":/ws -w /ws ros:humble bash -c 'source /opt/ros/humble/setup.bash && colcon build && colcon test && colcon test-result --all'`.

| Test | Package | Description |
|------|---------|-------------|
| `test_copyright.py` | `example_app_py` | `ament_copyright`: every source file carries an accepted licence header. |
| `test_flake8.py` | `example_app_py` | `ament_flake8`: source is flake8-clean. |
| `test_pep257.py` | `example_app_py` | `ament_pep257`: docstrings follow the ament PEP 257 convention. |
| `test_helpers.py` | `example_app_py` | Pure-helper unit tests (no ROS context): default topics match the example, `describe_image` summary fields, `make_twist` sets only the planar components. |
| `ament_lint_common` suite | `example_app_cpp` | `copyright` / `cpplint` / `uncrustify` / `lint_cmake` / `xmllint` / `cppcheck` (cppcheck skips when the optional tool is absent) over the C++ nodes + `CMakeLists.txt` + `package.xml`. |

