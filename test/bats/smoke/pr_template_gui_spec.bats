#!/usr/bin/env bats
# bats file_tags=core

bats_require_minimum_version 1.5.0

setup() {
  case "${BATS_TEST_DIRNAME%/}" in
    smoke_test|*/smoke_test) cd /lint ;;
    *) cd "${BATS_TEST_DIRNAME}/../../.." ;;
  esac
  local file
  for file in CONTRIBUTING.md .github/pull_request_template.md; do
    [[ -f "${file}" ]] || { echo "Missing required file: ${PWD}/${file}" >&2; return 1; }
  done
}

@test "PR template has an unchecked GUI screenshot item" {
  local template=.github/pull_request_template.md
  grep -E '^[[:blank:]]*- \[ \][[:blank:]]+' "${template}" |
    grep -i 'GUI' | grep -Ei '截圖|screenshot'
}

@test "contributor guide requires visual evidence for GUI PRs" {
  # Keep wrapped Markdown together so an unrelated screenshot elsewhere
  # in the guide cannot satisfy the GUI review rule.
  awk -v RS='' '{ gsub(/\n/, " "); print }' CONTRIBUTING.md |
    grep -i 'GUI' | grep -Ei '截圖|screenshot' |
    grep -Ei 'PR|pull request|merge|合併' |
    grep -Ei 'must|requir|before merg|必須|須|需|才能|合併前'
  grep -Ei '指令|命令|command' CONTRIBUTING.md
  grep -Ei 'Isaac Sim' CONTRIBUTING.md
  grep -Ei '場景|scene' CONTRIBUTING.md
}

@test "contributor guide records the Xvfb Kit screenshot experiment" {
  grep -Fi 'Xvfb' CONTRIBUTING.md
  grep -F -- '--no-window' CONTRIBUTING.md
  grep -Ei '選單|menu' CONTRIBUTING.md
  grep -F 'capture_app_screenshot_async' CONTRIBUTING.md
  awk -v RS='' '{ gsub(/\n/, " "); print }' CONTRIBUTING.md |
    grep -Ei '(尚未|還沒|未|暫不|not|outside|pending).*CI|CI.*(尚未|還沒|未|暫不|not|pending)'
}

@test "contributor guide uses a generic machine label and omits personal identifiers" {
  grep -E '電腦規格|test_1 server' CONTRIBUTING.md
  run grep -Ei '/home/[a-z_][a-z0-9_-]*|[[:alnum:]_.%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}' CONTRIBUTING.md
  [ "${status}" -eq 1 ]
  if [[ -n "${USER:-}" && "${USER}" != root ]]; then
    run grep -Fiw -- "${USER}" CONTRIBUTING.md
    [ "${status}" -eq 1 ]
  fi
}
