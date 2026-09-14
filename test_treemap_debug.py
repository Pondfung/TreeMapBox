#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
详细调试版本 - 矩形树图
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton, QTextEdit
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QColor

sys.path.insert(0, str(Path(__file__).parent))
from core.scanner import DiskScanner, FileNode


class SimpleTreemap(QWidget):
    """最简单的矩形树图实现"""

    def __init__(self):
        super().__init__()
        self.data = None
        self.rects = []
        self.setMinimumSize(400, 300)

        # 添加背景色，方便看到控件
        self.setStyleSheet("background-color: #f0f0f0; border: 2px solid red;")

    def set_data(self, node):
        """设置数据"""
        self.data = node
        print(f"[SimpleTreemap] set_data called: {node.name if node else None}")
        print(f"[SimpleTreemap] children: {len(node.children) if node else 0}")
        self._calculate()
        self.update()

    def _calculate(self):
        """计算矩形"""
        if not self.data:
            return

        print(f"[SimpleTreemap] _calculate - window size: {self.width()}x{self.height()}")

        if self.width() == 0 or self.height() == 0:
            print("[SimpleTreemap] Size is 0, skipping calculation")
            return

        # 简单的切片布局
        self.rects = []
        x = 0
        y = 0
        width = self.width()
        height = self.height()

        total_size = self.data.size if self.data.size > 0 else 1

        for name, child in self.data.children.items():
            if child.size > 0:
                ratio = child.size / total_size
                rect_width = int(width * ratio)

                if rect_width > 0:
                    self.rects.append({
                        'x': x,
                        'y': y,
                        'width': rect_width,
                        'height': height,
                        'name': name,
                        'size': child.size
                    })
                    x += rect_width

        print(f"[SimpleTreemap] Calculated {len(self.rects)} rects")

    def paintEvent(self, event):
        """绑定绘制"""
        print(f"[SimpleTreemap] paintEvent called, rects: {len(self.rects)}")

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 绘制背景
        painter.fillRect(self.rect(), QColor(255, 255, 255))

        # 绘制矩形
        colors = [
            QColor(100, 181, 246),  # 蓝
            QColor(129, 199, 132),  # 绿
            QColor(255, 213, 79),   # 黄
            QColor(239, 83, 80),    # 红
        ]

        for i, rect in enumerate(self.rects):
            color = colors[i % len(colors)]
            painter.fillRect(
                rect['x'], rect['y'],
                rect['width'], rect['height'],
                color
            )

            # 绘制文本
            if rect['width'] > 50:
                painter.drawText(
                    rect['x'] + 5,
                    rect['y'] + 20,
                    f"{rect['name']}"
                )

        print(f"[SimpleTreemap] Painted {len(self.rects)} rectangles")


def test():
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("矩形树图调试")
    window.resize(800, 600)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout()
    central.setLayout(layout)

    # 标签
    label = QLabel("红色边框内应该显示矩形")
    layout.addWidget(label)

    # 矩形树图
    treemap = SimpleTreemap()
    layout.addWidget(treemap, 1)

    # 日志区域
    log = QTextEdit()
    log.setMaximumHeight(100)
    layout.addWidget(log)

    # 按钮
    btn = QPushButton("加载测试数据")
    layout.addWidget(btn)

    def load_data():
        log.append("开始扫描...")
        scanner = DiskScanner(skip_system_dirs=True)
        test_path = Path(__file__).parent
        root = scanner.scan(str(test_path), depth=1)

        if root:
            log.append(f"扫描成功: {root.name}, 子项: {len(root.children)}")
            treemap.set_data(root)
            log.append(f"数据已设置，矩形数: {len(treemap.rects)}")
        else:
            log.append("扫描失败")

    btn.clicked.connect(load_data)

    print("程序启动")
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    test()