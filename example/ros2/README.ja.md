# example/ros2 -- アプリ側 ROS 2 テンプレート

これらの ROS 2 Humble ノードは Isaac シーンのカメラ画像を購読し、`/cmd_vel` に速度指令を配信します。

これが「ROS 2 デフォルトの双方向トポロジー」を構造として体現したもの
（ADR-0017 第 6 節）です。フレームワークが Isaac 側のブリッジ配線を担い、
アプリのロジックはこちらの標準 ROS 2 パッケージに置きます。

言語を選べるよう、2 つのテンプレートを用意しています。

| パッケージ | Build type | 言語 | ノード |
|---|---|---|---|
| [`src/example_app_py`](src/example_app_py/) | `ament_python` | Python | `camera_subscriber`、`cmd_vel_publisher` |
| [`src/example_app_cpp`](src/example_app_cpp/) | `ament_cmake` | C++ | `camera_subscriber`、`cmd_vel_publisher` |

どちらも「最小限だが本物」です。colcon でビルドでき、`ament_lint` がクリーン
です。1 つコピーして名前を変え、ノードの中身を自分のロジックに置き換えて
ください。

## トピック

次の表はノードのデフォルト値です。シーンのカメラが別の名前空間を使う場合は、`camera_topic` にその画像トピックを指定してください。例えば Jetbot の統合テスト用シーンでは `/jetbot/camera/color/image_raw` を使います。

| 方向 | トピック | 型 | ROS 2 パラメータ |
|---|---|---|---|
| Isaac -> アプリ（inbound） | `/camera_bot/camera/color/image_raw` | `sensor_msgs/Image` | `camera_topic` |
| アプリ -> Isaac（outbound） | `/cmd_vel` | `geometry_msgs/Twist` | `cmd_vel_topic` |

## 前提条件

- Docker（サンプルは公式 `ros:humble` イメージ内で実行するので、ホストに
  ROS 2 をインストールする必要はありません）。

## ビルド

このディレクトリ（`example/ros2/`）で実行します。

```bash
docker run --rm -v "$PWD":/ws -w /ws ros:humble \
  bash -c 'source /opt/ros/humble/setup.bash && colcon build'
```

`colcon` は `src/` 配下の 2 パッケージを検出してビルドします。成果物は
`build/`、`install/`、`log/`（いずれも gitignore 済み）に出力されます。

## Lint とテスト

`ament_lint` は `colcon test`（標準 ROS 2 の流れ）で実行します。

```bash
docker run --rm -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  colcon build &&
  colcon test &&
  colcon test-result --all'
```

クリーンな実行は `0 errors, 0 failures` を報告します（C++ の `cppcheck`
linter は base イメージにオプションツールが無いため skip されます -- これは
skip であり failure ではありません）。

## Isaac シーンに接続する

ノードと同じ DDS ドメインで、カメラ画像を配信して速度指令を購読するシーンを起動します。デフォルトのトピックを使う場合は次を実行します。

```bash
docker run --rm --net=host -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  source install/setup.bash &&
  ros2 run example_app_py camera_subscriber'
```

カメラフレームを受信するたびに `[FRAME OK]` のログが 1 行出ます。別の
コンテナで動作指令を配信します。

```bash
docker run --rm --net=host -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  source install/setup.bash &&
  ros2 run example_app_py cmd_vel_publisher'
```

`[CMD_VEL OK]` の各行はノードが Twist を配信したことを示します。C++ パッケージでも同じパラメータを使います。
`ros2 run example_app_cpp camera_subscriber` /
`ros2 run example_app_cpp cmd_vel_publisher`。

Isaac と ament のコンテナ間の往復テストは `isaac_ros_io` に移りました（isaac#276）。
このテンプレートはホスト側の CI で `colcon build` と `ament_lint` を使って検証します。

## 自分用にする

1. `src/example_app_py` または `src/example_app_cpp` を自分の名前にコピー
   します。
2. パッケージ名を変更します。ディレクトリ、`package.xml` の `name`、
   さらに（Python）`setup.py` の `package_name` ／内側のモジュール
   ディレクトリ、または（C++）`CMakeLists.txt` の `project()`。
3. `camera_topic` と `cmd_vel_topic` にシーンで使うトピックを指定します。
4. ノードの中身を自分のアプリロジックに置き換えます。

## ライセンス

Apache-2.0。[LICENSE](../../LICENSE) を参照してください。

## 翻訳

- [English](README.md)
- [繁體中文](README.zh-TW.md)
- [简体中文](README.zh-CN.md)
- [日本語](README.ja.md)
