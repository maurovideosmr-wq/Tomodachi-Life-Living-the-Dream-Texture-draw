# Tomodachi Life: Living the Dream — 贴图绘制 / Texture draw

**中文** 用 **Arduino Pro Micro / Leonardo**（ATmega32U4）在 PC 上伪装为 **USB 手柄**，向 Switch 自动执行游戏内 256×256 格贴图/线稿操作。  
**EN** A **Pro Micro or Leonardo**-class board emulates a **USB gamepad** to drive in-game 256×256 **bitmap** or **vector line-art** painting on *Tomodachi Life: Living the Dream* (Switch).

**仓库导航** [中文说明](#中文) · [README in English](#english)

---

## 中文

### 这是什么，你需要什么

- **一块开发板**：常见为 **SparkFun Pro Micro** 或 **Arduino Leonardo**（需 **ATmega32U4**，能模拟键盘/手柄的 USB 功能）。只有 **串口、没有“手柄”** 时，请看 [firmware/USB_VID_PID_patch.md](firmware/USB_VID_PID_patch.md) 与 [docs/arduino_switch_setup.md](docs/arduino_switch_setup.md#21-windows--switch-只认串口不认手柄重要)。
- **一台 Windows PC（推荐）**：用来装 [Arduino IDE](https://www.arduino.cc/en/software) 和跑 Python 预处理脚本；**烧录只接电脑**，**不要**在烧录时把板子插 Switch。
- **一根能传数据的数据线**（不是纯充电线）。
- 本游戏支持 **线稿/单色素描** 式贴图；本仓库提供 **位图** 与 **SVG 线稿** 两条固件，以及图形工具链。

更细的库安装、板型、COM 口、两次 RST 进引导、Switch 上验收等，见 **[docs/arduino_switch_setup.md](docs/arduino_switch_setup.md)**。

### 给「只买了一块板」的极简流程

下面按**第一次接触 Arduino** 的假设来写；你已有环境可跳步。

1. **装 IDE**
  安装 Arduino IDE 1.8 或 2.x。若与第三方库严重冲突，可换 **1.8.x**（见 [arduino_switch_setup](docs/arduino_switch_setup.md) 文末说明）。
2. **接电脑**
  用数据线把板子插到 PC。设备管理器里应出现 **端口 (COMx)**。没有 COM：换线、换 USB 口、装驱动（板子商说明）。
3. **装本仓库里的手柄库**
  将仓库根目录的 `**NintendoSwitchControlLibrary-1.3.1`** 整个文件夹**复制**到：  
   `文档\Arduino\libraries\`（或你 IDE 首选项里显示的 sketchbook 下的 `libraries`）。  
   **完全退出再打开** Arduino IDE。
4. **选板与端口**
  - **工具 → 开发板**：先试 **Arduino Leonardo**；若你是 SparkFun Pro Micro 且需专用板定义，可安装 [SparkFun AVR Boards](https://github.com/sparkfun/Arduino_Boards) 后选对应 Pro Micro（电压/频率按你板子丝印）。  
  - **工具 → 端口**：选出现的 **COMx**。
5. **烟测（强烈建议先做一次）**
  在 IDE 中 **文件 → 打开**  
   `firmware/switch_smoke_test/switch_smoke_test.ino`，点 **上传**。  
   若失败：对 Pro Micro **快速连按两次 RST** 进入引导，在几秒内再点上传。  
   成功后，把线从 PC 拔下，插到 **Switch**，在**设置 → 手柄**里应能识别**有线控制器**；进入游戏后烟测会周期性按 A（见 sketch 内说明）。  
   不响应：线、口、板型、以及文档里的 **VID/PID / HID** 说明。
6. **准备贴图数据（在 PC 上，不是 Switch）**
  - 安装 Python 3，在终端进入 `scripts/texture_prep`，执行：  
   `pip install -r requirements.txt`  
  - 运行 **图形界面**：`python gui_app.py`（一个窗口、**位图** 与 **矢量** 两个 Tab）。  
  - **位图 Tab**：打开 **正方形 PNG**（或按 `docs/texture_prep.md` 用 CLI）→ 导出 `draw_data.h` → 覆盖到  
  `firmware/paint_mono_flash/draw_data.h`。  
  - **矢量 Tab**：打开含 `<path>` 的 **线稿 SVG** → 导出 `draw_vector_data.h` → 覆盖到  
  `firmware/paint_vector_flash/draw_vector_data.h`。
7. **烧录贴图固件**
  - 单色位图：打开并上传 `firmware/paint_mono_flash/paint_mono_flash.ino`（**不要**和烟测/其它 sketch 同时混在一个窗口里改乱）。  
  - 矢量线稿：打开并上传 `firmware/paint_vector_flash/paint_vector_flash.ino`。
8. **进游戏**
  **先在游戏里选好一种颜色**，再进入贴图中心；固件**不负责换色**，只负责走位与落笔。详细参数与排障见 **[docs/texture_prep.md](docs/texture_prep.md)**。
9. **排障与进阶**
  手柄枚举、只认串口、调试记录等：**[firmware/AGENT_SWITCH_DEBUG_RECORD.md](firmware/AGENT_SWITCH_DEBUG_RECORD.md)**（偏技术）。

### 目录结构（概览）


| 路径                                               | 说明                                                                                                                 |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| `firmware/`                                      | 烟测 `switch_smoke_test`、探针/巡游类 sketch、**位图** `paint_mono_flash`、**矢量** `paint_vector_flash` 等；排障与 USB 说明见同目录下 `.md` |
| `scripts/`                                       | 色板工具 `palette_extract/`、`**texture_prep/`**（`gui_app.py` 双 Tab、`svg_compiler.py`）                                  |
| `assets/reference/`                              | 参考色板、示例 `texturemap.png` 等（根目录不堆放杂文件）                                                                              |
| `assets/generated/` / `processed/` / `textures/` | 生成色表、预处理输出、贴图相关资源                                                                                                  |
| `docs/`                                          | **[arduino_switch_setup.md](docs/arduino_switch_setup.md)**、**[texture_prep.md](docs/texture_prep.md)** 等          |
| `NintendoSwitchControlLibrary-1.3.1/`            | 第三方 Nintendo Switch 手柄库（**v1.3.1**，见下方[致谢](#第三方库与致谢--third-party-credits)）；需放入 Arduino `libraries` |


### 另见

- 完整预处理与命令行： **[docs/texture_prep.md](docs/texture_prep.md)**  
- 库与线材、VID/PID： **[docs/arduino_switch_setup.md](docs/arduino_switch_setup.md)**、**[firmware/USB_VID_PID_patch.md](firmware/USB_VID_PID_patch.md)**

---

## English

### What this is and what you need

- **Board**: A **Pro Micro** or **Leonardo**-class **ATmega32U4** board that can present as a **USB gamepad** to the Switch. If Windows only shows a **serial (COM) port** and no gamepad, read **[firmware/USB_VID_PID_patch.md](firmware/USB_VID_PID_patch.md)** and **[docs/arduino_switch_setup.md](docs/arduino_switch_setup.md)** (section on HID / VID&PID).
- **A Windows PC** for Arduino IDE and optional Python tools; **flash firmware while connected to the PC**, not to the Switch.
- **A data-capable USB cable** (not charge-only).
- The game supports a **single-color / line-art** style canvas; this repo ships **bitmap** and **vector (SVG)** pipelines plus GUI helpers.

### Minimal path for a first-time buyer

1. **Install** [Arduino IDE](https://www.arduino.cc/en/software) (1.8 or 2.x; use 1.8.x if you hit library/AVR quirks—see the docs above).
2. **Plug the board in**; you should see a **COM port** in Device Manager. If not, try another cable/port or board-specific drivers.
3. **Install the bundled library**: copy the folder `**NintendoSwitchControlLibrary-1.3.1`** from the repo root into your Arduino user `**libraries**` directory (e.g. `Documents\Arduino\libraries\` on Windows), then **restart** the IDE.
4. **Select board and port**: e.g. **Tools → Board → Arduino Leonardo** (or your vendor’s Pro Micro package if needed). **Tools → Port → the COM port** shown.
5. **Smoke test (recommended first)**: open `**firmware/switch_smoke_test/switch_smoke_test.ino`**, **Upload**. On Pro Micro, **double-tap RESET** to enter the bootloader if upload fails, then upload again. After success, move the USB cable to the **Switch** and check **System Settings → Controllers** for a wired controller; the sketch should emit periodic A presses. If nothing works, follow the **cable / board / HID** notes in the linked docs.
6. **Prepare art on the PC**: install Python 3, `cd scripts/texture_prep`, `pip install -r requirements.txt`, run `python gui_app.py`. Use the **Bitmap** tab → export `draw_data.h` → replace `**firmware/paint_mono_flash/draw_data.h`**, *or* the **Vector** tab / CLI → `draw_vector_data.h` → `**firmware/paint_vector_flash/draw_vector_data.h*`*. Full detail: **[docs/texture_prep.md](docs/texture_prep.md)**.
7. **Flash the painting firmware**: open `**firmware/paint_mono_flash/paint_mono_flash.ino`** *or* `**firmware/paint_vector_flash/paint_vector_flash.ino*`* and upload the one you need.
8. **In-game**: **Pick a color first**, then open the 256×256 painting mode; the firmware does **not** change the palette, only movement and paint timing.
9. **Troubleshooting / deep dives**: **[firmware/AGENT_SWITCH_DEBUG_RECORD.md](firmware/AGENT_SWITCH_DEBUG_RECORD.md)** (technical).

### Repository layout (summary)


| Path                                           | Purpose                                                                                           |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `firmware/`                                    | Smoke test, grid probes, `**paint_mono_flash`**, `**paint_vector_flash**`, and firmware-side docs |
| `scripts/`                                     | Palette tools, `**texture_prep/**` ( `**gui_app.py**`, `**svg_compiler.py**` )                    |
| `assets/reference/`                            | Reference captures and sample **texturemap** image                                                |
| `assets/generated/`, `processed/`, `textures/` | Generated palettes, preprocessed output, texture assets                                           |
| `docs/`                                        | **Arduino + Switch** setup, **texture / vector** workflow                                         |
| `NintendoSwitchControlLibrary-1.3.1/`          | Vendored Switch gamepad library (**v1.3.1**; see [Third-party credits](#第三方库与致谢--third-party-credits)); under Arduino `libraries` |


### See also

- **Workflow & CLI:** **[docs/texture_prep.md](docs/texture_prep.md)**  
- **Environment & USB quirks:** **[docs/arduino_switch_setup.md](docs/arduino_switch_setup.md)**, **[firmware/USB_VID_PID_patch.md](firmware/USB_VID_PID_patch.md)**

## 第三方库与致谢 / Third-party credits

**中文** 随仓库附带的 **`NintendoSwitchControlLibrary-1.3.1/`** 来自上游 **[NintendoSwitchControlLibrary](https://github.com/lefmarna/NintendoSwitchControlLibrary)**（本副本 **v1.3.1**）。著作权归原作者，以 **MIT** 再分发，完整条款见 [`NintendoSwitchControlLibrary-1.3.1/LICENSE`](NintendoSwitchControlLibrary-1.3.1/LICENSE)（Copyright © 2021 **lefmarna**；Copyright © 2019 **celclow**）。感谢作者维护该库。

**EN** The bundled **`NintendoSwitchControlLibrary-1.3.1/`** is a vendored copy (**v1.3.1**) of **[NintendoSwitchControlLibrary](https://github.com/lefmarna/NintendoSwitchControlLibrary)**. It is redistributed under the **MIT License**; see [`NintendoSwitchControlLibrary-1.3.1/LICENSE`](NintendoSwitchControlLibrary-1.3.1/LICENSE) (Copyright © 2021 **lefmarna**; Copyright © 2019 **celclow**). Thanks to the authors for maintaining the library.

