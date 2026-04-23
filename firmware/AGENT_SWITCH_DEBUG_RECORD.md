# Switch 固件调试记录（已验证状态，供 Agent / 人工查阅）

> **目的**：记录本次排障的**已证实结论**与**易错点**，避免后续会话误判为「VID/PID -only」或重复错误假设。  
> **最后验证**：用户确认 Windows / 手柄检测流程可完成（烟测通过）。

---

## 1. 已验证的环境与现象


| 项目   | 说明                                                                                 |
| ---- | ---------------------------------------------------------------------------------- |
| 板型   | Arduino IDE 中选 **Arduino Leonardo**（实物可为 ATmega32U4 / Pro Micro 类）                 |
| 库    | `NintendoSwitchControlLibrary` 1.3.1（本仓库根目录 `NintendoSwitchControlLibrary-1.3.1/`） |
| 症状 A | `joy.cpl` **无**游戏控制器；设备管理器里复合设备下 **仅有 `MI_00`**（串口）                                |
| 症状 B | Switch **不认**有线手柄（与 PC 侧无 HID 一致）                                                  |


---

## 2. 根因一（必须写进 sketch）：HID 注册时机

**事实**：库内 `SwitchControlLibrary()` 使用 **函数内 `static` 延迟初始化**。第一次调用发生在 `pushButton()` / 其它 API 内部。

**事实**：Arduino `main()` 在 `setup()` 之前执行 `USBDevice.attach()`，主机随即完成 **首次 USB 枚举**。若此时 `**SwitchControlLibrary` 的静态对象尚未构造**，则 `PluggableUSB` **尚未** `plug` HID，配置描述符里 **只有 CDC**。

**结果**：Windows 只枚举 **一个接口（串口）**，PnP 常见为 `**VID_xxxx&PID_xxxx&MI_00` 仅此一项**，`joy.cpl` 无手柄。

**本仓库烟测的修复**（**必须保留**）：在 `[switch_smoke_test/switch_smoke_test.ino](switch_smoke_test/switch_smoke_test.ino)` 中使用 **全局对象的构造函数**，在 `main()`（从而也在 `USBDevice.attach()`）**之前**调用 `(void)SwitchControlLibrary();`。

**勿犯的错误**（Agent 常见误判）：

- 认为「空 `setup()` + 只在 `loop()` 里 `pushButton`」足够——**不足**，易再次只有串口。  
- 认为问题仅是数据线 / Switch 菜单——在 **MI_00 only** 时应 **先** 怀疑 HID 未注册。  
- 删除或移动 `g_early_switch_hid` 全局初始化块。

**等价替代**（用户自有 sketch）：在 `**setup()` 第一行**立即调用一次 `pushButton`（上游示例 `collect-fossils.ino` 的做法），与主机枚举 **抢时间窗**；不如全局构造函数 **稳妥**。

---

## 2b. 热插拔配对：L+R 过后卡在「请按 A」

**现象**：系统已识别 L+R，但自动发的 **A** 无效。

**常见原因**：L+R 松开后 UI 尚未切到可接受 **A** 的状态；**过早**发 A 会被主机丢弃。

**本仓库做法**：`switch_pairing.h` 内：`**PairingInputWarmup()`**（中性报告连发、双摇杆微抖、ZL/ZR/LCLICK/RCLICK 轻点，**不按十字键**以免绘图里移格，**不按 A/B/X/Y**）→ **L+R 长按约 0.9s → 松开后等待约 2.4s → 仅一次 A 长按**。若热身仍不够，见下条 **软件重枚举**。

**首次枚举后必须物理拔插才过 L+R**：Arduino AVR 的 `USBDevice.detach()` **无实现**。在 `canvas_corners_tour` / `brush_grid_count_probe` 的 `**usb_soft_reconnect_avr.h`** 中：置 `**UDCON.DETACH**` 模拟从总线断开，再 `**USBDevice.attach()**`，让 Switch **重新枚举**（等价于你拔插一次）。默认在配对前执行；关闭：`#define RUN_SWITCH_USB_BUS_SOFT_RECONNECT 0`。仍失败可调长 `USB_SOFT_RECONNECT_DETACHED_MS` / `AFTER_ATTACH_MS`。

若仍失败，**加大**「松 L+R 之后到 A」的 `delay`，或先在**非绘图界面**完成配对。

---

## 3. 根因二（本机 Arduino 安装）：Leonardo 默认 VID/PID

**事实**：默认 `0x2341` / `0x8036` 时，部分 Windows / Switch 场景下 **手柄识别差**；社区常用 **HORI / Pokken** 运行态 `**0x0F0D` / `0x0092`** 及产品字符串。

**本机修改位置**（**非**仓库内文件，属用户 Arduino15 安装）：

- `%LOCALAPPDATA%\Arduino15\packages\arduino\hardware\avr\<版本>\boards.txt` 中 **Leonardo** 段  
- 备份名：`boards.txt.pre-tomodachi.bak`（若当时已创建）

**详细步骤与还原**：见 `[USB_VID_PID_patch.md](USB_VID_PID_patch.md)`。

**勿犯的错误**：

- 在未说明「用户是否已改 boards.txt」时，假定 **仅改 sketch** 即可在 Switch 上识别。  
- 直接修改仓库里的 `boards.txt`——Arduino **不会**读项目内的该文件；改的是 **Arduino15** 下包内文件。

---

## 4. 诊断命令（本机 PowerShell）

仓库内脚本（插板后运行，看是否 **仅有 MI_00**）：

- `[tools/list_vid_all.ps1](tools/list_vid_all.ps1)` — 列出 `VID_0F0D` 等节点  
- `[tools/list_vid.ps1](tools/list_vid.ps1)` — 精简 VID 过滤

**解读**：

- 健康：除串口外，还应有 **HID / 额外 MI_xx** 或 `joy.cpl` 可见手柄。  
- 异常：同一 `VID/PID` 下 **只有 `MI_00`** → 优先回到 **§2 HID 注册时机**。

---

## 5. 与文档索引


| 文档                                                                | 内容                              |
| ----------------------------------------------------------------- | ------------------------------- |
| `[docs/arduino_switch_setup.md](../docs/arduino_switch_setup.md)` | IDE、库路径、VID/PID、§2.1 **HID 注册** |
| `[USB_VID_PID_patch.md](USB_VID_PID_patch.md)`                    | boards.txt 补丁、joy.cpl/MI_00 说明  |
| 本文                                                                | **Agent 防错**：已验证因果链，勿删烟测全局初始化   |


---

## 6. 仍失败时的次要方向（未在本次逐一验证）

- 开发板管理器将 **Arduino AVR Boards** 降至库 README 提及的 **1.8.3** 附近。  
- 社区有 **Arduino IDE 1.8.x** 优于 2.x 的说法（以 GBATemp 等讨论为准）。  
- 数据线需 **数据传输** 能力。

---

**变更本烟测 sketch 时**：任何 PR / Agent 若移除 `EarlySwitchHidRegister` / `g_early_switch_hid`，须在 PR 说明中给出 **等价的「枚举前 HID 注册」** 方案，否则视为回归风险。