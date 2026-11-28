#!/usr/bin/env bash
# pre-run hook: host-side, runs before run.sh main logic.
# Receives the same "$@" as run.sh. Non-zero exit aborts the wrapper.
# Skipped when just docker run runs with --dry-run.
#
# 1. Refuses to run while this checkout still uses the image tag / compose
#    project that every checkout on this host shares (stopgap for
#    base#1550 / base#1551; see script/checkout_identity.sh). Fix once per
#    checkout with ./script/checkout_identity.sh isolate, or opt out
#    explicitly with ISAAC_ALLOW_SHARED_IDENTITY=1.
# 2. Warns when the operator layer drops repo mounts.
# 3. Creates the Isaac Sim cache mount sources as the host user before
#    compose mounts them (script/init_isaac_dirs.sh). Otherwise the daemon
#    creates them root-owned and Kit cannot write its caches.
set -euo pipefail

repo_root="${FILE_PATH:-$(pwd -P)}"
lib="${ISAAC_IDENTITY_LIB:-${repo_root}/script/checkout_identity.sh}"
bash "${lib}" guard run "${repo_root}"

check_operator_volumes() {
  local repo_conf="${repo_root}/setup.toml"
  local operator_conf="${repo_root}/setup.local.toml"
  [[ -f "${repo_conf}" && -f "${operator_conf}" ]] || return 0

  local repo_kv effective_kv
  # Use base's merge so an omitted list inherits and an empty list clears.
  if ! source "${repo_root}/.base/dist/script/docker/lib/toml_bridge.sh" ||
     ! repo_kv="$(toml_bridge_merge --kv "${repo_conf}")" ||
     ! effective_kv="$(toml_bridge_merge --kv "${repo_conf}" "${operator_conf}")"; then
    printf '[run] WARNING: could not check setup.local.toml volume coverage.\n' >&2
    return 0
  fi

  # The bridge serializes volumes as source[:target[:mode]]. Match the
  # source and target so local mount options can differ.
  awk -F '\t' '
    $1 == "volumes" && $2 ~ /^mount_[0-9]+$/ && $3 != "" {
      split($3, fields, ":")
      mount = fields[1] ":" fields[2]
      if (FILENAME == ARGV[1]) {
        covered[mount] = 1
      } else if (!(mount in covered)) {
        if (!warned++)
          print "[run] WARNING: setup.local.toml is missing these mounts from setup.toml:"
        print "  " $3
      }
    }
  ' <(printf '%s\n' "${effective_kv}") <(printf '%s\n' "${repo_kv}") >&2
}

check_operator_volumes

init_dirs="${repo_root}/script/init_isaac_dirs.sh"
if [[ -x "${init_dirs}" ]]; then
  "${init_dirs}" --quiet
fi
