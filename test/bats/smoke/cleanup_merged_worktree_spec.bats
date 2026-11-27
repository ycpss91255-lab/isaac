#!/usr/bin/env bats
# bats file_tags=core
#
# Behavioral guard for script/git/cleanup-merged-worktree.sh (#368).
#
# Hermetic: a throwaway repo (bare "origin" + a clone as the main checkout +
# a sibling worktree/ directory) is built inside BATS_TEST_TMPDIR, and `gh`
# is a stub that prints a canned tab-separated "state<TAB>branch<TAB>oid"
# line. Nothing touches a real repo or worktree. No docker, no network.
#
# Baked into /smoke_test/ next to the script by the devel-test stage.

bats_require_minimum_version 1.5.0

setup() {
  export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.invalid
  export GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.invalid
  export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null

  ROOT="${BATS_TEST_TMPDIR}"
  git init -q --bare -b main "${ROOT}/origin.git"
  git clone -q "${ROOT}/origin.git" "${ROOT}/repo/src" 2>/dev/null
  git -C "${ROOT}/repo/src" checkout -q -b main
  echo base >"${ROOT}/repo/src/f.txt"
  git -C "${ROOT}/repo/src" add f.txt
  git -C "${ROOT}/repo/src" commit -q -m base
  git -C "${ROOT}/repo/src" push -q origin main
  git -C "${ROOT}/repo/src" remote set-head origin main

  MAIN="${ROOT}/repo/src"
  WT="${ROOT}/repo/worktree/feat-x"
  git -C "${MAIN}" worktree add -q "${WT}" -b feat/x main
  echo work >"${WT}/g.txt"
  git -C "${WT}" add g.txt
  git -C "${WT}" commit -q -m work
  git -C "${WT}" push -q origin feat/x
  OID="$(git -C "${WT}" rev-parse HEAD)"

  # gh stub: `gh pr view N --json ... --jq ...` prints the canned line.
  STUB="${ROOT}/bin"
  mkdir -p "${STUB}"
  cat >"${STUB}/gh" <<'EOF'
#!/usr/bin/env bash
cat "${GH_STUB_OUT}"
EOF
  cat >"${STUB}/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' docker "$@" >>"${DOCKER_LOG}"
exit "${DOCKER_STUB_STATUS}"
EOF
  chmod +x "${STUB}/gh" "${STUB}/docker"
  export GH_STUB_OUT="${ROOT}/gh.out"
  export DOCKER_LOG="${ROOT}/docker.log" DOCKER_STUB_STATUS=0
  export PATH="${STUB}:${PATH}"

  SCRIPT="${BATS_TEST_DIRNAME}/cleanup-merged-worktree.sh"
}

gh_says() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >"${GH_STUB_OUT}"; }

# Deny the first worktree removal (once) or every removal (always).
stub_remove_denied() {
  REAL_GIT="$(command -v git)"
  export REAL_GIT
  export REMOVE_FAILURE="$1" REMOVE_LOG="${ROOT}/remove.log"
  cat >"${STUB}/git" <<'EOF'
#!/usr/bin/env bash
args=("$@")
if [[ "$1" == "-C" ]]; then args=("${@:3}"); fi
if [[ "${args[0]}" == worktree && "${args[1]}" == remove ]]; then
  echo remove >>"${REMOVE_LOG}"
  if [[ "${REMOVE_FAILURE}" == always || $(wc -l <"${REMOVE_LOG}") -eq 1 ]]; then
    echo "error: failed to delete '${args[2]}/x': Permission denied" >&2
    exit 1
  fi
fi
exec "${REAL_GIT}" "$@"
EOF
  chmod +x "${STUB}/git"
}

@test "cleanup: dirty worktree -> SKIP dirty, nothing removed" {
  gh_says MERGED feat/x "${OID}"
  echo wip >>"${WT}/g.txt"
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [ "${output}" = "SKIP dirty" ]
  [ -d "${WT}" ]
  [ -n "$(git -C "${MAIN}" branch --list feat/x)" ]
}

@test "cleanup: untracked file also counts as dirty" {
  gh_says MERGED feat/x "${OID}"
  echo new >"${WT}/untracked.txt"
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [ "${output}" = "SKIP dirty" ]
  [ -d "${WT}" ]
}

@test "cleanup: unpushed commit -> SKIP unpushed, nothing removed" {
  gh_says MERGED feat/x "${OID}"
  echo more >"${WT}/h.txt"
  git -C "${WT}" add h.txt
  git -C "${WT}" commit -q -m local-only
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [ "${output}" = "SKIP unpushed" ]
  [ -d "${WT}" ]
  [ -n "$(git -C "${MAIN}" branch --list feat/x)" ]
}

@test "cleanup: PR not merged -> SKIP not-merged, nothing removed" {
  gh_says OPEN feat/x "${OID}"
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [ "${output}" = "SKIP not-merged" ]
  [ -d "${WT}" ]
  [ -n "$(git -C "${MAIN}" branch --list feat/x)" ]
}

@test "cleanup: all checks pass -> worktree and branch removed, removed=1" {
  gh_says MERGED feat/x "${OID}"
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"removed=1"* ]]
  [ ! -e "${WT}" ]
  [ -z "$(git -C "${MAIN}" branch --list feat/x)" ]
  run git -C "${MAIN}" worktree list
  [[ "${output}" != *"feat-x"* ]]
}

@test "cleanup: root-owned files -> SKIP root-owned files + fix command, nothing else removed" {
  gh_says MERGED feat/x "${OID}"
  stub_remove_denied always
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [[ "${output}" == *"SKIP root-owned files"* ]]
  [[ "${output}" == *"chown -R"* ]]
  [ -d "${WT}" ]
  [ -n "$("${REAL_GIT}" -C "${MAIN}" branch --list feat/x)" ]
}

@test "cleanup: --fix-owner runs chown once and retries removal" {
  gh_says MERGED feat/x "${OID}"
  stub_remove_denied once
  cd "${MAIN}"
  run "${SCRIPT}" --fix-owner 7
  [ "${status}" -eq 0 ]
  [ "${lines[0]}" = "REMOVED ${WT} (feat/x)" ]
  [ "${lines[1]}" = "removed=1" ]
  [ "$(wc -l <"${REMOVE_LOG}")" -eq 2 ]
  diff -u <(printf '%s\n' docker run --rm -v "${WT}:/x" busybox:1 chown -R "$(id -u):$(id -g)" /x) "${DOCKER_LOG}"
  [ ! -e "${WT}" ]
  run git show-ref --verify --quiet refs/heads/feat/x
  [ "${status}" -eq 1 ]
}

@test "cleanup: --fix-owner skips removal when docker fails" {
  gh_says MERGED feat/x "${OID}"
  stub_remove_denied once
  DOCKER_STUB_STATUS=1
  cd "${MAIN}"
  run "${SCRIPT}" --fix-owner 7
  [ "${status}" -eq 0 ]
  [ "${output}" = "SKIP fix-owner-failed" ]
  [ -s "${DOCKER_LOG}" ]
  [ "$(wc -l <"${REMOVE_LOG}")" -eq 1 ]
  [ -d "${WT}" ]
  git show-ref --verify --quiet refs/heads/feat/x
}

@test "cleanup: --fix-owner reports remove-failed when the retry fails" {
  gh_says MERGED feat/x "${OID}"
  stub_remove_denied always
  cd "${MAIN}"
  run "${SCRIPT}" --fix-owner 7
  [ "${status}" -eq 0 ]
  [[ "${output}" == "SKIP remove-failed:"* ]]
  [ -s "${DOCKER_LOG}" ]
  [ "$(wc -l <"${REMOVE_LOG}")" -eq 2 ]
  [ -d "${WT}" ]
}

@test "cleanup: permission denied without --fix-owner never invokes docker" {
  gh_says MERGED feat/x "${OID}"
  stub_remove_denied always
  cd "${MAIN}"
  run "${SCRIPT}" 7
  [ "${status}" -eq 0 ]
  [ "${lines[0]}" = "SKIP root-owned files" ]
  [ ! -e "${DOCKER_LOG}" ]
}

@test "cleanup: --fix-owner skips docker when the first removal succeeds" {
  gh_says MERGED feat/x "${OID}"
  cd "${MAIN}"
  run "${SCRIPT}" --fix-owner 7
  [ "${status}" -eq 0 ]
  [ "${lines[0]}" = "REMOVED ${WT} (feat/x)" ]
  [ ! -e "${WT}" ]
  [ ! -e "${DOCKER_LOG}" ]
}

@test "cleanup: worktree outside the worktree root -> SKIP outside-worktree-root" {
  gh_says MERGED feat/x "${OID}"
  git -C "${MAIN}" worktree remove "${WT}"
  OUT="${ROOT}/elsewhere/feat-x"
  git -C "${MAIN}" worktree add -q "${OUT}" feat/x
  run bash -c "cd '${MAIN}' && '${SCRIPT}' 7"
  [ "${status}" -eq 0 ]
  [ "${output}" = "SKIP outside-worktree-root" ]
  [ -d "${OUT}" ]
}

@test "cleanup: no PR number -> usage, exit 2" {
  run bash -c "cd '${MAIN}' && '${SCRIPT}'"
  [ "${status}" -eq 2 ]
  [[ "${output}" == *"Usage"* ]]
}

@test "cleanup: --dry-run on an all-pass worktree prints WOULD-REMOVE and removes nothing" {
  gh_says MERGED feat/x "${OID}"
  run bash -c "cd '${MAIN}' && '${SCRIPT}' --dry-run 7"
  [ "${status}" -eq 0 ]
  [[ "${output}" == "WOULD-REMOVE "* ]]
  [ -d "${WT}" ]
  [ -n "$(git -C "${MAIN}" branch --list feat/x)" ]
}
