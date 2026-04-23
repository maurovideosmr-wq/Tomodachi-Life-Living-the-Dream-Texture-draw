# 长按画线探针（`paint_rate_probe`）

**极简流程**：USB 就绪 + 手柄配对完成后，等待 `START_DELAY_MS`，然后**在当前笔位置**画**一根**横向线（持续 **A + 右**），结束。不做走位、不画多条。

用于标定游戏里「长按画线」加速有多猛：默认 `LINE_HOLD_DURATION_MS` **很小**（200ms），避免第一次就冲出画布；你只需**改这个数反复烧录**，逐步加长直到长度满意。

## 主要宏（`paint_rate_probe.ino`）

| 宏 | 含义 |
|----|------|
| `START_DELAY_MS` | 配对结束到开画前的等待；进绘制、笔在默认格后可酌减。 |
| `LINE_HOLD_DURATION_MS` | **主旋钮**：按住 A+右 的时长（毫秒）。 |
| `LINE_HOLD_USE_GAME_RAMP_PRIME` | 是否在长按前先「A + 离散右一格」+ `LINE_HOLD_AFTER_FIRST_CELL_MS`。 |
| `LINE_A_SETTLE_MS` | 按下 A 后到首格/长按前的短延时。 |

使用前请**先进贴图绘制、笔在默认中心**，再上电或复位；配对会发 **A**，若在画布上配对可能留下点。
