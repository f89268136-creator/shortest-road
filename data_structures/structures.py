"""
数据结构及其内部增删改查方法实现模块

本文件以类实现系统用到的六种数据结构，每种结构都包含各自的增删改查方法：
  · LinkedList     单链表（邻接表的边结点存储：insert_head / find / delete / size）
  · Queue          链式队列（BFS 用：push / pop / empty / size）
  · MinHeap        二叉堆（优先队列，Dijkstra/Prim/A* 用：push / pop / sift_down）
  · Stack          顺序栈（撤销/重做双栈与树的中序、前缀后继遍历用：push / pop / top 等）
  · BinSearchTree  二叉搜索树（城市名→下标索引：insert / search / keys / prefix，
                   支持 O(log n) 精确查找与 O(log n + k) 前缀区间检索）
  · Graph          无向带权图（邻接表存储：set_edge / delete_edge / edges_between /
                   degree / total_km / total_fee / is_connected / adjacency_text 等）
另提供：
  · EditHistory    基于两个栈的撤销/重做历史管理器（业务层记录入栈，本类只管顺序）
  · build_graph()  由基础数据模块的城市与公路表构建整张路网图
                   （构建时做数据合法性校验：越界下标、重名城市、非法里程/费用）
"""

from basic_data.data import CITIES, ROADS


class LinkedListNode:
    __slots__ = ("city", "dist", "fee", "kind", "next")

    def __init__(self, city, dist, fee=0, kind="免费", next=None):
        self.city = city
        self.dist = dist
        self.fee = fee
        self.kind = kind
        self.next = next


class LinkedList:
    def __init__(self):
        self.head = None

    def insert_head(self, city, dist, fee=0, kind="免费"):
        self.head = LinkedListNode(city, dist, fee, kind, self.head)

    def find(self, city):
        p = self.head
        while p is not None:
            if p.city == city:
                return p
            p = p.next
        return None

    def delete(self, city):
        if self.head is None:
            return False
        if self.head.city == city:
            self.head = self.head.next
            return True
        p = self.head
        while p.next is not None and p.next.city != city:
            p = p.next
        if p.next is None:
            return False
        p.next = p.next.next
        return True

    def size(self):
        n = 0
        p = self.head
        while p is not None:
            n += 1
            p = p.next
        return n


class QueueNode:
    __slots__ = ("val", "next")

    def __init__(self, val, nxt=None):
        self.val = val
        self.next = nxt


class Queue:
    def __init__(self):
        self.head = None
        self.tail = None

    def empty(self):
        return self.head is None

    def push(self, v):
        node = QueueNode(v)
        if self.tail is None:
            self.head = node
            self.tail = node
        else:
            self.tail.next = node
            self.tail = node

    def pop(self):
        if self.head is None:
            return None
        v = self.head.val
        self.head = self.head.next
        if self.head is None:
            self.tail = None
        return v

    def size(self):
        n = 0
        p = self.head
        while p is not None:
            n += 1
            p = p.next
        return n


class MinHeap:
    def __init__(self):
        self.a = []

    def empty(self):
        return len(self.a) == 0

    def _less(self, i, j):
        x, y = self.a[i], self.a[j]
        return x[0] < y[0] or (x[0] == y[0] and x[1] < y[1])

    def push(self, item):
        self.a.append(item)
        i = len(self.a) - 1
        while i > 0:
            parent = (i - 1) // 2
            if self._less(i, parent):
                self.a[i], self.a[parent] = self.a[parent], self.a[i]
                i = parent
            else:
                break

    def pop(self):
        top = self.a[0]
        last = self.a.pop()
        if len(self.a) > 0:
            self.a[0] = last
            self._sift_down(0)
        return top

    def _sift_down(self, i):
        n = len(self.a)
        while True:
            left = 2 * i + 1
            right = 2 * i + 2
            smallest = i
            if left < n and self._less(left, smallest):
                smallest = left
            if right < n and self._less(right, smallest):
                smallest = right
            if smallest == i:
                break
            self.a[i], self.a[smallest] = self.a[smallest], self.a[i]
            i = smallest


class Stack:
    """顺序栈：后进先出。用于撤销/重做双栈，以及树的中序/后继迭代遍历。"""

    def __init__(self):
        self.a = []

    def empty(self):
        return len(self.a) == 0

    def push(self, item):
        self.a.append(item)

    def pop(self):
        if len(self.a) == 0:
            return None
        return self.a.pop()

    def top(self):
        if len(self.a) == 0:
            return None
        return self.a[-1]

    def size(self):
        return len(self.a)

    def clear(self):
        self.a.clear()


class BinSearchTreeNode:
    __slots__ = ("key", "val", "left", "right")

    def __init__(self, key, val):
        self.key = key
        self.val = val
        self.left = None
        self.right = None


class BinSearchTree:
    """二叉搜索树：键为字符串（城市名），值为任意数据（城市下标）。

    · insert / search  精确查找 O(log n)（最坏 O(n)）
    · keys             用显式栈做非递归中序遍历，得到按键升序的 (key, val) 列表
    · prefix           前缀区间检索：先沿 BST 定位“大于等于前缀的最小结点”，
                       再用栈模拟中序后继依次收集所有以该前缀开头的键，
                       复杂度 O(log n + k)；无匹配时返回空列表
    """

    def __init__(self):
        self.root = None
        self.count = 0

    def size(self):
        return self.count

    def insert(self, key, val):
        if self.root is None:
            self.root = BinSearchTreeNode(key, val)
            self.count += 1
            return True
        node = self.root
        while True:
            if key == node.key:
                node.val = val
                return False
            if key < node.key:
                if node.left is None:
                    node.left = BinSearchTreeNode(key, val)
                    self.count += 1
                    return True
                node = node.left
            else:
                if node.right is None:
                    node.right = BinSearchTreeNode(key, val)
                    self.count += 1
                    return True
                node = node.right

    def search(self, key):
        node = self.root
        while node is not None:
            if key == node.key:
                return node.val
            node = node.left if key < node.key else node.right
        return None

    def keys(self):
        res = []
        st = Stack()
        node = self.root
        while node is not None or not st.empty():
            while node is not None:
                st.push(node)
                node = node.left
            node = st.pop()
            res.append((node.key, node.val))
            node = node.right
        return res

    def prefix(self, prefix):
        if prefix == "":
            return self.keys()
        res = []
        st = Stack()
        node = self.root
        # 定位第一个键 >= prefix 的结点，沿途所有 >= prefix 的结点入栈，
        # 栈顶即为中序遍历中第一个待收集的结点
        while node is not None:
            if node.key >= prefix:
                st.push(node)
                node = node.left
            else:
                node = node.right
        # 以 prefix + 最大字符 为上界：所有以 prefix 开头的键都小于它
        hi = prefix + chr(0x10FFFF)
        while not st.empty():
            node = st.pop()
            if node.key >= hi:
                break
            if node.key.startswith(prefix):
                res.append((node.key, node.val))
            nxt = node.right
            while nxt is not None:
                st.push(nxt)
                nxt = nxt.left
        return res


class EditHistory:
    """基于两个栈的撤销/重做管理器：撤销栈 + 重做栈。

    业务层执行新操作后 push(rec)；undo()/redo() 只负责把记录从一个栈
    搬到另一个栈并返回给调用方，由调用方执行具体的正向/逆向操作。
    push 新记录会清空重做栈（经典"撤销→新操作即切断重做链"模型）。
    """

    def __init__(self):
        self._undo = Stack()
        self._redo = Stack()

    def push(self, rec):
        self._undo.push(rec)
        self._redo.clear()

    def undo(self):
        if self._undo.empty():
            return None
        rec = self._undo.pop()
        self._redo.push(rec)
        return rec

    def redo(self):
        if self._redo.empty():
            return None
        rec = self._redo.pop()
        self._undo.push(rec)
        return rec

    def can_undo(self):
        return not self._undo.empty()

    def can_redo(self):
        return not self._redo.empty()

    def clear(self):
        self._undo.clear()
        self._redo.clear()


class Graph:
    def __init__(self, n):
        self.n = n
        self.adj = [LinkedList() for _ in range(n)]
        self.edge_num = 0
        self.warnings = []

    def set_edge(self, u, v, w, fee=0, kind="免费"):
        # 边界检查：下标越界（负数下标会静默绕回队尾，必须显式拒绝）、
        # 自环、非正里程、负费用一律拒绝，返回 False 表示未加边
        if not isinstance(u, int) or not isinstance(v, int):
            return False
        if not (0 <= u < self.n) or not (0 <= v < self.n):
            return False
        if u == v or w <= 0 or fee < 0:
            return False
        self.adj[u].insert_head(v, w, fee, kind)
        self.adj[v].insert_head(u, w, fee, kind)
        self.edge_num += 1
        return True

    def edges_between(self, u, v):
        res = []
        p = self.adj[u].head
        while p is not None:
            if p.city == v:
                res.append(p.dist)
            p = p.next
        return res

    def delete_edge(self, u, v):
        if u == v:
            return False
        if self.adj[u].delete(v):
            self.adj[v].delete(u)
            self.edge_num -= 1
            return True
        return False

    def adjacency_text(self):
        rows = []
        for i in range(self.n):
            seg = []
            p = self.adj[i].head
            while p is not None:
                seg.append("%s(%d公里/费%d)" % (CITIES[p.city][0], p.dist, p.fee))
                p = p.next
            rows.append("%s（直达%d条）→ %s" % (CITIES[i][0], self.degree(i), "、".join(seg)))
        return "\n".join(rows)

    def get_weight(self, u, v):
        ds = self.edges_between(u, v)
        if len(ds) == 0:
            return -1
        best = ds[0]
        for d in ds:
            if d < best:
                best = d
        return best

    def get_fee(self, u, v):
        best = -1
        p = self.adj[u].head
        while p is not None:
            if p.city == v and (best < 0 or p.fee < best):
                best = p.fee
            p = p.next
        return best

    def fees_between(self, u, v):
        res = []
        p = self.adj[u].head
        while p is not None:
            if p.city == v:
                res.append(p.fee)
            p = p.next
        return res

    def degree(self, i):
        return self.adj[i].size()

    def total_km(self):
        total = 0
        for u in range(self.n):
            p = self.adj[u].head
            while p is not None:
                if u < p.city:
                    total += p.dist
                p = p.next
        return total

    def total_fee(self):
        total = 0
        for u in range(self.n):
            p = self.adj[u].head
            while p is not None:
                if u < p.city:
                    total += p.fee
                p = p.next
        return total

    def is_connected(self):
        n = self.n
        if n == 0:
            return True
        visited = [False] * n
        q = Queue()
        visited[0] = True
        q.push(0)
        while not q.empty():
            u = q.pop()
            p = self.adj[u].head
            while p is not None:
                v = p.city
                if not visited[v]:
                    visited[v] = True
                    q.push(v)
                p = p.next
        for i in range(n):
            if not visited[i]:
                return False
        return True


def build_graph():
    """由城市表与公路表构建路网图，同时做数据合法性校验：
    重名城市、引用不存在城市的公路、里程/费用非法或类型错误的公路
    都会被跳过并记入 graph.warnings（状态栏展示），保证图上数据一致。"""
    g = Graph(len(CITIES))
    pos = {}
    for i in range(len(CITIES)):
        name = CITIES[i][0]
        if name in pos:
            g.warnings.append("城市 %s 重复定义（下标 %d 已忽略，保留下标 %d）"
                              % (name, i, pos[name]))
        else:
            pos[name] = i
    for r in ROADS:
        if len(r) < 3:
            g.warnings.append("公路记录格式非法（%r），已忽略" % (r,))
            continue
        a, b = r[0], r[1]
        km = r[2]
        fee = r[3] if len(r) > 3 else 0
        if not isinstance(km, (int, float)) or not isinstance(fee, (int, float)):
            g.warnings.append("公路 %s — %s 的里程(%r)/费用(%r)类型非法，已忽略"
                              % (a, b, km, fee))
            continue
        ia = pos.get(a)
        ib = pos.get(b)
        if ia is None or ib is None:
            g.warnings.append("公路 %s — %s 引用了不存在的城市，已忽略" % (a, b))
            continue
        if km <= 0 or fee < 0:
            g.warnings.append("公路 %s — %s 的里程(%s)/费用(%s)非法，已忽略"
                              % (a, b, km, fee))
            continue
        g.set_edge(ia, ib, km, fee, "高速" if fee > 0 else "免费")
    return g
