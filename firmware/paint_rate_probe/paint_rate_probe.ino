/**
 * 长按画线探针（极简）：USB 就绪 + 配对完成后，**只画一根**横向长按（A + RIGHT）。
 *
 * 默认 `LINE_HOLD_DURATION_MS` 很短，避免长按加速把线甩出画布；你只需反复改这一参数（及可选 RAMP）再烧录。
 * 假定进贴图绘制后笔在默认格 (128,128)，**不做任何走位**。
 *
 * `LINE_HOLD_USE_GAME_RAMP_PRIME`：先 A + 离散右移一格，短停，再持续长按（见宏说明）。
 *
 * 配对：建议主机主页插线；若在绘制里配对会按 A 可能落点。
 */
#include <stdint.h>
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

#ifndef RUN_SWITCH_CONTROLLER_PAIRING
#define RUN_SWITCH_CONTROLLER_PAIRING 1
#endif

#ifndef RATE_PROBE_LOG_SERIAL
#define RATE_PROBE_LOG_SERIAL 0
#endif

const unsigned long USB_SETTLE_MS = 2000;

/** 配对完成后到开始画线前的等待（进绘制界面、笔归中后再缩短） */
#ifndef START_DELAY_MS
#define START_DELAY_MS 400ul
#endif

/**
 * 持续按住 A+右 的毫秒数（**主旋钮**：从小往大加，直到长度满意且不出界）。
 * 旧默认 1800 会高速冲出画布，故默认改为极保守值。
 */
#ifndef LINE_HOLD_DURATION_MS
#define LINE_HOLD_DURATION_MS 50ul
#endif

#ifndef LINE_HOLD_POST_MS
#define LINE_HOLD_POST_MS 120ul
#endif

/**
 * 1：先「A + 一格离散右移」再 LINE_HOLD_AFTER_FIRST_CELL_MS，再持续长按；
 * 0：直接 A + 长按 LINE_HOLD_DURATION_MS。
 */
#ifndef LINE_HOLD_USE_GAME_RAMP_PRIME
#define LINE_HOLD_USE_GAME_RAMP_PRIME 0
#endif

#ifndef LINE_HOLD_PRIME_GAP_MS
#define LINE_HOLD_PRIME_GAP_MS 35ul
#endif

#ifndef LINE_HOLD_AFTER_FIRST_CELL_MS
#define LINE_HOLD_AFTER_FIRST_CELL_MS 80ul
#endif

/** 按下 A 后、首格/长按前的短稳态 */
#ifndef LINE_A_SETTLE_MS
#define LINE_A_SETTLE_MS 40ul
#endif

static void paintSingleHoldLineRight() {
  SwitchControlLibrary().pressButton(Button::A);
  SwitchControlLibrary().sendReport();
  delay(LINE_A_SETTLE_MS);

#if LINE_HOLD_USE_GAME_RAMP_PRIME
  pushHat(Hat::RIGHT, LINE_HOLD_PRIME_GAP_MS, 1);
  delay(LINE_HOLD_AFTER_FIRST_CELL_MS);
#endif

  SwitchControlLibrary().pressHatButton(Hat::RIGHT);
  SwitchControlLibrary().sendReport();
  delay(LINE_HOLD_DURATION_MS);
  SwitchControlLibrary().releaseHatButton();
  SwitchControlLibrary().releaseButton(Button::A);
  SwitchControlLibrary().sendReport();
  delay(LINE_HOLD_POST_MS);
}

static void runOnce() {
#if RATE_PROBE_LOG_SERIAL
  Serial.begin(115200);
  delay(200);
  Serial.print(F("LINE_HOLD_DURATION_MS="));
  Serial.println((unsigned long)LINE_HOLD_DURATION_MS);
#endif

  paintSingleHoldLineRight();

#if RATE_PROBE_LOG_SERIAL
  Serial.println(F("done"));
#endif
}

void setup() {
#if defined(LED_BUILTIN)
  pinMode(LED_BUILTIN, OUTPUT);
#endif

  delay(USB_SETTLE_MS);
#if RUN_SWITCH_USB_BUS_SOFT_RECONNECT
  UsbBusSoftReconnectAvr32u4();
#endif
#if RUN_SWITCH_CONTROLLER_PAIRING
  DismissSwitchControllerPairingDialog();
#endif
  delay(START_DELAY_MS);

  runOnce();
}

void loop() {
  delay(60000);
}
