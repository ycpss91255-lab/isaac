#!/usr/bin/env bats
# bats file_tags=core

bats_require_minimum_version 1.5.0

@test "tracked text uses current Docker commands and config names" {
  if [[ "${BATS_TEST_DIRNAME}" == /smoke_test ]]; then
    local root
    root=$(git rev-parse --show-toplevel 2>/dev/null) || skip "the copied specs need a Git checkout"
    cd "$root"
  else
    cd "${BATS_TEST_DIRNAME}/../../.."
  fi

  # ADRs 0005, 0007 and 0014 explicitly preserve their original decisions
  # and give the modern equivalents in editorial notes.
  git ls-files -z -- . ':!.base' \
    ':(exclude,glob)**/CHANGELOG*' ':(exclude,glob)**/.gitignore' \
    ':(exclude,glob)**/.dockerignore' ':!test/bats/smoke/stale_naming_spec.bats' \
    ':!src/doc/adr/0005-standalone-with-livestream-as-default-dev-entrypoint.md' \
    ':!src/doc/adr/0007-custom-streaming-experience-for-simulationapp.md' \
    ':!src/doc/adr/0014-sim-runtime-stage-taxonomy-stream-vs-headless.md' \
    > "${BATS_TEST_TMPDIR}/tracked"
  local -a files
  mapfile -d '' -t files < "${BATS_TEST_TMPDIR}/tracked"
  (( ${#files[@]} > 0 ))

  # Match the five former Docker targets and root wrappers. Paths such as
  # ./script/run.sh and script/hooks/pre/run.sh still name real files.
  local stale='(^|[^[:alnum:]_])setup[.]conf([^[:alnum:]_-]|$)'
  stale+='|(^|[^[:alnum:]_-])make[[:blank:]]+(build|run|exec|stop|test)([^[:alnum:]_-]|$)'
  stale+='|(^|[^[:alnum:]_./-])[.]/(build|run|exec|stop)[.]sh[.]?([^[:alnum:]_.-]|$)'

  # Git grep reads working-tree text, respects binary attributes and skips
  # symlinks (including wrappers into .base). Status 1 means no matches.
  git --literal-pathspecs grep --no-color -IznE "$stale" -- "${files[@]}" \
    > "${BATS_TEST_TMPDIR}/hits" || [[ $? == 1 ]]

  local path number line remaining failed=0
  while IFS= read -r -d '' path && IFS= read -r -d '' number && IFS= read -r line; do
    remaining=$line
    case "$path" in
      script/checkout_identity.sh)
        # The rc6 migration note names the previous override file.
        remaining=${remaining/'base rc6 moved it from `.setup.conf.local`'/}
        ;;
      test/bats/smoke/checkout_identity_spec.bats)
        # The test asserts the obsolete file was never written.
        remaining=${remaining/'[ ! -e "${REPO}/.setup.conf.local" ]'/}
        ;;
      test/bats/smoke/init_isaac_dirs_spec.bats|doc/test/TEST.md)
        # Negative assertions, their test titles and their catalogue entries.
        remaining=${remaining/'refute_output --partial "./build.sh"'/}
        remaining=${remaining/'refute_output --partial "./run.sh"'/}
        remaining=${remaining/'no removed ./build.sh hint'/}
        remaining=${remaining/'not the removed ./build.sh / ./run.sh'/}
        remaining=${remaining/'not the removed `./build.sh`'/}
        remaining=${remaining/'and no `.setup.conf.local`'/}
        ;;
      src/doc/adr/0011-ci-architecture-with-self-hosted-gpu-runner.md)
        # The dated rollout records the original CI scope map.
        remaining=${remaining/'compose, `.setup.conf`, config, the base subtree'/}
        ;;
      src/doc/adr/0022-conform-bats-smoke-to-base-canonical-layout.md)
        # The cited upstream change relocated the config in v0.42.
        remaining=${remaining/'+ `.setup.conf` relocation'/}
        ;;
      src/doc/adr/0025-output-mode-ros-or-python.md)
        # This decision records override behaviour on the v0.42 pin.
        remaining=${remaining/'key in `.setup.conf` `[environment]` (section-replaced by'/}
        remaining=${remaining/'`.setup.conf.local`).'/}
        remaining=${remaining/'UNVERIFIED; avoided by not defining the key in `.setup.conf`'/}
        ;;
    esac
    if [[ $remaining =~ $stale ]]; then
      printf '%s:%s:%s\n' "$path" "$number" "$line"
      failed=1
    fi
  done < "${BATS_TEST_TMPDIR}/hits"
  return "$failed"
}
