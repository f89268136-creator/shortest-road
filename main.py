"""
程序入口 —— 启动城市路网规划系统

职责：
  · 设置进程 DPI 感知，保证高分屏下窗口与截图清晰
  · 创建 Tk 根窗口，装配 GUI 主界面（gui_app.gui.App）
  · 支持通过命令行参数临时指定百度地图 AK（python main.py <AK>）
  · 进入 Tk 事件主循环

模块划分：
  basic_data/       基础数据定义模块（静态数据集 + 百度真实路网获取与缓存，
                    缓存读取时逐条做数据合法性校验）
  data_structures/  数据结构模块（单链表、链式队列、二叉堆、顺序栈、
                    二叉搜索树、图及其增删改查，双栈撤销/重做历史）
  core_algorithms/  核心算法模块（Dijkstra / A* / Yen K 短路 / BFS / Prim、
                   单源最短路代价矩阵与计算几何、空间索引；入口均做边界检查）
  gui_app/          GUI 界面模块（主界面 gui.py）
"""

import ctypes
import sys

import tkinter as tk

from basic_data import data
from data_structures import structures
from gui_app import gui


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    ak = data.BAIDU_AK
    if len(sys.argv) > 1:
        ak = sys.argv[1]
    root = tk.Tk()
    app = gui.App(root, structures.Graph(0), ak)
    root.mainloop()


if __name__ == "__main__":
    main()
