#!/usr/bin/env python3
"""
全色板切色链 — 规格验证用 GUI (Tkinter, 与固件/编译器独立).

键位: 方向键, y=开菜单/进全色, a/Enter=确认.

九槽在 12×7 上的**约定默认格**为人工口述的 1-based R/C(槽0=顶…8=底);
若 palette JSON 在对应格上采样的 RGB 与「应黑/应深蓝」等不符, 在窗口「九槽约定格
校验」区会对照, 需检查 ROI 或重取样; 实机进全色时, 本模拟从**当前槽绑定的
index 所在格**起跳(改色 A 后下次 Y 会落在新区)。
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path

# .../scripts/texture_prep/this.py -> 仓库根为 parent.parent.parent
_REPO = Path(__file__).resolve().parent.parent.parent
_SCR = Path(__file__).resolve().parent.parent
if str(_SCR) not in sys.path:
    sys.path.insert(0, str(_SCR))
from common import palette_defaults as _pd  # 九格 1-based R/C 与 gui/固件同源

_DEFAULT_JSON = _REPO / "assets" / "generated" / "palette_default.json"

ROWS, COLS = 7, 12

# 实机九快选默认格(1-based)与 common.palette_defaults; 下为仅模拟器用的格标签
_QUICK_LAB: tuple[str, ...] = (
    "C7R1 黑",  # 1-based 行7列1；非 R1C7(1,7)
    "R1C1 白",
    "R4C11 棕",
    "R4C10 红",
    "R4C9 黄",
    "R4C7 嫩绿",
    "R4C6 深绿",
    "R4C4 深蓝",
    "R4C2 紫",
)
# 与 _pd.QUICK_DEFAULT_CELLS_1BASED 同序；下标 0..83 来自色表 JSON，勿与「index=槽号 0..8」混淆
# (R1, C1) 1-based, label
QUICK_DEFAULT_CELLS_1BASED: tuple[tuple[int, int, str], ...] = tuple(
    (a, b, _QUICK_LAB[i]) for i, (a, b) in enumerate(_pd.QUICK_DEFAULT_CELLS_1BASED)
)

QUICK_DEFAULT_CELLS_0: list[tuple[int, int, str]] = [
    (r1 - 1, c1 - 1, lab) for r1, c1, lab in QUICK_DEFAULT_CELLS_1BASED
]


def _default_slot_palette_indices() -> list[int]:
    if not _DEFAULT_JSON.is_file():
        return [i for i in range(9)]
    try:
        return list(_pd.default_nine_indices_from_palette_path(_DEFAULT_JSON))
    except (OSError, ValueError, KeyError):
        return [i for i in range(9)]


class Mode(Enum):
    PAINT = auto()
    QUICK = auto()  # 9 槽
    FULL = auto()  # 12x7
    MII_HAIR = auto()  # 过渡: 同方向再按才落格
    MII_SKIN = auto()


@dataclass
class Sim:
    mode: Mode = Mode.PAINT
    paint_row: int = 128
    paint_col: int = 128
    # 9 槽各自绑定的 palette index 0..83（默认同固件 PALETTE_DEFAULT_NINE / palette_defaults）
    slot_palette_index: list[int] = field(default_factory=_default_slot_palette_indices)
    quick_index: int = 0
    # 开快选/确认后: 高亮以「当前选中的槽」为准(顶格=0 仅首次)
    active_slot: int = 0
    ever_a_from_quick: bool = False
    full_r: int = 0
    full_c: int = 0
    # 过渡: 同方向二键, 与进入时同向
    mii_stored_dir: str = ""  # "L" or "R"
    log_lines: list[str] = field(default_factory=list)
    # index -> (r,c) rgb; (r,c) -> index
    index_to_cell: dict[int, tuple[int, int, tuple[int, int, int]]] = field(
        default_factory=dict
    )
    cell_to_index: dict[tuple[int, int], int] = field(default_factory=dict)
    _palette_path: Path = field(default_factory=lambda: _DEFAULT_JSON)

    def log(self, msg: str) -> None:
        self.log_lines.append(msg)
        if len(self.log_lines) > 16:
            self.log_lines = self.log_lines[-16:]


def apply_quick_default_slot_indices(s: Sim) -> None:
    """用约定格 (row,col) 在 JSON 中的 index 填满 9 槽；用于默认/重载/重置。"""
    out: list[int] = []
    for r0, c0, _lab in QUICK_DEFAULT_CELLS_0:
        if (r0, c0) in s.cell_to_index:
            out.append(s.cell_to_index[(r0, c0)])
        else:
            s.log(f"缺格: 约定 ({r0},{c0}) 0-based 无 index, 槽用 0")
            out.append(0)
    s.slot_palette_index = out[:9]


def load_palette(path: Path) -> Sim:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    s = Sim()
    s._palette_path = path
    s.index_to_cell.clear()
    s.cell_to_index.clear()
    for c in data["colors"]:
        idx = int(c["index"])
        r, co = int(c["row"]), int(c["col"])
        rgb = tuple(c["rgb"])
        s.index_to_cell[idx] = (r, co, rgb)
        s.cell_to_index[(r, co)] = idx
    apply_quick_default_slot_indices(s)
    return s


def build_quick_verify_text(s: Sim) -> str:
    """供界面展示: 约定格、当前槽绑定 index 与采样 hex, 与约定格是否一致。"""
    lines: list[str] = [
        "【九槽默认格校验】约定 R/C 为 1-based(你口述); 下为 palette JSON 中该格的 index 与颜色。"
        " 若与记忆不符(如「应黑实浅」)说明 ROI/截图与实机有偏差, 需改色板或重新取样。"
    ]
    for k in range(9):
        r0, c0, _lab0 = QUICK_DEFAULT_CELLS_0[k]
        r1, c1_1b = r0 + 1, c0 + 1
        pidx = s.slot_palette_index[k]
        want_r, want_c = r0, c0
        if pidx not in s.index_to_cell:
            lines.append(
                f"  槽{k} 约定R{r1}C{c1_1b} 当前 index={pidx} (JSON 中无此 index)"
            )
            continue
        ar, ac, rgb = s.index_to_cell[pidx]
        hx = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
        if (ar, ac) == (want_r, want_c):
            mark = "格一致"
        else:
            mark = f"绑定在R{ar+1}C{ac+1} (与约定格R{r1}C{c1_1b} 不同, 常因全色A改过)"
        lines.append(
            f"  槽{k} 约定R{r1}C{c1_1b} → 采样 index {pidx}  {hx}  {mark}"
        )
    return "\n".join(lines)


def cell_to_index(s: Sim, r: int, c: int) -> int:
    return s.cell_to_index[(r, c)]


def full_move_up_down(s: Sim, dr: int) -> None:
    s.full_r = (s.full_r + dr) % ROWS
    s.log(f"全色: Up/Down loop → 格 ({s.full_r},{s.full_c})")


def full_left_right_loops_simplerow(s: Sim, r: int, c: int, d: int) -> tuple[int, int] | None:
    """0..2 行: 本行内左右 loop. d=-1 左, d=+1 右. 不触发 Mii."""
    c2 = (c + d) % COLS
    return r, c2


def full_normal_lr_row34(s: Sim, r: int, c: int, d: int) -> tuple[int, int] | None:
    """3..6 行 内部 1..10: 普通左右一格."""
    if d < 0 and c > 0:
        return r, c - 1
    if d > 0 and c < COLS - 1:
        return r, c + 1
    return None  # 边缘走 Mii 或特殊


def mii_hair_second_left(s: Sim) -> None:
    s.mode = Mode.FULL
    s.full_r, s.full_c = 4, 11  # 第五行(1-based) 最右, 0-based (4,11)
    s.log("Mii发 → 同向再左: 到 (4,11) 第五行最右")
    s.mii_stored_dir = ""


def mii_hair_second_right(s: Sim) -> None:
    s.mode = Mode.FULL
    s.full_r, s.full_c = 4, 0  # 第五行最左
    s.log("Mii发 → 同向再右: 到 (4,0) 第五行最左")
    s.mii_stored_dir = ""


def mii_skin_second_left(s: Sim) -> None:
    s.mode = Mode.FULL
    s.full_r, s.full_c = 6, 11  # 第七行最右
    s.log("Mii肤 → 同向再左: 到 (6,11) 第七行最右")
    s.mii_stored_dir = ""


def mii_skin_second_right(s: Sim) -> None:
    s.mode = Mode.FULL
    s.full_r, s.full_c = 6, 0
    s.log("Mii肤 → 同向再右: 到 (6,0) 第七行最左")
    s.mii_stored_dir = ""


def on_full_left(s: Sim) -> None:
    r, c = s.full_r, s.full_c
    if s.mode in (Mode.MII_HAIR, Mode.MII_SKIN):
        if s.mii_stored_dir == "L":
            if s.mode == Mode.MII_HAIR:
                mii_hair_second_left(s)
            else:
                mii_skin_second_left(s)
        else:
            s.log("Mii: 与进入方向不符, 取消过渡")
            s.mode = Mode.FULL
            s.mii_stored_dir = ""
        return
    if s.mode != Mode.FULL:
        return
    # 前三行: 行内 loop
    if r in (0, 1, 2):
        s.full_r, s.full_c = full_left_right_loops_simplerow(s, r, c, -1)  # type: ignore[assignment]
        s.log(f"全色 行0-2: 左 loop → ({s.full_r},{s.full_c})")
        return
    # 行 3..6, 最左: 进 Mii
    if c == 0 and r in (3, 4, 5):
        s.mode = Mode.MII_HAIR
        s.mii_stored_dir = "L"
        s.log("第4-6行(0-based 3-5) 最左+左: Mii 头发(同向再按)")
        return
    if c == 0 and r == 6:
        s.mode = Mode.MII_SKIN
        s.mii_stored_dir = "L"
        s.log("第7行(0-based6) 最左+左: Mii 肤色(同向再按)")
        return
    # 内部
    t = full_normal_lr_row34(s, r, c, -1)
    if t:
        s.full_r, s.full_c = t
        s.log(f"全色: 左 → ({s.full_r},{s.full_c})")


def on_full_right(s: Sim) -> None:
    r, c = s.full_r, s.full_c
    if s.mode in (Mode.MII_HAIR, Mode.MII_SKIN):
        if s.mii_stored_dir == "R":
            if s.mode == Mode.MII_HAIR:
                mii_hair_second_right(s)
            else:
                mii_skin_second_right(s)
        else:
            s.log("Mii: 与进入方向不符, 取消过渡")
            s.mode = Mode.FULL
            s.mii_stored_dir = ""
        return
    if s.mode != Mode.FULL:
        return
    if r in (0, 1, 2):
        s.full_r, s.full_c = full_left_right_loops_simplerow(s, r, c, 1)  # type: ignore[assignment]
        s.log(f"全色 行0-2: 右 loop → ({s.full_r},{s.full_c})")
        return
    if c == 11 and r in (3, 4, 5):
        s.mode = Mode.MII_HAIR
        s.mii_stored_dir = "R"
        s.log("第4-6行 最右+右: Mii 发(同向再按)")
        return
    if c == 11 and r == 6:
        s.mode = Mode.MII_SKIN
        s.mii_stored_dir = "R"
        s.log("第7行 最右+右: Mii 肤(同向再按)")
        return
    t = full_normal_lr_row34(s, r, c, 1)
    if t:
        s.full_r, s.full_c = t
        s.log(f"全色: 右 → ({s.full_r},{s.full_c})")


def on_full_up(s: Sim) -> None:
    if s.mode in (Mode.MII_HAIR, Mode.MII_SKIN):
        s.log("Mii 过渡中: 上下键可取消(规格未写, 此处取消+上移)")
        s.mode = Mode.FULL
        s.mii_stored_dir = ""
        full_move_up_down(s, -1)
        return
    if s.mode == Mode.FULL:
        full_move_up_down(s, -1)


def on_full_down(s: Sim) -> None:
    if s.mode in (Mode.MII_HAIR, Mode.MII_SKIN):
        s.log("Mii 过渡: 按 Down 取消+下移")
        s.mode = Mode.FULL
        s.mii_stored_dir = ""
        full_move_up_down(s, 1)
        return
    if s.mode == Mode.FULL:
        full_move_up_down(s, 1)


def on_y(s: Sim) -> None:
    if s.mode == Mode.PAINT:
        s.mode = Mode.QUICK
        if s.ever_a_from_quick:
            s.quick_index = s.active_slot
        else:
            s.quick_index = 0
        s.log(
            f"Y: 9 槽, 高亮=槽{s.quick_index} (从未A确认过=顶0, 否则=上次active)"
        )
        return
    if s.mode == Mode.QUICK:
        # 起点 = 该槽「当前」绑定的 0..83 在色板上的格; 全色A 改绑后, 下回进全色仍从该新 index 的格进
        idx = s.slot_palette_index[s.quick_index]
        if idx not in s.index_to_cell:
            s.log(f"槽绑定 index {idx} 无效")
            return
        r, co, _ = s.index_to_cell[idx]
        s.full_r, s.full_c = r, co
        s.mode = Mode.FULL
        s.mii_stored_dir = ""
        s.log(
            f"Y: 全色 12×7, 槽{s.quick_index} 绑定 index={idx} → 起点格 (row,col)=({r},{co}) 0-based"
        )
        return
    s.log("Y: 当前模式未处理")


def on_a(s: Sim) -> None:
    if s.mode == Mode.QUICK:
        s.active_slot = s.quick_index
        s.ever_a_from_quick = True
        s.mode = Mode.PAINT
        s.log(
            f"A: 回绘画, 座标不变 ({s.paint_row},{s.paint_col}), 记住槽 {s.active_slot}"
        )
        return
    if s.mode == Mode.FULL:
        pidx = cell_to_index(s, s.full_r, s.full_c)
        s.slot_palette_index[s.quick_index] = pidx
        s.active_slot = s.quick_index
        s.mode = Mode.QUICK
        s.log(
            f"A: 槽{s.quick_index} 覆盖为 index={pidx} (格 {s.full_r},{s.full_c}) → 回 9 槽"
        )
        return
    if s.mode in (Mode.MII_HAIR, Mode.MII_SKIN):
        s.log("A: 过渡中无效(实机: 不选头发)")
        return
    s.log("A: 绘画模式无操作")


def on_quick_up(s: Sim) -> None:
    if s.quick_index <= 0:
        s.log("快选: 顶再按上 → 翻车(无 loop)")
        return
    s.quick_index -= 1
    s.log(f"快选: 上 → 槽 {s.quick_index}")


def on_quick_down(s: Sim) -> None:
    if s.quick_index >= 8:
        s.log("快选: 底再按下 → 翻车(无 loop)")
        return
    s.quick_index += 1
    s.log(f"快选: 下 → 槽 {s.quick_index}")


# --- GUI ---

try:
    import tkinter as tk
    from tkinter import filedialog, ttk, messagebox
except ImportError as e:  # pragma: no cover
    raise SystemExit("需要 tkinter") from e


def run_gui() -> None:
    p = _DEFAULT_JSON
    if not p.is_file():
        p = Path.cwd() / "assets" / "generated" / "palette_default.json"
    sim = load_palette(p)

    root = tk.Tk()
    root.title("全色板切色链 验证 (规格模拟)")
    root.minsize(900, 560)

    top = ttk.Frame(root, padding=6)
    top.pack(fill=tk.X)
    ttk.Label(top, text="Palette JSON:").pack(side=tk.LEFT)
    pal_var = tk.StringVar(value=str(p))
    ttk.Entry(top, textvariable=pal_var, width=50).pack(side=tk.LEFT, padx=4)
    ttk.Label(
        top,
        text="键: y=菜单, a/Enter=确认, 方向=导航",
    ).pack(side=tk.LEFT, padx=8)

    info = ttk.LabelFrame(root, text="状态", padding=6)
    info.pack(fill=tk.X, padx=6, pady=2)
    lbl_state = ttk.Label(info, text="")
    lbl_state.pack(anchor=tk.W)

    verify_fr = ttk.LabelFrame(
        root, text="九槽约定格(1-based R/C) 与当前绑定校验", padding=4
    )
    verify_fr.pack(fill=tk.X, padx=6, pady=2)
    lbl_verify = ttk.Label(
        verify_fr,
        text=build_quick_verify_text(sim),
        font=("Consolas", 8),
        wraplength=900,
    )
    lbl_verify.pack(anchor=tk.W)

    slot_fr = ttk.LabelFrame(
        root, text="9 槽 palette index (0-83) — 与主工程多色九槽同义", padding=4
    )
    slot_fr.pack(fill=tk.X, padx=6, pady=2)
    svars: list[tk.IntVar] = []
    for r in range(3):
        rowf = ttk.Frame(slot_fr)
        rowf.pack(fill=tk.X)
        for c in range(3):
            k = r * 3 + c
            ttk.Label(rowf, text=f"槽{k}:").pack(side=tk.LEFT, padx=2)
            v = tk.IntVar(value=sim.slot_palette_index[k])
            svars.append(v)
            ttk.Spinbox(rowf, from_=0, to=83, textvariable=v, width=4).pack(
                side=tk.LEFT, padx=1
            )

    mid = ttk.Panedwindow(root, orient=tk.HORIZONTAL)
    mid.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
    leftf = ttk.LabelFrame(mid, text="全色 12×7 (行0-6, 列0-11)", padding=2)
    rightf = ttk.LabelFrame(mid, text="9 槽快选(0=顶) + 日志", padding=2)
    mid.add(leftf, weight=3)
    mid.add(rightf, weight=1)
    cnv_full = tk.Canvas(
        leftf,
        width=12 * 20,
        height=7 * 20,
        highlightthickness=0,
        bg="#1a1a22",
    )
    cnv_full.pack(fill=tk.BOTH, expand=True)
    rq = ttk.Frame(rightf)
    rq.pack(fill=tk.X)
    cnv_quick = tk.Canvas(
        rq, width=50, height=9 * 26, highlightthickness=0, bg="#1a1a22"
    )
    cnv_quick.pack(side=tk.LEFT, fill=tk.Y)
    log_w = tk.Text(rightf, height=12, width=40, font=("Consolas", 9))
    log_w.pack(fill=tk.BOTH, expand=True, pady=4)
    ttk.Separator(root).pack(fill=tk.X, pady=2)
    bar = ttk.Frame(root, padding=4)
    bar.pack(fill=tk.X)

    def read_slots_from_ui() -> None:
        for i in range(9):
            x = int(svars[i].get())
            sim.slot_palette_index[i] = max(0, min(83, x))

    # 批量 .set( Spin ) 时禁止 trace, 避免「只改了一个框就 redraw」用旧 8 个框覆盖 sim
    _syncing_from_sim: bool = False

    def sync_spins_from_sim() -> None:
        nonlocal _syncing_from_sim
        _syncing_from_sim = True
        try:
            for i in range(9):
                svars[i].set(sim.slot_palette_index[i])
        finally:
            _syncing_from_sim = False
        paint_ui()

    def paint_ui() -> None:
        """只根据 sim 重绘, 不 read_slots(避免用旧 Spin 覆盖全色A 等刚写入的槽)."""
        m = sim.mode
        mtxt = (
            f"模式: {m.name}  绘画:({sim.paint_row},{sim.paint_col})  "
            f"active槽: {sim.active_slot}"
        )
        if m == Mode.QUICK:
            mtxt += f"  快选高亮: 槽{sim.quick_index}"
        if m in (Mode.FULL, Mode.MII_HAIR, Mode.MII_SKIN):
            mii = (
                f"  [Mii 过渡 dir={sim.mii_stored_dir!r}]"
                if m in (Mode.MII_HAIR, Mode.MII_SKIN)
                else ""
            )
            ix = sim.cell_to_index.get((sim.full_r, sim.full_c), -1)
            mtxt += f"  全色格: ({sim.full_r},{sim.full_c})  index={ix}{mii}"
        lbl_state.config(text=mtxt)
        cnv_full.delete("all")
        cnv_quick.delete("all")
        cell = 20
        for rr in range(ROWS):
            for cc in range(COLS):
                x1, y1 = cc * cell, rr * cell
                tidx = sim.cell_to_index.get((rr, cc))
                if tidx is not None and tidx in sim.index_to_cell:
                    r_, g, b3 = sim.index_to_cell[tidx][2]
                    fill = f"#{r_:02x}{g:02x}{b3:02x}"
                else:
                    fill = "#2a2a32"
                cnv_full.create_rectangle(
                    x1, y1, x1 + cell - 1, y1 + cell - 1, fill=fill, outline="#444"
                )
        if sim.mode in (Mode.FULL, Mode.MII_HAIR, Mode.MII_SKIN):
            fr, fco = sim.full_r, sim.full_c
            x1, y1 = fco * cell, fr * cell
            cnv_full.create_rectangle(
                x1 - 1, y1 - 1, x1 + cell, y1 + cell, outline="yellow", width=2
            )
        qw, qh = 32, 22
        for k in range(9):
            ty = k * (qh + 2)
            pidx = sim.slot_palette_index[k]
            if pidx in sim.index_to_cell:
                r_, g, b3 = sim.index_to_cell[pidx][2]
                bg2 = f"#{r_:02x}{g:02x}{b3:02x}"
            else:
                bg2 = "#444"
            cnv_quick.create_rectangle(
                2, 2 + ty, 2 + qw, 2 + ty + qh, fill=bg2, outline="#666"
            )
            cnv_quick.create_text(
                4 + qw // 2,
                2 + ty + qh // 2,
                text=str(k),
                fill="white" if (k == sim.quick_index and sim.mode == Mode.QUICK) else "#ccc",
            )
        if sim.mode == Mode.QUICK:
            ky = sim.quick_index * (qh + 2)
            cnv_quick.create_rectangle(
                0, ky, 4 + qw + 2, ky + qh + 4, outline="yellow", width=2
            )
        lbl_verify.config(text=build_quick_verify_text(sim))
        log_w.delete(1.0, tk.END)
        log_w.insert(tk.END, "\n".join(sim.log_lines))

    def redraw_all() -> None:
        """从 Spin 读入 sim(用户改框) 后重绘. 全色/键盘 逻辑应用 sync_spins+paint_ui."""
        read_slots_from_ui()
        paint_ui()

    def reload_palette() -> None:
        nonlocal sim
        try:
            sim = load_palette(Path(pal_var.get()))
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("错误", str(e))
            return
        sim.log("已重载 JSON, 9 槽已按约定格重置为当前文件中的 index")
        sync_spins_from_sim()

    def reset_sim() -> None:
        sim.mode = Mode.PAINT
        apply_quick_default_slot_indices(sim)
        sim.quick_index = 0
        sim.active_slot = 0
        sim.ever_a_from_quick = False
        sim.full_r = 0
        sim.full_c = 0
        sim.mii_stored_dir = ""
        sim.log_lines = []
        sim.log("重置: 9 槽=约定 R/C 在 JSON 上对应的 index(见上表), active=0")
        sync_spins_from_sim()

    def browse_json() -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            initialdir=str(_REPO / "assets" / "generated"),
        )
        if path:
            pal_var.set(path)
            reload_palette()

    ttk.Button(bar, text="浏览…", command=browse_json).pack(side=tk.LEFT, padx=2)
    ttk.Button(bar, text="重载 JSON", command=reload_palette).pack(side=tk.LEFT, padx=2)
    ttk.Button(bar, text="重置状态", command=reset_sim).pack(side=tk.LEFT, padx=2)

    def on_spin_write(*_args: object) -> None:
        if _syncing_from_sim:
            return
        read_slots_from_ui()
        paint_ui()

    for v in svars:
        v.trace_add("write", on_spin_write)

    def on_key(e: tk.Event) -> str | None:
        keys = e.keysym
        read_slots_from_ui()
        if keys in ("y", "Y"):
            on_y(sim)
        elif keys in ("a", "A", "Return"):
            on_a(sim)
        elif sim.mode == Mode.PAINT:
            sim.log(f"键 {keys}: 绘画中仅 y 开快选(无空跑移动)")
        elif sim.mode == Mode.QUICK:
            if keys == "Up":
                on_quick_up(sim)
            elif keys == "Down":
                on_quick_down(sim)
            else:
                sim.log(f"快选: {keys} 未用")
        elif sim.mode in (Mode.FULL, Mode.MII_HAIR, Mode.MII_SKIN):
            if keys == "Up":
                on_full_up(sim)
            elif keys == "Down":
                on_full_down(sim)
            elif keys == "Left":
                on_full_left(sim)
            elif keys == "Right":
                on_full_right(sim)
            else:
                sim.log(f"全色: {keys} 未用")
        else:
            sim.log("?")
        # 由 sim 推 Spin(抑制 trace) 再仅 paint, 避免 trace+read_slots 用旧 8 格覆盖新槽
        sync_spins_from_sim()
        return "break"

    for key in (
        "y",
        "Y",
        "a",
        "A",
        "Return",
        "Up",
        "Down",
        "Left",
        "Right",
    ):
        root.bind(f"<{key}>", on_key)

    sim.log("起動: 按 y 进入 9 槽")
    paint_ui()
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print("用法: python palette_chain_sim.py")
        sys.exit(0)
    run_gui()