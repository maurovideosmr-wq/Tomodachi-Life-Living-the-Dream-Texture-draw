# Arduino + NintendoSwitchControlLibrary 操作说明

本仓库在根目录包含第三方库：`[NintendoSwitchControlLibrary-1.3.1](../NintendoSwitchControlLibrary-1.3.1/)`（MIT）。上游文档以日语为主，见其中 [README.md](../NintendoSwitchControlLibrary-1.3.1/README.md)。

## 1. 让 Arduino IDE 能找到库

IDE **不会**自动扫描本仓库根目录，任选其一：

**方式 A（推荐）**  

1. 将整个文件夹 `NintendoSwitchControlLibrary-1.3.1` **复制**到：
  `文档\Arduino\libraries\`
2. 重启 Arduino IDE（或 **工具 → 管理库** 刷新后，在 **文件 → 示例** 里应出现 `NintendoSwitchControlLibrary`）。

**方式 B**  

1. 把 `NintendoSwitchControlLibrary-1.3.1` 打成 **ZIP**
2. **项目 → 导入库 → 添加 ZIP 库…** 选中该 ZIP。

> 文件夹内必须有 `library.properties`（本库已具备）。文件夹名带版本号也可以。

## 2. 选择开发板与端口

1. USB 将 **Pro Micro / Leonardo** 接到 **PC**（烧录只走 PC，不要插 Switch）。
2. **工具 → 开发板**：
  - 先试 **Arduino Leonardo**（与 ATmega32U4 + 本库常见搭配）。  
  - 若为 SparkFun Pro Micro 且 Leonardo 上传失败，安装 **SparkFun AVR Boards** 后选对应 **Pro Micro**（处理器 5V/16MHz 按你板子丝印）。
3. **工具 → 端口**：选择出现的 COM 口。
4. 上传失败时：Pro Micro 可 **快速按两次 RST** 进入引导，再立刻点上传。

## 2.1 Windows / Switch 只认串口、不认手柄（重要）

默认 Leonardo 的 USB VID/PID（`0x2341` / `0x8036`）下，**设备管理器里只有 COM、joy.cpl 没有手柄** 的情况较常见，**Switch 也可能不认**。

社区做法（与 GBATemp / Pokken 手柄教程一致）是：把 **运行态** USB 改成 **HORI** 标识（`0x0F0D` / `0x0092`）及对应产品字符串。本仓库说明与备份/还原步骤见：

`**[firmware/USB_VID_PID_patch.md](../firmware/USB_VID_PID_patch.md)`**

修改 `boards.txt` 后必须 **重启 IDE**，再 **重新上传** 烟测 sketch，然后 **拔插 USB** 再测 `joy.cpl` / Switch。

**若已改 VID/PID 仍只有 COM、设备管理器里复合设备下仅 `MI_00`**：多半是 **HID 未在枚举前注册**。库内 `SwitchControlLibrary()` 为延迟初始化，必须在 **`USBDevice.attach()` 之前**触发一次（本仓库烟测用全局构造函数处理）；勿把第一次 `pushButton` 只放在很久以后的 `loop()` 里。

若仍异常：开发板管理器将 **Arduino AVR Boards** 降到 **1.8.3**；部分教程建议用 **Arduino IDE 1.8.x** 搭配本库。

## 3. 打开并上传烟测 sketch

1. **文件 → 打开**，选择本仓库：
  `[firmware/switch_smoke_test/switch_smoke_test.ino](../firmware/switch_smoke_test/switch_smoke_test.ino)`
2. 点击 **上传**。
3. 编译错误若提示找不到 `NintendoSwitchControlLibrary.h`，说明第 1 步库未装进 `libraries`。

## 4. 在 Switch 上验收

1. 从 PC **拔掉** USB，插入 **Switch**（主机或底座）。
2. **设置 → 手柄与传感器**（或手柄配对界面）中确认 **有线控制器** 被识别。
3. 进入任意会响应 **A 键** 的菜单：应约 **每 3 秒** 有一次 A（烟测逻辑在 `loop()` 里）。

若完全不响应：换数据线、换 USB 口、确认开发板型号与库文档推荐的 **Leonardo** 是否一致；上游 README 写明 **非 Leonardo 不予支持**，Pro Micro 为自行承担兼容性。

## 5. 与本项目贴图流水线的关系

烟测通过后，可在同一库 API 上增加：`pushHat` / `tiltLeftStick` 等与贴图模式一致的输入序列；`indices.bin` 需通过 **PROGMEM/压缩或换大 Flash 板** 等方式纳入固件（见 `[canvas_home_test.md](canvas_home_test.md)` 与 `[texture_prep.md](texture_prep.md)`）。

## 参考链接

- 上游仓库：[https://github.com/lefmarna/NintendoSwitchControlLibrary](https://github.com/lefmarna/NintendoSwitchControlLibrary)  
- 作者博客（环境搭建，日语）：README 中的 pokemonit 链接

---

**已验证排障记录（含 HID 注册时机、MI_00 诊断、勿删烟测全局初始化）**：[../firmware/AGENT_SWITCH_DEBUG_RECORD.md](../firmware/AGENT_SWITCH_DEBUG_RECORD.md)