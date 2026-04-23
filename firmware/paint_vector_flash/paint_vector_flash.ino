/**
 * 矢量线稿（PROGMEM DrawCmd）：空跑 + 长按 A + pushHat 离散拖线（与 paint_mono_flash 时序一致）。
 *
 * 生成：scripts/texture_prep/svg_compiler.py 或 gui_app「矢量」Tab → draw_vector_data.h
 */
#include <stdint.h>
#include <avr/pgmspace.h>
#include <NintendoSwitchControlLibrary.h>
#include "usb_soft_reconnect_avr.h"
#include "switch_pairing.h"
#include "draw_vector_data.h"

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

const unsigned long USB_SETTLE_MS = 2000;
const unsigned long START_DELAY_MS = 2000;

const unsigned long STEP_GAP_MS = 20;
#ifndef AIR_STEP_GAP_MS
#define AIR_STEP_GAP_MS 20
#endif
const unsigned long LINE_STEP_GAP_MS = 20;
const unsigned long LINE_A_PRIME_MS = 33;
const unsigned long LINE_POST_RELEASE_MS = 33;
const unsigned long STAMP_AFTER_A_MS = 30;
const unsigned long STAMP_SETTLE_MS = 30;

#ifndef PAINT_DIAGONAL_AIR
#define PAINT_DIAGONAL_AIR 1
#endif

static uint8_t g_row = HOME_ROW0;
static uint8_t g_col = HOME_COL0;

static void moveGridAir(uint8_t hat, unsigned n) {
  if (n == 0) {
    return;
  }
  pushHat(hat, AIR_STEP_GAP_MS, n);
}

static void airMoveManhattan(uint8_t tr, uint8_t tc) {
  int dr = (int)tr - (int)g_row;
  int dc = (int)tc - (int)g_col;
  if (dr > 0) {
    moveGridAir(Hat::DOWN, (unsigned)dr);
  } else if (dr < 0) {
    moveGridAir(Hat::UP, (unsigned)(-dr));
  }
  if (dc > 0) {
    moveGridAir(Hat::RIGHT, (unsigned)dc);
  } else if (dc < 0) {
    moveGridAir(Hat::LEFT, (unsigned)(-dc));
  }
  g_row = tr;
  g_col = tc;
}

static void airMoveToCell(uint8_t tr, uint8_t tc) {
#if !PAINT_DIAGONAL_AIR
  airMoveManhattan(tr, tc);
  return;
#else
  for (;;) {
    const int16_t dr = (int16_t)tr - (int16_t)g_row;
    const int16_t dc = (int16_t)tc - (int16_t)g_col;
    if (dr == 0 && dc == 0) {
      return;
    }
    if (dr == 0 || dc == 0) {
      break;
    }
    if (dr > 0 && dc > 0) {
      moveGridAir(Hat::DOWN_RIGHT, 1);
      ++g_row;
      ++g_col;
    } else if (dr > 0 && dc < 0) {
      moveGridAir(Hat::DOWN_LEFT, 1);
      ++g_row;
      --g_col;
    } else if (dr < 0 && dc > 0) {
      moveGridAir(Hat::UP_RIGHT, 1);
      --g_row;
      ++g_col;
    } else if (dr < 0 && dc < 0) {
      moveGridAir(Hat::UP_LEFT, 1);
      --g_row;
      --g_col;
    } else {
      break;
    }
  }
  airMoveManhattan(tr, tc);
#endif
}

/** Hat 0..7：每步行/列增量（与 SwitchControlLibrary Hat 一致） */
static void step_hat(uint8_t h) {
  int dr = 0, dc = 0;
  switch (h) {
    case 0:
      dr = -1;
      break;
    case 1:
      dr = -1;
      dc = 1;
      break;
    case 2:
      dc = 1;
      break;
    case 3:
      dr = 1;
      dc = 1;
      break;
    case 4:
      dr = 1;
      break;
    case 5:
      dr = 1;
      dc = -1;
      break;
    case 6:
      dc = -1;
      break;
    case 7:
      dr = -1;
      dc = -1;
      break;
    default:
      return;
  }
  g_row = (uint8_t)((int16_t)g_row + dr);
  g_col = (uint8_t)((int16_t)g_col + dc);
}

static void paintVectorDrag(uint8_t hat, uint8_t n_steps) {
  if (n_steps == 0) {
    pushButton(Button::A, STAMP_AFTER_A_MS, 1);
    delay(STAMP_SETTLE_MS);
    return;
  }
  SwitchControlLibrary().pressButton(Button::A);
  SwitchControlLibrary().sendReport();
  delay(LINE_A_PRIME_MS);
  pushHat(hat, LINE_STEP_GAP_MS, n_steps);
  SwitchControlLibrary().releaseButton(Button::A);
  SwitchControlLibrary().sendReport();
  delay(LINE_POST_RELEASE_MS);
  for (uint8_t i = 0; i < n_steps; ++i) {
    step_hat(hat);
  }
}

static void runVectorFromProgmem() {
#if DRAW_CMD_COUNT == 0
  return;
#endif
  for (uint16_t i = 0; i < (uint16_t)DRAW_CMD_COUNT; ++i) {
    DrawCmd c;
    memcpy_P(&c, &draw_cmds[i], sizeof(DrawCmd));
    if (c.op == DRAW_CMD_OP_AIR) {
      // arg1=col, arg2=row
      airMoveToCell(c.arg2, c.arg1);
    } else if (c.op == DRAW_CMD_OP_DRAG) {
      paintVectorDrag(c.arg1, c.arg2);
    }
  }
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
  g_row = HOME_ROW0;
  g_col = HOME_COL0;
  runVectorFromProgmem();
}

void loop() {
  delay(60000);
}
