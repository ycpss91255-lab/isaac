# isaac

**[English](../README.md)** | **[繁體中文](README.zh-TW.md)** | **[简体中文](README.zh-CN.md)** | **[日本語](README.ja.md)**

NVIDIA Isaac Sim 6.2.0 Docker 開発環境。[`ycpss91255-lab/base`](https://github.com/ycpss91255-lab/base)（旧名 `ycpss91255-lab/template`）をベースに構築。

イメージには Isaac Sim 本体と、scene-spawn backend（`sim_utils` spawner；ADR-0018）として使う NVIDIA Isaac Lab 3.0（`v3.0.0`）が含まれます。`IsaacDriver` は `isaacsim.SimulationApp` で Kit を起動する。下流のアプリケーションノード（CoreSAM、AGV bring-up）と Noetic 互換用の ROS 1 / ROS 2 bridge は隣接する docker folder に配置。

本リポジトリは Isaac Sim ワークスペース（driver スクリプト、ADR、USD モデル）も [`src/`](../src/README.md) に同梱する。root の Dockerfile + base subtree がそのワークスペースを動かす開発環境。元々は `ycpss91255-lab/isaac` と `ycpss91255-lab/isaac`（research が docker を submodule として包む構成）に分かれていたが、 [#78](https://github.com/ycpss91255-lab/isaac/issues/78) に従い本リポジトリへ統合した。

## 前提条件

- NVIDIA driver `>= 580`（Isaac Lab 3.0 は CUDA 13 版 PyTorch を導入；NVIDIA は Isaac Sim 6.2.0 を 595.58.03 で検証；本 repo は driver 610 で検証済み）
- GPU `>= RTX 4080`（または同等）、VRAM `>= 16 GB`
- Docker + nvidia-container-toolkit
- 約 50 GB の空き領域。build 後のイメージは約 31 GB で、そのうち 20.7 GB が NGC base image、約 10 GB が Isaac Lab と tooling；他の stage はこれらの layer を共有する。build には BuildKit cache 用の余裕が必要で、初回起動後に cache ディレクトリがさらに 5–10 GB 増加

NGC イメージ（`nvcr.io/nvidia/isaac-sim:6.2.0.1`、6.2.0 GA ビルド；`:6.2.0` を使わない理由は `Dockerfile` の `BASE_IMAGE` コメント参照）は公開取得可能、`docker login nvcr.io` 不要。

## Quick Start

clone した直後の repo で、まず repo root から次の 2 つの初回手順を実行する：

```bash
./script/checkout_identity.sh isolate   # 初回のみ — この checkout 専用の image tag と compose project を割り当てる
./script/init_isaac_dirs.sh             # 初回のみ — ./script/setup.sh apply を実行し、host 所有の cache ディレクトリ 10 個を作成
```

> cache ディレクトリは、container が mount する **前に** 存在し、自分の所有になっている必要がある。そうでないと docker daemon がそれらを **root** で作成し、Kit が cache を書き込めない。その結果 ROS 2 OmniGraph node を登録できず（`[Errno 13] ... kit/cache/ogn_generated`）、それでも exit 0 で終了する。`init_isaac_dirs.sh` がこれらを作成し、pre-run hook が毎回の `just docker run` の前に再実行する。すでに root 所有になっている場合、スクリプトは停止して `chown` による修正方法を表示する。

次に経路を**1 つだけ**選ぶ。各 stage は互いに独立しており、実行する stage だけを build すればよい。headless の経路の前に devel を build する必要は**ない**。

| やりたいこと | Build | Run |
|---|---|---|
| シーンを実行して ROS 2 topic を見る（まずはここから） | `just docker build -t headless` | `just docker run -t headless -d`、続いて下の「Headless：Isaac を起動してシーンを実行する」 |
| 開発用の対話 shell | `just docker build`（devel） | `just docker run` |
| WebRTC でシミュレーションを見る | `just docker build -t stream` | `just docker run -t stream -d`、続いて「WebRTC livestream への接続」 |

コールド状態の初回 build には約 1 時間かかる。20.7 GB の NGC base image を pull してから Isaac Lab をインストールするためである。GitHub-hosted CI の build は 45〜84 分だった（[45 分](https://github.com/ycpss91255-lab/isaac/actions/runs/42550974606/job/128946327237)、[58 分](https://github.com/ycpss91255-lab/isaac/actions/runs/42545601510/job/128929863953)、[84 分](https://github.com/ycpss91255-lab/isaac/actions/runs/42491566385/job/128764928999)）。以降の build は layer cache を再利用し、他の stage もそれらの layer を共有するので、2 つ目の stage の build は数秒から数分で済む。

Production stage（両 stage とも起動後は idle — driver スクリプトを exec で実行中の container に送り込む）：

```bash
just docker run -t headless -d                             # pure sim, no streaming (ISAAC_LIVESTREAM=0)
just docker run -t stream -d                               # sim + WebRTC streaming (ISAAC_LIVESTREAM=2)
just docker exec -t stream /isaac-sim/python.sh <script>   # run a driver script
```

> Stage ツリー：`devel-base` -> `devel`（共通層：isaac コードと共通設定）-> `gui` / `stream` / `headless`。X11 を mount するのは `gui` service のみ（`setup.toml` の `["stage:gui"] "gui.mode" = "auto"`。トップレベルの `[gui]` は `mode = "off"` なので `devel` と他の stage は mount しない）：`just docker run -t gui`。2 つの stage が [base #215](https://github.com/ycpss91255-lab/base/issues/215) により profile-gated compose service として auto-emit される：`headless`（pure sim、`ISAAC_LIVESTREAM=0`）、`stream`（sim + WebRTC、`ISAAC_LIVESTREAM=2`）。両者とも起動時は `CMD ["sleep","infinity"]` で idle（`runheadless.sh -v` ENTRYPOINT は無い）— container は起動したまま、`just docker exec -t <stage> <cmd>` で driver スクリプト（`/isaac-sim/python.sh <driver.py>`、`ISAAC_LIVESTREAM=2` を読んで stream を有効化）または一回限りの `/usr/local/bin/runheadless-host-config.sh` を送り込む；streaming 起動後は web-viewer が `:5173` で接続する。`just docker run -t <stage> -d` で起動。

### Headless：Isaac を起動してシーンを実行する

このリポジトリにはシミュレーションのサンプルを同梱していません。[Isaac Sim 公式サンプル](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/introduction/examples.html#standalone-examples)からヘッドレスで実行できるスクリプトを選び、`path/to/your_scene.py` をコンテナ内のパスに置き換えてください。相対パスの起点はリポジトリのルート（`~/work`）です。

```bash
just docker build -t headless
just docker run -t headless -d
./script/exec.sh -t headless bash -c \
  'echo $$ > /tmp/isaac-driver.pid; ROS_DOMAIN_ID=77 exec /isaac-sim/python.sh path/to/your_scene.py'

just docker stop
```

ROS 2 を使うシーンでは、シーンと ROS 2 クライアントで同じ未使用の `ROS_DOMAIN_ID`（ここでは `77`）を指定してください。

Kit は session log を host 側の `isaac-sim/kit/logs/Kit/<app>/<version>/kit_<timestamp>.log` に書き込む。最新のものを追うには：

```bash
tail -f "$(ls -t isaac-sim/kit/logs/Kit/*/*/kit_*.log | head -1)"
```

container の `docker logs` には idle の main process（`sleep infinity`）しか出ず、exec で送り込んだスクリプトの出力は表示されない。

> quote された `bash -c '...'` を含むコマンドは `just docker exec` ではなく `./script/exec.sh` を経由する。base v0.42.0 では `just` recipe が引数を再分割するため、quote したコマンドや `>` が host 側で実行されてしまう。base は v0.43.0-rc5（base PR #1298）で修正済みだが、本 repo はまだ v0.42.0 を pin している（#297）。

### 無視してよい起動時の警告

Kit は起動のたびに、実行に影響しない警告をいくつか出力する：

- `OmniHub: ... Hub encountered error. Trying to reconnect to Hub. retry_reason="Hub failed to launch: ..."`、最初の 2 秒で約 40 行。OmniHub は Nucleus asset 用の任意のローカル cache サービスである。その helper（`/usr/local/bin/hub`）は container 内で `Permission denied` で終了するため、Kit は asset を直接読み込む。
- `Extensions config 'extension.toml' doesn't exist '/home/<user>/work/<dir>'`、repo のトップレベルディレクトリごとに 1 行（約 15 行）。これはこの修正より前に build した image で出る：experience ファイルの `extsUser` extension フォルダが image になく、container user もそれを作成できないため、Kit が代わりに作業ディレクトリで extension を探していた。現在の image はこのフォルダを作成する。まだこの警告が出る場合は `just docker build -t <stage>` でその stage を再 build すること。

### driver スクリプトの停止

対話的な `just docker exec` での Ctrl+C はスクリプトに届き、その SIGINT handler が Kit を shutdown する。しかし exec client が TTY でない場合や、client が kill された場合（terminal を閉じた、`timeout`、CI）、signal はスクリプトに届かず、**Kit は container 内で動き続ける**。確実に停止するには、上の例の `echo $$ > /tmp/isaac-driver.pid` のように、スクリプト起動時に PID を記録しておく。その上で、その process の子（`python.sh` が起動した Python）に SIGINT を送る：

```bash
./script/exec.sh -t headless bash -c 'pkill -INT -P "$(cat /tmp/isaac-driver.pid)"'
```

素の `pkill -f <script>` は使わないこと。container は `pid: host` で動作しているため、その pattern は host や他の container の process にもマッチする。すべてを停止したい場合は、`just docker stop` でこの checkout の container を削除すれば、内部で動いている Kit もまとめて停止する。

### checkout ごとに 1 つの image と 1 つの compose project

以前は同じ host 上のこの repo のすべての checkout が同じ image tag（`<hub>/isaac:<stage>`）と同じ compose project（`<hub>-isaac`）に解決されていた。そのため `just docker build` が別の checkout の build した image を prune し、`just docker stop` / `run` が別の checkout の container を削除していた（上流：[base#1550](https://github.com/ycpss91255-lab/base/issues/1550)、[base#1551](https://github.com/ycpss91255-lab/base/issues/1551)、[base#1552](https://github.com/ycpss91255-lab/base/issues/1552)）。base が修正するまでは：

- `./script/checkout_identity.sh isolate` が `[[image.rules]] rule = "string:isaac-<dir>-<hash>"` (and `[project] name`) を gitignore 済みの `setup.local.toml` に書き込む。image tag・compose project・container 名はすべてこれに従う。`./script/checkout_identity.sh show` でこの checkout の解決結果を表示できる。
- pre build / run / stop hook は共有名のままでは実行を拒否する。`ISAAC_ALLOW_SHARED_IDENTITY=1` で上書きできる（CI の build ステップが使用）。
- `just docker run` は既存の image を再 build しない（base#1552）。変更を pull したら `just docker run -t <stage>` の前に `just docker build -t <stage>` を実行する。
- ディスク使用量：build する checkout または worktree ごとに独自の image tag（`<hub>/isaac-<dir>-<hash>:<stage>`）を持つ。`docker images` に表示される stage tag あたり約 31 GB は名目上のサイズ。共有レイヤーがあるため、tag を削除して実際に回収できる容量はそれより少ない。checkout ディレクトリを削除しても image は Docker daemon に残る。
- 削除済み checkout の後始末：`./script/checkout_identity.sh show`（ディレクトリ削除前に実行。`.env.generated` が必要）または `docker images` から `isaac-<dir>-<hash>` の名前を確認する。`PROJECT_NAME` を独自に設定すると `<hub>-<slug>` と異なる場合がある。ラベルの出力から削除済み checkout の image を探し、その行の project 名をコピーする。

  ```bash
  SLUG='isaac-<dir>-<hash>'   # 正確な名前。例: "image: <hub>/<SLUG>:<stage>" から
  docker ps -a --format '{{.Label "com.docker.compose.project"}}  {{.Image}}  {{.Names}}'
  PROJECT='<project>'
  docker ps -a --filter "label=com.docker.compose.project=${PROJECT}" --format '{{.Names}}'
  docker ps -aq --filter "label=com.docker.compose.project=${PROJECT}" | xargs -r docker rm -f  # 実行中のコンテナを強制終了するため、checkout がもう存在しない場合のみ実行する。現存する checkout には使わないこと
  docker images --filter "reference=*/${SLUG}:*"
  docker images --filter "reference=*/${SLUG}:*" --format '{{.Repository}}:{{.Tag}}' | xargs -r docker rmi
  ```

  filter は project と image の slug をそれぞれ完全一致で指定する。`docker rmi` で tag を外しても、別の checkout が使う共有レイヤーの容量は、それを参照する最後の tag がなくなるまで解放されない。`isaac*` に広げたり `docker image prune -a` を実行したりしない：共有の `test-tools:<base バージョン>` image（次の項目）はこの手順で削除してはならない。
- 1 つの image はまだ共有される：毎回の build で lint/bats 用ツール image `test-tools:<base バージョン>`（現在は `test-tools:v0.42.0`）も build され、その名前は pin した base バージョンだけで決まる。同じ base バージョンを pin する host 上のすべての checkout と repo が同じ tag を書き込むため、別の checkout が build 中かもしれないときは削除しないこと。`just docker build --clean-tools` は全員の分をまとめて削除する。これは base の `build.sh` に由来し、上流では [base#1551](https://github.com/ycpss91255-lab/base/issues/1551) で追跡している。
- isolate 前に起動した container は共有 project に残る。`docker compose -p <hub>-isaac ps -a` で一覧し、自分のものを名前で停止する。`ISAAC_ALLOW_SHARED_IDENTITY=1 just docker stop` は共有 project 全体（別の checkout の container を含む）を停止する。

### 複数 instance の並列実行

この repo は checkout ごとに 1 つの instance を起動する設計を採用し、同じ checkout で複数の instance を管理する独自の仕組みを削除した（[ADR-0019](../src/doc/adr/0019-remove-same-repo-multi-instance.md)）。N 個の instance を実行するには、multi_run からこの repo の `compose.yaml` を使って N 回起動する。設計の詳細は [multi_run#15](https://github.com/ycpss91255-lab/multi_run/issues/15) を参照。

- `-p <name>` で instance ごとに異なる compose project 名を指定する。これで `just docker stop` が停止するのは対象の instance だけになり、起動時に前回の instance を誤って引き継ぐことも防げる。
- 各 instance にはキャッシュとデータを格納する専用の `isaac-sim/` ディレクトリツリーが必要になる。書き込み可能なキャッシュディレクトリを共有すると、実行中の instance の Kit キャッシュが警告なしに破損する。[Cache レイアウト](#cache-レイアウト)を参照。
- headless で並列実行する場合、ポートの上書きは不要。ポートの上書きが必要なのはストリーミング時のみ。

実用上の同時実行数は GPU の空きメモリで決まる。32607 MiB の GPU で実測したところ、実行中の Isaac instance は 1 つあたり約 3.9 GiB を使用し、6～7 個を同時に実行できる。手元の GPU の空きメモリを GiB に換算し、3.9 で割ると目安がわかる。GPU の演算資源は共有するため、各 instance の実行速度は低下する。

## ローカルの USD モデルをマウントする

Isaac にはサンプルモデルが同梱されていません。`sim_asset` の USD モデル、または `asset_converter` で変換した USD モデルを使ってください。

1. `cp setup.isaac_sample.toml setup.local.toml` を実行して、Git の管理対象外のローカル設定ファイルを作成します。すでにファイルがある場合は、このチェックアウトの設定を保持するため、既存のファイルにサンプルの設定を統合してください。
2. モデルのマウント設定の `source` を、モデルがあるディレクトリに変更します。どのマシンでもシーンから同じパスを参照できるように、読み取り専用のマウント先は `/home/${USER_NAME}/models/sim_asset` のままにします。モデルのマウントを追加する場合は、対応するコンテナ内のパスをコロン区切りで `MODEL_PATH` に追加します。
3. `just docker run -t headless -d` でコンテナを起動します。

Base はローカル設定を適用するときに `[[volumes]]` のリスト全体を置き換えます。ローカル設定には `setup.toml` のマウントをすべて残し、リポジトリにマウントが追加されたら反映してください。

## WebRTC livestream への接続

Isaac Sim 6.2.0 は NVCF（`omni.services.livestream.nvcf`）livestream プロトコルを使用。デスクトップ client またはブラウザベースのビューアで接続：

1. [NVIDIA ドキュメント — manual livestream clients](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/manual_livestream_clients.html) から **Isaac Sim WebRTC Streaming Client** をダウンロード。NVIDIA ドキュメントがそこに記載する、お使いの Isaac Sim バージョンに対応した client バージョンを使用してください。
2. `stream` 実行中、client を起動し Server: `<server-ip>` を入力（同一マシン: `localhost`、リモート: server の LAN IP）。**`:8011` などの port サフィックスを付けないこと** — client が signaling / data port を内部で管理しており、port を付けると誤った経路に入って黒画面になります。
3. Connect をクリック。初回 shader compile に 1–3 分かかってから viewport が描画されます。

### Browser-based viewer (omniverse_web_viewer)

[`omniverse_web_viewer`](https://github.com/ycpss91255-lab/omniverse_web_viewer) リポジトリが、サイドカーコンテナとしてブラウザベースの client を提供。本リポジトリの `web_viewer/` にサブモジュールとして同梱。

```bash
# 初回：サブモジュール初期化 + per-host config 作成
git submodule update --init --recursive web_viewer
cp config/host.yaml.example config/host.yaml
# config/host.yaml を編集：network.public_ip にこのマシンの LAN IP を設定

# idle な stream コンテナ + host.yaml + web-viewer を起動。
# post-run hook（base #440）が host.yaml をコピーし viewer を起動する。
just docker run -t stream -d

# Isaac Sim をコンテナに起動 -- 明示的なステップ（run = infra、
# exec = workload）。driver スクリプトを使う場合：
just docker exec -t stream /isaac-sim/python.sh <driver.py>
# ...または driver なしのクイックストリームには livestream wrapper：
#   just docker exec -t stream /usr/local/bin/runheadless-host-config.sh

# Watch Isaac Sim load: Kit's session log on the host (docker logs only
# shows the container's idle main process)
tail -f "$(ls -t isaac-sim/kit/logs/Kit/*/*/kit_*.log | head -1)"

# Chrome -> http://<host-ip>:5173 を開く
# そのまま映像ストリームが起動します（stream-only 自動起動。UI Option 選択画面なし）

# すべて停止（post-stop hook が web-viewer を削除する）
just docker stop
```

`config/host.yaml` は gitignored・per-machine。`network.public_ip` が両方の container にマウントされ、Isaac 側は `runheadless-host-config.sh` が読んで Kit `publicEndpointAddress` 引数に注入、web-viewer 側は entrypoint が読んで `SIGNALING_SERVER` に設定する。

post-run hook はさらに `network.public_ip` を `SIGNALING_SERVER` env として viewer container に渡す — defense in depth として、ローカルキャッシュの viewer image が `omniverse_web_viewer#12`（`/etc/host.yaml` を読む entrypoint）より古い場合でも正しい host IP を取得できる。`web_viewer/` submodule pointer 更新後は `owv:runtime` を手動 rebuild して新しい entrypoint を取り込むこと。

要件：Chrome または Chromium（Firefox 非互換）。稼働中の Isaac Sim ごとに 1 つのインタラクティブ client のみ接続可能。

注意：

- streaming kit app は `8011`（NVCF signaling、FastAPI/uvicorn）、`49100`（self-host WebRTC）、`8211`（kit API / streaming viewer）を同時に listen。WebRTC Streaming Client が正しい方を選ぶので **port を書かないこと**
- **同時に 1 つの client のみ接続可能**（NVIDIA 制限）。2 つ目の接続は拒否されます
- `setup.toml` の `[network]` で `mode = "host"` が設定済みのため、コンテナ内の listen port = host の port。Host ファイアウォールで `8011/tcp` と `49100/tcp` を許可（`sudo ufw allow 8011/tcp && sudo ufw allow 49100/tcp`）
- `setup.toml` の `[deploy]` では `gpu_capabilities = "all"` により `video` が有効 — なければ nvidia-container-runtime が NVENC libs（`libnvidia-encode.so` / `libnvcuvid.so`）を mount せず、server 接続成功でも encode できない → 黒画面。
- Server 側で listener を確認：`ss -tln | grep -E ':8011|:49100'` で 2 つの `LISTEN` が見えるはず

### 決定論的 stream-source producer（GHCR image、isaac#223）

CI とブラウザベースの視覚 e2e（[`omniverse_web_viewer#48`](https://github.com/ycpss91255-lab/omniverse_web_viewer/issues/48)）向けに、デスクトップ Isaac session を立ち上げずに*確実に非ブラック*な WebRTC ソースを提供する、pull 可能で版号を pin した producer image。起動時に決定論的な「空だが光のある」シーン — dome + distant key light を 12×12 チェッカーボード床に当て、カメラは `eye=[15,-15,11]` にフレーミング — をレンダリングし、永久に livestream するので、ブラウザはいつ接続しても再現可能なフレームを見る。シーン全体はプログラムで生成（外部 asset なし）、image は自己完結。

- **Image**：`ghcr.io/ycpss91255-lab/isaac-stream-source:<tag>`（pin した immutable tag — `:latest` ではない）。`producer` Dockerfile stage から build。
- **Driver**：`src/script/stream_source_producer.py`、`/opt/isaac-producer/stream_source_producer.py` に bake され、image `CMD` が起動。
- **公開**：`Publish Stream-Source Producer (GHCR)` workflow の手動起動のみ（`workflow_dispatch`、input `tag`、デフォルト `0.0.1`）。push/tag trigger は無いので、merge で自動公開されない。

実行：

```bash
# --network=host でコンテナの WebRTC listen port = host の port。
# PUBLIC_IP はこの host の LAN IP（リモートブラウザがダイヤルする先）；
# ISAAC_SIGNAL_PORT はデフォルト signaling port（49100）を上書き。
docker run --rm --network=host --gpus all \
  -e PUBLIC_IP=<host-lan-ip> \
  -e ISAAC_SIGNAL_PORT=49100 \
  ghcr.io/ycpss91255-lab/isaac-stream-source:0.0.2

# その後ブラウザ / omniverse_web_viewer で <host-lan-ip> に接続（上記参照）。
```

Isaac Sim 6.2.0 から build した producer image はまだ公開されていない。最新は 6.0.1 上で build した `0.0.2` なので、下の表もそこで終わっている。公開は publish workflow の手動 `workflow_dispatch` で行い、表は image 自身の label から更新される。

### バージョンと Isaac Sim の対応

producer image のバージョンは単純に増加し、Isaac Sim のバージョンを符号化しません。あるイメージがどの Isaac Sim 上でビルドされたかは、イメージ自身に尋ねてください。

<!-- producer-versions:start -->
| Tag | Isaac Sim | Source |
|---|---|---|
| `0.0.1` | 5.1.0 | declared (predates the label) |
| `0.0.2` | 6.0.1 | declared (predates the label) |

Generated by `script/ci/sync_producer_versions.py`; do not edit by hand.

The table is a convenience view. The authority is the image itself --
ask it directly when it matters:

```bash
docker inspect ghcr.io/ycpss91255-lab/isaac-stream-source:<tag> \
  --format '{{index .Config.Labels "org.opencontainers.image.base.name"}}'
```
<!-- producer-versions:end -->

必須：NVENC フレームエンコード用の NVIDIA GPU runtime（`--gpus all`）、`--network=host`、非 localhost client には `PUBLIC_IP`。`ISAAC_SIGNAL_PORT` は任意（デフォルト `49100`）。driver は `--public-ip` / `--port` / `--run-seconds N`（`N>0` で smoke run を区切る；デフォルトは永久実行）も受け付ける。

## ROS I/O

このイメージでは、外部プラグインが ROS 連携を提供します。`ISAAC_IO_PLUGIN` にプラグインの `module:function` を指定すると、ROS I/O が有効になります。

### Standalone Python ドライバー

#### 追加の Kit 引数（`ISAAC_KIT_EXTRA_ARGS`）

`IsaacDriver.run` は `ISAAC_KIT_EXTRA_ARGS` を読み、空白で分割して Kit 起動時の既存引数（組み込みの boot 引数）の後ろに追加する。未設定、空文字列、空白のみの場合は動作が変わらない。この変数を読むのは `IsaacDriver` だけで、`stream_source_producer`、`src/script/` 配下のスクリプトは非対応。

```bash
export ISAAC_KIT_EXTRA_ARGS='--/app/isaac_test/marker=1'
/isaac-sim/python.sh my_driver.py
# または 1 行で：
ISAAC_KIT_EXTRA_ARGS='--/app/isaac_test/marker=1' /isaac-sim/python.sh my_driver.py
```

#### 起動プラグイン（`ISAAC_IO_PLUGIN`）

`IsaacDriver.run` は `ISAAC_IO_PLUGIN`（`module:function`）を読む。stage の構築後、timeline の play 前に、その module を import し `function(stage, robot_prim, config)` を 1 回呼ぶ。`config` は opaque な dict（現在は `usd_path` と、stage の default prim パスである `robot_prim`）。未設定または空文字列なら何も呼ばず、ROS モジュールも import しない。形式の誤り、module を import できない、function が見つからない場合は、それぞれ原因を示して起動時に失敗する。対応するのは `IsaacDriver.run` だけで、`stream_source_producer`、`src/script/` 配下のスクリプトは非対応。

```bash
export ISAAC_IO_PLUGIN='my_pkg.io:setup_io'
/isaac-sim/python.sh my_driver.py
# 1 行で書く場合：
ISAAC_IO_PLUGIN='my_pkg.io:setup_io' /isaac-sim/python.sh my_driver.py
```

### Python 出力 API（isaac#365）

`isaac_devkit.output.setup_output` は ROS を介さずにシミュレーションデータを Python コールバックへ渡します。種別：`rgb`（uint8 `(H, W, 3)`）、`depth`（float32 `(H, W)`）、`joint_state`（`names` / `positions` / `velocities` / `efforts`）、`imu`（`lin_acc` / `ang_vel` / `orientation`、順序 `w, x, y, z`）。コンシューマが登録された種別だけ GPU から CPU へコピーします。`ISAAC_OUTPUT_MODE` がサポートする値は既定値の `python` のみです。`ros` を含む他の値を指定すると `ValueError` が発生します。ROS 出力は `isaac_ros_io` が `ISAAC_IO_PLUGIN` を通じて提供します（ADR-0025 は新しい決定に置き換えられました）。

```python
from isaac_devkit.output import CameraOutput, JointOutput, setup_output

out = setup_output(
    cameras=[CameraOutput("rgb", "/World/Robot/cam", 640, 480)],
    joint=JointOutput("/World/Robot"),
)
out.register(lambda frame: print(frame.kind, frame.stamp), kinds=["rgb", "joint_state"])
# per app.update():
out.step(sim_time_seconds)
```

## Cache レイアウト

すべての Isaac Sim runtime state は host 側の `${WS_PATH}/isaac-sim/` に永続化される。`WS_PATH` は repo root に解決されるため、checkout 内の `isaac-sim/` がこれに当たる。gitignore 済みで、`.dockerignore` により docker build context からも除外されている：

| Host | Container | 用途 |
|------|-----------|------|
| `isaac-sim/kit/cache` | `/isaac-sim/kit/cache` | Kit framework cache |
| `isaac-sim/kit/data` | `/isaac-sim/kit/data` | Kit app data（`user.config.json`、pipapi envs）|
| `isaac-sim/kit/logs` | `/isaac-sim/kit/logs` | Kit app logs |
| `isaac-sim/ov/cache` | `/home/${USER_NAME}/.cache/ov` | Omniverse cache（主に shader build 成果物）|
| `isaac-sim/ov/data` | `/home/${USER_NAME}/.local/share/ov/data` | Omniverse data |
| `isaac-sim/ov/logs` | `/home/${USER_NAME}/.nvidia-omniverse/logs` | Omniverse logs |
| `isaac-sim/pip` | `/home/${USER_NAME}/.cache/pip` | pip cache |
| `isaac-sim/nvidia/glcache` | `/home/${USER_NAME}/.cache/nvidia/GLCache` | GL shader cache |
| `isaac-sim/nvidia/computecache` | `/home/${USER_NAME}/.nv/ComputeCache` | CUDA compute cache |
| `isaac-sim/documents` | `/home/${USER_NAME}/Documents` | User Documents（USD scenes 等）|

2026-05-21 以前の layout（`cache/{kit,ov,pip,glcache,computecache}`、flat `logs/`、flat `data/`）はアップグレード後の初回 `./script/init_isaac_dirs.sh` 実行で新しい namespaced path に自動 migrate されます（issue #21 fix-A）。既存の shader / pip / compute cache は mv で保持されます。

Kit は `isaac-sim/documents/Kit/shared/screenshots` がまだ存在しない場合、mode 000 で作成する。`init_isaac_dirs.sh` はこれを 0755 で事前作成し、mode 000 になっているものは修復する。

container は health status を報告しない（`HEALTHCHECK NONE`）。NGC base image の check は Kit log を `App is loaded` で grep するが、これらの container は設計上 Kit なしで idle するため、すべて `unhealthy` と判定されていた。

初回 headless 起動時は shader compile に 1–3 分かかります；以降は cache hit で `< 30 秒` 起動。

## コンテナ User

コンテナは host UID と整合した非 root ユーザーで実行（`USER_NAME` は `.env` から読み取り、デフォルト UID 1000）。このユーザーはイメージの `isaac-sim` group に追加され、`/isaac-sim/*`（mode `0750`）が読み取り可能。`/home/${USER_NAME}/work`（host 側 `${WS_PATH}` に mount）経由で書いたファイルは host 側 owner を保持、`chown` 不要。

## EULA

`ACCEPT_EULA=Y` と `PRIVACY_CONSENT=Y` は `setup.toml [environment]` 経由で注入。注意：Isaac Sim 6.x は privacy consent を `OMNI_ENV_PRIVACY_CONSENT` から読む（この名前は 5.1 で採用され、5.1 より前の版とは異なる）；現在設定している `PRIVACY_CONSENT=Y` は無害だが実際には作用しません。telemetry opt-in したい場合は正しい変数名を設定してください。

## Smoke Tests

詳細は [doc/test/TEST.md](test/TEST.md) を参照。

すべてのテストはちょうど 1 つの範囲グループ（`core`、`gui`、`stream`、`headless`、`docs`）に属します。pytest モジュールは `pytestmark = pytest.mark.<グループ>`（1 グループだけ実行するには `pytest -m <グループ>`）、bats spec は `# bats file_tags=<グループ>` を書きます。グループのないテストは収集時に失敗します。`test/pytest-baseline.txt` にはグループごとの下限があります。件数は TEST.md のグループ表を参照。

stream グループの GPU ジョブ `stream-visual-e2e` は stream ステージを起動し、赤いテスト用キューブが映ったフレームを Chromium が継続して受信できることを確認します。

Workflow と job の命名規則は [doc/workflow-naming.md](workflow-naming.md) を参照。`script/ci/lint_workflow_names.py` が検査します。

## Python テストツールキット（devel-test ステージ）

`devel-test` ステージには `pytest`、`pyyaml`、`pytest-cov` が Isaac Sim 同梱の Python（`/isaac-sim/python.sh`）にインストールされており、consumer repos がコンテナ内で Python unit / integration test を実行できる。runtime `devel` ステージにはこれらの依存を入れないため、軽量なまま — テストツールのサイズコストは `devel-test` だけで負担する。

使い方：

```bash
just docker build -t test                                                 # devel-test ステージをビルド (compose service `test`)
just docker run -t test -- /isaac-sim/python.sh -m pytest test/unit/
just docker run -t test -- /isaac-sim/python.sh -m pytest --cov=<pkg> test/
```

システムの `python3` ではこれらのパッケージはインストールできない（Isaac base image の PEP 668 が `pip` をブロック）— 必ず `/isaac-sim/python.sh -m pytest ...` を使い、`pytest ...` は使わない。

GPU integration test（Isaac Sim の実起動が必要なもの、例: ヘッドレスの Jetbot 統合テスト）は `test` compose service で実行する。この service の NVIDIA GPU reservation は `setup.toml` の `["stage:devel-test"]` override（`"deploy.gpu_mode" = "force"`、base #493）に由来する:

```bash
just docker run -t test -- /isaac-sim/python.sh -m pytest \
    test/integration/
```

GPU ジョブは `test/integration/` 配下の両方のディレクトリからテストを収集する。

- [test/integration/pytest/](../test/integration/pytest/) — シーン、センサー、ドライバーの統合テスト。ヘッドレスの Jetbot サンプルも含む。
- [test/integration/no_ros/](../test/integration/no_ros/README.md) — Isaac が ROS モジュールを読み込まずに動作することを確認するテスト。

Kit は `app.close` 内でプロセスを直接終了することがあるため、Jetbot サンプルは stdout の `[BOOT OK]`、`[CAMERA PRIM OK]`、`[EXIT CLEAN]` などのマーカーを確認する。[テスト一覧](test/TEST.md)
