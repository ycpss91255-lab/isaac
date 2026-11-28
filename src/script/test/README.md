# Standalone scripts smoke

**[English](README.md)** | **[繁體中文](../../doc/readme/script-test/README.zh-TW.md)** | **[简体中文](../../doc/readme/script-test/README.zh-CN.md)** | **[日本語](../../doc/readme/script-test/README.ja.md)**

The smoke matrix in `standalone_smoke.sh` is empty. The runner reports that no cases are configured and exits successfully before starting Docker.

## Usage

```bash
./isaac_ws/src/script/test/standalone_smoke.sh
```

Each configured case specifies a script basename, a ready marker (regular expression), and a timeout in seconds.

## Exit codes

| Code | Meaning |
|-----:|---------|
| 0 | All selected cases PASS |
| 1 | At least one FAIL |
| 2 | Unknown flag or pre-flight failure (docker dir missing / standalone container won't start) |
