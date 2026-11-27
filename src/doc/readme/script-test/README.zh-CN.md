# Standalone scripts smoke

**[English](../../../script/test/README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

`standalone_smoke.sh` 目前没有配置任何测试用例。运行时会提示用例为空，随后正常退出，不会启动 Docker。

## 用法

```bash
./isaac_ws/src/script/test/standalone_smoke.sh
```

每个用例需指定脚本文件名、匹配就绪消息的正则表达式和超时秒数。

## Exit codes

| Code | 意义 |
|-----:|------|
| 0 | 所选案例全部 PASS |
| 1 | 至少 1 个 FAIL |
| 2 | 未知选项或 Pre-flight 失败(docker dir 不在 / standalone container 起不来)|
