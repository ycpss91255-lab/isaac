# Standalone scripts smoke

**[English](../../../script/test/README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

`standalone_smoke.sh` 目前沒有設定任何測試案例。執行時會提示沒有案例，接著正常結束，不會啟動 Docker。

## 用法

```bash
./isaac_ws/src/script/test/standalone_smoke.sh
```

每個案例需指定腳本檔名、比對就緒訊息的正規表示式與逾時秒數。

## Exit codes

| Code | 意義 |
|-----:|------|
| 0 | 所選案例全部 PASS |
| 1 | 至少 1 個 FAIL |
| 2 | 未知選項或 Pre-flight 失敗(docker dir 不在 / standalone container 起不來)|
