#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试矩形树图改进
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent))
from ui.simple_treemap import SimpleTreemapWidget
from core.scanner import DiskScanner


def test_improvements():
    """测试改进后的矩形树图"""
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("矩形树图改进测试")
    window.resize(1000, 700)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout()
    central.setLayout(layout)

    # 说明标签
    label = QLabel("测试改进项:\n1. 单个项目应该显示为正方形\n2. 多个项目的矩形应该更接近正方形\n3. 文本应该根据矩形大小自适应\n4. 颜色应该更丰富和鲜明")
    layout.addWidget(label)

    # 矩形树图
    treemap = SimpleTreemapWidget()
    layout.addWidget(treemap, 1)

    # 加载测试数据
    scanner = DiskScanner(skip_system_dirs=True)
    test_path = Path(__file__).parent
    root = scanner.scan(str(test_path), depth=2)

    if root:
        print(f"OK - 扫描成功: {root.name}, 子项: {len(root.children)}")

        # 测试单项目情况
        if len(root.children) == 1:
            print("OK - 测试单项目布局")

        treemap.set_data(root)
        print(f"OK - 数据已设置，矩形数: {len(treemap.rects)}")

        # 检查矩形形状
        for i, rect in enumerate(treemap.rects[:5]):
            aspect_ratio = rect['width'] / rect['height'] if rect['height'] > 0 else 0
            print(f"  矩形 {i+1}: {rect['name']}, 宽高比: {aspect_ratio:.2f}")
    else:
        print("ERROR - 扫描失败")

    window.show()
    print("\n程序已启动，请查看矩形形状和文本显示")

    sys.exit(app.exec())


if __name__ == "__main__":
    test_improvements()