#!/usr/bin/env python3
"""
Compile monochrome line-art SVG to PROGMEM draw_vector_data.h (DrawCmd opcodes).
Uses 8-connected grid, run-length, nearest-neighbor stroke order (Chebyshev).
"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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


@dataclass
class DrawCmd:
    op: int
    arg1: int
    arg2: int


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
        strokes.append(Stroke(start=(r0, c0), end=(r1, c1), runs=runs))
    return strokes


def _collect_all_strokes(
    path_d_list: list[str],
    minx: float,
    miny: float,
    w: float,
    h: float,
    gsize: int,
    samples: float,
) -> list[Stroke]:
    all_s: list[Stroke] = []
    for d in path_d_list:
        all_s.extend(_collect_strokes(d, minx, miny, w, h, gsize, samples))
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


def _build_cmd_list(
    home: tuple[int, int], ordered: list[Stroke]
) -> list[DrawCmd]:
    """home (row, col) per firmware convention: arg1=col, arg2=row for AIR."""
    cmds: list[DrawCmd] = []
    g_row, g_col = home[0], home[1]
    for s in ordered:
        tr, tc = s.start[0], s.start[1]
        if (g_row, g_col) != (tr, tc):
            cmds.append(DrawCmd(0, tc, tr))  # AIR: col, row
            g_row, g_col = tr, tc
        if not s.runs:
            cmds.append(DrawCmd(1, 0, 0))  # single stamp, hat arg ignored
        else:
            for hat, n in s.runs:
                cmds.append(DrawCmd(1, hat, n))
                # update g: n steps in hat
                for _ in range(n):
                    dr, dc = HAT_TO_DR_DC[hat]
                    g_row += dr
                    g_col += dc
    return cmds


# --- Public API for GUI / CLI ---


@dataclass
class CompileResult:
    cmds: list[DrawCmd]
    strokes: int
    home: tuple[int, int]
    bytes_size: int
    ordered_strokes: list[Stroke] = field(default_factory=list)


def compile_svg(
    svg_path: str | Path,
    *,
    grid_size: int = 256,
    home_row: int = 128,
    home_col: int = 128,
    samples_per_len: float = 2.0,
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
    raw = 3 * len(cmds)
    return CompileResult(
        cmds=cmds,
        strokes=len(strokes),
        home=home,
        bytes_size=raw,
        ordered_strokes=ordered,
    )


def render_strokes_preview(
    ordered: list[Stroke],
    *,
    scale: int = 2,
    grid: int = 256,
    max_preview_points: int = 0,
):
    """
    仅用于 GUI 预览。不用 ImageDraw.line：在部分 Windows + Pillow 下宽折线会整图不画。
    在 1:1 逻辑格网上 putpixel，再 NEAREST 放大，与实机 256 格一致。max_preview_points>0
    且步数极长时，按索引下采样以减轻大 SVG 的 CPU 负担，不影响固件。
    """
    from PIL import Image

    w, h = grid, grid
    bg = (22, 24, 32)
    fg = (245, 248, 255)
    im = Image.new("RGB", (w, h), bg)
    pix = im.load()
    for s in ordered:
        c, r = s.start[1], s.start[0]
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
                pix[cc, rr] = fg

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


def _main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="input.svg")
    ap.add_argument("-o", "--output", type=Path, required=True, help="output draw_vector_data.h")
    ap.add_argument("--summary", action="store_true", help="print cmd count and bytes")
    ap.add_argument(
        "--samples",
        type=float,
        default=2.0,
        help="samples per unit of path length (default 2)",
    )
    args = ap.parse_args()
    res = compile_svg(
        args.input,
        samples_per_len=args.samples,
    )
    write_draw_vector_header(res, args.output, source_note=str(args.input))
    print(f"Wrote {args.output} ({len(res.cmds)} commands)")
    if args.summary:
        print(
            f"  strokes={res.strokes}  bytes≈{res.bytes_size} (3*cmds)",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
