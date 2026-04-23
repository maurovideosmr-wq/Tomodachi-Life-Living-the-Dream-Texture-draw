#!/usr/bin/env python3
"""
Compile monochrome line-art SVG to PROGMEM draw_vector_data.h (DrawCmd opcodes).
Uses 8-connected grid, run-length; 多色时可选用近邻空跑、按槽分层或带换色惩罚的贪心顺序 (Chebyshev)。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np

_TPD = Path(__file__).resolve().parent
_SCR = _TPD.parent
for _p in (_SCR, _TPD):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from common import colorutil
from common import palette_defaults as paldef

import full_palette_bfs
import svg_color

_REPO = _SCR.parent
DEFAULT_PALETTE_JSON = _REPO / "assets" / "generated" / "palette_default.json"

# -----------------------------------------------------------------------------
# Hat code matches NintendoSwitchControlLibrary Hat:: 0-7, NEUTRAL=8
HAT_TO_DR_DC: list[tuple[int, int]] = [
    (-1, 0),  # 0 UP
    (-1, 1),  # 1 UP_RIGHT
    (0, 1),   # 2 RIGHT
    (1, 1),   # 3 DOWN_RIGHT
    (1, 0),   # 4 DOWN
    (1, -1),  # 5 DOWN_LEFT
    (0, -1),  # 6 LEFT
    (-1, -1), # 7 UP_LEFT
]


def drdc_to_hat(dr: int, dc: int) -> int:
    for i, (ddr, ddc) in enumerate(HAT_TO_DR_DC):
        if ddr == dr and ddc == dc:
            return i
    raise ValueError(f"invalid 8-step dr,dc: {dr}, {dc}")


def chebyshev(
    a: tuple[int, int], b: tuple[int, int]
) -> int:
    (r0, c0) = a
    (r1, c1) = b
    return max(abs(r0 - r1), abs(c0 - c1))


def grid_line_8(
    c0: int, r0: int, c1: int, r1: int
) -> list[tuple[int, int]]:
    """8-connected grid line (col, row) inclusive, diagonal-first when both off."""
    c, r = c0, r0
    out: list[tuple[int, int]] = [(c, r)]
    while (c, r) != (c1, r1):
        dc = 0 if c1 == c else (1 if c1 > c else -1)
        dr = 0 if r1 == r else (1 if r1 > r else -1)
        if c == c1:
            r += dr
        elif r == r1:
            c += dc
        else:
            c += dc
            r += dr
        out.append((c, r))
    return out


def path_cells_to_runs(
    cells: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """
    cells: col,row along stroke in order.
    Returns list of (hat, n_steps) where n_steps = k-1 for k cells in that direction run.
    """
    if not cells:
        return []
    if len(cells) == 1:
        return []  # caller uses stamp-only: DRAG arg2=0

    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(cells) - 1:
        c0, r0 = cells[i]
        c1, r1 = cells[i + 1]
        dr = r1 - r0
        dc = c1 - c0
        if dr not in (-1, 0, 1) or dc not in (-1, 0, 1) or (dr == 0 and dc == 0):
            i += 1
            continue
        hat = drdc_to_hat(dr, dc)
        n_steps = 1
        j = i + 1
        while j < len(cells) - 1:
            cj, rj = cells[j]
            cj1, rj1 = cells[j + 1]
            dr2 = rj1 - rj
            dc2 = cj1 - cj
            if (dr2, dc2) == (dr, dc):
                n_steps += 1
                j += 1
            else:
                break
        runs.append((hat, n_steps))
        i = j
    return runs


def _parse_viewbox(s: str) -> tuple[float, float, float, float]:
    parts = re.split(r"[,\s]+", s.strip())
    if len(parts) < 4:
        raise ValueError(f"viewBox needs 4 numbers: {s!r}")
    return tuple(map(float, parts[:4]))  # type: ignore[return-value]


def _get_svg_size(el: ET.Element) -> tuple[float, float, float, float, float, float] | None:
    """Return (minx, miny, w, h, width_attr, height_attr) for viewBox or width/height."""
    vb = el.get("viewBox")
    if vb:
        minx, miny, w, h = _parse_viewbox(vb)
        return (minx, miny, w, h, w, h)
    w = el.get("width")
    h = el.get("height")
    if w and h:
        wf = float(re.sub(r"[^\d.]+", "", w) or 0) or 256.0
        hf = float(re.sub(r"[^\d.]+", "", h) or 0) or 256.0
        return (0.0, 0.0, wf, hf, wf, hf)
    return None


def _to_grid(
    x: float,
    y: float,
    minx: float,
    miny: float,
    w: float,
    h: float,
    gsize: int = 256,
) -> tuple[int, int]:
    if w <= 0 or h <= 0:
        raise ValueError("non-positive viewBox size")
    col = int(round((x - minx) / w * (gsize - 1)))
    row = int(round((y - miny) / h * (gsize - 1)))
    col = max(0, min(gsize - 1, col))
    row = max(0, min(gsize - 1, row))
    return (col, row)


@dataclass
class Stroke:
    """One continuous subpath: sequence of (hat, n_steps) after AIR to first cell, plus endpoints."""

    start: tuple[int, int]  # (row, col) for TSP
    end: tuple[int, int]
    # draw runs: (hat, n_steps) n_steps>=1; if empty, single-stamp at start (0 runs -> DRAG 0)
    runs: list[tuple[int, int]] = field(default_factory=list)
    slot: int = 0  # quick-palette slot 0=top..8=bottom; mono uses 0
    # 多色 84 自动模式: 笔划目标色=色表 0..83; None 时沿用九目标分槽
    ink_index: int | None = None


@dataclass
class DrawCmd:
    op: int
    arg1: int
    arg2: int


# DrawCmd 操作码与固件 `paint_vector_flash.ino` 一致
DRAW_CMD_OP_AIR = 0x00
DRAW_CMD_OP_DRAG = 0x01
DRAW_CMD_OP_QUICK = 0x02
DRAW_CMD_OP_FULL_BIND = 0x03
"""全色将槽绑到 arg1(0..83) 的 palette index, arg2=槽0..8; 与默认格 index 等则发 QUICK 等效。"""
DRAW_CMD_OP_SUB_HAT4 = 0x04
"""全色 12x7 内 4 向; arg1=0..3 U/R/D/L, arg2=0; 仅允许紧跟在 FULL_BIND(0:03) 后由固件在子过程内消费。"""

# 多色换色发码：内联(每笔前按需 FULL_BIND) / 段首把本段用到的非默认槽先铺好再仅 QUICK
COLOR_EMIT_INLINE = "inline"
COLOR_EMIT_BATCH_PREFILL = "batch_prefill"
ColorEmit = Literal["inline", "batch_prefill"]
# False：槽变一律走 0:03+0:04(或 0 条帽键)，不自动发 0:02(快选由你在机上手切); True：沿用原 QUICK+全色 混合发码

# 多色笔划顺序（上位机）；固件仍只按 DrawCmd 顺序执行
STROKE_ORDER_MIN_AIR = "min_air"
STROKE_ORDER_BY_SLOT = "by_slot"
STROKE_ORDER_PENALIZED = "penalized_greedy"
StrokeOrder = Literal["min_air", "by_slot", "penalized_greedy"]
_STROKE_ORDERS = frozenset(
    (STROKE_ORDER_MIN_AIR, STROKE_ORDER_BY_SLOT, STROKE_ORDER_PENALIZED)
)


def _merge_polyline(cells: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not cells:
        return []
    out = [cells[0]]
    for c, r in cells[1:]:
        if (c, r) != out[-1]:
            out.append((c, r))
    return out


def _split_paths_on_move(d: str) -> list[str]:
    """
    Return list of d fragments: each is one continuous 'stroke' (split before each M m).
    First fragment may be empty; skip.
    """
    m_pos = [m.start() for m in re.finditer(r"[Mm]", d)]
    if not m_pos:
        return [d] if d.strip() else []
    out: list[str] = []
    for i, start in enumerate(m_pos):
        end = m_pos[i + 1] if i + 1 < len(m_pos) else len(d)
        frag = d[start:end].strip()
        if frag:
            out.append(frag)
    return out if out else [d.strip()] if d.strip() else []


def _collect_strokes(
    d: str,
    minx: float,
    miny: float,
    w: float,
    h: float,
    gsize: int,
    samples: float,
    slot: int = 0,
    ink_index: int | None = None,
) -> list[Stroke]:
    from svg.path import parse_path  # type: ignore[import-untyped]

    fragments = _split_paths_on_move(d)
    strokes: list[Stroke] = []
    for frag in fragments:
        if not frag:
            continue
        p = parse_path(frag)
        # Sample entire fragment (one Move at start of frag)
        total_len = p.length() if p.length() else 0.0
        n = max(4, int(total_len * samples) + 1)
        cells: list[tuple[int, int]] = []
        for k in range(n):
            t = k / max(1, n - 1)
            pt = p.point(t)
            col, row = _to_grid(pt.real, pt.imag, minx, miny, w, h, gsize)
            cells.append((col, row))
        # Exact subpath endpoints (avoids off-by-one on long axis-only lines)
        pa, pz = p.point(0.0), p.point(1.0)
        cells[0] = _to_grid(pa.real, pa.imag, minx, miny, w, h, gsize)
        cells[-1] = _to_grid(pz.real, pz.imag, minx, miny, w, h, gsize)
        cells = _merge_polyline(cells)
        if not cells:
            continue
        # Build full list through line_8 between consecutive samples
        full: list[tuple[int, int]] = [cells[0]]
        for i in range(len(cells) - 1):
            c0, r0 = full[-1]
            c1, r1 = cells[i + 1]
            seg = grid_line_8(c0, r0, c1, r1)
            full.extend(seg[1:])
        full = _merge_polyline(full)
        if not full:
            continue
        r0, c0 = full[0][1], full[0][0]
        r1, c1 = full[-1][1], full[-1][0]
        runs = path_cells_to_runs([(fc, fr) for fc, fr in full])
        strokes.append(
            Stroke(
                start=(r0, c0),
                end=(r1, c1),
                runs=runs,
                slot=slot,
                ink_index=ink_index,
            )
        )
    return strokes


def _collect_all_strokes(
    path_d_list: list[str],
    minx: float,
    miny: float,
    w: float,
    h: float,
    gsize: int,
    samples: float,
    slot: int = 0,
) -> list[Stroke]:
    all_s: list[Stroke] = []
    for d in path_d_list:
        all_s.extend(
            _collect_strokes(
                d, minx, miny, w, h, gsize, samples, slot=slot
            )
        )
    return all_s


def _nearest_neighbor_order(
    home: tuple[int, int], strokes: list[Stroke]
) -> list[Stroke]:
    if not strokes:
        return []
    pos = (home[0], home[1])  # row, col
    remaining = list(strokes)
    out: list[Stroke] = []
    while remaining:
        best = min(remaining, key=lambda s: chebyshev(pos, s.start))
        out.append(best)
        remaining.remove(best)
        pos = (best.end[0], best.end[1])
    return out


def _order_strokes_by_slot(
    home: tuple[int, int], strokes: list[Stroke]
) -> list[Stroke]:
    """槽 0…8 升序、跳过空槽；槽内为近邻序（从进入该槽前一刻位姿起算）。"""
    if not strokes:
        return []
    by_slot: dict[int, list[Stroke]] = {}
    for s in strokes:
        sl = int(s.slot) & 0xFF
        if sl > 8:
            sl = 8
        by_slot.setdefault(sl, []).append(s)
    pos = (home[0], home[1])
    out: list[Stroke] = []
    for slot in range(9):
        group = by_slot.get(slot) or []
        if not group:
            continue
        sub = _nearest_neighbor_order(pos, group)
        out.extend(sub)
        if sub:
            pos = (sub[-1].end[0], sub[-1].end[1])
    return out


def _strokes_color_ink_mode(strokes: list[Stroke]) -> bool:
    return bool(strokes) and all(s.ink_index is not None for s in strokes)


def _order_strokes_by_ink(
    home: tuple[int, int], strokes: list[Stroke]
) -> list[Stroke]:
    """按 0..83 色表下标升序分组，组内近邻序。"""
    if not strokes:
        return []
    by_ink: dict[int, list[Stroke]] = {}
    for s in strokes:
        if s.ink_index is None:
            raise ValueError("ink_index required")
        ik = int(s.ink_index) & 0xFF
        by_ink.setdefault(ik, []).append(s)
    pos = (home[0], home[1])
    out: list[Stroke] = []
    for ink in sorted(by_ink.keys()):
        group = by_ink[ink]
        sub = _nearest_neighbor_order(pos, group)
        out.extend(sub)
        if sub:
            pos = (sub[-1].end[0], sub[-1].end[1])
    return out


def _order_strokes_penalized_ink(
    home: tuple[int, int],
    strokes: list[Stroke],
    quick_switch_penalty: float,
    start_quick_index: int,
) -> list[Stroke]:
    if not strokes:
        return []
    pos = (home[0], home[1])
    w = float(quick_switch_penalty)
    last_ink: int | None = None
    remaining = list(strokes)
    out: list[Stroke] = []
    while remaining:
        def score(s: Stroke) -> float:
            d = float(chebyshev(pos, s.start))
            if s.ink_index is None:
                raise ValueError("ink_index required")
            iix = int(s.ink_index) & 0xFF
            if last_ink is not None and iix != (last_ink & 0xFF):
                d += w
            return d

        best = min(remaining, key=score)
        out.append(best)
        remaining.remove(best)
        pos = (best.end[0], best.end[1])
        if best.ink_index is not None:
            last_ink = int(best.ink_index) & 0xFF
    return out


def _assign_slots_lru(ordered: list[Stroke], def9: list[int]) -> None:
    """九槽内容 LRU 替换：在 sim 中放入每笔所需 ink; 只写 s.slot, 0..8。"""
    sim: list[int] = [int(def9[sl] & 0xFF) for sl in range(9)]
    last_use: list[int] = [-1] * 9
    for i, s in enumerate(ordered):
        if s.ink_index is None:
            raise ValueError("ink_index required for LRU")
        t = int(s.ink_index) & 0xFF
        hit = [sl for sl in range(9) if (sim[sl] & 0xFF) == t]
        if hit:
            s.slot = int(min(hit))
        else:
            ev = int(min(range(9), key=lambda sl: (last_use[sl], sl)))
            s.slot = ev
            sim[ev] = t
        last_use[int(s.slot) & 0xFF] = i


def _order_strokes_penalized_greedy(
    home: tuple[int, int],
    strokes: list[Stroke],
    quick_switch_penalty: float,
    start_quick_index: int,
) -> list[Stroke]:
    """
    下一笔代价 = 空跑切比雪夫 + (与当前笔色槽不同 ? W : 0)。
    W=0 时与 _nearest_neighbor_order 行为一致。current_slot 随每笔结束更新；首笔相对 start_quick_index。
    """
    if not strokes:
        return []
    pos = (home[0], home[1])
    w = float(quick_switch_penalty)
    current_slot = int(start_quick_index) & 0xFF
    remaining = list(strokes)
    out: list[Stroke] = []
    while remaining:
        def score(s: Stroke) -> float:
            d = float(chebyshev(pos, s.start))
            ss = int(s.slot) & 0xFF
            if ss != (current_slot & 0xFF):
                d += w
            return d

        best = min(remaining, key=score)
        out.append(best)
        remaining.remove(best)
        pos = (best.end[0], best.end[1])
        current_slot = int(best.slot) & 0xFF
    return out


def order_strokes_multicolor(
    home: tuple[int, int],
    strokes: list[Stroke],
    stroke_order: StrokeOrder | str,
    *,
    quick_switch_penalty: float = 0.0,
    start_quick_index: int = 0,
) -> list[Stroke]:
    o = str(stroke_order)
    if o not in _STROKE_ORDERS:
        raise ValueError(
            f"stroke_order 须为 {sorted(_STROKE_ORDERS)} 之一, 得 {o!r}"
        )
    inked = _strokes_color_ink_mode(strokes)
    if o == STROKE_ORDER_MIN_AIR:
        return _nearest_neighbor_order(home, strokes)
    if o == STROKE_ORDER_BY_SLOT:
        return (
            _order_strokes_by_ink(home, strokes)
            if inked
            else _order_strokes_by_slot(home, strokes)
        )
    return (
        _order_strokes_penalized_ink(home, strokes, quick_switch_penalty, start_quick_index)
        if inked
        else _order_strokes_penalized_greedy(
            home, strokes, quick_switch_penalty, start_quick_index
        )
    )


def estimate_path_stats(
    home: tuple[int, int],
    ordered: list[Stroke],
    start_quick_index: int,
    *,
    count_quick: bool = True,
) -> tuple[int, int]:
    """
    各笔前空跑步数(切比雪夫之和); count_quick 时仍按「槽变则计一次切槽」估计(多色时若用 FULL_BIND 应改用 cmds 统计).
    单色: count_quick=False 则 quick=0.
    """
    g_row, g_col = int(home[0]), int(home[1])
    current_slot = int(start_quick_index) & 0xFF
    air_sum = 0
    n_quick = 0
    for s in ordered:
        sn = int(s.slot) & 0xFF
        if count_quick and sn != (current_slot & 0xFF):
            n_quick += 1
        current_slot = sn
        tr, tc = int(s.start[0]), int(s.start[1])
        if (g_row, g_col) != (tr, tc):
            air_sum += chebyshev((g_row, g_col), (tr, tc))
        g_row, g_col = int(s.end[0]), int(s.end[1])
    return air_sum, n_quick


def _count_quick_full_subhat_in_cmds(
    cmds: list[DrawCmd],
) -> tuple[int, int, int]:
    nq, nf, ns = 0, 0, 0
    for c in cmds:
        if c.op == DRAW_CMD_OP_QUICK:
            nq += 1
        elif c.op == DRAW_CMD_OP_FULL_BIND:
            nf += 1
        elif c.op == DRAW_CMD_OP_SUB_HAT4:
            ns += 1
    return nq, nf, ns


def _count_quick_and_full_in_cmds(cmds: list[DrawCmd]) -> tuple[int, int]:
    nq, nf, _s = _count_quick_full_subhat_in_cmds(cmds)
    return nq, nf


def _append_full_bind_bfs(
    cmds: list[DrawCmd],
    target_index: int,
    slot: int,
    sim: list[int],
    pal_r: list[int],
    pal_c: list[int],
) -> None:
    """在 cmds 后追加 0:03 及 N 条 0:04, 并更新 sim[slot]。"""
    t = target_index & 0xFF
    src_i = sim[slot] & 0xFF
    if src_i > 83 or t > 83:
        raise ValueError("palette index 须为 0..83")
    sr, sc = pal_r[src_i], pal_c[src_i]
    tr, tc = pal_r[t], pal_c[t]
    hats = full_palette_bfs.full_palette_bfs_hats(sr, sc, tr, tc)
    cmds.append(DrawCmd(DRAW_CMD_OP_FULL_BIND, t, slot))
    for m in hats:
        cmds.append(DrawCmd(DRAW_CMD_OP_SUB_HAT4, int(m) & 0xFF, 0))
    sim[slot] = t


def _build_cmd_list(
    home: tuple[int, int], ordered: list[Stroke]
) -> list[DrawCmd]:
    """home (row, col) per firmware convention: arg1=col, arg2=row for AIR."""
    return _build_cmd_list_multicolor(home, ordered, start_quick_index=0, insert_quick=False)


def _append_stroke_vector(
    g_row: int, g_col: int, s: Stroke, cmds: list[DrawCmd]
) -> tuple[int, int]:
    tr, tc = s.start[0], s.start[1]
    if (g_row, g_col) != (tr, tc):
        cmds.append(DrawCmd(DRAW_CMD_OP_AIR, tc, tr))  # AIR: col, row
        g_row, g_col = tr, tc
    if not s.runs:
        cmds.append(DrawCmd(DRAW_CMD_OP_DRAG, 0, 0))  # single stamp, hat arg ignored
    else:
        for hat, n in s.runs:
            cmds.append(DrawCmd(DRAW_CMD_OP_DRAG, hat, n))
            for _ in range(n):
                dr, dc = HAT_TO_DR_DC[hat]
                g_row += dr
                g_col += dc
    return g_row, g_col


def _build_cmd_list_multicolor(
    home: tuple[int, int],
    ordered: list[Stroke],
    *,
    start_quick_index: int = 0,
    insert_quick: bool = True,
    palette_index_by_slot: list[int] | None = None,
    default_nine: list[int] | None = None,
    color_emit: str = COLOR_EMIT_INLINE,
    pal_row: list[int] | None = None,
    pal_col: list[int] | None = None,
    emit_color_quick: bool = True,
) -> list[DrawCmd]:
    """
    若 insert_quick: 在笔划前发换色(见 emit_color_quick)。
    default_nine 为 9 个默认 index; palette_index_by_slot 为 9 槽用户目标(缺省=default_nine).
    color_emit: inline / batch_prefill
    全色换绑: 每个 FULL_BIND(0:03) 后紧跟 N 条 SUB_HAT4(0:04)（编译期 BFS; pal_row/pal_col 为 0..83 的 r/c）。
    emit_color_quick=True 时: 可发 0:02(仅快选)或 0:03+0:04; False 时: 槽变只发 0:03+0:04(快选不写入矢量, 机上手动)。
    """
    cmds: list[DrawCmd] = []
    g_row, g_col = int(home[0]), int(home[1])
    if not insert_quick:
        current_slot = 0
        for s in ordered:
            g_row, g_col = _append_stroke_vector(g_row, g_col, s, cmds)
        return cmds

    if default_nine is not None:
        def9 = list(default_nine)
    else:
        try:
            def9 = list(paldef.default_nine_indices_from_palette_path(DEFAULT_PALETTE_JSON))
        except (OSError, ValueError, KeyError):
            def9 = [i for i in range(9)]
    pidx: list[int] = (
        list(palette_index_by_slot) if palette_index_by_slot is not None else list(def9)
    )
    if len(pidx) != 9 or len(def9) != 9:
        raise ValueError("palette 与 default 各须 9 项")
    if pal_row is None or pal_col is None or len(pal_row) != 84 or len(pal_col) != 84:
        raise ValueError(
            "多色 BFS 需要每 index 0..83 的 (row,col) : pal_row, pal_col 各 84 项"
        )

    if color_emit == COLOR_EMIT_BATCH_PREFILL:
        used = {int(s.slot) & 0xFF for s in ordered}
        sim = [int(def9[sl] & 0xFF) for sl in range(9)]
        last_full_slot: int | None = None
        for sl in range(9):
            if sl not in used:
                continue
            t, d0 = pidx[sl] & 0xFF, def9[sl] & 0xFF
            if t != d0 and sim[sl] != t:
                _append_full_bind_bfs(cmds, t, sl, sim, pal_row, pal_col)
                last_full_slot = sl
        if last_full_slot is not None:
            current_slot = int(last_full_slot) & 0xFF
        else:
            current_slot = int(start_quick_index) & 0xFF
        for s in ordered:
            to_slot = int(s.slot) & 0xFF
            if to_slot != current_slot:
                if emit_color_quick:
                    cmds.append(DrawCmd(DRAW_CMD_OP_QUICK, to_slot, 0))
                else:
                    _append_full_bind_bfs(
                        cmds,
                        pidx[to_slot] & 0xFF,
                        to_slot,
                        sim,
                        pal_row,
                        pal_col,
                    )
                current_slot = to_slot
            g_row, g_col = _append_stroke_vector(g_row, g_col, s, cmds)
        return cmds

    # inline: emit_color_quick 时 可仅 QUICK; 否则 槽变一律全色序列(0:03+0:04, 由固件在需默认时走短路径)
    sim = [int(def9[sl] & 0xFF) for sl in range(9)]
    current_slot = int(start_quick_index) & 0xFF
    for s in ordered:
        to_slot = int(s.slot) & 0xFF
        if to_slot != current_slot:
            ti = pidx[to_slot] & 0xFF
            de = def9[to_slot] & 0xFF
            if emit_color_quick:
                if sim[to_slot] == ti:
                    cmds.append(DrawCmd(DRAW_CMD_OP_QUICK, to_slot, 0))
                elif ti == de:
                    cmds.append(DrawCmd(DRAW_CMD_OP_QUICK, to_slot, 0))
                else:
                    _append_full_bind_bfs(cmds, ti, to_slot, sim, pal_row, pal_col)
            else:
                _append_full_bind_bfs(cmds, ti, to_slot, sim, pal_row, pal_col)
            current_slot = to_slot
        g_row, g_col = _append_stroke_vector(g_row, g_col, s, cmds)
    return cmds


def _build_cmd_list_multicolor_auto(
    home: tuple[int, int],
    ordered: list[Stroke],
    def9: list[int],
    pal_row: list[int],
    pal_col: list[int],
    *,
    start_quick_index: int = 0,
    emit_color_quick: bool = True,
) -> list[DrawCmd]:
    """
    每笔用 ink_index(0..83); 槽位由 _assign_slots_lru 定。先保证 sim[槽] 与 ink 一致，再切高亮(QUICK)或全色绑。
    超 9 种色时 LRU 会复用槽，发码仍按 0:03+0:04/0:02 与固件一致。
    """
    if len(def9) != 9 or len(pal_row) != 84 or len(pal_col) != 84:
        raise ValueError("def9/pal_row/pal_col 尺寸非法")
    cmds: list[DrawCmd] = []
    g_row, g_col = int(home[0]), int(home[1])
    sim: list[int] = [int(def9[sl] & 0xFF) for sl in range(9)]
    current_slot: int = int(start_quick_index) & 0xFF
    for s in ordered:
        if s.ink_index is None:
            raise ValueError("多色 auto 需要 ink_index")
        ti: int = int(s.ink_index) & 0xFF
        to_slot: int = int(s.slot) & 0xFF
        de: int = int(def9[to_slot] & 0xFF)
        if to_slot == (current_slot & 0xFF) and (sim[to_slot] & 0xFF) != ti:
            if emit_color_quick:
                if ti == de:
                    cmds.append(DrawCmd(DRAW_CMD_OP_QUICK, to_slot, 0))
                    sim[to_slot] = ti
                else:
                    _append_full_bind_bfs(cmds, ti, to_slot, sim, pal_row, pal_col)
            else:
                _append_full_bind_bfs(cmds, ti, to_slot, sim, pal_row, pal_col)
        elif to_slot != (current_slot & 0xFF):
            if emit_color_quick:
                if (sim[to_slot] & 0xFF) == ti:
                    cmds.append(DrawCmd(DRAW_CMD_OP_QUICK, to_slot, 0))
                elif ti == de:
                    cmds.append(DrawCmd(DRAW_CMD_OP_QUICK, to_slot, 0))
                    sim[to_slot] = ti
                else:
                    _append_full_bind_bfs(cmds, ti, to_slot, sim, pal_row, pal_col)
            else:
                _append_full_bind_bfs(cmds, ti, to_slot, sim, pal_row, pal_col)
            current_slot = to_slot
        g_row, g_col = _append_stroke_vector(g_row, g_col, s, cmds)
        current_slot = int(s.slot) & 0xFF
    return cmds


# --- Public API for GUI / CLI ---


@dataclass
class RemapColorRow:
    raw_hex: str
    path_count: int
    slot: int
    target_rgb: tuple[int, int, int]
    delta_e: float
    # 多色 84 自动: 0..83 下标(此时 slot 可能仅作占位列)
    nearest_palette_index: int | None = None


@dataclass
class CompileResult:
    cmds: list[DrawCmd]
    strokes: int
    home: tuple[int, int]
    bytes_size: int
    ordered_strokes: list[Stroke] = field(default_factory=list)
    multicolor: bool = False
    auto_nearest_84: bool = False
    """True: 每 path 在 84 色里 Lab 最近 + 九槽 LRU 发码(非手填九格下标)。"""
    nine_target_rgb: list[tuple[int, int, int]] = field(default_factory=list)
    """九快选槽目标色 sRGB; 多色时由 palette 下标或 GUI 提供。"""
    palette_index_per_slot: list[int] | None = None
    """与九槽一一对应的 0..83 色表索引,供 setup 文档; 可缺省。"""
    default_nine_indices: list[int] | None = None
    """与 palette JSON 九格约定格对应的 9 个默认 index(与固件 PALETTE_DEFAULT_NINE 一致)。"""
    start_quick_index: int = 0
    """自动化开始时主机快选高亮(0=顶)。"""
    remap_rows: list[RemapColorRow] = field(default_factory=list)
    """多色: 去重后原色 -> 目标槽,供确认与副产物。"""
    air_cheb_sum: int = 0
    """各笔前空跑，切比雪夫步数之和(与固件格距一致)。"""
    quick_switch_count: int = 0
    """多色: DRAW_CMD_OP_QUICK 条数(与当前 emit 规则一致)。"""
    full_bind_count: int = 0
    """多色: DRAW_CMD_OP_FULL_BIND(0x03) 条数。"""
    sub_hat4_count: int = 0
    """多色: DRAW_CMD_OP_SUB_HAT4(0:04) 全色 4 向帽键条数(由编译期 BFS 展开)。"""
    stroke_order: str = STROKE_ORDER_MIN_AIR
    """多色: 笔划顺序策略。单色固定 min_air 。"""
    quick_switch_penalty: float = 0.0
    """penalized_greedy 时使用的 W；其他策略为 0。"""
    color_emit: str = COLOR_EMIT_INLINE
    """inline 或 batch_prefill。"""
    distinct_palette_index_count: int = 0
    """本段在「槽目标 index」上的去重种数。"""
    over_nine_distinct_indices: bool = False
    """去重后是否超过 9 种(需多轮批处理时 True)。"""
    emit_color_quick: bool = True
    """多色: True=可发 0:02; False=槽变只发 0:03+0:04(快选不写入矢量)。"""
    monochrome_preamble: bool = False
    """单色: 是否在 AIR/DRAG 前插槽 0 的 0:03+0:04 定色。"""


def compile_svg(
    svg_path: str | Path,
    *,
    grid_size: int = 256,
    home_row: int = 128,
    home_col: int = 128,
    samples_per_len: float = 2.0,
    palette_default_json: str | Path | None = None,
    monochrome_preamble: bool = False,
    monochrome_slot0_index: int | None = None,
) -> CompileResult:
    path = Path(svg_path)
    root = _load_svg_root(path)
    if not _strip_ns(root.tag).lower().endswith("svg"):
        raise ValueError("根元素须为 <svg>（带 xmlns 时仍为 svg）")

    size = _get_svg_size(root)
    if not size:
        minx, miny, w, h = 0.0, 0.0, 256.0, 256.0
    else:
        minx, miny, w, h, _, _ = size

    path_ds: list[str] = []
    for el in root.iter():
        if _strip_ns(el.tag) == "path" and el.get("d"):
            path_ds.append(el.get("d", "").strip())

    if not path_ds:
        raise ValueError("no <path d=...> in SVG")

    strokes = _collect_all_strokes(path_ds, minx, miny, w, h, grid_size, samples_per_len)
    if not strokes:
        raise ValueError("no drawable strokes after sampling")

    home = (home_row, home_col)
    ordered = _nearest_neighbor_order(home, strokes)
    cmds = _build_cmd_list(home, ordered)
    if monochrome_preamble:
        if not palette_default_json:
            raise ValueError("monochrome_preamble 须指定 palette_default_json(色表 JSON 路径)")
        pjson = Path(palette_default_json)
        if not pjson.is_file():
            raise FileNotFoundError(f"色表文件不存在: {pjson}")
        def9m = paldef.default_nine_indices_from_palette_path(pjson)
        pr, pc = paldef.index_row_col_arrays_84(pjson)
        tix = int(monochrome_slot0_index) if monochrome_slot0_index is not None else int(def9m[0] & 0xFF)
        if tix < 0 or tix > 83:
            raise ValueError("monochrome_slot0_index 须 0..83")
        sim0 = [int(def9m[sl] & 0xFF) for sl in range(9)]
        pre: list[DrawCmd] = []
        _append_full_bind_bfs(pre, tix, 0, sim0, pr, pc)
        cmds = pre + cmds
    raw = 3 * len(cmds)
    air, _qu = estimate_path_stats(
        home, ordered, 0, count_quick=False
    )
    nq, nfb, nsh = _count_quick_full_subhat_in_cmds(cmds)
    return CompileResult(
        cmds=cmds,
        strokes=len(strokes),
        home=home,
        bytes_size=raw,
        ordered_strokes=ordered,
        multicolor=False,
        air_cheb_sum=air,
        quick_switch_count=nq,
        full_bind_count=nfb,
        sub_hat4_count=nsh,
        default_nine_indices=None,
        stroke_order=STROKE_ORDER_MIN_AIR,
        quick_switch_penalty=0.0,
        color_emit=COLOR_EMIT_INLINE,
        distinct_palette_index_count=0,
        over_nine_distinct_indices=False,
        emit_color_quick=True,
        monochrome_preamble=bool(monochrome_preamble),
    )


def _build_remap_rows(
    path_rows: list[tuple[str, tuple[int, int, int]]],
    nine: np.ndarray,
) -> list[RemapColorRow]:
    from collections import Counter

    cnt: Counter[tuple[int, int, int]] = Counter()
    for _d, raw in path_rows:
        cnt[raw] += 1
    rows: list[RemapColorRow] = []
    for raw, n_paths in sorted(cnt.items(), key=lambda x: (-x[1], x[0])):
        rgb = np.array(raw, dtype=np.uint8)
        slot, d_e = colorutil.nearest_nine_targets_lab(rgb, nine)
        tgt = (int(nine[slot, 0]), int(nine[slot, 1]), int(nine[slot, 2]))
        rows.append(
            RemapColorRow(
                raw_hex=colorutil.rgb_to_hex(rgb),
                path_count=n_paths,
                slot=slot,
                target_rgb=tgt,
                delta_e=d_e,
            )
        )
    return rows


def _build_remap_rows_auto(
    path_rows: list[tuple[str, tuple[int, int, int]]],
    pal84: np.ndarray,
) -> list[RemapColorRow]:
    from collections import Counter

    if pal84.shape != (84, 3):
        raise ValueError("pal84 须为 84×3")
    cnt: Counter[tuple[int, int, int]] = Counter()
    for _d, raw in path_rows:
        cnt[raw] += 1
    rows: list[RemapColorRow] = []
    for raw, n_paths in sorted(cnt.items(), key=lambda x: (-x[1], x[0])):
        rgb = np.array(raw, dtype=np.uint8)
        j = int(colorutil.nearest_palette_index_lab(rgb, pal84))
        tgt = (int(pal84[j, 0]), int(pal84[j, 1]), int(pal84[j, 2]))
        pix_lab = colorutil.xyz_to_lab(colorutil.rgb255_to_xyz(rgb.reshape(1, 3)))
        pal_lab = colorutil.xyz_to_lab(
            colorutil.rgb255_to_xyz(pal84[j : j + 1, :].astype(np.uint8))
        )
        d2 = float(np.sum((pix_lab - pal_lab) ** 2))
        d_e = float(np.sqrt(d2))
        rows.append(
            RemapColorRow(
                raw_hex=colorutil.rgb_to_hex(rgb),
                path_count=n_paths,
                slot=j,
                target_rgb=tgt,
                delta_e=d_e,
                nearest_palette_index=j,
            )
        )
    return rows


def compile_svg_multicolor(
    svg_path: str | Path,
    nine_target_rgb: np.ndarray,
    *,
    palette_index_per_slot: list[int] | None = None,
    palette_default_json: str | Path | None = None,
    start_quick_index: int = 0,
    grid_size: int = 256,
    home_row: int = 128,
    home_col: int = 128,
    samples_per_len: float = 2.0,
    stroke_order: StrokeOrder | str = STROKE_ORDER_MIN_AIR,
    quick_switch_penalty: float = 0.0,
    color_emit: ColorEmit | str = COLOR_EMIT_INLINE,
    emit_color_quick: bool = True,
) -> CompileResult:
    path = Path(svg_path)
    root = _load_svg_root(path)
    if not _strip_ns(root.tag).lower().endswith("svg"):
        raise ValueError("根元素须为 <svg>（带 xmlns 时仍为 svg）")

    nine = np.asarray(nine_target_rgb, dtype=np.uint8)
    if nine.shape != (9, 3):
        raise ValueError("nine_target_rgb 须为 9×3 的 sRGB(0..255)")

    if palette_index_per_slot is not None and len(palette_index_per_slot) != 9:
        raise ValueError("palette_index_per_slot 须为 9 个 0..83 的索引")
    for x in (palette_index_per_slot or []):
        if int(x) < 0 or int(x) > 83:
            raise ValueError("palette index 须为 0..83")

    ce = str(color_emit)
    if ce not in (COLOR_EMIT_INLINE, COLOR_EMIT_BATCH_PREFILL):
        raise ValueError(
            f"color_emit 须为 {COLOR_EMIT_INLINE!r} 或 {COLOR_EMIT_BATCH_PREFILL!r}, 得 {ce!r}"
        )

    pjson = Path(palette_default_json) if palette_default_json else DEFAULT_PALETTE_JSON
    if not pjson.is_file():
        raise FileNotFoundError(
            f"多色全色/默认对比需要 palette JSON: {pjson} (可用 palette_default_json= 指定)"
        )
    def9 = paldef.default_nine_indices_from_palette_path(pjson)
    pal_r, pal_c = paldef.index_row_col_arrays_84(pjson)
    pidx: list[int] = (
        [int(x) for x in palette_index_per_slot] if palette_index_per_slot is not None else list(def9)
    )

    size = _get_svg_size(root)
    if not size:
        minx, miny, w, h = 0.0, 0.0, 256.0, 256.0
    else:
        minx, miny, w, h, _, _ = size

    path_rows: list[tuple[str, tuple[int, int, int]]] = []
    for el in root.iter():
        if _strip_ns(el.tag) != "path" or not el.get("d"):
            continue
        d = el.get("d", "").strip()
        if not d:
            continue
        raw = svg_color.path_effective_line_rgb(el, root)
        if raw is None:
            raw = (0, 0, 0)
        path_rows.append((d, (int(raw[0]), int(raw[1]), int(raw[2]))))

    if not path_rows:
        raise ValueError("no <path d=...> in SVG")

    strokes: list[Stroke] = []
    for d, raw in path_rows:
        rgb = np.array(raw, dtype=np.uint8)
        slot, _ = colorutil.nearest_nine_targets_lab(rgb, nine)
        strokes.extend(
            _collect_strokes(
                d, minx, miny, w, h, grid_size, samples_per_len, slot=slot
            )
        )

    if not strokes:
        raise ValueError("no drawable strokes after sampling")

    remap_rows = _build_remap_rows(path_rows, nine)
    home = (home_row, home_col)
    sq = int(start_quick_index) & 0xFF
    so = str(stroke_order)
    if so not in _STROKE_ORDERS:
        raise ValueError(
            f"stroke_order 须为 {sorted(_STROKE_ORDERS)} 之一, 得 {so!r}"
        )
    w = float(quick_switch_penalty)
    if w < 0.0:
        raise ValueError("quick_switch_penalty 须 >= 0")
    ordered = order_strokes_multicolor(
        home,
        strokes,
        so,
        quick_switch_penalty=w,
        start_quick_index=sq,
    )
    used_slots = {int(s.slot) for s in ordered}
    pidx_in_use: set[int] = {pidx[sl] for sl in used_slots if 0 <= sl < 9}
    distinct_n = len(pidx_in_use)
    over9 = distinct_n > 9

    cmds = _build_cmd_list_multicolor(
        home,
        ordered,
        start_quick_index=sq,
        insert_quick=True,
        palette_index_by_slot=pidx,
        default_nine=def9,
        color_emit=ce,
        pal_row=pal_r,
        pal_col=pal_c,
        emit_color_quick=emit_color_quick,
    )
    raw_b = 3 * len(cmds)
    air, _ = estimate_path_stats(
        home, ordered, sq, count_quick=True
    )
    nq, nfb, nsh = _count_quick_full_subhat_in_cmds(cmds)
    return CompileResult(
        cmds=cmds,
        strokes=len(strokes),
        home=home,
        bytes_size=raw_b,
        ordered_strokes=ordered,
        multicolor=True,
        nine_target_rgb=[(int(nine[i, 0]), int(nine[i, 1]), int(nine[i, 2])) for i in range(9)],
        palette_index_per_slot=(list(palette_index_per_slot) if palette_index_per_slot else list(def9)),
        default_nine_indices=list(def9),
        start_quick_index=sq,
        remap_rows=remap_rows,
        air_cheb_sum=air,
        quick_switch_count=nq,
        full_bind_count=nfb,
        sub_hat4_count=nsh,
        stroke_order=so,
        quick_switch_penalty=(w if so == STROKE_ORDER_PENALIZED else 0.0),
        color_emit=ce,
        distinct_palette_index_count=distinct_n,
        over_nine_distinct_indices=over9,
        emit_color_quick=emit_color_quick,
        monochrome_preamble=False,
    )


def compile_svg_multicolor_auto84(
    svg_path: str | Path,
    *,
    palette_default_json: str | Path | None = None,
    start_quick_index: int = 0,
    grid_size: int = 256,
    home_row: int = 128,
    home_col: int = 128,
    samples_per_len: float = 2.0,
    stroke_order: StrokeOrder | str = STROKE_ORDER_MIN_AIR,
    quick_switch_penalty: float = 0.0,
    color_emit: ColorEmit | str = COLOR_EMIT_INLINE,
    emit_color_quick: bool = True,
) -> CompileResult:
    """
    每条 path 在 84 色里取 Lab 最近下标; 笔划带 ink_index。九槽 LRU 分配物理槽，下位机按序全色/快选换绑，>9 色会复用槽继续画。
    """
    from prepare_texture import load_palette

    path = Path(svg_path)
    root = _load_svg_root(path)
    if not _strip_ns(root.tag).lower().endswith("svg"):
        raise ValueError("根元素须为 <svg>（带 xmlns 时仍为 svg）")

    pjson = Path(palette_default_json) if palette_default_json else DEFAULT_PALETTE_JSON
    if not pjson.is_file():
        raise FileNotFoundError(f"需要 palette JSON: {pjson}")

    pal84, _meta = load_palette(str(pjson))
    def9 = paldef.default_nine_indices_from_palette_path(pjson)
    pal_r, pal_c = paldef.index_row_col_arrays_84(pjson)

    ce = str(color_emit)
    if ce == COLOR_EMIT_BATCH_PREFILL:
        ce = COLOR_EMIT_INLINE

    size = _get_svg_size(root)
    if not size:
        minx, miny, w, h = 0.0, 0.0, 256.0, 256.0
    else:
        minx, miny, w, h, _, _ = size

    path_rows: list[tuple[str, tuple[int, int, int]]] = []
    for el in root.iter():
        if _strip_ns(el.tag) != "path" or not el.get("d"):
            continue
        d = el.get("d", "").strip()
        if not d:
            continue
        raw = svg_color.path_effective_line_rgb(el, root)
        if raw is None:
            raw = (0, 0, 0)
        path_rows.append((d, (int(raw[0]), int(raw[1]), int(raw[2]))))

    if not path_rows:
        raise ValueError("no <path d=...> in SVG")

    strokes: list[Stroke] = []
    for d, raw in path_rows:
        rgb = np.array(raw, dtype=np.uint8)
        ink = int(colorutil.nearest_palette_index_lab(rgb, pal84)) & 0xFF
        strokes.extend(
            _collect_strokes(
                d,
                minx,
                miny,
                w,
                h,
                grid_size,
                samples_per_len,
                slot=0,
                ink_index=ink,
            )
        )

    if not strokes:
        raise ValueError("no drawable strokes after sampling")

    remap_rows = _build_remap_rows_auto(path_rows, pal84)
    home = (home_row, home_col)
    sq = int(start_quick_index) & 0xFF
    so = str(stroke_order)
    if so not in _STROKE_ORDERS:
        raise ValueError(
            f"stroke_order 须为 {sorted(_STROKE_ORDERS)} 之一, 得 {so!r}"
        )
    wpen = float(quick_switch_penalty)
    if wpen < 0.0:
        raise ValueError("quick_switch_penalty 须 >= 0")
    ordered = order_strokes_multicolor(
        home,
        strokes,
        so,
        quick_switch_penalty=wpen,
        start_quick_index=sq,
    )
    _assign_slots_lru(ordered, def9)
    di = {int(s.ink_index) & 0xFF for s in ordered if s.ink_index is not None}
    distinct_n = len(di)
    over9 = distinct_n > 9

    cmds = _build_cmd_list_multicolor_auto(
        home,
        ordered,
        def9,
        pal_r,
        pal_c,
        start_quick_index=sq,
        emit_color_quick=emit_color_quick,
    )
    raw_b = 3 * len(cmds)
    air, _ = estimate_path_stats(home, ordered, sq, count_quick=True)
    nq, nfb, nsh = _count_quick_full_subhat_in_cmds(cmds)
    nine_show = [
        (int(pal84[def9[i], 0]), int(pal84[def9[i], 1]), int(pal84[def9[i], 2]))
        for i in range(9)
    ]
    return CompileResult(
        cmds=cmds,
        strokes=len(strokes),
        home=home,
        bytes_size=raw_b,
        ordered_strokes=ordered,
        multicolor=True,
        auto_nearest_84=True,
        nine_target_rgb=nine_show,
        palette_index_per_slot=list(def9),
        default_nine_indices=list(def9),
        start_quick_index=sq,
        remap_rows=remap_rows,
        air_cheb_sum=air,
        quick_switch_count=nq,
        full_bind_count=nfb,
        sub_hat4_count=nsh,
        stroke_order=so,
        quick_switch_penalty=(wpen if so == STROKE_ORDER_PENALIZED else 0.0),
        color_emit=ce,
        distinct_palette_index_count=distinct_n,
        over_nine_distinct_indices=over9,
        emit_color_quick=emit_color_quick,
        monochrome_preamble=False,
    )


# 多色栅格预览用：9 个易区分的 sRGB。游戏九目标色在 Lab 上可能彼此接近，屏上难辨，故与实色可分离。
PREVIEW_MULTICOLOR_SLOT_RGB: tuple[tuple[int, int, int], ...] = (
    (255, 90, 90),
    (255, 195, 75),
    (235, 235, 85),
    (100, 220, 120),
    (85, 200, 225),
    (110, 145, 255),
    (210, 115, 255),
    (255, 100, 180),
    (215, 215, 255),
)


def render_strokes_preview(
    ordered: list[Stroke],
    *,
    scale: int = 2,
    grid: int = 256,
    max_preview_points: int = 0,
    slot_rgb9: list[tuple[int, int, int]] | None = None,
    preview_distinct_multicolor: bool = False,
    preview_background_rgb: tuple[int, int, int] | None = None,
    palette_full_84: np.ndarray | None = None,
):
    """
    仅用于 GUI 预览。不用 ImageDraw.line：在部分 Windows + Pillow 下宽折线会整图不画。
    在 1:1 逻辑格网上 putpixel，再 NEAREST 放大，与实机 256 格一致。max_preview_points>0
    且步数极长时，按索引下采样以减轻大 SVG 的 CPU 负担，不影响固件。
    slot_rgb9: 多色时 9 个 sRGB, 按 slot 0..8 上色; None 为单色高亮 (245,248,255)。
    preview_distinct_multicolor: True 时按槽 0..8 用 PREVIEW_MULTICOLOR_SLOT_RGB 上色，便于在深色底上区分
    不同槽；与九快选上绑定的实色可无关。为 False 且 slot_rgb9 非空时仍用实色作为预览色。
    preview_background_rgb: 为 None 时用默认深底 (22,24,32)；可传入标准灰等以便对照实色（如 192,192,192）。
    palette_full_84: 多色 84 自动且笔划带 ink_index 时，用其取每笔下标 RGB，预览与「映射实色」一致；
    若同时 preview_distinct_multicolor=True，则优先按槽位伪色上色，不读 palette_full_84。
    """
    from PIL import Image

    w, h = grid, grid
    bg = preview_background_rgb if preview_background_rgb is not None else (22, 24, 32)
    fg = (245, 248, 255)
    im = Image.new("RGB", (w, h), bg)
    pix = im.load()
    p84: np.ndarray | None = None
    if palette_full_84 is not None and palette_full_84.size:
        p84 = np.asarray(palette_full_84, dtype=np.uint8)
    for s in ordered:
        c, r = s.start[1], s.start[0]
        if preview_distinct_multicolor and 0 <= s.slot < len(PREVIEW_MULTICOLOR_SLOT_RGB):
            this = PREVIEW_MULTICOLOR_SLOT_RGB[s.slot]
        elif (
            p84 is not None
            and p84.shape[0] >= 84
            and s.ink_index is not None
        ):
            ii = int(s.ink_index) & 0xFF
            this = (int(p84[ii, 0]), int(p84[ii, 1]), int(p84[ii, 2]))
        elif slot_rgb9 and 0 <= s.slot < len(slot_rgb9):
            this = slot_rgb9[s.slot]
        else:
            this = fg
        cells: list[tuple[int, int]] = [(c, r)]
        for hat, n in s.runs:
            for _ in range(n):
                dr, dc = HAT_TO_DR_DC[hat]
                r += dr
                c += dc
                cells.append((c, r))

        if max_preview_points and len(cells) > max_preview_points:
            n = len(cells)
            cap = min(int(max_preview_points), n)
            if cap < 2:
                visit = {cells[0]}
            else:
                visit = set()
                for k in range(cap):
                    i = int(round(k * (n - 1) / max(1, cap - 1)))
                    if 0 <= i < n:
                        visit.add(cells[i])
        else:
            visit = set(cells)

        for cc, rr in visit:
            if 0 <= cc < w and 0 <= rr < h:
                pix[cc, rr] = this

    if scale != 1:
        im = im.resize((w * scale, h * scale), Image.Resampling.NEAREST)
    return im


def write_draw_vector_header(
    result: CompileResult,
    out_path: str | Path,
    *,
    source_note: str = "",
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "/* Auto-generated — draw_vector_data.h for paint_vector_flash */",
        f"/* Generated: {now} */",
    ]
    if source_note:
        lines.append(f"/* Source: {source_note} */")
    lines.extend(
        [
            "#ifndef DRAW_VECTOR_DATA_H",
            "#define DRAW_VECTOR_DATA_H",
            "",
            "#include <stdint.h>",
            "#include <avr/pgmspace.h>",
            "",
            "#define DRAW_CMD_OP_AIR  0x00u",
            "#define DRAW_CMD_OP_DRAG 0x01u",
            "#define DRAW_CMD_OP_QUICK 0x02u  /* 快选槽: arg1=0..8 顶=0 */",
            "#define DRAW_CMD_OP_FULL_BIND 0x03u  /* arg1=palette index 0..83, arg2=槽 0..8; 后随 N 条 0:04 */",
            "#define DRAW_CMD_OP_SUB_HAT4 0x04u  /* 全色 4 向: arg1=0U 1R 2D 3L, arg2=0; 仅作 0:03 子序列 */",
            f"#define DRAW_QUICK_INDEX_INIT {int(result.start_quick_index) & 0xFF}u",
            f"#define HOME_ROW0 {result.home[0]}u",
            f"#define HOME_COL0 {result.home[1]}u",
            f"#define DRAW_CMD_COUNT {len(result.cmds)}u",
            f"#define DRAW_CMD_BYTES (DRAW_CMD_COUNT * 3u)",
            "",
            "typedef struct {",
            "  uint8_t op;",
            "  uint8_t arg1;",
            "  uint8_t arg2;",
            "} DrawCmd;",
            "",
        ]
    )

    n = len(result.cmds)
    lines.append(f"static const DrawCmd draw_cmds[{n}] PROGMEM = {{")

    for c in result.cmds:
        lines.append(f"  {{ 0x{c.op:02X}, 0x{c.arg1:02X}, 0x{c.arg2:02X} }},")
    lines.append("};")
    lines.append("")
    lines.append("#endif /* DRAW_VECTOR_DATA_H */")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def write_remap_json(result: CompileResult, out_path: str | Path) -> Path:
    if not result.multicolor:
        raise ValueError("write_remap_json 仅用于多色 CompileResult")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {
        "remap": [asdict(r) for r in result.remap_rows],
        "nine_target_rgb": [list(x) for x in result.nine_target_rgb],
        "palette_index_per_slot": result.palette_index_per_slot,
        "default_nine_indices": result.default_nine_indices,
        "start_quick_index": result.start_quick_index,
        "color_emit": result.color_emit,
        "full_bind_count": result.full_bind_count,
        "quick_switch_count": result.quick_switch_count,
        "distinct_palette_index_count": result.distinct_palette_index_count,
        "over_nine_distinct_indices": result.over_nine_distinct_indices,
        "emit_color_quick": result.emit_color_quick,
    }
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return out_path


def write_vector_setup_markdown(
    result: CompileResult,
    out_path: str | Path,
    palette_json_path: str | Path,
) -> Path:
    """
    生成快选九格与 palette 行/列说明。槽 0=设计稿 c9(顶)…8=c1(底)。
    应在「多色 + emit_color_quick(快选 0:02)」时由 GUI/CLI 调用; 全色发码(无 0:02) 不生成此文件。
    须提供 palette_index_per_slot(9) 以填列/行,否则列行为「—」。
    """
    out_path = Path(out_path)
    p = Path(palette_json_path)
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    colors = sorted(data["colors"], key=lambda c: int(c["index"]))
    by_idx = {int(c["index"]): c for c in colors}

    if result.auto_nearest_84:
        head = [
            "# 快选九格与游戏内填色 (MVP)",
            "",
            "> **本矢量为「84 色自动最近」模式**：`draw_vector_data` 中已按序发全色换绑/快选，**一般无需**按表手填快选；下表为设备**默认九格**（上电态）供对照。",
            "",
            "（自动模式通常可忽略）若你仍需手动对快选：",
        ]
    else:
        head = [
            "# 快选九格与游戏内填色 (MVP)",
            "",
            "请按**自上而下**在游戏快选里绑定下列颜色。**槽 0=最上格** (设计稿常标为 `c9`), **槽 8=最下格** (`c1`)。",
        ]
    lines: list[str] = head + [
        "",
        "| 槽 (设计位) | 色板 列(0-11) | 行(0-6) | 索引(0-83) | 目标 sRGB(工具) |",
        "|:---:|:---:|:---:|:---:|:---|",
    ]
    pidxs = result.palette_index_per_slot
    n9 = result.nine_target_rgb
    for slot in range(9):
        label = f"c{9 - slot}"
        rgb = n9[slot] if slot < len(n9) else (0, 0, 0)
        pidx: int | None = pidxs[slot] if pidxs and slot < len(pidxs) else None
        if pidx is not None and pidx in by_idx:
            c = by_idx[pidx]
            col, row = (int(c["col"]), int(c["row"]))
        else:
            col, row = "—", "—"
        hx = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        id_cell = f"{pidx}" if pidx is not None else "—"
        lines.append(
            f"| {slot} (`{label}`) | {col} | {row} | {id_cell} | {hx} |"
        )
    lines.append("")
    lines.append(
        f"自动化起点的快选高亮需与头文件 `DRAW_QUICK_INDEX_INIT` (= **{result.start_quick_index}**) 所选手顺一致。"
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[-1]
    return tag


def _read_svg_text(svg_path: Path) -> str:
    """Illustrator/Windows: UTF-8 BOM、无 BOM、或中文路径下用系统编码保存的 SVG 均可尽量解码。"""
    raw = svg_path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text: str | None = None
    for enc in ("utf-8", "cp936", "gbk", "utf-8-sig", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")
    text = text.lstrip().lstrip("\ufeff")
    if not text.startswith("<"):
        i = text.find("<?xml")
        if i >= 0:
            text = text[i:]
    if not text.startswith("<"):
        i = text.find("<svg")
        if i >= 0:
            text = text[i:]
    return text


def _load_svg_root(svg_path: Path) -> ET.Element:
    text = _read_svg_text(svg_path)
    try:
        return ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(
            f"无法解析为 XML（请用 UTF-8 另存，或检查文件开头是否有乱码/多余字符）: {e}"
        ) from e


def _nine_rgb_from_indices(pal_path: Path, indices: list[int]) -> np.ndarray:
    if len(indices) != 9:
        raise ValueError("need 9 palette indices 0..83")
    from prepare_texture import load_palette

    rgb, _ = load_palette(str(pal_path))
    if rgb.shape[0] != 84:
        raise ValueError("palette 须为 84 色")
    out = np.zeros((9, 3), dtype=np.uint8)
    for i, ix in enumerate(indices):
        ii = int(ix)
        if ii < 0 or ii > 83:
            raise ValueError("palette index 须为 0..83")
        out[i, :] = rgb[ii]
    return out


def _main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__ + "  多色: --multicolor 需 --palette-json 与 9 个 --palette-index。"
    )
    ap.add_argument("input", type=Path, help="input.svg")
    ap.add_argument("-o", "--output", type=Path, required=True, help="output draw_vector_data.h")
    ap.add_argument("--summary", action="store_true", help="print cmd count and bytes")
    ap.add_argument(
        "--samples",
        type=float,
        default=2.0,
        help="samples per unit of path length (default 2)",
    )
    ap.add_argument(
        "--multicolor",
        action="store_true",
        help="多色(须 --palette-json；与 --multicolor-auto-84 二选一与九格法)",
    )
    ap.add_argument(
        "--multicolor-auto-84",
        action="store_true",
        help="多色: 每 path 在 84 色里 Lab 最近 + 九槽 LRU 全色/快选(无需 --palette-indices-9)",
    )
    ap.add_argument(
        "--palette-json",
        type=Path,
        help="如 assets/generated/palette_default.json, 多色时必填",
    )
    ap.add_argument(
        "--palette-indices-9",
        type=str,
        help="9 个 0-83, 逗号分隔, 与快选槽0..8一一对应 (槽0=顶)",
    )
    ap.add_argument(
        "--remap-json",
        type=Path,
        help="多色: 重映射报告路径",
    )
    ap.add_argument(
        "--setup-md",
        type=Path,
        default=None,
        help="仅多色且为快选发码模式(无 --no-color-quick) 时: 填格说明 .md; 省缺=与 -o 同目录 <stem>_vector_setup.md",
    )
    ap.add_argument(
        "--no-color-quick",
        action="store_true",
        help="多色: 不生成 0:02(快选由机上手动), 槽变只发 0:03+0:04 全色序列",
    )
    ap.add_argument(
        "--monochrome-preamble",
        action="store_true",
        help="单色: 在空跑/拖线前插槽0 的 0:03+0:04 定色(须 --palette-default-json)",
    )
    ap.add_argument(
        "--monochrome-slot0-index",
        type=int,
        default=None,
        help="单色: 与 --monochrome-preamble 同用, 片头绑定的 palette 下标 0..83; 省缺=JSON 九格[槽0] 默认下标",
    )
    ap.add_argument(
        "--start-quick",
        type=int,
        default=0,
        help="与主机快选起点的槽 0..8, 仅多色, 写 DRAW_QUICK_INDEX_INIT",
    )
    ap.add_argument(
        "--stroke-order",
        default=STROKE_ORDER_MIN_AIR,
        choices=sorted(_STROKE_ORDERS),
        help="多色: 笔划顺序: min_air=全局少空跑, by_slot=按槽0..8分层, penalized_greedy=空跑+换色惩罚W",
    )
    ap.add_argument(
        "--quick-penalty",
        type=float,
        default=0.0,
        help="多色且 penalized_greedy: 换槽等效格数(>=0; 0 等价于 min_air 贪心)",
    )
    ap.add_argument(
        "--color-emit",
        default=COLOR_EMIT_INLINE,
        choices=(COLOR_EMIT_INLINE, COLOR_EMIT_BATCH_PREFILL),
        help="多色: 换色发码 inline(每笔) 或 batch_prefill(段首铺 9 槽后仅 QUICK)",
    )
    ap.add_argument(
        "--palette-default-json",
        type=Path,
        default=None,
        help="多色: 与九格 default index 同源的 JSON; 省缺则与 --palette-json 同文件",
    )
    args = ap.parse_args()

    if args.multicolor and args.multicolor_auto_84:
        print("错误: 请只选其一: --multicolor(手选九格) 或 --multicolor-auto-84", file=sys.stderr)
        return 2
    if args.multicolor or args.multicolor_auto_84:
        if not args.palette_json or not Path(args.palette_json).is_file():
            print("错误: 多色需要有效的 --palette-json", file=sys.stderr)
            return 2
        qp = float(args.quick_penalty)
        if qp < 0.0:
            print("错误: --quick-penalty 须 >= 0", file=sys.stderr)
            return 2
        pdef = args.palette_default_json or args.palette_json
        if args.multicolor_auto_84:
            res = compile_svg_multicolor_auto84(
                args.input,
                palette_default_json=Path(pdef) if pdef else None,
                start_quick_index=int(args.start_quick) & 0xFF,
                samples_per_len=args.samples,
                stroke_order=str(args.stroke_order),
                quick_switch_penalty=qp,
                color_emit=str(args.color_emit),
                emit_color_quick=not bool(args.no_color_quick),
            )
        else:
            if not args.palette_indices_9:
                print("错误: 手选九格多色须指定 --palette-indices-9", file=sys.stderr)
                return 2
            inds = [int(x.strip()) for x in args.palette_indices_9.split(",") if x.strip()]
            if len(inds) != 9:
                print("错误: --palette-indices-9 须 9 个下标", file=sys.stderr)
                return 2
            nine = _nine_rgb_from_indices(args.palette_json, inds)
            res = compile_svg_multicolor(
                args.input,
                nine,
                palette_index_per_slot=inds,
                palette_default_json=Path(pdef) if pdef else None,
                start_quick_index=int(args.start_quick) & 0xFF,
                samples_per_len=args.samples,
                stroke_order=str(args.stroke_order),
                quick_switch_penalty=qp,
                color_emit=str(args.color_emit),
                emit_color_quick=not bool(args.no_color_quick),
            )
    else:
        mpre = bool(args.monochrome_preamble)
        pdef1 = args.palette_default_json
        if mpre and not pdef1:
            print("错误: --monochrome-preamble 需要 --palette-default-json", file=sys.stderr)
            return 2
        res = compile_svg(
            args.input,
            samples_per_len=args.samples,
            palette_default_json=Path(pdef1) if pdef1 else None,
            monochrome_preamble=mpre,
            monochrome_slot0_index=args.monochrome_slot0_index,
        )
    write_draw_vector_header(res, args.output, source_note=str(args.input))
    if (args.multicolor or args.multicolor_auto_84) and args.remap_json:
        write_remap_json(res, args.remap_json)
    print(f"Wrote {args.output} ({len(res.cmds)} commands)")
    if (args.multicolor or args.multicolor_auto_84) and res.emit_color_quick:
        pjson = args.palette_default_json or args.palette_json
        if pjson and Path(pjson).is_file():
            pout = Path(args.output)
            md_path = args.setup_md if args.setup_md else pout.parent / f"{pout.stem}_vector_setup.md"
            write_vector_setup_markdown(res, md_path, pjson)
            print(f"Wrote {md_path} (快选发码, 九格说明)")
    if (args.multicolor or args.multicolor_auto_84) and res.remap_rows:
        print(f"  重映射: {len(res.remap_rows)} 种原色")
    if args.multicolor or args.multicolor_auto_84:
        ex = f"  空跑(切比): {res.air_cheb_sum}  QUICK: {res.quick_switch_count}  FULL_BIND: {res.full_bind_count}  SUB_HAT4: {res.sub_hat4_count}  快选发码: {res.emit_color_quick}  顺序: {res.stroke_order}"
        if res.over_nine_distinct_indices and not res.auto_nearest_84:
            ex += f"  [去重{res.distinct_palette_index_count}色>9, 单段铺色不覆盖; 多批需后续策略]"
        if res.over_nine_distinct_indices and res.auto_nearest_84:
            ex += f"  [去重{res.distinct_palette_index_count}色>9, 九槽循环换绑]"
        print(ex)
    if args.summary:
        s_extra = f"  air_cheb={res.air_cheb_sum}  quick={res.quick_switch_count}  full_bind={res.full_bind_count}  sub_hat4={res.sub_hat4_count}"
        if res.multicolor:
            s_extra += f"  order={res.stroke_order}  W={res.quick_switch_penalty!r}  emit={res.color_emit!r}  color_quick={res.emit_color_quick!r}"
        print(
            f"  strokes={res.strokes}  bytes≈{res.bytes_size} (3*cmds)  multi={res.multicolor}{s_extra}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
