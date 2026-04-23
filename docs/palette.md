# 工作色彩映射（默认色板）

## 索引约定

- 网格：**12 列 × 7 行**，共 **84** 色。
- **行优先（row-major）**：`row` 从上到下为 `0 … 6`，`col` 从左到右为 `0 … 11`。
- **线性索引**：`index = row * 12 + col`，范围 `0 … 83`。

与游戏内光标移动顺序不一致时，应在此文档中改约定，并同步修改 [scripts/palette_extract/config/default.yaml](scripts/palette_extract/config/default.yaml) 中的 `grid.index_order`（若实现支持其它顺序）。

## 参考图规范

- 将截图或导出图放在 [assets/reference/](assets/reference/)，建议使用 **PNG** 或高质量 **JPG**，避免多次重压缩。
- **尽量避免 UI 叠加**：例如橙色选中框会混入采样 ROI，导致该格颜色偏差；若无法避免，可缩小 `sampling.roi_ratio` 或调整 `crop` 仅包住色板区域，并关注脚本输出的质检警告。

## 生成色表

在仓库根目录执行（需已安装依赖，见 `scripts/palette_extract/requirements.txt`）：

```bash
cd scripts/palette_extract
pip install -r requirements.txt
python extract_palette.py --config config/default.yaml --output-json ../../assets/generated/palette_default.json
```

可选生成 C 头文件供固件包含：

```bash
python extract_palette.py --config config/default.yaml --output-json ../../assets/generated/palette_default.json --emit-header ../../assets/generated/palette_default.h
```

## 换图重采

1. 替换 `assets/reference/` 下的源图（或 `--input` 指定路径）。
2. 若分辨率或 UI 裁切变化，调整 `default.yaml` 中的 `crop` 与 `sampling` 参数。
3. 重新运行命令，检查终端中的 **WARN**（过滤后像素过少、结果接近背景等）。

