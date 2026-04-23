"""笔划顺序策略与空跑/QUICK 统计的烟测 (unittest)。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_TPD = Path(__file__).resolve().parent
if str(_TPD) not in sys.path:
    sys.path.insert(0, str(_TPD))

import svg_compiler as sc
from common import palette_defaults as paldef

_PR, _PC = paldef.index_row_col_arrays_84(sc.DEFAULT_PALETTE_JSON)


def _count_quick_ops(cmds: list[sc.DrawCmd]) -> int:
    return sum(1 for c in cmds if c.op == sc.DRAW_CMD_OP_QUICK)


def _s(r: int, c: int, slot: int) -> sc.Stroke:
    return sc.Stroke(start=(r, c), end=(r, c), runs=[], slot=slot)


class OrderStrategiesTest(unittest.TestCase):
    def test_min_air_matches_penalized_w_zero(self) -> None:
        home = (0, 0)
        strokes = [_s(10, 10, 0), _s(5, 5, 1), _s(12, 10, 0)]
        a = sc.order_strokes_multicolor(
            home, list(strokes), sc.STROKE_ORDER_MIN_AIR
        )
        b = sc.order_strokes_multicolor(
            home,
            list(strokes),
            sc.STROKE_ORDER_PENALIZED,
            quick_switch_penalty=0.0,
            start_quick_index=0,
        )
        self.assertEqual(
            [(x.start, x.end, x.slot) for x in a],
            [(x.start, x.end, x.slot) for x in b],
        )

    def test_by_slot_runs_slot_zero_before_slot_one(self) -> None:
        home = (0, 0)
        strokes = [_s(20, 20, 1), _s(1, 1, 0), _s(3, 1, 0)]
        o = sc.order_strokes_multicolor(
            home, list(strokes), sc.STROKE_ORDER_BY_SLOT
        )
        slots = [int(s.slot) for s in o]
        i0s = [i for i, sl in enumerate(slots) if sl == 0]
        i1s = [i for i, sl in enumerate(slots) if sl == 1]
        if i0s and i1s:
            self.assertLess(max(i0s), min(i1s), "by_slot: 所有槽0应在槽1之前")

    def test_estimate_path_stats_matches_quicks_in_cmds(self) -> None:
        home = (128, 128)
        ordered = [_s(10, 10, 2), _s(20, 20, 2), _s(30, 30, 1)]
        sq = 2
        air, nq = sc.estimate_path_stats(home, ordered, sq, count_quick=True)
        cmds = sc._build_cmd_list_multicolor(
            home,
            ordered,
            start_quick_index=sq,
            insert_quick=True,
            pal_row=_PR,
            pal_col=_PC,
            emit_color_quick=True,
        )
        self.assertEqual(nq, _count_quick_ops(cmds))
        self.assertGreaterEqual(air, 0)

    def test_high_penalty_prefers_fewer_slot_switches(self) -> None:
        home = (0, 0)
        strokes = [_s(100, 0, 0), _s(1, 0, 1), _s(2, 0, 0)]
        o_low = sc.order_strokes_multicolor(
            home,
            list(strokes),
            sc.STROKE_ORDER_PENALIZED,
            quick_switch_penalty=0.0,
            start_quick_index=0,
        )
        o_high = sc.order_strokes_multicolor(
            home,
            list(strokes),
            sc.STROKE_ORDER_PENALIZED,
            quick_switch_penalty=50_000.0,
            start_quick_index=0,
        )
        _a, q_low = sc.estimate_path_stats(
            home, o_low, 0, count_quick=True
        )
        _b, q_high = sc.estimate_path_stats(
            home, o_high, 0, count_quick=True
        )
        self.assertGreater(q_low, 1, "W=0 时应为省空跑产生超过一次换色")
        self.assertLessEqual(q_high, q_low, "极大 W 应不增加于小 W 的换色次数")


if __name__ == "__main__":
    unittest.main()
