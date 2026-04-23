#!/usr/bin/env python3
"""Generate 256×256 probe PNG + indices.bin (single or few pixels) for canvas home-cell testing."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from prepare_texture import export_bundle, load_palette


def build_rgba_from_draws(
    pal_rgb: np.ndarray,
    size: int,
    draws: list[tuple[int, int, int]],
) -> np.ndarray:
    rgba = np.zeros((size, size, 4), dtype=np.uint8)
    for row, col, pidx in draws:
        rgba[row, col, :3] = pal_rgb[pidx]
        rgba[row, col, 3] = 255
    return rgba


def make_flat_indices(
    size: int,
    sentinel: int,
    draws: list[tuple[int, int, int]],
) -> np.ndarray:
    """draws: list of (row, col, palette_index)."""
    flat = np.full(size * size, sentinel, dtype=np.uint8)
    for row, col, pidx in draws:
        if not (0 <= row < size and 0 <= col < size):
            raise ValueError(f"row,col out of range: ({row}, {col})")
        if not (0 <= pidx < 84):
            raise ValueError(f"palette index must be 0..83, got {pidx}")
        flat[row * size + col] = pidx
    return flat


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate home/center probe textures (256×256).")
    ap.add_argument("--palette-json", required=True, help="palette_default.json")
    ap.add_argument("--out-prefix", required=True, help="Output path prefix (no extension)")
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--sentinel", type=int, default=255)
    ap.add_argument("--palette-index", type=int, default=1, help="Palette index 0..83 for drawn pixels")
    ap.add_argument(
        "--pixel",
        action="append",
        default=[],
        metavar="ROW,COL",
        help="Draw one pixel at ROW,COL (repeatable). Default: single 127,127 if none passed.",
    )
    args = ap.parse_args()

    size = int(args.size)
    if size != 256:
        print("Warning: non-256 size; game grid is 256×256.", file=sys.stderr)

    draws: list[tuple[int, int, int]] = []
    if args.pixel:
        for s in args.pixel:
            parts = s.replace(" ", "").split(",")
            if len(parts) != 2:
                print(f"Bad --pixel {s!r}, use ROW,COL", file=sys.stderr)
                return 2
            r, c = int(parts[0]), int(parts[1])
            draws.append((r, c, args.palette_index))
    else:
        draws.append((127, 127, args.palette_index))

    if args.sentinel <= 83:
        print("--sentinel must not collide with palette indices 0..83", file=sys.stderr)
        return 2

    pal_rgb, pal_meta = load_palette(args.palette_json)
    flat = make_flat_indices(size, args.sentinel, draws)
    rgba = build_rgba_from_draws(pal_rgb, size, draws)

    prefix = args.out_prefix
    out_png = f"{prefix}.png"
    out_bin = f"{prefix}_indices.bin"
    out_meta = f"{prefix}_meta.json"

    export_bundle(
        rgba,
        flat,
        out_png=out_png,
        out_bin=out_bin,
        out_meta=out_meta,
        size=size,
        alpha_threshold=128,
        index_sentinel=args.sentinel,
        rgb_name="nearest",
        alpha_name="nearest",
        source_file=f"synthetic_probe:{draws}",
        palette_path=os.path.abspath(args.palette_json),
        pal_meta=pal_meta,
    )

    side = {
        "kind": "home_grid_probe",
        "draws_logical_rc": [{"row": r, "col": c, "palette_index": p} for r, c, p in draws],
        "index_order": "row_major_i_eq_y_mul_w_plus_x",
        "note": "Use docs/canvas_home_test.md for in-game procedure.",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    with open(f"{prefix}_sidecar.json", "w", encoding="utf-8") as f:
        json.dump(side, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Wrote {out_png}, {out_bin}, {out_meta}, {prefix}_sidecar.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
