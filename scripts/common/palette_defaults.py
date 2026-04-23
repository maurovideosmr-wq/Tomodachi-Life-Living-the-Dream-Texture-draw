"""
九快选在 12×7 上约定默认格 (1-based R/C, C1=左) 与 palette JSON 的 index 解析。

与 palette_chain_sim / 固件 palette_defaults 同源；改格请在唯一真相源更新。
"""

from __future__ import annotations

import json
from pathlib import Path

# 槽0=顶…槽8=底；元组为 (1-based 行, 1-based 列) = (R, C), C1=左。
# 槽0 为「C7R1」简单色第一格(行7 列1)，勿与口语「R1C7」混淆(那是行1 列7，另一格)。
QUICK_DEFAULT_CELLS_1BASED: tuple[tuple[int, int], ...] = (
    (7, 1),
    (1, 1),
    (4, 11),
    (4, 10),
    (4, 9),
    (4, 7),
    (4, 6),
    (4, 4),
    (4, 2),
)


def default_nine_indices_from_palette_path(path: str | Path) -> list[int]:
    p = Path(path)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    by_rc: dict[tuple[int, int], int] = {}
    for c in data["colors"]:
        r, co = int(c["row"]), int(c["col"])
        by_rc[(r, co)] = int(c["index"])
    out: list[int] = []
    for r1, c1 in QUICK_DEFAULT_CELLS_1BASED:
        r0, c0 = r1 - 1, c1 - 1
        if (r0, c0) not in by_rc:
            raise ValueError(
                f"palette {p} 缺少格 (row={r0}, col={c0}) 0-based, 1-based 为 R{r1}C{c1}"
            )
        out.append(by_rc[(r0, c0)])
    if len(out) != 9:
        raise ValueError("default nine length")
    return out


def index_row_col_arrays_84(path: str | Path) -> tuple[list[int], list[int]]:
    """
    与固件 `PAL_INDEX_ROW` / `PAL_INDEX_COL` 同源(0..83, 0-based 格).
    用于编译期 BFS: index -> (r,c) 在 12x7 全色上。
    """
    p = Path(path)
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    row: list[int] = [0] * 84
    col: list[int] = [0] * 84
    for c in data["colors"]:
        i = int(c["index"])
        if 0 <= i < 84:
            row[i] = int(c["row"])
            col[i] = int(c["col"])
    return row, col
