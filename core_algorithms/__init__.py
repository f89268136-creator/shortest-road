"""
核心算法模块

本包实现路网系统使用的核心算法，分为两个文件：
  · algorithms.py 图与组合优化算法：Dijkstra（里程/过路费、禁行城市、禁用边）、
                  单源最短路 dijkstra_all 与途经点代价矩阵 via_cost_matrix、
                  A* 启发式搜索、Yen K 条最短路径（备选路线）、
                  途经点最优排序（回溯 + 剪枝）、BFS 最少经停、Prim 最小生成树、
                  车程估算辅助函数
  · geometry.py   计算几何与视图变换：墨卡托投影、缩放/平移/重置视图、
                  折线去重与平滑（Chaikin / Catmull-Rom）、Douglas-Peucker 抽稀、
                  大圆距离与直线里程估算、点到折线距离、
                  均匀网格空间索引（悬停拾取最近折线）
"""
