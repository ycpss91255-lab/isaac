#!/usr/bin/env bash
# Print the Docker volume option for Git metadata outside the checkout.
set -euo pipefail

repo_root="$(realpath -- "${1:?usage: git_common_mount.sh REPO_ROOT}")"
common_dir="$(git -C "${repo_root}" rev-parse --path-format=absolute --git-common-dir)"
if [[ "${common_dir}" != "${repo_root}" && "${common_dir}" != "${repo_root%/}/"* ]]; then
  printf -- '-v %s:%s:ro\n' "${common_dir}" "${common_dir}"
fi
