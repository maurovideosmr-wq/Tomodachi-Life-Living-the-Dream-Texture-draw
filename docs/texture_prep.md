# 256×256 贴图预处理

将任意边长的 **正方形 PNG**（可含透明通道）缩放为 **256×256**，并把**需要绘制**的像素量化到游戏默认 **84 色**（在 **Lab** 空间最近邻，无抖动）。透明区域在输出中有明确语义，供 Arduino 固件**跳过绘制**。

## 依赖

```bash
cd scripts/texture_prep
pip install -r requirements.txt
```

（另含 `svg.path`，供矢量。）

## 图形界面

无需命令行参数时，可在 `scripts/texture_prep` 下启动（**一个窗口、两个 Tab**）：

```bash
cd scripts/texture_prep
python gui_app.py
```

### 位图 Tab

- **打开图片**：选择 **1:1** 正方形 PNG（含透明亦可）；非正方形会在状态栏报错且无法导出。
- **参数**：与 `config/default.yaml` 一致（Alpha 阈值、RGB/Alpha 缩放算法）；拖动滑块会在约 300ms 后**自动刷新预览**（防抖）。
- **预览**：左侧为原图缩略图，右侧为 **256×256** 量化结果（最近邻放大显示像素块）。
- **导出**：选择 PNG 保存路径；若勾选「导出 .bin / meta.json」，会在**同名前缀**下写入 `*_indices.bin`、`*_meta.json`（与 CLI 语义相同）。
- **导出 draw_data.h (单色)**：在预览成功后，将当前 `flat_idx` 打成 **PROGMEM 位图掩码**（`ceil(W×H/8)` 字节；256×256 时为 8192），与 `.bin` 的 NO_DRAW 语义一致，供 [`firmware/paint_mono_flash`](../firmware/paint_mono_flash) 使用。游戏内需**先选好一种颜色**再进绘制；固件只负责走位 + **A** 落笔，不切换调色板。
- **色表**：默认读取配置中的 `palette_default.json`；也可通过「色表 JSON…」更换。

### 矢量 Tab（线稿 / `paint_vector_flash`）

- 打开 **线稿 `*.svg`**（内部用 `<path d="…">`），「刷新/编译」生成 **八向格点** 指令，右侧为 256 格栅格预览。
- 导出 **`draw_vector_data.h`** 放入 [`firmware/paint_vector_flash`](../firmware/paint_vector_flash)，与位图单色的提示相同：**在主机上先选一种颜色**再进贴图绘制，固件**不切调色板**；落笔为「长按 A + `pushHat` 离散」与 `paint_mono_flash` 时序一致。
- 亦可用命令行：[`svg_compiler.py`](../scripts/texture_prep/svg_compiler.py) 见下节。

## 矢量线稿（命令行 + `draw_vector_data.h`）

将纯线稿 SVG 编译为 `paint_vector_flash` 使用的 `DrawCmd` 表（空跑 + 八向游程，笔画顺序为最近邻 / 切比雪夫）：

```bash
cd scripts/texture_prep
pip install -r requirements.txt
python svg_compiler.py path/to/lineart.svg -o ../../firmware/paint_vector_flash/draw_vector_data.h --summary
```

覆盖 `firmware/paint_vector_flash/draw_vector_data.h` 后，在 Arduino IDE 中打开 `paint_vector_flash.ino` 并上传。库与 [arduino_switch_setup.md](arduino_switch_setup.md) 与位图流相同；烟测、VID/PID、HID 见 [AGENT](../firmware/AGENT_SWITCH_DEBUG_RECORD.md) 与 [USB 补丁说明](../firmware/USB_VID_PID_patch.md)。

## 单色 Arduino 位图掩码（命令行）

从已有的 `*_indices.bin` 生成 `draw_data.h`（与 GUI 单色导出等价）：

```bash
cd scripts/texture_prep
python mono_draw_export.py --indices ../../assets/processed/foo_indices.bin -o ../../firmware/paint_mono_flash/draw_data.h
```

覆盖 `firmware/paint_mono_flash/draw_data.h` 后，用 Arduino IDE 打开 `paint_mono_flash.ino` 上传。长按混合实验副本见 [`firmware/paint_mono_flash_hold`](../firmware/paint_mono_flash_hold)（导出时可把 `-o` 指向该目录下的 `draw_data.h`）。

**注意（AVR）**：`unsigned` 在 ATmega32U4 上为 **16 位**，`256 * 256` 会溢出为 0；`paint_mono_flash.ino` 内栅格循环已用 **`uint32_t`** 计算像素总数，若你 fork 固件请勿改回 16 位乘法。

**绘制策略（`paint_mono_flash.ino`）**：

- 从**默认格 (128,128)** 起画；**空跑**可走八向斜线（缩短步数），`#define PAINT_DIAGONAL_AIR 0` 则仅曼哈顿移动。
- **蛇形**：偶数行从左到右画段（`RIGHT` 拖线），奇数行从右到左（`LEFT` 拖线）。
- **行裁剪**：默认 `PAINT_CLIP_ROWS 1`，只扫描掩码中出现像素的 `min_r..max_r` 行；置 0 则始终扫满高。
- **间隔**：落笔拖线用 `LINE_STEP_GAP_MS`；空跑默认 `AIR_STEP_GAP_MS`（未定义时等于 `STEP_GAP_MS`）。
- 单格仍短按 A；`#define PAINT_LINE_MODE 0` 退回逐格点按。长按加速过猛可调 `LINE_STEP_GAP_MS` / `LINE_A_PRIME_MS`。
- **速率标定**：游戏内「持续按住」与库里 `pushHat` 短按链不同；用 [`firmware/paint_rate_probe`](../firmware/paint_rate_probe) 配对后**只画一根**长按横线，从小调大 `LINE_HOLD_DURATION_MS`，详见 [`docs/paint_rate_probe.md`](paint_rate_probe.md)。
- **速率标定**：游戏内「持续按住」与库里 `pushHat` 短按链不同；用 [`firmware/paint_rate_probe`](../firmware/paint_rate_probe) 扫长按时长或离散间隔，详见 [`docs/paint_rate_probe.md`](paint_rate_probe.md)。

## 用法（命令行）

```bash
cd scripts/texture_prep
python prepare_texture.py --config config/default.yaml ^
  --input path/to/source.png ^
  --output-png ../../assets/processed/out_256.png ^
  --output-bin ../../assets/processed/out_256_indices.bin ^
  --output-meta ../../assets/processed/out_256_meta.json
```

- `--palette-json` 可省略（使用配置里 `paths.palette_json`，相对路径相对于 **YAML 所在目录** `config/`）。
- 输入必须 **宽高相等**；否则脚本退出并报错。

## 缩放与透明

- **RGB** 通道默认使用 `lanczos`（可在 `config/default.yaml` 的 `resampling.rgb` 改为 `bilinear` / `box` / `nearest`）。
- **Alpha** 默认 `nearest`，减轻半透明边缘在缩放后变成大量「需绘制」杂点的问题。
- **绘制判定**：`alpha >= alpha_threshold`（默认 `128`）视为落笔；否则视为 **NO_DRAW**。

## 输出语义

### PNG（`--output-png`）

- **RGBA**，固定 **256×256**。
- 可绘制像素：`A = 255`，`RGB` 为色板中某一色的精确值。
- 跳过像素：`A = 0`，`RGB = 0`（占位；固件应以 alpha 或 `.bin` 为准）。

### 索引二进制（可选 `--output-bin`）

- 长度 **65536** 字节（`256 × 256`），**行优先**：`i = y * 256 + x`（`y` 自上而下，`x` 自左而右）。
- 每字节：`0–83` 与 [palette_default.json](assets/generated/palette_default.json) 中 `colors[].index` 一致。
- **`255` (`0xFF`)**：**NO_DRAW**，固件不得在此处落笔。

### 元数据（可选 `--output-meta`）

- JSON：记录 `alpha_threshold`、`index_sentinel`、`resampling_*`、`quantization: nearest_lab`、源文件与色表路径等，便于固件与 PC 工具对齐版本。

## 与色板的关系

量化只读 [../assets/generated/palette_default.json](../assets/generated/palette_default.json)。若你更新了参考截图并重跑 `palette_extract`，应再运行本脚本以刷新贴图输出。

Lab 转换实现与 `palette_extract` 共用 [../scripts/common/colorutil.py](../scripts/common/colorutil.py)。

画布默认画笔格点与四角测试见 [canvas_home_test.md](canvas_home_test.md)（脚本 `scripts/texture_prep/generate_probe.py`）。
