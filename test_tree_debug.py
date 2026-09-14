#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
带调试信息的测试版本
"""

import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QLabel, QPushButton
)

def test_treeview():
    app = QApplication(sys.argv)

    # 创建主窗口
    window = QMainWindow()
    window.setWindowTitle("TreeView 调试测试")
    window.resize(800, 600)

    # 创建中心部件
    central = QWidget()
    window.setCentralWidget(central)

    # 创建布局
    layout = QVBoxLayout()
    central.setLayout(layout)

    # 添加标签（测试布局）
    label = QLabel("如果你能看到这个标签，说明布局正常")
    label.setStyleSheet("background-color: yellow; padding: 10px;")
    layout.addWidget(label)

    # 添加按钮（测试控件）
    btn = QPushButton("这是一个按钮")
    btn.setStyleSheet("background-color: lightblue; padding: 10px;")
    layout.addWidget(btn)

    # 创建树形视图
    tree = QTreeWidget()
    tree.setHeaderLabels(["名称", "大小"])
    tree.setStyleSheet("background-color: white; border: 2px solid black;")

    # 添加测试数据
    for i in range(5):
        item = QTreeWidgetItem()
        item.setText(0, f"文件夹 {i+1}")
        item.setText(1, f"{(i+1)*100} MB")
        tree.addTopLevelItem(item)

    # 添加到布局
    layout.addWidget(tree)

    # 调试信息
    print("=== 调试信息 ===")
    print(f"Tree 控件创建: {tree}")
    print(f"Tree 父级: {tree.parent()}")
    print(f"Tree 是否可见: {tree.isVisible()}")
    print(f"Tree 几何尺寸: {tree.geometry()}")
    print(f"Tree 大小策略: {tree.sizePolicy()}")
    print(f"Tree 项数: {tree.topLevelItemCount()}")
    print(f"Layout 控件数: {layout.count()}")
    print(f"Central 控件: {central}")
    print(f"Central 布局: {central.layout()}")

    # 显示窗口
    window.show()

    print("\n窗口已显示，请检查屏幕")
    print(f"窗口几何: {window.geometry()}")
    print(f"窗口可见: {window.isVisible()}")

    sys.exit(app.exec())

if __name__ == "__main__":
    test_treeview()