/**
 * Switch 热插拔「L+R / 再按 A」登记流程（NintendoSwitchControlLibrary）。
 *
 * 注意：若在**贴图绘制画面内**配对，每一次 **A** 都可能被游戏当成**落笔**。
 * 因此正式配对用 **A** 仍只发一次长按；热身阶段**绝不按 A/B/X/Y**。
 *
 * 部分环境下首次枚举后立刻 L+R 无效，需先「弄出点输入」主机才认；见 PairingInputWarmup()。
 * 更稳妥：在主页插线配对；或 `#define RUN_SWITCH_CONTROLLER_PAIRING 0` 手动配对。
 *
 * 与 brush_grid_count_probe 内同文件保持同步。
 */
#pragma once

#include <NintendoSwitchControlLibrary.h>

#ifndef SKIP_PAIRING_WARMUP
#define SKIP_PAIRING_WARMUP 0
#endif

inline void SwitchSendNeutralReport() {
  SwitchControlLibrary().releaseButton(0xFFFF);
  SwitchControlLibrary().releaseHatButton();
  SwitchControlLibrary().sendReport();
}

/**
 * 乱按热身（无 A/B/X/Y）：中性报告连发 + 摇杆微抖 + 肩键/摇杆帽轻点。
 * 若仍首次必败，可略增大中性循环次数或 `canvas_corners_tour.ino` 里 `USB_SETTLE_MS`。
 */
inline void PairingInputWarmup() {
#if SKIP_PAIRING_WARMUP
  return;
#endif
  for (unsigned i = 0; i < 20; ++i) {
    SwitchSendNeutralReport();
    delay(40);
  }
  tiltLeftStick(132, 129, 70, 0);
  delay(100);
  tiltRightStick(126, 132, 70, 0);
  delay(100);
  /* 不用十字键热身：绘图界面里会真的移格 */
  pushButton(Button::ZL, 55, 1);
  pushButton(Button::ZR, 55, 1);
  pushButton(Button::LCLICK, 55, 1);
  pushButton(Button::RCLICK, 55, 1);
  SwitchSendNeutralReport();
  delay(250);
}

/**
 * 配对用 A：仅一次长按。若主机仍不认，请先加大「L+R 松开之后」的 delay，不要擅自加连点 A。
 */
inline void DismissSwitchControllerPairingDialog() {
  const uint16_t lr = static_cast<uint16_t>(Button::L | Button::R);

  PairingInputWarmup();

  SwitchSendNeutralReport();
  delay(100);  // 原版 200，缩减

  SwitchControlLibrary().pressButton(lr);
  SwitchControlLibrary().sendReport();
  delay(400);  // 原版 900。按 L+R 没必要按近 1 秒，400ms (近半秒) 绝对够了
  SwitchControlLibrary().releaseButton(lr);
  SwitchControlLibrary().sendReport();

  /* 等 UI 切到「请按 A」 */
  delay(1500);  // 原版 2400 (2.4秒)。Switch 弹窗动画大概 1 秒左右，给 1.5 秒足够了

  SwitchSendNeutralReport();
  delay(100);  // 原版 300，缩减

  holdButton(Button::A, 200);  // 原版 750 (大半秒)。按 A 键确认，200ms 足够触发
  delay(200);  // 原版 500，缩减

  SwitchSendNeutralReport();
}
