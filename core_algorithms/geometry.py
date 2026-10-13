"""
核心算法模块 —— 计算几何与视图变换算法

本文件收录路网系统用到的计算几何算法（由原 gui_app/geo.py 与 network.py 迁入）：
  · 投影变换   lonlat_xy / xy_lonlat      墨卡托投影正/反换算
  · 视图变换   zoom_around / pan / reset_view / canvas_xy
               以光标为中心的固定点仿射缩放、平移、按实际画布尺寸重置取景
  · 曲线算法   dedupe_pts / chaikin / catmull_rom
               折线去重、Chaikin 角切平滑、向心 Catmull-Rom 样条插值
  · 距离算法   haversine_km / rough_road_km   大圆距离、直线距离估算公路里程
  · 几何查询   dist_to_polyline / flatten_pts 点到折线最短距离（悬停拾取）、点串展平
  · 折线简化   rdp / simplify_route           Douglas-Peucker 抽稀与限点数简化
  · 空间索引   build_curve_grid / pick_curve  均匀网格索引加速最近折线查询（悬停拾取）

说明：GUI 中的鼠标事件绑定（拖动/滚轮）属交互逻辑，保留在 gui_app/gui.py；
本文件只负责其中涉及的坐标变换与几何计算。
"""

import math

from basic_data import data

_PROJ = None
_BASE_S = 0.0
_VIEW_W = 840.0
_VIEW_H = 560.0


# ---------------------------------------------------------------- 投影变换

def _ensure_proj():
    global _PROJ, _BASE_S
    if _PROJ is not None:
        return
    if len(data.CITIES) == 0:
        lons = [84.0, 126.0]
        lats = [22.0, 46.0]
    else:
        lons = []
        lats = []
        for c in data.CITIES:
            lons.append(float(c[1]))
            lats.append(float(c[2]))
    R = 6378137.0

    def mx(lon):
        return math.radians(lon) * R

    def my(lat):
        return R * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))

    xs = [mx(l) for l in lons]
    ys = [my(a) for a in lats]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad = 34.0
    s = min((_VIEW_W - 2 * pad) / (x1 - x0), (_VIEW_H - 2 * pad) / (y1 - y0))
    _BASE_S = s
    _PROJ = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, s, R,
             _VIEW_W / 2.0, _VIEW_H / 2.0)


def _safe_lat(lat):
    if lat > 85.0:
        return 85.0
    if lat < -85.0:
        return -85.0
    return lat


def lonlat_xy(lon, lat):
    _ensure_proj()
    cx, cy, s, R, px, py = _PROJ
    x = (math.radians(float(lon)) * R - cx) * s + px
    y = (cy - R * math.log(math.tan(math.pi / 4.0 + math.radians(float(lat)) / 2.0))) * s + py
    return x, y


def xy_lonlat(x, y):
    _ensure_proj()
    cx, cy, s, R, px, py = _PROJ
    xr = (x - px) / s + cx
    yr = cy - (y - py) / s
    lon = math.degrees(xr / R)
    k = yr / R
    if k > 300.0:
        lat = 85.0
    elif k < -300.0:
        lat = -85.0
    else:
        lat = math.degrees(2.0 * math.atan(math.exp(k)) - math.pi / 2.0)
        lat = _safe_lat(lat)
    return lon, lat


def canvas_xy(i):
    return lonlat_xy(data.CITIES[i][1], data.CITIES[i][2])


# ---------------------------------------------------------------- 视图变换

def zoom_around(mx, my, factor):
    global _PROJ
    _ensure_proj()
    lon, lat = xy_lonlat(mx, my)
    lat = _safe_lat(lat)
    cx, cy, s, R, px, py = _PROJ
    ns = s * factor
    if ns < _BASE_S / 4.0:
        ns = _BASE_S / 4.0
    if ns > _BASE_S * 16.0:
        ns = _BASE_S * 16.0
    npx = mx - (math.radians(lon) * R - cx) * ns
    npy = my - (cy - R * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))) * ns
    _PROJ = (cx, cy, ns, R, npx, npy)


def pan(dx, dy):
    global _PROJ
    _ensure_proj()
    cx, cy, s, R, px, py = _PROJ
    _PROJ = (cx, cy, s, R, px + dx, py + dy)


def reset_view(w=0, h=0):
    global _PROJ, _VIEW_W, _VIEW_H
    _PROJ = None
    if w > 100 and h > 100:
        _VIEW_W = float(w)
        _VIEW_H = float(h)


# ---------------------------------------------------------------- 曲线算法

def dedupe_pts(pts, min_gap=0.75):
    out = []
    for x, y in pts:
        if out:
            dx = x - out[-1][0]
            dy = y - out[-1][1]
            if dx * dx + dy * dy < min_gap * min_gap:
                continue
        out.append((x, y))
    if len(out) < 2 and pts:
        out = [pts[0], pts[-1]]
    return out


def chaikin(pts, iters=2):
    out = list(pts)
    for _ in range(iters):
        if len(out) < 3:
            return out
        nxt = [out[0]]
        for i in range(len(out) - 1):
            x1, y1 = out[i]
            x2, y2 = out[i + 1]
            nxt.append((x1 * 0.75 + x2 * 0.25, y1 * 0.75 + y2 * 0.25))
            nxt.append((x1 * 0.25 + x2 * 0.75, y1 * 0.25 + y2 * 0.75))
        nxt.append(out[-1])
        out = nxt
    return out


def catmull_rom(pts, samples=16, alpha=0.5):
    n = len(pts)
    if n < 3:
        return list(pts)

    def knot(a, b):
        d = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
        if d < 1e-6:
            d = 1e-6
        return d ** alpha

    out = [pts[0]]
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else p2
        t1 = 0.0
        t2 = t1 + knot(p1, p2)
        t0 = t1 - knot(p0, p1)
        t3 = t2 + knot(p2, p3)
        for s in range(1, samples + 1):
            t = t1 + (t2 - t1) * s / samples
            a1x = (t1 - t) / (t1 - t0) * p0[0] + (t - t0) / (t1 - t0) * p1[0]
            a1y = (t1 - t) / (t1 - t0) * p0[1] + (t - t0) / (t1 - t0) * p1[1]
            a2x = (t2 - t) / (t2 - t1) * p1[0] + (t - t1) / (t2 - t1) * p2[0]
            a2y = (t2 - t) / (t2 - t1) * p1[1] + (t - t1) / (t2 - t1) * p2[1]
            a3x = (t3 - t) / (t3 - t2) * p2[0] + (t - t2) / (t3 - t2) * p3[0]
            a3y = (t3 - t) / (t3 - t2) * p2[1] + (t - t2) / (t3 - t2) * p3[1]
            b1x = (t2 - t) / (t2 - t0) * a1x + (t - t0) / (t2 - t0) * a2x
            b1y = (t2 - t) / (t2 - t0) * a1y + (t - t0) / (t2 - t0) * a2y
            b2x = (t3 - t) / (t3 - t1) * a2x + (t - t1) / (t3 - t1) * a3x
            b2y = (t3 - t) / (t3 - t1) * a2y + (t - t1) / (t3 - t1) * a3y
            cx = (t2 - t) / (t2 - t1) * b1x + (t - t1) / (t2 - t1) * b2x
            cy = (t2 - t) / (t2 - t1) * b1y + (t - t1) / (t2 - t1) * b2y
            out.append((cx, cy))
    out.append(pts[-1])
    return out


# ---------------------------------------------------------------- 距离算法

def haversine_km(lng1, lat1, lng2, lat2):
    """两点经纬度间的大圆距离（千米），用作 A* 的可采纳启发式与直线估算基础。"""
    R = 6371.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    h = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * R * math.asin(min(1.0, math.sqrt(h)))


def rough_road_km(ca, cb):
    """直线距离估算公路里程：大圆距离 × 1.25 绕行系数（接口失败时的兜底估算）。"""
    return max(1, round(haversine_km(ca[0], ca[1], cb[0], cb[1]) * 1.25))


# ---------------------------------------------------------------- 几何查询

def flatten_pts(pts):
    out = []
    for x, y in pts:
        out.append(x)
        out.append(y)
    return out


def dist_to_polyline(x, y, pts):
    best = 1e18
    for i in range(len(pts) - 1):
        x1, y1 = pts[i]
        x2, y2 = pts[i + 1]
        dx = x2 - x1
        dy = y2 - y1
        seg2 = dx * dx + dy * dy
        if seg2 < 1e-9:
            d = ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
        else:
            t = ((x - x1) * dx + (y - y1) * dy) / seg2
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0
            px = x1 + t * dx
            py = y1 + t * dy
            d = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
        if d < best:
            best = d
    return best


# ---------------------------------------------------------------- 折线简化

def rdp(pts, eps):
    """Douglas-Peucker 折线抽稀：保留所有到首尾连线距离超过 eps 的特征点。"""
    n = len(pts)
    if n < 3:
        return list(pts)
    keep = [False] * n
    keep[0] = keep[n - 1] = True
    eps2 = eps * eps
    stack = [(0, n - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        x1, y1 = pts[i]
        x2, y2 = pts[j]
        dx = x2 - x1
        dy = y2 - y1
        d2 = dx * dx + dy * dy
        best = -1.0
        bi = -1
        for k in range(i + 1, j):
            x, y = pts[k]
            if d2 < 1e-12:
                dd = (x - x1) ** 2 + (y - y1) ** 2
            else:
                t = ((x - x1) * dx + (y - y1) * dy) / d2
                if t < 0.0:
                    t = 0.0
                elif t > 1.0:
                    t = 1.0
                dd = (x - (x1 + t * dx)) ** 2 + (y - (y1 + t * dy)) ** 2
            if dd > best:
                best = dd
                bi = k
        if best > eps2 and bi > 0:
            keep[bi] = True
            stack.append((i, bi))
            stack.append((bi, j))
    out = []
    for k in range(n):
        if keep[k]:
            out.append(pts[k])
    return out


def simplify_route(raw, limit=160, base_eps=0.004):
    """路线限点数简化：先按 base_eps 抽稀，若仍超过 limit 则逐步放大容差重抽。"""
    pts = rdp(raw, base_eps)
    eps = base_eps
    while len(pts) > limit and eps < 0.08:
        eps *= 1.6
        pts = rdp(raw, eps)
    return pts


# ---------------------------------------------------------------- 空间索引

def build_curve_grid(curves, cell=20.0):
    """均匀网格空间索引：把每条折线的每个线段按其包围盒注册进网格单元。

    悬停拾取原本要对全部折线逐线段算距离（O(全部线段)），建格后查询
    只需检查光标所在单元及其邻域（O(邻近线段)）。线段按包围盒注册，
    跨越单元边界的线段在相邻单元中同样查得到；同一曲线在同一单元内
    连续注册，用“与上一个键相同则跳过”去重。
    返回 (cell, 网格字典)，网格字典为 {(单元x, 单元y): [曲线键, ...]}。
    """
    grid = {}
    for key, pts in curves.items():
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]
            gx0 = int(min(x1, x2) // cell)
            gx1 = int(max(x1, x2) // cell)
            gy0 = int(min(y1, y2) // cell)
            gy1 = int(max(y1, y2) // cell)
            for gx in range(gx0, gx1 + 1):
                for gy in range(gy0, gy1 + 1):
                    lst = grid.get((gx, gy))
                    if lst is None:
                        grid[(gx, gy)] = [key]
                    elif lst[-1] != key:
                        lst.append(key)
    return cell, grid


def pick_curve(curves, grid, x, y, radius=14.0):
    """借助网格索引查询距 (x, y) 最近且在 radius 以内的曲线。

    从光标所在单元起逐环向外扩展（第 r 环到光标的距离下界为 (r-1)×cell），
    一旦下界不小于当前最优距离即停止，因此结果与全量暴力扫描一致，
    仅在距离完全相等的并列情况下存在先访顺序差异。精确距离只用
    dist_to_polyline 在候选曲线上计算。返回 (曲线键, 最近距离)，
    未命中时曲线键为 None、距离为 radius。
    """
    cell, cells = grid
    cx = int(x // cell)
    cy = int(y // cell)
    best = None
    best_d = radius
    seen = set()
    r = 0
    while True:
        if r > 0 and (r - 1) * cell >= best_d:
            break
        if r == 0:
            ring = ((cx, cy),)
        else:
            ring = []
            for gx in range(cx - r, cx + r + 1):
                ring.append((gx, cy - r))
                ring.append((gx, cy + r))
            for gy in range(cy - r + 1, cy + r):
                ring.append((cx - r, gy))
                ring.append((cx + r, gy))
        for gc in ring:
            for key in cells.get(gc, ()):
                if key in seen:
                    continue
                seen.add(key)
                d = dist_to_polyline(x, y, curves[key])
                if d < best_d:
                    best_d = d
                    best = key
        r += 1
    return best, best_d
