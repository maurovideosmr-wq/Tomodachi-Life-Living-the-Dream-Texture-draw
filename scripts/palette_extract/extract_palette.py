#!/usr/bin/env python3
"""Extract a 12x7 game palette from a reference screenshot (robust ROI + filtering)."""

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


def _load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _resolve_path(config_path: str, p: str | None) -> str | None:
    if p is None:
        return None
    if os.path.isabs(p):
        return p
    base = os.path.dirname(os.path.abspath(config_path))
    return os.path.normpath(os.path.join(base, p))


def _aggregate_color(pixels: np.ndarray, mode: str) -> np.ndarray:
    """pixels: (N, 3) uint8 -> (3,) uint8."""
    if pixels.shape[0] == 0:
        raise ValueError("no pixels")
    if mode == "median_rgb":
        return np.median(pixels.astype(np.float64), axis=0).round().clip(0, 255).astype(np.uint8)
    if mode == "median_lab":
        xyz = colorutil.rgb255_to_xyz(pixels)
        lab = colorutil.xyz_to_lab(xyz)
        med = np.median(lab, axis=0).reshape(1, 3)
        out = colorutil.xyz_to_rgb255(colorutil.lab_to_xyz(med))
        return out.reshape(3)
    raise ValueError(f"unknown aggregate mode: {mode}")


def _foreground_mask_vs_white(pixels: np.ndarray, white: float = 255.0) -> np.ndarray:
    """Keep pixels closer to the patch median than to pure white (screens gaps / halos).

    Works for literal white swatches: when the median is already near white, most
    pigment pixels tie with white and remain included.
    """
    p = pixels.astype(np.float64)
    med = np.median(p, axis=0)
    w = np.array([white, white, white], dtype=np.float64)
    d_med = np.linalg.norm(p - med, axis=1)
    d_white = np.linalg.norm(p - w, axis=1)
    return d_med <= d_white + 1e-9


def extract_palette(
    img: Image.Image,
    cfg: dict[str, Any],
    log: list[str],
) -> list[dict[str, Any]]:
    grid = cfg["grid"]
    cols = int(grid["cols"])
    rows = int(grid["rows"])
    order = str(grid.get("index_order", "row_major"))
    if order != "row_major":
        raise ValueError(f"unsupported index_order: {order}")

    cr = cfg.get("crop") or {}
    left = int(cr.get("left") or 0)
    top = int(cr.get("top") or 0)
    cw = cr.get("width")
    ch = cr.get("height")
    w, h = img.size
    if cw is None:
        cw = w - left
    if ch is None:
        ch = h - top
    cw = int(cw)
    ch = int(ch)
    if cw <= 0 or ch <= 0:
        raise ValueError("invalid crop width/height")

    img = img.crop((left, top, left + cw, top + ch))
    arr = np.asarray(img.convert("RGB"))

    sp = cfg.get("sampling") or {}
    roi_ratio = float(sp.get("roi_ratio", 0.42))
    min_px = int(sp.get("min_pixels_after_filter", 8))
    white_ref = float(sp.get("white_reference", 255.0))
    aggregate = str(sp.get("aggregate", "median_lab"))

    out_cfg = cfg.get("output") or {}
    inc_hex = bool(out_cfg.get("include_hex", True))
    inc_lab = bool(out_cfg.get("include_lab", True))

    cell_w = cw / cols
    cell_h = ch / rows
    results: list[dict[str, Any]] = []

    for row in range(rows):
        for col in range(cols):
            cx = (col + 0.5) * cell_w
            cy = (row + 0.5) * cell_h
            half = min(cell_w, cell_h) * roi_ratio / 2.0
            x0 = int(np.floor(cx - half))
            x1 = int(np.ceil(cx + half))
            y0 = int(np.floor(cy - half))
            y1 = int(np.ceil(cy + half))
            x0 = max(0, x0)
            y0 = max(0, y0)
            x1 = min(arr.shape[1], x1)
            y1 = min(arr.shape[0], y1)
            patch = arr[y0:y1, x0:x1]
            flat = patch.reshape(-1, 3)
            if flat.shape[0] == 0:
                log.append(f"WARN empty ROI row={row} col={col} — using full cell median")
                y0c = int(row * cell_h)
                y1c = int((row + 1) * cell_h)
                x0c = int(col * cell_w)
                x1c = int((col + 1) * cell_w)
                patch = arr[y0c:y1c, x0c:x1c]
                flat = patch.reshape(-1, 3)

            mask = _foreground_mask_vs_white(flat, white_ref)
            sel = flat[mask]
            used_fallback = False
            if sel.shape[0] < min_px:
                log.append(
                    f"WARN row={row} col={col}: only {sel.shape[0]} fg pixels "
                    f"(min {min_px}); using unfiltered median_rgb"
                )
                sel = flat
                used_fallback = True
                rgb = _aggregate_color(sel, "median_rgb")
            else:
                rgb = _aggregate_color(sel, aggregate)

            idx = row * cols + col
            entry: dict[str, Any] = {
                "index": idx,
                "row": row,
                "col": col,
                "rgb": [int(rgb[0]), int(rgb[1]), int(rgb[2])],
                "stats": {
                    "roi_pixels": int(flat.shape[0]),
                    "foreground_pixels": int(mask.sum()),
                    "used_unfiltered_fallback": used_fallback,
                },
            }
            if inc_hex:
                entry["hex"] = colorutil.rgb_to_hex(rgb)
            if inc_lab:
                entry["lab"] = colorutil.rgb_to_lab_dict(rgb)