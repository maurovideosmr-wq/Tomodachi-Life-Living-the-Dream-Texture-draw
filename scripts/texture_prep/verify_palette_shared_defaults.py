"""校验 palette JSON 的九格 default index 与 common/palette_defaults 及 gen 头一致(策划阶段 A)。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCR = Path(__file__).resolve().parent.parent
_REPO = _SCR.parent
if str(_SCR) not in sys.path:
    sys.path.insert(0, str(_SCR))

from common import palette_defaults as pd


def main() -> int:
    pj = _REPO / "assets" / "generated" / "palette_default.json"
    a = pd.default_nine_indices_from_palette_path(pj)
    h = _REPO / "firmware" / "paint_vector_flash" / "palette_defaults.h"
    if not h.is_file():
        print("skip: 无", h)
        return 0
    t = h.read_text(encoding="utf-8")
    for i, v in enumerate(a):
        if f"{v}u" not in t and f" {v}," not in t:
            print("warning: 头里未找到", i, v)
    with open(pj, encoding="utf-8") as f:
        data = json.load(f)
    by_rc: dict[tuple[int, int], int] = {}
    for c in data["colors"]:
        by_rc[(int(c["row"]), int(c["col"]))] = int(c["index"])
    for j, (r1, c1) in enumerate(pd.QUICK_DEFAULT_CELLS_1BASED):
        r0, c0 = r1 - 1, c1 - 1
        assert a[j] == by_rc[(r0, c0)], (j, a[j], by_rc.get((r0, c0)))
    print("OK: default nine =", a)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
