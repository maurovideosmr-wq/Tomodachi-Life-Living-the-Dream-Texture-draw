"""
全色 12x7 格上 BFS(与固件已删的 full_palette_bfs.c 同构, 行序与 sim 同).
仅在上位机生成 draw_vector 时使用; 方向 0=Up,1=Right,2=Down,3=Left.
与 C 的 enc/step/BFS/回溯 对齐; 最短路长若 >200(原固件 bfsb 上界)则抛错.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

ROWS, COLS = 7, 12
N_STATES = 756
M_MAX = 3
M_NONE, M_HAIR, M_SKIN = 0, 1, 2
D_NONE, D_L, D_R = 0, 1, 2
MAX_HATS_OUT = 200


@dataclass
class S:
    r: int
    c: int
    m: int
    d: int


def enc(s: S) -> int:
    return s.r + 7 * (s.c + 12 * (s.m + M_MAX * s.d))


def f_loop012(a: S, direction: int, b: S) -> None:
    r, c = a.r, a.c
    if r > 2:
        return
    if direction < 0:
        c = (c + 11) % COLS
    else:
        c = (c + 1) % COLS
    b.r, b.c, b.m, b.d = r, c, M_NONE, D_NONE


def f_norm_lr(direction: int, b: S) -> None:
    c = b.c
    if direction < 0:
        if c == 0:
            return
        b.c = c - 1
    else:
        if c == 11:
            return
        b.c = c + 1
    b.m, b.d = M_NONE, D_NONE


def f_ud(drw: int, b: S) -> None:
    b.r = (b.r + (ROWS + drw)) % ROWS
    b.m, b.d = M_NONE, D_NONE


def mii2_hL(s: S) -> None:
    s.m, s.d, s.r, s.c = M_NONE, D_NONE, 4, 11


def mii2_hR(s: S) -> None:
    s.m, s.d, s.r, s.c = M_NONE, D_NONE, 4, 0


def mii2_sL(s: S) -> None:
    s.m, s.d, s.r, s.c = M_NONE, D_NONE, 6, 11


def mii2_sR(s: S) -> None:
    s.m, s.d, s.r, s.c = M_NONE, D_NONE, 6, 0


def step_inplace(s: S, mov: int) -> bool:
    """与 C `step(S* s, uint8_t mov)` 一致; 行首 n=*s, f_loop 读 *s, 写 b(n)。"""
    n = S(s.r, s.c, s.m, s.d)  # C 行首 n=*s(若未在 HAIR/SKIN return, 下块仍用此初值)
    if n.m == M_HAIR:
        if mov == 0:
            f_ud(-1, n)
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        if mov == 2:
            f_ud(1, n)
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        if n.d == D_L:
            if mov == 3:
                mii2_hL(n)
                s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
                return True
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        if n.d == D_R:
            if mov == 1:
                mii2_hR(n)
                s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
                return True
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        return False
    if n.m == M_SKIN:
        if mov == 0:
            f_ud(-1, n)
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        if mov == 2:
            f_ud(1, n)
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        if n.d == D_L:
            if mov == 3:
                mii2_sL(n)
                s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
                return True
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        if n.d == D_R:
            if mov == 1:
                mii2_sR(n)
                s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
                return True
            n.m, n.d = M_NONE, D_NONE
            s.r, s.c, s.m, s.d = n.r, n.c, n.m, n.d
            return True
        return False
    # M_NONE: 与 C 行 70-91 同; n 为进入 step 时 *s 的拷贝, f_loop 读 *s 的 r/c
    r, c = n.r, n.c
    a_read = s  # 读侧与 C 的 *s, 在写回 s 前未变
    if mov == 0:
        t = S(a_read.r, a_read.c, a_read.m, a_read.d)
        f_ud(-1, t)
        s.r, s.c, s.m, s.d = t.r, t.c, t.m, t.d
        return True
    if mov == 2:
        t = S(a_read.r, a_read.c, a_read.m, a_read.d)
        f_ud(1, t)
        s.r, s.c, s.m, s.d = t.r, t.c, t.m, t.d
        return True
    if mov == 3:
        if r < 3:
            t = S(0, 0, 0, 0)
            f_loop012(S(a_read.r, a_read.c, a_read.m, a_read.d), -1, t)
            s.r, s.c, s.m, s.d = t.r, t.c, t.m, t.d
            return True
        if c == 0:
            if r in (3, 4, 5):
                s.r, s.c, s.m, s.d = a_read.r, a_read.c, M_HAIR, D_L
                return True
            if r == 6:
                s.r, s.c, s.m, s.d = a_read.r, a_read.c, M_SKIN, D_L
                return True
            return False
        n2 = S(a_read.r, a_read.c, a_read.m, a_read.d)
        f_norm_lr(-1, n2)
        s.r, s.c, s.m, s.d = n2.r, n2.c, n2.m, n2.d
        return True
    if mov == 1:
        if r < 3:
            t = S(0, 0, 0, 0)
            f_loop012(S(a_read.r, a_read.c, a_read.m, a_read.d), 1, t)
            s.r, s.c, s.m, s.d = t.r, t.c, t.m, t.d
            return True
        if c == 11:
            if r in (3, 4, 5):
                s.r, s.c, s.m, s.d = a_read.r, a_read.c, M_HAIR, D_R
                return True
            if r == 6:
                s.r, s.c, s.m, s.d = a_read.r, a_read.c, M_SKIN, D_R
                return True
            return False
        n2 = S(a_read.r, a_read.c, a_read.m, a_read.d)
        f_norm_lr(1, n2)
        s.r, s.c, s.m, s.d = n2.r, n2.c, n2.m, n2.d
        return True
    return False


def _dec(k: int) -> S:
    t = k
    r = t % 7
    t //= 7
    c = t % 12
    t //= 12
    m0 = t % 3
    d0 = t // 3
    return S(r, c, m0, d0 % 3)


def _find_step_parent_to_child(parent: S, child: S) -> int:
    for m in range(4):
        t = S(parent.r, parent.c, parent.m, parent.d)
        if step_inplace(t, m) and enc(t) == enc(child):
            return m
    return 0xFF


Q_MAX = 400


def full_palette_bfs_hats(
    sr: int, sc: int, tr: int, tc: int, max_len: int = MAX_HATS_OUT
) -> list[int]:
    start = S(sr, sc, M_NONE, D_NONE)
    goal = S(tr, tc, M_NONE, D_NONE)
    se, ge = enc(start), enc(goal)
    if se >= N_STATES or ge >= N_STATES:
        raise ValueError("enc range")
    if se == ge:
        return []
    parent: list[int | None] = [None] * N_STATES
    vis = [False] * N_STATES
    q: deque[int] = deque()
    q.append(se)
    vis[se] = True
    parent[se] = se
    got: int | None = None
    gk = ge
    n_enq = 1  # 与 C q[0]=se, qr=1: 总入队次数上界 400

    while q:
        qk = q.popleft()
        curn = _dec(qk)
        if curn.m == M_NONE and curn.r == tr and curn.c == tc:
            got = enc(curn)
            gk = got
            break
        for mv in range(4):
            t = S(curn.r, curn.c, curn.m, curn.d)
            if not step_inplace(t, mv):
                continue
            k2 = enc(t)
            if k2 >= N_STATES or vis[k2]:
                continue
            if n_enq >= Q_MAX:
                raise ValueError("全色 BFS 队满(与 C Q_MAX=400 一致), 与固件/JSON 检查")
            vis[k2] = True
            parent[k2] = qk
            q.append(k2)
            n_enq += 1
    if got is None:
        raise ValueError(f"全色 BFS 无路: ({sr},{sc}) -> ({tr},{tc})")

    rbuf: list[int] = []
    at = gk
    se_int = se
    while at != se_int:
        child = _dec(at)
        pk = parent[at]
        if pk is None:
            raise RuntimeError("bfs parent")
        par = _dec(pk)
        m = _find_step_parent_to_child(par, child)
        if m == 0xFF:
            raise RuntimeError("bfs 回溯 m 不合法")
        rbuf.append(m)
        at = pk
    rbuf.reverse()
    if len(rbuf) > max_len:
        raise ValueError(
            f"全色最短路长 {len(rbuf)} 超过 {max_len} (原固件 runFullBind bfsb 上界), 需放宽或分图"
        )
    return rbuf
