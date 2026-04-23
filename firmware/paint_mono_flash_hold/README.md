# paint_mono_flash_hold

`paint_mono_flash` 的**副本**：同款掩码绘制、蛇形/斜向空跑/行裁剪，但水平拖线采用**混合策略**：

| 线段长度 `len` | 行为 |
|----------------|------|
| `1` | 短按 A |
| `2 … PAINT_HOLD_LINE_MIN_LEN-1`（默认 `≤15`） | A + `pushHat` 离散（与原版 mono 一致） |
| `≥ PAINT_HOLD_LINE_MIN_LEN`（默认 `≥16`） | A + **长按**十字键，`delay(T)`，其中 `T = (411*len)/100 + 370` ms（可调宏） |

默认公式对应 **T ≈ 4.11×L + 370**，适合标定里 **L≥28** 的巡航段；短线用长按易落在死区/初加速，故保留离散。

## 可调宏（`paint_mono_flash_hold.ino`）

- `PAINT_HOLD_LINE_MIN_LEN`：默认 `16`（即长度 **>15** 走长按）。
- `HOLD_LINE_SLOPE_NUM` / `HOLD_LINE_SLOPE_DEN` / `HOLD_LINE_MS_OFFSET`：线性系数。
- `HOLD_LINE_MS_MAX`：长按上限（默认 1200），防异常 `len`。

## LEFT 拖线

与 RIGHT **共用同一公式**（未单独标定）；若 LEFT 偏长/偏短，请实测后改系数或仅对 RTL 分支定义常量。

## 与原版同步

导出掩码时覆盖本目录 [`draw_data.h`](draw_data.h)，或复制自 [`../paint_mono_flash/draw_data.h`](../paint_mono_flash/draw_data.h)。

Arduino IDE 请打开 **`paint_mono_flash_hold.ino`**。
