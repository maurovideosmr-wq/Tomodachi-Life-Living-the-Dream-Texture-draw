# Leonardo USB 标识（VID/PID）补丁说明

**完整调试因果（含「仅 MI_00 = HID 未注册」）**：[AGENT_SWITCH_DEBUG_RECORD.md](AGENT_SWITCH_DEBUG_RECORD.md)

## 原因

默认 **Arduino Leonardo** 使用 `0x2341` / `0x8036`。在 Windows 上有时 **只出现串口、不出现游戏控制器**；**Nintendo Switch** 也常依赖与第三方有线手柄兼容的 USB 标识才能稳定识别。

社区为 **NintendoSwitchControlLibrary** 准备的常见做法是：把 **运行态** USB 改为 **HORI / Pokken** 一类手柄的 VID/PID（与 GBATemp、JoyCon 库教程一致）：

- **VID**: `0x0F0D`
- **PID**: `0x0092`
- **产品字符串**: Pokken Pro Pad（见 `boards.txt` 中 `build.usb_product`）

**引导程序（bootloader）** 仍为 `0x2341` / `0x0036`，不影响 Arduino IDE 双击 RST 上传。

## 本机已做的修改

若你使用 Agent 在本机执行过补丁，则已对：

`%LOCALAPPDATA%\Arduino15\packages\arduino\hardware\avr\<版本>\boards.txt`

中 **Arduino Leonardo** 段落的下列项做过替换（并留有备份 `boards.txt.pre-tomodachi.bak`）：

- `leonardo.vid.1` / `leonardo.pid.1`
- `leonardo.upload_port.1`（与运行态枚举一致，便于 IDE 找端口）
- `leonardo.build.vid` / `leonardo.build.pid` / `leonardo.build.usb_product`
- 新增 `leonardo.build.usb_manufacturer`

## joy.cpl 仍只有串口、PnP 只有 `MI_00`（无第二接口）

常见原因不是 VID/PID，而是 **HID 注册太晚**：`SwitchControlLibrary()` 在库内是「函数内 static」，若第一次调用在 `loop()` 里，会晚于 `USBDevice.attach()` 后的主机枚举，配置描述符里**只有 CDC**，Windows 就只剩 COM。

**烟测 sketch** 已用「全局构造函数在 `main()` 之前调用 `SwitchControlLibrary()`」修复；若你自有 sketch，请在 `**#include` 之后、`setup` 之前**加入同样模式，或在 `**setup()` 最开头**立刻调用一次 `pushButton`（官方示例 `collect-fossils.ino` 即在 `setup` 里先 `pushButton` 抢时间窗）。

## 你需要做的

1. **完全退出并重新打开 Arduino IDE**（让 `boards.txt` 重新加载）。
2. 仍选 **工具 → 开发板 → Arduino Leonardo**，**重新编译并上传** `[switch_smoke_test.ino](switch_smoke_test/switch_smoke_test.ino)`。
3. 拔掉重插 USB，在 **设备管理器** 中应能看到与 **HORI / Pokken** 相关的 **HID / 游戏控制器**；`joy.cpl` 也可能出现手柄。
4. 再插 **Switch** 试有线识别。

## 恢复原厂 Leonardo USB 标识

将同目录下的备份拷回：

```text
copy /Y boards.txt.pre-tomodachi.bak boards.txt
```

然后重启 IDE、重新上传任意 sketch（会恢复为默认 Arduino USB 描述）。

## 若仍异常

1. **开发板管理器** 将 **Arduino AVR Boards** 降到库 README 推荐的 **1.8.3** 再试（部分用户报告 **1.8.6+ / IDE 2.x** 与复合 HID 行为异常）。
2. 有教程建议改用 **Arduino IDE 1.8.x** 做该库开发（见 GBATemp 讨论）。

