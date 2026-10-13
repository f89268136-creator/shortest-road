"""
GUI 界面模块 —— 主界面与交互

基于 Tkinter 自绘控件实现百度地图风格界面：
  · CityPicker/RoundBtn/Pill/Card/SegBar 等自绘控件（可搜索下拉框、按钮、卡片、分段选择）
  · 地图画布：路网绘制、路线高亮、途经点编号标记、起终点标记、缩放/平移/
             悬停查看（悬停拾取由核心算法模块的均匀网格空间索引加速）
  · 路线查询：最短路径（A* 启发式，附 A*/Dijkstra 扩展对比）、最少经停（BFS）、
             最省钱（过路费权重 Dijkstra），支持多个途经点逐段计算并按顺序串联、
             备选路线（Yen K 短路）与途经点智能排序（单源最短路代价矩阵 + 回溯剪枝）
  · 城市名索引与下拉候选过滤由二叉搜索树（BST）完成：精确查找 O(log n)、
             前缀检索 O(log n + k)（前缀命中优先展示，其余走子串匹配兜底）
  · 最省钱公路网（Prim 最小生成树）与路网邻接结构查看
  · 道路编辑：按起点/终点拉取百度真实数据新增道路（新城市自动定位），或删除道路；
             每次编辑写入操作记录并由双栈历史管理，支持撤销/重做（含缓存同步回退）
  · 真实路网导入的进度展示，导入完成后写入本地缓存
"""

import ctypes
import threading

import tkinter as tk
from tkinter import messagebox, simpledialog
from tkinter import font as tkfont

from basic_data import network
from basic_data.data import (CITIES, ROADS, ROUTE_POINTS, ROUTE_CURVES,
                             CITY_NAMES, ROAD_PAIRS, AK_PLACEHOLDER,
                             contains)
from core_algorithms.algorithms import (dijkstra, astar, k_shortest_paths,
                                        best_via_order, bfs_min_stops, prim_mst,
                                        estimate_time, via_cost_matrix)
from core_algorithms import geometry as geo
from data_structures import structures

YH = "Microsoft YaHei"
OUTER = "#eef2f7"
CARD = "#ffffff"
BORDER = "#e3e9f2"
TXT = "#1f2a37"
TXT2 = "#5b6b7f"
TXT3 = "#8a97a8"
BLUE = "#2f7bff"
BLUE_D = "#1f6ce0"
GREEN = "#0f8a4d"
GREEN2 = "#1aa260"
GOLD = "#ca8a04"
VIOLET = "#8b5cf6"
MAP_BG = "#f4f7fb"
ROAD_C = "#f9a95a"
START_NAVY = "#22334d"
END_RED = "#f0392f"


def _rounded(c, x0, y0, x1, y1, r, **kw):
    if x1 < x0:
        x0, x1 = x1, x0
    if y1 < y0:
        y0, y1 = y1, y0
    r = min(r, (x1 - x0) / 2.0, (y1 - y0) / 2.0)
    if r < 1:
        r = 1
    pts = (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0)
    return c.create_polygon(pts, smooth=True, **kw)


def _car_icon(c, x, y, tags=()):
    c.create_polygon(x - 5.5, y - 6.5, x + 5.5, y - 6.5, x + 8.0, y - 2.0, x - 8.0, y - 2.0,
                     fill="#5b6b82", outline="", tags=tags)
    _rounded(c, x - 9.5, y - 2.5, x + 9.5, y + 4.5, 3, fill="#43506a", outline="", tags=tags)
    c.create_oval(x - 6.5, y + 1.5, x - 2.5, y + 5.5, fill="#232b36",
                  outline="#ffffff", width=1, tags=tags)
    c.create_oval(x + 2.5, y + 1.5, x + 6.5, y + 5.5, fill="#232b36",
                  outline="#ffffff", width=1, tags=tags)


class RoundBtn(tk.Canvas):
    def __init__(self, parent, glyph, command, size=30, bg=OUTER,
                 fill="#ffffff", fg=TXT2, border="#d9e1ec"):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self._size = size
        self._glyph = glyph
        self._cmd = command
        self._fill = fill
        self._fg = fg
        self._bd = border
        self._hover = False
        self.configure(cursor="hand2")
        self.bind("<Button-1>", lambda e: self._cmd())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self._draw()

    def _enter(self, event):
        self._hover = True
        self._draw()

    def _leave(self, event):
        self._hover = False
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self._size
        fill = "#e8f1fe" if self._hover else self._fill
        self.create_oval(1, 1, s - 1, s - 1, fill=fill, outline=self._bd, width=1)
        self.create_text(s / 2.0, s / 2.0 + 1, text=self._glyph, fill=self._fg,
                         font=(YH, 9, "bold"))


class Pill(tk.Canvas):
    KINDS = {
        "primary": (BLUE, "#ffffff", BLUE, BLUE_D),
        "green": (GREEN2, "#ffffff", GREEN2, GREEN),
        "violet": (VIOLET, "#ffffff", VIOLET, "#7c4ce0"),
        "gold": (GOLD, "#ffffff", GOLD, "#b07a03"),
        "outline": ("#ffffff", "#41506a", "#d9e1ec", "#f3f7fc"),
    }

    def __init__(self, parent, text, command, width=140, height=32, kind="outline",
                 bg=CARD, font_size=9):
        super().__init__(parent, width=width, height=height, bg=bg, highlightthickness=0)
        self._text = text
        self._cmd = command
        self._kind = kind
        self._font_size = font_size
        self._hover = False
        self.configure(cursor="hand2")
        self.bind("<Button-1>", lambda e: self._cmd())
        self.bind("<Enter>", self._enter)
        self.bind("<Leave>", self._leave)
        self.bind("<Configure>", lambda e: self._draw())
        self._draw()

    def _enter(self, event):
        self._hover = True
        self._draw()

    def _leave(self, event):
        self._hover = False
        self._draw()

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 1:
            w = int(self["width"])
        if h <= 1:
            h = int(self["height"])
        fill, fg, bd, hov = Pill.KINDS.get(self._kind, Pill.KINDS["outline"])
        r = (h - 2) / 2.0
        _rounded(self, 1, 1, w - 1, h - 1, r,
                 fill=hov if self._hover else fill, outline=bd, width=1)
        self.create_text(w / 2.0, h / 2.0 + 0.5, text=self._text, fill=fg,
                         font=(YH, self._font_size, "bold" if self._kind != "outline" else "normal"))


class SegBar(tk.Canvas):
    def __init__(self, parent, items, command, height=36, bg=CARD):
        super().__init__(parent, bg=bg, highlightthickness=0, height=height)
        self.items = items
        self.command = command
        self.active = items[0][0]
        self._hover_i = -1
        self.configure(cursor="hand2")
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._click)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", lambda e: self._set_hover(-1))
        self._draw()

    def set_active(self, key):
        if key != self.active:
            self.active = key
            self._draw()

    def _index_at(self, x):
        w = max(1, self.winfo_width())
        n = len(self.items)
        gap = 6
        seg = (w - 4 - gap * (n - 1)) / float(n)
        if seg <= 1:
            return -1
        i = int((x - 2) // (seg + gap))
        if i < 0 or i >= n:
            return -1
        x0 = 2 + i * (seg + gap)
        if x > x0 + seg:
            return -1
        return i

    def _set_hover(self, i):
        if i != self._hover_i:
            self._hover_i = i
            self._draw()

    def _motion(self, event):
        self._set_hover(self._index_at(event.x))

    def _click(self, event):
        i = self._index_at(event.x)
        if i < 0:
            return
        key = self.items[i][0]
        self.set_active(key)
        self.command(key)

    def _draw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        n = len(self.items)
        gap = 6
        seg = (w - 4 - gap * (n - 1)) / float(n)
        if seg <= 1:
            return
        for i in range(n):
            key, label = self.items[i]
            x0 = 2 + i * (seg + gap)
            x1 = x0 + seg
            if key == self.active:
                fill, fg, bd = BLUE, "#ffffff", BLUE
                bold = "bold"
            elif i == self._hover_i:
                fill, fg, bd = "#eaf2ff", BLUE, "#c9dcff"
                bold = "normal"
            else:
                fill, fg, bd = "#ffffff", "#41506a", "#d9e1ec"
                bold = "normal"
            _rounded(self, x0, 1, x1, h - 1, (h - 2) / 2.0,
                     fill=fill, outline=bd, width=1)
            self.create_text((x0 + x1) / 2.0, h / 2.0 + 0.5, text=label, fill=fg,
                             font=(YH, 9, bold))


class CityPicker(tk.Canvas):
    ROW_H = 26
    MAX_ROWS = 9

    def __init__(self, parent, values, width=200, height=30, bg=CARD,
                 value="", placeholder="", on_pick=None, allow_free=False):
        super().__init__(parent, width=width, height=height, bg=bg,
                         highlightthickness=0)
        self._values = list(values)
        self._bst = self._make_tree()
        self._on_pick = on_pick
        self._placeholder = placeholder
        self._allow_free = allow_free
        self._value = value or ""
        self._ph_on = False
        self._focused = False
        self._hover_arrow = False
        self._suppress = False
        self._maxw = None
        self._font = tkfont.Font(family=YH, size=9)
        self._pop = None
        self._pop_canvas = None
        self._pop_items = []
        self._pop_disabled = False
        self._pop_hover = -1
        self._pop_w = 0
        self._sel = -1
        self._top = 0
        self._var = tk.StringVar()
        self.entry = tk.Entry(self, textvariable=self._var, font=(YH, 9),
                              relief="flat", bg="#f7f9fc", fg=TXT,
                              insertbackground=TXT, highlightthickness=0)
        self._win = self.create_window(9, height / 2.0, anchor="w",
                                       window=self.entry, width=width - 40,
                                       height=height - 13)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Button-1>", self._on_entry_click)
        self.entry.bind("<Down>", self._key_down)
        self.entry.bind("<Up>", self._key_up)
        self.entry.bind("<Return>", self._on_return)
        self.entry.bind("<Escape>", self._on_escape)
        self.entry.bind("<MouseWheel>", self._pop_wheel)
        self.bind("<Configure>", self._on_configure)
        self.bind("<Button-1>", self._on_canvas_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", self._on_leave)
        self._var.trace_add("write", self._on_var_write)
        self.winfo_toplevel().bind_all("<Button-1>", self._global_click, add="+")
        self._display(self._value)

    def get(self):
        if self._ph_on:
            return ""
        return self._var.get().strip()

    def set(self, text):
        self._value = text or ""
        self._display(self._value)

    def set_values(self, values):
        self._values = list(values)
        self._bst = self._make_tree()
        self._maxw = None
        self._close()

    def _make_tree(self):
        """由当前候选城市构建二叉搜索树（城市名索引，供前缀检索用）。"""
        tree = structures.BinSearchTree()
        for v in self._values:
            tree.insert(v, v)
        return tree

    def _on_configure(self, event=None):
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        self.coords(self._win, 9, h / 2.0)
        self.itemconfigure(self._win, width=max(30, w - 40), height=max(16, h - 13))
        self._draw()

    def _draw(self):
        self.delete("pick")
        w = max(self.winfo_width(), 60)
        h = max(self.winfo_height(), 20)
        border = BLUE if (self._focused or self._pop is not None) else BORDER
        _rounded(self, 1, 1, w - 1, h - 1, 8, fill="#f7f9fc",
                 outline=border, width=1, tags=("pick",))
        if self._hover_arrow:
            _rounded(self, w - 27, 3, w - 3, h - 3, 6, fill="#e8f1fe",
                     outline="", tags=("pick",))
        cx = w - 15
        cy = h / 2.0
        self.create_line(cx - 4.5, cy - 2.0, cx, cy + 2.5, cx + 4.5, cy - 2.0,
                         fill=BLUE if (self._hover_arrow or self._focused) else TXT3,
                         width=1.6, capstyle="round", joinstyle="round",
                         tags=("pick",))

    def _display(self, text):
        self._suppress = True
        if text == "" and self._placeholder != "":
            self._ph_on = True
            self._var.set(self._placeholder)
            self.entry.configure(fg=TXT3)
        else:
            self._ph_on = False
            self._var.set(text)
            self.entry.configure(fg=TXT)
        self._suppress = False

    def _on_var_write(self, *args):
        if self._suppress or self._ph_on:
            return
        if self._pop is None:
            if self.focus_get() is self.entry:
                self._open()
        else:
            self._refresh_items()

    def _clear_placeholder(self):
        self._suppress = True
        self._ph_on = False
        self._var.set("")
        self.entry.configure(fg=TXT)
        self._suppress = False

    def _on_focus_in(self, event=None):
        self._focused = True
        if self._ph_on:
            self._clear_placeholder()
        self._draw()

    def _on_focus_out(self, event=None):
        self._focused = False
        pop = self._pop
        if pop is not None:
            # 焦点可能刚被弹出列表抢走（点击列表项时），延迟关闭，
            # 等这次点击落地后再判断，否则点击还没处理列表就被销毁
            self.after(180, lambda: self._focus_out_settle(pop))
        else:
            self._normalize_display()
        self._draw()

    def _focus_out_settle(self, pop):
        if pop is not None and self._pop is pop:
            if self._pointer_in_pop(pop):
                return
            self._close()
        self._normalize_display()

    def _normalize_display(self):
        cur = self.get()
        if cur == "" and self._placeholder != "":
            self._display("")
        elif cur != "" and cur not in self._values and not self._allow_free:
            self._display(self._value)

    def _pointer_in_pop(self, pop):
        try:
            px = self.winfo_pointerx()
            py = self.winfo_pointery()
            rx = pop.winfo_rootx()
            ry = pop.winfo_rooty()
            rh = pop.winfo_height()
        except Exception:
            return False
        return (rx - 4 <= px <= rx + self._pop_w + 4
                and ry - 4 <= py <= ry + rh + 4)

    def _on_entry_click(self, event=None):
        if self._ph_on:
            self._clear_placeholder()
        if self._pop is None:
            self._open()

    def _on_canvas_click(self, event=None):
        self.entry.focus_set()
        if self._pop is not None:
            self._close()
        else:
            self._open()

    def _on_motion(self, event):
        hov = event.x > self.winfo_width() - 30
        if hov != self._hover_arrow:
            self._hover_arrow = hov
            self._draw()
        self.configure(cursor="hand2" if hov else "")

    def _on_leave(self, event=None):
        if self._hover_arrow:
            self._hover_arrow = False
            self._draw()

    def _key_down(self, event):
        self._open_or_nav(1)
        return "break"

    def _key_up(self, event):
        self._open_or_nav(-1)
        return "break"

    def _on_return(self, event):
        if self._pop is not None:
            if not self._pop_disabled and 0 <= self._sel < len(self._pop_items):
                self._pick(self._pop_items[self._sel])
            elif self._allow_free:
                typed = "" if self._ph_on else self._var.get().strip()
                self._close()
                if typed != "":
                    self._value = typed
                self._display(self._value)
            else:
                self._close()
                self._display(self._value)
            return "break"
        typed = self.get()
        if typed in self._values or (self._allow_free and typed != ""):
            self._value = typed
            self._display(typed)
        return None

    def _on_escape(self, event):
        if self._pop is not None:
            self._close()
            self._display(self._value)
            return "break"
        return None

    def _global_click(self, event):
        if self._pop is None:
            return
        w = event.widget
        if w is self or w is self.entry:
            return
        try:
            if w.winfo_toplevel() is self._pop:
                return
        except Exception:
            pass
        self._close()

    def _open_or_nav(self, step):
        if self._pop is None:
            self._open()
            return
        n = len(self._pop_items)
        if self._pop_disabled or n == 0:
            return
        if self._sel < 0:
            self._sel = 0 if step > 0 else n - 1
        else:
            self._sel = max(0, min(n - 1, self._sel + step))
        rows_vis = min(self.MAX_ROWS, n)
        if self._sel < self._top:
            self._top = self._sel
        elif self._sel >= self._top + rows_vis:
            self._top = self._sel - rows_vis + 1
        self._redraw_pop()

    def _max_item_w(self):
        if self._maxw is None:
            m = 0
            for v in self._values:
                tw = self._font.measure(v)
                if tw > m:
                    m = tw
            self._maxw = m
        return self._maxw

    def _filtered(self, typed):
        if typed == "" or typed == self._value:
            return list(self._values)
        # 前缀命中（BST 区间检索 O(log n + k)，按键序）优先展示，其余
        # 子串命中按原顺序兜底：中文场景输入“海”既要海口（前缀）也要
        # 上海/珠海（子串），两者并集与原“包含匹配”的候选集合完全一致
        heads = [k for k, _v in self._bst.prefix(typed)]
        head_set = set(heads)
        t = typed.lower()
        tails = [v for v in self._values
                 if v not in head_set and t in v.lower()]
        return heads + tails

    def _open(self):
        if self._pop is not None:
            return
        typed = "" if self._ph_on else self._var.get().strip()
        items = self._filtered(typed)
        self._pop_disabled = len(items) == 0
        if self._pop_disabled:
            items = ["回车按新城市联网定位加入" if self._allow_free
                     else "无匹配城市，可直接输入"]
        self._pop_items = items
        self._top = 0
        self._pop_hover = -1
        self._sel = -1
        if not self._pop_disabled:
            for idx, v in enumerate(self._pop_items):
                if v == self._value:
                    self._sel = idx
                    break
        rows_vis = min(self.MAX_ROWS, len(self._pop_items))
        h = rows_vis * self.ROW_H + 8
        w = max(self.winfo_width(), self._max_item_w() + 26)
        self._pop_w = w
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height() + 2
        if y + h > self.winfo_screenheight() - 6:
            y = max(6, self.winfo_rooty() - h - 2)
        self._pop = tk.Toplevel(self)
        self._pop.overrideredirect(True)
        self._pop.configure(bg=OUTER)
        self._pop.geometry("%dx%d+%d+%d" % (w, h, x, y))
        try:
            self._pop.attributes("-topmost", True)
        except Exception:
            pass
        c = tk.Canvas(self._pop, bg=OUTER, highlightthickness=0)
        c.pack(fill="both", expand=True)
        self._pop_canvas = c
        c.bind("<Motion>", self._pop_motion)
        c.bind("<Button-1>", self._pop_click)
        c.bind("<MouseWheel>", self._pop_wheel)
        c.bind("<Leave>", lambda e: self._pop_set_hover(-1))
        self._redraw_pop()
        self._draw()

    def _refresh_items(self):
        typed = "" if self._ph_on else self._var.get().strip()
        items = self._filtered(typed)
        self._pop_disabled = len(items) == 0
        if self._pop_disabled:
            items = ["回车按新城市联网定位加入" if self._allow_free
                     else "无匹配城市，可直接输入"]
        self._pop_items = items
        self._top = 0
        self._sel = -1 if self._pop_disabled else 0
        self._pop_hover = -1
        rows_vis = min(self.MAX_ROWS, len(self._pop_items))
        h = rows_vis * self.ROW_H + 8
        self._pop.geometry("%dx%d" % (self._pop_w, h))
        self._redraw_pop()

    def _close(self):
        if self._pop is None:
            return
        try:
            self._pop.destroy()
        except Exception:
            pass
        self._pop = None
        self._pop_canvas = None
        self._pop_items = []
        self._pop_disabled = False
        self._pop_hover = -1
        self._sel = -1
        self._top = 0
        self._draw()

    def _redraw_pop(self):
        c = self._pop_canvas
        if c is None:
            return
        c.delete("all")
        w = self._pop_w
        h = self._pop.winfo_height()
        _rounded(c, 1, 1, w - 1, h - 1, 8, fill="#ffffff", outline=BORDER, width=1)
        rows_vis = min(self.MAX_ROWS, len(self._pop_items))
        for r in range(rows_vis):
            i = self._top + r
            if i >= len(self._pop_items):
                break
            val = self._pop_items[i]
            y0 = 4 + r * self.ROW_H
            if self._pop_disabled:
                c.create_text(12, y0 + self.ROW_H / 2.0, anchor="w", text=val,
                              font=(YH, 9), fill=TXT3)
                continue
            if i == self._pop_hover:
                _rounded(c, 3, y0 + 1, w - 3, y0 + self.ROW_H - 1, 6,
                         fill="#e8f1fe", outline="")
            elif i == self._sel:
                _rounded(c, 3, y0 + 1, w - 3, y0 + self.ROW_H - 1, 6,
                         fill="#f1f6ff", outline="")
            cur = val == self._value
            c.create_text(12, y0 + self.ROW_H / 2.0, anchor="w", text=val,
                          font=(YH, 9, "bold" if cur else "normal"),
                          fill=BLUE if cur else TXT)
        n = len(self._pop_items)
        if n > rows_vis and not self._pop_disabled:
            ty0, ty1 = 5, h - 5
            th = (ty1 - ty0) * rows_vis / float(n)
            ty = ty0 + (ty1 - ty0 - th) * self._top / float(max(1, n - rows_vis))
            _rounded(c, w - 8, ty, w - 4, ty + th, 2, fill="#cdd8e6", outline="")

    def _pop_row_at(self, y):
        if y < 4 or self._pop_disabled:
            return -1
        r = int((y - 4) // self.ROW_H)
        if r < 0 or r >= self.MAX_ROWS:
            return -1
        i = self._top + r
        if i >= len(self._pop_items):
            return -1
        return i

    def _pop_set_hover(self, i):
        if i != self._pop_hover:
            self._pop_hover = i
            self._redraw_pop()

    def _pop_motion(self, event):
        self._pop_set_hover(self._pop_row_at(event.y))

    def _pop_click(self, event):
        i = self._pop_row_at(event.y)
        if i >= 0:
            self._pick(self._pop_items[i])

    def _pop_wheel(self, event):
        if self._pop is None:
            return None
        n = len(self._pop_items)
        rows_vis = min(self.MAX_ROWS, n)
        if self._pop_disabled or n <= rows_vis:
            return "break"
        step = -1 if event.delta > 0 else 1
        nt = max(0, min(n - rows_vis, self._top + step))
        if nt != self._top:
            self._top = nt
            self._redraw_pop()
        return "break"

    def _pick(self, val):
        self._value = val
        self._display(val)
        self._close()
        if self.focus_get() is not self.entry:
            self.entry.focus_set()
        if self._on_pick is not None:
            self._on_pick(val)


class Badge(tk.Canvas):
    def __init__(self, parent, letter, size=26, bg=CARD, fill=START_NAVY):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self.create_oval(1, 1, size - 1, size - 1, fill=fill, outline="")
        self.create_text(size / 2.0, size / 2.0 + 0.5, text=letter, fill="#ffffff",
                         font=(YH, 9, "bold"))


class Card(tk.Frame):
    def __init__(self, parent, radius=12, pad=10, bg=CARD, border=BORDER, outer=OUTER):
        super().__init__(parent, bg=outer)
        self._radius = radius
        self._pad = pad
        self._bg = bg
        self._border = border
        self.canvas = tk.Canvas(self, bg=outer, highlightthickness=0, height=24)
        self.canvas.pack(fill="x")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(pad, pad, anchor="nw", window=self.inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        self.inner.bind("<Configure>", self._on_inner)

    def _on_canvas(self, event=None):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        self.canvas.delete("cardbg")
        _rounded(self.canvas, 1, 1, w - 1, h - 1, self._radius,
                 fill=self._bg, outline=self._border, width=1, tags=("cardbg",))
        self.canvas.tag_lower("cardbg")
        self.canvas.itemconfigure(self._win, width=max(10, w - 2 * self._pad))

    def _on_inner(self, event=None):
        need = self.inner.winfo_reqheight() + 2 * self._pad
        if abs(need - self.canvas.winfo_height()) > 1:
            self.canvas.configure(height=need)


class App:
    def __init__(self, root, graph, ak=""):
        self.root = root
        self.graph = graph
        self.city_bst = structures.BinSearchTree()
        self.ak = ak
        self.source = "未加载路网"
        self.panel_shown = True
        root.title("城市路网规划系统")
        root.geometry("1300x880")
        root.configure(bg=OUTER)
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem()
            if dpi < 96:
                dpi = 96
            root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        body = tk.Frame(root, bg=OUTER)
        body.pack(fill="both", expand=True, padx=10, pady=(10, 2))
        names = [CITIES[i][0] for i in range(len(CITIES))]

        panel = tk.Frame(body, bg=OUTER, width=344)
        panel.pack(side="left", fill="y")
        panel.pack_propagate(False)
        self.panel = panel

        psb = tk.Scrollbar(panel, orient="vertical", width=10,
                           bg="#e8edf4", troughcolor=OUTER,
                           activebackground="#c9d4e0", relief="flat",
                           borderwidth=0, highlightthickness=0)
        pcanvas = tk.Canvas(panel, bg=OUTER, highlightthickness=0)
        psb.configure(command=pcanvas.yview)
        pcanvas.configure(yscrollcommand=psb.set)
        psb.pack(side="right", fill="y")
        pcanvas.pack(side="left", fill="both", expand=True)
        self.pcanvas = pcanvas
        self.psb = psb
        pbody = tk.Frame(pcanvas, bg=OUTER)
        pwin = pcanvas.create_window((0, 0), window=pbody, anchor="nw")
        self.pwin = pwin
        pbody.bind("<Configure>", self._panel_layout)
        pcanvas.bind("<Configure>", self._panel_resize)

        head = tk.Frame(pbody, bg=OUTER)
        head.pack(fill="x", padx=16, pady=(2, 0))
        tk.Label(head, text="路线", font=(YH, 17, "bold"), bg=OUTER,
                 fg=TXT).pack(side="left")
        self.btn_collapse = Pill(head, "◀ 收起", self.toggle_panel, kind="primary",
                                 bg=OUTER, width=76, height=26)
        self.btn_collapse.pack(side="right")
        tk.Label(pbody, text="城市路网规划系统 · 基于图与六种数据结构", font=(YH, 9),
                 bg=OUTER, fg=TXT3).pack(anchor="w", padx=18)

        self.mode = "short"
        card_seg = Card(pbody)
        card_seg.pack(fill="x", padx=10, pady=(2, 0))
        self.seg = SegBar(card_seg.inner,
                          [("short", "最短路径"), ("stops", "最少经停"), ("cheap", "最省钱")],
                          self.on_mode)
        self.seg.pack(fill="x", padx=6, pady=4)

        card_route = Card(pbody)
        card_route.pack(fill="x", padx=10, pady=(2, 0))
        g = tk.Frame(card_route.inner, bg=CARD)
        g.pack(fill="x", padx=6, pady=4)
        g.columnconfigure(1, weight=1)
        Badge(g, "A").grid(row=0, column=0, padx=(2, 8), pady=2)
        self.combo_from = CityPicker(g, names, value="北京", width=210)
        self.combo_from.grid(row=0, column=1, columnspan=2, sticky="we", pady=2)
        conn = tk.Canvas(g, width=26, height=18, bg=CARD, highlightthickness=0)
        conn.grid(row=1, column=0)
        for yy in (4, 9, 14):
            conn.create_oval(11.5, yy - 1.5, 14.5, yy + 1.5, fill="#c6d0dd", outline="")
        self.btn_swap = RoundBtn(g, "⇅", self.swap_from_to, size=24, bg=CARD)
        self.btn_swap.grid(row=1, column=2, sticky="e", padx=(6, 0))
        Badge(g, "B").grid(row=2, column=0, padx=(2, 8), pady=2)
        self.combo_to = CityPicker(g, names, value="上海", width=210)
        self.combo_to.grid(row=2, column=1, columnspan=2, sticky="we", pady=2)
        tk.Frame(g, bg="#eef2f8", height=1).grid(row=3, column=0, columnspan=3,
                                                 sticky="we", pady=(6, 4))
        via_icon = tk.Canvas(g, width=20, height=20, bg=CARD, highlightthickness=0)
        via_icon.grid(row=4, column=0, padx=(2, 8))
        via_icon.create_oval(2.5, 2.5, 17.5, 17.5, outline=VIOLET, width=1.6)
        via_icon.create_line(10, 6.5, 10, 13.5, fill=VIOLET, width=1.6)
        via_icon.create_line(6.5, 10, 13.5, 10, fill=VIOLET, width=1.6)
        tk.Label(g, text="途经点（按顺序经过）", font=(YH, 9), bg=CARD,
                 fg=VIOLET).grid(row=4, column=1, sticky="w")
        via_add = tk.Label(g, text="＋ 添加途经点", font=(YH, 9), bg=CARD,
                           fg=BLUE_D, cursor="hand2")
        via_add.grid(row=4, column=2, sticky="e", padx=(0, 2))
        via_add.bind("<Button-1>", lambda e: self._add_via())
        via_add.bind("<Enter>", lambda e: via_add.config(fg=BLUE))
        via_add.bind("<Leave>", lambda e: via_add.config(fg=BLUE_D))
        self.via_box = tk.Frame(g, bg=CARD)
        self.via_box.grid(row=5, column=0, columnspan=3, sticky="we")
        self.via_rows = []
        self.via_sort = tk.Label(self.via_box, text="⇅ 智能排序（自动按里程）",
                                 font=(YH, 9), bg=CARD, fg=GREEN2, cursor="hand2")
        self.via_sort.bind("<Button-1>", lambda e: self.on_sort_vias())
        self._via_sort_shown = False
        Pill(g, "查询", self.run_query, kind="primary", bg=CARD,
             width=200, height=32).grid(row=6, column=0, columnspan=3,
                                        sticky="we", padx=2, pady=(8, 0))

        card_res = Card(pbody)
        card_res.pack(fill="x", padx=10, pady=(2, 0))
        head2 = tk.Frame(card_res.inner, bg=CARD)
        head2.pack(fill="x", padx=8, pady=(6, 2))
        hic = tk.Canvas(head2, width=24, height=18, bg=CARD, highlightthickness=0)
        hic.pack(side="left")
        _car_icon(hic, 12, 9)
        tk.Label(head2, text="路线方案", font=(YH, 10, "bold"), bg=CARD,
                 fg=TXT).pack(side="left", padx=(6, 0))
        self.btn_clear = Pill(head2, "清空高亮", self.reset_highlight,
                              kind="outline", bg=CARD, width=78, height=24)
        self.btn_clear.pack(side="right")
        self.btn_alt = Pill(head2, "备选路线", self.on_alternatives,
                            kind="primary", bg=CARD, width=78, height=24)
        self.btn_alt.pack(side="right", padx=(0, 8))
        self.result = tk.Text(card_res.inner, height=9, font=(YH, 9),
                              state="disabled", bg="#f8fafd", relief="flat",
                              highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=BORDER, wrap="word",
                              padx=10, pady=8)
        self.result.tag_config("res_title", font=(YH, 11, "bold"),
                               foreground="#1c3a5e", spacing1=1, spacing3=4)
        self.result.tag_config("res_chain", font=(YH, 10, "bold"),
                               foreground="#33475f", spacing3=3)
        self.result.tag_config("res_meta", font=(YH, 9, "bold"),
                               foreground=GREEN, spacing3=4)
        self.result.tag_config("res_div", foreground="#bfcdde", spacing2=4, spacing3=4)
        self.result.tag_config("res_seg", font=(YH, 9), foreground="#43536b",
                               spacing2=1, lmargin1=6, lmargin2=22)
        self.result.tag_config("res_norm", font=(YH, 9), foreground="#4b5563", spacing2=1)
        self.result.tag_config("res_note", font=(YH, 9), foreground=TXT3, spacing2=2)
        self.result.tag_config("res_alg", font=(YH, 9), foreground="#6d4fc4", spacing2=2)
        self.result.pack(fill="x", padx=10, pady=(0, 8))
        self.result.bind("<MouseWheel>", self._wheel_result)

        card_net = Card(pbody)
        card_net.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(card_net.inner, text="路网规划", font=(YH, 9, "bold"), bg=CARD,
                 fg=TXT2).pack(anchor="w", padx=12, pady=(6, 2))
        cn = tk.Frame(card_net.inner, bg=CARD)
        cn.pack(fill="x", padx=8, pady=(2, 6))
        cn.columnconfigure(0, weight=1)
        cn.columnconfigure(1, weight=1)
        Pill(cn, "最省钱公路网", self.on_prim, kind="green", bg=CARD,
             width=130).grid(row=0, column=0, sticky="we", padx=(2, 4))
        Pill(cn, "查看路网结构", self.on_adjacency, kind="outline", bg=CARD,
             width=130).grid(row=0, column=1, sticky="we", padx=(4, 2))

        card_edit = Card(pbody)
        card_edit.pack(fill="x", padx=10, pady=(2, 0))
        tk.Label(card_edit.inner, text="道路编辑", font=(YH, 9, "bold"), bg=CARD,
                 fg=TXT2).pack(anchor="w", padx=12, pady=(6, 2))
        ged = tk.Frame(card_edit.inner, bg=CARD)
        ged.pack(fill="x", padx=8, pady=(0, 6))
        ged.columnconfigure(1, weight=1)
        ged.columnconfigure(3, weight=1)
        tk.Label(ged, text="起点", font=(YH, 9), bg=CARD, fg=TXT2).grid(
            row=0, column=0, sticky="w", padx=(2, 6), pady=2)
        self.combo_a = CityPicker(ged, names, width=100, height=28,
                                  placeholder="输入城市", allow_free=True)
        self.combo_a.grid(row=0, column=1, sticky="we", pady=2)
        tk.Label(ged, text="终点", font=(YH, 9), bg=CARD, fg=TXT2).grid(
            row=0, column=2, sticky="w", padx=(10, 6), pady=2)
        self.combo_b = CityPicker(ged, names, width=100, height=28,
                                  placeholder="输入城市", allow_free=True)
        self.combo_b.grid(row=0, column=3, sticky="we", pady=2)
        tk.Label(ged, text="选好起终点后自动拉取百度真实路线，新城市自动定位加入",
                 font=(YH, 8), bg=CARD, fg=TXT3, wraplength=270,
                 justify="left", anchor="w").grid(
            row=1, column=0, columnspan=4, sticky="we", padx=2, pady=(0, 2))
        Pill(ged, "拉取真实数据新增", self.on_add_road, kind="primary",
             bg=CARD, width=120, height=30).grid(
            row=2, column=0, columnspan=2, sticky="we", padx=(2, 4), pady=(6, 0))
        Pill(ged, "删除该道路", self.on_delete_road, kind="outline", bg=CARD,
             width=120, height=30).grid(row=2, column=2, columnspan=2,
                                        sticky="we", padx=(4, 2), pady=(6, 0))
        Pill(ged, "撤销编辑", self.on_undo_edit, kind="outline", bg=CARD,
             width=120, height=30).grid(row=3, column=0, columnspan=2,
                                        sticky="we", padx=(2, 4), pady=(6, 0))
        Pill(ged, "重做编辑", self.on_redo_edit, kind="outline", bg=CARD,
             width=120, height=30).grid(row=3, column=2, columnspan=2,
                                        sticky="we", padx=(4, 2), pady=(6, 0))

        card_data = Card(pbody)
        card_data.pack(fill="x", padx=10, pady=(2, 4))
        Pill(card_data.inner, "重新导入真实路网", self.on_import_real, kind="violet",
             bg=CARD, width=200).pack(fill="x", padx=8, pady=6)

        right = tk.Frame(body, bg=MAP_BG)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self.right = right
        toolbar = tk.Frame(right, bg=MAP_BG)
        toolbar.pack(side="bottom", fill="x")
        RoundBtn(toolbar, "＋", self.zoom_in, size=30, bg=MAP_BG).pack(
            side="left", pady=4, padx=(2, 4))
        RoundBtn(toolbar, "－", self.zoom_out, size=30, bg=MAP_BG).pack(
            side="left", pady=4, padx=4)
        Pill(toolbar, "重置视图", self.zoom_reset, kind="outline", bg=MAP_BG,
             width=88, height=30).pack(side="left", pady=4, padx=(4, 8))
        tk.Label(toolbar, text="滚轮缩放 · 拖动平移 · 悬停道路查看详情",
                 font=(YH, 9), bg=MAP_BG, fg=TXT3).pack(side="left", padx=6)
        self.canvas = tk.Canvas(right, bg=MAP_BG,
                                highlightthickness=1, highlightbackground="#dfe7f1")
        self.canvas.pack(fill="both", expand=True)
        self.reopen = Pill(right, "展开面板 ▶", self.toggle_panel, kind="primary",
                           bg=MAP_BG, width=108, height=32)

        self.hover = None
        self.curves = {}
        self.curve_grid = None
        self._panning = False
        self._pan_x = 0
        self._pan_y = 0
        self.current_path = None
        self.current_mst = None
        self.current_vias = []
        self.alt_paths = []
        self.current_path_color = BLUE
        self._lbl_font = tkfont.Font(family=YH, size=8)
        self._lbl_font_b = tkfont.Font(family=YH, size=8, weight="bold")
        self.import_done = True
        self.import_result = None
        self.import_lines = []
        self.road_busy = False
        self.road_done = True
        self.road_result = None
        self.hist = structures.EditHistory()
        self.canvas.bind("<Motion>", self.on_motion)
        self.canvas.bind("<Leave>", self.on_leave)
        self.canvas.bind("<MouseWheel>", self.on_wheel)
        self.canvas.bind("<ButtonPress-1>", self.on_pan_start)
        self.canvas.bind("<B1-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_pan_end)
        self.canvas.bind("<ButtonPress-2>", self.on_pan_start)
        self.canvas.bind("<B2-Motion>", self.on_pan_move)
        self.canvas.bind("<ButtonRelease-2>", self.on_pan_end)
        self.root.bind_all("<MouseWheel>", self._panel_wheel)

        self.status = tk.Label(root, text="", font=(YH, 9), fg=TXT2,
                               bg=OUTER, anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 6))
        self.update_status()
        self.draw_graph()
        self.root.after(200, self.start_import)

    def _wheel_result(self, event):
        self.result.yview_scroll(int(-event.delta / 120), "units")
        return "break"

    def _panel_layout(self, event=None):
        bbox = self.pcanvas.bbox("all")
        if bbox is None:
            return
        self.pcanvas.configure(scrollregion=bbox)
        need = bbox[3] > self.pcanvas.winfo_height() + 1
        if need and not self.psb.winfo_ismapped():
            self.psb.pack(side="right", fill="y")
        elif not need and self.psb.winfo_ismapped():
            self.psb.pack_forget()

    def _panel_resize(self, event):
        self.pcanvas.itemconfigure(self.pwin, width=event.width)
        self._panel_layout()

    def _panel_wheel(self, event):
        try:
            t = self.root.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while t is not None:
            if t is self.result or t is self.canvas:
                return
            if t is self.pcanvas or t is self.panel:
                step = int(-event.delta / 120)
                self.pcanvas.yview_scroll(step if step != 0 else -1, "units")
                return
            t = t.master

    def on_mode(self, key):
        self.mode = key

    def run_query(self, note=""):
        if self.mode == "stops":
            self._query_route("stops", note)
        elif self.mode == "cheap":
            self._query_route("fee", note)
        else:
            self._query_route("km", note)

    def swap_from_to(self):
        a = self.combo_from.get()
        b = self.combo_to.get()
        if a == "" or b == "":
            return
        self.combo_from.set(b)
        self.combo_to.set(a)

    def _city_names(self):
        return [CITIES[i][0] for i in range(len(CITIES))]

    def _ci(self, name):
        """城市名 → 下标：二叉搜索树精确查找，O(log n)；未命中返回 -1。"""
        v = self.city_bst.search(name)
        return -1 if v is None else v

    def _add_via(self):
        if len(self.via_rows) >= 8:
            messagebox.showinfo("提示", "最多添加 8 个途经点")
            return
        row = tk.Frame(self.via_box, bg=CARD)
        row.pack(fill="x", pady=1)
        num = tk.Label(row, text="①", font=(YH, 10, "bold"), bg=CARD,
                       fg=VIOLET, width=2)
        num.pack(side="left")
        pk = CityPicker(row, self._city_names(), width=150, height=28,
                        placeholder="输入或选择途经城市")
        pk.pack(side="left", fill="x", expand=True)
        RoundBtn(row, "✕", lambda: self._remove_via(row), size=20, bg=CARD,
                 fill="#fbfcfe", fg=TXT3).pack(side="left", padx=(4, 0))
        self.via_rows.append((row, num, pk))
        self._renumber_vias()

    def _remove_via(self, row):
        for k in range(len(self.via_rows)):
            if self.via_rows[k][0] is row:
                self.via_rows.pop(k)
                row.destroy()
                break
        self._renumber_vias()

    def _renumber_vias(self):
        marks = "①②③④⑤⑥⑦⑧"
        for k in range(len(self.via_rows)):
            self.via_rows[k][1].config(text=marks[k])
        want = len(self.via_rows) >= 2
        if want and not self._via_sort_shown:
            self.via_sort.pack(side="bottom", anchor="w", padx=(22, 0), pady=(3, 0))
            self._via_sort_shown = True
        elif not want and self._via_sort_shown:
            self.via_sort.pack_forget()
            self._via_sort_shown = False

    def _via_values(self):
        out = []
        for _, _, pk in self.via_rows:
            v = pk.get()
            if v != "":
                out.append(v)
        return out

    def toggle_panel(self):
        if self.panel_shown:
            self.panel.pack_forget()
            self.panel_shown = False
            self.reopen.place(relx=1.0, rely=0.0, x=-14, y=14, anchor="ne")
        else:
            self.panel.pack(side="left", fill="y", before=self.right)
            self.panel_shown = True
            self.reopen.place_forget()

    def zoom_in(self):
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        geo.zoom_around(w / 2.0, h / 2.0, 1.3)
        self.draw_graph()

    def zoom_out(self):
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        geo.zoom_around(w / 2.0, h / 2.0, 1.0 / 1.3)
        self.draw_graph()

    def zoom_reset(self):
        geo.reset_view(self.canvas.winfo_width(), self.canvas.winfo_height())
        self.draw_graph()

    def on_pan_start(self, event):
        self._clear_hover()
        self._panning = True
        self._pan_x = event.x
        self._pan_y = event.y
        self.canvas.configure(cursor="fleur")

    def on_pan_move(self, event):
        dx = event.x - self._pan_x
        dy = event.y - self._pan_y
        self._pan_x = event.x
        self._pan_y = event.y
        if dx == 0 and dy == 0:
            return
        geo.pan(dx, dy)
        self.canvas.move("all", dx, dy)
        self.canvas.move("legend", -dx, -dy)

    def on_pan_end(self, event):
        self._panning = False
        self.canvas.configure(cursor="")
        self.draw_graph()

    def on_wheel(self, event):
        factor = 1.12 ** (event.delta / 120.0)
        geo.zoom_around(event.x, event.y, factor)
        self.draw_graph()

    def update_status(self):
        km = self.graph.total_km()
        fee = self.graph.total_fee()
        conn = "连通" if self.graph.is_connected() else "不连通"
        warns = len(self.graph.warnings)
        chk = "通过" if warns == 0 else "忽略 %d 条无效道路" % warns
        self.status.config(text="数据源：%s    城市：%d 个    公路：%d 条    总里程：%d 公里    过路费：%d 元    路网：%s    数据校验：%s"
                                % (self.source, self.graph.n, self.graph.edge_num,
                                   km, fee, conn, chk))

    def edge_curve_points(self, u, v):
        a_name = CITIES[u][0]
        b_name = CITIES[v][0]
        stops = None
        if (a_name, b_name) in ROUTE_CURVES:
            stops = ROUTE_CURVES[(a_name, b_name)]
        elif (b_name, a_name) in ROUTE_CURVES:
            stops = list(ROUTE_CURVES[(b_name, a_name)])
            stops.reverse()
        pts = [geo.canvas_xy(u)]
        if stops is not None:
            for name in stops:
                lon, lat = ROUTE_POINTS[name]
                pts.append(geo.lonlat_xy(lon, lat))
        pts.append(geo.canvas_xy(v))
        pts = geo.dedupe_pts(pts)
        if stops is not None and len(stops) >= 10:
            return geo.dedupe_pts(geo.chaikin(pts, 2))
        return geo.catmull_rom(pts)

    def draw_graph(self, path=None, mst_edges=None):
        if path is None:
            path = self.current_path
        if mst_edges is None:
            mst_edges = self.current_mst
        pcol = self.current_path_color
        c = self.canvas
        c.delete("all")
        self.hover = None
        self.curves = {}
        self.curve_grid = None
        self._panning = False
        self._pan_x = 0
        self._pan_y = 0
        pedges = []
        if path is not None:
            for i in range(len(path) - 1):
                a, b = path[i], path[i + 1]
                if a < b:
                    pedges.append((a, b))
                else:
                    pedges.append((b, a))
        for u in range(self.graph.n):
            p = self.graph.adj[u].head
            seen = {}
            while p is not None:
                v = p.city
                if u < v:
                    seq = seen.get(v, 0) + 1
                    seen[v] = seq
                    if seq == 1:
                        curve = self.edge_curve_points(u, v)
                        self.curves[(u, v)] = curve
                        flat = geo.flatten_pts(curve)
                        c.create_line(flat, fill="#ffffff", width=6,
                                      capstyle="round", joinstyle="round",
                                      tags=("edge", "e_%d_%d" % (u, v)))
                        c.create_line(flat, fill=ROAD_C, width=2.4,
                                      capstyle="round", joinstyle="round",
                                      tags=("edge", "e_%d_%d" % (u, v)))
                    else:
                        a = geo.canvas_xy(u)
                        b = geo.canvas_xy(v)
                        dx = b[0] - a[0]
                        dy = b[1] - a[1]
                        L = (dx * dx + dy * dy) ** 0.5
                        if L < 1e-6:
                            nx, ny = 0.0, -1.0
                        else:
                            nx = -dy / L
                            ny = dx / L
                        off = 7.0 if seq % 2 == 0 else -7.0
                        xa = a[0] + nx * off
                        ya = a[1] + ny * off
                        xb = b[0] + nx * off
                        yb = b[1] + ny * off
                        c.create_line(xa, ya, xb, yb, fill="#ffffff", width=5,
                                      tags=("edge", "e_%d_%d" % (u, v)))
                        c.create_line(xa, ya, xb, yb, fill=ROAD_C, width=2,
                                      tags=("edge", "e_%d_%d" % (u, v)))
                p = p.next
        self.curve_grid = geo.build_curve_grid(self.curves)
        if mst_edges is not None:
            for u, v in mst_edges:
                curve = self.curves.get((u, v))
                if curve is None:
                    curve = self.edge_curve_points(u, v)
                flat = geo.flatten_pts(curve)
                c.create_line(flat, fill="#ffffff", width=13,
                              capstyle="round", joinstyle="round")
                c.create_line(flat, fill="#b5e6c8", width=10,
                              capstyle="round", joinstyle="round")
                c.create_line(flat, fill="#1f9d55", width=4.5,
                              capstyle="round", joinstyle="round")
        if self.alt_paths:
            for ap in self.alt_paths:
                for i in range(len(ap) - 1):
                    u, v = ap[i], ap[i + 1]
                    key = (u, v) if u < v else (v, u)
                    curve = self.curves.get(key)
                    if curve is None:
                        curve = self.edge_curve_points(u, v)
                    flat = geo.flatten_pts(curve)
                    c.create_line(flat, fill="#ffffff", width=10,
                                  capstyle="round", joinstyle="round")
                    c.create_line(flat, fill="#cbb7f0", width=6,
                                  capstyle="round", joinstyle="round")
        if path is not None:
            for u, v in pedges:
                curve = self.curves.get((u, v))
                if curve is None:
                    curve = self.edge_curve_points(u, v)
                flat = geo.flatten_pts(curve)
                c.create_line(flat, fill="#ffffff", width=14,
                              capstyle="round", joinstyle="round")
                c.create_line(flat, fill="#cfe0ff", width=10,
                              capstyle="round", joinstyle="round")
                c.create_line(flat, fill=pcol, width=5.5,
                              capstyle="round", joinstyle="round")
        entries = []
        for i in range(self.graph.n):
            x, y = geo.canvas_xy(i)
            on_path = path is not None and contains(path, i)
            if on_path:
                c.create_oval(x - 5, y - 5, x + 5, y + 5,
                              fill="#ffffff", outline=pcol, width=2.5)
            else:
                c.create_oval(x - 3.2, y - 3.2, x + 3.2, y + 3.2,
                              fill="#8291a6", outline="#ffffff", width=1.2)
            entries.append((0 if on_path else 1, i, x, y, on_path))
        entries.sort(key=lambda t: (t[0], t[1]))
        placed = []
        for pri, i, x, y, on_path in entries:
            name = CITIES[i][0]
            fnt = self._lbl_font_b if on_path else self._lbl_font
            bx0 = x + 7.0
            by0 = y - 6.0
            bx1 = x + 11.0 + fnt.measure(name)
            by1 = y + 7.0
            blocked = False
            for px0, py0, px1, py1 in placed:
                if bx0 < px1 and bx1 > px0 and by0 < py1 and by1 > py0:
                    blocked = True
                    break
            if blocked and not on_path:
                continue
            placed.append((bx0, by0, bx1, by1))
            if on_path:
                c.create_text(x + 9, y + 1, text=name, anchor="w",
                              font=(YH, 8, "bold"), fill=START_NAVY)
            else:
                c.create_text(x + 8, y + 1, text=name, anchor="w",
                              font=(YH, 8), fill="#67788d")
        if path is not None:
            sx, sy = geo.canvas_xy(path[0])
            ex, ey = geo.canvas_xy(path[-1])
            c.create_oval(sx - 9, sy - 9, sx + 9, sy + 9,
                          fill=START_NAVY, outline="#ffffff", width=2)
            c.create_text(sx, sy + 0.5, text="A", fill="#ffffff", font=(YH, 8, "bold"))
            c.create_polygon(ex - 4.6, ey - 12, ex + 4.6, ey - 12, ex, ey - 1,
                             fill=END_RED, outline="#ffffff", width=1.4)
            c.create_oval(ex - 8.6, ey - 23, ex + 8.6, ey - 6,
                          fill=END_RED, outline="#ffffff", width=1.4)
            c.create_text(ex, ey - 14.5, text="B", fill="#ffffff",
                          font=(YH, 8, "bold"))
            marks = "①②③④⑤⑥⑦⑧"
            for k, vi in enumerate(self.current_vias):
                if not contains(path, vi):
                    continue
                vx, vy = geo.canvas_xy(vi)
                c.create_oval(vx - 8, vy - 8, vx + 8, vy + 8,
                              fill=VIOLET, outline="#ffffff", width=2)
                c.create_text(vx, vy + 0.5, text=marks[k % 8], fill="#ffffff",
                              font=(YH, 7, "bold"))
            km = 0
            for i in range(len(path) - 1):
                km += self.graph.get_weight(path[i], path[i + 1])
            self._draw_path_bubble(c, path, km)
        self._draw_legend(c)
        self.update_status()

    def _draw_path_bubble(self, c, path, km):
        mid = path[len(path) // 2]
        mx, my = geo.canvas_xy(mid)
        w, h = 186, 52
        cw = max(self.canvas.winfo_width(), 320)
        x0 = min(max(8, mx - w / 2.0), cw - w - 8)
        x1 = x0 + w
        y1 = my - 24
        if y1 - h < 8:
            down = False
            y0 = my + 26
            y1 = y0 + h
        else:
            down = True
            y0 = y1 - h
        if down:
            tail = (mx - 7, y1 - 1, mx + 6, y1 - 1, mx, my - 7)
        else:
            tail = (mx - 7, y0 + 1, mx + 6, y0 + 1, mx, my + 7)
        _rounded(c, x0 + 2, y0 + 3, x1 + 2, y1 + 3, 10, fill="#dde5f0", outline="")
        c.create_polygon(tail, fill="#ffffff", outline="#d7e0ec", width=1)
        _rounded(c, x0, y0, x1, y1, 10, fill="#ffffff", outline="#d7e0ec", width=1)
        _car_icon(c, x0 + 23, y0 + 18)
        c.create_text(x0 + 42, y0 + 18, text=estimate_time(km, len(path) - 2),
                      anchor="w", font=(YH, 10, "bold"), fill=TXT)
        c.create_text(x0 + 42, y0 + 37, text="%d 公里" % km,
                      anchor="w", font=(YH, 9), fill=TXT3)

    def _draw_legend(self, c):
        x0, y0, x1 = 12, 12, 232
        y1 = y0 + 128
        _rounded(c, x0 + 2, y0 + 3, x1 + 2, y1 + 3, 10, fill="#dde5f0",
                 outline="", tags=("legend",))
        _rounded(c, x0, y0, x1, y1, 10, fill="#ffffff", outline="#d7e0ec",
                 width=1, tags=("legend",))
        rows = [(BLUE, "最短路径"), (GOLD, "最省钱路线"),
                ("#1f9d55", "最省钱公路网"), (ROAD_C, "普通公路（悬停查看）")]
        yy = y0 + 22
        for col, txt in rows:
            c.create_line(x0 + 10, yy, x0 + 38, yy, fill=col, width=5,
                          capstyle="round", tags=("legend",))
            c.create_text(x0 + 46, yy, text=txt, anchor="w", font=(YH, 9),
                          fill="#4b5563", tags=("legend",))
            yy += 22
        cy = yy + 4
        c.create_oval(x0 + 10, cy - 7, x0 + 24, cy + 7, fill=START_NAVY,
                      outline="#ffffff", width=1.5, tags=("legend",))
        c.create_text(x0 + 15.5, cy, text="A", fill="#ffffff",
                      font=(YH, 7, "bold"), tags=("legend",))
        c.create_text(x0 + 30, cy, text="起点", anchor="w", font=(YH, 9),
                      fill="#4b5563", tags=("legend",))
        c.create_oval(x0 + 86, cy - 7, x0 + 100, cy + 7, fill=END_RED,
                      outline="#ffffff", width=1.5, tags=("legend",))
        c.create_text(x0 + 91.5, cy, text="B", fill="#ffffff",
                      font=(YH, 7, "bold"), tags=("legend",))
        c.create_text(x0 + 106, cy, text="终点", anchor="w", font=(YH, 9),
                      fill="#4b5563", tags=("legend",))

    def _clear_hover(self):
        self.canvas.delete("hoverglow")
        self.canvas.delete("hovertip")
        self.hover = None

    def _draw_hover(self, u, v):
        curve = self.curves.get((u, v))
        if curve is None:
            return
        flat = geo.flatten_pts(curve)
        self.canvas.create_line(flat, fill="#cfe0ff", width=11,
                                capstyle="round", joinstyle="round",
                                tags=("hoverglow",))
        self.canvas.create_line(flat, fill=BLUE, width=5,
                                capstyle="round", joinstyle="round",
                                tags=("hoverglow",))
        self.canvas.tag_raise("legend")

    def _show_road_tip(self, x, y, u, v):
        c = self.canvas
        ds = self.graph.edges_between(u, v)
        fs = self.graph.fees_between(u, v)
        if len(ds) == 0:
            return
        km = ds[0]
        for d in ds:
            if d < km:
                km = d
        fee = fs[0] if len(fs) > 0 else 0
        for f in fs:
            if f < fee:
                fee = f
        extra = ""
        if len(ds) > 1:
            extra = "（%d 条平行路）" % len(ds)
        w, h = 216, 72
        cw = max(c.winfo_width(), 320)
        ch = max(c.winfo_height(), 240)
        x0 = min(max(8, x + 18), cw - w - 8)
        y0 = min(max(8, y + 16), ch - h - 8)
        c.delete("hovertip")
        _rounded(c, x0 + 2, y0 + 3, x0 + w + 2, y0 + h + 3, 10,
                 fill="#dfe6f0", outline="", tags=("hovertip",))
        _rounded(c, x0, y0, x0 + w, y0 + h, 10, fill="#ffffff",
                 outline="#d7e0ec", width=1, tags=("hovertip",))
        _car_icon(c, x0 + 22, y0 + 18, tags=("hovertip",))
        c.create_text(x0 + 40, y0 + 18, text="道路 %s — %s" % (CITIES[u][0], CITIES[v][0]),
                      anchor="w", font=(YH, 9, "bold"), fill=TXT, tags=("hovertip",))
        c.create_text(x0 + 13, y0 + 39, text="里程 %d 公里 · 过路费 %d 元%s" % (km, fee, extra),
                      anchor="w", font=(YH, 9), fill=TXT2, tags=("hovertip",))
        c.create_text(x0 + 13, y0 + 57, text="预计 %s" % estimate_time(km, 0),
                      anchor="w", font=(YH, 9, "bold"), fill=GREEN, tags=("hovertip",))
        c.tag_raise("legend")

    def on_motion(self, event):
        if self._panning:
            return
        if self.graph.n == 0 or len(self.curves) == 0:
            return
        x, y = event.x, event.y
        best, _bd = geo.pick_curve(self.curves, self.curve_grid, x, y)
        if best is None:
            if self.hover is not None:
                self._clear_hover()
                self.update_status()
            return
        if best != self.hover:
            self._clear_hover()
            self.hover = best
            self._draw_hover(best[0], best[1])
        else:
            self.canvas.delete("hovertip")
        u, v = best
        self._show_road_tip(x, y, u, v)
        ds = self.graph.edges_between(u, v)
        fs = self.graph.fees_between(u, v)
        extra = "（%d 条平行路）" % len(ds) if len(ds) > 1 else ""
        self.status.config(text="道路：%s — %s    里程：%s 公里    过路费：%s 元%s"
                                % (CITIES[u][0], CITIES[v][0],
                                   "/".join(str(d) for d in ds),
                                   "/".join(str(f) for f in fs), extra))

    def on_leave(self, event):
        if self.hover is not None:
            self._clear_hover()
            self.update_status()

    def show_result(self, text):
        self.result.config(state="normal")
        self.result.delete("1.0", "end")
        lines = text.split("\n")
        for i, ln in enumerate(lines):
            s = ln.strip()
            tag = "res_norm"
            if i == 0 and s != "":
                tag = "res_title"
            elif s.startswith("注"):
                tag = "res_note"
            elif s.startswith("算法对比"):
                tag = "res_alg"
            elif s.count("─") >= 3:
                tag = "res_div"
            elif s[:1].isdigit() and " → " in s:
                tag = "res_seg"
            elif " → " in s and "：" not in s:
                tag = "res_chain"
            elif "预计" in s or "总里程" in s:
                tag = "res_meta"
            self.result.insert("end", ln + "\n", tag)
        self.result.config(state="disabled")
        self.result.see("1.0")

    def _path_report(self, path, show_fee=False):
        segs = []
        names = []
        for k in range(len(path) - 1):
            u = path[k]
            v = path[k + 1]
            names.append(CITIES[u][0])
            if show_fee:
                segs.append("  %2d. %s → %s    %d 公里 · 过路费 %d 元"
                            % (k + 1, CITIES[u][0], CITIES[v][0],
                               self.graph.get_weight(u, v), self.graph.get_fee(u, v)))
            else:
                segs.append("  %2d. %s → %s    %d 公里"
                            % (k + 1, CITIES[u][0], CITIES[v][0],
                               self.graph.get_weight(u, v)))
        names.append(CITIES[path[-1]][0])
        return " → ".join(names), "\n".join(segs)

    def _path_km(self, path):
        total = 0
        for s in range(len(path) - 1):
            total += self.graph.get_weight(path[s], path[s + 1])
        return total

    def _path_fee(self, path):
        total = 0
        for s in range(len(path) - 1):
            total += self.graph.get_fee(path[s], path[s + 1])
        return total

    def _query_route(self, mode, note=""):
        a = self.combo_from.get()
        b = self.combo_to.get()
        vias = self._via_values()
        if a == "" or b == "":
            messagebox.showwarning("提示", "请选择出发城市和到达城市")
            return
        pts = [a] + vias + [b]
        idx = []
        for p in pts:
            i = self._ci(p)
            if i < 0:
                messagebox.showwarning(
                    "提示", "%s 不在路网中，请从下拉列表中选择城市" % p)
                return
            idx.append(i)
        for k in range(len(idx) - 1):
            if idx[k] == idx[k + 1]:
                messagebox.showwarning(
                    "提示", "相邻的出发/途经/到达城市不能相同：%s" % pts[k])
                return
        base = {"km": "最短路线 · A* 启发式", "stops": "最少经停路线 · BFS",
                "fee": "最省钱路线 · Dijkstra 过路费权重"}[mode]
        if vias:
            shown = "、".join(vias[:3])
            if len(vias) > 3:
                shown += " 等 %d 城" % len(vias)
            title = base + "（途经 %s）" % shown
        else:
            title = base
        used = set()
        path = None
        repeat_legs = []
        leg_specs = []
        ast_expand = 0
        for k in range(len(idx) - 1):
            s, e = idx[k], idx[k + 1]
            ban = set(used)
            ban.discard(s)
            leg, rep, exp, ok_ban = self._leg_path(s, e, ban, mode)
            if leg is None:
                self.current_path = None
                self.current_mst = None
                self.current_vias = []
                self.alt_paths = []
                if vias:
                    self.show_result(
                        "无法规划路线：%s → %s 这一路段没有可通行的道路（途经 %s）"
                        % (pts[k], pts[k + 1], "、".join(vias)))
                else:
                    self.show_result("从 %s 到 %s 目前没有可通行的道路" % (a, b))
                self.draw_graph()
                return
            if rep:
                repeat_legs.append("%s → %s" % (pts[k], pts[k + 1]))
            ast_expand += exp
            leg_specs.append((s, e, ok_ban))
            if path is None:
                path = list(leg)
            else:
                path = path + leg[1:]
            used.update(leg[:-1])
        km = self._path_km(path)
        fee = self._path_fee(path)
        names, segs = self._path_report(path, mode == "fee")
        tm = estimate_time(km, len(path) - 2)
        self.current_path = path
        self.current_mst = None
        self.current_vias = idx[1:-1]
        self.alt_paths = []
        self.current_path_color = GOLD if mode == "fee" else BLUE
        if mode == "stops":
            head = "预计车程 %s · 总里程 %d 公里 · 经停 %d 段" % (
                tm, km, len(path) - 1)
        elif mode == "fee":
            head = "预计过路费 %d 元 · 车程 %s · 总里程 %d 公里 · 途经 %d 个中转" % (
                fee, tm, km, len(path) - 2)
        else:
            head = "预计车程 %s · 总里程 %d 公里 · 途经 %d 个中转" % (
                tm, km, len(path) - 2)
        if repeat_legs:
            line = "─── 路段明细（含重复路段）───"
        else:
            line = "─── 路段明细（全程不重复）───"
        text = "%s\n%s\n%s\n%s\n%s" % (title, names, head, line, segs)
        if repeat_legs:
            text += "\n注：%s 无法做到全程不重复，已允许重复经过城市" % \
                    "、".join(repeat_legs)
        notes = []
        if mode == "km":
            dij_expand = 0
            for s0, e0, b0 in leg_specs:
                dst = []
                dijkstra(self.graph, s0, e0, b0, "km", stats=dst)
                dij_expand += dst[0]
            notes.append("算法对比：A* 扩展 %d 城 · Dijkstra 扩展 %d 城（同一查询，里程一致）"
                         % (ast_expand, dij_expand))
        if note:
            notes.append(note)
        if notes:
            text += "\n" + "\n".join(notes)
        self.show_result(text)
        self.draw_graph(path)

    def _leg_path(self, s, e, ban, mode):
        """单段查询：优先避开已走过的城市，失败则退回无禁行重查。
        返回 (路径, 是否重复经过, 成功尝试的扩展城市数, 成功尝试使用的禁行集合)。"""
        if mode == "stops":
            p, _ = bfs_min_stops(self.graph, s, e, ban)
            if p is not None:
                return p, False, 0, ban
            if not ban:
                return None, False, 0, ban
            p, _ = bfs_min_stops(self.graph, s, e, None)
            if p is None:
                return None, False, 0, None
            rep = False
            for x in p[1:-1]:
                if x in ban:
                    rep = True
                    break
            return p, rep, 0, None
        st = []
        if mode == "km":
            p, _ = astar(self.graph, s, e, ban, stats=st)
        else:
            p, _ = dijkstra(self.graph, s, e, ban, mode, stats=st)
        if p is not None:
            return p, False, st[0], ban
        if not ban:
            return None, False, st[0], ban
        st = []
        if mode == "km":
            p, _ = astar(self.graph, s, e, None, stats=st)
        else:
            p, _ = dijkstra(self.graph, s, e, None, mode, stats=st)
        if p is None:
            return None, False, st[0], None
        rep = False
        for x in p[1:-1]:
            if x in ban:
                rep = True
                break
        return p, rep, st[0], None

    def on_prim(self):
        mst_edges, total = prim_mst(self.graph)
        if mst_edges is None:
            self.current_path = None
            self.current_mst = None
            self.current_vias = []
            self.alt_paths = []
            self.show_result("当前路网不连通，无法用一条公路网覆盖所有城市")
            self.draw_graph()
            return
        names = []
        for u, v in mst_edges:
            names.append("%s — %s（%d 公里）"
                         % (CITIES[u][0], CITIES[v][0], self.graph.get_weight(u, v)))
        self.show_result(
            "最省钱公路网 · Prim 最小生成树\n─── 选中的公路（共 %d 条）───\n%s\n"
            "─── 汇总 ───\n总里程 %d 公里 · 连通全部 %d 个城市且里程最小"
            % (len(mst_edges), "\n".join(names), total, self.graph.n))
        self.current_path = None
        self.current_mst = mst_edges
        self.current_vias = []
        self.alt_paths = []
        self.draw_graph(None, mst_edges)

    def on_adjacency(self):
        self.show_result("当前路网结构（邻接表，链表存储）：\n%s"
                         % self.graph.adjacency_text())
        self.draw_graph()

    def on_alternatives(self):
        a = self.combo_from.get()
        b = self.combo_to.get()
        if a == "" or b == "":
            messagebox.showwarning("提示", "请选择出发城市和到达城市")
            return
        s = self._ci(a)
        e = self._ci(b)
        if s < 0 or e < 0:
            messagebox.showwarning("提示", "出发/到达城市不在路网中，请从下拉列表中选择")
            return
        if s == e:
            messagebox.showwarning("提示", "出发城市和到达城市不能相同")
            return
        mode = "fee" if self.mode == "cheap" else "km"
        paths, costs = k_shortest_paths(self.graph, s, e, k=3, mode=mode)
        if not paths:
            self.current_path = None
            self.current_mst = None
            self.current_vias = []
            self.alt_paths = []
            self.show_result("从 %s 到 %s 目前没有可通行的道路" % (a, b))
            self.draw_graph()
            return
        rows = []
        for k in range(len(paths)):
            p = paths[k]
            km = self._path_km(p)
            fee = self._path_fee(p)
            tm = estimate_time(km, len(p) - 2)
            chain = " → ".join(CITIES[i][0] for i in p)
            who = "推荐" if k == 0 else "备选 %d" % k
            rows.append("─── 路线 %d（%s · %d 段）───\n%s\n"
                        "预计车程 %s · 总里程 %d 公里 · 过路费 %d 元"
                        % (k + 1, who, len(p) - 1, chain, tm, km, fee))
        metric = "过路费" if mode == "fee" else "里程"
        text = "备选路线 · Yen K 短路（按%s）\n%s → %s\n%s" % (
            metric, a, b, "\n".join(rows))
        if self._via_values():
            text += "\n注：备选路线按 出发→到达 直接计算，不包含途经点"
        if len(paths) < 3:
            text += "\n注：该起终点间可用的不同路线不足 3 条"
        self.current_path = paths[0]
        self.current_mst = None
        self.current_vias = []
        self.alt_paths = paths[1:]
        self.current_path_color = GOLD if mode == "fee" else BLUE
        self.show_result(text)
        self.draw_graph(paths[0])

    def on_sort_vias(self):
        a = self.combo_from.get()
        b = self.combo_to.get()
        vias = self._via_values()
        if a == "" or b == "":
            messagebox.showwarning("提示", "请先选择出发城市和到达城市")
            return
        if len(vias) < 2:
            messagebox.showinfo("提示", "至少需要 2 个途经点才能排序")
            return
        if len(self.via_rows) != len(vias):
            messagebox.showwarning("提示", "请先填写所有途经点城市，或删除空行")
            return
        pts = [a] + vias + [b]
        idx = []
        for p in pts:
            i = self._ci(p)
            if i < 0:
                messagebox.showwarning(
                    "提示", "%s 不在路网中，请从下拉列表中选择城市" % p)
                return
            idx.append(i)
        n = len(idx)
        cost, bad = via_cost_matrix(self.graph, idx)
        if cost is None:
            messagebox.showwarning(
                "提示", "%s 与 %s 之间没有可通行的道路，无法排序"
                % (CITIES[bad[0]][0], CITIES[bad[1]][0]))
            return
        order, new_total = best_via_order(cost)
        old_total = sum(cost[k][k + 1] for k in range(n - 1))
        new_vias = [vias[k - 1] for k in order]
        if new_vias == vias:
            self.run_query(note="智能排序：当前途经顺序已是最优，估算总里程 %d 公里"
                                % new_total)
            return
        for k in range(len(self.via_rows)):
            self.via_rows[k][2].set(new_vias[k])
        self.run_query(note="智能排序：途经顺序已按里程重排，估算总里程 %d → %d 公里"
                            % (old_total, new_total))

    def on_add_road(self):
        a = self.combo_a.get()
        b = self.combo_b.get()
        if a == "" or b == "":
            messagebox.showwarning("提示", "请选择起点和终点城市")
            return
        if a == b:
            messagebox.showwarning("提示", "起点和终点不能相同")
            return
        if self.road_busy:
            return
        ak = self._ask_ak()
        if ak is None:
            messagebox.showwarning("提示", "需要百度地图 AK 才能拉取真实道路数据")
            return
        snap = {}
        for name in (a, b):
            idx = self._ci(name)
            if idx >= 0:
                snap[name] = (CITIES[idx][1], CITIES[idx][2])
        self.road_busy = True
        self.road_done = False
        self.road_result = None
        self.show_result("正在从百度拉取 %s — %s 的真实路线，新城市将自动定位…" % (a, b))
        self.status.config(text="数据源：%s    正在拉取 %s — %s 真实路线…"
                                % (self.source, a, b))
        threading.Thread(target=self._add_road_worker,
                         args=(a, b, ak, snap), daemon=True).start()
        self.root.after(100, self._poll_add_road)

    def _add_road_worker(self, a, b, ak, snap):
        lines = []
        new_cities = []
        coords = dict(snap)
        ok = True
        for name in (a, b):
            if name in coords:
                continue
            loc, err = network.geocode(name, ak)
            if loc is None:
                ok = False
                lines.append("城市 %s 定位失败：%s" % (name, err))
            else:
                lng, lat = float(loc[0]), float(loc[1])
                coords[name] = (lng, lat)
                new_cities.append((name, lng, lat))
                lines.append("已定位新城市 %s（%.4f, %.4f）" % (name, lat, lng))
        km = fee = 0
        pts = []
        if ok:
            res, err = network._driving_with_retry(
                coords[a][0], coords[a][1], coords[b][0], coords[b][1], ak)
            if res is None:
                km = geo.rough_road_km(coords[a], coords[b])
                lines.append("真实路线获取失败（%s）；已按直线距离估算 %d 公里" % (err, km))
            else:
                dist_m, toll, pts = res
                km = max(1, round(dist_m / 1000.0))
                fee = max(0, round(toll))
                lines.append("真实里程 %d 公里，过路费 %d 元，路径坐标点 %d 个"
                             % (km, fee, len(pts)))
        self.road_result = (a, b, new_cities, coords, km, fee, pts, lines, ok)
        self.road_done = True

    def _poll_add_road(self):
        if not self.road_done:
            self.root.after(100, self._poll_add_road)
            return
        self.road_busy = False
        a, b, new_cities, coords, km, fee, pts, lines, ok = self.road_result
        if not ok:
            self.update_status()
            self.show_result("新增道路失败：\n%s" % "\n".join(lines))
            return
        rec = {"op": "add", "a": a, "b": b, "road": (a, b, km, fee),
               "new_cities": new_cities, "pts": pts,
               "snap": self._snapshot_road_side(a, b)}
        self._commit_road_add(rec)
        self.show_result("已新增道路：%s — %s，里程 %d 公里，过路费 %d 元\n%s\n"
                         "已写入 road_network_cache.json，重启后依然存在；"
                         "可点击“撤销编辑”回退"
                         % (a, b, km, fee, "\n".join(lines)))

    def _commit_road_add(self, rec):
        """执行一次“新增道路”并记入撤销历史（拉取完成回调与测试共用入口）。"""
        self._apply_road_add(rec)
        self.hist.push(rec)
        self._after_edit()

    def on_delete_road(self):
        a = self.combo_a.get()
        b = self.combo_b.get()
        if a == "" or b == "" or a == b:
            messagebox.showwarning("提示", "请选择两个不同的城市")
            return
        if self.road_busy:
            return
        ia = self._ci(a)
        ib = self._ci(b)
        if ia < 0 or ib < 0:
            messagebox.showwarning("提示", "请从下拉列表中选择路网中的城市")
            return
        idx = -1
        for i, r in enumerate(ROADS):
            if r[:2] in ((a, b), (b, a)):
                idx = i
                break
        if idx < 0:
            self.show_result("道路 %s — %s 不存在，无需删除" % (a, b))
            return
        rec = {"op": "del", "a": a, "b": b, "road_idx": idx,
               "road": ROADS[idx], "snap": self._snapshot_road_side(a, b)}
        still = self._apply_road_del(rec)
        self.hist.push(rec)
        self._after_edit()
        if still:
            self.show_result("已删除一条道路：%s — %s（该路段剩余平行路，已同步缓存）\n"
                             "可点击“撤销编辑”恢复" % (a, b))
        else:
            self.show_result("已删除道路：%s — %s（已从缓存移除，重启后不再出现）\n"
                             "可点击“撤销编辑”恢复" % (a, b))

    # ── 道路编辑：操作记录与撤销/重做（双栈历史，见数据结构模块 EditHistory） ──

    def _snapshot_road_side(self, a, b):
        """快照 (a,b) 道路关联的曲线与几何点（含反向键），供撤销时恢复。"""
        pa = a + "-" + b + "-"
        pb = b + "-" + a + "-"
        pts = {}
        for k, v in ROUTE_POINTS.items():
            if k.startswith(pa) or k.startswith(pb):
                pts[k] = v
        return {"curve_ab": ROUTE_CURVES.get((a, b)),
                "curve_ba": ROUTE_CURVES.get((b, a)),
                "points": pts}

    def _remove_road_side(self, a, b):
        ROUTE_CURVES.pop((a, b), None)
        ROUTE_CURVES.pop((b, a), None)
        pa = a + "-" + b + "-"
        pb = b + "-" + a + "-"
        for k in [k for k in ROUTE_POINTS
                  if k.startswith(pa) or k.startswith(pb)]:
            del ROUTE_POINTS[k]

    def _restore_road_side(self, a, b, snap):
        self._remove_road_side(a, b)
        if snap["curve_ab"] is not None:
            ROUTE_CURVES[(a, b)] = snap["curve_ab"]
        if snap["curve_ba"] is not None:
            ROUTE_CURVES[(b, a)] = snap["curve_ba"]
        ROUTE_POINTS.update(snap["points"])

    def _apply_road_add(self, rec):
        """正向执行“新增道路”：补入新城市、追加道路、写入几何点与曲线。"""
        a, b = rec["a"], rec["b"]
        for name, lng, lat in rec["new_cities"]:
            CITIES.append((name, lng, lat))
        rec["road_idx"] = len(ROADS)
        ROADS.append(rec["road"])
        pts = rec["pts"]
        if pts:
            stops = []
            for i in range(len(pts)):
                key = "%s-%s-%d" % (a, b, i + 1)
                ROUTE_POINTS[key] = (float(pts[i][0]), float(pts[i][1]))
                stops.append(key)
            ROUTE_CURVES[(a, b)] = stops

    def _revert_road_add(self, rec):
        """撤销“新增道路”：移除道路与本次新增的城市，恢复被覆盖的曲线与点。"""
        a, b = rec["a"], rec["b"]
        i = rec.get("road_idx", -1)
        if 0 <= i < len(ROADS) and ROADS[i] is rec["road"]:
            del ROADS[i]
        else:
            for k in range(len(ROADS) - 1, -1, -1):
                if ROADS[k][:2] in ((a, b), (b, a)):
                    del ROADS[k]
                    break
        for name, _lng, _lat in reversed(rec["new_cities"]):
            if len(CITIES) > 0 and CITIES[-1][0] == name:
                CITIES.pop()
        self._restore_road_side(a, b, rec["snap"])

    def _apply_road_del(self, rec):
        """正向执行“删除道路”：移除一条道路；无平行路时同步清掉曲线与点。
        返回是否仍有平行路（供结果文案区分）。"""
        a, b = rec["a"], rec["b"]
        i = rec["road_idx"]
        if not (0 <= i < len(ROADS)) or ROADS[i][:2] not in ((a, b), (b, a)):
            i = -1
            for k in range(len(ROADS) - 1, -1, -1):
                if ROADS[k][:2] in ((a, b), (b, a)):
                    i = k
                    break
            if i < 0:
                return False
        del ROADS[i]
        still = False
        for r in ROADS:
            if r[:2] in ((a, b), (b, a)):
                still = True
                break
        if not still:
            self._remove_road_side(a, b)
        return still

    def _revert_road_del(self, rec):
        """撤销“删除道路”：把道路插回原下标，并恢复当时清掉的曲线与点。"""
        i = rec["road_idx"]
        if not (0 <= i <= len(ROADS)):
            i = len(ROADS)
        ROADS.insert(i, rec["road"])
        self._restore_road_side(rec["a"], rec["b"], rec["snap"])

    def _after_edit(self):
        """编辑（增/删/撤销/重做）后的统一收尾：重建图与索引、同步缓存与界面。"""
        self.graph = structures.build_graph()
        network._save_cache(CITIES, ROADS, ROUTE_POINTS, ROUTE_CURVES)
        self.current_path = None
        self.current_mst = None
        self.current_vias = []
        self.alt_paths = []
        self.refresh_names()
        self.update_status()
        self.draw_graph()

    def on_undo_edit(self):
        if self.road_busy:
            self.show_result("正在拉取道路数据，请稍候再撤销")
            return
        rec = self.hist.undo()
        if rec is None:
            self.show_result("没有可撤销的编辑（撤销栈为空）")
            return
        if rec["op"] == "add":
            self._revert_road_add(rec)
            what = "新增"
        else:
            self._revert_road_del(rec)
            what = "删除"
        self._after_edit()
        self.show_result("已撤销%s道路：%s — %s\n路网与缓存已恢复；可点击“重做编辑”再次执行"
                         % (what, rec["a"], rec["b"]))

    def on_redo_edit(self):
        if self.road_busy:
            self.show_result("正在拉取道路数据，请稍候再重做")
            return
        rec = self.hist.redo()
        if rec is None:
            self.show_result("没有可重做的编辑（重做栈为空）")
            return
        if rec["op"] == "add":
            self._apply_road_add(rec)
            what = "新增"
        else:
            self._apply_road_del(rec)
            what = "删除"
        self._after_edit()
        self.show_result("已重做%s道路：%s — %s" % (what, rec["a"], rec["b"]))

    def reset_highlight(self):
        self.current_path = None
        self.current_mst = None
        self.current_vias = []
        self.alt_paths = []
        self.draw_graph()
        self.show_result("已清空高亮。选择出发/途经/到达城市与上方规划方式后，点击“查询”即可。")

    def refresh_names(self):
        names = [CITIES[i][0] for i in range(len(CITIES))]
        self.city_bst = structures.BinSearchTree()
        for i in range(len(names)):
            self.city_bst.insert(names[i], i)
        self.combo_from.set_values(names)
        self.combo_to.set_values(names)
        for _, _, pk in self.via_rows:
            pk.set_values(names)
        self.combo_a.set_values(names)
        self.combo_b.set_values(names)

    def start_import(self):
        cache = network._load_cache()
        if cache is not None:
            self._import_done(cache + (0,),
                              ["已从本地缓存加载路网（road_network_cache.json），"
                               "无需重新请求百度接口"])
            return
        self.on_import_real()

    def _ask_ak(self):
        ak = self.ak.strip()
        if ak != "" and ak != AK_PLACEHOLDER:
            return ak
        ak = simpledialog.askstring(
            "百度地图 AK",
            "请在 basic_data/data.py 顶部把 BAIDU_AK 常量改为你的百度地图开放平台 AK；\n"
            "或在此临时输入本次使用（lbsyun.baidu.com 免费申请）：",
            parent=self.root, initialvalue="")
        if ak is None or ak.strip() == "":
            return None
        return ak.strip()

    def on_import_real(self):
        ak = self._ask_ak()
        if ak is None:
            self.show_result("未导入路网：需要百度地图 AK。\n"
                             "获取方式：lbsyun.baidu.com 注册应用后复制 AK，"
                             "填入 basic_data/data.py 顶部 BAIDU_AK = \"...\"，重启程序即可自动导入真实路网。")
            return
        self.do_import(ak)

    def do_import(self, ak):
        self.ak = ak
        self.import_done = False
        self.import_result = None
        self.import_lines = []
        self.show_result("正在从百度地图并行拉取真实路网（%d 城 / %d 路，约需 1~2 分钟），界面保持可用…"
                         % (len(CITY_NAMES), len(ROAD_PAIRS)))
        self.status.config(text="数据源：%s    正在导入真实路网…" % self.source)
        self.root.update()
        t = threading.Thread(target=self._import_worker, args=(ak,), daemon=True)
        t.start()
        self.root.after(100, self._poll_import)

    def _import_worker(self, ak):
        lines = []
        result = network.fetch_real_network(ak, lines.append)
        self.import_result = result
        self.import_lines = lines
        self.import_done = True

    def _poll_import(self):
        if not self.import_done:
            self.root.after(100, self._poll_import)
            return
        self._import_done(self.import_result, self.import_lines)

    def _import_done(self, result, lines):
        if result is None:
            self.show_result("\n".join(lines))
            self.update_status()
            return
        new_cities, new_roads, new_points, new_curves, fail = result
        CITIES[:] = new_cities
        ROADS[:] = new_roads
        ROUTE_POINTS.clear()
        ROUTE_POINTS.update(new_points)
        ROUTE_CURVES.clear()
        ROUTE_CURVES.update(new_curves)
        geo.reset_view(self.canvas.winfo_width(), self.canvas.winfo_height())
        self.graph = structures.build_graph()
        self.source = "百度真实路网"
        self.hist.clear()
        self.refresh_names()
        self.update_status()
        self.draw_graph()
        network._save_cache(new_cities, new_roads, new_points, new_curves)
        self.show_result("已导入百度真实路网并基于导入数据建模（源码不含任何虚构数值）\n%s\n\n"
                         "真实城市 %d 个、真实公路 %d 条（%d 条获取失败，已按直线距离临时估算）\n"
                         "路网已缓存到 road_network_cache.json，下次启动将秒级加载"
                         % ("\n".join(lines), len(new_cities), len(new_roads), fail))
