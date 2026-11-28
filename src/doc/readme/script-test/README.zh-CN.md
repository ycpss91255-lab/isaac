# Standalone scripts smoke

**[English](../../../script/test/README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

`standalone_smoke.sh` 目前没有配置任何测试用例。运行时会提示用例为空，随后正常退出，不会启动 Docker。

## 用法

在检出目录的根目录运行：

```bash
./src/script/test/standalone_smoke.sh
```

每个用例需指定脚本文件名、匹配就绪消息的正则表达式和超时秒数。

运行已配置的用例时，脚本使用自身所在的检出目录与 `stream` 服务。可用 `ISAAC_SMOKE_REPO_DIR` 指定另一个包含 justfile 的检出目录。可用 `ISAAC_SMOKE_SCRIPT_DIR` 覆盖容器内的 `src/script`，默认路径相对于容器挂载的检出目录。

## Exit codes

| Code | 意义 |
|-----:|------|
| 0 | 所选案例全部 PASS |
| 1 | 至少 1 个 FAIL |
| 2 | 未知选项或预检失败（检出目录不可用或 stream 容器无法启动） |
