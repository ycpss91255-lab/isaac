# cmd_vel teleop in-kit SOP — OpenBase Chassis SE(2) Slide

> **LEGACY(2026-05-20 起)**:本 SOP 走的 in-kit Script Editor 路徑已不是預設,改走 **standalone-with-livestream**(`just docker exec -t headless /isaac-sim/python.sh <script>`)。
> 新 driver 一律走新 SOP `standalone_livestream_workflow.md`(對應 `adr/0005-standalone-with-livestream-as-default-dev-entrypoint.md`)。
> 本文件保留當歷史參考 / 偶爾需要 interactive REPL 偵錯時用。
> ADR-0002(本 SOP 對應的決策,已移至 isaac_physics_test)保留歷史紀錄;entrypoint pattern 的最新決策見 ADR-0005。

---

> ROS 2 `/cmd_vel` → Isaac Sim 5.1 內 OpenBase 平面移動的日常操作流程。
> 走 in-kit Script Editor + `rclpy` + `dc.set_rigid_body_linear_velocity` 路徑（**Chassis SE(2) Slide**，輪子不參與）。

---

## 為什麼選這條路（vs Action Graph 烤進 USD）

CoreSAM grill-with-docs Q1-Q4 grilling 後決定，路徑對照：

| 路徑 | Setup | Daily | NVIDIA 範例 | 5.1 真實阻擋 | 採用？ |
|---|---|---|---|---|---|
| (a-blackbox) Holonomic Controller + ArticulationController | Tools menu 一鍵 | 0 | 完整 | wheel 物理介入 → trajectory 受摩擦影響不等於 cmd_vel | 否 |
| (a-fake) Action Graph baked into USD + ROS2SubscribeTwist + WritePrimAttribute (physics:velocity) | 一次性 GUI | 0 | 零 | `physics:velocity` 連續寫 NVIDIA 無背書，可能只在 reset 讀 | 否 |
| (β) OmniGraph Script Node baked into USD + 自寫 Python 積分 | 中-高 | 點 trust dialog | 部分 | USD-embedded Python 安全 gating → daily 跳 prompt | 否 |
| **(γ) in-kit Script Editor + rclpy + dc velocity write** | 0（script 已存） | 1-2 分鐘 GUI | 完整 (M1 已驗) | 無 | **採用** |

(γ) 的代價是 daily 每次 kit launch 需點開 Script Editor 載 script + Run，**約 1-2 分鐘 GUI**。換得：
- 已驗穩定（M1 + 本 demo）
- NVIDIA 範例完整支援 (`omni.isaac.dynamic_control` API 標準路徑)
- 邏輯改動只動 Python，不動 USD

**長期出路**：Isaac Sim 6.0 GA 後可遷移到 OnImpulseEvent OmniGraph 純腳本路徑（NVIDIA 6.0 standalone tutorial 範本），daily GUI 步驟整個消失，本 MD 屆時可廢棄。

詳細詞彙 (Chassis SE(2) Slide / Upper-Layer Algorithm / Motion-Control Simulation) 見 isaac_physics_test 的 `src/doc/CONTEXT.md`。
決策依據見 isaac_physics_test 的 `src/doc/adr/0001-chassis-se2-slide-for-upper-layer-algorithm.md`。

---

## 前置條件

### 1. isaac docker image 已 build

```bash
cd isaac_ws/src/docker
just docker build         # 第一次 / 改 Dockerfile 後跑
```

### 2. OpenBase USD 在 `isaac_ws/src/model/usd/robot/openbase/openbase.usda`

```bash
ls /home/yunchien/workspace/coreSAM_ws/isaac_ws/src/model/usd/robot/openbase/openbase.usda
```

若缺少模型，請將 [asset_converter](https://github.com/ycpss91255-lab/asset_converter) 產出的 OpenBase USD 放在上述路徑。


### 3. fastdds.xml 設定檔存在

```bash
ls /home/yunchien/workspace/coreSAM_ws/isaac_ws/src/docker/config/ros2/fastdds.xml
```

跨 container DDS 需要這個 profile。

---

## 日常使用流程

### Step 1 — 啟 headless kit

```bash
cd /home/yunchien/workspace/coreSAM_ws/isaac_ws/src/docker

just docker stop                # 收掉殘留
just docker run -t headless -d  # 起 runheadless.sh -v
docker ps | grep headless       # 預期: yunchien-isaac-headless Up
```

kit + WebRTC ext 載完約 30-60 秒。等 `ss -tln | grep 8011` 出現 LISTEN 表示 WebRTC server ready。

### Step 2 — WebRTC client 連線

browser 開：

```
http://localhost:8011/streaming/webrtc-client
```

Server 欄填 `localhost`，Click **Connect**。首次連線編 shader 約 1-3 分鐘。

> 注意：port 是 **8011**，不是 8211。早期文件可能誤寫。

### Step 3 — 載 + 跑 cmd_vel script

WebRTC viewport 內：

1. **Window → Script Editor**（沒開的話）
2. **File → Open** → isaac_physics_test 的 `src/script/cmd_vel_planar_move.py`
3. **Ctrl+Enter** 跑

預期 Output：

```
[setup] opened /home/yunchien/work/src/model/usd/robot/openbase/openbase.usda
[setup] sunlight added
[setup] ground plane added (Isaac grid texture)
[setup] back_rim_joint: drive disabled
[setup] left_rim_joint: drive disabled
[setup] right_rim_joint: drive disabled
[setup] base_link: gravity disabled
[setup] debug cube (red) attached to base_link
[cmd_vel] subscribed /cmd_vel; initial cmd = (0.0, 0.0, w=0.0) — base 不會動，直到推 /cmd_vel
```

Stage panel 內應該看到 `/open_base/base_link/DebugCube`（紅色方塊）+ `/World/GroundPlane`（有 grid texture）。

### Step 4 — 啟 timeline

viewport 內**點空白 → 按 Spacebar**（或左側 ▶ 按鈕）強制 timeline play。

驗證：Property panel 點 base_link → Translate 區段 X/Y/Z 應該保持 (0, 0, 0)（cmd_vel 還是 0 → base 不動）。

### Step 5 — 推 fixed `/cmd_vel`

另開 host terminal：

```bash
docker run --rm --net=host --ipc=host \
    -e ROS_DOMAIN_ID=0 \
    -v /home/yunchien/workspace/coreSAM_ws/isaac_ws/src/docker/config/ros2/fastdds.xml:/isaac-sim/fastdds.xml:ro \
    -e FASTRTPS_DEFAULT_PROFILES_FILE=/isaac-sim/fastdds.xml \
    ros:humble bash -c 'source /opt/ros/humble/setup.bash && \
        ros2 topic pub /cmd_vel geometry_msgs/Twist \
            "{linear: {x: 0.5}}" -r 10'
```

預期：
- viewport 內紅色方塊沿 **+x 方向** 以 0.5 m/s 移動
- Script Editor Output 每 60 ticks 一行 `[tick N] cmd=(+0.50,...) pos=(+x.xx,+0.00,+0.00) lin=(+0.50,...)`
- Property panel base_link `Translate.X` 同步增加

停車：

```bash
docker run --rm --net=host --ipc=host -e ROS_DOMAIN_ID=0 \
    ros:humble bash -c 'source /opt/ros/humble/setup.bash && \
        ros2 topic pub /cmd_vel geometry_msgs/Twist "{linear: {x: 0.0}}" --once'
```

### Step 6 — teleop_twist_keyboard 互動式

```bash
docker run --rm -it --net=host --ipc=host \
    -e ROS_DOMAIN_ID=0 \
    -v /home/yunchien/workspace/coreSAM_ws/isaac_ws/src/docker/config/ros2/fastdds.xml:/isaac-sim/fastdds.xml:ro \
    -e FASTRTPS_DEFAULT_PROFILES_FILE=/isaac-sim/fastdds.xml \
    ros:humble bash -c 'apt update && apt install -y ros-humble-teleop-twist-keyboard && \
        source /opt/ros/humble/setup.bash && \
        ros2 run teleop_twist_keyboard teleop_twist_keyboard'
```

i/j/k/l/, 等鍵控 base 方向。

### Step 7 — 收尾

```bash
cd /home/yunchien/workspace/coreSAM_ws/isaac_ws/src/docker
just docker stop
```

---

## 驗證 checklist（demo 跑成的 expected behavior）

- [ ] `[setup]` 8 行全印（含 `gravity disabled` + `debug cube`）
- [ ] Step 5 推 cmd_vel 後 viewport 紅方塊 +x 方向 0.5 m/s 移動
- [ ] `[tick N] pos.x` 線性增加，60 ticks 約 +0.5（== 1s × 0.5 m/s）
- [ ] `ang=(+0.00, +0.00, +0.00)` 全程 — 輪子不參與
- [ ] `pos.z` 鎖在初始值（0 或 +0.02），**不下沉**
- [ ] Property panel base_link Translate.X 與 [tick N] pos.x 同步

---

## 故障排除

| 症狀 | 原因 | 修 |
|---|---|---|
| WebRTC 連不上 localhost:8011 | kit 還沒 ready | 等 30-60s，`ss -tln \| grep 8011` 確認 LISTEN |
| `[exec] Container '...' is not running` | `just docker run` 沒帶 `-d`，跑成 `compose run --rm` 一次性 | `just docker stop && just docker run -t headless -d` |
| 看不到 base | base 跑出 camera 視野 | Stage panel 點 base_link → viewport 按 **F** focus |
| pos.x = 0 + lin = 0 + ticks 持續增加 | timeline 沒 play | viewport 按 Spacebar |
| pos.x = 0 + lin = 0 + USD_PATH 是 `openbase_free.usda` | articulation root blocks dc velocity write | USD_PATH 用 `model/usd/robot/openbase/openbase.usda` (root free rigid body)；script 已 hardcode |
| pos.z 持續下沉 | gravity 在 PhysX substep 累積 | script 已加 `disable gravity on base_link`，重 Run 確認 setup log 有 `base_link: gravity disabled` |
| 推 cmd_vel 但 base 不動 | ROS_DOMAIN_ID / fastdds.xml profile 不一致 | 確認 sibling container 跟 isaac container 用同 DOMAIN_ID + 同 fastdds.xml |

---

## 重做時機

- **模型改動**：更新 `openbase.usda`；script 在 setup 時會重新建立環境。
- **Isaac Sim 升 6.0 GA** → 遷移到 OnImpulseEvent OmniGraph 純腳本路徑（NVIDIA 6.0 standalone tutorial），整個 Step 3 / Step 4 GUI 操作消失，本 MD **可廢棄**

---

## 已知缺陷

1. **每次 kit launch 需手動 Script Editor 載 + Ctrl+Enter**（無法 auto-load via kit CLI flag，沒找到對應的 startup args）— 6.0 GA 才能解
2. 若 USD 的 `base_link` 沒有 visual mesh，畫面上只會看見 debug cube。
3. **WebRTC port 不固定**：早期文件寫 8211，實機是 8011；任何 port 衝突要查 kit log 內 `0.0.0.0:NNNN` listening 字樣
4. **無 follow camera**：base 跑遠了要手動按 F focus；可加 follow camera tick callback 修

---

## 參考

- isaac_physics_test `src/doc/CONTEXT.md` — 詞彙表（Chassis SE(2) Slide / Upper-Layer Algorithm / Motion-Control Simulation）
- isaac_physics_test `src/doc/adr/0001-chassis-se2-slide-for-upper-layer-algorithm.md` — 決策依據
- `action_graph_setup.md` — 原規劃的 Action Graph baked into USD 路徑，grilling 後**棄用**，本 MD 取代
- `ros2_pubsub_smoke.md` — M1 純 ROS 2 bridge 通訊驗證
- isaac_physics_test `src/script/cmd_vel_planar_move.py` — 本 MD 對應 script
- isaac_physics_test `src/script/move_openbase_planar.py` — hardcoded CMD 版（離線本地驗證 fallback）
- isaac_physics_test `src/script/move_openbase_planar_standalone.py` — standalone python.sh 版（no-ROS terminal-only 驗證）

### 上游文件

- [Isaac Sim 6.2 Mobile Robot Controllers](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/robot_simulation/mobile_robot_controllers.html)
- [Isaac Sim 6.2 Known Issues](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/overview/known_issues.html)
- [Isaac Sim 6.2 ROS 2 Bridge in Standalone Workflow](https://docs.isaacsim.omniverse.nvidia.com/6.2.0/ros2_tutorials/tutorial_ros2_python.html)
- [gazebo_planar_move_plugin (ROS 2 Humble)](https://docs.ros.org/en/ros2_packages/humble/api/gazebo_planar_move_plugin/) — 參考的 kinematic 平移語意
