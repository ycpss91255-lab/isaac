# Standalone scripts smoke

**[English](../../../script/test/README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

`standalone_smoke.sh` 目前沒有設定任何測試案例。執行時會提示沒有案例，接著正常結束，不會啟動 Docker。

## 用法

在 checkout 根目錄執行：

```bash
./src/script/test/standalone_smoke.sh
```

每個案例需指定腳本檔名、比對就緒訊息的正規表示式與逾時秒數。

執行已設定的案例時，腳本會使用自身所在的 checkout 與 `stream` 服務。可用 `ISAAC_SMOKE_REPO_DIR` 指定另一個包含 justfile 的 checkout。可用 `ISAAC_SMOKE_SCRIPT_DIR` 覆寫容器內的 `src/script`，預設路徑相對於容器掛載的 checkout。

## Exit codes

| Code | 意義 |
|-----:|------|
| 0 | 所選案例全部 PASS |
| 1 | 至少 1 個 FAIL |
| 2 | 未知選項或前置檢查失敗（checkout 無法使用或 stream 容器無法啟動） |
