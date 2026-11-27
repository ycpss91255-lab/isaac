# Standalone scripts smoke

**[English](../../../script/test/README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

`standalone_smoke.sh` には現在テストケースがありません。実行するとその旨を表示し、Docker を起動せずに正常終了します。

## 使い方

```bash
./isaac_ws/src/script/test/standalone_smoke.sh
```

各ケースにはスクリプトのファイル名、起動完了を示す正規表現、タイムアウト秒数を指定します。

## Exit codes

| Code | 意味 |
|-----:|------|
| 0 | 選択した全 case が PASS |
| 1 | 1 件以上 FAIL |
| 2 | 不明なオプション、または Pre-flight 失敗(docker dir が無い / standalone container 起動不可)|
