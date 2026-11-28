# TEST.md

**233 tests** total (bats). Hosted pytest collects **987 tests**.

## Tests by group (isaac#434)

CI runs per scope, so every test belongs to exactly one group: core (framework, shared Docker layers, shared scripts, CI tooling), gui, stream, headless, docs. A pytest module declares its group with a module-level `pytestmark = pytest.mark.<group>` (select with `pytest -m <group>`); a bats spec with `# bats file_tags=<group>` (select with `bats --filter-tags <group>`). A test with no group fails collection (`test/group_markers.py`) and the static check (`script/ci/scope_groups.py check`, pinned by `test_test_groups.py`). Floors per group are in `test/pytest-baseline.txt`; `test_test_groups.py` pins this table to the specs and to the baseline file.

| Group | bats | pytest hosted | pytest GPU | Total |
|-------|-----:|--------------:|-----------:|------:|
| core | 129 | 839 | 36 | 1004 |
| gui | 0 | 0 | 0 | 0 |
| stream | 91 | 55 | 0 | 146 |
| headless | 13 | 6 | 0 | 19 |
| docs | 0 | 87 | 0 | 87 |

The total above counts Bats tests. The GUI configuration and PR policy checks (#428) run in `core` and read repository files. The `gui` group has no runtime tests. The `headless` group has the boot check (#461). The GPU integration tests run in `core` because they boot Isaac on the shared `devel` layer.

## Framework purity (#137)

Core CI runs `bash script/ci/check_framework_purity.sh` before hosted pytest.
It scans `framework/isaac_devkit/*.py` and `framework/pyproject.toml` for
case-insensitive matches of `forklift|coresam|pallet|pushback|openbase`.
Matches and scan errors fail the check. Runnable applications in `src/` and
ADR pointers sit outside the scope. Nine core tests cover the current checkout,
all five terms, scope exclusions, scan errors and CI wiring.

## Official Isaac Sim Python buckets (#440)

The scoped `core-gpu` job runs the official `asset` (17 scripts) and `deprecated` (2 scripts)
buckets in order after the startup tests. Core PR changes select the job. Pushes to main,
release tags, and default manual dispatch select all groups. The `official-tests` artifact
contains startup reports and a separate JUnit XML per Python bucket. Both buckets are
attempted even if the first fails. Each reports its script pass rate and summed execution time.
The failure allowlist is empty.

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

## test/bats/smoke/post_run_hook_spec.bats (19)

Post-run hook (`script/hooks/post/run.sh`, base #440): on `run.sh -t stream -d`, copies host.yaml into the Isaac container and starts the per-project `${USER_NAME}-${IMAGE_NAME}-owv<suffix>` web-viewer (#237, isaac#238). The WebRTC livestream ports are sourced from `host.yaml` (#231), not hardcoded. base v0.42.0 removed `--instance` / `INSTANCE_SUFFIX` (base#666); the viewer suffix is now derived from the resolved `PROJECT_NAME` (empty when it equals the default `${DOCKER_HUB_USER}-${IMAGE_NAME}` -> byte-identical to today's names, `-<remainder>` for any distinct project; owv#55). A distinct `PROJECT_NAME` is the internal isolation seam for CI/tooling (a distinct compose project + per-project viewer name, so a CI actor never reaps a co-hosted manual stack), not a return of user-facing same-repo multi-instance, which ADR-0019 removed as a feature. The Isaac stream container name is base-fixed by `compose.yaml` `container_name` (no suffix; residual co-host collision filed as base#920), so the `docker cp` target is that fixed name. Exercised via `POST_RUN_DRYRUN=1`.

| Test | Description |
|------|-------------|
| `post-run: non-stream target is a no-op` | A non-`stream` target produces no actions. |
| `post-run: stream without -d is a no-op` | The stream stage without `-d/--detach` produces no actions. |
| `post-run: stream + -d is a no-op with ISAAC_SKIP_STREAM_POST_RUN=1` | The hook exits 0 with empty stdout and stderr. |
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

## test/bats/smoke/docker_env.bats (4)

| Test | Description |
|------|-------------|
| `entrypoint.sh is installed and executable` | Entrypoint check |
| `bash is available on PATH` | Shell sanity |
| `NVIDIA's full streaming Kit experience is present and readable` | Checks that the image user can read the bundled `/isaac-sim/apps/isaacsim.exp.full.streaming.kit`. |
| `devel stage drops the NGC Kit healthcheck (idle containers are not 'unhealthy')` | The NGC base image's HEALTHCHECK greps a Kit log for `App is loaded`. devel / headless / stream / test idle with no Kit by design, so the devel stage (inherited by the others) resets it with `HEALTHCHECK NONE`. |

## test/bats/smoke/isaac_smoke.bats (9)

| Test | Description |
|------|-------------|
| `isaac-sim launchers exist and are executable` | `/isaac-sim/runheadless.sh` and `/isaac-sim/runapp.sh` both `0755` |
| `isaac-sim ships Python 3.12 in /isaac-sim/kit/python/bin/python3` | Isolated Python interpreter exists and reports `3.12` |
| `runtime user is host-aligned (not root, not isaac-sim default)` | Container user is the host-UID-aligned `USER_NAME`, not the image default `isaac-sim` (UID 1234) |
| `runtime user is in isaac-sim group (can read /isaac-sim/* mode 0750)` | Group membership unlocks read/exec on Isaac Sim binaries |
| `HOME is writable` | `${HOME}` is owned by the runtime user — required for cache / logs / Documents writes |
| `bundled ROS 2 humble + jazzy libs are both readable` | `librmw_fastrtps_cpp.so` present under both `humble/lib/` and `jazzy/lib/` in the official base image |
| `bundled ROS 2 humble + jazzy rclpy are both readable (Python 3.12)` | `rclpy/` Python bindings present under both distros; kit-side `import rclpy` resolves to whichever the bridge extension activates |
| `optional training and URDF packages are absent from standalone Sim Python` | Each package import raises a top-level `ModuleNotFoundError` in the NVIDIA Python launcher (isaac#480). |
| `no pip_prebundle package lost its __init__.py (isaac#288)` | No dangling `__init__.py` symlink under any `pip_prebundle` -- the 6.0.1 build left `packaging` dangling under `omni.services.pip_archive`, breaking matplotlib plots and the Newton experience |

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

## test/bats/smoke/assert_pytest_baseline_isolation_spec.bats (2)

Behavioral guard for `test/assert_pytest_baseline.sh --gpu` (owv#55 second axis; first axis was isaac#239). The `--gpu` tier runs the integration suite via a foreground `script/run.sh -t test` whose EXIT trap `_app_cleanup` does a project-wide `compose down --remove-orphans`; left at the default `<user>-isaac` project that would reap a co-hosted manual stream stack. base v0.42.0 removed `--instance` (base#666); the tier now pins a distinct `PROJECT_NAME` in `.env.generated` (default `<derived>-baseline`, override `BASELINE_PROJECT`) before the `run.sh -t test` call. `assert_pytest_baseline.sh` is baked into `/smoke_test/` next to this spec so the devel-test bats suite can reach it. Hermetic — no docker, no GPU.

| Test | Description |
|------|-------------|
| `assert_pytest_baseline --gpu isolates the GPU pytest run in its own compose project (PROJECT_NAME, owv#55)` | Runs the script against a stub `run.sh` (records argv) + a fake `.env.generated`, and asserts the `-t test` invocation NO LONGER carries `--instance` and that the distinct `BASELINE_PROJECT` was written into `.env.generated` before `run.sh` fired — placing the GPU pytest tier in a non-default, isolated compose project so `_app_cleanup`'s project-wide teardown can never reap a co-hosted manual `stream` container. |
| `assert_pytest_baseline --gpu defaults the baseline project to <derived>-baseline when BASELINE_PROJECT is unset (owv#55)` | With the override unset, the pinned project defaults to a dedicated `<derived>-baseline` (`alice-isaac-baseline`, derived from the cache's own `PROJECT_NAME`), still distinct from the default project. |

## test/bats/smoke/assert_pytest_baseline_gpu_spec.bats (4)

A stub container runner supplies the JUnit report to `test/assert_pytest_baseline.sh --gpu`.

| Test | Description |
|------|-------------|
| `GPU baseline requires a container JUnit report` | Fails when the runner exits without writing a report. |
| `GPU baseline requires at least one passing test` | Rejects a report where all collected tests were skipped. |
| `GPU baseline enforces the in-container collection floor` | Rejects a passing suite whose collection count is below the GPU floor. |
| `GPU baseline counts the container report once in the aggregate` | Checks the pass count and the sum of hosted and GPU counts for a partially skipped suite. |

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

## test/bats/smoke/gpu_job_scripts_spec.bats (16)

Behavioral guard for the self-hosted GPU job scripts (`script/ci/gpu_integration_job.sh`, `script/ci/stream_smoke_job.sh`). Both jobs run through the org reusable workflow `gpu-self-hosted.yml`, which owns the runner, the fork-PR gate, the pre-checkout workspace reclaim and the checkout, and then runs one repo script. This spec pins what those steps do: the order, the `WS_PATH` pin, which env reaches which command, the writable cache dirs, and that a failing step fails the job. The Docker stub executes the mounted startup script with a temporary home directory. Its fixture `run_tests.py` writes JUnit to `/tmp/r.xml` and a Kit log under `$HOME/.nvidia-omniverse/logs/Kit/Isaac-Sim Streaming (Newton)/6.2/`. The spec runs without Docker or a GPU.

| Test | Description |
|------|-------------|
| `gpu integration job: apply, pin WS_PATH, build test, caches, gpu baseline, official startuptests -- in order` | The job runs startup tests after the GPU baseline, then runs the Python buckets. A baseline failure stops the job before both suites. |
| `gpu integration job: successful startuptests retain JUnit and the Kit log` | Checks the passing JUnit report in `artifacts/startuptests/r.xml` and the Kit log under `kit-logs/` with its app and version directories preserved. |
| `gpu integration job: failed startuptests fail the job and retain JUnit and the Kit log` | Checks that the job returns the fixture's exit code 23 and retains both the failing JUnit report and that run's Kit log. |
| `gpu integration job: JUnit failure fails the job even when run_tests.py exits zero` | A single `<testsuite>` reports one failure for `tests-startup.main.sh` with the message `Exit code: 55`. The job fails and retains the report and Kit log. |
| `gpu integration job: an error inside testsuites fails the job even when run_tests.py exits zero` | A suite inside `<testsuites>` reports one error and zero failures. The job fails and retains the report and Kit log. |
| `gpu integration job: a truncated JUnit report fails the job even when run_tests.py exits zero` | The report is missing its closing tag. The job fails and retains the truncated XML and Kit log. |
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

## test/bats/smoke/gui_stage_static_spec.bats (3)

In `setup.toml`, `stage:gui` sets `gui.mode = "force"` because `auto` would inherit the top-level `off`. The resolver test checks that only `gui` resolves to `gui=true`, enabling `DISPLAY` and the X11 socket mount for that service.

| Test | Description |
|------|-------------|
| `setup.toml disables GUI by default and explicitly for every non-GUI stage` | Checks that the top-level mode and each non-GUI stage override are `off`. |
| `every auto-emitted Dockerfile service stage has a setup.toml override` | Requires a section for each emitted Dockerfile stage and an explicit `gui.mode` of `off`, `auto`, or `force` in every stage section. |
| `effective GUI per stage: only gui mounts X11` | Validates each stage override key and resolves the Docker flags with `DISPLAY` unset and the parent GUI flag disabled. Expects `gui=true` for `gui` and `gui=false` for every other configured stage. |

## test/bats/smoke/pr_template_gui_spec.bats (4)

Both #428 specs read files from the checkout when run locally. In the devel-test image they read the Dockerfile, resolver libraries, setup.toml, contributor guide, and PR template under `/lint`. A missing input fails setup with its path.

| Test | Description |
|------|-------------|
| `PR template has an unchecked GUI screenshot item` | Checks that one unchecked Markdown item in the PR template mentions both GUI and a screenshot. |
| `contributor guide requires visual evidence for GUI PRs` | Checks the merge rule and looks for the execution command, Isaac Sim, and the scene in the guide. |
| `contributor guide records the Xvfb Kit screenshot experiment` | Checks for Xvfb, `--no-window`, menu readiness, the screenshot API, and CI status. |
| `contributor guide uses a generic machine label and omits personal identifiers` | Requires an approved label and checks for home paths, email addresses, and the current username when set to a non-root account. |

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

## test/bats/smoke/uid_matrix_spec.bats (6)

`script/ci/uid_matrix.sh` (isaac#474): builds `devel-base` (default; `UID_MATRIX_TARGET=devel` selects the full `devel` build) for several host UID/GID pairs and checks the runtime user. The spec uses a Docker stub. Hosted CI runs the Sim matrix with `--no-gpu`, and the `core-gpu` job imports `isaacsim` as each user. To run the same GPU checks on the Lab base, use `BASE_IMAGE=nvcr.io/nvidia/isaac-lab:3.0.0 script/ci/uid_matrix.sh`.

| Test | Description |
|------|-------------|
| `uid_matrix: --help prints usage without Docker` | Exit 0, usage printed. |
| `uid_matrix: an unknown option fails before any Docker call` | Nonzero exit, no docker call. |
| `uid_matrix: dry-run plans each host identity on the Sim base` | One plan per UID/GID case including the GID-conflict case. |
| `uid_matrix: --no-gpu dry-run honors the Lab base and devel target overrides` | `BASE_IMAGE` and `UID_MATRIX_TARGET` overrides are passed through; no GPU flags. |
| `uid_matrix: every devel identity checks, creates and removes a file in each MJCF data directory, kit/data, kit/cache and _testoutput` | Replays the CPU probe for all four identities and checks each write and removal. |
| `core-gpu: a failing GPU UID matrix fails the integration job` | A matrix failure propagates to the job. |

## test/unit/pytest/ — hosted unit (pytest, not in the bats count above)

The hosted suite collects **987 tests** on a host without Isaac Sim. isaac#440 adds nine core cases for the official Python buckets. isaac#399 adds four core cases for standalone smoke path portability and Docker lint coverage. Issue #528 adds seven core tests for the pre-run hook using base's TOML parser. They cover listing missing mounts while startup proceeds, a changed source at an existing target, a complete list with an extra mount and custom mode, inherited volumes with and without a local file, explicit empty lists, and advisory parse failures. isaac#478 adds 22 core cases for the scene backend and override contract. isaac#535 adds one stream case for camera framing. isaac#536 adds two core removal guards. isaac#429 adds 18 net core cases. isaac#474 adds 40 core cases for host UID/GID setup and the recursive ownership guard. isaac#375 adds 6 core cases for AST-based detection of hard-coded variants. isaac#480 replaces four NumPy pin cases with two base-dependency guards. Issue #484 adds two net stream tests for the official streaming experience and one core test for CI scope selection, bringing the total from 885 to 888 before isaac#276 removed 35 core tests. isaac#493 adds 6 core cases for PR scope and build selection. isaac#491 adds 19 core cases, including checks that non-Markdown docs paths select only the `docs` group. CI runs `test/assert_pytest_baseline.sh` to enforce the per-group floors in `test/pytest-baseline.txt` and the 80% coverage floor for the framework’s pure Python code.

| File | Collected | Scope |
|------|:---------:|-------|
| `test_container_min_privilege.py` | 10 | `core`. Checks privileged mode, host device bindings, three added capabilities, seccomp, PID and IPC isolation, shared memory size and host networking (isaac#549). |
| `test_readme_container_permissions.py` | 4 | `docs`. Checks that each README explains the local privilege override in its container permissions section (isaac#549). |
| `test_operator_volumes.py` | 7 | `core`. Checks the pre-run hook’s advisory volume coverage against base’s TOML merge rules (isaac#528). |
| `test_dockerfile_sim_dependencies.py` | 2 | `core`. The Dockerfile omits optional training and URDF packages and uses the NumPy bundled by NVIDIA (isaac#480). |
| `test_setup_isaac_sample.py` | 16 | `core`. Checks the documented TOML sample, model search path, read-only model mount, repo mounts after merging, absence of personal paths and URDF references, and sample references and no references to the unavailable `just run scene` recipe in all four READMEs (isaac#338). |
| `test_stage_names_docs.py` | 4 | `docs` (isaac#86). Checks the driver for `headless-stream` and the standalone livestream SOP and ZED installation guide for retired stage names, the `isaac-headless` container name and stale headless prose. Requires the SOP to include both `run -t stream -d` (start the idle container) and `exec -t stream /isaac-sim/runheadless.sh` (start Kit inside it). |
| `test_check_stale_naming.py` | 14 | `core`. Checks retired-name boundaries, path exclusions, and one allowed occurrence per phrase per line. Covers working-tree edits, file and line diagnostics, missing Git or checkout, and the move from Bats to a `core-unit` step after checkout (isaac#458). |
| `test_check_forbidden_names.py` | 14 | `core`. Checks case-insensitive matches, redaction in filenames and matched lines, tracked-file scope, the skip reason when the secret is unavailable, Git errors, and the current checkout. Verifies that CI passes the secret to the standalone scan and hosted core tests, and checks the core runner’s image, skip gate, and per-test reporting (isaac#487). |
| `test_import_safety.py` | 15 | Hosted import of each `isaac_devkit.*` module (incl. `__init__`) leaves `sys.modules` free of `omni` / `pxr` / `isaacsim` (ADR-0017 section 8 / PRD A1). |
| `test_no_module_top_isaac_import.py` | 16 | AST static guard: no module-top `import omni\|pxr\|isaacsim` in any package source (catches try/except-disguised module-top imports; mirrors the ruff TID253 config). |
| `test_output_mode.py` | 12 | `isaac_devkit.output_mode.resolve_output_mode` (isaac#366, #514): unset -> `python`; only `python` passes through; `ros`, `ROS`, `Python`, empty, `both`, leading / trailing space raise `ValueError` naming the offending value, `ISAAC_OUTPUT_MODE` and the allowed set; unrelated variables ignored; defaults to `os.environ`; constants. |
| `test_output_hub.py` | 17 | `isaac_devkit.output_hub.OutputHub` (isaac#365): delivery of the four kinds with the documented payloads (RGB uint8 `(H,W,3)` alpha dropped, depth float32 `(H,W)`, joint `names/positions/velocities/efforts`, IMU `lin_acc/ang_vel/orientation` w,x,y,z), `test_reader_not_called_without_consumer`, `test_reader_called_once_per_emit_with_consumer` (incl. unregister), shared copy for several consumers, `None` readings skipped, unknown kinds and malformed payloads raise `ValueError`. Fake sources only. |
| `test_output.py` | 8 | `isaac_devkit.output.setup_output` (isaac#365 / #366): spec defaults, python mode builds readers (monkeypatched), unset -> python, invalid mode raises, `step` / `unregister`, `ros` raises `ValueError`, `OutputModeError` hierarchy. |
| `test_stamp.py` | 4 | `isaac_devkit.stamp.split_stamp` (isaac#365, Bug 1 regression): `1.0 - 1e-10 -> (1, 0)` nanosecond carry, exact values, strictly increasing `(sec, nanosec)` pairs across second boundaries, `0 <= nanosec < 1e9` for seeded random times. |
| `test_buffers.py` | 7 | `isaac_devkit.buffers.to_u8_buffer` (isaac#365, Bug 2 regression): a float32 depth image is 4 bytes per pixel and equals `tobytes()`, uint8 RGB round-trips, returns `array.array('B')`, accepts stdlib buffers, and the non-contiguous contract (strided / Fortran-ordered input raises `ValueError`, `np.ascontiguousarray` input passes). Needs `numpy` (installed by `assert_pytest_baseline.sh`). |
| `test_no_ros_import_in_devkit.py` | 31 | 逐檔檢查原始碼（含註解與 docstring）沒有 `rclpy` 或 `isaacsim.ros2`。在新的 Python 程序中匯入整個套件及所有子模組，逐次確認未載入 ROS 模組。另檢查預設 Kit 擴充套件、已移除的兩個模組及三個公開名稱。 |
| `test_default_driver.py` | 8 | `isaac_devkit.default_driver.DefaultSceneDriver` (isaac#336 part 3): the driver a scene launch uses with no user driver. Pins that it is an `IsaacDriver` adding no `setup` / `main` / `shutdown` override, requires a scene path, `_open_stage` order (load scene -> new stage -> `build_scene`), the `run()` order with fake Kit (open stage, defaults, play timeline, tick `app.update()`, close), and Kit-free import. |
| `test_camera_setup.py` | 29 | Camera surface of `isaac_devkit.sensors` (former `camera_setup.py`): `validate_camera`, unified `load_config`, role -> Camera Helper type, FOV -> aperture math. |
| `test_sensor_setup.py` | 26 | `isaac_devkit.sensors` (former `sensor_setup.py`): YAML load, shared validation, category dispatch, per-category validation (lidar profile, IMU rigid-body rule), plus `_enable_extensions` through the `omni.kit.app` extension manager with `isaacsim.core.utils` unimportable and a static no-`isaacsim.core.utils`-import scan (isaac#248). |
| `test_sensor_prim.py` | 23 | `isaac_devkit.sensor_prim` (layer a, ADR-0024): config loading, shared/per-category validation, `ros:` section optional (loads without `ros:`, validates `ros:` when present), host-pure helpers (`fov_to_aperture`, `role_to_helper_type`), `get_category`. |
| `test_sensors_dispatch.py` | 10 | 驗證相容入口與感測器設定。自訂相機在有、無 `ros:` 的情況下均建立 color、depth 兩個 Camera prim，並回傳掛載路徑。 |
| `test_material_setup.py` | 29 | `isaac_devkit.materials`: material YAML load / validate, variant enumeration, prim-material mapping, plus `material_cfg_from_yaml` (ADR-0018 decision 7) -- color-only variant -> per-prim spawn cfg-param mapping (`{prim: {shader, diffuse_color (r,g,b), ...}}`), JSON-serializable / GPU-free, the seam `build_scene` uses to set Preview Surface diffuse color. |
| `test_scene_builder.py` | 74 | Checks YAML loading and validation, model path resolution (including `MODEL_PATH` and `package://`), instance expansion and sensor config resolution. The pure `to_spawn_specs` adapter checks ordered ground, light, robot and prop specs, scalar-first orientation, mobility, variants, diffuse color, and JSON serialization. It also checks the override allowlist and rejects five physics keys across robot, prop, light and ground settings, with an error directing authors to sim_asset and asset_converter. |
| `test_no_urdf_import.py` | 6 | Enforces the USD-only boundary and verifies that the USD helpers remain importable. |
| `test_isaac_driver.py` | 57 | Tests both livestream helpers, USD resolution, boot extension ordering, Kit-free construction, and the `SCENE` class attribute. A fake `SimulationApp` records headless mode, streaming experience, and the boot arguments followed by whitespace-split `ISAAC_KIT_EXTRA_ARGS` in `extra_args`. The tests check caller `sys.argv` during and after construction, invalid livestream rejection before startup, signal registration and lifecycle order, traceback output before close, and `ISAAC_IO_PLUGIN` invocation and error handling before timeline play. `TestPlayTimeline` checks warm start callback preference, package fallback, and the warning when neither callback is available. It verifies all three settings (fixed time stepping, rate limiting enabled, and a 60 Hz limit) and the call order from disabling looping through setting the end time, starting playback, and running 10 warmup updates. |
| `test_prim_summary.py` | 3 | Checks the `PrimSummary` fields, link and joint classification from USD prim records, and empty-stage handling. |
| `test_example_sim_removed.py` | 1 | Guards against restoring the bundled simulation example or importing its driver. |
| `test_dockerfile_no_ros.py` | 4 | Checks image inputs, build arguments and environment settings for obsolete ROS configuration. |
| `test_stage_structure.py` | 4 | Parses the Dockerfile `FROM ... AS` lines and `setup.toml` (isaac#427): `devel` is `FROM devel-base`; `gui` / `stream` / `headless` are each `FROM devel`; the header `# Stages:` block lists every active stage; top-level `[gui] mode = "off"` with only `["stage:gui"] "gui.mode" = "force"` (stream / headless / devel-test stay `off`). No docker/GPU. |
| `test_dockerfile_uid_agnostic.py` | 13 | Dockerfile host-user setup (isaac#474): no literal official uid or `isaac-sim` group name, official ids probed from the base USER, sudoers by `#UID`, group joined by numeric gid, POSIX sh MJCF loop, MJCF group write inherited by both targets, creation of group-writable `kit/data`, `kit/cache`, and `_testoutput` directories, recursive ownership guard, and hosted CPU and self-hosted GPU matrix wiring. |
| `test_check_no_recursive_chown.py` | 27 | `core`. `script/ci/check_no_recursive_chown.py` (isaac#474): flags recursive chown outside `${HOME}/` in any option order, variable targets, `/`, `/opt`, `find -exec chown`, `xargs chown`, continuation lines; accepts safe forms and the real Dockerfile; CLI exit codes; `core-unit` runs the script. |
| `test_test_groups.py` | 25 | Test-group contract (isaac#434), `core`: every pytest module has exactly one `pytestmark` group (static AST check over `test/unit/pytest`, `test/integration/pytest`, and `test/integration/no_ros`, with unmarked / two-group / unknown-group / function-level-marker detector self-tests on temp trees); every bats spec has exactly one `# bats file_tags=<group>` (non-group tags allowed, `test_tags` may not name a group) plus per-group bats counts; the collection-time plugin `test/group_markers.py` aborts a subprocess pytest run for an ungrouped or two-group test, accepts a grouped one, and `-m <other group>` collects nothing without an unknown-marker warning; the plugin and `script/ci/scope_groups.py` agree on the five groups; `test/pytest-baseline.txt` has a floor per group that sums to the total, the bats counts meet the `BATS_BASELINE_*` floors, and the 'Tests by group' table above matches the specs and the baseline. |
| `test_changed_groups.py` | 68 | `core`. Scope selection for CI (isaac#434), `script/ci/changed_groups.py`: push / dispatch / tag run every group; a PR runs the groups its paths belong to plus `docs`; docs-only paths touch only `docs`; a shared layer (Dockerfile, compose, `setup.toml`, config, `.base`, `main.yaml`, the CI scripts and baseline) runs all five; a test file follows the group it declares (not a path pattern); `ci-<group>-*` workflow files follow the group in their name; an unknown or deleted path is `core`, never nothing; dispatch group list validated; outputs (`build`, `stages`, `bats_skip`) per scenario; the CLI prints `$GITHUB_OUTPUT` lines and reads the PR diff with `git diff --name-only base...head` (stub `git`). Each stream smoke input must select `stream` on its own, with the shared entrypoint and pre-hooks selecting all five groups (isaac#459). A merge group selects all five groups and the CLI enables every flag without PR SHAs (isaac#453). An `apps/` path is no longer a stream path and falls back to `core` (isaac#484). |
| `test_ci_gate.py` | 10 | `core`. The required-check summary job (isaac#434), `script/ci/gate_result.py`: success and skipped jobs pass; failure or cancelled fails; `changes` not succeeding fails even when everything else is skipped (nothing was checked); empty needs fails; CLI exit codes 0 / 1 / 2. |
| `test_stream_visual_job.py` | 11 | Per-run ports, the shared viewer image default, producer and client startup, failure artifacts and teardown. |
| `test_stream_visual_scene.py` | 3 | Kit startup, known scene content and recovery after a stage replacement. |
| `test_stream_visual_probe.py` | 2 | Browser frame sampling, fresh navigation on retry and diagnostic capture. |
| `test_stream_visual_verdict.py` | 12 | Pixel statistics, known-colour thresholds and WebRTC requirements. |
| `test_stream_visual_wiring.py` | 5 | 驗證 stream 組觸發條件、GPU 工作流程、失敗時的產物上傳、必要檢查，以及容器清理篩選器只命中同一次執行與嘗試的容器。 |
| `test_main_workflow_scope.py` | 28 | `core`. Structure of `main.yaml` after the split (isaac#434): exact job set; no `paths:` filter on any trigger and no `schedule`; PR / main / tag / dispatch triggers; `gate` needs every other job and runs `always()` and calls `gate_result.py` with `toJSON(needs)`; each scoped job needs `changes` and checks its own flag; `docs-unit` has no condition; `core-gpu` keeps the fork guard and needs `core-unit`; `stream-smoke` (stream group, isaac#434 PR3) calls `./.github/workflows/ci-stream-smoke.yaml`, needs `stream-unit` and has the same fork guard; `core-build` receives `stages` and `BATS_SKIP_GROUPS`; `release` waits for `gate`. The merge queue requests checks, and the job conditions admit every job through `gate` while reserving `release` for tags (isaac#453). |
| `test_official_pythontests.py` | 9 | `core`. Checks shared GPU workflow and artifact wiring, sequential bucket execution, and failure on Docker errors or failed, skipped, missing, malformed, or incomplete JUnit results (isaac#440). |
| `test_official_startuptests.py` | 3 | `core`. The per-PR GPU job calls the official Isaac Sim suite helper, the helper has no Isaac Lab dependency, and the reusable workflow uploads `artifacts/startuptests` on success and failure (isaac#436). |
| `test_workflow_naming.py` | 42 | `core`. Workflow naming rule and lint (isaac#443), `script/ci/lint_workflow_names.py` + `doc/workflow-naming.md`: the real `.github/workflows/` follows the rule (and the glob finds `main.yaml` and `ci-stream-smoke.yaml`, no vacuous pass; the pre-rename stream smoke file is gone); detector self-tests on temp trees for bad file names (`.yml`, no category, uppercase, underscores), bad display names (parenthesised note, wrong case, wrong category), non-kebab job ids, a CI job with no group prefix, job-level `name:`; the allowed CI ids (`changes` / `gate` / `release` / `<group>-...`) and a bot job needing only kebab-case; exemptions are by exact file name and each carries a reason; `main.yaml` is exempt from file and display name but not from the job rule; base's `init.sh` still generates `base-version-monitor.yaml` under that name and only creates it when absent (the reason it keeps its name); the doc lists every category, group and exemption; retired names (`RETIRED_NAMES` in the lint: the old job ids, the old stream smoke file name and display name) are reported in docs while the new file name and history (changelog, ADRs) are not. |
| `test_track_isaac_sim.py` | 24 | `core`. Official Isaac Sim stable tag filtering, version ordering, suite and script changes, Traditional Chinese PR text, deduplication and the Dockerfile pin (isaac#442). |
| `test_bot_isaac_sim_version_workflow.py` | 13 | `core`. Weekly and manual triggers, optional version override, tracker invocation, gate independence, scoped permissions and built-in token (isaac#442). |
| `test_track_isaac_sim_inventory.py` | 10 | `core`. Offline tar-layer fixtures for `read_layer`, `image_layers`, `image_inventory` and `inventory_diff`: whiteout, opaque whiteout, oversized metadata, index manifests and history mismatch (isaac#442). |
| `test_track_isaac_sim_run.py` | 20 | `core`. Offline `run()` flow with faked registry, git and gh: same version opens nothing, new version opens a PR and an inventory issue, an existing branch, PR or issue opens nothing, `--dry-run` writes nothing, and main.yaml is dispatched after the PR is created (isaac#442). |
| `test_workflow_triggers.py` | 4 | `core`. No nightly run (isaac#434 PR3): only the upstream release trackers `base-version-monitor.yaml` and `bot-isaac-sim-version.yaml` may have a `schedule`; the glob must find workflows (no vacuous pass); `ci-stream-smoke.yaml` has no `schedule` but keeps `workflow_dispatch` and is callable (`workflow_call`) from `main.yaml`; it still runs `script/ci/stream_smoke_job.sh` through the pinned org `gpu-self-hosted.yml` with the 30 minute budget. |
| `test_workflow_pins.py` | 5 | Three guards cover the GPU workflow pin (isaac#402, isaac#405). The workflow jobs and the Dependabot comment must match `GPU_REUSABLE_TAG` in `gpu_pin.py`, the single source of truth for pytest. The expected callers are `main.yaml`, `ci-stream-smoke.yaml`, `ci-headless-smoke.yaml`, `ci-stream-visual-e2e.yaml`, and `publish-stream-source.yaml`. A mismatch lists missing and extra callers and directs maintainers to update `_EXPECTED_CALLERS` and this row. Two tests cover the run-scoped reap filter (isaac#344). |
| `test_readme_cleanup_text.py` | 4 | `docs`. One case per README language (isaac#381) checks the inline force-removal warning, the compose project label lookup, the nominal per-tag size and when shared layers can be reclaimed. |
| `test_stream_source_producer.py` | 22 | Hosted import/CLI-contract for the deterministic WebRTC stream-source producer driver `src/script/stream_source_producer.py` (isaac#223 / owv#48 / isaac#173): the module imports on a non-Isaac host without pulling `omni`/`pxr`/`isaacsim`/`carb` into `sys.modules` (every Isaac import function-local), the argparse surface exposes `--public-ip`/`--port`/`--run-seconds`, `--public-ip`/`--port` default from the `PUBLIC_IP`/`ISAAC_SIGNAL_PORT` env vars (the `docker run -e` container contract) with an explicit flag overriding the env, and `python stream_source_producer.py --help` exits 0 on a bare host (argparse exits before any Isaac import). Loads the driver by file path and mocks the rendering manager to verify the camera path, eye and target (isaac#535). No Isaac runtime or GPU is required. Four checks from isaac#484 cover the official experience path in both streaming scripts, removal of the repo's `apps/` directory, and removal of the Dockerfile copy step. |
| `test_xc_compose_project_isolation.py` | 4 | Hosted guard for the isaac-side root cause of `ycpss91255-lab/omniverse_web_viewer#55`: the cross-container round-trip's default `COMPOSE_PROJECT` is the dedicated `xc-isaac-roundtrip` (not the `${DOCKER_HUB_USER}-${IMAGE_NAME}` stream-stack project, e.g. `<user>-isaac`), so its project-level teardown can never reach a co-hosted manual `stream` container; asserts the dedicated literal, the isolation intent (distinct from any `${user}-${image}` derivation, which would still coincide), and that the `XC_COMPOSE_PROJECT` env override still wins. Loads the integration module by file path with env cleaned -- pure, no docker/GPU. |
| `test_xc_roundtrip_asset_migration.py` | 4 | Hosted guard for the cross-container round-trip migration onto the official Jetbot asset (isaac#325): expected camera topic / frame_id are `/jetbot/camera/color/image_raw` / `jetbot_camera_color_optical_frame`; the ament `camera_subscriber` sibling is pointed at that topic via its `camera_topic` parameter (no ament package change); the test module fetches the USD through `fetch_test_asset("jetbot")`; the Isaac runner takes `--robot-usd` and no longer imports `example_driver` or references camera_bot. Reads the real module + runner source; no docker, GPU or network. |
| ~~`test_render_settings.py`~~ | ~~13~~ | Moved to `ycpss91255-lab/isaac_physics_test` with `viz_render.py` (isaac#309). The converged-render recipe `_capture_noise_runner.py` used is now inlined there. |
| `test_sim_version.py` | 17 | Checks the release read from `/isaac-sim/VERSION`, the missing and empty file fallbacks, and the default path (isaac#295). Scans `src/script/*.py` for hard-coded `isaac_variant` values and exercises the scan on empty script sets and a planted literal (isaac#360). The AST scan detects string literals in dictionary displays, keyword arguments, and subscript assignments. Six core cases cover these forms and accept values from calls or variables (isaac#375). Checks that each line of the module docstring is at most 79 characters (isaac#376). |
| `test_adr_drop_isaac_lab.py` | 4 | ADR-0026 (isaac#476), `docs`. Checks the superseded ADR and repository names in the decision, the status in ADR-0018, URDF import ownership in ADR-0020, and the reference in ADR-0017's Isaac Lab amendment. |
| `test_readme_multi_instance.py` | 24 | `docs`. Six checks per README across four languages (isaac#289) cover section placement, the ADR-0019 and multi_run#15 links, per-instance cache, memory and project guidance, headless ports, and the absence of personal identifiers. |
| `test_no_ai_attribution.py` | 30 | PR commit checks (isaac#413, isaac#414). Clean commits, ordinary mentions, and human co-author names containing Claude pass. Model names and versions, anthropic.com co-author, author, or committer addresses, generation notices (including Markdown links), and session trailers flag the offending commit SHAs. Coverage includes indentation, mixed case, and versions written without a space (`Claude Sonnet4.5`, `Claude Opus4`, and `Claude-3`). With a stubbed git log, an empty range succeeds and an invalid range reports an error with exit code 2. Omitting both the range and `--stdin` is a usage error. |
| `test_model_readme_layout.py` | 11 | `docs`. Checks the five moved model paths, the removal of their old paths, the sim_asset README citation (isaac#363). |
| `test_standalone_smoke_matrix.py` | 11 | `core`. Three parametrized checks guard against reintroducing the USD gate. Two more verify that each case has three fields and that the runner passes `bash -n` (isaac#359). Two parser cases verify that both an empty matrix and a matrix containing only a comment yield an empty list. Four more checks cover the empty matrix exit, default paths from outside the checkout, environment overrides, and inclusion in Docker ShellCheck. |
| `test_standalone_scripts.py` | 14 | Checks the pure helpers for Kit configuration, periodic timers, exit codes, removal of OpenBase-specific attributes, the smoke script’s workspace path, and the sensor and camera shim entry points. Also checks that the USD inspector stays removed and that tracked Python files contain no references to the retired extension. |
| `test_ros_scripts_removed.py` | 25 | Guards against restoring retired ROS scripts and cross-container tests, checks the no-ROS integration layout, and verifies the documentation updates. |
| `test_repo_config.py` | 3 | Repo-level config found by onboarding. `.dockerignore` keeps the host Isaac Sim cache tree `isaac-sim/` out of the build context; Kit creates `isaac-sim/documents/Kit/shared/screenshots` with mode 000, which made `just docker build` fail with `permission denied` after the first launch. `setup.toml` `[deploy]` uses `gpu_runtime`, not the deprecated `runtime` that base warns about on every setup. The Dockerfile pre-creates `/isaac-sim/extsUser`: the experience file lists it as an extension folder, the NGC image does not ship it, and the non-root user cannot create it, so Kit scanned `~/work` instead and warned `Extensions config 'extension.toml' doesn't exist` once per top-level directory. Pure file reads. |
| `test_test_assets.py` | 12 | Official Isaac test-asset fetch helper (`test/test_assets.py`, #324). Pins the NVIDIA Jetbot USD URL on the Omniverse S3 bucket with a version segment and SHA-256 digest; cache-hit path returns without calling `_download`; cache-miss path calls `_download`; the return value is a `Path`; an empty cache with a simulated `ConnectionError` raises `RuntimeError` naming the asset; an unknown asset name raises `KeyError`. #325 adds the pinned `nvidia_cube` entry (URL on the same bucket/version, SHA-256) and a structural guard that `test_build_scene_adapter.py` / `_build_scene_runner.py` no longer reference the removed bundled simulation example and use `fetch_test_asset`. Pure -- mocked HTTP, filesystem only. |
| `test_headless_smoke_wiring.py` | 6 | Checks the headless smoke workflow, its CI scope and the scripts installed in the image. |
| `test_producer_versions.py` | 6 | Checks the generated producer-version tables in the four READMEs. |

## test/integration/ — GPU integration

### test/integration/pytest/

The GPU suite collects **36 tests**, all inside the Isaac test container. `test/assert_pytest_baseline.sh --gpu` requires at least one pass, enforces the collection floor and checks the cross-runner aggregate. Both directories under `test/integration/` are collected.

| Test | Description |
|------|-------------|
| `test_camera_headless.py::test_camera_custom_yaml_creates_prims_headless` | 從 `custom.yaml` 建立相機，驗證 color、depth 兩個 USD Camera prim 的路徑、CUDA 與 Vulkan 初始化及正常結束標記。 |
| `test_example_gpu_integration.py` (6) | 檢查 Jetbot 場景啟動與結束、CUDA 與 Vulkan 初始化、底盤剛體、連桿與關節數量、底盤下的 Camera prim，以及 SIGINT 關閉流程。 |
| `test_sensor_setup_integration.py` (5) | 使用含 `ros:` 的 YAML 建立 RealSense、兩種 LiDAR 及 IMU，檢查回傳的 prim 與掛載位置，並驗證 IMU 拒絕非剛體的父節點。 |
| `test_joint_drive_integration.py` (1) | Creates a revolute USD joint, applies a runtime drive and reads the angular stiffness and damping back from its DriveAPI. |
| `test_output_hub_gpu.py` (4) | OutputHub delivery (isaac#365): one runner boot (`_output_hub_runner.py`, official Jetbot) builds python-mode output with an RGB and a depth camera, joint state and an IMU prim, steps 300 ticks and the four tests assert RGB uint8 `480x640x3`, depth float32 `480x640`, joint names present, IMU orientation length 4. Marker-line acceptance. Executed on a real GPU in the devel-test container (isaac#384): 4 passed, 0 skipped; the runtime `IMU.create(...)` + IMU reader path is confirmed (orientation length 4). |
| `test_kit_extra_args_integration.py` (2) | `ISAAC_KIT_EXTRA_ARGS` (isaac#422): `_kit_extra_args_runner.py` boots a minimal `IsaacDriver` and reads `/app/isaac_test/marker` back through carb settings. With `ISAAC_KIT_EXTRA_ARGS=--/app/isaac_test/marker=1` the value is `1`; without the variable the setting is absent (control). First proof is the CI GPU job. |
| `test_build_scene_adapter.py` (5) | The runner builds an in-memory scene from the official Jetbot and NVIDIA cube USDs fetched via `test/test_assets.py` (#325). Checks clean exit, ground and light creation, the robot and its `/World/Robot/chassis` prim, a dynamic cube with `RigidBodyAPI`, the existing ground and prop collision schemas, optional variant sets, and identity orientation for zero roll, pitch and yaw. |
| `test_capture_noise.py` (3) | Capture-speckle fix (isaac#266): one Kit boot (`_capture_noise_runner.py`) builds a lit room and captures it TWICE through the SAME render product -- once as replicator creates it, once after `apply_converged_render_settings` (inlined from the former `viz_render` module, now in `ycpss91255-lab/isaac_physics_test`) authors the recipe on the RenderProduct prim. Asserts the default leg is CLEAN, i.e. NGX-denoised (isaac#294: since #285 set `gpu_capabilities = all` the container gets the `ngx` capability, so the old "default must still be noisy" guard was inverted -- a default leg back near 53 now means NGX dropped out again), that the mode reads back as `PathTracing` off the live prim (a carb `/rtx/rendermode` write reads back unchanged, so this is what separates "applied" from "attempted"), and that the converged frame is clean (absolute ceiling, no relative-to-default check since both legs are now clean) with no fully black pixels. The metric is neighbouring-pixel mean absolute difference, NOT frame `std`: `std` is dominated by scene contrast, which is why every failed hypothesis in the issue "left std unchanged" and looked equally inert. Reference on the RTX 5090: pre-#285 default 53.0 vs converged 2.1; post-#285 default ~0.41 vs converged ~1.53 (CI run 34233956492). |
| `test_driver_joint_motion.py` (6) | The #447 regression shares one Jetbot run per engine (PhysX and Newton). The wheel test checks the active engine and requires both wheels to move more than one radian in the commanded direction. The settings test checks that the 60 Hz rate limit and fixed stepping are enabled and timeline looping is off. The clock test requires monotonic `omni.timeline` time, 60 updates per simulated second (±15%), and fewer than 69 updates per wall-clock second (upper bound only, detects removal of the 60 Hz rate limit). |
| `test_isaac_driver_integration.py` (1) | Exercises the driver lifecycle in Kit. |

### test/integration/no_ros/

[Suite files and purpose](../../test/integration/no_ros/README.md)

| Test | Description |
|------|-------------|
| `test_io_plugin_integration.py` (2) | Boots the Jetbot with the default extensions and checks that the fake I/O plugin creates its marker only when configured. Both cases verify that no ROS client or bridge module was loaded. |

## example/ros2/ — app-side ament package tests (colcon test, not in the counts above)

The app-side ROS 2 templates (#133, `example/ros2/src/`) carry their own tests, run by `colcon test` inside a hosted `ros:humble` container (`docker run --rm`, no Isaac / no GPU per the PRD compatibility matrix ament row). They are NOT counted in the bats header total (the drift check counts `^@test` lines only) and are NOT part of the framework hosted-unit pytest baseline (`test/assert_pytest_baseline.sh` collects only `test/unit/pytest/`). Run: `docker run --rm -v "$PWD/example/ros2":/ws -w /ws ros:humble bash -c 'source /opt/ros/humble/setup.bash && colcon build && colcon test && colcon test-result --all'`.

| Test | Package | Description |
|------|---------|-------------|
| `test_copyright.py` | `example_app_py` | `ament_copyright`: every source file carries an accepted licence header. |
| `test_flake8.py` | `example_app_py` | `ament_flake8`: source is flake8-clean. |
| `test_pep257.py` | `example_app_py` | `ament_pep257`: docstrings follow the ament PEP 257 convention. |
| `test_helpers.py` | `example_app_py` | Pure-helper unit tests (no ROS context): default camera and velocity command topics, `describe_image` summary fields, `make_twist` sets only the planar components. |
| `ament_lint_common` suite | `example_app_cpp` | `copyright` / `cpplint` / `uncrustify` / `lint_cmake` / `xmllint` / `cppcheck` (cppcheck skips when the optional tool is absent) over the C++ nodes + `CMakeLists.txt` + `package.xml`. |

