"""
基础数据定义模块 —— 真实路网获取与缓存

通过百度地图开放平台接口获取真实数据，供主程序导入路网使用：
  · geocode     城市名称 → 经纬度（地理编码接口）
  · driving     两城市间驾车路线（里程 / 过路费 / 路径点串）
  · fetch_all   批量抓取整张路网（多线程 + 限速 + 重试 + 直线距离估算兜底）
  · _load_cache / _save_cache   road_network_cache.json 的读写与指纹校验
                 （缓存文件位于项目根目录，指纹由静态数据集计算，用于识别数据变更）；
                 读取时逐条校验（名称非空、坐标/里程/费用合法、键格式正确），
                 损坏文件或非法记录自动跳过/拒绝，保证加载失败不会导致程序崩溃

说明：路径点抽稀（Douglas-Peucker）与直线距离估算已迁移至核心算法模块
core_algorithms/geometry.py（simplify_route / rough_road_km），本模块直接调用。
"""

import concurrent.futures
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from basic_data import data
from core_algorithms import geometry

_MAX_RPS = 5

_throttle_lock = threading.Lock()
_req_times = []


def _throttle():
    with _throttle_lock:
        now = time.time()
        _req_times[:] = [t for t in _req_times if now - t < 1.0]
        while len(_req_times) >= _MAX_RPS:
            wait = 1.0 - (now - _req_times[0])
            if wait <= 0:
                _req_times[:] = [t for t in _req_times if now - t < 1.0]
                continue
            time.sleep(wait)
            now = time.time()
            _req_times[:] = [t for t in _req_times if now - t < 1.0]
        _req_times.append(now)


def http_get_json(url):
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def geocode(name, ak):
    url = "https://api.map.baidu.com/geocoding/v3/?" + urllib.parse.urlencode(
        {"address": name, "output": "json", "ak": ak})
    try:
        resp = http_get_json(url)
    except Exception as e:
        return None, "网络请求失败：%s" % e
    if resp.get("status") != 0:
        return None, "百度返回 status=%s：%s" % (resp.get("status"), resp.get("message", "无说明"))
    loc = resp["result"]["location"]
    return (float(loc["lng"]), float(loc["lat"])), None


def _parse_path_field(path_str):
    pts = []
    if not path_str:
        return pts
    for chunk in path_str.split(";"):
        parts = chunk.strip().split(",")
        if len(parts) != 2:
            continue
        try:
            pts.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return pts


def _step_samples(steps):
    raw = []
    for step in steps:
        seg = _parse_path_field(step.get("path"))
        if not seg:
            loc = step.get("start_location") or step.get("end_location")
            if loc is not None:
                seg = [(float(loc["lng"]), float(loc["lat"]))]
        for p in seg:
            if not raw or raw[-1] != p:
                raw.append(p)
    return raw


def driving(a_lng, a_lat, b_lng, b_lat, ak):
    url = "https://api.map.baidu.com/directionlite/v1/driving?" + urllib.parse.urlencode(
        {"origin": "%f,%f" % (a_lat, a_lng),
         "destination": "%f,%f" % (b_lat, b_lng),
         "ak": ak})
    try:
        resp = http_get_json(url)
    except Exception as e:
        return None, "网络请求失败：%s" % e
    if resp.get("status") != 0:
        return None, "百度返回 status=%s：%s" % (resp.get("status"), resp.get("message", "无说明"))
    route = resp["result"]["routes"][0]
    dist_m = float(route.get("distance", 0))
    toll = float(route.get("toll", 0))
    raw = _step_samples(route.get("steps", []))
    pts = geometry.simplify_route(raw) if len(raw) >= 2 else []
    return (dist_m, toll, pts), None


def _geo_once(name, ak):
    try:
        return geocode(name, ak)
    except Exception as e:
        return None, "未知异常：%s" % e


def _geo_with_retry(name, ak):
    loc, err = None, "未执行"
    for attempt in range(3):
        loc, err = _geo_once(name, ak)
        if loc is not None:
            break
        time.sleep(1.0)
    return loc, err


def _driving_once(alng, alat, blng, blat, ak):
    try:
        return driving(alng, alat, blng, blat, ak)
    except Exception as e:
        return None, "未知异常：%s" % e


def _driving_with_retry(alng, alat, blng, blat, ak):
    res, err = None, "未执行"
    for attempt in range(3):
        res, err = _driving_once(alng, alat, blng, blat, ak)
        if res is not None:
            break
        time.sleep(1.0)
    return res, err


def fetch_real_network(ak, report):
    cities = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        geo_futs = [pool.submit(_geo_with_retry, name, ak) for name in data.CITY_NAMES]
        for name, fut in zip(data.CITY_NAMES, geo_futs):
            loc, err = fut.result()
            if loc is None:
                report("城市 %s 坐标获取失败（已重试3次）：%s" % (name, err))
            else:
                report("城市 %s 真实坐标 (%.4f, %.4f)" % (name, float(loc[0]), float(loc[1])))
                cities.append((name, float(loc[0]), float(loc[1])))
    if len(cities) == 0:
        report("所有城市坐标获取失败，请检查 AK 与网络")
        return None
    roads = []
    points = {}
    curves = {}
    fail = 0
    tasks = []
    pos = {}
    for nc, clng, clat in cities:
        pos[nc] = (clng, clat)
    for a, b in data.ROAD_PAIRS:
        ca = pos.get(a)
        cb = pos.get(b)
        if ca is None or cb is None:
            report("公路 %s—%s 城市坐标缺失，已跳过" % (a, b))
            continue
        tasks.append((a, b, ca, cb))
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        drive_futs = {}
        for a, b, ca, cb in tasks:
            drive_futs[(a, b)] = pool.submit(
                _driving_with_retry, ca[0], ca[1], cb[0], cb[1], ak)
        for a, b, ca, cb in tasks:
            res, err = drive_futs[(a, b)].result()
            if res is None:
                fail += 1
                km = geometry.rough_road_km(ca, cb)
                roads.append((a, b, km, 0))
                report("公路 %s—%s 路线获取失败（已重试3次）：%s；按直线距离临时估算 %d 公里"
                       % (a, b, err, km))
                continue
            dist_m, toll, pts = res
            km = max(1, round(dist_m / 1000.0))
            toll = max(0, round(toll))
            stops = []
            for i in range(len(pts)):
                key = "%s-%s-%d" % (a, b, i + 1)
                points[key] = (float(pts[i][0]), float(pts[i][1]))
                stops.append(key)
            roads.append((a, b, km, toll))
            curves[(a, b)] = stops
            report("公路 %s—%s 真实里程 %d 公里，过路费 %d 元，路径坐标点 %d 个"
                   % (a, b, km, toll, len(stops)))
    if len(roads) == 0:
        report("所有公路路线获取失败，请检查 AK 与网络")
        return None
    return cities, roads, points, curves, fail


CACHE_FILE = ""


def _cache_path():
    global CACHE_FILE
    if CACHE_FILE == "":
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        CACHE_FILE = os.path.join(root, "road_network_cache.json")
    return CACHE_FILE


def _cache_fingerprint():
    s = "v2|" + "|".join(data.CITY_NAMES)
    for a, b in data.ROAD_PAIRS:
        s += "|%s>%s" % (a, b)
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) % 1000000007
    return str(h)


def _save_cache(cities, roads, points, curves):
    payload = {
        "fingerprint": _cache_fingerprint(),
        "cities": [[c[0], float(c[1]), float(c[2])] for c in cities],
        "roads": [[r[0], r[1], r[2], r[3] if len(r) > 3 else 0] for r in roads],
        "points": {k: [float(v[0]), float(v[1])] for k, v in points.items()},
        "curves": {"%s|%s" % (a, b): list(v) for (a, b), v in curves.items()},
    }
    try:
        with open(_cache_path(), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return True
    except Exception:
        return False


def _load_cache():
    """读取缓存并逐条校验合法性；文件损坏、结构错误或指纹不符时返回 None，
    单条记录非法（坐标越界、里程非正、类型错误等）时跳过该条而非整体失败。"""
    try:
        with open(_cache_path(), "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        if payload.get("fingerprint") != _cache_fingerprint():
            return None
        cities = []
        for c in payload.get("cities", []):
            try:
                if len(c) < 3:
                    continue
                name = str(c[0]).strip()
                lng = float(c[1])
                lat = float(c[2])
            except (TypeError, ValueError):
                continue
            if name == "" or not (-180.0 <= lng <= 180.0) or not (-90.0 <= lat <= 90.0):
                continue
            cities.append((name, lng, lat))
        roads = []
        for r in payload.get("roads", []):
            try:
                if len(r) < 3:
                    continue
                a = str(r[0]).strip()
                b = str(r[1]).strip()
                km = int(r[2])
                fee = int(r[3]) if len(r) > 3 else 0
            except (TypeError, ValueError):
                continue
            if a == "" or b == "" or a == b or km <= 0 or fee < 0:
                continue
            roads.append((a, b, km, fee))
        points = {}
        for k, v in payload.get("points", {}).items():
            try:
                lng = float(v[0])
                lat = float(v[1])
            except (TypeError, ValueError, IndexError):
                continue
            if -180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0:
                points[k] = (lng, lat)
        curves = {}
        for k, v in payload.get("curves", {}).items():
            if not isinstance(k, str) or "|" not in k or not isinstance(v, list):
                continue
            a, b = k.split("|", 1)
            curves[(a, b)] = v
        if len(cities) == 0 or len(roads) == 0:
            return None
        return cities, roads, points, curves
    except Exception:
        return None
