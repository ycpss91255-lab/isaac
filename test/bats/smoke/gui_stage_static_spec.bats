#!/usr/bin/env bats
# bats file_tags=core

bats_require_minimum_version 1.5.0

setup() {
  case "${BATS_TEST_DIRNAME%/}" in
    smoke_test|*/smoke_test)
      cd /lint
      lib_dir=lib
      python=/isaac-sim/python.sh
      ;;
    *)
      cd "${BATS_TEST_DIRNAME}/../../.."
      lib_dir=.base/dist/script/docker/lib
      python=python3
      ;;
  esac
  local file
  for file in setup.toml Dockerfile; do
    [[ -f "${file}" ]] || { echo "Missing required file: ${PWD}/${file}" >&2; return 1; }
  done
  source "${lib_dir}/stage.sh"
}

@test "setup.toml disables GUI by default and explicitly for every non-GUI stage" {
  "${python}" - <<'PY'
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open("setup.toml", "rb") as f:
    config = tomllib.load(f)
assert config["gui"]["mode"] == "off", "[gui] mode must be off"
for section, values in config.items():
    if section.startswith("stage:") and section != "stage:gui":
        assert values.get("gui.mode") == "off", f"[{section}] must explicitly set gui.mode to off"
PY
}

@test "every auto-emitted Dockerfile service stage has a setup.toml override" {
  local stages stage
  local -a emitted=()
  stages="$(_parse_dockerfile_stages Dockerfile)"
  while IFS= read -r stage; do
    _validate_stage_name "${stage}" || continue
    emitted+=("${stage}")
  done <<<"${stages}"
  "${python}" - "${emitted[@]}" <<'PY'
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open("setup.toml", "rb") as f:
    config = tomllib.load(f)
assert "gui" in sys.argv[1:], "Dockerfile must declare a gui service stage"
for stage in sys.argv[1:]:
    assert f"stage:{stage}" in config, f'setup.toml is missing ["stage:{stage}"]'
for section, values in config.items():
    if section.startswith("stage:"):
        mode = values.get("gui.mode")
        assert mode in ("off", "auto", "force"), f"[{section}] needs explicit gui.mode off|auto|force, got {mode!r}"
PY
}

# devel-test copies the shell libraries but omits the native bridge. Supply
# its TSV for flat stage overrides when the only local layer is empty.
stage_test_bridge() {
  [[ "$#" == 4 && "$1" == --merge && "$2" == --kv &&
     "$3" == "${PWD}/setup.toml" && "$4" == "${_SETUP_CONF_LOCAL}" && ! -s "$4" ]] || return 1
  "${python}" - "$3" <<'PY'
import sys
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open(sys.argv[1], "rb") as f:
    config = tomllib.load(f)
for section, values in config.items():
    if section.startswith("stage:"):
        for key, value in values.items():
            assert isinstance(value, (str, bool, int, float)), f"[{section}] {key} needs a scalar override"
            print(section, key, str(value).lower() if isinstance(value, bool) else value, sep="\t")
PY
}

@test "effective GUI per stage: only gui mounts X11" {
  unset DISPLAY _SETUP_SCRIPT_DIR TOML_BRIDGE_FORCE_DOCKER
  source "${lib_dir}/setup_conf.sh"  # also sources conf.sh and its TOML bridge
  local _SETUP_CONF_LOCAL="${BATS_TEST_TMPDIR}/empty.toml"
  : > "${_SETUP_CONF_LOCAL}"  # ignore any operator's setup.local.toml
  if ! command -v toml-bridge >/dev/null; then
    if [[ -f .base/dockerfile/toml_bridge.py ]]; then
      toml-bridge() { "${python}" .base/dockerfile/toml_bridge.py "$@"; }
    else
      toml-bridge() { stage_test_bridge "$@"; }
    fi
  fi

  local -A parent=(
    [gui]=false [gpu]=false [gpu_count]="" [gpu_caps]="" [runtime]=""
    [net_mode]="" [ipc_mode]="" [pid_mode]="" [net_name]=""
    [volumes_top]="" [env_top]="" [ports_top]=""
    [cap_add_top]="" [cap_drop_top]="" [sec_opt_top]=""
  )
  local -A eff=()
  local -a keys=() values=()
  local sections section stage key expected
  _setup_conf_handle "${PWD}" gui_test_conf
  sections="$(_conf_sections gui_test_conf)"
  grep -Fxq 'stage:gui' <<<"${sections}"
  while IFS= read -r section; do
    [[ "${section}" == stage:* ]] || continue
    stage="${section#stage:}"
    _load_stage_overrides "${PWD}" "${stage}" keys values
    (( ${#keys[@]} > 0 )) || { echo "[stage:${stage}] loaded no overrides" >&2; return 1; }
    for key in "${keys[@]}"; do
      _validate_stage_override_key "${key}" || {
        echo "[stage:${stage}] has unsupported override key '${key}'" >&2
        return 1
      }
    done
    _resolve_docker_flags keys values parent eff
    expected=false
    if [[ "${stage}" == gui ]]; then expected=true; fi
    [[ "${eff[gui]}" == "${expected}" ]] || {
      echo "[stage:${stage}] resolved gui=${eff[gui]}, expected ${expected} with DISPLAY unset" >&2
      return 1
    }
  done <<<"${sections}"
}
