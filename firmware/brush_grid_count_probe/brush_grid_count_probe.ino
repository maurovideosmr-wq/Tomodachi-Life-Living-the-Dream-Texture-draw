/**
 * 画布网格：慢速「一格一格」十字键，便于数步数定默认画笔 (row,col)。
 *
 * 使用前：进入贴图绘制，画笔在默认中心；板子插 Switch。
 * 流程：上电约 2s → **软件 USB 重枚举**（模拟拔插，见 usb_soft_reconnect_avr.h）→ **L+R、A** 配对窗 → 再 5s 后十字键。
 *        若插线不再弹窗：`RUN_SWITCH_CONTROLLER_PAIRING 0`。若重枚举干扰 PC 调试：`RUN_SWITCH_USB_BUS_SOFT_RECONNECT 0`。
 *
 * 在文件顶部 **二选一** 只保留一个 #define PROBE_* 为 1：
 *   PROBE_LEFT_COLUMN  — 向左数，直到最左列，步数 = 默认列号 col0（0..255）
 *   PROBE_UP_ROW       — 向上数，直到最上行，步数 = 默认行号 row0（0..255）
 *
 * 数法：从第一次光标移动开始数 1，每到新格 +1，到撞边停；与 docs/canvas_home_test.md 一致。
 *
 * 注意：若游戏「一次点按移动多格」，本计数无效，需改用手柄长按或摇杆方案（见文档）。
 *
 * 依赖：NintendoSwitchControlLibrary + Leonardo HID 早注册（同 smoke_test）。
 */
#include <NintendoSwitchControlLibrary.h>
#include "usb_soft_reconnect_avr.h"
#include "switch_pairing.h"

namespace {
struct EarlySwitchHidRegister {
  EarlySwitchHidRegister() {
    (void)SwitchControlLibrary();
  }
} g_early_switch_hid;
}  // namespace

// ========== 只开一个 ==========
#define PROBE_LEFT_COLUMN 1
#define PROBE_UP_ROW 0

/** 每次移动之间的停顿（毫秒），方便肉眼计数 */
const unsigned long STEP_PAUSE_MS = 1600;
/** pushHat 内部点按间隔由库固定；这里为点按后的额外等待（传入 pushHat 第二参数） */
const unsigned long HAT_GAP_MS = 80;

/** 热插拔后 Switch 会要求 L+R / A；先发配对再进入原来的 5s 等待 */
const unsigned long USB_SETTLE_MS = 2000;
#ifndef RUN_SWITCH_CONTROLLER_PAIRING
#define RUN_SWITCH_CONTROLLER_PAIRING 1
#endif

void setup() {
  delay(USB_SETTLE_MS);
#if RUN_SWITCH_USB_BUS_SOFT_RECONNECT
  UsbBusSoftReconnectAvr32u4();
#endif
#if RUN_SWITCH_CONTROLLER_PAIRING
  DismissSwitchControllerPairingDialog();
#endif
  delay(5000);
}

void loop() {
  delay(STEP_PAUSE_MS);
#if PROBE_LEFT_COLUMN
  pushHat(Hat::LEFT, HAT_GAP_MS, 1);
#elif PROBE_UP_ROW
  pushHat(Hat::UP, HAT_GAP_MS, 1);
#else
#error 请在 PROBE_LEFT_COLUMN / PROBE_UP_ROW 中只启用一个
#endif
}
