#!/usr/bin/env python3
"""Tkinter GUI: Tab1 位图 256×256 / 84 色；Tab2 矢量 SVG → draw_vector_data.h（单色线稿）。"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

_APP_DIR = Path(__file__).resolve().parent
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from mono_draw_export import write_draw_mask_header
from svg_compiler import (
    CompileResult,
    compile_svg,
    render_strokes_preview,
    write_draw_vector_header,
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
        self._photo_vec: ImageTk.PhotoImage | None = None
        self._vec_samples = tk.DoubleVar(value=2.0)

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
        info = ttk.LabelFrame(parent, text="说明（单色线稿）", padding=6)
        info.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(
            info,
            text="与位图单色相同：在主机上先选一种颜色再进贴图绘制；本页只生成线稿指令，不切调色板。",
            wraplength=820,
        ).pack(anchor=tk.W)
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
        _pbg = "#1e1e26"
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
        self._vector_status.config(text=text, foreground=("red" if error else ""))

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
                bg="#1e1e26",
                fg="#b0b0c0",
            )
            self._vec_lbl_stats.config(text="")
            return
        try:
            self._vector_result = compile_svg(
                self._svg_path,
                samples_per_len=float(self._vec_samples.get()),
            )
            r = self._vector_result
            im = render_strokes_preview(
                r.ordered_strokes,
                scale=2,
                grid=256,
                max_preview_points=0,
            )
            self._vector_preview_pil = im
            w, h = im.size
            # 须用浮点：`PREVIEW_MAX // max(w,h)` 在 512 侧长时为 0，会得到 1×1 缩略图
            mside = max(w, h) if w and h else 0
            sc = min(PREVIEW_MAX / float(mside), 1.0) if mside else 1.0
            if sc < 1.0:
                nw, nh = max(1, int(round(w * sc))), max(1, int(round(h * sc)))
                im = im.resize((nw, nh), Image.Resampling.NEAREST)
            if max(im.size) > 600:
                im = im.copy()
                im.thumbnail((600, 600), Image.Resampling.NEAREST)
            _vbg = "#1e1e26"
            self._photo_vec = ImageTk.PhotoImage(im)
            self._lbl_vec.configure(
                image=self._photo_vec,
                text="",
                bg=_vbg,
                highlightthickness=0,
            )
            self._vec_lbl_stats.config(
                text=(
                    f"笔画数: {r.strokes}\n"
                    f"指令数: {len(r.cmds)}  (≈ {r.bytes_size} 字节 3×cmds)\n"
                    f"起点 HOME: 行 {r.home[0]} 列 {r.home[1]}\n"
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
                bg="#1e1e26",
                fg="#e08080",
            )
            self._set_vector_status(f"编译失败: {e}", error=True)
            messagebox.showerror("矢量编译", err)

    def _export_vector_header(self) -> None:
        if self._vector_result is None:
            messagebox.showwarning("导出", "请先成功「刷新/编译」。")
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
                self._vector_result,
                path,
                source_note=self._svg_path or "gui_app",
            )
            messagebox.showinfo(
                "draw_vector_data.h",
                f"已写入:\n{path}\n\n覆盖同目录后打开 "
                f"firmware/paint_vector_flash/paint_vector_flash.ino 上传。进游戏前选好颜色。",
            )
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
