/**
 * 单色自动落笔（PROGMEM 位图掩码）
 *
 * 刀路：可选**斜向空跑**（八向）、**蛇形扫描**（偶行 LTR / 奇行 RTL）、**行范围裁剪**（仅 min_r..max_r）。
 * 水平段：按住 A + RIGHT 或 LEFT 拖线；单点短按 A。
 *
 * 开关：PAINT_DIAGONAL_AIR、PAINT_CLIP_ROWS、PAINT_LINE_MODE、AIR_STEP_GAP_MS（默认同 STEP_GAP_MS，可在 include 前覆盖）。
 *
 * 依赖：NintendoSwitchControlLibrary + Leonardo；配对见 usb_soft_reconnect / switch_pairing。
 */
#include <stdint.h>
#include <NintendoSwitchControlLibrary.h>
#include "usb_soft_reconnect_avr.h"
#include "switch_pairing.h"
#include "draw_data.h"

namespace {
struct EarlySwitchHidRegister {
  EarlySwitchHidRegister() {
    (void)SwitchControlLibrary();
  }
} g_early_switch_hid;
}  // namespace

constexpr uint8_t HOME_ROW0 = 128;
constexpr uint8_t HOME_COL0 = 128;

const unsigned long USB_SETTLE_MS = 2000;
#ifndef RUN_SWITCH_CONTROLLER_PAIRING
#define RUN_SWITCH_CONTROLLER_PAIRING 1
#endif
const unsigned long START_DELAY_MS = 2000;

// 退回最稳的 20ms 步进（绝不漏格）
const unsigned long STEP_GAP_MS = 20;
#ifndef AIR_STEP_GAP_MS
#define AIR_STEP_GAP_MS 20
#endif
const unsigned long LINE_STEP_GAP_MS = 20;

// 按键缓冲时间也退回两帧以上，保证引擎绝对能识别
const unsigned long LINE_A_PRIME_MS = 33;
const unsigned long LINE_POST_RELEASE_MS = 33;  // 原版是 50，33 足够稳了

// 孤立单点的落笔时间
const unsigned long STAMP_AFTER_A_MS = 30;
const unsigned long STAMP_SETTLE_MS = 30;

#ifndef PAINT_LINE_MODE
#define PAINT_LINE_MODE 1
#endif
#ifndef PAINT_DIAGONAL_AIR
#define PAINT_DIAGONAL_AIR 1
#endif
#ifndef PAINT_CLIP_ROWS
#define PAINT_CLIP_ROWS 1
#endif

static uint8_t g_row = HOME_ROW0;
static uint8_t g_col = HOME_COL0;

static void moveGridAir(uint8_t hat, unsigned n) {
  if (n == 0) {
    return;
  }
  pushHat(hat, AIR_STEP_GAP_MS, n);
}

static void moveGridOrthoPaint(uint8_t hat, unsigned n) {
  if (n == 0) {
    return;
  }
  pushHat(hat, STEP_GAP_MS, n);
}

static inline bool maskPixelSet(uint32_t idx) {
  const uint32_t bi = idx >> 3;
  const uint8_t b = pgm_read_byte(&draw_mask[bi]);
  return (b >> (7u - (uint8_t)(idx & 7u))) & 1u;
}

static inline bool maskAt(uint32_t r, uint32_t c, uint32_t w) {
  return maskPixelSet(r * w + c);
}

/** 曼哈顿空跑（仅轴方向），使用 AIR_STEP_GAP_MS */
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

/**
 * 空跑：优先斜向（dr、dc 均非零且可走对角），余量走曼哈顿。关 PAINT_DIAGONAL_AIR 时仅曼哈顿。
 */
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

/**
 * @param c_lo 列区间左端（较小列）
 * @param c_hi 列区间右端（较大列）
 * @param ltr true：从 c_lo 画到 c_hi（RIGHT）；false：从 c_hi 画到 c_lo（LEFT）
 */
static void paintHorizontalRun(uint8_t r, uint8_t c_lo, uint8_t c_hi, bool ltr) {
  const uint8_t start_c = ltr ? c_lo : c_hi;
  airMoveToCell(r, start_c);
  const unsigned len = (unsigned)(c_hi - c_lo) + 1u;

#if !PAINT_LINE_MODE
  for (unsigned k = 0; k < len; ++k) {
    if (k > 0u) {
      moveGridOrthoPaint(ltr ? Hat::RIGHT : Hat::LEFT, 1);
      if (ltr) {
        ++g_col;
      } else {
        --g_col;
      }
    }
    pushButton(Button::A, STAMP_AFTER_A_MS, 1);
    delay(STAMP_SETTLE_MS);
  }
  g_row = r;
  g_col = ltr ? c_hi : c_lo;
  return;
#else
  if (len == 1u) {
    pushButton(Button::A, STAMP_AFTER_A_MS, 1);
    delay(STAMP_SETTLE_MS);
    return;
  }

  const uint8_t hat_paint = ltr ? Hat::RIGHT : Hat::LEFT;
  SwitchControlLibrary().pressButton(Button::A);
  SwitchControlLibrary().sendReport();
  delay(LINE_A_PRIME_MS);
  pushHat(hat_paint, LINE_STEP_GAP_MS, len - 1u);
  SwitchControlLibrary().releaseButton(Button::A);
  SwitchControlLibrary().sendReport();
  delay(LINE_POST_RELEASE_MS);
  g_row = r;
  g_col = ltr ? c_hi : c_lo;
#endif
}

/** 返回是否至少有一格可画；写入含像素的最小/最大行号 */
static bool computeRowBounds(uint32_t w, uint32_t h, uint16_t *min_r, uint16_t *max_r) {
  bool any = false;
  uint16_t lo = 0;
  uint16_t hi = 0;

  for (uint32_t r = 0; r < h; ++r) {
    bool row_has = false;
    for (uint32_t c = 0; c < w; ++c) {
      if (maskAt(r, c, w)) {
        row_has = true;
        break;
      }
    }
    if (row_has) {
      if (!any) {
        lo = hi = (uint16_t)r;
        any = true;
      } else {
        if ((uint16_t)r < lo) {
          lo = (uint16_t)r;
        }
        if ((uint16_t)r > hi) {
          hi = (uint16_t)r;
        }
      }
    }
  }

  if (any) {
    *min_r = lo;
    *max_r = hi;
  }
  return any;
}

static void runSerpentineLinePaint(uint16_t min_r, uint16_t max_r) {
  const uint32_t w = (uint32_t)DRAW_MASK_WIDTH;
  const uint32_t h = (uint32_t)DRAW_MASK_HEIGHT;
  (void)h;

  for (uint32_t r = (uint32_t)min_r; r <= (uint32_t)max_r; ++r) {
    const bool ltr = ((r & 1u) == 0);

    if (ltr) {
      uint32_t c = 0;
      while (c < w) {
        while (c < w && !maskAt(r, c, w)) {
          ++c;
        }
        if (c >= w) {
          break;
        }
        const uint32_t c0 = c;
        while (c < w && maskAt(r, c, w)) {
          ++c;
        }
        const uint8_t c1 = (uint8_t)(c - 1u);
        paintHorizontalRun((uint8_t)r, (uint8_t)c0, c1, true);
      }
    } else {
      int32_t c = (int32_t)w - 1;
      while (c >= 0) {
        while (c >= 0 && !maskAt(r, (uint32_t)c, w)) {
          --c;
        }
        if (c < 0) {
          break;
        }
        const int32_t c_hi = c;
        while (c >= 0 && maskAt(r, (uint32_t)c, w)) {
          --c;
        }
        const uint8_t c_lo = (uint8_t)(c + 1);
        paintHorizontalRun((uint8_t)r, c_lo, (uint8_t)c_hi, false);
      }
    }
  }
}

static void runPaint() {
#if defined(DRAW_PIXEL_COUNT) && (DRAW_PIXEL_COUNT == 0ul)
  return;
#endif

  const uint32_t w = (uint32_t)DRAW_MASK_WIDTH;
  const uint32_t h = (uint32_t)DRAW_MASK_HEIGHT;

  uint16_t min_r = 0;
  uint16_t max_r = (uint16_t)(h - 1u);

#if PAINT_CLIP_ROWS
  if (!computeRowBounds(w, h, &min_r, &max_r)) {
    return;
  }
#endif

  runSerpentineLinePaint(min_r, max_r);
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
  runPaint();
}

void loop() {
  delay(60000);
}
