#!/usr/bin/env bats
# bats file_tags=core

bats_require_minimum_version 1.5.0

setup() {
  if [[ "${BATS_TEST_DIRNAME}" == /smoke_test ]]; then
    cd /lint
    stage_lib=lib/stage.sh
    python=/isaac-sim/python.sh
  else
    cd "${BATS_TEST_DIRNAME}/../../.."
    stage_lib=.base/dist/script/docker/lib/stage.sh
    python=python3
  fi
  [ -f setup.toml ]
}

@test "setup.toml sets GUI off by default and auto only for stage:gui" {
  "${python}" - <<'PY'
try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

with open("setup.toml", "rb") as f:
    config = tomllib.load(f)
assert config["gui"]["mode"] == "off", "[gui] mode must be off"
assert config["stage:gui"]["gui.mode"] == "auto", "[stage:gui] gui.mode must be auto"
for section, values in config.items():
    if section.startswith("stage:") and section != "stage:gui":
        assert values.get("gui.mode") == "off", f"[{section}] must explicitly set gui.mode to off"
PY
}

@test "every auto-emitted Dockerfile service stage has a setup.toml override" {
  [ -f Dockerfile ]
  source "${stage_lib}"
  local stages stage
  local -a configured=()
  stages="$(_parse_dockerfile_stages Dockerfile)"
  grep -Fxq gui <<<"${stages}"
  _parse_stage_sections setup.toml configured
  while IFS= read -r stage; do
    _validate_stage_name "${stage}" || continue
    if ! printf '%s\n' "${configured[@]}" | grep -Fx "${stage}" >/dev/null; then
      echo "setup.toml is missing [\"stage:${stage}\"] with an explicit gui.mode"
      return 1
    fi
  done <<<"${stages}"
}
