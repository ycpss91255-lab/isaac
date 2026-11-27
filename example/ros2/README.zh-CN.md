# example/ros2 -- 应用端 ROS 2 模板

这些 ROS 2 Humble 节点订阅 Isaac 场景的相机图像，并通过 `/cmd_vel` 发布速度指令。

这就是「ROS 2 默认双向拓扑」在结构上的体现（ADR-0017 第 6 节）：框架负责
Isaac 端的桥接 wiring；你的应用逻辑写在这边的标准 ROS 2 包里。

提供两种模板让你挑语言：

| 包 | Build type | 语言 | 节点 |
|---|---|---|---|
| [`src/example_app_py`](src/example_app_py/) | `ament_python` | Python | `camera_subscriber`、`cmd_vel_publisher` |
| [`src/example_app_cpp`](src/example_app_cpp/) | `ament_cmake` | C++ | `camera_subscriber`、`cmd_vel_publisher` |

两种模板都「精简但真实」：可被 colcon 构建、`ament_lint` 干净。复制一份、
改名、把节点内容换成你自己的逻辑即可。

## Topic

下表列出节点的默认值。如果场景使用其他相机命名空间，请将 `camera_topic` 设为对应的图像 topic，例如 Jetbot 集成测试场景的 `/jetbot/camera/color/image_raw`。

| 方向 | Topic | 类型 | ROS 2 参数 |
|---|---|---|---|
| Isaac -> 应用（inbound） | `/camera_bot/camera/color/image_raw` | `sensor_msgs/Image` | `camera_topic` |
| 应用 -> Isaac（outbound） | `/cmd_vel` | `geometry_msgs/Twist` | `cmd_vel_topic` |

## 前置需求

- Docker（示例都在官方 `ros:humble` image 内执行，host 不需要装
  ROS 2）。

## 构建

在本目录（`example/ros2/`）执行：

```bash
docker run --rm -v "$PWD":/ws -w /ws ros:humble \
  bash -c 'source /opt/ros/humble/setup.bash && colcon build'
```

`colcon` 会在 `src/` 下找到两个包并构建。产物落在 `build/`、`install/`、
`log/`（皆已 gitignore）。

## Lint 与测试

`ament_lint` 通过 `colcon test` 执行（标准 ROS 2 流程）：

```bash
docker run --rm -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  colcon build &&
  colcon test &&
  colcon test-result --all'
```

干净的执行会报告 `0 errors, 0 failures`（C++ 的 `cppcheck` linter 会被
skip，因为 base image 没有那个可选工具 -- 那是 skip，不是 failure）。

## 连接 Isaac 场景

在与节点相同的 DDS domain 启动会发布相机图像并订阅速度指令的场景。如果使用默认 topic，请运行：

```bash
docker run --rm --net=host -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  source install/setup.bash &&
  ros2 run example_app_py camera_subscriber'
```

每收到一张相机图像，你会看到一行 `[FRAME OK]` log。在另一个容器发布
运动指令：

```bash
docker run --rm --net=host -v "$PWD":/ws -w /ws ros:humble bash -c '
  source /opt/ros/humble/setup.bash &&
  source install/setup.bash &&
  ros2 run example_app_py cmd_vel_publisher'
```

每一行 `[CMD_VEL OK]` 表示节点已发布一条 Twist。C++ 包使用相同的参数：
`ros2 run example_app_cpp camera_subscriber` /
`ros2 run example_app_cpp cmd_vel_publisher`。

CI 在托管的 ROS 容器内用 `colcon build` 和 `ament_lint` 验证这些模板。

## 改成你自己的

1. 把 `src/example_app_py` 或 `src/example_app_cpp` 复制成你自己的名字。
2. 改包名：目录、`package.xml` 的 `name`，以及（Python）`setup.py` 的
   `package_name` ／内层模块目录，或（C++）`CMakeLists.txt` 的
   `project()`。
3. 将 `camera_topic` 和 `cmd_vel_topic` 设为场景使用的 topic。
4. 把节点内容换成你的应用逻辑。

## 许可

Apache-2.0。见 [LICENSE](../../LICENSE)。

## 翻译

- [English](README.md)
- [繁體中文](README.zh-TW.md)
- [简体中文](README.zh-CN.md)
- [日本語](README.ja.md)
