#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试矩形树图组件
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QPushButton
from PyQt6.QtCore import Qt

sys.path.insert(0, str(Path(__file__).parent))
from ui.treemap_widget import TreemapWidget
from core.scanner import DiskScanner


def test_treemap():
    app = QApplication(sys.argv)

    # 创建主窗口
    window = QMainWindow()
    window.setWindowTitle("矩形树图测试")
    window.resize(800, 600)

    central = QWidget()
    window.setCentralWidget(central)
    layout = QVBoxLayout()
    central.setLayout(layout)

    # 添加标签
    label = QLabel("矩形树图应该显示在下方")
    layout.addWidget(label)

    # 创建矩形树图组件
    treemap = TreemapWidget()
    treemap.setMinimumHeight(400)
    layout.addWidget(treemap, 1)

    # 添加按钮（用于测试数据）
    btn = QPushButton("加载测试数据")
    layout.addWidget(btn)

    # 测试数据加载
    def load_test_data():
        print("加载测试数据...")
        scanner = DiskScanner(skip_system_dirs=True)
        test_path = Path(__file__).parent
        root_node = scanner.scan(str(test_path), depth=1)

        if root_node:
            print(f"扫描成功: {root_node.name}")
            print(f"子项数: {len(root_node.children)}")
            for name, child in root_node.children.items():
                print(f"  - {name}: {child.size} bytes")

            treemap.set_data(root_node)
            print("数据已设置到 TreemapWidget")
        else:
            print("扫描失败")

    btn.clicked.connect(load_test_data)

    print("窗口已创建，点击按钮加载测试数据")
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    test_treemap()