#!/usr/bin/env python3
"""Resize square PNG to 256×256, quantize opaque pixels to nearest Lab palette color, preserve transparency."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import colorutil


def load_yaml(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve_path(base_file: str, p: str) -> str:
    if os.path.isabs(p):
        return p
    base = os.path.dirname(os.path.abspath(base_file))
    return os.path.normpath(os.path.join(base, p))


def resampling_from_name(name: str) -> int:
    n = (name or "lanczos").lower()
    table = {
        "lanczos": Image.Resampling.LANCZOS,
        "bilinear": Image.Resampling.BILINEAR,
        "box": Image.Resampling.BOX,
        "nearest": Image.Resampling.NEAREST,
    }
    if n not in table:
        raise ValueError(f"unknown resampling: {name!r} (use {', '.join(table)})")
    return table[n]


def load_palette(path: str) -> tuple[np.ndarray, dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    colors = sorted(data["colors"], key=lambda c: int(c["index"]))
    if len(colors) != 84:
        raise ValueError(f"expected 84 palette colors, got {len(colors)}")
    for i, c in enumerate(colors):
        if int(c["index"]) != i:
            raise ValueError("palette indices must be contiguous 0..83")
    rgb = np.array([c["rgb"] for c in colors], dtype=np.uint8)
    return rgb, data.get("meta") or {}


def _resize_rgba(
    img: Image.Image,
    size: int,
    rgb_mode: int,
    alpha_mode: int,
) -> Image.Image:
    if img.mode not in ("RGBA", "RGB"):
        img = img.convert("RGBA")
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = rgb.resize((size, size), rgb_mode)
    a = a.resize((size, size), alpha_mode)
    return Image.merge("RGBA", (*rgb.split(), a))


def prepare(
    img: Image.Image,
    pal_rgb: np.ndarray,
    size: int,
    alpha_threshold: int,
    index_sentinel: int,
    rgb_mode: int,
    alpha_mode: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return rgba uint8 (H,W,4) and flat indices uint8 (H*W,) with sentinel for NO_DRAW."""
    w, h = img.size
    if w != h:
        raise ValueError(f"input must be 1:1 (square), got {w}×{h}")

    resized = _resize_rgba(img, size, rgb_mode, alpha_mode)
    rgba = np.asarray(resized, dtype=np.uint8)
    rgb = rgba[:, :, :3].reshape(-1, 3)
    alpha = rgba[:, :, 3].reshape(-1)
    draw = alpha >= alpha_threshold

    nearest = colorutil.nearest_palette_indices_lab(rgb, pal_rgb)
    out_rgb = np.zeros_like(rgb)
    out_a = np.zeros(alpha.shape[0], dtype=np.uint8)
    flat_idx = np.full(alpha.shape[0], index_sentinel, dtype=np.uint8)

    d = draw
    out_rgb[d] = pal_rgb[nearest[d]]
    out_a[d] = 255
    out_a[~d] = 0
    flat_idx[d] = nearest[d].astype(np.uint8)

    out_rgba = np.empty((size, size, 4), dtype=np.uint8)
    out_rgba[:, :, :3] = out_rgb.reshape(size, size, 3)
    out_rgba[:, :, 3] = out_a.reshape(size, size)
    return out_rgba, flat_idx


def export_bundle(
    rgba: np.ndarray,
    flat_idx: np.ndarray,
    *,
    out_png: str,
    out_bin: str | None,
    out_meta: str | None,
    size: int,
    alpha_threshold: int,
    index_sentinel: int,
    rgb_name: str,
    alpha_name: str,
    source_file: str,
    palette_path: str,
    pal_meta: dict[str, Any],
) -> None:
    """Write PNG and optional bin/meta (same layout as CLI)."""
    out_dir = os.path.dirname(os.path.abspath(out_png))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(rgba).save(out_png)

    if out_bin:
        if flat_idx.size != size * size:
            raise RuntimeError("internal: index buffer size mismatch")
        bdir = os.path.dirname(os.path.abspath(out_bin))
        if bdir:
            os.makedirs(bdir, exist_ok=True)
        flat_idx.tofile(out_bin)

    if out_meta:
        meta = {
            "version": 1,
            "width": size,
            "height": size,
            "index_order": "row_major_y_then_x",
            "index_formula": "i = y * width + x",
            "index_sentinel": index_sentinel,
            "index_sentinel_meaning": "NO_DRAW",
            "alpha_threshold": alpha_threshold,
            "resampling_rgb": rgb_name,
            "resampling_alpha": alpha_name,
            "quantization": "nearest_lab",
            "source_file": os.path.abspath(source_file),
            "palette_json": os.path.abspath(palette_path),
            "palette_source_meta": pal_meta,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        mdir = os.path.dirname(os.path.abspath(out_meta))
        if mdir:
            os.makedirs(mdir, exist_ok=True)
        with open(out_meta, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)
            f.write("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Prepare 256×256 quantized texture for Arduino drawing.")
    ap.add_argument("--config", default=None, help="YAML config (defaults merged with CLI)")
    ap.add_argument("--input", required=True, help="Square PNG input")
    ap.add_argument("--palette-json", default=None, help="palette_default.json path")
    ap.add_argument("--output-png", required=True, help="256×256 RGBA PNG output")
    ap.add_argument("--output-bin", default=None, help="Optional 65536-byte index file (0–83, 0xFF=NO_DRAW)")
    ap.add_argument("--output-meta", default=None, help="Optional sidecar JSON metadata")
    args = ap.parse_args()

    cfg: dict[str, Any] = {}
    config_path = args.config
    if config_path:
        cfg = load_yaml(config_path) or {}

    out = cfg.get("output") or {}
    size = int(out.get("size", 256))
    alpha_threshold = int(cfg.get("alpha_threshold", 128))
    index_sentinel = int(cfg.get("index_sentinel", 255))
    res = cfg.get("resampling") or {}
    rgb_name = str(res.get("rgb", "lanczos"))
    alpha_name = str(res.get("alpha", "nearest"))

    paths = cfg.get("paths") or {}
    pal_rel = paths.get("palette_json", "../../../assets/generated/palette_default.json")
    palette_path = args.palette_json
    if not palette_path:
        if not config_path:
            print("Pass --palette-json or --config with paths.palette_json", file=sys.stderr)
            return 2
        palette_path = resolve_path(config_path, pal_rel)
    elif config_path and not os.path.isabs(palette_path):
        palette_path = resolve_path(config_path, palette_path)

    if not os.path.isfile(palette_path):
        print(f"Palette JSON not found: {palette_path}", file=sys.stderr)
        return 2

    if index_sentinel < 0 or index_sentinel > 255:
        print("index_sentinel must be 0–255", file=sys.stderr)
        return 2
    if index_sentinel <= 83:
        print("index_sentinel must not collide with palette indices 0–83", file=sys.stderr)
        return 2

    pal_rgb, pal_meta = load_palette(palette_path)
    rgb_mode = resampling_from_name(rgb_name)
    alpha_mode = resampling_from_name(alpha_name)

    img = Image.open(args.input)
    rgba, flat_idx = prepare(
        img,
        pal_rgb,
        size=size,
        alpha_threshold=alpha_threshold,
        index_sentinel=index_sentinel,
        rgb_mode=rgb_mode,
        alpha_mode=alpha_mode,
    )

    export_bundle(
        rgba,
        flat_idx,
        out_png=args.output_png,
        out_bin=args.output_bin,
        out_meta=args.output_meta,
        size=size,
        alpha_threshold=alpha_threshold,
        index_sentinel=index_sentinel,
        rgb_name=rgb_name,
        alpha_name=alpha_name,
        source_file=args.input,
        palette_path=palette_path,
        pal_meta=pal_meta,
    )

    out_png = args.output_png

    drawn = int((flat_idx != index_sentinel).sum())
    print(f"Wrote {size}×{size} PNG ({drawn} drawable pixels): {out_png}")
    if args.output_bin:
        print(f"Wrote index bin ({flat_idx.size} bytes): {args.output_bin}")
    if args.output_meta:
        print(f"Wrote meta: {args.output_meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
