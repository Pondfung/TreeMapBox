#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试右键菜单功能
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent))
from ui.simple_treemap import SimpleTreemapWidget
from core.scanner import DiskScanner


def test_right_click():
    """测试右键菜单功能"""
    app = QApplication(sys.argv)

    window = QMainWindow()
    window.setWindowTitle("右键菜单功能测试")
    window.resize(1000, 700)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout()
    central.setLayout(layout)

    # 说明标签
    label = QLabel("测试步骤:\n1. 右键点击任意矩形\n2. 查看 '复制路径'、'在资源管理器打开'、'在树形列表显示' 菜单项\n3. 测试各项功能")
    layout.addWidget(label)

    # 矩形树图
    treemap = SimpleTreemapWidget()
    layout.addWidget(treemap, 1)

    # 加载测试数据
    scanner = DiskScanner(skip_system_dirs=True)
    test_path = Path(__file__).parent
    root = scanner.scan(str(test_path), depth=2)

    if root:
        print(f"扫描成功: {root.name}, 子项: {len(root.children)}")
        treemap.set_data(root)
        print(f"矩形数: {len(treemap.rects)}")
        print("\n右键菜单功能已添加:")
        print("  1. 复制路径")
        print("  2. 在资源管理器中打开")
        print("  3. 在树形列表中显示")
    else:
        print("扫描失败")

    window.show()
    print("\n程序已启动，请测试右键菜单功能")

    sys.exit(app.exec())


if __name__ == "__main__":
    test_right_click()