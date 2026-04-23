#!/usr/bin/env python3
"""Tkinter GUI: Tab1 位图 256×256 / 84 色；Tab2 矢量 SVG → draw_vector_data.h（单色 / 多色 + 重映射）。"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

_APP_DIR = Path(__file__).resolve().parent
_SCRIPTS = _APP_DIR.parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from common import palette_defaults as paldef
from mono_draw_export import write_draw_mask_header
from svg_compiler import (
    COLOR_EMIT_BATCH_PREFILL,
    COLOR_EMIT_INLINE,
    CompileResult,
    STROKE_ORDER_BY_SLOT,
    STROKE_ORDER_MIN_AIR,
    STROKE_ORDER_PENALIZED,
    compile_svg,
    compile_svg_multicolor,
    compile_svg_multicolor_auto84,
    render_strokes_preview,
    write_draw_vector_header,
    write_remap_json,
    write_vector_setup_markdown,
)
from prepare_texture import (
    export_bundle,
    load_palette,
    load_yaml,
    prepare,
    resampling_from_name,
    resolve_path,
)

RESAMPLE_CHOICES = ("lanczos", "bilinear", "box", "nearest")
PREVIEW_MAX = 420
OUTPUT_PREVIEW_SCALE = 3  # 256 * 3 = 768 max side, clamp below

# 多色栅格预览：与 render_strokes_preview(preview_background_rgb) 的灰底一致
VEC_PREVIEW_MODE_DISTINCT = "distinct"  # 高区分度伪色，深底
VEC_PREVIEW_MODE_MAPPED = "mapped"  # 九槽在色表中的 sRGB 实色
VECTOR_PREVIEW_CHROME_DARK = "#1e1e26"
VECTOR_PREVIEW_CHROME_MAPPED_BG = "#c0c0c0"  # 与 (192,192,192) 标准灰一致
PREVIEW_MAPPED_BACKGROUND_RGB: tuple[int, int, int] = (192, 192, 192)


def _default_nine_indices_from_path(p: str) -> list[int]:
    """
    与固件 PALETTE_DEFAULT_NINE / common.palette_defaults 一致；无有效 JSON 时回退 0..8。
    """
    if not p.strip() or not Path(p).is_file():
        return [i for i in range(9)]
    try:
        return list(paldef.default_nine_indices_from_palette_path(Path(p)))
    except (OSError, ValueError, KeyError):
        return [i for i in range(9)]


class TexturePrepApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.minsize(880, 640)

        self._cfg_path = _APP_DIR / "config" / "default.yaml"
        cfg = load_yaml(str(self._cfg_path)) if self._cfg_path.is_file() else {}

        out = cfg.get("output") or {}
        self._size = int(out.get("size", 256))
        self._alpha_threshold = tk.IntVar(value=int(cfg.get("alpha_threshold", 128)))
        self._index_sentinel = int(cfg.get("index_sentinel", 255))

        res = cfg.get("resampling") or {}
        self._rgb_resample = tk.StringVar(value=str(res.get("rgb", "lanczos")))
        self._alpha_resample = tk.StringVar(value=str(res.get("alpha", "nearest")))

        paths = cfg.get("paths") or {}
        pal_rel = paths.get("palette_json", "../../../assets/generated/palette_default.json")
        default_pal = resolve_path(str(self._cfg_path), pal_rel) if self._cfg_path.is_file() else ""

        self._palette_path = tk.StringVar(value=default_pal)
        self._image_path: str | None = None
        self._pil_source: Image.Image | None = None
        self._pal_rgb = None
        self._pal_meta: dict = {}
        self._last_rgba = None
        self._last_flat_idx = None

        self._photo_in: ImageTk.PhotoImage | None = None
        self._photo_out: ImageTk.PhotoImage | None = None
        self._debounce_id: str | None = None

        self._export_bin = tk.BooleanVar(value=True)
        self._export_meta = tk.BooleanVar(value=True)

        self._svg_path: str | None = None
        self._vector_result: CompileResult | None = None
        self._vector_preview_pil: Image.Image | None = None
        self._vec_multicolor = tk.BooleanVar(value=False)
        self._vec_multicolor_auto84 = tk.BooleanVar(value=True)
        self._vec_start_quick = tk.IntVar(value=0)
        _slot0 = _default_nine_indices_from_path(default_pal)
        self._vec_slot_idx: list[tk.IntVar] = [tk.IntVar(value=int(v)) for v in _slot0]
        self._vec_stroke_order = tk.StringVar(value=STROKE_ORDER_MIN_AIR)
        self._vec_penalty = tk.DoubleVar(value=0.0)
        self._vec_color_emit = tk.StringVar(value=COLOR_EMIT_INLINE)
        self._vec_emit_quick = tk.BooleanVar(
            value=False
        )  # False: 多色不写入 0:02(快选手动), 槽变只 0:03+0:04
        self._vec_mono_preamble = tk.BooleanVar(
            value=False
        )  # 单色: 片头槽0 全色定色
        self._vec_mono_slot0 = tk.IntVar(value=0)  # 0..83, 与 preamble 同用
        self._photo_vec: ImageTk.PhotoImage | None = None
        self._vec_samples = tk.DoubleVar(value=2.0)
        self._vec_preview_mode = tk.StringVar(value=VEC_PREVIEW_MODE_DISTINCT)
        self._vec_preview_rbs: list[ttk.Radiobutton] = []

        root = self.root
        root.title("贴图与矢量 — 绘制准备")
        nb = ttk.Notebook(root)
        nb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        tab_b = ttk.Frame(nb, padding=4)
        tab_v = ttk.Frame(nb, padding=4)
        nb.add(tab_b, text="位图 / 色板")
        nb.add(tab_v, text="矢量 / 线稿")
        self._build_bitmap_tab(tab_b)
        self._build_vector_tab(tab_v)
        self._try_load_palette_from_var()

    def _build_bitmap_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, padding=6)
        top.pack(fill=tk.X)
        ttk.Button(top, text="打开图片…", command=self._open_image).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="色表 JSON…", command=self._open_palette).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="刷新预览", command=self._refresh_preview).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="导出…", command=self._export).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="导出 draw_data.h (单色)…", command=self._export_mono_header).pack(
            side=tk.LEFT, padx=2
        )

        params = ttk.LabelFrame(parent, text="参数", padding=8)
        params.pack(fill=tk.X, padx=6, pady=4)

        row0 = ttk.Frame(params)
        row0.pack(fill=tk.X, pady=2)
        ttk.Label(row0, text="Alpha 阈值（≥ 则绘制）:").pack(side=tk.LEFT)
        self._alpha_scale = ttk.Scale(
            row0,
            from_=0,
            to=255,
            variable=self._alpha_threshold,
            orient=tk.HORIZONTAL,
            length=220,
            command=lambda _v: self._schedule_preview(),
        )
        self._alpha_scale.pack(side=tk.LEFT, padx=6)
        self._alpha_label = ttk.Label(row0, text="")
        self._alpha_label.pack(side=tk.LEFT)
        self._alpha_threshold.trace_add("write", lambda *_: self._update_alpha_label())

        row1 = ttk.Frame(params)
        row1.pack(fill=tk.X, pady=2)
        ttk.Label(row1, text="RGB 缩放:").pack(side=tk.LEFT)
        rgb_cb = ttk.Combobox(
            row1,
            textvariable=self._rgb_resample,
            values=RESAMPLE_CHOICES,
            state="readonly",
            width=12,
        )
        rgb_cb.pack(side=tk.LEFT, padx=6)
        rgb_cb.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())
        ttk.Label(row1, text="Alpha 缩放:").pack(side=tk.LEFT, padx=(16, 0))
        cb_a = ttk.Combobox(
            row1,
            textvariable=self._alpha_resample,
            values=RESAMPLE_CHOICES,
            state="readonly",
            width=12,
        )
        cb_a.pack(side=tk.LEFT, padx=6)
        cb_a.bind("<<ComboboxSelected>>", lambda _e: self._schedule_preview())

        row2 = ttk.Frame(params)
        row2.pack(fill=tk.X, pady=2)
        ttk.Label(row2, text=f"输出尺寸: {self._size}×{self._size}").pack(side=tk.LEFT)
        ttk.Label(row2, text=f"  NO_DRAW 索引: {self._index_sentinel}").pack(side=tk.LEFT, padx=(16, 0))
        ttk.Checkbutton(row2, text="导出 .bin", variable=self._export_bin).pack(side=tk.LEFT, padx=(24, 0))
        ttk.Checkbutton(row2, text="导出 meta.json", variable=self._export_meta).pack(side=tk.LEFT, padx=6)

        pan = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)

        left_f = ttk.LabelFrame(pan, text="原图预览", padding=4)
        right_f = ttk.LabelFrame(pan, text="量化预览（放大）", padding=4)
        pan.add(left_f, weight=1)
        pan.add(right_f, weight=1)

        self._lbl_in = ttk.Label(left_f)
        self._lbl_in.pack(expand=True)
        self._lbl_out = ttk.Label(right_f)
        self._lbl_out.pack(expand=True)

        self._status = ttk.Label(parent, text="就绪。请打开正方形 PNG。", anchor=tk.W)
        self._status.pack(fill=tk.X, padx=8, pady=4)

        self._update_alpha_label()

    def _build_vector_tab(self, parent: ttk.Frame) -> None:
        top = ttk.Frame(parent, padding=6)
        top.pack(fill=tk.X)
        ttk.Button(top, text="打开 SVG…", command=self._open_svg).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="刷新/编译", command=self._refresh_vector).pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="导出 draw_vector_data.h…", command=self._export_vector_header).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Checkbutton(
            top,
            text="多色 (换色发码)",
            variable=self._vec_multicolor,
            command=self._on_vec_multicolor_toggle,
        ).pack(side=tk.LEFT, padx=12)
        self._vec_cb_auto84 = ttk.Checkbutton(
            top,
            text="84 色自动 + 九槽 LRU(不手填 9 下标)",
            variable=self._vec_multicolor_auto84,
            command=self._on_vec_auto84_toggle,
        )
        self._vec_cb_auto84.pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(
            top,
            text="自动 0:02 快选发码(关=仅全色0:03+0:04, 快选由机上先手动)",
            variable=self._vec_emit_quick,
        ).pack(side=tk.LEFT, padx=8)
        info = ttk.LabelFrame(parent, text="说明", padding=6)
        info.pack(fill=tk.X, padx=6, pady=4)
        self._vec_info = ttk.Label(
            info,
            text="单色可勾选「片头全色(槽0)」在矢量前用 0:03+0:04 定色(须色表 JSON)。多色: 关「快选发码」则槽变只发全色序列(不写 0:02), 你先在机上切好快选高亮(与起槽一致)。多色时: 仅「自动 0:02 快选发码」开启才会额外写出 _vector_setup.md(填格说明) 。",
            wraplength=820,
        )
        self._vec_info.pack(anchor=tk.W)
        param = ttk.Frame(parent)
        param.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(param, text="路径采样（× 弧长）:").pack(side=tk.LEFT)
        sp = ttk.Scale(
            param,
            from_=0.3,
            to=8.0,
            variable=self._vec_samples,
            orient=tk.HORIZONTAL,
            length=200,
        )
        sp.pack(side=tk.LEFT, padx=4)
        self._vec_lbl = ttk.Label(param, text="2.0")
        self._vec_lbl.pack(side=tk.LEFT, padx=4)
        self._vec_samples.trace_add("write", lambda *_: self._vec_lbl.config(text=f"{self._vec_samples.get():.2f}"))

        ordrow = ttk.Frame(parent)
        ordrow.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(ordrow, text="多色 笔划顺序:").pack(side=tk.LEFT)
        self._vec_order_combo = ttk.Combobox(
            ordrow,
            textvariable=self._vec_stroke_order,
            state="readonly",
            width=22,
            values=(STROKE_ORDER_MIN_AIR, STROKE_ORDER_BY_SLOT, STROKE_ORDER_PENALIZED),
        )
        self._vec_order_combo.pack(side=tk.LEFT, padx=4)
        self._vec_order_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_vec_stroke_order_change())
        ttk.Label(ordrow, text="换色代价 W (等效格, 仅折中)").pack(side=tk.LEFT, padx=(10, 2))
        self._vec_sp_penalty = tk.Spinbox(
            ordrow,
            from_=0.0,
            to=10_000.0,
            increment=1.0,
            textvariable=self._vec_penalty,
            width=7,
        )
        self._vec_sp_penalty.pack(side=tk.LEFT, padx=2)
        self._vec_penalty.trace_add("write", lambda *_: self._vec_refresh_if_penalized())
        self._vec_sync_penalty_widget_state()
        emrow = ttk.Frame(parent)
        emrow.pack(fill=tk.X, padx=8, pady=2)
        ttk.Label(emrow, text="换色发码:").pack(side=tk.LEFT)
        ttk.Combobox(
            emrow,
            textvariable=self._vec_color_emit,
            state="readonly",
            width=18,
            values=(COLOR_EMIT_INLINE, COLOR_EMIT_BATCH_PREFILL),
        ).pack(side=tk.LEFT, padx=4)
        mof = ttk.Frame(parent)
        mof.pack(fill=tk.X, padx=8, pady=2)
        ttk.Checkbutton(
            mof,
            text="单色: 片头全色定色(槽0, 须位图 Tab 色表 JSON)",
            variable=self._vec_mono_preamble,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Label(mof, text="槽0 下标 0-83:").pack(side=tk.LEFT, padx=6)
        ttk.Spinbox(
            mof, from_=0, to=83, width=5, textvariable=self._vec_mono_slot0
        ).pack(side=tk.LEFT, padx=2)

        mc = ttk.LabelFrame(parent, text="多色: 快选 9 槽 = 0(顶)…8(底) 色板索引(0-83) 与 起点槽", padding=4)
        mc.pack(fill=tk.X, padx=6, pady=2)
        slotf = ttk.Frame(mc)
        slotf.pack(fill=tk.X)
        self._vec_slot_spins: list[tk.Spinbox] = []
        for r in range(3):
            rowf = ttk.Frame(slotf)
            rowf.pack(fill=tk.X, pady=1)
            for c in range(3):
                k = r * 3 + c
                ttk.Label(rowf, text=f"槽{k}:").pack(side=tk.LEFT, padx=2)
                sb = tk.Spinbox(
                    rowf,
                    from_=0,
                    to=83,
                    width=4,
                    textvariable=self._vec_slot_idx[k],
                )
                sb.pack(side=tk.LEFT, padx=1)
                self._vec_slot_spins.append(sb)
        ttk.Label(mc, text="开跑时主机快选高亮与之一致(通常 0=顶格):").pack(anchor=tk.W, pady=2)
        sk = tk.Spinbox(mc, from_=0, to=8, width=4, textvariable=self._vec_start_quick)
        sk.pack(anchor=tk.W)
        pm = ttk.Frame(mc)
        pm.pack(fill=tk.X, pady=(6, 2))
        ttk.Label(pm, text="多色栅格预览:").pack(side=tk.LEFT, padx=(0, 4))
        self._vec_preview_rbs = [
            ttk.Radiobutton(
                pm,
                text="槽位伪色(深底)",
                variable=self._vec_preview_mode,
                value=VEC_PREVIEW_MODE_DISTINCT,
            ),
            ttk.Radiobutton(
                pm,
                text="映射实色(标准灰底)",
                variable=self._vec_preview_mode,
                value=VEC_PREVIEW_MODE_MAPPED,
            ),
        ]
        for rb in self._vec_preview_rbs:
            rb.pack(side=tk.LEFT, padx=3)
        self._vec_preview_mode.trace_add("write", lambda *_: self._on_vec_preview_mode_change())

        pan = ttk.Panedwindow(parent, orient=tk.HORIZONTAL)
        pan.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        left_f = ttk.LabelFrame(pan, text="文件", padding=4)
        right_f = ttk.LabelFrame(pan, text="256 格栅格预览", padding=4)
        pan.add(left_f, weight=1)
        pan.add(right_f, weight=2)
        self._vec_lbl_path = ttk.Label(left_f, text="未打开文件。", wraplength=360, justify=tk.LEFT)
        self._vec_lbl_path.pack(anchor=tk.NW, fill=tk.X)
        self._vec_lbl_stats = ttk.Label(left_f, text="", wraplength=360, justify=tk.LEFT)
        self._vec_lbl_stats.pack(anchor=tk.NW, pady=8, fill=tk.X)
        # ttk.Label 在部分 Windows 主题下不显示 PhotoImage，改用经典 tk.Label
        _pbg = VECTOR_PREVIEW_CHROME_DARK
        self._frame_vec_img = tk.Frame(right_f, bg=_pbg)
        self._frame_vec_img.pack(fill=tk.BOTH, expand=True)
        self._lbl_vec = tk.Label(
            self._frame_vec_img,
            text="打开 SVG 后点「刷新/编译」。",
            bg=_pbg,
            fg="#b0b0c0",
            justify=tk.LEFT,
        )
        self._lbl_vec.pack(expand=True, fill=tk.BOTH)
        self._vector_status = ttk.Label(parent, text="就绪。", anchor=tk.W)
        self._vector_status.pack(fill=tk.X, padx=8, pady=4)
        self._sync_vec_preview_mode_state()
        self._sync_vec_slot_spins_state()

    def _vector_preview_chrome_color(self) -> str:
        r = self._vector_result
        if (
            r is not None
            and r.multicolor
            and self._vec_preview_mode.get() == VEC_PREVIEW_MODE_MAPPED
        ):
            return VECTOR_PREVIEW_CHROME_MAPPED_BG
        return VECTOR_PREVIEW_CHROME_DARK

    def _apply_vector_preview_from_result(self, r: CompileResult) -> None:
        """仅重画栅格与窗口周遍底色，不重新 compile。"""
        if not r.multicolor:
            im0 = render_strokes_preview(
                r.ordered_strokes,
                scale=2,
                grid=256,
                max_preview_points=0,
                slot_rgb9=None,
                preview_distinct_multicolor=False,
                preview_background_rgb=None,
            )
        else:
            slot9 = r.nine_target_rgb
            p84 = self._pal_rgb
            pkw: dict = {}
            if bool(getattr(r, "auto_nearest_84", False)) and p84 is not None:
                pkw = {"palette_full_84": p84}
            if self._vec_preview_mode.get() == VEC_PREVIEW_MODE_MAPPED:
                im0 = render_strokes_preview(
                    r.ordered_strokes,
                    scale=2,
                    grid=256,
                    max_preview_points=0,
                    slot_rgb9=slot9,
                    preview_distinct_multicolor=False,
                    preview_background_rgb=PREVIEW_MAPPED_BACKGROUND_RGB,
                    **pkw,
                )
            else:
                im0 = render_strokes_preview(
                    r.ordered_strokes,
                    scale=2,
                    grid=256,
                    max_preview_points=0,
                    slot_rgb9=slot9,
                    preview_distinct_multicolor=True,
                    preview_background_rgb=None,
                    **pkw,
                )
        self._vector_preview_pil = im0
        w, h = im0.size
        mside = max(w, h) if w and h else 0
        sc = min(PREVIEW_MAX / float(mside), 1.0) if mside else 1.0
        im = im0
        if sc < 1.0:
            nw, nh = max(1, int(round(w * sc))), max(1, int(round(h * sc)))
            im = im.resize((nw, nh), Image.Resampling.NEAREST)
        if max(im.size) > 600:
            im = im.copy()
            im.thumbnail((600, 600), Image.Resampling.NEAREST)
        ch = self._vector_preview_chrome_color()
        self._photo_vec = ImageTk.PhotoImage(im)
        self._lbl_vec.configure(image=self._photo_vec, text="", bg=ch)
        self._frame_vec_img.config(bg=ch)

    def _on_vec_preview_mode_change(self) -> None:
        r = self._vector_result
        if r is not None and r.multicolor:
            self._apply_vector_preview_from_result(r)

    def _sync_vec_preview_mode_state(self) -> None:
        st = tk.NORMAL if self._vec_multicolor.get() else tk.DISABLED
        for w in self._vec_preview_rbs:
            w.config(state=st)

    def _sync_vec_slot_spins_state(self) -> None:
        mco = self._vec_multicolor.get()
        auto = self._vec_multicolor_auto84.get()
        sb_st = (
            tk.DISABLED
            if (not mco) or (mco and auto)
            else tk.NORMAL
        )
        for sb in getattr(self, "_vec_slot_spins", ()):
            sb.config(state=sb_st)
        if hasattr(self, "_vec_cb_auto84"):
            self._vec_cb_auto84.config(state=tk.NORMAL if mco else tk.DISABLED)

    def _update_alpha_label(self) -> None:
        self._alpha_label.config(text=str(self._alpha_threshold.get()))

    def _schedule_preview(self) -> None:
        if self._debounce_id is not None:
            self.root.after_cancel(self._debounce_id)
        self._debounce_id = self.root.after(320, self._debounce_fire)

    def _debounce_fire(self) -> None:
        self._debounce_id = None
        self._refresh_preview()

    def _try_load_palette_from_var(self) -> None:
        p = self._palette_path.get().strip()
        if not p or not os.path.isfile(p):
            self._set_status(f"色表无效或不存在: {p or '(未设置)'}", error=True)
            self._pal_rgb = None
            return
        try:
            self._pal_rgb, self._pal_meta = load_palette(p)
            self._set_status(f"已加载色表: {os.path.basename(p)}（84 色）")
        except Exception as e:
            self._pal_rgb = None
            self._set_status(f"色表加载失败: {e}", error=True)

    def _open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="选择正方形 PNG",
            filetypes=[("PNG", "*.png"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            im = Image.open(path)
            self._pil_source = im
            self._image_path = path
            self._show_input_preview()
            self._schedule_preview()
            self._set_status(f"已打开: {path}  ({im.size[0]}×{im.size[1]})")
        except Exception as e:
            messagebox.showerror("打开失败", str(e))
            self._set_status(str(e), error=True)

    def _open_palette(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 palette JSON",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        self._palette_path.set(path)
        self._try_load_palette_from_var()
        self._schedule_preview()

    def _fit_preview(self, im: Image.Image, max_side: int) -> Image.Image:
        w, h = im.size
        scale = min(max_side / max(w, h), 1.0)
        if scale < 1.0:
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            return im.resize((nw, nh), Image.Resampling.LANCZOS)
        return im.copy()

    def _show_input_preview(self) -> None:
        if not self._pil_source:
            return
        disp = self._pil_source
        if disp.mode not in ("RGBA", "RGB"):
            disp = disp.convert("RGBA")
        thumb = self._fit_preview(disp, PREVIEW_MAX)
        self._photo_in = ImageTk.PhotoImage(thumb)
        self._lbl_in.configure(image=self._photo_in)

    def _show_output_preview(self, rgba: Image.Image) -> None:
        # rgba is PIL Image RGBA 256x256
        w, h = rgba.size
        scale = min(OUTPUT_PREVIEW_SCALE, PREVIEW_MAX // max(w, h))
        scale = max(scale, 1)
        nw, nh = w * scale, h * scale
        big = rgba.resize((nw, nh), Image.Resampling.NEAREST)
        self._photo_out = ImageTk.PhotoImage(big)
        self._lbl_out.configure(image=self._photo_out)

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status.config(text=text, foreground=("red" if error else ""))

    def _refresh_preview(self) -> None:
        self._update_alpha_label()
        if not self._pil_source:
            self._set_status("请先打开图片。", error=False)
            self._lbl_out.configure(image="")
            self._photo_out = None
            self._last_rgba = self._last_flat_idx = None
            return
        if self._pal_rgb is None:
            self._try_load_palette_from_var()
        if self._pal_rgb is None:
            self._last_rgba = self._last_flat_idx = None
            return

        w, h = self._pil_source.size
        if w != h:
            self._set_status(f"错误: 需要 1:1 正方形图，当前 {w}×{h}", error=True)
            self._lbl_out.configure(image="")
            self._photo_out = None
            self._last_rgba = self._last_flat_idx = None
            return

        try:
            rgb_mode = resampling_from_name(self._rgb_resample.get())
            alpha_mode = resampling_from_name(self._alpha_resample.get())
            rgba_arr, flat_idx = prepare(
                self._pil_source,
                self._pal_rgb,
                size=self._size,
                alpha_threshold=int(self._alpha_threshold.get()),
                index_sentinel=self._index_sentinel,
                rgb_mode=rgb_mode,
                alpha_mode=alpha_mode,
            )
            self._last_rgba = rgba_arr
            self._last_flat_idx = flat_idx
            out_img = Image.fromarray(rgba_arr)
            self._show_output_preview(out_img)
            drawn = int((flat_idx != self._index_sentinel).sum())
            self._set_status(
                f"预览 OK — 可绘制像素: {drawn} / {self._size * self._size}  |  源: {self._image_path}",
                error=False,
            )
        except Exception as e:
            self._last_rgba = self._last_flat_idx = None
            self._lbl_out.configure(image="")
            self._photo_out = None
            self._set_status(f"预览失败: {e}", error=True)

    def _export_mono_header(self) -> None:
        if self._last_flat_idx is None:
            messagebox.showwarning("导出 draw_data.h", "请先成功刷新预览（需要可绘制的 flat 索引）。")
            return
        path = filedialog.asksaveasfilename(
            title="保存 draw_data.h（放入 firmware/paint_mono_flash/）",
            defaultextension=".h",
            filetypes=[("C header", "*.h"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            _, count = write_draw_mask_header(
                self._last_flat_idx,
                path,
                sentinel=self._index_sentinel,
                source_note=self._image_path or "gui_app",
            )
            messagebox.showinfo(
                "draw_data.h",
                f"已写入:\n{path}\n可绘制像素: {count}\n\n覆盖 firmware/paint_mono_flash/draw_data.h 后打开 "
                f"paint_mono_flash.ino 上传。进游戏前先选好颜色，再进贴图绘制默认中心。",
            )
            self._set_status(f"已导出 draw_data.h（{count} 笔）: {path}", error=False)
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            self._set_status(str(e), error=True)

    def _export(self) -> None:
        if self._last_rgba is None or self._last_flat_idx is None:
            messagebox.showwarning("导出", "没有可导出的预览结果（请先成功刷新预览）。")
            return
        path = filedialog.asksaveasfilename(
            title="导出 PNG",
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All", "*.*")],
        )
        if not path:
            return
        pal = self._palette_path.get().strip()
        if not pal:
            messagebox.showerror("导出", "色表路径为空。")
            return
        base, _ = os.path.splitext(path)
        bin_path = f"{base}_indices.bin" if self._export_bin.get() else None
        meta_path = f"{base}_meta.json" if self._export_meta.get() else None

        try:
            export_bundle(
                self._last_rgba,
                self._last_flat_idx,
                out_png=path,
                out_bin=bin_path,
                out_meta=meta_path,
                size=self._size,
                alpha_threshold=int(self._alpha_threshold.get()),
                index_sentinel=self._index_sentinel,
                rgb_name=self._rgb_resample.get(),
                alpha_name=self._alpha_resample.get(),
                source_file=self._image_path or "",
                palette_path=pal,
                pal_meta=self._pal_meta,
            )
            msg = f"已写入:\n{path}"
            if bin_path:
                msg += f"\n{bin_path}"
            if meta_path:
                msg += f"\n{meta_path}"
            messagebox.showinfo("导出完成", msg)
            self._set_status(f"已导出: {path}", error=False)
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            self._set_status(str(e), error=True)

    def _set_vector_status(self, text: str, error: bool = False) -> None:
        self._vector_status.config(
            text=text, foreground=("#a03030" if error else "")
        )

    def _vec_sync_penalty_widget_state(self) -> None:
        en = (
            self._vec_stroke_order.get() == STROKE_ORDER_PENALIZED
            and self._vec_multicolor.get()
        )
        self._vec_sp_penalty.config(state=tk.NORMAL if en else tk.DISABLED)

    def _on_vec_stroke_order_change(self) -> None:
        self._vec_sync_penalty_widget_state()
        self._refresh_vector()

    def _on_vec_multicolor_toggle(self) -> None:
        self._vec_sync_penalty_widget_state()
        self._sync_vec_preview_mode_state()
        self._sync_vec_slot_spins_state()
        self._refresh_vector()

    def _on_vec_auto84_toggle(self) -> None:
        self._sync_vec_slot_spins_state()
        self._refresh_vector()

    def _vec_refresh_if_penalized(self) -> None:
        if self._vec_stroke_order.get() == STROKE_ORDER_PENALIZED and self._vec_multicolor.get():
            self._refresh_vector()

    def _vec_slot_indices(self) -> list[int]:
        out: list[int] = []
        for v in self._vec_slot_idx:
            x = int(v.get())
            x = max(0, min(83, x))
            out.append(x)
        return out

    def _nine_target_rgb(self) -> np.ndarray:
        if self._pal_rgb is None:
            raise RuntimeError("未加载 84 色表")
        idxs = self._vec_slot_indices()
        out = np.zeros((9, 3), dtype=np.uint8)
        for i, ix in enumerate(idxs):
            out[i, :] = self._pal_rgb[ix]
        return out

    def _remap_confirm_dialog(self, res: CompileResult) -> bool:
        if not res.multicolor or not res.remap_rows:
            return True
        top = tk.Toplevel(self.root)
        top.title("确认重映射 (多色 SVG)")
        top.transient(self.root)
        top.grab_set()
        ttk.Label(
            top,
            text="Lab 最近邻到九目标槽。大 ΔE 时请在 Illustrator 中换色后重新编译。确认後才写入头文件。",
            wraplength=480,
        ).pack(padx=8, pady=6)
        cols = ("raw", "n", "slot", "target", "de")
        tv = ttk.Treeview(
            top,
            columns=cols,
            show="headings",
            height=min(12, max(3, len(res.remap_rows))),
        )
        tv.heading("raw", text="原色")
        tv.heading("n", text="path 数")
        tv.heading("slot", text="槽 0-8")
        tv.heading("target", text="目标 RGB")
        tv.heading("de", text="ΔE(76)")
        tv.column("raw", width=80)
        tv.column("n", width=50)
        tv.column("slot", width=50)
        tv.column("target", width=100)
        tv.column("de", width=80)
        for row in res.remap_rows:
            tg = row.target_rgb
            tv.insert(
                "",
                tk.END,
                values=(
                    row.raw_hex,
                    row.path_count,
                    row.slot,
                    f"#{tg[0]:02x}{tg[1]:02x}{tg[2]:02x}",
                    f"{row.delta_e:.1f}",
                ),
            )
        tv.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        out = {"ok": False}

        def _ok() -> None:
            out["ok"] = True
            top.destroy()

        def _cancel() -> None:
            top.destroy()

        bf = ttk.Frame(top)
        bf.pack(pady=6)
        ttk.Button(bf, text="确认并继续导出", command=_ok).pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text="取消", command=_cancel).pack(side=tk.LEFT, padx=4)
        self.root.wait_window(top)
        return bool(out["ok"])

    def _open_svg(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 SVG 线稿",
            filetypes=[("SVG", "*.svg"), ("All", "*.*")],
        )
        if not path:
            return
        self._svg_path = path
        self._vec_lbl_path.config(text=path)
        self._set_vector_status(f"已选择: {path}", error=False)
        self._refresh_vector()

    def _refresh_vector(self) -> None:
        if not self._svg_path or not os.path.isfile(self._svg_path):
            self._set_vector_status("请先打开有效的 SVG 文件。", error=True)
            self._vector_result = None
            self._vector_preview_pil = None
            self._photo_vec = None
            self._lbl_vec.configure(
                image="",
                text="请先打开 .svg 文件。",
                bg=VECTOR_PREVIEW_CHROME_DARK,
                fg="#b0b0c0",
            )
            self._frame_vec_img.config(bg=VECTOR_PREVIEW_CHROME_DARK)
            self._vec_lbl_stats.config(text="")
            return

        try:
            if self._vec_multicolor.get():
                if self._pal_rgb is None:
                    self._try_load_palette_from_var()
                if self._pal_rgb is None:
                    raise RuntimeError("多色需要有效的色表 (位图 Tab 或默认 palette 路径)")
                wpen = float(self._vec_penalty.get() or 0.0)
                pal_def = self._palette_path.get().strip()
                pjson = pal_def if pal_def and os.path.isfile(pal_def) else None
                if self._vec_multicolor_auto84.get():
                    self._vector_result = compile_svg_multicolor_auto84(
                        self._svg_path,
                        palette_default_json=pjson,
                        start_quick_index=int(self._vec_start_quick.get()) & 0xFF,
                        samples_per_len=float(self._vec_samples.get()),
                        stroke_order=str(self._vec_stroke_order.get()),
                        quick_switch_penalty=wpen,
                        color_emit=str(self._vec_color_emit.get()),
                        emit_color_quick=self._vec_emit_quick.get(),
                    )
                else:
                    nine = self._nine_target_rgb()
                    pidxs = self._vec_slot_indices()
                    self._vector_result = compile_svg_multicolor(
                        self._svg_path,
                        nine,
                        palette_index_per_slot=pidxs,
                        palette_default_json=pjson,
                        start_quick_index=int(self._vec_start_quick.get()) & 0xFF,
                        samples_per_len=float(self._vec_samples.get()),
                        stroke_order=str(self._vec_stroke_order.get()),
                        quick_switch_penalty=wpen,
                        color_emit=str(self._vec_color_emit.get()),
                        emit_color_quick=self._vec_emit_quick.get(),
                    )
            else:
                palp = self._palette_path.get().strip()
                mpre = self._vec_mono_preamble.get()
                if mpre and (not palp or not os.path.isfile(palp)):
                    raise RuntimeError(
                        "已勾选「片头全色(槽0)」：请在位图 Tab 选择有效色表 JSON 路径"
                    )
                self._vector_result = compile_svg(
                    self._svg_path,
                    samples_per_len=float(self._vec_samples.get()),
                    palette_default_json=palp if mpre else None,
                    monochrome_preamble=mpre,
                    monochrome_slot0_index=int(self._vec_mono_slot0.get()) if mpre else None,
                )
            r = self._vector_result
            self._apply_vector_preview_from_result(r)
            extra = ""
            if r.multicolor:
                if r.remap_rows:
                    extra = f"\n重映射: {len(r.remap_rows)} 种原色  \n多色: 确认重映射后导出(含 .h 与 _remap.json) 。"
                if self._vec_preview_mode.get() == VEC_PREVIEW_MODE_MAPPED:
                    extra += "\n栅格预览: 九槽在色表中的映射实色，标准灰底(#c0c0c0)。"
                else:
                    if getattr(r, "auto_nearest_84", False) and self._pal_rgb is not None:
                        extra += "\n栅格预览(自动): ink=全表最近色 。"
                    else:
                        extra += "\n栅格预览: 按槽 0-8 高区分度伪色(非实机九色)，深底。"
            ord_line = ""
            if r.multicolor:
                ord_line = (
                    f"\n空跑(切比和): {r.air_cheb_sum}  QUICK: {r.quick_switch_count}  "
                    f"FULL_BIND: {r.full_bind_count}  SUB_HAT4: {r.sub_hat4_count}  "
                    f"emit: {r.color_emit}  快选发码(0:02): {r.emit_color_quick}\n  顺序: {r.stroke_order}"
                )
                if r.over_nine_distinct_indices:
                    if getattr(r, "auto_nearest_84", False):
                        ord_line += (
                            f"  去重 {r.distinct_palette_index_count} 色(>9 时九槽循环换绑)"
                        )
                    else:
                        ord_line += f"  去重色 {r.distinct_palette_index_count}>9 (单段铺不下)"
                if r.stroke_order == STROKE_ORDER_PENALIZED:
                    ord_line += f"  W={r.quick_switch_penalty:.0f}"
            else:
                if getattr(r, "monochrome_preamble", False) or r.full_bind_count:
                    ord_line = (
                        f"\n(单色) FULL_BIND: {r.full_bind_count}  "
                        f"SUB_HAT4: {r.sub_hat4_count}  QUICK: {r.quick_switch_count}  "
                        f"片头全色: {getattr(r, 'monochrome_preamble', False)}"
                    )
            _mode = "单色"
            if r.multicolor:
                _mode = "多色(84自动)" if getattr(r, "auto_nearest_84", False) else "多色(手选九格)"
            self._vec_lbl_stats.config(
                text=(
                    f"模式: {_mode}\n"
                    f"笔画数: {r.strokes}\n"
                    f"指令数: {len(r.cmds)}  (≈ {r.bytes_size} 字节 3×cmds)\n"
                    f"起点 HOME: 行 {r.home[0]} 列 {r.home[1]}{ord_line}"
                    f"{extra}\n"
                    f"注：每格=与固件相同的一格；NEAREST 放大，仅示意，以实机为准。"
                )
            )
            self._set_vector_status("编译 OK。可导出 draw_vector_data.h", error=False)
        except Exception as e:
            self._vector_result = None
            self._vector_preview_pil = None
            self._photo_vec = None
            self._vec_lbl_stats.config(text="")
            err = str(e)
            self._lbl_vec.configure(
                image="",
                text="编译失败，栅格无内容。\n\n" + err[:500],
                wraplength=420,
                justify=tk.LEFT,
                bg=VECTOR_PREVIEW_CHROME_DARK,
                fg="#e08080",
            )
            self._frame_vec_img.config(bg=VECTOR_PREVIEW_CHROME_DARK)
            self._set_vector_status(f"编译失败: {e}", error=True)
            messagebox.showerror("矢量编译", err)

    def _export_vector_header(self) -> None:
        if self._vector_result is None:
            messagebox.showwarning("导出", "请先成功编译矢量。")
            return
        r = self._vector_result
        if r.multicolor and not self._remap_confirm_dialog(r):
            self._set_vector_status("已取消导出（重映射未确认）", error=False)
            return
        default = _APP_DIR.parent.parent / "firmware" / "paint_vector_flash" / "draw_vector_data.h"
        path = filedialog.asksaveasfilename(
            title="保存 draw_vector_data.h",
            defaultextension=".h",
            initialfile=default.name,
            initialdir=str(default.parent) if default.parent.is_dir() else str(_APP_DIR),
            filetypes=[("C header", "*.h"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            write_draw_vector_header(
                r,
                path,
                source_note=self._svg_path or "gui_app",
            )
            msg_extra = ""
            p_h = Path(path)
            if r.multicolor:
                palp = self._palette_path.get().strip()
                if not palp or not os.path.isfile(palp):
                    raise ValueError("多色写 remap 需要有效色表路径 (palette JSON)")
                base = p_h.parent / p_h.stem
                rj = Path(str(base) + "_remap.json")
                write_remap_json(r, rj)
                msg_extra = f"\n{rj}"
                if r.emit_color_quick:
                    sm = Path(str(base) + "_vector_setup.md")
                    write_vector_setup_markdown(r, sm, palp)
                    msg_extra += f"\n{sm}"
            _vec_body = (
                f"已写入:\n{path}{msg_extra}\n\n"
                "覆盖后打开 firmware/paint_vector_flash/paint_vector_flash.ino 上传。\n"
                "进游戏前选好颜色。"
            )
            messagebox.showinfo("draw_vector_data.h", _vec_body)
            self._set_vector_status(f"已导出: {path}", error=False)
        except Exception as e:
            messagebox.showerror("导出失败", str(e))
            self._set_vector_status(str(e), error=True)


def main() -> None:
    root = tk.Tk()
    try:
        style = ttk.Style()
        if sys.platform == "win32":
            style.theme_use("vista")
    except tk.TclError:
        pass
    TexturePrepApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
