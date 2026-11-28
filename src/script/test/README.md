# Standalone scripts smoke

**[English](README.md)** | **[繁體中文](../../doc/readme/script-test/README.zh-TW.md)** | **[简体中文](../../doc/readme/script-test/README.zh-CN.md)** | **[日本語](../../doc/readme/script-test/README.ja.md)**

The smoke matrix in `standalone_smoke.sh` is empty. The runner reports that no cases are configured and exits successfully before starting Docker.

## Usage

From the checkout root, run:

```bash
./src/script/test/standalone_smoke.sh
```

Each configured case specifies a script basename, a ready marker (regular expression), and a timeout in seconds.

For configured cases, the runner uses the checkout containing the script and the `stream` service. Set `ISAAC_SMOKE_REPO_DIR` to use another checkout containing the justfile. Set `ISAAC_SMOKE_SCRIPT_DIR` to override `src/script`, which is relative to the mounted checkout in the container.

## Exit codes

| Code | Meaning |
|-----:|---------|
| 0 | All selected cases PASS |
| 1 | At least one FAIL |
| 2 | Unknown flag or pre-flight failure (checkout unavailable or stream container won't start) |
