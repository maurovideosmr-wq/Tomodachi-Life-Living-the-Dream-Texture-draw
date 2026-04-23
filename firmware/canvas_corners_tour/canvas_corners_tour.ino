/**
 * 画布四角巡游（验证十字键步进与默认格假设）
 *
 * 约定（与 docs/canvas_home_test.md 一致）：
 *   - 进入贴图绘制且未移动时，画笔在逻辑格 (HOME_ROW0, HOME_COL0) = (128, 128)。
 *   - row：0 在上；col：0 在左。
 *
 * 用法（推荐顺序，避免配对 A 当成落笔）：
 *   1. 上传后先在 **Switch 主页或手柄登记界面** 插线，让自动 L+R / A 完成；再进贴图绘制、默认中心别动。
 *      若必须在绘图里插线：配对时的 A 仍可能画 1 点，属正常现象。
 *   2. 配对与 START_DELAY_MS（默认 10s）结束后，才会开始 **左 128 / 上 128**；这 10s 内光标不动，不是死机。
 *   3. 然后自动执行：
 *        回左上角 → 每角 **A 落笔一点**（默认开）→ 停 CORNER_PAUSE_MS → 再巡下一角。
 *   4. 肉眼检查四角**墨点**是否贴齐格线；若某条边差 1 格，调 STEP_GAP_MS 或 HOME_*。
 *      不要落笔时把 STAMP_DOT_AT_EACH_CORNER 设为 0。
 *
 * 若游戏一次连跳多格：加大 STEP_GAP_MS，或改用手动长按方案（见 canvas_home_test.md）。
 *
 * 依赖：NintendoSwitchControlLibrary + Leonardo HID 早注册（同 smoke_test）。
 *
 * 配对怪癖：若 Switch 总要求「先选手柄、第一次 L+R 无效、拔插后才过」，固件会在配对前做一次
 * **软件 USB 重枚举**（`usb_soft_reconnect_avr.h`，模拟拔插）。不需要时设 RUN_SWITCH_USB_BUS_SOFT_RECONNECT 0。
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

/** 默认画笔逻辑坐标（你已确认为十字线交点右下格） */
constexpr unsigned HOME_ROW0 = 128;
constexpr unsigned HOME_COL0 = 128;

/** USB 枚举稳定后再发配对键 */
const unsigned long USB_SETTLE_MS = 2000;
/**
 * 热插拔 Pro 手柄时系统会先要求 L+R、再 A。必须在发十字键之前完成，否则会一直卡在对话框。
 * 若你已提前在系统里配对该手柄、插线不再弹窗，可改为 0 跳过（避免在其它界面误触肩键）。
 */
#ifndef RUN_SWITCH_CONTROLLER_PAIRING
#define RUN_SWITCH_CONTROLLER_PAIRING 1
#endif
/** 配对后等你回到贴图绘制默认中心 */
const unsigned long START_DELAY_MS = 2000;
/** 每次十字键点按后的间隔（毫秒），过小可能吞步 */
const unsigned long STEP_GAP_MS = 40;
/** 每到一角后停顿，方便你对准格线观察 */
const unsigned long CORNER_PAUSE_MS = 1000;
/** 光标停稳后再按 A，减少歪点 */
const unsigned long CORNER_STAMP_SETTLE_MS = 400;

#ifndef STAMP_DOT_AT_EACH_CORNER
#define STAMP_DOT_AT_EACH_CORNER 1
#endif

static void moveGrid(uint8_t hat, unsigned n) {
  if (n == 0) {
    return;
  }
  pushHat(hat, STEP_GAP_MS, n);
}

/** 到达一角：稍等 → 可选 A 落一笔 → 再长时间停留观察 */
static void pauseAtCorner() {
  delay(CORNER_STAMP_SETTLE_MS);
#if STAMP_DOT_AT_EACH_CORNER
  pushButton(Button::A, 220, 1);
  delay(350);
#endif
  delay(CORNER_PAUSE_MS);
}

void setup() {
  delay(USB_SETTLE_MS);
#if RUN_SWITCH_USB_BUS_SOFT_RECONNECT
  UsbBusSoftReconnectAvr32u4();
#endif
#if RUN_SWITCH_CONTROLLER_PAIRING
  DismissSwitchControllerPairingDialog();
#endif
  delay(START_DELAY_MS);

  // 从 (HOME_ROW0, HOME_COL0) 回到 (0, 0)
  moveGrid(Hat::LEFT, HOME_COL0);
  moveGrid(Hat::UP, HOME_ROW0);
  pauseAtCorner();  // 左上角 (0,0)

  moveGrid(Hat::RIGHT, 255);
  pauseAtCorner();  // 顶行右 (0,255)

  moveGrid(Hat::DOWN, 255);
  pauseAtCorner();  // 右下 (255,255)

  moveGrid(Hat::LEFT, 255);
  pauseAtCorner();  // 左下 (255,0)
}

void loop() {
  delay(60000);
}
