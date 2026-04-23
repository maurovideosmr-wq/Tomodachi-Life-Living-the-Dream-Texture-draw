/**
 * 矢量线稿（PROGMEM DrawCmd）：空跑 + 长按 A + pushHat 离散拖线（与 paint_mono_flash 时序一致）。
 *
 * 生成：scripts/texture_prep/svg_compiler.py 或 gui_app「矢量」Tab → draw_vector_data.h
 *
 * 多色时含 DRAW_CMD_OP_QUICK：Y 开快选 → D-pad 上/下（不更新 g_row/g_col 画布位）
 * → A 确认; g_quick_index 与头文件 DRAW_QUICK_INDEX_INIT 对齐。旧版无 QUICK 指令时
 * 仅含 AIR/DRAG，行为与单色相同。
 */
#include <stdint.h>
#include <avr/pgmspace.h>
#include <NintendoSwitchControlLibrary.h>
#include "usb_soft_reconnect_avr.h"
#include "switch_pairing.h"
#include "draw_vector_data.h"
#include "palette_defaults.h"

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

#ifndef DRAW_CMD_OP_QUICK
#define DRAW_CMD_OP_QUICK 0x02u
#endif
#ifndef DRAW_CMD_OP_FULL_BIND
#define DRAW_CMD_OP_FULL_BIND 0x03u
#endif
#ifndef DRAW_CMD_OP_SUB_HAT4
#define DRAW_CMD_OP_SUB_HAT4 0x04u
#endif
#ifndef FULL_BIND_HAT_MAX
#define FULL_BIND_HAT_MAX 200u
#endif
#ifndef DRAW_QUICK_INDEX_INIT
#define DRAW_QUICK_INDEX_INIT 0u
#endif

#ifndef QUICK_Y_PRIME_MS
#define QUICK_Y_PRIME_MS 50
#endif
#ifndef QUICK_Y_MENU_SETTLE_MS
#define QUICK_Y_MENU_SETTLE_MS 250u
#endif
#ifndef QUICK_HAT_GAP_MS
#define QUICK_HAT_GAP_MS 20u
#endif
#ifndef QUICK_A_TAP_MS
#define QUICK_A_TAP_MS 40
#endif
#ifndef QUICK_POST_A_MS
#define QUICK_POST_A_MS 80u
#endif
#ifndef FULL_HAT_GAP_MS
#define FULL_HAT_GAP_MS 22u
#endif
#ifndef FULL_Y_TO_FULL_SETTLE_MS
#define FULL_Y_TO_FULL_SETTLE_MS 280u
#endif
#ifndef FULL_A_TAP_MS
#define FULL_A_TAP_MS 40
#endif
#ifndef FULL_A_GAP_MS
#define FULL_A_GAP_MS 90u
#endif

/* 上电前须保证游戏 9 快选与 JSON 九格 default 一致; 与 pgm 及编译器 default_nine 对齐 */
static uint8_t g_slot_to_index[9];
/* 自快选 A 回画布后, 与 sim: 再按 Y 时高亮=active(否则=顶) */
static uint8_t g_ever_a_from_quick = 0u;
static uint8_t g_active_slot = 0u;

static uint8_t g_quick_index = 0u;

static void pushFullHat4(uint8_t m) {
  if (m == 0u) {
    pushHat(Hat::UP, FULL_HAT_GAP_MS, 1u);
  } else if (m == 1u) {
    pushHat(Hat::RIGHT, FULL_HAT_GAP_MS, 1u);
  } else if (m == 2u) {
    pushHat(Hat::DOWN, FULL_HAT_GAP_MS, 1u);
  } else {
    pushHat(Hat::LEFT, FULL_HAT_GAP_MS, 1u);
  }
}

// 自绘画按 Y: 开快选; 高亮: 未从快选 A 过则顶=0, 否则=上次 active
static void yOpenFromPaint() {
  pushButton(Button::Y, static_cast<unsigned long>(QUICK_Y_PRIME_MS), 1u);
  delay(QUICK_Y_MENU_SETTLE_MS);
  if (g_ever_a_from_quick == 0u) {
    g_quick_index = 0u;
  } else {
    g_quick_index = g_active_slot;
  }
}

// 在已打开的快选内 D-pad 上/下, 不改 g_row/g_col
static void nudgeInQuickTo(uint8_t k) {
  if (k > 8u) {
    return;
  }
  const int target = static_cast<int>(k);
  int cur = static_cast<int>(g_quick_index);
  const int d = target - cur;
  if (d > 0) {
    nudgeQuickMenuDown(static_cast<unsigned>(d));
  } else if (d < 0) {
    nudgeQuickMenuUp(static_cast<unsigned>(-d));
  }
  g_quick_index = k;
}

// 在快选内再按 Y: 进全色, 光标=当前槽绑定 index 所在格
static void yOpenFullFromQuick() {
  pushButton(Button::Y, static_cast<unsigned long>(QUICK_Y_PRIME_MS), 1u);
  delay(FULL_Y_TO_FULL_SETTLE_MS);
}

// FULL_BIND( arg1=index, arg2=槽 ) + 紧随 N 条 SUB_HAT4: 帽键由生成器 BFS 展开, 片上无寻路
static void runFullBindWithPath(
    uint8_t target_index, uint8_t slot, const uint8_t* hats, uint8_t n) {
  if (slot > 8u || target_index > 83u) {
    return;
  }
  if (g_slot_to_index[slot] == target_index) {
    selectQuickColorSlot(slot);
    return;
  }
  {
    const uint8_t def0 = pgm_read_byte(&PALETTE_DEFAULT_NINE[(size_t)slot]);
    if (def0 == target_index) {
      selectQuickColorSlot(slot);
      g_slot_to_index[slot] = target_index;
      return;
    }
  }
  yOpenFromPaint();
  nudgeInQuickTo(slot);
  yOpenFullFromQuick();
  for (uint8_t k = 0u; k < n; ++k) {
    pushFullHat4(hats[k] & 3u);
  }
  pushButton(Button::A, static_cast<unsigned long>(FULL_A_TAP_MS), 1u);
  delay(FULL_A_GAP_MS);
  pushButton(Button::A, static_cast<unsigned long>(QUICK_A_TAP_MS), 1u);
  delay(QUICK_POST_A_MS);
  g_slot_to_index[slot] = target_index;
  g_ever_a_from_quick = 1u;
  g_active_slot = slot;
  g_quick_index = slot;
}

static void nudgeQuickMenuDown(unsigned n) {
  for (unsigned j = 0; j < n; ++j) {
    pushHat(Hat::DOWN, QUICK_HAT_GAP_MS, 1u);
  }
}

static void nudgeQuickMenuUp(unsigned n) {
  for (unsigned j = 0; j < n; ++j) {
    pushHat(Hat::UP, QUICK_HAT_GAP_MS, 1u);
  }
}

// 在快选菜单里切到笔色槽 k (0=顶) ；不改画布格点 g_row/g_col。
static void selectQuickColorSlot(uint8_t k) {
  if (k > 8u) {
    return;
  }
  if (k == g_quick_index) {
    return;
  }
  pushButton(Button::Y, static_cast<unsigned long>(QUICK_Y_PRIME_MS), 1u);
  delay(QUICK_Y_MENU_SETTLE_MS);
  const int target = static_cast<int>(k);
  const int cur = static_cast<int>(g_quick_index);
  const int d = target - cur;
  if (d > 0) {
    nudgeQuickMenuDown(static_cast<unsigned>(d));
  } else if (d < 0) {
    nudgeQuickMenuUp(static_cast<unsigned>(-d));
  }
  delay(60);
  pushButton(Button::A, static_cast<unsigned long>(QUICK_A_TAP_MS), 1u);
  delay(QUICK_POST_A_MS);
  g_quick_index = k;
  g_ever_a_from_quick = 1u;
  g_active_slot = k;
}

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
  uint16_t i = 0u;
  while (i < (uint16_t)DRAW_CMD_COUNT) {
    DrawCmd c;
    memcpy_P(&c, &draw_cmds[i], sizeof(DrawCmd));
    if (c.op == DRAW_CMD_OP_AIR) {
      airMoveToCell(c.arg2, c.arg1);
      ++i;
    } else if (c.op == DRAW_CMD_OP_DRAG) {
      paintVectorDrag(c.arg1, c.arg2);
      ++i;
    } else if (c.op == DRAW_CMD_OP_QUICK) {
      selectQuickColorSlot(c.arg1);
      ++i;
    } else if (c.op == DRAW_CMD_OP_FULL_BIND) {
      uint8_t buf[FULL_BIND_HAT_MAX];
      uint8_t n = 0u;
      uint16_t j = (uint16_t)(i + 1u);
      while (j < (uint16_t)DRAW_CMD_COUNT && n < FULL_BIND_HAT_MAX) {
        DrawCmd d;
        memcpy_P(&d, &draw_cmds[j], sizeof(DrawCmd));
        if (d.op != DRAW_CMD_OP_SUB_HAT4) {
          break;
        }
        buf[n] = d.arg1;
        ++n;
        ++j;
      }
      runFullBindWithPath(c.arg1, c.arg2, buf, n);
      i = j;
    } else if (c.op == DRAW_CMD_OP_SUB_HAT4) {
      /* 生成器约定: 0:04 仅作 0:03 子序列; 孤件跳过 */
      ++i;
    } else {
      ++i;
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
  g_quick_index = static_cast<uint8_t>(DRAW_QUICK_INDEX_INIT & 0xFFu);
  g_active_slot = g_quick_index;
  g_ever_a_from_quick = 0u;
  for (uint8_t i = 0u; i < 9u; ++i) {
    g_slot_to_index[i] = pgm_read_byte(&PALETTE_DEFAULT_NINE[(size_t) i]);
  }
  runVectorFromProgmem();
}

void loop() {
  delay(60000);
}
