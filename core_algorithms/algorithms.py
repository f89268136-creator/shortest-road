"""
核心算法模块

本文件实现路网系统使用的核心图算法与组合优化算法（均基于数据结构模块的自建结构）：
  · dijkstra        单源最短路径（可指定按“里程”或“过路费”作权重，
                    支持 forbidden 禁行城市集合，用于多途经点分段与全程不重复约束；
                    支持 forbidden_edges 禁用边集合，用于 Yen 备选路线；
                    stats 参数可收集“扩展城市数”用于与 A* 对比）
  · dijkstra_all    单源最短路到全部城市（一次运行求出起点到所有城市的最短距离，
                    批量查询多目标时替代逐对调用 dijkstra，由 n² 次降为 n 次）
  · astar           A* 启发式搜索（以到终点的直线距离作可采纳启发式引导，
                    里程权重下与 Dijkstra 结果完全一致，但扩展城市数更少）
  · k_shortest_paths  Yen 算法求 K 条互不相同的最短路径（备选路线推荐）
  · best_via_order  回溯 + 剪枝求途经点最优访问顺序（小型旅行商问题）
  · via_cost_matrix 途经点排序代价矩阵（n 次单源最短路构建 n×n 矩阵）
  · bfs_min_stops   广度优先搜索最少经停路线（以链式队列实现）
  · prim_mst        最小生成树（二叉堆选边，得到“最省钱公路网”）
  · estimate_time   根据总里程与经停段数估算预计车程
  · _path_cost      按里程/过路费计算一条完整路径总代价的辅助函数

所有算法入口均做下标边界检查与空输入保护：起点/终点越界、空代价矩阵等
非法输入安全返回 None / 空结果（stats 仍会回填 0），保证调用方不因脏数据崩溃。
"""

from basic_data import data
from core_algorithms import geometry
from data_structures.structures import MinHeap, Queue


def dijkstra(graph, start, end, forbidden=None, mode="km",
             forbidden_edges=None, stats=None):
    INF = 10 ** 9
    n = graph.n
    if not (0 <= start < n) or not (0 <= end < n):
        if stats is not None:
            stats.append(0)
        return None, None
    dist = [INF] * n
    prev = [-1] * n
    done = [False] * n
    dist[start] = 0
    expanded = 0
    pq = MinHeap()
    pq.push((0, start))
    while not pq.empty():
        d, u = pq.pop()
        if done[u]:
            continue
        done[u] = True
        expanded += 1
        if u == end:
            break
        p = graph.adj[u].head
        while p is not None:
            v = p.city
            if forbidden_edges is not None and ((u, v) in forbidden_edges
                                                or (v, u) in forbidden_edges):
                p = p.next
                continue
            w = p.dist if mode == "km" else p.fee
            if not done[v] and (forbidden is None or v not in forbidden
                                or v == start or v == end) and d + w < dist[v]:
                dist[v] = d + w
                prev[v] = u
                pq.push((dist[v], v))
            p = p.next
    if stats is not None:
        stats.append(expanded)
    if dist[end] >= INF:
        return None, None
    path = []
    cur = end
    while cur != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path, dist[end]


def dijkstra_all(graph, start, mode="km", forbidden=None):
    """单源最短路：一次运行求出 start 到全部城市的最短距离。

    与 dijkstra 的差异是“不设终点、不提前截断”，适合批量多目标查询
    （如途经点排序的代价矩阵）：求得距离数组后，任意目标城市按 O(1) 取值，
    总共 n 次运行即可替代 n² 次两两 dijkstra。返回距离列表，不可达为 10^9；
    start 越界时安全返回 None。
    """
    INF = 10 ** 9
    n = graph.n
    if not (0 <= start < n):
        return None
    dist = [INF] * n
    done = [False] * n
    dist[start] = 0
    pq = MinHeap()
    pq.push((0, start))
    while not pq.empty():
        d, u = pq.pop()
        if done[u]:
            continue
        done[u] = True
        p = graph.adj[u].head
        while p is not None:
            v = p.city
            w = p.dist if mode == "km" else p.fee
            if not done[v] and (forbidden is None or v not in forbidden
                                or v == start) and d + w < dist[v]:
                dist[v] = d + w
                pq.push((dist[v], v))
            p = p.next
    return dist


def astar(graph, start, end, forbidden=None, stats=None):
    n = graph.n
    if not (0 <= start < n) or not (0 <= end < n):
        if stats is not None:
            stats.append(0)
        return None, None
    goal = data.CITIES[end]
    glng = float(goal[1])
    glat = float(goal[2])

    def h(u):
        c = data.CITIES[u]
        # × 0.98 吸收里程取整误差（路网中最短公路远大于 25 公里），
        # 保证启发式一致性，从而与 Dijkstra 结果完全一致
        return 0.98 * geometry.haversine_km(float(c[1]), float(c[2]), glng, glat)

    INF = 10 ** 9
    dist = [INF] * n
    prev = [-1] * n
    done = [False] * n
    dist[start] = 0
    expanded = 0
    pq = MinHeap()
    pq.push((h(start), 0, start))
    while not pq.empty():
        f, g, u = pq.pop()
        if done[u]:
            continue
        done[u] = True
        expanded += 1
        if u == end:
            break
        p = graph.adj[u].head
        while p is not None:
            v = p.city
            if not done[v] and (forbidden is None or v not in forbidden
                                or v == start or v == end):
                ng = g + p.dist
                if ng < dist[v]:
                    dist[v] = ng
                    prev[v] = u
                    pq.push((ng + h(v), ng, v))
            p = p.next
    if stats is not None:
        stats.append(expanded)
    if dist[end] >= INF:
        return None, None
    path = []
    cur = end
    while cur != -1:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path, dist[end]


def _path_cost(graph, path, mode="km"):
    total = 0
    for i in range(len(path) - 1):
        u = path[i]
        v = path[i + 1]
        w = graph.get_weight(u, v) if mode == "km" else graph.get_fee(u, v)
        if w > 0:
            total += w
    return total


def k_shortest_paths(graph, start, end, k=3, mode="km", forbidden=None):
    if k <= 0:
        return [], []
    first, cost = dijkstra(graph, start, end, forbidden=forbidden, mode=mode)
    if first is None:
        return [], []
    paths = [first]
    costs = [cost]
    cand = []
    heap = MinHeap()
    seen = set()
    seen.add(tuple(first))
    while len(paths) < k:
        last = paths[-1]
        for i in range(len(last) - 1):
            spur = last[i]
            root = last[:i + 1]
            ban_edges = set()
            for p in paths:
                if len(p) > i + 1 and p[:i + 1] == root:
                    ban_edges.add((p[i], p[i + 1]))
            for _c, bp in cand:
                if len(bp) > i + 1 and bp[:i + 1] == root:
                    ban_edges.add((bp[i], bp[i + 1]))
            ban_nodes = set(root[:-1])
            if forbidden:
                ban_nodes |= set(forbidden)
            spur_path, _sc = dijkstra(graph, spur, end, forbidden=ban_nodes,
                                      mode=mode, forbidden_edges=ban_edges)
            if spur_path is None:
                continue
            full = root[:-1] + spur_path
            tup = tuple(full)
            if tup in seen:
                continue
            seen.add(tup)
            cand.append((_path_cost(graph, full, mode), full))
            heap.push((cand[-1][0], len(cand) - 1))
        if heap.empty():
            break
        c, idx = heap.pop()
        paths.append(cand[idx][1])
        costs.append(c)
    return paths, costs


def best_via_order(cost, start=0, end=None):
    n = len(cost)
    if n == 0:
        return [], 0
    if end is None:
        end = n - 1
    if not (0 <= start < n) or not (0 <= end < n):
        return [], 0
    mids = [i for i in range(n) if i != start and i != end]
    if len(mids) == 0:
        return [], cost[start][end] if n >= 2 else 0
    best = [10 ** 18, None]
    used = [False] * n
    used[start] = True
    used[end] = True
    order = []

    def dfs(cur, total):
        # 下界：已走里程 + 当前位置直达终点的最短里程（途经点越多只会更远）
        if total + cost[cur][end] >= best[0]:
            return
        if len(order) == len(mids):
            best[0] = total + cost[cur][end]
            best[1] = list(order)
            return
        for v in mids:
            if used[v]:
                continue
            used[v] = True
            order.append(v)
            dfs(v, total + cost[cur][v])
            order.pop()
            used[v] = False

    dfs(start, 0)
    return best[1], best[0]


def via_cost_matrix(graph, nodes, mode="km", forbidden=None):
    """途经点排序代价矩阵：对 nodes 中每个城市各做一次单源最短路，
    直接取回全部两两距离，n 次运行构建 n×n 矩阵（替代 n² 次两两 Dijkstra）。

    返回 (矩阵, bad)：全部可达时 bad 为 None；存在不可达城市对时
    矩阵为 None、bad 为 (起点下标, 终点下标) 的城市对。
    空输入返回空矩阵；含越界下标时按非法城市对安全返回。
    """
    n = len(nodes)
    if n == 0:
        return [], None
    for x in nodes:
        if not (0 <= x < graph.n):
            return None, (nodes[0], nodes[0])
    INF = 10 ** 9
    mat = [[0] * n for _ in range(n)]
    for i in range(n):
        row = dijkstra_all(graph, nodes[i], mode, forbidden)
        for j in range(n):
            if i == j:
                continue
            if row[nodes[j]] >= INF:
                return None, (nodes[i], nodes[j])
            mat[i][j] = row[nodes[j]]
    return mat, None


def bfs_min_stops(graph, start, end, forbidden=None):
    n = graph.n
    if not (0 <= start < n) or not (0 <= end < n):
        return None, None
    visited = [False] * n
    parent = [-1] * n
    q = Queue()
    visited[start] = True
    q.push(start)
    while not q.empty():
        u = q.pop()
        if u == end:
            break
        p = graph.adj[u].head
        while p is not None:
            v = p.city
            if not visited[v] and (forbidden is None or v not in forbidden
                                   or v == start or v == end):
                visited[v] = True
                parent[v] = u
                q.push(v)
            p = p.next
    if not visited[end]:
        return None, None
    path = []
    cur = end
    while cur != -1:
        path.append(cur)
        cur = parent[cur]
    path.reverse()
    return path, len(path) - 1


def prim_mst(graph):
    n = graph.n
    if n == 0:
        return None, None
    INF = 10 ** 9
    in_tree = [False] * n
    dist = [INF] * n
    dist[0] = 0
    pq = MinHeap()
    pq.push((0, 0, -1))
    mst_edges = []
    total = 0
    while not pq.empty():
        w, u, fr = pq.pop()
        if in_tree[u]:
            continue
        in_tree[u] = True
        total += w
        if fr != -1:
            if u < fr:
                mst_edges.append((u, fr))
            else:
                mst_edges.append((fr, u))
        p = graph.adj[u].head
        while p is not None:
            v = p.city
            ww = p.dist
            if not in_tree[v] and ww < dist[v]:
                dist[v] = ww
                pq.push((ww, v, u))
            p = p.next
    for i in range(n):
        if not in_tree[i]:
            return None, None
    return mst_edges, total


def estimate_time(km, stops):
    km = max(0.0, float(km))
    stops = max(0, int(stops))
    hours = km / 90.0 + stops * (10.0 / 60.0)
    h = int(hours)
    m = int((hours - h) * 60.0 + 0.5)
    if m >= 60:
        h += 1
        m -= 60
    if h <= 0:
        return "%d 分钟" % m
    return "%d 小时 %d 分钟" % (h, m)
