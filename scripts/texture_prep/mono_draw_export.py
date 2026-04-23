#!/usr/bin/env python3
"""Export 256×256 (or N×N) draw mask as Arduino PROGMEM header for monochrome paint firmware."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

_LEONARDO_MASK_BYTES = 8192
_FLASH_WARN_PIXELS = 14000


def flat_idx_to_packed_mask(flat_idx: np.ndarray, sentinel: int) -> tuple[np.ndarray, int, int]:
    """
    Return (packed_uint8, side, drawable_pixel_count).
    packed has length ceil(side*side/8); bit order big-endian within each byte, linear index 0 = row0 col0.
    """
    flat_idx = np.asarray(flat_idx, dtype=np.uint8).ravel()
    n = int(flat_idx.size)
    side = int(np.sqrt(n))
    if side * side != n:
        raise ValueError(f"flat index length must be a square (got {n})")
    if sentinel < 0 or sentinel > 255:
        raise ValueError("sentinel must be 0–255")
    draw = (flat_idx != np.uint8(sentinel)).astype(np.uint8)
    pixel_count = int(draw.sum())
    packed = np.packbits(draw, bitorder="big")
    return packed, side, pixel_count


def write_draw_mask_header(
    flat_idx: np.ndarray,
    out_path: str | Path,
    *,
    sentinel: int,
    source_note: str = "",
) -> tuple[int, int]:
    """
    Write C header with PROGMEM uint8 array draw_mask[].
    Returns (side, pixel_count).
    """
    packed, side, pixel_count = flat_idx_to_packed_mask(flat_idx, sentinel)
    n_bits = side * side
    expected_bytes = (n_bits + 7) // 8
    if packed.size != expected_bytes:
        raise RuntimeError(f"packbits size mismatch: {packed.size} vs {expected_bytes}")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "/* Auto-generated draw mask for paint_mono_flash — do not edit by hand. */",
        f"/* Generated: {datetime.now(timezone.utc).isoformat()} */",
    ]
    if source_note:
        lines.append(f"/* Source: {source_note} */")
    lines.extend(
        [
            "#ifndef DRAW_DATA_H",
            "#define DRAW_DATA_H",
            "",
            "#include <stdint.h>",
            "#include <avr/pgmspace.h>",
            "",
            f"#define DRAW_MASK_WIDTH {side}u",
            f"#define DRAW_MASK_HEIGHT {side}u",
            f"#define DRAW_MASK_BYTES {packed.size}u",
            f"#define DRAW_MASK_SENTINEL_NOTE 0x{sentinel:02X} /* NO_DRAW in source indices */",
            f"#define DRAW_PIXEL_COUNT {pixel_count}ul",
            "",
            f"const uint8_t draw_mask[{packed.size}] PROGMEM = {{",
        ]
    )

    row: list[str] = []
    for i, b in enumerate(packed):
        row.append(f"0x{int(b):02x}")
        if len(row) >= 16 or i == len(packed) - 1:
            lines.append("  " + ", ".join(row) + ("," if i < len(packed) - 1 else ""))
            row = []

    lines.extend(["};", "", "#endif", ""])

    out_path.write_text("\n".join(lines), encoding="utf-8")

    if packed.size > _LEONARDO_MASK_BYTES:
        print(
            f"warning: mask is {packed.size} bytes (> {_LEONARDO_MASK_BYTES}); "
            "Leonardo may not fit sketch + NintendoSwitchControlLibrary — use sparse export later or smaller canvas.",
            file=sys.stderr,
        )
    if pixel_count > _FLASH_WARN_PIXELS:
        print(
            f"warning: {pixel_count} drawable pixels — expect long runtime (not flash size).",
            file=sys.stderr,
        )

    return side, pixel_count


def load_indices_bin(path: Path) -> np.ndarray:
    data = path.read_bytes()
    return np.frombuffer(data, dtype=np.uint8)


def main() -> int:
    ap = argparse.ArgumentParser(description="Export mono draw mask header for paint_mono_flash.ino")
    ap.add_argument("--indices", type=Path, required=True, help="65536-byte indices.bin (or N×N square)")
    ap.add_argument("--sentinel", type=int, default=255, help="NO_DRAW byte value (default 255)")
    ap.add_argument("-o", "--output", type=Path, default=Path("draw_data.h"), help="Output header path")
    ap.add_argument("--note", default="", help="Comment note in header")
    args = ap.parse_args()

    if not args.indices.is_file():
        print(f"not found: {args.indices}", file=sys.stderr)
        return 2

    flat = load_indices_bin(args.indices)
    side, count = write_draw_mask_header(flat, args.output, sentinel=args.sentinel, source_note=args.note or str(args.indices))
    print(f"Wrote {args.output} ({side}×{side}, {count} drawable pixels, {flat.size} source bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
