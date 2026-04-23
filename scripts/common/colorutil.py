"""sRGB (0–255) and CIE Lab (D65) helpers — shared by palette_extract and texture_prep."""

from __future__ import annotations

import numpy as np


def _srgb_channel_to_linear(c: np.ndarray) -> np.ndarray:
    c = c.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def rgb255_to_xyz(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    R = _srgb_channel_to_linear(r)
    G = _srgb_channel_to_linear(g)
    B = _srgb_channel_to_linear(b)
    X = R * 0.4124564 + G * 0.3575761 + B * 0.1804375
    Y = R * 0.2126729 + G * 0.7151522 + B * 0.0721750
    Z = R * 0.0193339 + G * 0.1191920 + B * 0.9503041
    return np.stack([X, Y, Z], axis=-1)


def _lab_f(t: np.ndarray) -> np.ndarray:
    delta = 6.0 / 29.0
    return np.where(t > delta**3, np.cbrt(t), (t / (3.0 * delta**2)) + (4.0 / 29.0))


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    Xn, Yn, Zn = 0.95047, 1.0, 1.08883
    x, y, z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    fx = _lab_f(x / Xn)
    fy = _lab_f(y / Yn)
    fz = _lab_f(z / Zn)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return np.stack([L, a, b], axis=-1)


def _lab_inv_f(ft: np.ndarray) -> np.ndarray:
    delta = 6.0 / 29.0
    ft3 = ft**3
    return np.where(ft3 > delta**3, ft3, 3.0 * delta**2 * (ft - 4.0 / 29.0))


def lab_to_xyz(lab: np.ndarray) -> np.ndarray:
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    Xn, Yn, Zn = 0.95047, 1.0, 1.08883
    x = _lab_inv_f(fx) * Xn
    y = _lab_inv_f(fy) * Yn
    z = _lab_inv_f(fz) * Zn
    return np.stack([x, y, z], axis=-1)


def xyz_to_rgb255(xyz: np.ndarray) -> np.ndarray:
    X, Y, Z = xyz[..., 0], xyz[..., 1], xyz[..., 2]
    R_lin = X * 3.2404542 + Y * -1.5371385 + Z * -0.4985314
    G_lin = X * -0.9692660 + Y * 1.8760108 + Z * 0.0415560
    B_lin = X * 0.0556434 + Y * -0.2040259 + Z * 1.0572252

    def lin_to_srgb(c: np.ndarray) -> np.ndarray:
        c = np.clip(c, 0.0, 1.0)
        return np.where(c <= 0.0031308, 12.92 * c, 1.055 * (c ** (1.0 / 2.4)) - 0.055)

    r = lin_to_srgb(R_lin)
    g = lin_to_srgb(G_lin)
    bl = lin_to_srgb(B_lin)
    rgb = np.stack([r, g, bl], axis=-1) * 255.0
    return np.clip(np.round(rgb), 0, 255).astype(np.uint8)


def rgb_to_hex(rgb: np.ndarray) -> str:
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    return f"#{r:02x}{g:02x}{b:02x}"


def rgb_to_lab_dict(rgb: np.ndarray) -> dict[str, float]:
    xyz = rgb255_to_xyz(rgb.reshape(1, 3))
    lab = xyz_to_lab(xyz).reshape(3)
    return {
        "L": round(float(lab[0]), 3),
        "a": round(float(lab[1]), 3),
        "b": round(float(lab[2]), 3),
    }


def nearest_palette_index_lab(rgb: np.ndarray, palette_rgb: np.ndarray) -> np.int64:
    """Single pixel (3,) uint8 -> palette row index."""
    p = rgb.reshape(1, 3)
    return nearest_palette_indices_lab(p, palette_rgb)[0]


def nearest_palette_indices_lab(rgb: np.ndarray, palette_rgb: np.ndarray) -> np.ndarray:
    """Many pixels (N,3) uint8 -> (N,) int64 indices into palette rows."""
    pal_lab = xyz_to_lab(rgb255_to_xyz(palette_rgb.astype(np.uint8)))
    pix_lab = xyz_to_lab(rgb255_to_xyz(rgb.astype(np.uint8)))
    d = np.sum((pix_lab[:, None, :] - pal_lab[None, :, :]) ** 2, axis=2)
    return np.argmin(d, axis=1).astype(np.int64)
