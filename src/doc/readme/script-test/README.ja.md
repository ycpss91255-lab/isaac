# Standalone scripts smoke

**[English](../../../script/test/README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

`standalone_smoke.sh` には現在テストケースがありません。実行するとその旨を表示し、Docker を起動せずに正常終了します。

## 使い方

チェックアウトのルートで実行します。

```bash
./src/script/test/standalone_smoke.sh
```

各ケースにはスクリプトのファイル名、起動完了を示す正規表現、タイムアウト秒数を指定します。

設定済みのケースを実行するときは、スクリプトが属するチェックアウトと `stream` サービスを使います。別のチェックアウトを使うには、justfile のあるディレクトリを `ISAAC_SMOKE_REPO_DIR` に指定します。コンテナにマウントしたチェックアウトからの相対パス `src/script` は、`ISAAC_SMOKE_SCRIPT_DIR` で上書きできます。

## Exit codes

| Code | 意味 |
|-----:|------|
| 0 | 選択した全 case が PASS |
| 1 | 1 件以上 FAIL |
| 2 | 不明なオプション、または事前確認の失敗（チェックアウトを利用できないか、stream コンテナを起動できない） |
