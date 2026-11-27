#!/usr/bin/env bash
# Run after gpu_job_apply_and_pin_ws_path and the stream build.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."
. script/ci/stream_smoke_lib.sh
project="isaac-visual-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"
source_dir="${PWD}/script/ci/visual_e2e"
out="${PWD}/artifacts/stream-visual-e2e"
log_name="${project}.log"
kit_log="${PWD}/isaac-sim/kit/logs/${log_name}"
viewer="${project}-viewer"
browser="${project}-browser"
playwright_version=1.62.1

compose() {
  docker compose -p "${project}" --env-file .env.generated -f compose.yaml "$@"
}

cleanup() {
  local status=$?
  trap - EXIT
  docker rm -f "${browser}" "${viewer}" >/dev/null 2>&1 || true
  COMPOSE_PROFILES='*' compose down -t 0 --remove-orphans || status=1
  if [[ -f "${kit_log}" ]]; then
    cp "${kit_log}" "${out}/kit.log" || status=1
  fi
  exit "${status}"
}

smoke_alive() {
  [[ "$(docker inspect -f '{{.State.Running}} {{.RestartCount}}' "${cid}")" == 'true 0' ]]
}

# The pinned base derives container names from the project in this cache.
sed -i "s|^PROJECT_NAME=.*|PROJECT_NAME=${project}|" .env.generated
mkdir -p "${out}"
chmod a+rwx "${out}"
ports="$(python3 "${source_dir}/ports.py")"
read -r signal media api serve <<< "${ports}"
echo "Starting ${project} with signal=${signal} media=${media} api=${api} viewer=${serve}"
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

ISAAC_SKIP_STREAM_POST_RUN=1 ./script/run.sh -t stream -d
cid="$(compose ps -q stream)"
[[ -n "${cid}" ]] || { echo "Stream container missing" >&2; exit 1; }
docker cp "${source_dir}/scene/min_scene.py" "${cid}:/tmp/min_scene.py"
# Kit 6 reads primaryStream.* settings. The wrapper also takes ISAAC_*_PORT.
primary=/exts/omni.kit.livestream.app/primaryStream
docker exec -d -e "ISAAC_SIGNAL_PORT=${signal}" -e "ISAAC_MEDIA_PORT=${media}" \
  -e "ISAAC_API_PORT=${api}" "${cid}" sh -c 'exec "$@" > "$0" 2>&1' \
  "/isaac-sim/kit/logs/${log_name}" /usr/local/bin/runheadless-host-config.sh \
  "--${primary}/signalPort=${signal}" "--${primary}/streamPort=${media}" \
  --exec /tmp/min_scene.py
smoke_wait_for "${kit_log}" "${SMOKE_TIMEOUT:-600}" "${SMOKE_POLL:-5}" \
  'Started primary stream server' 'App is loaded.' '[SBF] scene ready'

url="http://127.0.0.1:${serve}"
docker run -d --rm --name "${viewer}" --network host \
  -e VIEWER_UI_MODE=stream-only -e SIGNALING_SERVER=127.0.0.1 \
  -e "SIGNALING_PORT=${signal}" -e "MEDIA_PORT=${media}" -e "SERVE_PORT=${serve}" \
  ghcr.io/ycpss91255-docker/omniverse_web_viewer:0.3.0
deadline=$((SECONDS + 60))
until curl -fsS --max-time 2 "${url}" >/dev/null; do
  (( SECONDS < deadline )) || { echo "Viewer timed out" >&2; exit 1; }
  sleep 1
done

docker run --rm --name "${browser}" --network host --ipc host --user pwuser -w /tmp \
  -e "BASE_URL=${url}" -e OUT_DIR=/out -e "PLAYWRIGHT_VERSION=${playwright_version}" \
  -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 -v "${source_dir}:/probe:ro" -v "${out}:/out" \
  "mcr.microsoft.com/playwright:v${playwright_version}-noble" sh -ec 'cp /probe/probe.mjs .
    npm install --prefix /tmp --no-audit --no-fund "playwright@${PLAYWRIGHT_VERSION}"
    exec node probe.mjs' &
wait "$!"
smoke_alive
