"""Parse SVG presentation attributes for stroke/fill color -> sRGB (0..255)."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from PIL import ImageColor

def _strip_ns_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


# Illustrator 等导出：颜色在 <defs><style> 的 `.st0 { fill: #… }` + `class="st0"`，
# 无内联 fill/stroke。此处解析 style 块中类选择器，用于 path_effective_line_rgb。
def build_class_style_map(root: ET.Element) -> dict[str, dict[str, str]]:
    """
    class 名(无点) -> { "fill"?: str, "stroke"?: str }，来自文档内 <style> 文本。
    """
    out: dict[str, dict[str, str]] = {}
    for el in root.iter():
        if _strip_ns_tag(el.tag).lower() != "style":
            continue
        text = (el.text or "")
        for m in re.finditer(r"\.([a-zA-Z0-9_-]+)\s*\{([^}]*)\}", text, re.DOTALL):
            cls, body = m.group(1), m.group(2)
            decl = _parse_style(body)
            slot = out.setdefault(cls, {})
            for k in ("fill", "stroke"):
                v = decl.get(k)
                if v and str(v).strip().lower() not in ("inherit", "none", "transparent", ""):
                    slot[k] = v.strip()
    return out


_CLASS_STYLE_MEMO: dict[int, dict[str, dict[str, str]]] = {}


def _get_class_style_map(root: ET.Element) -> dict[str, dict[str, str]]:
    k = id(root)
    if k not in _CLASS_STYLE_MEMO:
        _CLASS_STYLE_MEMO[k] = build_class_style_map(root)
    return _CLASS_STYLE_MEMO[k]


def _class_tokens_deepest_first(
    el: ET.Element, pmap: dict[int, ET.Element | None]
) -> list[str]:
    """自当前元素起沿父链向上，合并各结点的 `class`（去重保序，子在前）。"""
    toks: list[str] = []
    cur: ET.Element | None = el
    while cur is not None:
        for t in (cur.get("class") or "").split():
            t = t.strip()
            if t and t not in toks:
                toks.append(t)
        cur = pmap.get(id(cur))
    return toks


def _build_parent_map(root: ET.Element) -> dict[int, ET.Element | None]:
    m: dict[int, ET.Element | None] = {}
    for p in root.iter():
        for ch in p:
            m[id(ch)] = p
    return m


def _parse_style(style: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in style.split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        k, _, v = part.partition(":")
        out[k.strip().lower()] = v.strip()
    return out


def _color_from_css_value(val: str) -> tuple[int, int, int] | None:
    s = val.strip()
    if not s or s.lower() in ("none", "transparent"):
        return None
    try:
        c = ImageColor.getrgb(s)
    except ValueError:
        return None
    if len(c) == 4:
        return (c[0], c[1], c[2])
    return (c[0], c[1], c[2])


def _pick_inherit(
    el: ET.Element, key: str, pmap: dict[int, ET.Element | None]
) -> str | None:
    cur: ET.Element | None = el
    while cur is not None:
        v = cur.get(key)
        if v is not None and str(v).strip().lower() != "inherit":
            return str(v).strip()
        st = cur.get("style")
        if st:
            d = _parse_style(st)
            sub = d.get(key.lower())
            if sub and sub.lower() != "inherit":
                return sub
        cur = pmap.get(id(cur)) if cur is not None else None
    return None


def resolve_stroke_and_fill_rgb(
    el: ET.Element,
    root: ET.Element,
) -> tuple[tuple[int, int, int] | None, tuple[int, int, int] | None]:
    """
    同时解析 stroke / fill 的 sRGB。若只关心线稿用色，请用 path_effective_line_rgb()（先描边、无则填充）。
    `none` / `transparent` -> None.
    """
    pmap = _build_parent_map(root)
    stroke_s = _pick_inherit(el, "stroke", pmap)
    fill_s = _pick_inherit(el, "fill", pmap)
    stroke_rgb = _color_from_css_value(stroke_s) if stroke_s else None
    fill_rgb = _color_from_css_value(fill_s) if fill_s else None
    return stroke_rgb, fill_rgb


def path_effective_line_rgb(el: ET.Element, root: ET.Element) -> tuple[int, int, int] | None:
    """
    多色/线稿用色：1) 继承链上 stroke，2) 继承链上 fill/行内 style，
    3) 文档内 <style> 中对应 `class` 的 stroke 与 fill；`class` 可写在父级
    <g> 上（自当前元素到根合并，子结点类名优先）。
    若仍无，返回 None，由调用方回退为 #000 等。
    """
    pmap = _build_parent_map(root)
    s_stroke = _pick_inherit(el, "stroke", pmap)
    if s_stroke:
        stroke_rgb = _color_from_css_value(s_stroke)
        if stroke_rgb is not None:
            return stroke_rgb
    s_fill = _pick_inherit(el, "fill", pmap)
    if s_fill:
        fill_rgb = _color_from_css_value(s_fill)
        if fill_rgb is not None:
            return fill_rgb

    clmap = _get_class_style_map(root)
    class_tokens = _class_tokens_deepest_first(el, pmap)
    for c in class_tokens:
        decl = clmap.get(c) or {}
        s_css = decl.get("stroke")
        if s_css:
            stroke_rgb = _color_from_css_value(s_css)
            if stroke_rgb is not None:
                return stroke_rgb
    for c in class_tokens:
        decl = clmap.get(c) or {}
        s_css = decl.get("fill")
        if s_css:
            fill_rgb = _color_from_css_value(s_css)
            if fill_rgb is not None:
                return fill_rgb
    return None
